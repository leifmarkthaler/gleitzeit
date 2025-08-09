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
        dispatch_interval: float = 2.0,
        max_concurrent_assignments: int = 10
    ):
        self.redis_client = redis_client
        self.socketio_server = socketio_server
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
                    
                    # Wait before next dispatch cycle
                    await asyncio.sleep(self.dispatch_interval)
                    
                except Exception as e:
                    self.logger.logger.error(f"Error in dispatch loop: {e}")
                    await asyncio.sleep(self.dispatch_interval)
                    
        except asyncio.CancelledError:
            self.logger.logger.info("Dispatch loop cancelled")
            raise
            
    async def _get_available_executors(self) -> List[Dict[str, str]]:
        """Get list of available executor nodes"""
        try:
            # Get active nodes from Redis
            active_node_ids = await self.redis_client.get_active_nodes()
            
            # If we have Socket.IO server, get real-time executor status
            if self.socketio_server:
                executor_nodes = []
                for node_id in active_node_ids:
                    # Check Socket.IO server for executor status
                    for sid, node_info in self.socketio_server.executor_nodes.items():
                        if node_info.get('node_id') == node_id and node_info.get('status') == 'ready':
                            executor_nodes.append({
                                'node_id': node_id,
                                'sid': sid,
                                'current_tasks': node_info.get('current_tasks', 0),
                                'max_tasks': node_info.get('max_tasks', 4)
                            })
                
                # Sort by current load (least loaded first)
                executor_nodes.sort(key=lambda x: x['current_tasks'])
                return executor_nodes
            else:
                # Fallback: assume all active nodes are available
                return [{'node_id': node_id, 'sid': None} for node_id in active_node_ids]
                
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
        """Assign a specific task to a specific executor"""
        try:
            # Mark as pending to avoid duplicate assignments
            self._pending_assignments.add(task_id)
            
            node_id = executor['node_id']
            sid = executor.get('sid')
            
            # Get task details for assignment
            task_data = await self.redis_client.redis.hgetall(f"task:{task_id}")
            if not task_data:
                self.logger.logger.warning(f"Task {task_id} not found for assignment")
                return False
                
            # Re-resolve task parameters before assignment
            await self._resolve_task_parameters(task_id, task_data)
            
            # Assign task in Redis
            await self.redis_client.assign_task_to_node(task_id, node_id)
            
            # Notify executor via Socket.IO if available
            if self.socketio_server and sid:
                await self._notify_executor_via_socketio(sid, task_id, task_data)
            
            self.logger.logger.info(f"Assigned task {task_id[:8]}... to executor {node_id}")
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
            
    async def _notify_executor_via_socketio(self, sid: str, task_id: str, task_data: Dict):
        """Notify executor about task assignment via Socket.IO"""
        try:
            if not self.socketio_server:
                return
                
            # Prepare task assignment notification
            assignment_data = {
                'task_id': task_id,
                'workflow_id': task_data.get('workflow_id'),
                'task_type': task_data.get('task_type'),
                'task_name': task_data.get('name'),
                'parameters': task_data.get('parameters'),
                'priority': task_data.get('priority', 'normal'),
                'max_retries': int(task_data.get('max_retries', 3)),
                'assigned_at': datetime.utcnow().isoformat()
            }
            
            # Send assignment to executor
            await self.socketio_server.sio.emit(
                'task:assign', 
                assignment_data, 
                room=sid,
                namespace='/cluster'
            )
            
            self.logger.logger.info(f"Notified executor {sid} about task {task_id[:8]}...")
            
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