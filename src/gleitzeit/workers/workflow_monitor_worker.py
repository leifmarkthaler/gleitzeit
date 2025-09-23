"""
Workflow Monitor Worker

Monitors workflow completions and handles parent-child notifications.
Wakes parent tasks when their child workflows complete.
"""

import json
import logging
from typing import Dict, List, Optional
from datetime import datetime

from .base import BaseWorker
from ..core.sharding import default_sharding
from ..core.models import TaskStatus

logger = logging.getLogger(__name__)


class WorkflowMonitorWorker(BaseWorker):
    """
    Monitor workflow completions and wake parent tasks.
    
    This worker:
    - Monitors workflow completion events
    - Checks if completed workflow is a child
    - Wakes parent tasks with child results
    - Handles cross-shard notifications
    """
    
    def get_base_streams(self) -> List[str]:
        """
        Get streams to monitor.
        
        Returns:
            - workflow:completed - Local workflow completions
            - workflow:child:completed - Cross-shard child notifications
        """
        return [
            "workflow:completed",
            "workflow:child:completed"
        ]
    
    async def process_message(self, stream: str, message_id: str, data: Dict[bytes, bytes]):
        """
        Process workflow completion event.
        
        Args:
            stream: Stream name
            message_id: Redis stream message ID
            data: Completion data
        """
        try:
            if stream.endswith("workflow:completed"):
                # Local workflow completion
                await self._handle_local_completion(data)
            elif stream.endswith("workflow:child:completed"):
                # Cross-shard child completion notification
                await self._handle_child_notification(data)
            else:
                logger.warning(f"Unknown stream type: {stream}")
                
        except Exception as e:
            logger.error(
                f"Failed to process workflow completion: {e}",
                exc_info=True,
                extra={'message_id': message_id, 'stream': stream}
            )
            # Don't raise - let message be reprocessed later
    
    async def _handle_local_completion(self, data: Dict[bytes, bytes]):
        """
        Handle completion of a workflow on this shard.
        
        Checks if it's a child workflow and notifies parent.
        """
        workflow_id = data[b'workflow_id'].decode()
        status = data.get(b'status', b'completed').decode()
        result = json.loads(data.get(b'result', b'{}'))
        error = data.get(b'error', b'').decode() if b'error' in data else None
        
        logger.info(f"Workflow {workflow_id} completed with status {status}")
        
        # Check if this is a child workflow
        registry_key = default_sharding.get_global_key(
            f"workflow:children:{workflow_id}"
        )
        child_info = await self.redis.hgetall(registry_key)
        
        if not child_info:
            # Not a child workflow, nothing to do
            logger.debug(f"Workflow {workflow_id} is not a child, no parent to notify")
            return
        
        # Parse child info
        parent_workflow_id = child_info[b'parent_workflow_id'].decode()
        parent_task_id = child_info[b'parent_task_id'].decode()
        parent_shard = int(child_info[b'parent_shard'])
        
        logger.info(
            f"Child workflow {workflow_id} completed, notifying parent "
            f"{parent_workflow_id} on shard {parent_shard}"
        )
        
        # Update registry with completion status
        await self.redis.hset(
            registry_key,
            mapping={
                b'status': status.encode(),
                b'result': json.dumps(result).encode(),
                b'completed_at': datetime.utcnow().isoformat().encode()
            }
        )
        
        if error:
            await self.redis.hset(registry_key, b'error', error.encode())
        
        # Check if parent is on this shard
        if parent_shard == self.shard:
            # Parent is local, wake it directly
            await self._wake_parent_task(
                parent_workflow_id=parent_workflow_id,
                parent_task_id=parent_task_id,
                child_workflow_id=workflow_id,
                result=result,
                status=status,
                error=error
            )
        else:
            # Parent is on different shard, send notification
            await self._notify_parent_shard(
                parent_shard=parent_shard,
                parent_workflow_id=parent_workflow_id,
                parent_task_id=parent_task_id,
                child_workflow_id=workflow_id,
                result=result,
                status=status,
                error=error
            )
        
        # Check for async callback
        await self._handle_callback(workflow_id, result, status)
    
    async def _handle_child_notification(self, data: Dict[bytes, bytes]):
        """
        Handle notification of child workflow completion from another shard.
        """
        parent_workflow_id = data[b'parent_workflow_id'].decode()
        parent_task_id = data[b'parent_task_id'].decode()
        child_workflow_id = data[b'child_workflow_id'].decode()
        status = data.get(b'status', b'completed').decode()
        result = json.loads(data.get(b'result', b'{}'))
        error = data.get(b'error', b'').decode() if b'error' in data else None
        
        logger.info(
            f"Received child completion notification for {child_workflow_id}, "
            f"waking parent task {parent_task_id}"
        )
        
        # Wake the parent task on this shard
        await self._wake_parent_task(
            parent_workflow_id=parent_workflow_id,
            parent_task_id=parent_task_id,
            child_workflow_id=child_workflow_id,
            result=result,
            status=status,
            error=error
        )
    
    async def _wake_parent_task(
        self,
        parent_workflow_id: str,
        parent_task_id: str,
        child_workflow_id: str,
        result: Dict,
        status: str,
        error: Optional[str] = None
    ):
        """
        Wake a waiting parent task with child workflow result.

        Similar to SignalWorker, we emit to task:completed stream
        and let DependencyWorker handle the rest.
        """
        # Get task key to verify task exists and is waiting
        task_key = default_sharding.get_task_key(parent_task_id, parent_workflow_id)

        task_data = await self.redis.hgetall(task_key)
        if not task_data:
            logger.error(f"Parent task {parent_task_id} not found")
            return

        current_status = task_data.get(b'status', b'').decode()
        if current_status != TaskStatus.WAITING.value:
            logger.warning(
                f"Parent task {parent_task_id} is not waiting (status: {current_status})"
            )
            return

        if status == 'completed':
            # Update task with child result
            await self.redis.hset(
                task_key,
                mapping={
                    b'status': TaskStatus.COMPLETED.value.encode(),
                    b'result': json.dumps(result).encode(),
                    b'waiting_cleared': b'true',
                    b'child_workflow_id': child_workflow_id.encode(),
                    b'completed_at': datetime.utcnow().isoformat().encode()
                }
            )

            # Emit to task:completed stream (like SignalWorker does)
            # DependencyWorker will process this and check dependencies
            await self.redis.xadd(
                default_sharding.get_stream_key("task:completed", parent_workflow_id).encode(),
                {
                    b'workflow_id': parent_workflow_id.encode(),
                    b'task_id': parent_task_id.encode(),
                    b'result': json.dumps(result).encode(),
                    b'child_workflow_id': child_workflow_id.encode(),
                    b'timestamp': datetime.utcnow().isoformat().encode()
                }
            )

            logger.info(
                f"Woke parent task {parent_task_id} with child result, "
                f"emitted to task:completed stream"
            )
        else:
            # Mark task as failed
            await self.redis.hset(
                task_key,
                mapping={
                    b'status': TaskStatus.FAILED.value.encode(),
                    b'error': (error or 'Child workflow failed').encode(),
                    b'child_workflow_id': child_workflow_id.encode(),
                    b'failed_at': datetime.utcnow().isoformat().encode()
                }
            )

            # Emit to task:failed stream
            await self.redis.xadd(
                default_sharding.get_stream_key("task:failed", parent_workflow_id).encode(),
                {
                    b'workflow_id': parent_workflow_id.encode(),
                    b'task_id': parent_task_id.encode(),
                    b'error': (error or 'Child workflow failed').encode(),
                    b'child_workflow_id': child_workflow_id.encode(),
                    b'timestamp': datetime.utcnow().isoformat().encode()
                }
            )

            logger.info(
                f"Failed parent task {parent_task_id} due to child failure"
            )
        
        # Clean up parent's children set
        parent_children_key = default_sharding.get_workflow_key(
            "children",
            parent_workflow_id
        )
        await self.redis.srem(parent_children_key, child_workflow_id)
    
    async def _notify_parent_shard(
        self,
        parent_shard: int,
        parent_workflow_id: str,
        parent_task_id: str,
        child_workflow_id: str,
        result: Dict,
        status: str,
        error: Optional[str] = None
    ):
        """
        Send notification to parent's shard about child completion.
        """
        # Target shard's notification stream
        notification_stream = default_sharding.get_stream_key(
            "workflow:child:completed",
            shard=parent_shard
        )
        
        # Build notification data
        notification_data = {
            b'parent_workflow_id': parent_workflow_id.encode(),
            b'parent_task_id': parent_task_id.encode(),
            b'child_workflow_id': child_workflow_id.encode(),
            b'status': status.encode(),
            b'result': json.dumps(result).encode(),
            b'timestamp': datetime.utcnow().isoformat().encode()
        }
        
        if error:
            notification_data[b'error'] = error.encode()
        
        # Send notification
        await self.redis.xadd(notification_stream, notification_data)
        
        logger.info(
            f"Sent child completion notification to parent shard {parent_shard} "
            f"for workflow {child_workflow_id}"
        )
    
    async def _handle_callback(self, workflow_id: str, result: Dict, status: str):
        """
        Handle callback for async workflows.
        """
        callback_key = default_sharding.get_global_key(
            f"workflow:callbacks:{workflow_id}"
        )
        
        callback_data = await self.redis.get(callback_key)
        if not callback_data:
            # No callback registered
            return
        
        callback = json.loads(callback_data)
        
        if callback.get('signal'):
            # Emit signal as callback
            signal_stream = default_sharding.get_stream_key(
                "signal:emit",
                workflow_id=workflow_id
            )
            
            await self.redis.xadd(
                signal_stream,
                {
                    b'signal_name': callback['signal'].encode(),
                    b'payload': json.dumps({
                        'workflow_id': workflow_id,
                        'status': status,
                        'result': result
                    }).encode(),
                    b'workflow_id': workflow_id.encode()
                }
            )
            
            logger.info(f"Triggered callback signal {callback['signal']} for {workflow_id}")
        
        # Clean up callback
        await self.redis.delete(callback_key)
    
    async def on_initialize(self):
        """Initialize worker resources."""
        await super().on_initialize()
        logger.info(
            f"WorkflowMonitorWorker initialized on shard {self.shard} "
            f"monitoring streams: {self.get_base_streams()}"
        )
    
    async def on_shutdown(self):
        """Clean up worker resources."""
        await super().on_shutdown()
        logger.info(f"WorkflowMonitorWorker on shard {self.shard} shut down")