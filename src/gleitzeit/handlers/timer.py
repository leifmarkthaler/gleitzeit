"""
Timer handler for sleep and scheduling tasks.

This handler validates timer parameters and returns scheduling information
for the TimerWorker to handle. It does NOT actually sleep or wait.
"""

import time
from datetime import datetime, timedelta
from typing import Dict, Any
import logging

from .base import BaseHandler
from .registry import HandlerRegistry
from ..core.models import Task, TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode

logger = logging.getLogger(__name__)


@HandlerRegistry.register
class TimerHandler(BaseHandler):
    """
    Handle timer tasks - returns scheduling info for TimerWorker.

    This handler:
    - Validates timer parameters
    - Calculates wake times
    - Returns SCHEDULED status for TimerWorker
    - Does NOT actually sleep (that's TimerWorker's job)
    """

    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """Get timer handler capabilities"""
        return {
            'protocol': 'timer/v1',
            'task_types': ['timer', 'sleep', 'delay', 'schedule'],
            'methods': {
                'timer/sleep': {
                    'description': 'Sleep for specified duration',
                    'required': ['duration'],
                    'optional': []
                },
                'timer/wait_until': {
                    'description': 'Wait until specific time',
                    'required': ['timestamp'],
                    'optional': []
                },
                'timer/schedule': {
                    'description': 'Schedule recurring execution',
                    'required': ['interval'],
                    'optional': ['max_runs', 'start_time']
                }
            }
        }

    async def validate(self, task: Task) -> None:
        """Validate timer task parameters"""
        await super().validate(task)

        if task.method == 'timer/sleep':
            duration = task.params.get('duration')
            if duration is None:
                raise GleitzeitError(
                    "Missing required parameter 'duration'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id, 'method': task.method}
                )

            if not isinstance(duration, (int, float)):
                raise GleitzeitError(
                    f"Duration must be a number, got {type(duration).__name__}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'duration': duration}
                )

            if duration < 0:
                raise GleitzeitError(
                    f"Duration cannot be negative: {duration}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'duration': duration}
                )

            # Warn about very long durations
            max_duration = self.config.get('max_duration', 86400)  # 24 hours default
            if duration > max_duration:
                raise GleitzeitError(
                    f"Duration {duration}s exceeds maximum {max_duration}s",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'duration': duration, 'max': max_duration}
                )

        elif task.method == 'timer/wait_until':
            timestamp = task.params.get('timestamp')
            if timestamp is None:
                raise GleitzeitError(
                    "Missing required parameter 'timestamp'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id, 'method': task.method}
                )

            # Validate timestamp format
            if isinstance(timestamp, str):
                try:
                    datetime.fromisoformat(timestamp)
                except ValueError:
                    raise GleitzeitError(
                        f"Invalid timestamp format: {timestamp}",
                        code=ErrorCode.TASK_PARAMETER_ERROR,
                        data={'task_id': task.id, 'timestamp': timestamp}
                    )
            elif not isinstance(timestamp, (int, float)):
                raise GleitzeitError(
                    f"Timestamp must be a number or ISO string, got {type(timestamp).__name__}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'timestamp': timestamp}
                )

        elif task.method == 'timer/schedule':
            interval = task.params.get('interval')
            if interval is None:
                raise GleitzeitError(
                    "Missing required parameter 'interval'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id, 'method': task.method}
                )

            if not isinstance(interval, (int, float)):
                raise GleitzeitError(
                    f"Interval must be a number, got {type(interval).__name__}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'interval': interval}
                )

            if interval <= 0:
                raise GleitzeitError(
                    f"Interval must be positive: {interval}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'interval': interval}
                )

    async def execute(self, task: Task) -> TaskResult:
        """Execute timer task - returns scheduling info"""
        start_time = time.time()

        try:
            # Record metrics if available
            if self.metrics:
                metric_start = await self.metrics.record_task_start()

            # Validate task
            await self.validate(task)

            # Handle based on method
            if task.method == 'timer/sleep':
                result = await self._handle_sleep(task)
            elif task.method == 'timer/wait_until':
                result = await self._handle_wait_until(task)
            elif task.method == 'timer/schedule':
                result = await self._handle_schedule(task)
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
                f"Timer execution failed: {e}",
                code=ErrorCode.TASK_EXECUTION_FAILED,
                data={'task_id': task.id},
                cause=e
            )

    async def _handle_sleep(self, task: Task) -> TaskResult:
        """Handle sleep task"""
        duration = task.params['duration']

        if duration <= 0:
            # Immediate completion for zero/negative duration
            logger.debug(f"Task {task.id} has duration {duration}, completing immediately")
            return self.create_result(
                task=task,
                status=TaskStatus.COMPLETED,
                result={'slept': 0, 'actual_duration': 0}
            )

        # Calculate wake time
        wake_time = time.time() + duration

        logger.info(f"Task {task.id} scheduled to wake in {duration}s at {wake_time}")

        # Return SCHEDULED status for TimerWorker to handle
        return self.create_result(
            task=task,
            status=TaskStatus.SCHEDULED,
            metadata={
                'wake_time': wake_time,
                'duration': duration,
                'timer_type': 'sleep',
                'scheduled_at': time.time()
            }
        )

    async def _handle_wait_until(self, task: Task) -> TaskResult:
        """Handle wait_until task"""
        timestamp = task.params['timestamp']

        # Parse timestamp
        if isinstance(timestamp, str):
            try:
                target_dt = datetime.fromisoformat(timestamp)
                target_time = target_dt.timestamp()
            except ValueError as e:
                raise GleitzeitError(
                    f"Invalid timestamp format: {timestamp}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'timestamp': timestamp},
                    cause=e
                )
        else:
            target_time = float(timestamp)

        current_time = time.time()

        if target_time <= current_time:
            # Already past target time
            logger.debug(f"Task {task.id} target time {target_time} already passed")
            return self.create_result(
                task=task,
                status=TaskStatus.COMPLETED,
                result={
                    'reached': True,
                    'target_time': target_time,
                    'current_time': current_time
                }
            )

        wait_duration = target_time - current_time
        logger.info(f"Task {task.id} scheduled to wake at {target_time} (in {wait_duration:.1f}s)")

        # Return SCHEDULED status
        return self.create_result(
            task=task,
            status=TaskStatus.SCHEDULED,
            metadata={
                'wake_time': target_time,
                'timer_type': 'wait_until',
                'wait_duration': wait_duration,
                'scheduled_at': current_time
            }
        )

    async def _handle_schedule(self, task: Task) -> TaskResult:
        """Handle recurring schedule task"""
        interval = task.params['interval']
        max_runs = task.params.get('max_runs', 0)  # 0 = unlimited
        start_time = task.params.get('start_time')

        # Calculate first run time
        if start_time:
            if isinstance(start_time, str):
                start_dt = datetime.fromisoformat(start_time)
                next_run = start_dt.timestamp()
            else:
                next_run = float(start_time)

            # If start time is in the past, calculate next interval
            current_time = time.time()
            while next_run < current_time:
                next_run += interval
        else:
            # Start from now
            next_run = time.time() + interval

        logger.info(
            f"Task {task.id} scheduled with interval {interval}s, "
            f"next run at {next_run}, max_runs={max_runs}"
        )

        # Return SCHEDULED status with schedule metadata
        return self.create_result(
            task=task,
            status=TaskStatus.SCHEDULED,
            metadata={
                'wake_time': next_run,
                'timer_type': 'schedule',
                'interval': interval,
                'max_runs': max_runs,
                'runs_completed': 0,
                'scheduled_at': time.time()
            }
        )