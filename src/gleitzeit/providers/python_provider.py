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

logger = logging.getLogger(__name__)


class PythonProvider(ProtocolProvider):
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
        if method == "python/execute":
            return await self._execute_file(params)
        elif method == "python/validate":
            return await self._validate_file(params)
        elif method == "python/info":
            return self._get_info()
        else:
            raise InvalidParameterError(param_name='method', reason=f"Unsupported method: {method}")
    
    async def _execute_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a Python file"""
        file_path = params.get('file') or params.get('file_path')
        if not file_path:
            raise InvalidParameterError(param_name='file', reason="Missing 'file' or 'file_path' parameter")
        
        args = params.get('args', [])
        env = params.get('env', {})
        timeout = params.get('timeout', 30)
        
        # Container endpoint provided by ResourceManager/DockerHub
        container_endpoint = params.get('container_endpoint')
        
        # Resolve file path
        file_path = Path(file_path).resolve()
        
        # Validate file
        if not file_path.exists():
            raise InvalidParameterError(param_name='file', reason=f"File not found: {file_path}")
        if not file_path.suffix == '.py':
            raise InvalidParameterError(param_name='file', reason=f"Not a Python file: {file_path}")
        
        # If container endpoint provided, execute in container
        if container_endpoint:
            return await self._execute_in_container(
                container_endpoint, file_path, args, env, timeout
            )
        
        # Otherwise check if local execution is allowed
        is_trusted = self._is_trusted_file(file_path)
        
        if not is_trusted:
            # File is not trusted and no container provided
            return {
                'success': False,
                'error': f"File {file_path} is not in trusted directories and no container provided",
                'needs_container': True,
                'execution_mode': 'blocked'
            }
        
        if not self.allow_local:
            return {
                'success': False,
                'error': "Local execution is disabled",
                'needs_container': True,
                'execution_mode': 'blocked'
            }
        
        # Execute locally
        return await self._execute_locally(file_path, args, env, timeout)
    
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
            cmd.extend(args)
        
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
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {
                    'success': False,
                    'error': f'Execution timed out after {timeout} seconds',
                    'timeout': True,
                    'execution_mode': 'local'
                }
            
            # Parse output
            output = stdout.decode('utf-8', errors='replace')
            error_output = stderr.decode('utf-8', errors='replace')
            
            # Try to parse as JSON if possible
            result_data = output
            try:
                result_data = json.loads(output)
            except:
                pass
            
            # If the script failed, raise an exception to trigger retry mechanism
            if process.returncode != 0:
                raise TaskExecutionError(
                    task_id='python_task',  # Generic task ID for Python execution
                    message=f"Python script failed with exit code {process.returncode}: {error_output}"
                )
            
            return {
                'success': process.returncode == 0,
                'result': result_data,
                'output': output,
                'error': error_output if process.returncode != 0 else None,
                'exit_code': process.returncode,
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