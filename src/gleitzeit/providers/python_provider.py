"""
Clean Python Provider - Pure Protocol Implementation
Executes Python files locally or delegates to DockerHub for container execution
"""

import logging
from typing import Dict, Any, Optional, List, Type
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import shutil

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core.errors import InvalidParameterError, TaskExecutionError
from gleitzeit.core.logging_mixin import LoggingMixin

logger = logging.getLogger(__name__)


class PythonProvider(ProtocolProvider, LoggingMixin):
    """
    Clean Python file execution provider - pure protocol implementation
    
    This provider focuses on Python protocol execution only.
    Container management is delegated to DockerHub when needed.
    
    Security model:
    - Local execution: For trusted/owned code only (subprocess isolation)
    - Container execution: Delegated to DockerHub via ResourceManager
    - NO arbitrary code execution via exec() or eval()
    
    Separation of concerns:
    - PythonProvider: Executes Python protocols (local subprocess or via endpoint)
    - DockerHub: Manages Docker containers for isolated execution
    """
    
    def __init__(
        self,
        provider_id: str = "python",
        protocol_id: str = "python/v1",
        allow_local: bool = True,
        trusted_dirs: Optional[List[str]] = None,
        resource_manager=None,  # Accept resource_manager
        hub=None,  # Accept hub (DockerHub)
        **kwargs  # Accept and ignore other params for compatibility
    ):
        """
        Initialize Python provider
        
        Args:
            provider_id: Unique provider ID
            protocol_id: Protocol this provider implements
            allow_local: Allow local execution of trusted files
            trusted_dirs: List of directories containing trusted code
            resource_manager: Optional ResourceManager for Docker allocation
            hub: Optional DockerHub for container execution
            **kwargs: Additional arguments for compatibility
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id=protocol_id,
            name="Python Provider",
            description="Execute Python files locally or in containers",
            resource_manager=resource_manager,
            hub=hub
        )
        
        # Initialize LoggingMixin to set _component_name
        LoggingMixin.__init__(self)
        
        self.allow_local = allow_local
        self.trusted_dirs = [Path(d).resolve() for d in (trusted_dirs or [])]
        
        # Add current working directory as trusted by default
        if not self.trusted_dirs:
            self.trusted_dirs.append(Path.cwd())
        
        logger.info(f"Initialized {self.name} with {len(self.trusted_dirs)} trusted directories")
    
    async def initialize(self) -> None:
        """Initialize the provider"""
        logger.info(f"Python provider initialized")
    
    async def cleanup(self) -> None:
        """Clean up resources"""
        pass
    
    async def shutdown(self) -> None:
        """Shutdown the provider (alias for cleanup)"""
        await self.cleanup()
    
    async def health_check(self) -> bool:
        """Check if provider is healthy"""
        # Python provider is always healthy if Python is available
        return True
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle a request - main entry point for protocol execution
        
        Args:
            method: The method to execute
            params: Method parameters
            
        Returns:
            Response dictionary
        """
        return await self.execute(method, params)
    
    def can_handle(self, method: str) -> bool:
        """Check if this provider can handle a method"""
        return method in self.get_supported_methods()
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        return [
            "python/execute",      # Execute Python file
            "python/validate",     # Validate Python file syntax
            "python/info"          # Get provider info
        ]
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a Python method
        
        For container execution, expects 'container_endpoint' parameter from ResourceManager.
        Otherwise executes locally if file is trusted.
        """
        # Extract task context for logging
        task_id = params.get('task_id')
        workflow_id = params.get('workflow_id')
        
        await self.log_operation(
            "execute_start", 
            task_id=task_id, 
            workflow_id=workflow_id, 
            method=method,
            has_file=bool(params.get('file') or params.get('file_path'))
        )
        
        try:
            if method == "python/execute":
                result = await self._execute_file(params)
                await self.log_success(
                    "execute_complete",
                    task_id=task_id,
                    workflow_id=workflow_id,
                    method=method,
                    output_length=len(str(result.get('output', '')))
                )
                return result
            elif method == "python/validate":
                result = await self._validate_file(params)
                await self.log_success("validate_complete", task_id=task_id, workflow_id=workflow_id)
                return result
            elif method == "python/info":
                result = self._get_info()
                await self.log_success("info_complete", task_id=task_id, workflow_id=workflow_id)
                return result
            else:
                error = InvalidParameterError(param_name='method', reason=f"Unsupported method: {method}")
                await self.log_error("execute_failed", error, task_id=task_id, workflow_id=workflow_id, method=method)
                raise error
        except Exception as e:
            await self.log_error("execute_failed", e, task_id=task_id, workflow_id=workflow_id, method=method)
            raise
    
    async def _execute_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a Python file"""
        # Extract context for logging
        task_id = params.get('task_id')
        workflow_id = params.get('workflow_id')
        
        file_path = params.get('file') or params.get('file_path')
        code = params.get('code')
        
        # If we have inline code, create a temporary file
        is_temp = False
        if not file_path and code:
            # Create temporary file with the code
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
            temp_file.write(code)
            temp_file.close()
            file_path = temp_file.name
            is_temp = True
            
            await self.log_debug(
                "temp_file_created", 
                f"Created temporary file for inline code: {file_path}", 
                task_id=task_id, 
                workflow_id=workflow_id
            )
        
        if not file_path:
            error = InvalidParameterError(param_name='file', reason="Missing 'file', 'file_path', or 'code' parameter")
            await self.log_error("file_validation_failed", error, task_id=task_id, workflow_id=workflow_id)
            raise error
        
        args = params.get('args', [])
        env = params.get('env', {})
        timeout = params.get('timeout', 30)
        
        # Container endpoint provided by ResourceManager/DockerHub
        container_endpoint = params.get('container_endpoint')
        
        await self.log_operation(
            "file_validation", 
            task_id=task_id, 
            workflow_id=workflow_id, 
            file_path=str(file_path),
            has_container_endpoint=bool(container_endpoint),
            timeout=timeout
        )
        
        # Resolve file path
        file_path = Path(file_path).resolve()
        
        # Validate file
        if not file_path.exists():
            error = InvalidParameterError(param_name='file', reason=f"File not found: {file_path}")
            await self.log_error("file_not_found", error, task_id=task_id, workflow_id=workflow_id, file_path=str(file_path))
            raise error
        if not file_path.suffix == '.py':
            error = InvalidParameterError(param_name='file', reason=f"Not a Python file: {file_path}")
            await self.log_error("invalid_file_type", error, task_id=task_id, workflow_id=workflow_id, file_path=str(file_path))
            raise error
        
        try:
            # If container endpoint provided, execute in container
            if container_endpoint:
                await self.log_operation("container_execution_start", task_id=task_id, workflow_id=workflow_id, endpoint=container_endpoint)
                result = await self._execute_in_container(
                    container_endpoint, file_path, args, env, timeout
                )
                await self.log_operation("container_execution_complete", task_id=task_id, workflow_id=workflow_id, success=result.get('success'))
                return result
            
            # Otherwise check if local execution is allowed
            # For temporary files (from code), always trust them
            is_trusted = is_temp or self._is_trusted_file(file_path)
            
            await self.log_debug(
                "trust_check", 
                f"File trust check: trusted={is_trusted}, temp={is_temp}", 
                task_id=task_id, 
                workflow_id=workflow_id,
                file_path=str(file_path),
                is_trusted=is_trusted
            )
            
            if not is_trusted:
                # File is not trusted and no container provided
                await self.log_warning(
                    "execution_blocked",
                    "File not in trusted directories and no container provided",
                    task_id=task_id,
                    workflow_id=workflow_id,
                    file_path=str(file_path)
                )
                return {
                    'success': False,
                    'error': f"File {file_path} is not in trusted directories and no container provided",
                    'needs_container': True,
                    'execution_mode': 'blocked'
                }
            
            if not self.allow_local:
                await self.log_warning(
                    "local_execution_disabled",
                    "Local execution is disabled",
                    task_id=task_id,
                    workflow_id=workflow_id
                )
                return {
                    'success': False,
                    'error': "Local execution is disabled",
                    'needs_container': True,
                    'execution_mode': 'blocked'
                }
            
            # Execute locally
            result = await self._execute_locally(file_path, args, env, timeout)
            return result
            
        finally:
            # Clean up temporary file if created
            if is_temp:
                try:
                    import os
                    os.unlink(file_path)
                except:
                    pass
    
    def _is_trusted_file(self, file_path: Path) -> bool:
        """Check if file is in a trusted directory"""
        file_path = file_path.resolve()
        for trusted_dir in self.trusted_dirs:
            try:
                file_path.relative_to(trusted_dir)
                return True
            except ValueError:
                continue
        return False
    
    async def _execute_locally(
        self,
        file_path: Path,
        args: List[str],
        env: Dict[str, str],
        timeout: int
    ) -> Dict[str, Any]:
        """Execute Python file locally in subprocess"""
        import os
        
        # Build command
        cmd = [sys.executable, str(file_path)]
        if args:
            # Ensure all args are strings for subprocess
            cmd.extend([str(arg) for arg in args])
        
        # Prepare environment
        process_env = os.environ.copy()
        process_env.update(env)
        
        try:
            # Run in subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env
            )
            
            try:
                # Wait for completion
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                
                return_code = process.returncode
                
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                
                return {
                    'success': False,
                    'error': f'Execution timed out after {timeout} seconds',
                    'timeout': True,
                    'execution_mode': 'local'
                }
            
            # Decode output
            output = stdout.decode('utf-8', errors='replace')
            error_output = stderr.decode('utf-8', errors='replace')
            
            # Try to parse as JSON if possible
            result_data = output
            try:
                result_data = json.loads(output)
            except:
                pass
            
            # If the script failed, raise an exception to trigger retry mechanism
            if return_code != 0:
                raise TaskExecutionError(
                    task_id=env.get('GLEITZEIT_TASK_ID', 'python_task'),
                    message=f"Python script failed with exit code {return_code}: {error_output}"
                )
            
            return {
                'success': return_code == 0,
                'result': result_data,
                'output': output,
                'error': error_output if return_code != 0 else None,
                'exit_code': return_code,
                'execution_mode': 'local'
            }
            
        except TaskExecutionError:
            # Re-raise TaskExecutionError to trigger retry
            raise
        except Exception as e:
            logger.error(f"Failed to execute {file_path} locally: {e}")
            
            return {
                'success': False,
                'error': str(e),
                'execution_mode': 'local'
            }
    
    async def _execute_in_container(
        self,
        container_endpoint: str,
        file_path: Path,
        args: List[str],
        env: Dict[str, str],
        timeout: int
    ) -> Dict[str, Any]:
        """
        Execute Python file in a container
        
        This method expects the ResourceManager/DockerHub to provide a container
        endpoint and handle the actual execution. This provider just prepares
        the execution request.
        """
        # This is a placeholder - the actual execution would be handled
        # by making a request to the container endpoint or through
        # the ResourceManager's execution API
        
        # For now, return a response indicating container execution is needed
        return {
            'success': False,
            'error': 'Container execution not yet fully implemented',
            'container_endpoint': container_endpoint,
            'file_path': str(file_path),
            'needs_implementation': True,
            'execution_mode': 'container'
        }
    
    async def _validate_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate Python file syntax"""
        file_path = params.get('file') or params.get('file_path')
        if not file_path:
            raise InvalidParameterError(param_name='file', reason="Missing 'file' or 'file_path' parameter")
        
        file_path = Path(file_path).resolve()
        
        if not file_path.exists():
            return {
                'valid': False,
                'error': f"File not found: {file_path}"
            }
        
        try:
            with open(file_path, 'r') as f:
                source = f.read()
            
            # Try to compile the source
            compile(source, str(file_path), 'exec')
            
            return {
                'valid': True,
                'file': str(file_path)
            }
        except SyntaxError as e:
            return {
                'valid': False,
                'error': f"Syntax error at line {e.lineno}: {e.msg}",
                'line': e.lineno,
                'offset': e.offset
            }
        except Exception as e:
            return {
                'valid': False,
                'error': str(e)
            }
    
    def _get_info(self) -> Dict[str, Any]:
        """Get provider information"""
        return {
            'provider': self.provider_id,
            'protocol': self.protocol_id,
            'python_version': sys.version,
            'allow_local': self.allow_local,
            'trusted_dirs': [str(d) for d in self.trusted_dirs],
            'supported_methods': self.get_supported_methods()
        }
    
    async def __aenter__(self) -> 'PythonProvider':
        """Async context manager entry"""
        await self.initialize()
        return self
    
    async def __aexit__(self, 
                         exc_type: Optional[Type[BaseException]], 
                         exc_val: Optional[BaseException], 
                         exc_tb: Optional[Any]) -> None:
        """Async context manager exit"""
        await self.cleanup()