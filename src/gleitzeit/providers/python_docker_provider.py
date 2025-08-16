"""
Python Docker Provider - Sandboxed Python execution in containers

This provider extends the basic PythonProvider to support Docker-based
sandboxed execution for enhanced security and isolation.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.execution.docker_executor import DockerExecutor, SecurityLevel
from gleitzeit.core.errors import (
    ProviderError, MethodNotSupportedError, InvalidParameterError,
    TaskExecutionError, ErrorCode
)

logger = logging.getLogger(__name__)


class PythonDockerProvider(ProtocolProvider):
    """
    Python provider with Docker-based sandboxed execution
    
    Supports multiple execution modes:
    - Local (trusted): Direct execution on host
    - Sandboxed: Full Docker isolation
    - Specialized: Pre-built environments (data science, ML, etc.)
    
    Implements the "python/v1" protocol with enhanced security.
    """
    
    def __init__(
        self,
        provider_id: str,
        docker_config: Optional[Dict[str, Any]] = None,
        pool_config: Optional[Dict[str, Any]] = None,
        default_mode: str = "sandboxed",
        allowed_local_modules: Optional[List[str]] = None
    ):
        """
        Initialize Python Docker Provider
        
        Args:
            provider_id: Unique provider identifier
            docker_config: Docker executor configuration
            pool_config: Container pool configuration
            default_mode: Default execution mode (local, sandboxed, specialized)
            allowed_local_modules: Modules allowed in local execution
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id="python/v1",
            name="Python Docker Provider",
            description="Python execution with Docker sandboxing"
        )
        
        self.default_mode = default_mode
        self.allowed_local_modules = allowed_local_modules or []
        
        # Execution modes configuration
        self.execution_modes = {
            "local": {
                "enabled": True,
                "trusted": True,
                "description": "Direct execution on host (trusted code only)"
            },
            "sandboxed": {
                "enabled": True,
                "image": "python:3.11-slim",
                "memory_limit": "512m",
                "cpu_limit": 1.0,
                "network": "none",
                "timeout": 60,
                "description": "Isolated Docker container execution"
            },
            "datascience": {
                "enabled": True,
                "image": "gleitzeit/datascience:latest",
                "memory_limit": "2g",
                "cpu_limit": 2.0,
                "network": "bridge",
                "timeout": 120,
                "description": "Data science environment with ML libraries"
            },
            "minimal": {
                "enabled": True,
                "image": "python:3.11-alpine",
                "memory_limit": "256m",
                "cpu_limit": 0.5,
                "network": "none",
                "timeout": 30,
                "description": "Minimal Python environment"
            }
        }
        
        # Docker executor (created on demand)
        self.docker_executor = None
        self.docker_config = docker_config or {}
        self.pool_config = pool_config or {}
        
        logger.info(f"Initialized PythonDockerProvider with default mode: {default_mode}")
        
    async def initialize(self):
        """Initialize the provider"""
        try:
            # Initialize Docker executor if any Docker mode is enabled
            docker_modes = [
                mode for mode, config in self.execution_modes.items()
                if mode != "local" and config.get("enabled", False)
            ]
            
            if docker_modes:
                try:
                    self.docker_executor = DockerExecutor(
                        config=self.docker_config,
                        pool_config=self.pool_config
                    )
                    await self.docker_executor.initialize()
                    logger.info("✅ Docker executor initialized")
                except ImportError:
                    logger.warning("Docker SDK not available, disabling Docker modes")
                    for mode in docker_modes:
                        self.execution_modes[mode]["enabled"] = False
                except Exception as e:
                    logger.error(f"Failed to initialize Docker executor: {e}")
                    for mode in docker_modes:
                        self.execution_modes[mode]["enabled"] = False
                        
            logger.info("✅ Python Docker provider initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Python Docker provider: {e}")
            raise ProviderError(
                code=ErrorCode.PROVIDER_INITIALIZATION_FAILED,
                message=f"Failed to initialize provider: {str(e)}",
                provider_id=self.provider_id
            )
            
    async def shutdown(self):
        """Shutdown the provider"""
        if self.docker_executor:
            await self.docker_executor.shutdown()
            self.docker_executor = None
            
        logger.info("Python Docker provider shutdown")
        
    async def health_check(self) -> Dict[str, Any]:
        """Check provider health"""
        docker_status = "not_initialized"
        container_pool_status = {}
        
        if self.docker_executor:
            try:
                container_pool_status = await self.docker_executor.get_pool_status()
                docker_status = "healthy"
            except Exception as e:
                docker_status = f"unhealthy: {e}"
                
        return {
            "status": "healthy",
            "details": {
                "default_mode": self.default_mode,
                "docker_status": docker_status,
                "container_pool": container_pool_status,
                "enabled_modes": [
                    mode for mode, config in self.execution_modes.items()
                    if config.get("enabled", False)
                ]
            }
        }
        
    def get_supported_methods(self) -> List[str]:
        """Get supported protocol methods"""
        return ["python/execute", "python/validate", "python/info"]
        
    async def execute(
        self,
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a Python method
        
        Args:
            method: Protocol method
            params: Method parameters including execution mode
            
        Returns:
            Execution result
        """
        if method not in self.get_supported_methods():
            raise MethodNotSupportedError(
                code=ErrorCode.METHOD_NOT_SUPPORTED,
                message=f"Method '{method}' not supported",
                provider_id=self.provider_id,
                method=method
            )
            
        if method == "python/execute":
            return await self._execute_python(params)
        elif method == "python/validate":
            return await self._validate_python(params)
        elif method == "python/info":
            return self._get_info()
        else:
            raise MethodNotSupportedError(
                code=ErrorCode.METHOD_NOT_SUPPORTED,
                message=f"Unknown method: {method}",
                provider_id=self.provider_id,
                method=method
            )
            
    async def _execute_python(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Python code with appropriate isolation"""
        
        # Get execution parameters
        code = params.get("code")
        file_path = params.get("file")
        args = params.get("args", {})
        execution_mode = params.get("execution_mode", self.default_mode)
        timeout = params.get("timeout", 60)
        
        # Validate inputs
        if not code and not file_path:
            raise InvalidParameterError(
                code=ErrorCode.INVALID_PARAMS,
                message="Either 'code' or 'file' parameter is required",
                provider_id=self.provider_id
            )
            
        # Load code from file if needed
        if file_path and not code:
            try:
                with open(file_path, 'r') as f:
                    code = f.read()
            except Exception as e:
                raise InvalidParameterError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"Failed to read file: {e}",
                    provider_id=self.provider_id
                )
                
        # Check if mode is enabled
        mode_config = self.execution_modes.get(execution_mode, {})
        if not mode_config.get("enabled", False):
            raise InvalidParameterError(
                code=ErrorCode.INVALID_PARAMS,
                message=f"Execution mode '{execution_mode}' is not enabled",
                provider_id=self.provider_id
            )
            
        # Execute based on mode
        if execution_mode == "local":
            return await self._execute_local(code, args, timeout)
        else:
            return await self._execute_docker(code, args, execution_mode, params)
            
    async def _execute_local(
        self,
        code: str,
        args: Dict[str, Any],
        timeout: int
    ) -> Dict[str, Any]:
        """Execute Python code locally (trusted mode)"""
        import sys
        import io
        import traceback
        import json
        from contextlib import redirect_stdout, redirect_stderr
        
        # Prepare execution environment
        exec_globals = {"__builtins__": __builtins__}
        exec_locals = args.copy()
        
        # Capture output
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        try:
            # Execute with timeout
            async def run_code():
                with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                    exec(code, exec_globals, exec_locals)
                    
            await asyncio.wait_for(run_code(), timeout=timeout)
            
            # Extract result
            result_value = None
            if 'result' in exec_locals:
                result_value = exec_locals['result']
            elif 'result' in exec_globals:
                result_value = exec_globals['result']
                
            return {
                "success": True,
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue(),
                "result": result_value,
                "execution_mode": "local"
            }
            
        except asyncio.TimeoutError:
            raise TaskExecutionError(
                code=ErrorCode.TASK_TIMEOUT,
                message=f"Execution timeout after {timeout} seconds",
                provider_id=self.provider_id
            )
            
        except Exception as e:
            error_trace = traceback.format_exc()
            return {
                "success": False,
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue() + "\n" + error_trace,
                "error": str(e),
                "execution_mode": "local"
            }
            
    async def _execute_docker(
        self,
        code: str,
        args: Dict[str, Any],
        execution_mode: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute Python code in Docker container"""
        
        if not self.docker_executor:
            raise ProviderError(
                code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                message="Docker executor not available",
                provider_id=self.provider_id
            )
            
        # Get mode configuration
        mode_config = self.execution_modes[execution_mode]
        
        # Prepare code with arguments
        if args:
            arg_code = "\n".join([
                f"{key} = {repr(value)}"
                for key, value in args.items()
            ])
            code = arg_code + "\n\n" + code
            
        # Determine security level
        security_level = SecurityLevel.SANDBOXED
        if execution_mode == "datascience":
            security_level = SecurityLevel.SPECIALIZED
            
        # Get custom parameters
        custom_params = {
            "image": params.get("image", mode_config.get("image")),
            "memory_limit": params.get("memory_limit", mode_config.get("memory_limit")),
            "cpu_limit": params.get("cpu_limit", mode_config.get("cpu_limit")),
            "network_mode": params.get("network", mode_config.get("network")),
            "timeout": params.get("timeout", mode_config.get("timeout", 60)),
            "volumes": params.get("volumes"),
            "environment": params.get("environment"),
            "files": params.get("files")
        }
        
        try:
            # Execute in Docker
            result = await self.docker_executor.execute(
                code=code,
                security_level=security_level,
                **{k: v for k, v in custom_params.items() if v is not None}
            )
            
            # Add execution mode to result
            result["execution_mode"] = execution_mode
            
            return result
            
        except Exception as e:
            logger.error(f"Docker execution failed: {e}")
            raise TaskExecutionError(
                code=ErrorCode.TASK_EXECUTION_FAILED,
                message=f"Docker execution failed: {str(e)}",
                provider_id=self.provider_id
            )
            
    async def _validate_python(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate Python code syntax"""
        code = params.get("code")
        file_path = params.get("file")
        
        if not code and not file_path:
            raise InvalidParameterError(
                code=ErrorCode.INVALID_PARAMS,
                message="Either 'code' or 'file' parameter is required",
                provider_id=self.provider_id
            )
            
        # Load code from file if needed
        if file_path and not code:
            try:
                with open(file_path, 'r') as f:
                    code = f.read()
            except Exception as e:
                return {
                    "valid": False,
                    "error": f"Failed to read file: {e}"
                }
                
        # Validate syntax
        try:
            compile(code, "<string>", "exec")
            return {
                "valid": True,
                "message": "Code syntax is valid"
            }
        except SyntaxError as e:
            return {
                "valid": False,
                "error": str(e),
                "line": e.lineno,
                "offset": e.offset
            }
            
    def _get_info(self) -> Dict[str, Any]:
        """Get provider information"""
        return {
            "provider": self.provider_id,
            "default_mode": self.default_mode,
            "execution_modes": {
                mode: {
                    "enabled": config.get("enabled", False),
                    "description": config.get("description", "")
                }
                for mode, config in self.execution_modes.items()
            },
            "docker_available": self.docker_executor is not None
        }
        
    async def batch_execute(
        self,
        tasks: List[Dict[str, Any]],
        max_concurrent: int = 5
    ) -> List[Dict[str, Any]]:
        """Execute multiple Python tasks in parallel"""
        
        if self.docker_executor:
            # Use Docker batch execution
            return await self.docker_executor.batch_execute(tasks, max_concurrent)
        else:
            # Fallback to sequential local execution
            results = []
            for task in tasks:
                result = await self._execute_python(task)
                results.append(result)
            return results
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle JSON-RPC request (required by base class)"""
        method = request.get("method")
        params = request.get("params", {})
        
        try:
            result = await self.execute(method, params)
            return {
                "jsonrpc": "2.0",
                "result": result,
                "id": request.get("id")
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": getattr(e, "code", -32603),
                    "message": str(e)
                },
                "id": request.get("id")
            }