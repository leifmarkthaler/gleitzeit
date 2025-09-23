"""
File Handler for Gleitzeit 0.0.7

Provides file operations as a handler that can be used in workflows.
Uses unified file operations core for consistency with workflow loader.
"""

import asyncio
import logging
from typing import Dict, Any
from pathlib import Path

from .base import BaseHandler
from .registry import HandlerRegistry
from ..core.models import TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode, HandlerExecutionError
from ..core.file_operations import get_handler_file_operations

logger = logging.getLogger(__name__)


@HandlerRegistry.register
class FileHandler(BaseHandler):
    """
    Handler for file operations in workflows.

    Capabilities:
    - Load files (text, images, documents)
    - List directory contents
    - Check file existence
    - Get file metadata
    """

    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """Return handler capabilities"""
        return {
            'protocol': 'file/v1',
            'task_types': ['file', 'file_load', 'file_list'],
            'methods': {
                'file/load': {
                    'description': 'Load a file and return its content',
                    'required': ['path'],
                    'optional': ['encoding', 'as_base64', 'cache']
                },
                'file/load_multiple': {
                    'description': 'Load multiple files',
                    'required': ['paths'],
                    'optional': ['encoding', 'as_base64', 'cache']
                },
                'file/list': {
                    'description': 'List files in a directory',
                    'required': ['directory'],
                    'optional': ['pattern', 'recursive', 'include_hidden']
                },
                'file/exists': {
                    'description': 'Check if a file exists',
                    'required': ['path'],
                    'optional': []
                },
                'file/metadata': {
                    'description': 'Get file metadata',
                    'required': ['path'],
                    'optional': []
                }
            }
        }

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)

        # Use unified file operations with handler context
        self.file_ops = get_handler_file_operations()

        # Store config for any handler-specific overrides
        self.handler_config = config or {}

    async def execute(self, task) -> TaskResult:
        """Execute file operation with comprehensive error handling"""
        start_time = asyncio.get_event_loop().time()

        try:
            # Record metrics if available
            if self.metrics:
                metric_start = await self.metrics.record_task_start()

            # Validate task
            await self.validate(task)

            # Execute based on method
            if task.method == 'file/load':
                result = await self._load_file(task)
            elif task.method == 'file/load_multiple':
                result = await self._load_multiple_files(task)
            elif task.method == 'file/list':
                result = await self._list_files(task)
            elif task.method == 'file/exists':
                result = await self._check_file_exists(task)
            elif task.method == 'file/metadata':
                result = await self._get_file_metadata(task)
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

        except GleitzeitError as e:
            # Record failure metrics
            if self.metrics:
                await self.metrics.record_task_end(metric_start, success=False, error=e)

            # Check if it's a HandlerExecutionError
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

            logger.error(f"File operation failed: {e}", exc_info=True)

            # Use HandlerExecutionError for consistent error handling
            handler_error = HandlerExecutionError(
                message=f"File handler execution failed: {str(e)}",
                task_id=task.id,
                handler_type="file",
                original_error=str(e),
                original_error_type=type(e).__name__
            )

            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=str(handler_error),
                metadata={
                    'error_type': 'HandlerExecutionError',
                    'handler_type': 'file',
                    'original_error': str(e),
                    'original_error_type': type(e).__name__
                },
                duration_seconds=asyncio.get_event_loop().time() - start_time
            )

    async def _load_file(self, task) -> Dict[str, Any]:
        """Load a single file using unified file operations"""
        params = task.params
        file_path = params['path']
        encoding = params.get('encoding', 'utf-8')
        as_base64 = params.get('as_base64', False)

        try:
            # Use unified file operations
            result = await self.file_ops.load_file(
                path=file_path,
                encoding=encoding,
                as_base64=as_base64,
                validate=True
            )

            # Add task context to metadata
            result['metadata']['task_id'] = task.id

            return result

        except GleitzeitError:
            # Re-raise Gleitzeit errors as-is (already properly formatted)
            raise
        except Exception as e:
            # Wrap unexpected errors in HandlerExecutionError
            raise HandlerExecutionError(
                message=f"Unexpected error loading file {file_path}: {str(e)}",
                task_id=task.id,
                handler_type="file",
                original_error=str(e),
                original_error_type=type(e).__name__
            )

    async def _load_multiple_files(self, task) -> Dict[str, Any]:
        """Load multiple files"""
        params = task.params
        file_paths = params['paths']
        encoding = params.get('encoding', 'utf-8')
        as_base64 = params.get('as_base64', False)

        results = []
        for file_path in file_paths:
            try:
                # Create a sub-task for each file
                sub_task = type(task)(
                    id=f"{task.id}_{Path(file_path).name}",
                    workflow_id=task.workflow_id,
                    name=f"Load {file_path}",
                    protocol=task.protocol,
                    method="file/load",
                    params={
                        'path': file_path,
                        'encoding': encoding,
                        'as_base64': as_base64
                    }
                )

                file_result = await self._load_file(sub_task)

                results.append({
                    'path': file_path,
                    'status': 'loaded',
                    'content': file_result['content'],
                    'metadata': file_result['metadata']
                })

            except Exception as e:
                results.append({
                    'path': file_path,
                    'status': 'failed',
                    'error': str(e),
                    'error_type': type(e).__name__
                })

        return {
            'files': results,
            'total': len(file_paths),
            'loaded': len([r for r in results if r['status'] == 'loaded']),
            'failed': len([r for r in results if r['status'] == 'failed'])
        }

    async def _list_files(self, task) -> Dict[str, Any]:
        """List files in a directory using unified file operations"""
        params = task.params
        directory = params['directory']
        pattern = params.get('pattern', '*')
        recursive = params.get('recursive', False)
        include_hidden = params.get('include_hidden', False)

        try:
            # Use unified file operations
            result = await self.file_ops.list_directory(
                directory=directory,
                pattern=pattern,
                recursive=recursive,
                include_hidden=include_hidden,
                validate=True
            )

            # Add task context to metadata
            result['metadata']['task_id'] = task.id

            return result

        except GleitzeitError:
            # Re-raise Gleitzeit errors as-is (already properly formatted)
            raise
        except Exception as e:
            # Wrap unexpected errors in HandlerExecutionError
            raise HandlerExecutionError(
                message=f"Unexpected error listing directory {directory}: {str(e)}",
                task_id=task.id,
                handler_type="file",
                original_error=str(e),
                original_error_type=type(e).__name__
            )

    async def _check_file_exists(self, task) -> Dict[str, Any]:
        """Check if a file exists using unified file operations"""
        params = task.params
        file_path = params['path']

        try:
            # Use unified file operations
            result = await self.file_ops.check_file_exists(
                path=file_path,
                get_details=True
            )

            # Add task context to metadata
            if 'metadata' not in result:
                result['metadata'] = {}
            result['metadata']['task_id'] = task.id

            return result

        except GleitzeitError:
            # Re-raise Gleitzeit errors as-is (already properly formatted)
            raise
        except Exception as e:
            # Wrap unexpected errors in HandlerExecutionError
            raise HandlerExecutionError(
                message=f"Unexpected error checking file exists {file_path}: {str(e)}",
                task_id=task.id,
                handler_type="file",
                original_error=str(e),
                original_error_type=type(e).__name__
            )

    async def _get_file_metadata(self, task) -> Dict[str, Any]:
        """Get file metadata using unified file operations"""
        params = task.params
        file_path = params['path']

        try:
            # Use unified file operations
            result = await self.file_ops.get_file_metadata(
                path=file_path,
                include_hash=True,
                validate=True
            )

            # Add task context to metadata
            result['metadata']['task_id'] = task.id

            return result

        except GleitzeitError:
            # Re-raise Gleitzeit errors as-is (already properly formatted)
            raise
        except Exception as e:
            # Wrap unexpected errors in HandlerExecutionError
            raise HandlerExecutionError(
                message=f"Unexpected error getting file metadata for {file_path}: {str(e)}",
                task_id=task.id,
                handler_type="file",
                original_error=str(e),
                original_error_type=type(e).__name__
            )


    async def cleanup(self):
        """Cleanup handler resources"""
        pass