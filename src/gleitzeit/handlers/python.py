"""
Python code execution handler.

Executes Python code in isolated subprocess for safety.
Supports code execution, expression evaluation, and file execution.

Error Handling:
- Code execution errors (syntax errors, runtime errors) are returned as structured errors
- Pool infrastructure failures trigger automatic fallback to individual subprocess execution
- The fallback mechanism ensures reliability while the pool provides performance

Pool Behavior:
- Uses subprocess pool for fast execution when enabled (default)
- Pool returns error responses for code failures without raising exceptions
- Only genuine pool failures (process crashes, communication errors) trigger fallback
- Fallback to individual subprocess is transparent to the caller
"""

import asyncio
import json
import tempfile
import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional
import logging

from .base import BaseHandler
from .registry import HandlerRegistry
from ..core.models import Task, TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode, TaskTimeoutError
from ..core.subprocess_pool import get_subprocess_pool, PythonSubprocessPool
from ..core.file_operations import get_file_operations

logger = logging.getLogger(__name__)


@HandlerRegistry.register
class PythonHandler(BaseHandler):
    """
    Execute Python code in subprocess.

    This handler:
    - Executes Python code in isolated subprocess
    - Supports code, eval, and file execution
    - Returns execution results or errors
    - Does NOT handle dependencies (they're pre-resolved)
    - Uses subprocess pooling for performance
    """

    def __init__(self, config: Optional[Dict] = None):
        """Initialize Python handler with optional subprocess pool

        The handler uses a subprocess pool for performance by default.
        Pool failures automatically fallback to individual subprocess execution.
        """
        super().__init__(config)

        # Check if pooling is enabled
        self.use_pool = self.config.get('subprocess_pool_enabled', True)
        self.pool: Optional[PythonSubprocessPool] = None
        self._pool_initialized = False

        if self.use_pool:
            # Get pool configuration
            pool_min_size = self.config.get('subprocess_pool_min_size', 2)
            pool_max_size = self.config.get('subprocess_pool_max_size', 10)

            # Get or create the global pool
            self.pool = get_subprocess_pool(
                min_size=pool_min_size,
                max_size=pool_max_size
            )

            # Schedule pool initialization
            # We'll initialize on first use to avoid blocking during handler creation
            logger.info(f"Python handler will use subprocess pool (min={pool_min_size}, max={pool_max_size})")
        else:
            logger.info("Python handler using individual subprocesses (pooling disabled)")

        # Note: File operations removed - use File Handler for file-based tasks

    async def async_init(self):
        """Asynchronously initialize the handler

        This eagerly initializes the subprocess pool to avoid delays on first use.
        """
        if self.use_pool and self.pool and not self._pool_initialized:
            try:
                logger.info("Eagerly initializing subprocess pool...")
                await self.pool.initialize()
                self._pool_initialized = True
                logger.info("Subprocess pool initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to eagerly initialize pool: {e}. Will initialize on first use.")

    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """Get Python handler capabilities"""
        return {
            'protocol': 'python/v1',
            'task_types': ['python', 'script', 'py'],  # For backward compatibility
            'methods': {
                'python/execute': {
                    'description': 'Execute Python code block',
                    'required': ['code'],
                    'optional': ['inputs', 'timeout', 'env']
                },
                'python/eval': {
                    'description': 'Evaluate Python expression',
                    'required': ['expression'],
                    'optional': ['context', 'timeout']
                }
            }
        }

    async def execute(self, task: Task) -> TaskResult:
        """Execute Python task"""
        start_time = asyncio.get_event_loop().time()

        try:
            # Record metrics if available
            if self.metrics:
                metric_start = await self.metrics.record_task_start()

            # Validate task
            await self.validate(task)

            # Execute based on method
            if task.method == 'python/execute':
                result = await self._execute_code(task)
            elif task.method == 'python/eval':
                result = await self._eval_expression(task)
            else:
                raise GleitzeitError(
                    f"Unknown method: {task.method}",
                    code=ErrorCode.METHOD_NOT_SUPPORTED,
                    data={'task_id': task.id, 'method': task.method}
                )

            # Record success metrics
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=True)

            return self.create_result(
                task=task,
                status=TaskStatus.COMPLETED,
                result=result,
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

        except asyncio.TimeoutError:
            # Record failure metrics
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=False)

            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=f"Task timed out after {task.timeout or 300}s",
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

        except GleitzeitError as e:
            # Record failure metrics
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=False, error=e)

            # Check if it's a HandlerExecutionError
            from ..core.errors import HandlerExecutionError
            if isinstance(e, HandlerExecutionError):
                metadata = {
                    'error_type': 'HandlerExecutionError',
                    'handler_type': e.handler_type,
                    'original_error': e.original_error,
                    'original_error_type': e.original_error_type,
                    'error_code': e.code.value,
                    'error_data': e.data
                }
            else:
                metadata = {'error_code': e.code.value, 'error_data': e.data}

            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=str(e),
                metadata=metadata,
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

        except Exception as e:
            # Record failure metrics
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=False, error=e)

            logger.error(f"Python execution failed: {e}", exc_info=True)

            # Use HandlerExecutionError for consistent error handling
            from ..core.errors import HandlerExecutionError

            handler_error = HandlerExecutionError(
                message=f"Python handler execution failed: {str(e)}",
                task_id=task.id,
                handler_type="python",
                original_error=str(e),
                original_error_type=type(e).__name__
            )

            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=str(handler_error),
                metadata={
                    'error_type': 'HandlerExecutionError',
                    'handler_type': 'python',
                    'original_error': str(e),
                    'original_error_type': type(e).__name__
                },
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

    async def _execute_code(self, task: Task) -> Any:
        """Execute Python code block

        Supports multiple execution modes:
        - 'container': Execute in isolated Docker container (most secure)
        - 'pool': Use subprocess pool for performance (default)
        - 'subprocess': Individual subprocess execution

        Code execution errors (syntax, runtime) are handled and returned.
        Pool infrastructure failures trigger automatic fallback to subprocess.
        """
        code = task.params['code']
        inputs = task.params.get('inputs', {})
        env = task.params.get('env', {})
        timeout = task.timeout or self.config.get('default_timeout', 300)

        # Check execution mode
        exec_mode = self.config.get('execution_mode', 'pool')

        # Container execution mode - most secure, isolated
        if exec_mode == 'container':
            from ..core.container_executor import ContainerExecutor

            # Get container configuration
            container_config = self.config.get('container_config', {})
            executor = ContainerExecutor(container_config)

            # Check if Docker is available
            if not executor.is_available():
                logger.warning("Container execution requested but Docker not available, falling back to pool")
                exec_mode = 'pool'  # Fallback to pool
            else:
                try:
                    logger.info(f"Executing Python code in container for task {task.id}")
                    container_result = await executor.execute(
                        code=code,
                        inputs=inputs,
                        timeout=timeout,
                        runtime='python'
                    )

                    # Check if container execution failed
                    if not container_result.get('success', False):
                        from ..core.errors import HandlerExecutionError
                        error_msg = container_result.get('output', 'Container execution failed')

                        raise HandlerExecutionError(
                            message=f"Container execution failed: {error_msg}",
                            task_id=task.id,
                            handler_type="python",
                            original_error=error_msg,
                            original_error_type="ContainerExecutionError",
                            data={
                                'exit_code': container_result.get('exit_code'),
                                'container_id': container_result.get('container_id'),
                                'output': error_msg
                            }
                        )

                    # Return the result from container
                    return container_result.get('result', container_result.get('output'))

                except Exception as e:
                    if isinstance(e, asyncio.TimeoutError):
                        raise TaskTimeoutError(
                            f"Container execution exceeded {timeout}s timeout",
                            task_id=task.id,
                            timeout_seconds=timeout
                        )
                    # Re-raise HandlerExecutionError as-is
                    if 'HandlerExecutionError' in type(e).__name__:
                        raise
                    # Wrap other errors
                    logger.error(f"Container execution failed: {e}")
                    from ..core.errors import HandlerExecutionError
                    raise HandlerExecutionError(
                        message=f"Container execution error: {str(e)}",
                        task_id=task.id,
                        handler_type="python",
                        original_error=str(e),
                        original_error_type=type(e).__name__
                    )

        # Use subprocess pool if enabled (default mode)
        if exec_mode == 'pool' and self.use_pool and self.pool:
            try:
                # Initialize pool if needed
                if not self._pool_initialized:
                    await self.pool.initialize()
                    self._pool_initialized = True

                # Execute using pool
                result = await asyncio.wait_for(
                    self.pool.execute_code(code, inputs),
                    timeout=timeout
                )

                # Check if execution failed (e.g., syntax error)
                if isinstance(result, dict) and result.get("success") is False:
                    from ..core.errors import HandlerExecutionError
                    error_msg = result.get("error", "Unknown error")
                    traceback_str = result.get("traceback", "")

                    raise HandlerExecutionError(
                        message=f"Python execution failed: {error_msg}",
                        task_id=task.id,
                        handler_type="python",
                        original_error=traceback_str,
                        original_error_type="CodeExecutionError",
                        data={
                            'error': error_msg,
                            'traceback': traceback_str
                        }
                    )

                return result

            except asyncio.TimeoutError:
                raise TaskTimeoutError(
                    task_id=task.id,
                    timeout=timeout
                )
            except GleitzeitError:
                # Re-raise GleitzeitErrors (including HandlerExecutionError)
                # These are code execution errors, not pool failures
                # Examples: syntax errors, runtime errors, undefined variables
                raise
            except Exception as e:
                # Fallback to regular subprocess only for actual pool errors
                # Examples: process crash, communication failure, pool exhaustion
                # This ensures reliability even if the pool encounters issues
                logger.warning(f"Pool execution failed, falling back to subprocess: {e}")
                return await self._execute_code_subprocess(task, code, inputs, env, timeout)

        else:
            # Use regular subprocess
            return await self._execute_code_subprocess(task, code, inputs, env, timeout)

    async def _execute_code_subprocess(self, task: Task, code: str, inputs: Dict, env: Dict, timeout: float) -> Any:
        """Execute Python code in a new subprocess (fallback/non-pooled mode)"""
        # Create temporary file with code
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            # Wrap code to capture result
            wrapped = f'''#!/usr/bin/env python3
import json
import sys

# Provided inputs (already resolved by workflow system)
inputs = {json.dumps(inputs)}

# User code
{code}

# Output result if defined
if 'result' in locals():
    print(json.dumps(result))
elif 'output' in locals():
    print(json.dumps(output))
'''
            f.write(wrapped)
            temp_path = f.name

        try:
            # Prepare environment
            process_env = os.environ.copy()
            if env:
                process_env.update(env)

            # Execute in subprocess
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env
            )

            # Wait with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise

            # Check return code
            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace').strip()
                from ..core.errors import HandlerExecutionError

                # Extract the actual Python error from stderr
                error_lines = error_msg.split('\n')
                # Get the last line which usually contains the actual error
                actual_error = error_lines[-1] if error_lines else error_msg

                raise HandlerExecutionError(
                    message=f"Python execution failed: {actual_error}",
                    task_id=task.id,
                    handler_type="python",
                    original_error=error_msg[:1000],  # Full traceback in metadata
                    original_error_type="SubprocessError",
                    data={
                        'returncode': process.returncode,
                        'stderr': error_msg[:1000],
                        'traceback': error_msg[:1000]
                    }
                )

            # Parse output
            output = stdout.decode('utf-8', errors='replace').strip()
            if output:
                try:
                    return json.loads(output)
                except json.JSONDecodeError:
                    # Return as string if not JSON
                    return output
            return None

        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)

    async def _eval_expression(self, task: Task) -> Any:
        """Evaluate Python expression"""
        expression = task.params['expression']
        context = task.params.get('context', {})
        timeout = task.timeout or self.config.get('default_timeout', 300)

        # Create evaluation code
        code = f'''
import json
context = {json.dumps(context)}
result = eval({json.dumps(expression)}, {{"__builtins__": __builtins__}}, context)
print(json.dumps(result) if result is not None else "null")
'''

        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_path = f.name

        try:
            # Execute in subprocess
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Wait with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise

            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace')
                raise GleitzeitError(
                    f"Expression evaluation failed: {error_msg}",
                    code=ErrorCode.TASK_EXECUTION_FAILED,
                    data={'task_id': task.id, 'expression': expression}
                )

            output = stdout.decode('utf-8', errors='replace').strip()
            return json.loads(output) if output and output != "null" else None

        finally:
            Path(temp_path).unlink(missing_ok=True)

