"""
Workflow execution handler.

Handles workflow invocation as tasks, enabling workflow composition.
Maintains statelessness by returning metadata for workers to process.
"""

import uuid
import logging
from typing import Dict, Any, Optional

from .base import BaseHandler
from .registry import HandlerRegistry
from ..core.models import Task, TaskResult, TaskStatus
from ..core.sharding import default_sharding
from ..core.errors import GleitzeitError, ErrorCode

logger = logging.getLogger(__name__)


@HandlerRegistry.register
class WorkflowHandler(BaseHandler):
    """
    Handle workflow invocation as tasks.
    
    This handler is STATELESS:
    - Does NOT submit workflows directly
    - Does NOT access Redis or any external state
    - Returns metadata for workers to handle actual submission
    - Similar to SignalHandler pattern
    """
    
    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """Get workflow handler capabilities"""
        return {
            'protocol': 'workflow/v1',
            'task_types': ['workflow', 'subworkflow'],
            'methods': {
                'workflow/execute': {
                    'description': 'Execute a workflow and wait for completion',
                    'required': ['workflow_ref'],
                    'optional': ['inputs', 'timeout', 'shard_preference']
                }
            }
        }
    
    async def validate(self, task: Task) -> None:
        """Validate workflow task parameters"""
        await super().validate(task)

        if task.method == 'workflow/execute':
            # Must have workflow_ref
            workflow_ref = task.params.get('workflow_ref')

            if not workflow_ref:
                raise GleitzeitError(
                    "Missing required parameter 'workflow_ref'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id, 'method': task.method}
                )

            # Validate workflow_ref format
            if not isinstance(workflow_ref, str):
                raise GleitzeitError(
                    f"workflow_ref must be a string, got {type(workflow_ref).__name__}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'workflow_ref': workflow_ref}
                )

            # Validate inputs if provided
            inputs = task.params.get('inputs')
            if inputs is not None and not isinstance(inputs, dict):
                raise GleitzeitError(
                    f"inputs must be a dict, got {type(inputs).__name__}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id}
                )

            # Validate shard_preference if provided
            shard_pref = task.params.get('shard_preference')
            if shard_pref:
                valid_prefs = ['any', 'same']
                if not (shard_pref in valid_prefs or shard_pref.startswith('specific:')):
                    raise GleitzeitError(
                        f"Invalid shard_preference: {shard_pref}",
                        code=ErrorCode.TASK_PARAMETER_ERROR,
                        data={'task_id': task.id, 'valid': valid_prefs + ['specific:N']}
                    )
    
    async def execute(self, task: Task) -> TaskResult:
        """Execute workflow task - returns metadata for workers"""
        try:
            # Validate task
            await self.validate(task)

            # Only one method: workflow/execute
            if task.method == 'workflow/execute':
                return await self._handle_execute(task)
            else:
                raise GleitzeitError(
                    f"Unknown method: {task.method}",
                    code=ErrorCode.METHOD_NOT_SUPPORTED,
                    data={'task_id': task.id, 'method': task.method}
                )
        
        except GleitzeitError:
            raise
        except Exception as e:
            raise GleitzeitError(
                f"Workflow handler failed: {e}",
                code=ErrorCode.TASK_EXECUTION_FAILED,
                data={'task_id': task.id},
                cause=e
            )
    
    async def _handle_execute(self, task: Task) -> TaskResult:
        """
        Handle workflow execution.

        Always returns WAITING status - parent task waits for child workflow.
        TaskExecutionWorker will:
        1. Submit the child workflow
        2. Task waits for completion
        3. WorkflowMonitorWorker wakes task when child completes
        """

        # Generate child workflow ID
        child_workflow_id = f"{task.workflow_id}:child:{task.id}:{uuid.uuid4().hex[:8]}"

        # Determine target shard
        shard_preference = task.params.get('shard_preference', 'any')
        target_shard = self._determine_shard(shard_preference, task.workflow_id, child_workflow_id)

        logger.info(
            f"Task {task.id} requesting child workflow {child_workflow_id} "
            f"on shard {target_shard}"
        )

        # Always return WAITING - parent waits for child
        return self.create_result(
            task=task,
            status=TaskStatus.WAITING,
            metadata={
                'waiting_for': 'workflow',
                'child_workflow_id': child_workflow_id,
                'child_shard': target_shard,
                'workflow_ref': task.params['workflow_ref'],  # Required
                'workflow_inputs': task.params.get('inputs', {}),
                'parent_workflow_id': task.workflow_id,
                'parent_task_id': task.id,
                'timeout': task.params.get('timeout', task.timeout),
                'submit_workflow': True  # Flag for worker to submit
            }
        )
    
    def _determine_shard(self, preference: str, parent_workflow_id: str, child_workflow_id: str) -> int:
        """
        Determine target shard for child workflow.
        
        This is deterministic and doesn't access any external state.
        """
        if preference == 'same':
            # Use same shard as parent
            return default_sharding.get_shard(parent_workflow_id)
        elif preference.startswith('specific:'):
            # Use specified shard
            try:
                shard = int(preference.split(':')[1])
                if 0 <= shard < default_sharding.num_shards:
                    return shard
                else:
                    logger.warning(
                        f"Invalid shard {shard}, using default sharding"
                    )
                    return default_sharding.get_shard(child_workflow_id)
            except (IndexError, ValueError):
                logger.warning(
                    f"Invalid shard preference {preference}, using default"
                )
                return default_sharding.get_shard(child_workflow_id)
        else:
            # 'any' - use child's natural shard
            return default_sharding.get_shard(child_workflow_id)