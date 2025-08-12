"""
Execution Engine Client for Gleitzeit V5

Distributed execution component that handles task execution coordination,
provider communication, and result management through pure Socket.IO events.
"""

import asyncio
import logging
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import uuid

from ..base.component import SocketIOComponent
from ..base.config import ComponentConfig
from ..core.protocol import get_protocol_registry, ProtocolSpec
from ..core.jsonrpc import JSONRPCRequest, JSONRPCResponse
from ..protocols import LLM_PROTOCOL_V1, PYTHON_PROTOCOL_V1

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task execution status"""
    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionTask:
    """Represents a task being executed"""
    task_id: str
    workflow_id: str
    task_type: str
    method: str
    parameters: Dict[str, Any]
    priority: int
    correlation_id: str
    started_at: datetime
    status: TaskStatus = TaskStatus.QUEUED
    assigned_provider: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class ProviderInfo:
    """Information about available providers"""
    provider_id: str
    protocol: str
    capabilities: List[str]
    last_seen: datetime
    active_tasks: int = 0
    success_rate: float = 1.0
    avg_response_time_ms: float = 0.0


class ExecutionEngineClient(SocketIOComponent):
    """
    Execution Engine Client for distributed task execution
    
    Responsibilities:
    - Receive ready tasks from QueueManager
    - Route tasks to appropriate providers based on protocol and capabilities
    - Coordinate parameter resolution with DependencyResolver
    - Monitor task execution and handle failures
    - Report task results back to QueueManager and DependencyResolver
    - Manage provider health and load balancing
    
    Events Emitted:
    - execute_task: Send task to provider for execution
    - task_completed: Notify completion to other components
    - task_failed: Notify failure to other components
    - provider_health_check: Check provider availability
    - execution_stats_updated: Report execution statistics
    
    Events Handled:
    - task_ready_for_execution: Receive ready task from QueueManager
    - task_execution_result: Receive execution result from provider
    - task_execution_error: Receive execution error from provider
    - provider_registered: Track new provider availability
    - provider_disconnected: Handle provider disconnection
    - cancel_task: Cancel running task
    """
    
    def __init__(
        self,
        component_id: Optional[str] = None,
        config: Optional[ComponentConfig] = None,
        hub_url: str = "http://localhost:8000"
    ):
        if config is None:
            config = ComponentConfig()
        config.hub_url = hub_url
        
        super().__init__(
            component_type="execution_engine",
            component_id=component_id or f"engine-{uuid.uuid4().hex[:8]}",
            config=config
        )
        
        # Task tracking
        self.executing_tasks: Dict[str, ExecutionTask] = {}  # task_id -> task
        self.task_queue: List[ExecutionTask] = []  # Priority queue for waiting tasks
        
        # Provider tracking
        self.available_providers: Dict[str, ProviderInfo] = {}  # provider_id -> info
        self.protocol_providers: Dict[str, List[str]] = {}  # protocol -> [provider_ids]
        
        # Load balancing
        self.provider_round_robin: Dict[str, int] = {}  # protocol -> index
        
        # Statistics
        self.stats = {
            'tasks_executed': 0,
            'tasks_completed': 0,
            'tasks_failed': 0,
            'tasks_cancelled': 0,
            'tasks_retried': 0,
            'average_execution_time_ms': 0.0,
            'providers_available': 0
        }
        
        # Execution history for calculating averages
        self.execution_times: List[float] = []
        self.max_history = 1000
        
        # Protocol registry
        self.protocol_registry = get_protocol_registry()
        
        # Register standard protocols
        self.protocol_registry.register(LLM_PROTOCOL_V1)
        self.protocol_registry.register(PYTHON_PROTOCOL_V1)
        
        logger.info(f"Initialized Execution Engine: {self.component_id}")
    
    def setup_events(self):
        """Setup event handlers for task execution"""
        
        @self.sio.on('task_ready_for_execution')
        async def handle_task_ready(data):
            """Handle ready task from Queue Manager"""
            try:
                task = ExecutionTask(
                    task_id=data['task_id'],
                    workflow_id=data['workflow_id'],
                    task_type=data.get('task_type', 'generic'),
                    method=data['method'],
                    parameters=data.get('parameters', {}),
                    priority=data.get('priority', 2),
                    correlation_id=data.get('_correlation_id', str(uuid.uuid4())),
                    started_at=datetime.utcnow()
                )
                
                await self._queue_task_for_execution(task)
                
            except Exception as e:
                logger.error(f"Error handling task_ready_for_execution: {e}")
        
        @self.sio.on('task_execution_result')
        async def handle_execution_result(data):
            """Handle execution result from provider"""
            try:
                task_id = data['task_id']
                result = data['result']
                execution_time = data.get('execution_time_ms', 0)
                
                await self._handle_task_success(task_id, result, execution_time)
                
            except Exception as e:
                logger.error(f"Error handling task_execution_result: {e}")
        
        @self.sio.on('task_execution_error')
        async def handle_execution_error(data):
            """Handle execution error from provider"""
            try:
                task_id = data['task_id']
                error = data.get('error', 'Unknown execution error')
                retryable = data.get('retryable', True)
                
                await self._handle_task_failure(task_id, error, retryable)
                
            except Exception as e:
                logger.error(f"Error handling task_execution_error: {e}")
        
        @self.sio.on('provider_registered')
        async def handle_provider_registered(data):
            """Handle new provider registration"""
            try:
                provider_info = ProviderInfo(
                    provider_id=data['component_id'],
                    protocol=data.get('protocol', 'generic'),
                    capabilities=data.get('capabilities', []),
                    last_seen=datetime.utcnow()
                )
                
                await self._register_provider(provider_info)
                
            except Exception as e:
                logger.error(f"Error handling provider_registered: {e}")
        
        @self.sio.on('component_disconnected')
        async def handle_component_disconnected(data):
            """Handle component disconnection (including providers)"""
            try:
                component_id = data['component_id']
                component_type = data.get('component_type', '')
                
                if component_type == 'provider' or component_id in self.available_providers:
                    await self._unregister_provider(component_id)
                
            except Exception as e:
                logger.error(f"Error handling component_disconnected: {e}")
        
        @self.sio.on('cancel_task')
        async def handle_cancel_task(data):
            """Handle task cancellation request"""
            try:
                task_id = data['task_id']
                reason = data.get('reason', 'Task cancelled')
                
                await self._cancel_task(task_id, reason)
                
            except Exception as e:
                logger.error(f"Error handling cancel_task: {e}")
        
        @self.sio.on('parameter_substitution_complete')
        async def handle_parameter_substitution(data):
            """Handle completed parameter substitution"""
            try:
                task_id = data['task_id']
                resolved_parameters = data['resolved_parameters']
                
                if task_id in self.executing_tasks:
                    task = self.executing_tasks[task_id]
                    task.parameters = resolved_parameters
                    
                    # Now execute the task with resolved parameters
                    await self._execute_task(task)
                
            except Exception as e:
                logger.error(f"Error handling parameter_substitution_complete: {e}")
        
        @self.sio.on('get_execution_stats')
        async def handle_get_execution_stats(data):
            """Return execution statistics"""
            try:
                correlation_id = data.get('_correlation_id', str(uuid.uuid4()))
                
                stats = self._get_execution_statistics()
                
                await self.emit_with_correlation('execution_stats_response', {
                    'stats': stats,
                    '_response_to': correlation_id
                }, correlation_id)
                
            except Exception as e:
                logger.error(f"Error handling get_execution_stats: {e}")
    
    def get_capabilities(self) -> List[str]:
        """Return list of capabilities this component provides"""
        return ['task_execution', 'provider_coordination', 'load_balancing', 'execution_monitoring']
    
    async def on_ready(self):
        """Called when component is registered and ready"""
        logger.info(f"Execution Engine {self.component_id} is ready")
    
    async def on_shutdown(self):
        """Called during graceful shutdown for component-specific cleanup"""
        # Cancel all executing tasks
        tasks_to_cancel = list(self.executing_tasks.keys())
        for task_id in tasks_to_cancel:
            await self._cancel_task(task_id, "Execution engine shutting down")
        logger.info(f"Execution Engine {self.component_id} shutdown cleanup completed")
    
    async def _queue_task_for_execution(self, task: ExecutionTask):
        """Queue a task for execution"""
        
        # Add to executing tasks
        self.executing_tasks[task.task_id] = task
        
        # Check if task parameters need resolution
        if self._needs_parameter_resolution(task.parameters):
            # Request parameter resolution from DependencyResolver via hub routing
            await self.emit_with_correlation('route_event', {
                'target_component_type': 'dependency_resolver',
                'event_name': 'resolve_parameters',
                'event_data': {
                    'task_id': task.task_id,
                    'parameters': task.parameters
                }
            }, task.correlation_id)
        else:
            # Parameters are ready, execute immediately
            await self._execute_task(task)
        
        logger.info(f"Queued task {task.task_id} for execution")
    
    def _needs_parameter_resolution(self, parameters: Dict[str, Any]) -> bool:
        """Check if parameters contain substitution patterns"""
        
        param_str = json.dumps(parameters)
        return '${' in param_str and '}' in param_str
    
    async def _execute_task(self, task: ExecutionTask):
        """Execute a task by routing to appropriate provider"""
        
        # Validate task against protocol specification
        try:
            await self._validate_task_against_protocol(task)
        except Exception as e:
            await self._handle_task_failure(
                task.task_id,
                f"Protocol validation failed: {str(e)}",
                retryable=False
            )
            return
        
        # Find suitable provider
        provider_id = await self._select_provider_for_task(task)
        
        if not provider_id:
            await self._handle_task_failure(
                task.task_id, 
                f"No available provider for method: {task.method}",
                retryable=False
            )
            return
        
        # Update task status
        task.status = TaskStatus.EXECUTING
        task.assigned_provider = provider_id
        
        # Update provider load
        if provider_id in self.available_providers:
            self.available_providers[provider_id].active_tasks += 1
        
        # Send task to provider via event routing
        await self.emit_with_correlation('route_event', {
            'target_component_type': 'provider',
            'event_name': 'execute_task',
            'event_data': {
                'task_id': task.task_id,
                'method': task.method,
                'parameters': task.parameters,
                'workflow_id': task.workflow_id,
                'timeout_seconds': 300  # 5 minute default timeout
            }
        }, task.correlation_id)
        
        self.stats['tasks_executed'] += 1
        
        logger.info(f"Executing task {task.task_id} on provider {provider_id}")
    
    async def _select_provider_for_task(self, task: ExecutionTask) -> Optional[str]:
        """Select best provider for task execution"""
        
        # Extract protocol from method (e.g., "llm/chat" -> "llm")
        protocol = task.method.split('/')[0] if '/' in task.method else 'generic'
        
        # Get available providers for this protocol
        providers = self.protocol_providers.get(protocol, [])
        if not providers:
            # Try generic providers as fallback
            providers = self.protocol_providers.get('generic', [])
        
        if not providers:
            return None
        
        # Simple round-robin selection
        if protocol not in self.provider_round_robin:
            self.provider_round_robin[protocol] = 0
        
        index = self.provider_round_robin[protocol] % len(providers)
        self.provider_round_robin[protocol] = (index + 1) % len(providers)
        
        selected_provider = providers[index]
        
        # Verify provider is still available
        if selected_provider in self.available_providers:
            return selected_provider
        
        # Provider no longer available, remove from list
        providers.remove(selected_provider)
        return await self._select_provider_for_task(task) if providers else None
    
    async def _handle_task_success(self, task_id: str, result: Any, execution_time_ms: float):
        """Handle successful task execution"""
        
        if task_id not in self.executing_tasks:
            logger.warning(f"Received result for unknown task: {task_id}")
            return
        
        task = self.executing_tasks[task_id]
        task.status = TaskStatus.COMPLETED
        task.result = result
        task.execution_time_ms = execution_time_ms
        
        # Update provider metrics
        if task.assigned_provider and task.assigned_provider in self.available_providers:
            provider = self.available_providers[task.assigned_provider]
            provider.active_tasks = max(0, provider.active_tasks - 1)
            provider.last_seen = datetime.utcnow()
            
            # Update success rate (simple moving average)
            provider.success_rate = (provider.success_rate * 0.9) + (1.0 * 0.1)
            
            # Update average response time
            if provider.avg_response_time_ms == 0:
                provider.avg_response_time_ms = execution_time_ms
            else:
                provider.avg_response_time_ms = (
                    provider.avg_response_time_ms * 0.8 + execution_time_ms * 0.2
                )
        
        # Update statistics
        self.stats['tasks_completed'] += 1
        self.execution_times.append(execution_time_ms)
        if len(self.execution_times) > self.max_history:
            self.execution_times.pop(0)
        
        self.stats['average_execution_time_ms'] = sum(self.execution_times) / len(self.execution_times)
        
        # Broadcast task completion to all components via hub's broadcast mechanism
        await self.emit_with_correlation('task_completed', {
            'task_id': task_id,
            'workflow_id': task.workflow_id,
            'result': result,
            'execution_time_ms': execution_time_ms
        }, task.correlation_id)
        
        # Clean up
        del self.executing_tasks[task_id]
        
        logger.info(f"Task {task_id} completed successfully in {execution_time_ms:.1f}ms")
    
    async def _handle_task_failure(self, task_id: str, error: str, retryable: bool = True):
        """Handle failed task execution"""
        
        if task_id not in self.executing_tasks:
            logger.warning(f"Received failure for unknown task: {task_id}")
            return
        
        task = self.executing_tasks[task_id]
        
        # Update provider metrics
        if task.assigned_provider and task.assigned_provider in self.available_providers:
            provider = self.available_providers[task.assigned_provider]
            provider.active_tasks = max(0, provider.active_tasks - 1)
            provider.last_seen = datetime.utcnow()
            
            # Update success rate
            provider.success_rate = (provider.success_rate * 0.9) + (0.0 * 0.1)
        
        # Check if we should retry
        if retryable and task.retry_count < task.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.QUEUED
            task.assigned_provider = None
            
            self.stats['tasks_retried'] += 1
            
            logger.warning(f"Retrying task {task_id} (attempt {task.retry_count}/{task.max_retries})")
            
            # Retry after a short delay
            await asyncio.sleep(min(task.retry_count * 2, 10))  # Exponential backoff
            await self._execute_task(task)
            
            return
        
        # Final failure
        task.status = TaskStatus.FAILED
        task.error = error
        
        self.stats['tasks_failed'] += 1
        
        # Notify other components
        await self.emit_with_correlation('task_failed', {
            'task_id': task_id,
            'workflow_id': task.workflow_id,
            'error': error,
            'retry_count': task.retry_count
        }, task.correlation_id)
        
        # Clean up
        del self.executing_tasks[task_id]
        
        logger.error(f"Task {task_id} failed permanently: {error}")
    
    async def _cancel_task(self, task_id: str, reason: str):
        """Cancel a running task"""
        
        if task_id not in self.executing_tasks:
            logger.warning(f"Cannot cancel unknown task: {task_id}")
            return
        
        task = self.executing_tasks[task_id]
        task.status = TaskStatus.CANCELLED
        task.error = reason
        
        # Notify provider to cancel if it's executing
        if task.assigned_provider and task.status == TaskStatus.EXECUTING:
            await self.emit_with_correlation('route_event', {
                'target_component_type': 'provider', 
                'event_name': 'cancel_task_execution',
                'event_data': {
                    'task_id': task_id,
                    'reason': reason
                }
            }, task.correlation_id)
        
        # Update provider load
        if task.assigned_provider and task.assigned_provider in self.available_providers:
            provider = self.available_providers[task.assigned_provider]
            provider.active_tasks = max(0, provider.active_tasks - 1)
        
        self.stats['tasks_cancelled'] += 1
        
        # Clean up
        del self.executing_tasks[task_id]
        
        logger.info(f"Task {task_id} cancelled: {reason}")
    
    async def _register_provider(self, provider_info: ProviderInfo):
        """Register a new provider"""
        
        self.available_providers[provider_info.provider_id] = provider_info
        
        # Add to protocol mapping
        protocol = provider_info.protocol
        if protocol not in self.protocol_providers:
            self.protocol_providers[protocol] = []
        
        if provider_info.provider_id not in self.protocol_providers[protocol]:
            self.protocol_providers[protocol].append(provider_info.provider_id)
        
        self.stats['providers_available'] = len(self.available_providers)
        
        logger.info(f"Registered provider {provider_info.provider_id} for protocol {protocol}")
    
    async def _unregister_provider(self, provider_id: str):
        """Unregister a provider"""
        
        if provider_id not in self.available_providers:
            return
        
        provider_info = self.available_providers[provider_id]
        
        # Remove from protocol mapping
        protocol = provider_info.protocol
        if protocol in self.protocol_providers:
            if provider_id in self.protocol_providers[protocol]:
                self.protocol_providers[protocol].remove(provider_id)
            
            # Clean up empty protocol lists
            if not self.protocol_providers[protocol]:
                del self.protocol_providers[protocol]
        
        # Cancel any tasks assigned to this provider
        tasks_to_retry = []
        for task in list(self.executing_tasks.values()):
            if task.assigned_provider == provider_id and task.status == TaskStatus.EXECUTING:
                tasks_to_retry.append(task)
        
        for task in tasks_to_retry:
            task.status = TaskStatus.QUEUED
            task.assigned_provider = None
            await self._execute_task(task)
        
        del self.available_providers[provider_id]
        self.stats['providers_available'] = len(self.available_providers)
        
        logger.warning(f"Unregistered provider {provider_id}, retrying {len(tasks_to_retry)} tasks")
    
    def _get_execution_statistics(self) -> Dict[str, Any]:
        """Get comprehensive execution statistics"""
        
        provider_stats = {}
        for provider_id, provider in self.available_providers.items():
            provider_stats[provider_id] = {
                'protocol': provider.protocol,
                'active_tasks': provider.active_tasks,
                'success_rate': provider.success_rate,
                'avg_response_time_ms': provider.avg_response_time_ms,
                'capabilities': provider.capabilities
            }
        
        return {
            **self.stats,
            'executing_tasks_count': len(self.executing_tasks),
            'queued_tasks_count': len(self.task_queue),
            'protocols_supported': list(self.protocol_providers.keys()),
            'provider_details': provider_stats,
            'component_uptime_seconds': (
                datetime.utcnow() - self.health_metrics['started_at']
            ).total_seconds()
        }
    
    async def get_health_metrics(self) -> Dict[str, Any]:
        """Get health metrics for heartbeat responses"""
        return {
            'tasks_executing': len(self.executing_tasks),
            'tasks_completed': self.stats['tasks_completed'],
            'tasks_failed': self.stats['tasks_failed'],
            'providers_available': self.stats['providers_available'],
            'success_rate': (
                self.stats['tasks_completed'] / 
                max(1, self.stats['tasks_completed'] + self.stats['tasks_failed'])
            ),
            'avg_execution_time_ms': self.stats['average_execution_time_ms'],
            'status': 'healthy' if self.stats['providers_available'] > 0 else 'degraded'
        }
    
    async def _validate_task_against_protocol(self, task: ExecutionTask):
        """Validate task parameters against protocol specification"""
        
        # Extract protocol from method name (e.g., "llm/chat" -> "llm")
        protocol_name = task.method.split('/')[0] if '/' in task.method else 'generic'
        
        # Find protocol specification
        protocols = self.protocol_registry.find_by_method(task.method)
        if not protocols:
            logger.warning(f"No protocol found for method {task.method}, skipping validation")
            return
        
        # Use the first matching protocol
        protocol = protocols[0]
        
        try:
            # Validate method call against protocol
            protocol.validate_method_call(task.method, task.parameters)
            logger.debug(f"Task {task.task_id} validated against protocol {protocol.protocol_id}")
            
        except Exception as e:
            logger.error(f"Protocol validation failed for task {task.task_id}: {e}")
            raise ValueError(f"Protocol validation failed: {e}")
    


# Convenience function to run the Execution Engine
async def run_execution_engine(
    component_id: Optional[str] = None,
    config: Optional[ComponentConfig] = None,
    hub_url: str = "http://localhost:8000"
):
    """Run an Execution Engine client"""
    
    execution_engine = ExecutionEngineClient(
        component_id=component_id,
        config=config,
        hub_url=hub_url
    )
    
    await execution_engine.start()


if __name__ == "__main__":
    import sys
    
    # Parse command line arguments
    component_id = sys.argv[1] if len(sys.argv) > 1 else None
    hub_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
    
    asyncio.run(run_execution_engine(component_id=component_id, hub_url=hub_url))