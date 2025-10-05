"""
Workflow Submission Worker

Handles cross-shard workflow submissions initiated by WorkflowHandler.
Monitors for workflow submission requests and creates child workflows.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from .base import BaseWorker
from ..core.sharding import default_sharding
from ..core.models import WorkflowStatus

logger = logging.getLogger(__name__)


class WorkflowSubmissionWorker(BaseWorker):
    """
    Handle workflow submissions across shards.
    
    This worker:
    - Monitors workflow submission requests from TaskExecutionWorker
    - Registers parent-child relationships in global registry
    - Submits workflows to appropriate shard's loader stream
    - Handles both sync and async workflow submissions
    """
    
    def get_base_streams(self) -> List[str]:
        """
        Get streams to monitor.
        
        Returns workflow submission stream for this shard.
        """
        return ["workflow:submit"]
    
    async def process_message(self, stream: str, message_id: str, data: Dict[bytes, bytes]):
        """
        Process workflow submission request.
        
        Args:
            stream: Stream name
            message_id: Redis stream message ID
            data: Submission data
        """
        try:
            # Parse submission data
            child_workflow_id = data[b'child_workflow_id'].decode()
            parent_workflow_id = data[b'parent_workflow_id'].decode()
            parent_task_id = data[b'parent_task_id'].decode()
            target_shard = int(data[b'target_shard'])

            # Get workflow reference
            workflow_ref = data.get(b'workflow_ref')
            if not workflow_ref:
                logger.error(f"Missing workflow_ref for child workflow {child_workflow_id}")
                return True  # ACK malformed message

            workflow_ref = workflow_ref.decode()
            logger.info(
                f"Submitting child workflow {child_workflow_id} from ref {workflow_ref} "
                f"to shard {target_shard} for parent {parent_workflow_id}"
            )
            
            # Parse inputs
            inputs = json.loads(data.get(b'inputs', b'{}'))
            
            # 1. Register parent-child relationship in global registry
            await self._register_parent_child(
                child_workflow_id=child_workflow_id,
                parent_workflow_id=parent_workflow_id,
                parent_task_id=parent_task_id,
                target_shard=target_shard
            )
            
            # 2. Submit workflow to target shard's loader
            await self._submit_to_loader(
                child_workflow_id=child_workflow_id,
                workflow_ref=workflow_ref,
                inputs=inputs,
                target_shard=target_shard,
                parent_workflow_id=parent_workflow_id,
                parent_task_id=parent_task_id
            )

            logger.info(
                f"Successfully submitted child workflow {child_workflow_id} to shard {target_shard}"
            )
            
        except Exception as e:
            logger.error(
                f"Failed to process workflow submission: {e}",
                exc_info=True,
                extra={'message_id': message_id, 'stream': stream}
            )
            # Log to Redis for queryability
            await self.log_worker_error(
                "process_workflow_submission",
                e,
                workflow_id=parent_workflow_id if 'parent_workflow_id' in locals() else None,
                child_workflow_id=child_workflow_id if 'child_workflow_id' in locals() else None,
                stream=stream,
                message_id=message_id
            )
            # Don't raise - let message be reprocessed later
    
    async def _register_parent_child(
        self,
        child_workflow_id: str,
        parent_workflow_id: str,
        parent_task_id: str,
        target_shard: int
    ):
        """
        Register parent-child relationship in global registry.
        
        Uses shard 0 for global registry to ensure consistency.
        """
        # Global registry key on shard 0
        registry_key = default_sharding.get_global_key(
            f"workflow:children:{child_workflow_id}"
        )
        
        # Store parent-child mapping
        await self.redis.hset(
            registry_key,
            mapping={
                b'parent_workflow_id': parent_workflow_id.encode(),
                b'parent_task_id': parent_task_id.encode(),
                b'parent_shard': str(default_sharding.get_shard(parent_workflow_id)).encode(),
                b'child_shard': str(target_shard).encode(),
                b'status': b'pending',
                b'created_at': datetime.utcnow().isoformat().encode()
            }
        )
        
        # Add to parent's children set for tracking
        parent_children_key = default_sharding.get_workflow_key(
            "children",
            parent_workflow_id
        )
        await self.redis.sadd(parent_children_key, child_workflow_id)
        
        # Set expiry on registry (30 days)
        await self.redis.expire(registry_key, 30 * 86400)
        
        logger.debug(
            f"Registered parent-child: {parent_workflow_id} -> {child_workflow_id}"
        )
    
    async def _submit_to_loader(
        self,
        child_workflow_id: str,
        workflow_ref: str,
        inputs: Dict[str, Any],
        target_shard: int,
        parent_workflow_id: str,
        parent_task_id: str
    ):
        """
        Submit workflow to target shard's loader stream.
        """
        # Target shard's loader stream
        loader_stream = default_sharding.get_stream_key(
            "workflow:load",
            shard=target_shard
        )
        
        # Build submission data
        submission_data = {
            b'workflow_id': child_workflow_id.encode(),
            b'workflow_ref': workflow_ref.encode(),  # Always required now
            b'inputs': json.dumps(inputs).encode(),
            b'is_child': b'true',
            b'parent_workflow_id': parent_workflow_id.encode(),
            b'parent_task_id': parent_task_id.encode(),
            b'timestamp': datetime.utcnow().isoformat().encode()
        }
        
        # Submit to loader
        await self.redis.xadd(loader_stream, submission_data)
        
        logger.debug(
            f"Submitted workflow {child_workflow_id} to loader on shard {target_shard}"
        )
    
    async def on_initialize(self):
        """Initialize worker resources."""
        await super().on_initialize()
        logger.info(
            f"WorkflowSubmissionWorker initialized with shards {self.config.assigned_shards} "
            f"monitoring streams: {self.get_base_streams()}"
        )
    
    async def on_shutdown(self):
        """Clean up worker resources."""
        await super().on_shutdown()
        logger.info(f"WorkflowSubmissionWorker with shards {self.config.assigned_shards} shut down")