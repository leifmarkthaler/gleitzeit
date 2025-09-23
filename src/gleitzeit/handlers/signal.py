"""
Signal handler for workflow synchronization.

Validates signal tasks and returns WAITING status for SignalWorker to handle.
Does NOT handle actual signal coordination - that's SignalWorker's job.
"""

import time
import json
from typing import Dict, Any, List, Optional
import logging

from .base import BaseHandler
from .registry import HandlerRegistry
from ..core.models import Task, TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode

logger = logging.getLogger(__name__)


@HandlerRegistry.register
class SignalHandler(BaseHandler):
    """
    Handle signal tasks for workflow synchronization.

    This handler:
    - Validates signal parameters
    - Returns WAITING status for SignalWorker
    - Does NOT handle actual signal coordination
    - Supports wait, wait_any, and wait_all operations
    """

    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """Get signal handler capabilities"""
        return {
            'protocol': 'signal/v1',
            'task_types': ['signal', 'sync', 'event'],
            'methods': {
                'signal/wait': {
                    'description': 'Wait for a specific signal',
                    'required': ['signal_name'],
                    'optional': ['timeout']
                },
                'signal/wait_any': {
                    'description': 'Wait for any of multiple signals',
                    'required': ['signal_names'],
                    'optional': ['timeout']
                },
                'signal/wait_all': {
                    'description': 'Wait for all of multiple signals',
                    'required': ['signal_names'],
                    'optional': ['timeout']
                },
                'signal/send': {
                    'description': 'Send a signal to current workflow or specific workflows',
                    'required': ['signal_name'],
                    'optional': ['payload', 'target_workflows']  # List of workflow IDs
                },
                'signal/broadcast': {
                    'description': 'Broadcast a signal system-wide (not workflow-specific)',
                    'required': ['signal_name'],
                    'optional': ['payload']
                }
            }
        }

    async def validate(self, task: Task) -> None:
        """Validate signal task parameters"""
        await super().validate(task)

        if task.method == 'signal/wait':
            signal_name = task.params.get('signal_name')
            if not signal_name:
                raise GleitzeitError(
                    "Missing required parameter 'signal_name'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id, 'method': task.method}
                )

            if not isinstance(signal_name, str):
                raise GleitzeitError(
                    f"Signal name must be a string, got {type(signal_name).__name__}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'signal_name': signal_name}
                )

            # Validate timeout if present
            timeout = task.params.get('timeout')
            if timeout is not None:
                if not isinstance(timeout, (int, float)):
                    raise GleitzeitError(
                        f"Timeout must be a number, got {type(timeout).__name__}",
                        code=ErrorCode.TASK_PARAMETER_ERROR,
                        data={'task_id': task.id, 'timeout': timeout}
                    )
                if timeout < 0:
                    raise GleitzeitError(
                        f"Timeout cannot be negative: {timeout}",
                        code=ErrorCode.TASK_PARAMETER_ERROR,
                        data={'task_id': task.id, 'timeout': timeout}
                    )

        elif task.method in ['signal/wait_any', 'signal/wait_all']:
            signal_names = task.params.get('signal_names')
            if not signal_names:
                raise GleitzeitError(
                    "Missing required parameter 'signal_names'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id, 'method': task.method}
                )

            if not isinstance(signal_names, list):
                raise GleitzeitError(
                    f"Signal names must be a list, got {type(signal_names).__name__}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'signal_names': signal_names}
                )

            if len(signal_names) == 0:
                raise GleitzeitError(
                    "Signal names list cannot be empty",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id}
                )

            # Validate each signal name
            for idx, name in enumerate(signal_names):
                if not isinstance(name, str):
                    raise GleitzeitError(
                        f"Signal name at index {idx} must be a string, got {type(name).__name__}",
                        code=ErrorCode.TASK_PARAMETER_ERROR,
                        data={'task_id': task.id, 'index': idx, 'value': name}
                    )

            # Check for duplicates
            unique_names = set(signal_names)
            if len(unique_names) != len(signal_names):
                raise GleitzeitError(
                    "Duplicate signal names not allowed",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'signal_names': signal_names}
                )

            # Validate timeout
            timeout = task.params.get('timeout')
            if timeout is not None:
                if not isinstance(timeout, (int, float)):
                    raise GleitzeitError(
                        f"Timeout must be a number, got {type(timeout).__name__}",
                        code=ErrorCode.TASK_PARAMETER_ERROR,
                        data={'task_id': task.id, 'timeout': timeout}
                    )
                if timeout < 0:
                    raise GleitzeitError(
                        f"Timeout cannot be negative: {timeout}",
                        code=ErrorCode.TASK_PARAMETER_ERROR,
                        data={'task_id': task.id, 'timeout': timeout}
                    )

        elif task.method == 'signal/send':
            signal_name = task.params.get('signal_name')
            if not signal_name:
                raise GleitzeitError(
                    "Missing required parameter 'signal_name'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id, 'method': task.method}
                )

            if not isinstance(signal_name, str):
                raise GleitzeitError(
                    f"Signal name must be a string, got {type(signal_name).__name__}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'signal_name': signal_name}
                )

            # Validate payload if present
            payload = task.params.get('payload')
            if payload is not None and not isinstance(payload, dict):
                raise GleitzeitError(
                    f"Payload must be a dictionary, got {type(payload).__name__}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'payload': payload}
                )

            # Validate target_workflows if present
            target_workflows = task.params.get('target_workflows')
            if target_workflows is not None:
                if not isinstance(target_workflows, list):
                    raise GleitzeitError(
                        f"Target workflows must be a list, got {type(target_workflows).__name__}",
                        code=ErrorCode.TASK_PARAMETER_ERROR,
                        data={'task_id': task.id, 'target_workflows': target_workflows}
                    )
                for wf_id in target_workflows:
                    if not isinstance(wf_id, str):
                        raise GleitzeitError(
                            f"Each workflow ID must be a string, got {type(wf_id).__name__}",
                            code=ErrorCode.TASK_PARAMETER_ERROR,
                            data={'task_id': task.id, 'invalid_workflow': wf_id}
                        )

        elif task.method == 'signal/broadcast':
            signal_name = task.params.get('signal_name')
            if not signal_name:
                raise GleitzeitError(
                    "Missing required parameter 'signal_name'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id, 'method': task.method}
                )

            if not isinstance(signal_name, str):
                raise GleitzeitError(
                    f"Signal name must be a string, got {type(signal_name).__name__}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'signal_name': signal_name}
                )

            # Validate payload if present
            payload = task.params.get('payload')
            if payload is not None and not isinstance(payload, dict):
                raise GleitzeitError(
                    f"Payload must be a dictionary, got {type(payload).__name__}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'payload': payload}
                )

    async def execute(self, task: Task) -> TaskResult:
        """Execute signal task - returns WAITING status for SignalWorker"""
        start_time = time.time()

        try:
            # Record metrics if available
            if self.metrics:
                metric_start = await self.metrics.record_task_start()

            # Validate task
            await self.validate(task)

            # Handle based on method
            if task.method == 'signal/wait':
                result = await self._handle_wait(task)
            elif task.method == 'signal/wait_any':
                result = await self._handle_wait_any(task)
            elif task.method == 'signal/wait_all':
                result = await self._handle_wait_all(task)
            elif task.method == 'signal/send':
                result = await self._handle_send(task)
            elif task.method == 'signal/broadcast':
                result = await self._handle_broadcast(task)
            else:
                raise GleitzeitError(
                    f"Unknown method: {task.method}",
                    code=ErrorCode.METHOD_NOT_SUPPORTED,
                    data={'task_id': task.id, 'method': task.method}
                )

            # Record success metrics
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=True)

            return result

        except GleitzeitError:
            # Record failure metrics
            if self.metrics and 'metric_start' in locals():
                await self.metrics.record_task_end(metric_start, success=False)
            raise

        except Exception as e:
            # Record failure metrics
            if self.metrics and 'metric_start' in locals():
                await self.metrics.record_task_end(metric_start, success=False, error=e)

            raise GleitzeitError(
                f"Signal execution failed: {e}",
                code=ErrorCode.TASK_EXECUTION_FAILED,
                data={'task_id': task.id},
                cause=e
            )

    async def _handle_wait(self, task: Task) -> TaskResult:
        """Handle wait for single signal"""
        signal_name = task.params['signal_name']
        timeout = task.params.get('timeout')

        logger.info(f"Task {task.id} waiting for signal '{signal_name}'")

        # Return WAITING status for SignalWorker to handle
        return self.create_result(
            task=task,
            status=TaskStatus.WAITING,
            metadata={
                'signal_type': 'wait',
                'signal_name': signal_name,
                'timeout': timeout,
                'waiting_since': time.time()
            }
        )

    async def _handle_wait_any(self, task: Task) -> TaskResult:
        """Handle wait for any of multiple signals"""
        signal_names = task.params['signal_names']
        timeout = task.params.get('timeout')

        logger.info(f"Task {task.id} waiting for any of {len(signal_names)} signals")

        # Return WAITING status
        return self.create_result(
            task=task,
            status=TaskStatus.WAITING,
            metadata={
                'signal_type': 'wait_any',
                'signal_names': signal_names,
                'timeout': timeout,
                'waiting_since': time.time()
            }
        )

    async def _handle_wait_all(self, task: Task) -> TaskResult:
        """Handle wait for all of multiple signals"""
        signal_names = task.params['signal_names']
        timeout = task.params.get('timeout')

        logger.info(f"Task {task.id} waiting for all of {len(signal_names)} signals")

        # Return WAITING status with tracking metadata
        return self.create_result(
            task=task,
            status=TaskStatus.WAITING,
            metadata={
                'signal_type': 'wait_all',
                'signal_names': signal_names,
                'pending_signals': signal_names.copy(),  # Track which signals are still pending
                'received_signals': [],  # Track which signals have been received
                'timeout': timeout,
                'waiting_since': time.time()
            }
        )

    async def _handle_send(self, task: Task) -> TaskResult:
        """Handle sending a signal to current or specific workflows"""
        signal_name = task.params['signal_name']
        payload = task.params.get('payload', {})
        target_workflows = task.params.get('target_workflows')

        # Default to current workflow if no targets specified
        if target_workflows is None:
            target_workflows = [task.workflow_id]

        logger.info(
            f"Task {task.id} sending signal '{signal_name}' to "
            f"{len(target_workflows)} workflow(s)"
        )

        # Return COMPLETED status with signal emission metadata
        return self.create_result(
            task=task,
            status=TaskStatus.COMPLETED,
            result={
                'signal_sent': signal_name,
                'target_workflows': target_workflows,
                'payload': payload
            },
            metadata={
                'signal_action': 'send',
                'signal_name': signal_name,
                'target_workflows': target_workflows,
                'payload': payload,
                'emit_signal': True
            }
        )

    async def _handle_broadcast(self, task: Task) -> TaskResult:
        """Handle broadcasting a signal system-wide"""
        signal_name = task.params['signal_name']
        payload = task.params.get('payload', {})

        logger.info(f"Task {task.id} broadcasting signal '{signal_name}' system-wide")

        # Return COMPLETED status with broadcast metadata
        return self.create_result(
            task=task,
            status=TaskStatus.COMPLETED,
            result={
                'signal_broadcast': signal_name,
                'payload': payload
            },
            metadata={
                'signal_action': 'broadcast',
                'signal_name': signal_name,
                'payload': payload,
                'emit_signal': True
            }
        )
