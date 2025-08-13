"""
Task Dispatcher - Automatically assigns queued tasks to available executor nodes
"""

import asyncio
import time
from typing import Dict, List, Optional, Set
from datetime import datetime

from .error_handling import GleitzeitLogger, RetryManager, RetryConfig
from ..storage.redis_client import RedisClient
from ..communication.socketio_server import SocketIOServer


class TaskDispatcher:
    """
    Automatically dispatches queued tasks to available executor nodes
    
    Handles:
    - Task assignment from Redis queues to executor nodes
    - Load balancing across executors
    - Retry logic for failed assignments
    - Recovery-aware task dispatch
    """
    
    def __init__(
        self,
        redis_client: RedisClient,
        socketio_server: Optional[SocketIOServer] = None,
        local_task_executor = None,  # Local TaskExecutor for direct execution
        dispatch_interval: float = 2.0,
        max_concurrent_assignments: int = 10
    ):
        self.redis_client = redis_client
        self.socketio_server = socketio_server
        self.local_task_executor = local_task_executor
        self.dispatch_interval = dispatch_interval
        self.max_concurrent_assignments = max_concurrent_assignments
        
        self.logger = GleitzeitLogger("TaskDispatcher")
        self.retry_manager = RetryManager(self.logger)
        
        self._running = False
        self._dispatch_task: Optional[asyncio.Task] = None
        self._assignment_semaphore = asyncio.Semaphore(max_concurrent_assignments)
        
        # Track assignment attempts to avoid duplicate assignments
        self._pending_assignments: Set[str] = set()
        
    async def start(self):
        """Start the task dispatcher"""
        if self._running:
            return
            
        self._running = True
        self.logger.logger.info("🚀 Starting Task Dispatcher")
        
        # Start the dispatch loop
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        
    async def stop(self):
        """Stop the task dispatcher"""
        if not self._running:
            return
            
        self._running = False
        self.logger.logger.info("🛑 Stopping Task Dispatcher")
        
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
                
    async def _dispatch_loop(self):
        """Main dispatch loop - continuously assigns tasks to executors"""
        try:
            while self._running:
                try:
                    # Get available executor nodes
                    available_executors = await self._get_available_executors()
                    
                    if available_executors:
                        # Dispatch tasks for each priority level
                        for priority in ["urgent", "high", "normal", "low"]:
                            await self._dispatch_tasks_by_priority(priority, available_executors)
                    else:
                        # No executors available - check why
                        if self.local_task_executor:
                            self.logger.logger.warning("Local task executor is available but not in executor list")
                        else:
                            self.logger.logger.warning("No local task executor available")
                    
                    # Wait before next dispatch cycle
                    await asyncio.sleep(self.dispatch_interval)
                    
                except Exception as e:
                    self.logger.logger.error(f"Error in dispatch loop: {e}")
                    await asyncio.sleep(self.dispatch_interval)
                    
        except asyncio.CancelledError:
            self.logger.logger.info("Dispatch loop cancelled")
            raise
            
    async def _get_available_executors(self) -> List[Dict[str, str]]:
        """Get list of available executor nodes (including external services)"""
        try:
            executor_nodes = []
            
            if self.socketio_server:
                # Get regular executor nodes
                for sid, node_info in self.socketio_server.executor_nodes.items():
                    if node_info.get('status') == 'ready':
                        executor_nodes.append({
                            'node_id': node_info.get('node_id'),
                            'sid': sid,
                            'node_type': 'executor',
                            'current_tasks': node_info.get('current_tasks', 0),
                            'max_tasks': node_info.get('max_tasks', 4),
                            'capabilities': node_info.get('capabilities', {})
                        })
                
                # Get external service nodes
                for sid, service_info in self.socketio_server.external_service_nodes.items():
                    if service_info.get('status') == 'ready':
                        executor_nodes.append({
                            'node_id': service_info.get('service_id'),
                            'sid': sid,
                            'node_type': 'external_service',
                            'current_tasks': service_info.get('current_tasks', 0),
                            'max_tasks': service_info.get('max_tasks', 10),
                            'task_types': service_info.get('task_types', []),
                            'capabilities': service_info.get('capabilities', [])
                        })
                
                # Always add local executor if available 
                if self.local_task_executor:
                    executor_nodes.append({
                        'node_id': 'local_executor',
                        'sid': None,
                        'node_type': 'local',
                        'current_tasks': 0,
                        'max_tasks': 4,
                        'capabilities': {'llm': True, 'external_custom': True}
                    })
                    self.logger.logger.info(f"Added local executor to available executors")
                
                # Debug: Log all available executors
                self.logger.logger.info(f"Available executors: {len(executor_nodes)} total")
                for executor in executor_nodes:
                    node_type = executor.get('node_type', 'unknown')
                    node_id = executor.get('node_id', 'unknown')
                    self.logger.logger.info(f"  - {node_type}: {node_id}")
                
                # Sort by current load (least loaded first)
                executor_nodes.sort(key=lambda x: x['current_tasks'])
                
                return executor_nodes
            else:
                # Fallback: get active nodes from Redis, or use local executor
                active_node_ids = await self.redis_client.get_active_nodes()
                if not active_node_ids and self.local_task_executor:
                    return [{'node_id': 'local_executor', 'sid': None, 'node_type': 'local'}]
                return [{'node_id': node_id, 'sid': None, 'node_type': 'executor'} for node_id in active_node_ids]
                
        except Exception as e:
            self.logger.logger.error(f"Failed to get available executors: {e}")
            return []
            
    async def _dispatch_tasks_by_priority(self, priority: str, available_executors: List[Dict]):
        """Dispatch tasks for a specific priority level"""
        try:
            # Limit concurrent assignments to avoid overwhelming
            async with self._assignment_semaphore:
                # Get tasks from this priority queue
                tasks_assigned = 0
                
                for executor in available_executors:
                    # Check if executor has capacity
                    current_tasks = executor.get('current_tasks', 0)
                    max_tasks = executor.get('max_tasks', 4)
                    
                    if current_tasks >= max_tasks:
                        continue
                        
                    # Try to assign a task to this executor
                    task_id = await self.redis_client.pop_task_from_queue(priority)
                    
                    if not task_id:
                        break  # No more tasks in this priority queue
                        
                    if task_id in self._pending_assignments:
                        continue  # Already being assigned
                        
                    # Assign task to executor
                    success = await self._assign_task_to_executor(task_id, executor)
                    
                    if success:
                        tasks_assigned += 1
                        
                    # Respect assignment limits
                    if tasks_assigned >= self.max_concurrent_assignments:
                        break
                        
                if tasks_assigned > 0:
                    self.logger.logger.info(f"Dispatched {tasks_assigned} {priority} priority tasks")
                    
        except Exception as e:
            self.logger.logger.error(f"Failed to dispatch {priority} priority tasks: {e}")
            
    async def _assign_task_to_executor(self, task_id: str, executor: Dict) -> bool:
        """Assign a specific task to a specific executor (regular or external service)"""
        try:
            # Mark as pending to avoid duplicate assignments
            self._pending_assignments.add(task_id)
            
            node_id = executor['node_id']
            sid = executor.get('sid')
            node_type = executor.get('node_type', 'executor')
            
            # Get task details for assignment
            task_data = await self.redis_client.redis.hgetall(f"task:{task_id}")
            if not task_data:
                self.logger.logger.warning(f"Task {task_id} not found for assignment")
                return False
                
            # Re-resolve task parameters before assignment
            await self._resolve_task_parameters(task_id, task_data)
            
            # Check task type routing
            task_type = task_data.get('task_type', '')
            is_external_task = task_type.startswith('external_')
            
            # FORCE LLM tasks (EXTERNAL_CUSTOM) to local executor if available
            if task_type == 'external_custom':
                if self.local_task_executor and node_type == 'local':
                    # Perfect - this is the local executor for LLM tasks
                    pass
                elif self.local_task_executor and node_type != 'local':
                    # We have a local executor but this is not it - skip other executors for LLM tasks
                    self.logger.logger.debug(f"Skipping {node_type} executor for LLM task - prefer local executor")
                    return False
                elif not self.local_task_executor and node_type == 'external_service':
                    # No local executor, check if external service can handle LLM
                    task_types = executor.get('task_types', [])
                    capabilities = executor.get('capabilities', [])
                    if 'llm' not in str(capabilities).lower() and 'external_custom' not in task_types:
                        return False
                elif not self.local_task_executor and node_type != 'external_service':
                    # No local executor and not external service - skip
                    return False
            
            # Handle other external task types
            elif is_external_task and node_type != 'external_service' and node_type != 'local':
                # Other external tasks should go to external service, skip regular executor
                return False
            elif not is_external_task and node_type == 'external_service':
                # Regular task should not go to external service, skip
                return False
            
            # For external services, check task type compatibility
            if node_type == 'external_service':
                task_types = executor.get('task_types', [])
                if task_type not in task_types:
                    # Check if any supported task type matches
                    external_task_type = task_data.get('external_task_type')
                    if external_task_type and external_task_type not in task_types:
                        return False
            
            # Handle local execution directly
            if node_type == 'local' and self.local_task_executor:
                await self._execute_task_locally(task_id, task_data)
                return True
            
            # Assign task in Redis
            await self.redis_client.assign_task_to_node(task_id, node_id)
            
            # Notify executor via Socket.IO if available
            if self.socketio_server and sid:
                await self._notify_executor_via_socketio(sid, task_id, task_data, executor)
            
            executor_type = "external service" if node_type == 'external_service' else "executor"
            self.logger.logger.info(f"Assigned task {task_id[:8]}... to {executor_type} {node_id}")
            return True
            
        except Exception as e:
            self.logger.logger.error(f"Failed to assign task {task_id} to executor {executor.get('node_id')}: {e}")
            return False
        finally:
            # Remove from pending assignments
            self._pending_assignments.discard(task_id)
            
    async def _resolve_task_parameters(self, task_id: str, task_data: Dict):
        """Re-resolve task parameters that reference other task results"""
        try:
            import json
            import re
            
            # Get workflow ID to fetch results
            workflow_id = task_data.get('workflow_id')
            if not workflow_id:
                return
                
            # Get workflow results for parameter substitution
            workflow_results = await self.redis_client.get_workflow_results(workflow_id)
            
            # Parse current parameters
            parameters_json = task_data.get('parameters', '{}')
            try:
                parameters = json.loads(parameters_json)
            except json.JSONDecodeError:
                return
                
            # Resolve parameter references like {{task_name.result}}
            updated = False
            for key, value in parameters.items():
                if isinstance(value, str) and '{{' in value and '}}' in value:
                    # Find parameter references
                    pattern = r'\{\{([^}]+)\}\}'
                    matches = re.findall(pattern, value)
                    
                    for match in matches:
                        if '.result' in match:
                            # Extract referenced task name
                            ref_task_name = match.replace('.result', '').strip()
                            
                            # Find result by task name
                            for result_task_id, result_value in workflow_results.items():
                                result_task_data = await self.redis_client.redis.hgetall(f"task:{result_task_id}")
                                if result_task_data and result_task_data.get('name') == ref_task_name:
                                    # Replace parameter reference with actual result
                                    value = value.replace(f"{{{{{match}}}}}", str(result_value))
                                    parameters[key] = value
                                    updated = True
                                    break
            
            # Update task parameters if changed
            if updated:
                updated_parameters_json = json.dumps(parameters)
                await self.redis_client.redis.hset(
                    f"task:{task_id}", 
                    "parameters", 
                    updated_parameters_json
                )
                self.logger.logger.info(f"Resolved parameters for task {task_id[:8]}...")
                
        except Exception as e:
            self.logger.logger.error(f"Failed to resolve parameters for task {task_id}: {e}")
    
    async def _execute_task_locally(self, task_id: str, task_data: Dict):
        """Execute task using local TaskExecutor"""
        try:
            import json
            from ..core.task import Task, TaskType
            
            self.logger.logger.info(f"Executing task {task_id[:8]}... locally")
            
            # Parse task data
            parameters_json = task_data.get('parameters', '{}')
            try:
                parameters = json.loads(parameters_json)
            except json.JSONDecodeError:
                parameters = {}
            
            # Map task type string to enum
            task_type_str = task_data.get('task_type', 'external_custom')
            task_type_enum = TaskType.EXTERNAL_CUSTOM  # Default
            try:
                if task_type_str == 'external_custom':
                    task_type_enum = TaskType.EXTERNAL_CUSTOM
                elif task_type_str == 'external_ml':
                    task_type_enum = TaskType.EXTERNAL_ML
                # Add other mappings as needed
            except:
                pass
            
            # Create Task object
            task = Task(
                id=task_id,
                workflow_id=task_data.get('workflow_id'),
                name=task_data.get('name', f'Task_{task_id[:8]}'),
                task_type=task_type_enum,
                parameters=parameters
            )
            
            # Execute task
            result = await self.local_task_executor.execute_task(task)
            
            # Store result in Redis
            await self.redis_client.complete_task(task_id, result=result)
            await self.redis_client.store_workflow_result(
                task_data.get('workflow_id'), task_id, result
            )
            
            self.logger.logger.info(f"✅ Local task completed: {task_id[:8]}...")
            
            # IMPORTANT: Emit task:completed event to Socket.IO server
            # This triggers workflow completion check and workflow:completed event
            if self.socketio_server:
                try:
                    workflow_id = task_data.get('workflow_id')
                    await self.socketio_server.broadcast_event('task:completed', {
                        'task_id': task_id,
                        'workflow_id': workflow_id,
                        'result': result,
                        'timestamp': datetime.utcnow().isoformat()
                    }, room=f"workflow:{workflow_id}")
                    
                    # Trigger workflow completion check
                    await self.socketio_server._check_workflow_completion(workflow_id)
                    
                    self.logger.logger.info(f"Emitted task:completed event for task {task_id[:8]}...")
                except Exception as emit_error:
                    self.logger.logger.warning(f"Failed to emit task:completed event: {emit_error}")
            
        except Exception as e:
            self.logger.logger.error(f"❌ Local task failed: {task_id[:8]}... - {e}")
            
            # Store error in Redis
            error_msg = str(e)
            await self.redis_client.complete_task(task_id, error=error_msg)
            await self.redis_client.store_workflow_error(
                task_data.get('workflow_id'), task_id, error_msg
            )
            
            # IMPORTANT: Emit task:failed event to Socket.IO server  
            # This triggers workflow completion check
            if self.socketio_server:
                try:
                    workflow_id = task_data.get('workflow_id')
                    await self.socketio_server.broadcast_event('task:failed', {
                        'task_id': task_id,
                        'workflow_id': workflow_id,
                        'error': error_msg,
                        'timestamp': datetime.utcnow().isoformat()
                    }, room=f"workflow:{workflow_id}")
                    
                    # Trigger workflow completion check
                    await self.socketio_server._check_workflow_completion(workflow_id)
                    
                    self.logger.logger.info(f"Emitted task:failed event for task {task_id[:8]}...")
                except Exception as emit_error:
                    self.logger.logger.warning(f"Failed to emit task:failed event: {emit_error}")
            
    async def _notify_executor_via_socketio(self, sid: str, task_id: str, task_data: Dict, executor: Dict):
        """Notify executor about task assignment via Socket.IO"""
        try:
            if not self.socketio_server:
                return
            
            # Parse parameters for external tasks
            parameters = task_data.get('parameters', '{}')
            if isinstance(parameters, str):
                try:
                    import json
                    parameters = json.loads(parameters)
                except json.JSONDecodeError:
                    parameters = {}
            
            # Prepare task assignment notification
            assignment_data = {
                'task_id': task_id,
                'workflow_id': task_data.get('workflow_id'),
                'task_type': task_data.get('task_type'),
                'task_name': task_data.get('name'),
                'parameters': parameters,
                'priority': task_data.get('priority', 'normal'),
                'max_retries': int(task_data.get('max_retries', 3)),
                'timeout': int(task_data.get('timeout', 300)),
                'assigned_at': datetime.utcnow().isoformat()
            }
            
            # Add external task specific fields
            if executor.get('node_type') == 'external_service':
                assignment_data.update({
                    'external_task_type': parameters.get('external_task_type'),
                    'service_name': parameters.get('service_name'),
                    'external_parameters': parameters.get('external_parameters', {}),
                    'external_timeout': parameters.get('external_timeout', 1800)
                })
            
            # Send assignment to executor
            await self.socketio_server.sio.emit(
                'task:assign', 
                assignment_data, 
                room=sid,
                namespace='/cluster'
            )
            
            executor_type = "external service" if executor.get('node_type') == 'external_service' else "executor"
            self.logger.logger.info(f"Notified {executor_type} {sid} about task {task_id[:8]}...")
            
        except Exception as e:
            self.logger.logger.error(f"Failed to notify executor {sid} about task {task_id}: {e}")
            
    async def dispatch_recovered_workflow(self, workflow_id: str) -> Dict[str, int]:
        """Immediately dispatch tasks for a recovered workflow (high priority)"""
        """This is called after workflow recovery to ensure immediate execution"""
        try:
            self.logger.logger.info(f"Dispatching recovered workflow: {workflow_id}")
            
            # Get incomplete tasks for this workflow
            incomplete_tasks = await self.redis_client.get_incomplete_tasks(workflow_id)
            resumable_tasks = [t for t in incomplete_tasks if t['can_resume']]
            
            # Get available executors
            available_executors = await self._get_available_executors()
            
            if not available_executors:
                self.logger.logger.warning("No available executors for recovered workflow")
                return {"assigned": 0, "failed": 0}
                
            assigned_count = 0
            failed_count = 0
            
            # Assign resumable tasks immediately
            for task_info in resumable_tasks:
                task_id = task_info['id']
                
                # Find best executor (least loaded)
                best_executor = min(available_executors, key=lambda x: x.get('current_tasks', 0))
                
                # Check capacity
                if best_executor.get('current_tasks', 0) >= best_executor.get('max_tasks', 4):
                    self.logger.logger.warning("All executors at capacity")
                    break
                    
                # Assign task
                success = await self._assign_task_to_executor(task_id, best_executor)
                
                if success:
                    assigned_count += 1
                    # Update executor load tracking
                    best_executor['current_tasks'] = best_executor.get('current_tasks', 0) + 1
                else:
                    failed_count += 1
                    
            self.logger.logger.info(f"Recovery dispatch: {assigned_count} assigned, {failed_count} failed")
            return {"assigned": assigned_count, "failed": failed_count}
            
        except Exception as e:
            self.logger.logger.error(f"Failed to dispatch recovered workflow {workflow_id}: {e}")
            return {"assigned": 0, "failed": 1}
            
    def get_stats(self) -> Dict:
        """Get dispatcher statistics"""
        return {
            "running": self._running,
            "dispatch_interval": self.dispatch_interval,
            "pending_assignments": len(self._pending_assignments),
            "max_concurrent": self.max_concurrent_assignments
        }