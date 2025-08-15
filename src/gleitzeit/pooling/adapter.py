"""
Queue-Integrated Pooling Adapter for Gleitzeit V4

This adapter integrates the pooling system as a task executor backend
for the existing ExecutionEngine, working with the central task queue
and persistence infrastructure.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Type, Callable
from datetime import datetime

from gleitzeit.pooling.manager import PoolManager
from gleitzeit.core.events import EventType, GleitzeitEvent
from gleitzeit.core.models import Task, TaskResult, TaskStatus
from gleitzeit.core.errors import ProviderError, ErrorCode, TaskError
from gleitzeit.registry import ProtocolProviderRegistry

logger = logging.getLogger(__name__)


class PoolingAdapter:
    """
    Pooling adapter that works as a task executor backend for ExecutionEngine.
    
    Instead of creating separate task routing, this integrates with the existing
    queue system by providing an execute_task method that the ExecutionEngine
    can use instead of directly calling providers.
    """
    
    def __init__(
        self,
        registry: ProtocolProviderRegistry,
        event_emitter: Optional[Callable] = None,
        pool_manager: Optional[PoolManager] = None
    ):
        self.registry = registry
        self.event_emitter = event_emitter
        
        # Create pool manager with our event emitter
        self.pool_manager = pool_manager or PoolManager(
            event_emitter=self._emit_event
        )
        
        # Protocol to pool mapping
        self.protocol_pools: Dict[str, str] = {}  # protocol_id -> pool_id
        
        # State
        self.running = False
        
        # Statistics
        self.stats = {
            "tasks_executed": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "providers_registered": 0
        }
    
    async def start(self) -> None:
        """Start the pooling adapter"""
        if self.running:
            return
            
        self.running = True
        await self.pool_manager.start()
        
        # Auto-register all available providers from registry
        await self._register_available_providers()
        
        logger.info("PoolingAdapter started")
    
    async def stop(self) -> None:
        """Stop the pooling adapter"""
        if not self.running:
            return
            
        self.running = False
        await self.pool_manager.stop()
        
        logger.info("PoolingAdapter stopped")
    
    async def _register_available_providers(self) -> None:
        """Register all available providers from the registry"""
        # Skip auto-registration for now - registry interface is different
        # Manual registration will be done as needed
        logger.info("Skipping auto-registration - manual provider registration required")
    
    async def register_provider(
        self,
        protocol_id: str,
        provider_class: Type,
        min_workers: int = 2,
        max_workers: int = 10,
        provider_config: Optional[Dict[str, Any]] = None,
        **pool_config
    ) -> str:
        """
        Register a provider for pooled execution
        
        Args:
            protocol_id: Protocol identifier
            provider_class: Provider class to instantiate
            min_workers: Minimum number of workers
            max_workers: Maximum number of workers
            **pool_config: Additional pool configuration
            
        Returns:
            Pool ID for the created pool
        """
        if not self.running:
            await self.start()
        
        # Create pool via pool manager
        pool_id = await self.pool_manager.create_pool(
            protocol_id=protocol_id,
            provider_class=provider_class,
            min_workers=min_workers,
            max_workers=max_workers,
            provider_config=provider_config,
            **pool_config
        )
        
        # Track the mapping
        self.protocol_pools[protocol_id] = pool_id
        self.stats["providers_registered"] += 1
        
        logger.info(f"Registered pooled provider {provider_class.__name__} for protocol {protocol_id}")
        return pool_id
    
    async def execute_task(self, task: Task) -> TaskResult:
        """
        Execute a task using the pooling system
        
        This is the main integration point - ExecutionEngine can call this
        method instead of directly calling providers.
        
        Args:
            task: Task to execute
            
        Returns:
            TaskResult with execution outcome
        """
        self.stats["tasks_executed"] += 1
        start_time = datetime.utcnow()
        
        try:
            # Check if we have a pool for this protocol
            if task.protocol not in self.protocol_pools:
                # For now, provider must be manually registered
                raise ProviderError(
                    f"No pooled provider available for protocol {task.protocol}. Provider must be manually registered in pooling adapter.",
                    code=ErrorCode.PROVIDER_NOT_FOUND,
                    data={"protocol_id": task.protocol, "available_pools": list(self.protocol_pools.keys())}
                )
            
            # Create a task completion future
            completion_future = asyncio.Future()
            correlation_id = f"task-{task.id}-{int(datetime.utcnow().timestamp())}"
            
            # Listen for task completion events
            completion_handler = self._create_completion_handler(task.id, completion_future)
            
            # Submit task to pool by creating TASK_AVAILABLE event
            task_event = GleitzeitEvent(
                event_type=EventType.TASK_AVAILABLE,
                data={
                    "task_id": task.id,
                    "protocol": task.protocol,
                    "method": task.method,
                    "params": task.params,
                    "priority": 0,
                    "timeout": None,
                    "submitted_by": "queue_integrated_pooling_adapter"
                },
                source="queue_integrated_pooling_adapter",
                timestamp=datetime.utcnow(),
                correlation_id=correlation_id
            )
            
            # Route task to appropriate pool
            await self.pool_manager._handle_task_available(task_event)
            
            # Register temporary handler for this task's completion
            original_emit = self.event_emitter
            self.event_emitter = lambda event: self._handle_execution_event(event, completion_handler, original_emit)
            
            try:
                # Wait for task completion (with timeout)
                timeout_seconds = 300  # 5 minutes default
                result = await asyncio.wait_for(completion_future, timeout=timeout_seconds)
                
                self.stats["tasks_completed"] += 1
                
                # Create successful TaskResult
                execution_time = (datetime.utcnow() - start_time).total_seconds()
                
                return TaskResult(
                    task_id=task.id,
                    workflow_id=task.workflow_id,  # Include workflow_id for dependency tracking
                    status=TaskStatus.COMPLETED,
                    result=result,
                    error=None,
                    duration_seconds=execution_time,
                    completed_at=datetime.utcnow()
                )
                
            finally:
                # Restore original event emitter
                self.event_emitter = original_emit
            
        except asyncio.TimeoutError:
            self.stats["tasks_failed"] += 1
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            error_msg = f"Task {task.id} timed out after {timeout_seconds} seconds"
            logger.error(error_msg)
            
            return TaskResult(
                task_id=task.id,
                workflow_id=task.workflow_id,
                status=TaskStatus.FAILED,
                result=None,
                error=error_msg,
                duration_seconds=execution_time,
                completed_at=datetime.utcnow()
            )
            
        except Exception as e:
            self.stats["tasks_failed"] += 1
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            logger.error(f"Task {task.id} execution failed: {e}")
            
            return TaskResult(
                task_id=task.id,
                workflow_id=task.workflow_id,
                status=TaskStatus.FAILED,
                result=None,
                error=str(e),
                duration_seconds=execution_time,
                completed_at=datetime.utcnow()
            )
    
    def _create_completion_handler(self, task_id: str, future: asyncio.Future) -> Callable:
        """Create completion handler for a specific task"""
        def handler(event: GleitzeitEvent) -> None:
            if not future.done() and event.data.get("task_id") == task_id:
                if event.event_type == EventType.TASK_COMPLETED:
                    result = event.data.get("result")
                    future.set_result(result)
                elif event.event_type == EventType.TASK_FAILED:
                    error = event.data.get("error", "Task execution failed")
                    future.set_exception(TaskError(error, code=ErrorCode.TASK_EXECUTION_FAILED))
        
        return handler
    
    async def _handle_execution_event(
        self, 
        event: GleitzeitEvent, 
        completion_handler: Callable,
        original_emitter: Optional[Callable]
    ) -> None:
        """Handle events during task execution"""
        # Check for task completion
        if event.event_type in [EventType.TASK_COMPLETED, EventType.TASK_FAILED]:
            completion_handler(event)
        
        # Forward to original emitter if available
        if original_emitter:
            await original_emitter(event)
    
    async def _emit_event(self, event: GleitzeitEvent) -> None:
        """Emit event using configured emitter"""
        if self.event_emitter:
            await self.event_emitter(event)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get adapter statistics"""
        pool_stats = self.pool_manager.get_system_stats()
        
        return {
            "adapter_stats": self.stats,
            "pool_stats": pool_stats,
            "registered_protocols": list(self.protocol_pools.keys()),
            "running": self.running
        }
    
    def is_protocol_available(self, protocol_id: str) -> bool:
        """Check if a protocol is available for pooled execution"""
        return protocol_id in self.protocol_pools
    
    def get_available_protocols(self) -> list:
        """Get list of protocols available for pooled execution"""
        return list(self.protocol_pools.keys())