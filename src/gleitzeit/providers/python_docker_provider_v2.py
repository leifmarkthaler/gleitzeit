"""
Refactored Python Docker Provider - Version 2
Uses DockerHub for container management while maintaining protocol compatibility
"""

import logging
from typing import Dict, Any, Optional, List
import asyncio
import json
import base64
from pathlib import Path

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.hub.docker_hub import DockerHub, DockerConfig
from gleitzeit.hub.base import ResourceStatus
from gleitzeit.core.errors import (
    ProviderError, MethodNotSupportedError, InvalidParameterError,
    TaskExecutionError, ErrorCode
)

logger = logging.getLogger(__name__)


class PythonDockerProviderV2(ProtocolProvider):
    """
    Refactored Python Docker provider using hub architecture
    
    This version:
    - Delegates container management to DockerHub
    - Focuses on Python execution protocol
    - Maintains backward compatibility
    - Reduces code duplication with Docker executor
    """
    
    def __init__(
        self,
        provider_id: str,
        hub: Optional[DockerHub] = None,
        default_image: str = "python:3.11-slim",
        default_mode: str = "sandboxed",
        allowed_local_modules: Optional[List[str]] = None,
        use_legacy_api: bool = False
    ):
        """
        Initialize refactored Python Docker provider
        
        Args:
            provider_id: Unique provider identifier
            hub: Optional existing DockerHub to use (shared container management)
            default_image: Default Docker image for Python execution
            default_mode: Default execution mode (local, sandboxed, specialized)
            allowed_local_modules: Modules allowed in local execution
            use_legacy_api: Use legacy API format for compatibility
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id="python/v1",
            name="Python Docker Provider V2",
            description="Refactored Python provider with hub architecture"
        )
        
        self.default_image = default_image
        self.default_mode = default_mode
        self.allowed_local_modules = allowed_local_modules or []
        self.use_legacy_api = use_legacy_api
        
        # Hub management
        if hub:
            # Use existing hub (shared container management)
            self.hub = hub
            self.owns_hub = False
            logger.info(f"Provider {provider_id} using shared hub {hub.hub_id}")
        else:
            # Create dedicated hub
            self.hub = DockerHub(
                hub_id=f"{provider_id}-hub"
            )
            self.owns_hub = True
            logger.info(f"Provider {provider_id} created dedicated hub")
        
        # Execution mode configurations
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
                "network": False,
                "timeout": 60,
                "description": "Isolated Docker container execution"
            },
            "datascience": {
                "enabled": True,
                "image": "jupyter/datascience-notebook:latest",
                "memory_limit": "2g",
                "cpu_limit": 2.0,
                "network": True,
                "timeout": 120,
                "description": "Data science environment with ML libraries"
            },
            "minimal": {
                "enabled": True,
                "image": "python:3.11-alpine",
                "memory_limit": "256m",
                "cpu_limit": 0.5,
                "network": False,
                "timeout": 30,
                "description": "Minimal Python environment"
            }
        }
    
    async def initialize(self):
        """Initialize the provider and hub"""
        try:
            # Check if Docker modes are needed
            docker_modes = [
                mode for mode, config in self.execution_modes.items()
                if mode != "local" and config.get("enabled", False)
            ]
            
            if docker_modes:
                # Start hub if we own it
                if self.owns_hub:
                    await self.hub.start()
                    logger.info(f"Started dedicated hub for provider {self.provider_id}")
                
                # Pre-create containers for common modes
                if "sandboxed" in docker_modes:
                    config = self._create_docker_config("sandboxed")
                    instance = await self.hub.start_instance(config)
                    if instance:
                        logger.info(f"Pre-created sandboxed container: {instance.id}")
            
            logger.info("✅ Python Docker provider initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize provider: {e}")
            # Disable Docker modes if initialization fails
            for mode in self.execution_modes:
                if mode != "local":
                    self.execution_modes[mode]["enabled"] = False
            
            if self.execution_modes["local"]["enabled"]:
                logger.warning("Docker initialization failed, falling back to local mode only")
            else:
                raise ProviderError(
                    code=ErrorCode.PROVIDER_INITIALIZATION_FAILED,
                    message=f"Failed to initialize provider: {str(e)}",
                    provider_id=self.provider_id
                )
    
    async def shutdown(self):
        """Shutdown the provider and optionally the hub"""
        try:
            # Stop hub if we own it
            if self.owns_hub and self.hub:
                await self.hub.stop()
                logger.info(f"Stopped dedicated hub for provider {self.provider_id}")
            
            logger.info("Provider shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check provider health"""
        hub_status = await self.hub.get_status() if self.hub else {}
        instances = await self.hub.list_instances() if self.hub else []
        
        healthy_count = sum(
            1 for inst in instances 
            if inst.status == ResourceStatus.HEALTHY
        )
        
        docker_modes_enabled = sum(
            1 for mode, config in self.execution_modes.items()
            if mode != "local" and config.get("enabled", False)
        )
        
        return {
            "status": "healthy" if healthy_count > 0 or self.execution_modes["local"]["enabled"] else "unhealthy",
            "details": {
                "hub_id": self.hub.hub_id if self.hub else None,
                "owns_hub": self.owns_hub,
                "total_containers": len(instances),
                "healthy_containers": healthy_count,
                "docker_modes_enabled": docker_modes_enabled,
                "local_mode_enabled": self.execution_modes["local"]["enabled"],
                "default_mode": self.default_mode
            }
        }
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a Python method"""
        # Map protocol methods
        method_map = {
            "python/execute": self._execute_python,
            "python/validate": self._validate_python,
            "python/info": self._get_info,
            "python/batch": self._batch_execute
        }
        
        handler = method_map.get(method)
        if not handler:
            raise MethodNotSupportedError(
                code=ErrorCode.METHOD_NOT_SUPPORTED,
                message=f"Method '{method}' not supported",
                provider_id=self.provider_id,
                method=method
            )
        
        if asyncio.iscoroutinefunction(handler):
            return await handler(params)
        else:
            return handler(params)
    
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
                param_name="code",
                reason="Either 'code' or 'file' parameter is required"
            )
        
        # Load code from file if needed
        if file_path and not code:
            try:
                with open(file_path, 'r') as f:
                    code = f.read()
            except Exception as e:
                raise InvalidParameterError(
                    param_name="file",
                    reason=f"Failed to read file: {e}"
                )
        
        # Check if mode is enabled
        mode_config = self.execution_modes.get(execution_mode, {})
        if not mode_config.get("enabled", False):
            raise InvalidParameterError(
                param_name="execution_mode",
                reason=f"Mode '{execution_mode}' is not enabled"
            )
        
        # Execute based on mode
        if execution_mode == "local":
            return await self._execute_local(code, args, timeout)
        else:
            return await self._execute_in_container(code, args, execution_mode, params)
    
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
                message=f"Execution timeout after {timeout} seconds"
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
    
    async def _execute_in_container(
        self,
        code: str,
        args: Dict[str, Any],
        execution_mode: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute Python code in Docker container using hub"""
        # Create Docker configuration for the mode
        config = self._create_docker_config(execution_mode, params)
        
        # Get or create container instance
        # First try to get an existing instance
        instances = await self.hub.list_instances(status=ResourceStatus.HEALTHY)
        instance = None
        
        # Look for a matching instance
        for inst in instances:
            if inst.config.image == config.image:
                instance = inst
                break
        
        # Create new instance if none found
        if not instance:
            instance = await self.hub.start_instance(config)
        
        if not instance:
            raise TaskExecutionError(
                message=f"Failed to get container for mode {execution_mode}"
            )
        
        # Prepare Python code with arguments
        if args:
            arg_code = "\n".join([
                f"{key} = {repr(value)}"
                for key, value in args.items()
            ])
            full_code = arg_code + "\n\n" + code
        else:
            full_code = code
        
        # Create execution script
        script = self._create_python_script(full_code, params.get("files"))
        
        try:
            # Execute in container via hub
            result = await self.hub.execute_in_container(
                instance_id=instance.id,
                command=f"python -c {json.dumps(script)}"
            )
            
            # Parse result
            success = result.get("exit_code", 1) == 0
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            
            # Try to extract result from output
            result_value = None
            if success and stdout:
                try:
                    # Look for JSON result in last line
                    lines = stdout.strip().split('\n')
                    if lines:
                        last_line = lines[-1]
                        if last_line.startswith('{') and '"result"' in last_line:
                            parsed = json.loads(last_line)
                            result_value = parsed.get('result')
                            # Remove JSON from stdout
                            stdout = '\n'.join(lines[:-1])
                except Exception:
                    pass
            
            return {
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
                "result": result_value,
                "execution_mode": execution_mode,
                "container_id": instance.id,
                "exit_code": result.get("exit_code", -1)
            }
            
        except Exception as e:
            logger.error(f"Container execution failed: {e}")
            raise TaskExecutionError(
                message=f"Container execution failed: {str(e)}"
            )
    
    async def _validate_python(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate Python code syntax"""
        code = params.get("code")
        file_path = params.get("file")
        
        if not code and not file_path:
            raise InvalidParameterError(
                param_name="code",
                reason="Either 'code' or 'file' parameter is required"
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
    
    def _get_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get provider information"""
        return {
            "provider": self.provider_id,
            "protocol": self.protocol_id,
            "default_mode": self.default_mode,
            "default_image": self.default_image,
            "owns_hub": self.owns_hub,
            "hub_id": self.hub.hub_id if self.hub else None,
            "execution_modes": {
                mode: {
                    "enabled": config.get("enabled", False),
                    "description": config.get("description", "")
                }
                for mode, config in self.execution_modes.items()
            }
        }
    
    async def _batch_execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute multiple Python tasks in parallel"""
        tasks = params.get("tasks", [])
        max_concurrent = params.get("max_concurrent", 5)
        
        if not tasks:
            return {"success": True, "results": []}
        
        # Execute tasks concurrently
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def execute_with_semaphore(task):
            async with semaphore:
                try:
                    return await self._execute_python(task)
                except Exception as e:
                    return {
                        "success": False,
                        "error": str(e),
                        "stdout": "",
                        "stderr": str(e)
                    }
        
        results = await asyncio.gather(
            *[execute_with_semaphore(task) for task in tasks]
        )
        
        return {
            "success": all(r.get("success", False) for r in results),
            "results": results,
            "summary": {
                "total": len(results),
                "successful": sum(1 for r in results if r.get("success", False)),
                "failed": sum(1 for r in results if not r.get("success", False))
            }
        }
    
    async def get_status(self) -> Dict[str, Any]:
        """Get provider status including hub metrics"""
        hub_status = None
        hub_metrics = None
        
        if self.hub:
            hub_status = await self.hub.get_status()
            hub_metrics = await self.hub.get_metrics_summary()
        
        return {
            "provider_id": self.provider_id,
            "protocol": self.protocol_id,
            "owns_hub": self.owns_hub,
            "hub_id": self.hub.hub_id if self.hub else None,
            "hub_status": hub_status,
            "metrics": hub_metrics,
            "capabilities": {
                "methods": ["python/execute", "python/validate", "python/info", "python/batch"],
                "execution_modes": list(self.execution_modes.keys()),
                "container_pooling": True,
                "parallel_execution": True,
                "syntax_validation": True
            }
        }
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle JSON-RPC style requests"""
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
    
    def _create_docker_config(
        self,
        execution_mode: str,
        params: Optional[Dict[str, Any]] = None
    ) -> DockerConfig:
        """Create Docker configuration for execution mode"""
        mode_config = self.execution_modes[execution_mode]
        params = params or {}
        
        return DockerConfig(
            image=params.get("image", mode_config.get("image", self.default_image)),
            memory_limit=params.get("memory_limit", mode_config.get("memory_limit", "512m")),
            cpu_limit=params.get("cpu_limit", mode_config.get("cpu_limit", 1.0)),
            network_mode="none" if not params.get("network", mode_config.get("network", False)) else "bridge",
            volumes=params.get("volumes", {}),
            environment=params.get("environment", {}),
            labels={"execution_mode": execution_mode, "provider": self.provider_id}
        )
    
    def _create_python_script(
        self,
        code: str,
        files: Optional[Dict[str, str]] = None
    ) -> str:
        """Create Python script with proper error handling"""
        script_parts = [
            "import sys",
            "import json",
            "import traceback",
            ""
        ]
        
        # Add files if provided
        if files:
            for filename, content in files.items():
                escaped = content.replace('\\', '\\\\').replace('"', '\\"')
                script_parts.append(f'with open("{filename}", "w") as f:')
                script_parts.append(f'    f.write("{escaped}")')
            script_parts.append("")
        
        # Add execution wrapper
        script_parts.extend([
            "try:",
            "    exec_globals = {}",
            "    exec_locals = {}",
            f"    exec({repr(code)}, exec_globals, exec_locals)",
            "    if 'result' in exec_locals:",
            "        print(json.dumps({'result': exec_locals['result']}))",
            "    elif 'result' in exec_globals:",
            "        print(json.dumps({'result': exec_globals['result']}))",
            "except Exception as e:",
            "    traceback.print_exc()",
            "    sys.exit(1)"
        ])
        
        return "\n".join(script_parts)