"""
Streamlined Python Provider with Integrated Hub
Much simpler implementation with built-in container management
"""

import logging
from typing import Dict, Any, Optional, List
import asyncio
import json
import docker
from docker.models.containers import Container

from gleitzeit.providers.hub_provider import HubProvider
from gleitzeit.hub.base import ResourceInstance, ResourceStatus
from gleitzeit.hub.docker_hub import DockerConfig
from gleitzeit.core.errors import InvalidParameterError, TaskExecutionError

logger = logging.getLogger(__name__)


class PythonProviderStreamlined(HubProvider[DockerConfig]):
    """
    Streamlined Python provider with integrated container management
    
    This version is much simpler:
    - Inherits all container management from HubProvider
    - Only implements Python execution logic
    - Automatic pooling, health monitoring, metrics
    """
    
    def __init__(
        self,
        provider_id: str = "python-streamlined",
        default_image: str = "python:3.11-slim",
        max_containers: int = 5,
        enable_local: bool = True,
        enable_sharing: bool = False
    ):
        """
        Initialize streamlined Python provider
        
        Args:
            provider_id: Unique provider identifier
            default_image: Default Docker image
            max_containers: Maximum containers to manage
            enable_local: Enable local Python execution
            enable_sharing: Allow provider to be shared
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id="python/v1",
            name="Streamlined Python Provider",
            description="Python provider with integrated container management",
            resource_config_class=DockerConfig,
            enable_sharing=enable_sharing,
            max_instances=max_containers,
            enable_auto_discovery=False  # Containers are created on-demand
        )
        
        self.default_image = default_image
        self.enable_local = enable_local
        self.docker_client: Optional[docker.DockerClient] = None
        
        # Execution modes
        self.modes = {
            "local": {
                "enabled": enable_local,
                "description": "Direct local execution"
            },
            "sandboxed": {
                "enabled": True,
                "image": "python:3.11-slim",
                "memory_limit": "512m",
                "cpu_limit": 1.0
            },
            "datascience": {
                "enabled": True,
                "image": "jupyter/datascience-notebook:latest",
                "memory_limit": "2g",
                "cpu_limit": 2.0
            }
        }
    
    async def initialize(self):
        """Initialize provider and Docker client"""
        try:
            # Initialize Docker client
            self.docker_client = docker.from_env()
            self.docker_client.ping()
            logger.info("Docker client initialized")
            
            # Pre-create a sandboxed container for quick startup
            if len(self.instances) == 0:
                config = DockerConfig(
                    image=self.default_image,
                    memory_limit="512m",
                    cpu_limit=1.0,
                    network_mode="none",
                    labels={"mode": "sandboxed", "provider": self.provider_id}
                )
                instance = await self.create_resource(config)
                await self.register_instance(instance)
                logger.info(f"Pre-created container: {instance.id}")
            
        except Exception as e:
            logger.warning(f"Docker initialization failed: {e}")
            if not self.enable_local:
                raise
        
        # Call parent initialization
        await super().initialize()
    
    async def shutdown(self):
        """Cleanup resources"""
        # Close Docker client
        if self.docker_client:
            self.docker_client.close()
            self.docker_client = None
        
        # Call parent shutdown (handles container cleanup)
        await super().shutdown()
    
    async def create_resource(self, config: DockerConfig) -> ResourceInstance[DockerConfig]:
        """Create a Docker container resource"""
        if not self.docker_client:
            raise Exception("Docker client not initialized")
        
        # Keep Python containers running with a sleep loop
        if 'python' in config.image and not config.command:
            config.command = 'sh -c "while true; do sleep 30; done"'
        
        # Create container
        container_config = {
            'image': config.image,
            'command': config.command,
            'environment': config.environment or {},
            'volumes': config.volumes or {},
            'mem_limit': config.memory_limit,
            'cpu_quota': int(config.cpu_limit * 100000),
            'cpu_period': 100000,
            'network_mode': config.network_mode,
            'labels': config.labels or {},
            'detach': True,
            'auto_remove': config.auto_remove
        }
        
        # Remove None values
        container_config = {k: v for k, v in container_config.items() if v is not None}
        
        # Run container
        container: Container = self.docker_client.containers.run(**container_config)
        
        # Create resource instance
        from gleitzeit.hub.base import ResourceType
        instance = ResourceInstance(
            id=f"docker-{container.short_id}",
            name=f"Container-{container.short_id}",
            type=ResourceType.DOCKER,
            endpoint=container.short_id,
            status=ResourceStatus.HEALTHY,
            config=config,
            capabilities=set(),
            tags=set(config.labels.keys()) if config.labels else set(),
            metadata={'container': container}
        )
        
        logger.info(f"Created container: {instance.id}")
        return instance
    
    async def destroy_resource(self, instance: ResourceInstance[DockerConfig]):
        """Destroy a Docker container"""
        if 'container' in instance.metadata:
            container = instance.metadata['container']
            try:
                container.stop(timeout=5)
                container.remove()
                logger.info(f"Destroyed container: {instance.id}")
            except Exception as e:
                logger.error(f"Failed to destroy container {instance.id}: {e}")
    
    async def check_resource_health(self, instance: ResourceInstance[DockerConfig]) -> bool:
        """Check if container is healthy"""
        if 'container' not in instance.metadata:
            return False
        
        try:
            container = instance.metadata['container']
            container.reload()
            return container.status == 'running'
        except Exception as e:
            logger.debug(f"Health check failed for {instance.id}: {e}")
            return False
    
    async def discover_resources(self) -> List[DockerConfig]:
        """No auto-discovery for Docker containers - they're created on demand"""
        return []
    
    async def execute_on_resource(
        self,
        instance: ResourceInstance[DockerConfig],
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute Python code on a container"""
        
        if method == "python/execute":
            return await self._execute_python(instance, params)
        elif method == "python/validate":
            return await self._validate_python(params)
        elif method == "python/info":
            return self._get_info()
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _execute_python(
        self,
        instance: Optional[ResourceInstance[DockerConfig]],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute Python code"""
        code = params.get('code')
        file_path = params.get('file')
        args = params.get('args', {})
        mode = params.get('execution_mode', 'sandboxed')
        
        # Validate inputs
        if not code and not file_path:
            raise InvalidParameterError(
                param_name='code',
                reason='Either code or file parameter is required'
            )
        
        # Load code from file if needed
        if file_path and not code:
            try:
                with open(file_path, 'r') as f:
                    code = f.read()
            except Exception as e:
                raise InvalidParameterError(
                    param_name='file',
                    reason=f'Failed to read file: {e}'
                )
        
        # Execute locally if requested and enabled
        if mode == 'local' and self.enable_local:
            return await self._execute_local(code, args)
        
        # Otherwise execute in container
        if not instance:
            # Get or create a container
            requirements = {'tags': {mode}}
            instance = await self.get_instance(requirements)
            
            if not instance:
                # Create new container
                mode_config = self.modes.get(mode, self.modes['sandboxed'])
                config = DockerConfig(
                    image=mode_config.get('image', self.default_image),
                    memory_limit=mode_config.get('memory_limit', '512m'),
                    cpu_limit=mode_config.get('cpu_limit', 1.0),
                    network_mode='none',
                    labels={'mode': mode}
                )
                instance = await self.create_resource(config)
                await self.register_instance(instance)
        
        return await self._execute_in_container(instance, code, args)
    
    async def _execute_local(self, code: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Python code locally"""
        import sys
        import io
        import traceback
        from contextlib import redirect_stdout, redirect_stderr
        
        # Prepare environment
        exec_globals = {"__builtins__": __builtins__}
        exec_locals = args.copy()
        
        # Capture output
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, exec_globals, exec_locals)
            
            # Extract result
            result = exec_locals.get('result') or exec_globals.get('result')
            
            return {
                'success': True,
                'stdout': stdout_capture.getvalue(),
                'stderr': stderr_capture.getvalue(),
                'result': result,
                'execution_mode': 'local'
            }
            
        except Exception as e:
            return {
                'success': False,
                'stdout': stdout_capture.getvalue(),
                'stderr': stderr_capture.getvalue() + '\n' + traceback.format_exc(),
                'error': str(e),
                'execution_mode': 'local'
            }
    
    async def _execute_in_container(
        self,
        instance: ResourceInstance[DockerConfig],
        code: str,
        args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute Python code in container"""
        container = instance.metadata['container']
        
        # Prepare code with arguments
        if args:
            arg_code = '\n'.join([f"{k} = {repr(v)}" for k, v in args.items()])
            full_code = arg_code + '\n\n' + code
        else:
            full_code = code
        
        # Create execution script
        script = self._create_script(full_code)
        
        # Execute in container
        exec_result = container.exec_run(
            cmd=['python', '-c', script],
            stdout=True,
            stderr=True,
            demux=True
        )
        
        stdout = exec_result.output[0] if exec_result.output[0] else b''
        stderr = exec_result.output[1] if exec_result.output[1] else b''
        
        # Parse result
        result = None
        stdout_str = stdout.decode('utf-8', errors='replace')
        stderr_str = stderr.decode('utf-8', errors='replace')
        
        if exec_result.exit_code == 0 and stdout_str:
            # Try to extract JSON result
            try:
                lines = stdout_str.strip().split('\n')
                if lines and lines[-1].startswith('{'):
                    parsed = json.loads(lines[-1])
                    if 'result' in parsed:
                        result = parsed['result']
                        stdout_str = '\n'.join(lines[:-1])
            except Exception:
                pass
        
        return {
            'success': exec_result.exit_code == 0,
            'stdout': stdout_str,
            'stderr': stderr_str,
            'result': result,
            'exit_code': exec_result.exit_code,
            'execution_mode': 'container',
            'container_id': instance.id
        }
    
    async def _validate_python(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate Python syntax"""
        code = params.get('code')
        
        if not code:
            raise InvalidParameterError(
                param_name='code',
                reason='Code parameter is required'
            )
        
        try:
            compile(code, '<string>', 'exec')
            return {
                'valid': True,
                'message': 'Code syntax is valid'
            }
        except SyntaxError as e:
            return {
                'valid': False,
                'error': str(e),
                'line': e.lineno,
                'offset': e.offset
            }
    
    def _get_info(self) -> Dict[str, Any]:
        """Get provider information"""
        return {
            'provider': self.provider_id,
            'protocol': self.protocol_id,
            'default_image': self.default_image,
            'total_containers': len(self.instances),
            'healthy_containers': sum(
                1 for inst in self.instances.values()
                if inst.status == ResourceStatus.HEALTHY
            ),
            'modes': {
                name: config.get('enabled', False)
                for name, config in self.modes.items()
            }
        }
    
    def _create_script(self, code: str) -> str:
        """Create Python execution script"""
        return f"""
import sys
import json
import traceback

try:
    exec_globals = {{}}
    exec_locals = {{}}
    exec({repr(code)}, exec_globals, exec_locals)
    
    if 'result' in exec_locals:
        print(json.dumps({{'result': exec_locals['result']}}))
    elif 'result' in exec_globals:
        print(json.dumps({{'result': exec_globals['result']}}))
except Exception:
    traceback.print_exc()
    sys.exit(1)
"""
    
    def get_method_requirements(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get resource requirements for a method"""
        if method == "python/execute":
            mode = params.get('execution_mode', 'sandboxed')
            return {'tags': {mode}}
        return {}
    
    def create_default_config(self, method: str, params: Dict[str, Any]) -> DockerConfig:
        """Create default Docker configuration"""
        mode = params.get('execution_mode', 'sandboxed')
        mode_config = self.modes.get(mode, self.modes['sandboxed'])
        
        return DockerConfig(
            image=mode_config.get('image', self.default_image),
            memory_limit=mode_config.get('memory_limit', '512m'),
            cpu_limit=mode_config.get('cpu_limit', 1.0),
            network_mode='none',
            labels={'mode': mode}
        )
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle JSON-RPC style requests"""
        method = request.get('method')
        params = request.get('params', {})
        
        try:
            result = await self.execute(method, params)
            return {
                'jsonrpc': '2.0',
                'result': result,
                'id': request.get('id')
            }
        except Exception as e:
            return {
                'jsonrpc': '2.0',
                'error': {
                    'code': getattr(e, 'code', -32603),
                    'message': str(e)
                },
                'id': request.get('id')
            }