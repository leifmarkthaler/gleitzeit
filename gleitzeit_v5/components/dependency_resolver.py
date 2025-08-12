"""
Dependency Resolver Client for Gleitzeit V5

Distributed component that handles task dependency resolution,
parameter substitution, and workflow coordination through pure Socket.IO events.
"""

import asyncio
import logging
import json
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass
from enum import Enum
import uuid

from ..base.component import SocketIOComponent
from ..base.config import ComponentConfig

logger = logging.getLogger(__name__)


class DependencyStatus(Enum):
    """Dependency resolution status"""
    PENDING = "pending"
    RESOLVED = "resolved" 
    FAILED = "failed"
    CIRCULAR = "circular"


@dataclass
class DependencyRequest:
    """Represents a dependency resolution request"""
    task_id: str
    workflow_id: str
    dependencies: List[str]
    requested_at: datetime
    correlation_id: str
    status: DependencyStatus = DependencyStatus.PENDING
    resolved_count: int = 0
    
    
@dataclass
class TaskResult:
    """Represents a completed task result"""
    task_id: str
    workflow_id: str
    result: Any
    completed_at: datetime
    success: bool = True
    error: Optional[str] = None


class DependencyResolverClient(SocketIOComponent):
    """
    Dependency Resolver Client for distributed dependency management
    
    Responsibilities:
    - Track task dependencies within and across workflows
    - Resolve parameter substitutions using dependency results
    - Detect and handle circular dependencies
    - Coordinate with QueueManager for dependency satisfaction
    - Maintain task result cache for parameter resolution
    
    Events Emitted:
    - dependency_resolved: When a dependency is resolved for a task
    - dependency_failed: When a dependency fails to resolve
    - circular_dependency_detected: When circular dependencies are found
    - parameter_substitution_complete: When parameter substitution is done
    
    Events Handled:
    - dependency_check_request: Check and resolve dependencies for a task
    - task_completed: Record task completion for future dependency resolution
    - task_failed: Record task failure affecting dependent tasks
    - resolve_parameters: Perform parameter substitution with dependency results
    - clear_workflow_results: Clear cached results for a workflow
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
            component_type="dependency_resolver",
            component_id=component_id or f"depres-{uuid.uuid4().hex[:8]}",
            config=config
        )
        
        # Dependency tracking
        self.pending_requests: Dict[str, DependencyRequest] = {}  # task_id -> request
        self.task_dependencies: Dict[str, Set[str]] = {}  # task_id -> dependency_task_ids
        self.dependent_tasks: Dict[str, Set[str]] = {}  # dependency_id -> dependent_task_ids
        
        # Result cache
        self.task_results: Dict[str, TaskResult] = {}  # task_id -> result
        self.workflow_results: Dict[str, Dict[str, TaskResult]] = {}  # workflow_id -> {task_id -> result}
        
        # Circular dependency detection
        self.dependency_graph: Dict[str, Set[str]] = {}  # task_id -> direct_dependencies
        
        # Statistics
        self.stats = {
            'dependencies_resolved': 0,
            'dependencies_failed': 0,
            'circular_dependencies_detected': 0,
            'parameter_substitutions': 0,
            'cached_results': 0
        }
        
        logger.info(f"Initialized Dependency Resolver: {self.component_id}")
    
    def setup_events(self):
        """Setup event handlers for dependency resolution"""
        
        @self.sio.on('dependency_check_request')
        async def handle_dependency_check(data):
            """Handle dependency check request from Queue Manager"""
            try:
                request = DependencyRequest(
                    task_id=data['task_id'],
                    workflow_id=data['workflow_id'],
                    dependencies=data['dependencies'],
                    requested_at=datetime.utcnow(),
                    correlation_id=data.get('_correlation_id', str(uuid.uuid4()))
                )
                
                await self._process_dependency_request(request)
                
            except Exception as e:
                logger.error(f"Error handling dependency_check_request: {e}")
        
        @self.sio.on('task_completed')
        async def handle_task_completed(data):
            """Handle task completion notification"""
            try:
                result = TaskResult(
                    task_id=data['task_id'],
                    workflow_id=data['workflow_id'],
                    result=data.get('result'),
                    completed_at=datetime.utcnow(),
                    success=True
                )
                
                await self._store_task_result(result)
                await self._check_dependent_tasks(result.task_id)
                
            except Exception as e:
                logger.error(f"Error handling task_completed: {e}")
        
        @self.sio.on('task_failed') 
        async def handle_task_failed(data):
            """Handle task failure notification"""
            try:
                result = TaskResult(
                    task_id=data['task_id'],
                    workflow_id=data['workflow_id'],
                    result=None,
                    completed_at=datetime.utcnow(),
                    success=False,
                    error=data.get('error', 'Unknown error')
                )
                
                await self._store_task_result(result)
                await self._propagate_failure(result.task_id, result.error or "Dependency failed")
                
            except Exception as e:
                logger.error(f"Error handling task_failed: {e}")
        
        @self.sio.on('resolve_parameters')
        async def handle_resolve_parameters(data):
            """Handle parameter resolution request"""
            try:
                task_id = data['task_id']
                parameters = data['parameters']
                correlation_id = data.get('_correlation_id', str(uuid.uuid4()))
                
                resolved_params = await self._resolve_parameter_substitutions(
                    task_id, parameters
                )
                
                await self.emit_with_correlation('parameter_substitution_complete', {
                    'task_id': task_id,
                    'original_parameters': parameters,
                    'resolved_parameters': resolved_params
                }, correlation_id)
                
                self.stats['parameter_substitutions'] += 1
                
            except Exception as e:
                logger.error(f"Error resolving parameters: {e}")
                await self.emit_with_correlation('parameter_resolution_failed', {
                    'task_id': data.get('task_id'),
                    'error': str(e)
                })
        
        @self.sio.on('clear_workflow_results')
        async def handle_clear_workflow_results(data):
            """Clear cached results for a workflow"""
            try:
                workflow_id = data['workflow_id']
                await self._clear_workflow_results(workflow_id)
                
                logger.info(f"Cleared results cache for workflow: {workflow_id}")
                
            except Exception as e:
                logger.error(f"Error clearing workflow results: {e}")
        
        @self.sio.on('get_dependency_stats')
        async def handle_get_dependency_stats(data):
            """Return dependency resolution statistics"""
            try:
                correlation_id = data.get('_correlation_id', str(uuid.uuid4()))
                
                stats = self._get_dependency_statistics()
                
                await self.emit_with_correlation('dependency_stats_response', {
                    'stats': stats,
                    '_response_to': correlation_id
                }, correlation_id)
                
            except Exception as e:
                logger.error(f"Error handling get_dependency_stats: {e}")
    
    def get_capabilities(self) -> List[str]:
        """Return list of capabilities this component provides"""
        return ['dependency_resolution', 'parameter_substitution', 'circular_detection', 'result_caching']
    
    async def on_ready(self):
        """Called when component is registered and ready"""
        logger.info(f"Dependency Resolver {self.component_id} is ready")
    
    async def on_shutdown(self):
        """Called during graceful shutdown for component-specific cleanup"""
        # Clear all caches
        self.task_results.clear()
        self.workflow_results.clear()
        self.pending_requests.clear()
        self.dependency_graph.clear()
        logger.info(f"Dependency Resolver {self.component_id} shutdown cleanup completed")
    
    async def _process_dependency_request(self, request: DependencyRequest):
        """Process a dependency resolution request"""
        
        self.pending_requests[request.task_id] = request
        
        # Build dependency graph for circular detection
        self.dependency_graph[request.task_id] = set(request.dependencies)
        self.task_dependencies[request.task_id] = set(request.dependencies)
        
        # Track reverse dependencies
        for dep_id in request.dependencies:
            if dep_id not in self.dependent_tasks:
                self.dependent_tasks[dep_id] = set()
            self.dependent_tasks[dep_id].add(request.task_id)
        
        # Check for circular dependencies
        if self._has_circular_dependency(request.task_id):
            await self._handle_circular_dependency(request)
            return
        
        # Check which dependencies are already resolved
        resolved_count = 0
        for dep_id in request.dependencies:
            if dep_id in self.task_results:
                result = self.task_results[dep_id]
                if result.success:
                    await self._resolve_single_dependency(request, dep_id, result)
                    resolved_count += 1
                else:
                    # Dependency failed, propagate failure
                    await self._fail_dependency_request(
                        request, f"Dependency {dep_id} failed: {result.error}"
                    )
                    return
        
        request.resolved_count = resolved_count
        
        # Check if all dependencies are resolved
        if resolved_count == len(request.dependencies):
            await self._complete_dependency_request(request)
    
    async def _store_task_result(self, result: TaskResult):
        """Store task result for future dependency resolution"""
        
        self.task_results[result.task_id] = result
        
        # Also store in workflow cache
        if result.workflow_id not in self.workflow_results:
            self.workflow_results[result.workflow_id] = {}
        self.workflow_results[result.workflow_id][result.task_id] = result
        
        self.stats['cached_results'] = len(self.task_results)
        
        logger.debug(f"Stored result for task {result.task_id}")
    
    async def _check_dependent_tasks(self, completed_task_id: str):
        """Check if any pending tasks are waiting for this dependency"""
        
        if completed_task_id not in self.dependent_tasks:
            return
        
        dependent_task_ids = self.dependent_tasks[completed_task_id].copy()
        
        for task_id in dependent_task_ids:
            if task_id in self.pending_requests:
                request = self.pending_requests[task_id]
                result = self.task_results[completed_task_id]
                
                if result.success:
                    await self._resolve_single_dependency(request, completed_task_id, result)
                    request.resolved_count += 1
                    
                    # Check if all dependencies are now resolved
                    if request.resolved_count == len(request.dependencies):
                        await self._complete_dependency_request(request)
                else:
                    # Dependency failed
                    await self._fail_dependency_request(
                        request, f"Dependency {completed_task_id} failed: {result.error}"
                    )
    
    async def _resolve_single_dependency(
        self, 
        request: DependencyRequest, 
        dep_id: str, 
        result: TaskResult
    ):
        """Resolve a single dependency for a task"""
        
        await self.emit_with_correlation('route_event', {
            'target_component_type': 'queue_manager',
            'event_name': 'dependency_resolved',
            'event_data': {
                'dependent_task_id': request.task_id,
                'dependency_task_id': dep_id,
                'result': result.result,
                'workflow_id': request.workflow_id
            }
        }, request.correlation_id)
        
        logger.debug(f"Resolved dependency {dep_id} for task {request.task_id}")
    
    async def _complete_dependency_request(self, request: DependencyRequest):
        """Complete a dependency resolution request"""
        
        request.status = DependencyStatus.RESOLVED
        self.stats['dependencies_resolved'] += 1
        
        logger.info(f"All dependencies resolved for task {request.task_id}")
        
        # Clean up completed request
        del self.pending_requests[request.task_id]
    
    async def _fail_dependency_request(self, request: DependencyRequest, error: str):
        """Fail a dependency resolution request"""
        
        request.status = DependencyStatus.FAILED
        self.stats['dependencies_failed'] += 1
        
        await self.emit_with_correlation('route_event', {
            'target_component_type': 'queue_manager',
            'event_name': 'dependency_failed',
            'event_data': {
                'task_id': request.task_id,
                'workflow_id': request.workflow_id,
                'error': error
            }
        }, request.correlation_id)
        
        logger.error(f"Dependencies failed for task {request.task_id}: {error}")
        
        # Clean up failed request
        del self.pending_requests[request.task_id]
    
    async def _propagate_failure(self, failed_task_id: str, error: str):
        """Propagate failure to dependent tasks"""
        
        if failed_task_id not in self.dependent_tasks:
            return
        
        dependent_task_ids = self.dependent_tasks[failed_task_id].copy()
        
        for task_id in dependent_task_ids:
            if task_id in self.pending_requests:
                request = self.pending_requests[task_id]
                await self._fail_dependency_request(
                    request, f"Dependency {failed_task_id} failed: {error}"
                )
    
    def _has_circular_dependency(self, task_id: str, visited: Optional[Set[str]] = None) -> bool:
        """Check for circular dependencies using DFS"""
        
        if visited is None:
            visited = set()
        
        if task_id in visited:
            return True
        
        visited.add(task_id)
        
        dependencies = self.dependency_graph.get(task_id, set())
        for dep_id in dependencies:
            if self._has_circular_dependency(dep_id, visited.copy()):
                return True
        
        return False
    
    async def _handle_circular_dependency(self, request: DependencyRequest):
        """Handle circular dependency detection"""
        
        request.status = DependencyStatus.CIRCULAR
        self.stats['circular_dependencies_detected'] += 1
        
        await self.emit_with_correlation('circular_dependency_detected', {
            'task_id': request.task_id,
            'workflow_id': request.workflow_id,
            'dependencies': request.dependencies
        }, request.correlation_id)
        
        logger.error(f"Circular dependency detected for task {request.task_id}")
        
        # Clean up circular request
        del self.pending_requests[request.task_id]
    
    async def _resolve_parameter_substitutions(
        self, 
        task_id: str, 
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Resolve parameter substitutions using dependency results"""
        
        resolved_params = {}
        
        for key, value in parameters.items():
            resolved_params[key] = await self._resolve_parameter_value(value, task_id)
        
        return resolved_params
    
    async def _resolve_parameter_value(self, value: Any, task_id: str) -> Any:
        """Resolve a single parameter value"""
        
        if isinstance(value, str):
            # Look for parameter substitution patterns like ${task_id.result}
            pattern = r'\$\{([^.]+)\.([^}]+)\}'
            matches = re.findall(pattern, value)
            
            resolved_value = value
            for dep_task_id, result_path in matches:
                if dep_task_id in self.task_results:
                    result = self.task_results[dep_task_id]
                    if result.success:
                        # Extract value from result using dot notation
                        extracted_value = self._extract_nested_value(result.result, result_path)
                        # Replace the substitution pattern
                        resolved_value = resolved_value.replace(
                            f"${{{dep_task_id}.{result_path}}}", str(extracted_value)
                        )
                    else:
                        logger.warning(f"Cannot substitute from failed task {dep_task_id}")
                else:
                    logger.warning(f"Task result not found for substitution: {dep_task_id}")
            
            return resolved_value
            
        elif isinstance(value, dict):
            # Recursively resolve dictionary values
            return {
                k: await self._resolve_parameter_value(v, task_id) 
                for k, v in value.items()
            }
            
        elif isinstance(value, list):
            # Recursively resolve list values
            return [
                await self._resolve_parameter_value(item, task_id) 
                for item in value
            ]
        
        else:
            # Return value as-is for non-string types
            return value
    
    def _extract_nested_value(self, data: Any, path: str) -> Any:
        """Extract nested value from data using dot notation"""
        
        if not path:
            return data
        
        parts = path.split('.')
        current = data
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                index = int(part)
                if 0 <= index < len(current):
                    current = current[index]
                else:
                    return None
            else:
                return None
        
        return current
    
    async def _clear_workflow_results(self, workflow_id: str):
        """Clear cached results for a specific workflow"""
        
        if workflow_id in self.workflow_results:
            # Remove from main cache
            task_ids = list(self.workflow_results[workflow_id].keys())
            for task_id in task_ids:
                self.task_results.pop(task_id, None)
            
            # Remove workflow cache
            del self.workflow_results[workflow_id]
        
        # Clean up dependency tracking for workflow tasks
        workflow_tasks = set()
        for task_id, result in list(self.task_results.items()):
            if result.workflow_id == workflow_id:
                workflow_tasks.add(task_id)
        
        # Remove from dependency tracking structures
        for task_id in workflow_tasks:
            self.dependency_graph.pop(task_id, None)
            self.task_dependencies.pop(task_id, None)
            self.dependent_tasks.pop(task_id, None)
        
        self.stats['cached_results'] = len(self.task_results)
    
    def _get_dependency_statistics(self) -> Dict[str, Any]:
        """Get comprehensive dependency resolution statistics"""
        
        return {
            **self.stats,
            'pending_requests': len(self.pending_requests),
            'tracked_dependencies': len(self.dependency_graph),
            'workflows_with_cached_results': len(self.workflow_results),
            'component_uptime_seconds': (
                datetime.utcnow() - self.health_metrics['started_at']
            ).total_seconds()
        }
    
    async def get_health_metrics(self) -> Dict[str, Any]:
        """Get health metrics for heartbeat responses"""
        return {
            'dependencies_resolved': self.stats['dependencies_resolved'],
            'dependencies_failed': self.stats['dependencies_failed'],
            'cached_results': self.stats['cached_results'],
            'pending_requests': len(self.pending_requests),
            'memory_usage_mb': len(self.task_results) * 0.001,  # Rough estimate
            'status': 'healthy'
        }
    


# Convenience function to run the Dependency Resolver
async def run_dependency_resolver(
    component_id: Optional[str] = None,
    config: Optional[ComponentConfig] = None,
    hub_url: str = "http://localhost:8000"
):
    """Run a Dependency Resolver client"""
    
    dependency_resolver = DependencyResolverClient(
        component_id=component_id,
        config=config,
        hub_url=hub_url
    )
    
    await dependency_resolver.start()


if __name__ == "__main__":
    import sys
    
    # Parse command line arguments
    component_id = sys.argv[1] if len(sys.argv) > 1 else None
    hub_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
    
    asyncio.run(run_dependency_resolver(component_id=component_id, hub_url=hub_url))