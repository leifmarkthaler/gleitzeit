"""
Streamlined Python Provider with Integrated Hub
Executes Python files either locally (trusted) or in Docker (untrusted)
"""

import logging
from typing import Dict, Any, Optional, List
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import shutil

# Optional Docker import
try:
    import docker
    from docker.models.containers import Container
    DOCKER_AVAILABLE = True
except ImportError:
    docker = None
    Container = None
    DOCKER_AVAILABLE = False

from gleitzeit.providers.hub_provider import HubProvider
from gleitzeit.hub.base import ResourceInstance, ResourceStatus, ResourceType
from gleitzeit.hub.docker_hub import DockerConfig
from gleitzeit.core.errors import InvalidParameterError, TaskExecutionError

logger = logging.getLogger(__name__)


class PythonProvider(HubProvider[DockerConfig]):
    """
    Secure Python file execution provider
    
    Security model:
    - Local execution: For trusted/owned code only (subprocess isolation)
    - Docker execution: For untrusted/external code (container isolation)
    - NO arbitrary code execution via exec() or eval()
    """
    
    def __init__(
        self,
        provider_id: str = "python",
        docker_image: str = "python:3.11-slim",
        max_containers: int = 5,
        allow_local: bool = True,
        trusted_dirs: Optional[List[str]] = None
    ):
        """
        Initialize Python provider
        
        Args:
            provider_id: Unique provider ID
            docker_image: Default Docker image for containers
            max_containers: Maximum number of containers to manage
            allow_local: Allow local execution of trusted files
            trusted_dirs: List of directories containing trusted code
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id="python/v1",
            name="Python File Executor",
            description="Securely execute Python files locally or in Docker",
            resource_config_class=DockerConfig,
            max_instances=max_containers
        )
        
        self.docker_image = docker_image
        self.allow_local = allow_local
        self.trusted_dirs = [Path(d).resolve() for d in (trusted_dirs or [])]
        
        # Add current working directory as trusted by default
        if not self.trusted_dirs:
            self.trusted_dirs.append(Path.cwd())
        
        # Docker client
        self.docker_client = None
        if DOCKER_AVAILABLE:
            try:
                self.docker_client = docker.from_env()
                logger.info("Docker client initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Docker client: {e}")
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        return [
            "python/execute",      # Execute Python file
            "python/validate",     # Validate Python file syntax
            "python/info"          # Get provider info
        ]
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a Python method"""
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
        use_docker = params.get('use_docker', None)
        
        # Resolve file path
        file_path = Path(file_path).resolve()
        
        # Validate file
        if not file_path.exists():
            raise InvalidParameterError(param_name='file', reason=f"File not found: {file_path}")
        if not file_path.suffix == '.py':
            raise InvalidParameterError(param_name='file', reason=f"Not a Python file: {file_path}")
        
        # Determine execution mode
        is_trusted = self._is_trusted_file(file_path)
        
        if use_docker is None:
            # Auto-detect: use Docker for untrusted files
            use_docker = not is_trusted
        
        if use_docker:
            if not DOCKER_AVAILABLE or not self.docker_client:
                raise TaskExecutionError("Docker not available for untrusted code execution")
            return await self._execute_in_docker(file_path, args, env, timeout)
        else:
            if not is_trusted and not params.get('force_local', False):
                raise TaskExecutionError(
                    f"File {file_path} is not in trusted directories. "
                    "Use use_docker=True or add to trusted_dirs"
                )
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
            
            return {
                'success': process.returncode == 0,
                'returncode': process.returncode,
                'stdout': stdout.decode('utf-8', errors='replace') if stdout else '',
                'stderr': stderr.decode('utf-8', errors='replace') if stderr else '',
                'execution_mode': 'local',
                'trusted': True
            }
            
        except Exception as e:
            logger.error(f"Failed to execute {file_path} locally: {e}")
            return {
                'success': False,
                'error': str(e),
                'execution_mode': 'local'
            }
    
    async def _execute_in_docker(
        self,
        file_path: Path,
        args: List[str],
        env: Dict[str, str],
        timeout: int
    ) -> Dict[str, Any]:
        """Execute Python file in Docker container"""
        if not self.docker_client:
            raise TaskExecutionError("Docker client not initialized")
        
        # Get or create container
        instance = await self._get_or_create_container()
        container = instance.metadata['container']
        
        # Create temporary directory for file transfer
        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy file to temp directory
            temp_script = Path(tmpdir) / "script.py"
            shutil.copy2(file_path, temp_script)
            
            # Create tar archive
            import tarfile
            import io
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                tar.add(str(temp_script), arcname='script.py')
            tar_stream.seek(0)
            
            # Copy to container
            container.put_archive('/tmp', tar_stream.read())
            
            # Build command
            cmd = ['python', '/tmp/script.py']
            if args:
                cmd.extend(args)
            
            # Execute in container
            try:
                exec_result = container.exec_run(
                    cmd=cmd,
                    stdout=True,
                    stderr=True,
                    demux=True,
                    environment=env
                )
                
                stdout = exec_result.output[0] if exec_result.output[0] else b''
                stderr = exec_result.output[1] if exec_result.output[1] else b''
                
                return {
                    'success': exec_result.exit_code == 0,
                    'returncode': exec_result.exit_code,
                    'stdout': stdout.decode('utf-8', errors='replace'),
                    'stderr': stderr.decode('utf-8', errors='replace'),
                    'execution_mode': 'docker',
                    'container_id': container.short_id,
                    'trusted': False
                }
                
            except Exception as e:
                logger.error(f"Failed to execute {file_path} in Docker: {e}")
                return {
                    'success': False,
                    'error': str(e),
                    'execution_mode': 'docker'
                }
    
    async def _get_or_create_container(self) -> ResourceInstance[DockerConfig]:
        """Get existing container or create new one"""
        # Try to get healthy instance
        for instance in self.instances.values():
            if instance.status == ResourceStatus.HEALTHY:
                return instance
        
        # Create new container
        config = DockerConfig(
            image=self.docker_image,
            memory_limit='512m',
            cpu_limit=1.0,
            network_mode='none'  # Isolated network for security
        )
        
        instance = await self.create_resource(config)
        await self.register_instance(instance)
        return instance
    
    async def _validate_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate Python file syntax"""
        file_path = params.get('file') or params.get('file_path')
        if not file_path:
            raise InvalidParameterError(param_name='file', reason="Missing 'file' or 'file_path' parameter")
        
        file_path = Path(file_path).resolve()
        
        if not file_path.exists():
            return {
                'valid': False,
                'error': f'File not found: {file_path}'
            }
        
        if not file_path.suffix == '.py':
            return {
                'valid': False,
                'error': f'Not a Python file: {file_path}'
            }
        
        try:
            with open(file_path, 'r') as f:
                code = f.read()
            
            compile(code, str(file_path), 'exec')
            return {
                'valid': True,
                'message': 'Python syntax is valid',
                'file': str(file_path)
            }
        except SyntaxError as e:
            return {
                'valid': False,
                'error': str(e),
                'line': e.lineno,
                'offset': e.offset,
                'file': str(file_path)
            }
    
    def _get_info(self) -> Dict[str, Any]:
        """Get provider information"""
        return {
            'provider': self.provider_id,
            'protocol': self.protocol_id,
            'docker_available': DOCKER_AVAILABLE,
            'docker_image': self.docker_image,
            'allow_local': self.allow_local,
            'trusted_dirs': [str(d) for d in self.trusted_dirs],
            'total_containers': len(self.instances),
            'healthy_containers': sum(
                1 for inst in self.instances.values()
                if inst.status == ResourceStatus.HEALTHY
            )
        }
    
    async def create_resource(self, config: DockerConfig) -> ResourceInstance[DockerConfig]:
        """Create Docker container for Python execution"""
        if not self.docker_client:
            raise TaskExecutionError("Docker client not available")
        
        try:
            container = self.docker_client.containers.run(
                image=config.image,
                detach=True,
                mem_limit=config.memory_limit,
                nano_cpus=int(config.cpu_limit * 1e9),
                network_mode=config.network_mode,
                labels=config.labels,
                command="sleep infinity",  # Keep container running
                remove=False
            )
            
            instance = ResourceInstance(
                id=f"python-{container.short_id}",
                name=f"Python Container {container.short_id}",
                type=ResourceType.DOCKER,
                endpoint=f"container://{container.id}",
                status=ResourceStatus.HEALTHY,
                config=config,
                metadata={'container': container},
                capabilities=set(self.get_supported_methods()),
                tags={'python', 'docker'}
            )
            
            logger.info(f"Created Python container: {container.short_id}")
            return instance
            
        except Exception as e:
            logger.error(f"Failed to create Docker container: {e}")
            raise TaskExecutionError(f"Failed to create container: {e}")
    
    async def destroy_resource(self, instance: ResourceInstance[DockerConfig]) -> None:
        """Destroy Docker container"""
        container = instance.metadata.get('container')
        if container:
            try:
                container.stop(timeout=5)
                container.remove()
                logger.info(f"Destroyed container: {container.short_id}")
            except Exception as e:
                logger.error(f"Failed to destroy container: {e}")
    
    async def check_resource_health(self, instance: ResourceInstance[DockerConfig]) -> bool:
        """Check if container is healthy"""
        container = instance.metadata.get('container')
        if not container:
            return False
        
        try:
            container.reload()
            return container.status == 'running'
        except Exception:
            return False
    
    async def execute_on_resource(
        self,
        instance: ResourceInstance[DockerConfig],
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute method on specific container"""
        # For now, just delegate to main execute
        return await self.execute(method, params)
    
    async def discover_resources(self) -> List[ResourceInstance[DockerConfig]]:
        """Discover existing Python containers"""
        if not self.docker_client:
            return []
        
        discovered = []
        try:
            containers = self.docker_client.containers.list(
                filters={'label': 'gleitzeit.provider=python'}
            )
            
            for container in containers:
                instance = ResourceInstance(
                    id=f"python-{container.short_id}",
                    name=f"Python Container {container.short_id}",
                    type=ResourceType.DOCKER,
                    endpoint=f"container://{container.id}",
                    status=ResourceStatus.HEALTHY if container.status == 'running' else ResourceStatus.UNHEALTHY,
                    config=DockerConfig(image=container.image.tags[0] if container.image.tags else 'unknown'),
                    metadata={'container': container},
                    capabilities=set(self.get_supported_methods()),
                    tags={'python', 'docker', 'discovered'}
                )
                discovered.append(instance)
            
        except Exception as e:
            logger.error(f"Failed to discover containers: {e}")
        
        return discovered