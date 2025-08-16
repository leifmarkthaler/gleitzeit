"""
Docker Executor - Runs Python code in isolated containers
"""
from typing import Dict, Any, Optional, List, Tuple
import asyncio
import logging
import json
import base64
import tempfile
import os
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

try:
    import docker
    from docker.models.containers import Container
    from docker.errors import DockerException, ContainerError, ImageNotFound, APIError
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    Container = Any

logger = logging.getLogger(__name__)


class SecurityLevel(Enum):
    """Security levels for code execution"""
    TRUSTED = "trusted"          # Direct execution on host
    RESTRICTED = "restricted"    # Local with restrictions
    SANDBOXED = "sandboxed"      # Full Docker isolation
    SPECIALIZED = "specialized"  # Pre-built environments


@dataclass
class ContainerConfig:
    """Configuration for a Docker container"""
    image: str = "python:3.11-slim"
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    network_mode: str = "none"
    read_only_root: bool = True
    volumes: Dict[str, Dict[str, str]] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)
    security_opt: List[str] = field(default_factory=list)
    cap_drop: List[str] = field(default_factory=lambda: ["ALL"])
    user: str = "nobody"
    working_dir: str = "/workspace"
    auto_remove: bool = False
    detach: bool = True
    

@dataclass
class ContainerInstance:
    """Represents a running container"""
    container: Container
    config: ContainerConfig
    created_at: datetime
    last_used: datetime
    execution_count: int = 0
    is_busy: bool = False
    
    @property
    def idle_time(self) -> float:
        """Time since last use in seconds"""
        return (datetime.now() - self.last_used).total_seconds()
        

class ContainerPool:
    """Manages a pool of reusable containers"""
    
    def __init__(
        self,
        max_containers: int = 10,
        idle_timeout: int = 300,
        reuse_containers: bool = True
    ):
        self.max_containers = max_containers
        self.idle_timeout = idle_timeout
        self.reuse_containers = reuse_containers
        self.containers: Dict[str, List[ContainerInstance]] = {}
        self.cleanup_task = None
        
    async def get_container(
        self, 
        config: ContainerConfig,
        docker_client: Any
    ) -> Container:
        """Get or create a container from the pool"""
        image_key = config.image
        
        # Try to reuse existing container
        if self.reuse_containers and image_key in self.containers:
            available = [
                c for c in self.containers[image_key]
                if not c.is_busy
            ]
            if available:
                container_inst = available[0]
                container_inst.is_busy = True
                container_inst.last_used = datetime.now()
                logger.debug(f"Reusing container {container_inst.container.short_id}")
                return container_inst.container
                
        # Create new container if pool not full
        if self._total_containers() < self.max_containers:
            container = await self._create_container(config, docker_client)
            container_inst = ContainerInstance(
                container=container,
                config=config,
                created_at=datetime.now(),
                last_used=datetime.now(),
                is_busy=True
            )
            
            if image_key not in self.containers:
                self.containers[image_key] = []
            self.containers[image_key].append(container_inst)
            
            logger.info(f"Created new container {container.short_id}")
            return container
            
        # Wait for available container
        logger.warning("Container pool full, waiting for available container")
        return await self._wait_for_container(config, docker_client)
        
    async def release_container(self, container: Container):
        """Release container back to pool"""
        for image_containers in self.containers.values():
            for container_inst in image_containers:
                if container_inst.container.id == container.id:
                    container_inst.is_busy = False
                    container_inst.execution_count += 1
                    container_inst.last_used = datetime.now()
                    logger.debug(f"Released container {container.short_id}")
                    return
                    
    async def cleanup_idle(self, docker_client: Any):
        """Remove idle containers"""
        removed_count = 0
        
        for image_key, image_containers in list(self.containers.items()):
            to_remove = []
            
            for container_inst in image_containers:
                if (not container_inst.is_busy and 
                    container_inst.idle_time > self.idle_timeout):
                    try:
                        container_inst.container.remove(force=True)
                        to_remove.append(container_inst)
                        removed_count += 1
                        logger.debug(f"Removed idle container {container_inst.container.short_id}")
                    except Exception as e:
                        logger.error(f"Failed to remove container: {e}")
                        
            # Remove from pool
            for container_inst in to_remove:
                image_containers.remove(container_inst)
                
            # Clean up empty lists
            if not image_containers:
                del self.containers[image_key]
                
        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} idle containers")
            
    async def shutdown(self, docker_client: Any):
        """Shutdown all containers in pool"""
        for image_containers in self.containers.values():
            for container_inst in image_containers:
                try:
                    container_inst.container.remove(force=True)
                    logger.debug(f"Shutdown container {container_inst.container.short_id}")
                except Exception as e:
                    logger.error(f"Failed to shutdown container: {e}")
                    
        self.containers.clear()
        
    def _total_containers(self) -> int:
        """Get total number of containers in pool"""
        return sum(len(containers) for containers in self.containers.values())
        
    async def _create_container(
        self, 
        config: ContainerConfig,
        docker_client: Any
    ) -> Container:
        """Create a new container"""
        # Build container configuration
        container_config = {
            'image': config.image,
            'mem_limit': config.memory_limit,
            'cpu_quota': int(config.cpu_limit * 100000),
            'cpu_period': 100000,
            'network_mode': config.network_mode,
            'volumes': config.volumes,
            'environment': config.environment,
            'security_opt': config.security_opt,
            'cap_drop': config.cap_drop,
            'user': config.user,
            'working_dir': config.working_dir,
            'auto_remove': config.auto_remove,
            'detach': config.detach,
            'stdin_open': True,
            'tty': False
        }
        
        if config.read_only_root:
            container_config['read_only'] = True
            # Add writable temp directory
            container_config['tmpfs'] = {'/tmp': 'size=100M,mode=1777'}
            
        # Create container
        container = docker_client.containers.create(**container_config)
        container.start()
        
        return container
        
    async def _wait_for_container(
        self,
        config: ContainerConfig,
        docker_client: Any,
        max_wait: int = 30
    ) -> Container:
        """Wait for an available container"""
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            # Check for available containers
            image_key = config.image
            if image_key in self.containers:
                available = [
                    c for c in self.containers[image_key]
                    if not c.is_busy
                ]
                if available:
                    container_inst = available[0]
                    container_inst.is_busy = True
                    container_inst.last_used = datetime.now()
                    return container_inst.container
                    
            await asyncio.sleep(0.5)
            
        # Timeout - create new container anyway
        return await self._create_container(config, docker_client)


class DockerExecutor:
    """
    Executes Python code in Docker containers for isolation
    """
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        pool_config: Optional[Dict[str, Any]] = None
    ):
        if not DOCKER_AVAILABLE:
            raise ImportError("Docker SDK not installed. Install with: pip install docker")
            
        self.config = config or {}
        self.docker_client = None
        self.container_pool = None
        self.cleanup_task = None
        
        # Initialize container pool
        pool_cfg = pool_config or {}
        self.container_pool = ContainerPool(
            max_containers=pool_cfg.get('max_containers', 10),
            idle_timeout=pool_cfg.get('idle_timeout', 300),
            reuse_containers=pool_cfg.get('reuse_containers', True)
        )
        
        # Security presets
        self.security_presets = {
            SecurityLevel.SANDBOXED: ContainerConfig(
                image="python:3.11-slim",
                memory_limit="512m",
                cpu_limit=1.0,
                network_mode="none",
                read_only_root=False,  # Need writable /tmp for script execution
                cap_drop=["ALL"],
                user="nobody",
                volumes={"/tmp": {"bind": "/tmp", "mode": "rw"}}  # Ensure /tmp is writable
            ),
            SecurityLevel.SPECIALIZED: ContainerConfig(
                image="gleitzeit/datascience:latest",
                memory_limit="2g",
                cpu_limit=2.0,
                network_mode="bridge",
                read_only_root=False,
                cap_drop=["NET_ADMIN", "SYS_ADMIN"],
                user="1000"
            )
        }
        
    async def initialize(self):
        """Initialize Docker client and start cleanup task"""
        try:
            self.docker_client = docker.from_env()
            # Test connection
            self.docker_client.ping()
            logger.info("Docker executor initialized successfully")
            
            # Start cleanup task
            self.cleanup_task = asyncio.create_task(self._cleanup_loop())
            
        except DockerException as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise
            
    async def shutdown(self):
        """Shutdown executor and cleanup resources"""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
                
        if self.container_pool and self.docker_client:
            await self.container_pool.shutdown(self.docker_client)
            
        if self.docker_client:
            self.docker_client.close()
            
    async def execute(
        self,
        code: str,
        image: str = "python:3.11-slim",
        timeout: int = 60,
        memory_limit: str = "512m",
        cpu_limit: float = 1.0,
        network_mode: str = "none",
        volumes: Optional[Dict[str, Dict[str, str]]] = None,
        environment: Optional[Dict[str, str]] = None,
        security_level: SecurityLevel = SecurityLevel.SANDBOXED,
        files: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Execute Python code in a Docker container
        
        Args:
            code: Python code to execute
            image: Docker image to use
            timeout: Execution timeout in seconds
            memory_limit: Memory limit (e.g., "512m", "1g")
            cpu_limit: CPU limit (1.0 = 1 CPU)
            network_mode: Network mode ("none", "bridge", "host")
            volumes: Volume mounts
            environment: Environment variables
            security_level: Security level preset
            files: Additional files to include
            
        Returns:
            Execution result with stdout, stderr, exit_code
        """
        if not self.docker_client:
            await self.initialize()
            
        # Get container configuration
        if security_level in self.security_presets:
            config = self.security_presets[security_level]
            # Override with custom settings
            config.image = image
            config.memory_limit = memory_limit
            config.cpu_limit = cpu_limit
            if network_mode:
                config.network_mode = network_mode
        else:
            config = ContainerConfig(
                image=image,
                memory_limit=memory_limit,
                cpu_limit=cpu_limit,
                network_mode=network_mode,
                volumes=volumes or {},
                environment=environment or {}
            )
            
        container = None
        try:
            # Get container from pool
            container = await self.container_pool.get_container(
                config, 
                self.docker_client
            )
            
            # Prepare execution script
            exec_script = self._prepare_script(code, files)
            
            # Execute code in container
            result = await self._execute_in_container(
                container,
                exec_script,
                timeout
            )
            
            return result
            
        except ImageNotFound:
            logger.error(f"Docker image not found: {image}")
            return {
                'success': False,
                'error': f"Docker image not found: {image}",
                'stdout': '',
                'stderr': '',
                'exit_code': 1
            }
            
        except ContainerError as e:
            logger.error(f"Container execution error: {e}")
            return {
                'success': False,
                'error': str(e),
                'stdout': e.stdout.decode() if e.stdout else '',
                'stderr': e.stderr.decode() if e.stderr else '',
                'exit_code': e.exit_status
            }
            
        except asyncio.TimeoutError:
            logger.error(f"Execution timeout after {timeout} seconds")
            if container:
                try:
                    container.kill()
                except Exception:
                    pass
            return {
                'success': False,
                'error': f"Execution timeout after {timeout} seconds",
                'stdout': '',
                'stderr': '',
                'exit_code': -1
            }
            
        except Exception as e:
            logger.error(f"Unexpected error during execution: {e}")
            return {
                'success': False,
                'error': str(e),
                'stdout': '',
                'stderr': '',
                'exit_code': -1
            }
            
        finally:
            # Always release container back to pool
            if container and self.container_pool:
                await self.container_pool.release_container(container)
                
    async def execute_file(
        self,
        file_path: str,
        args: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute a Python file in container"""
        with open(file_path, 'r') as f:
            code = f.read()
            
        # Inject arguments if provided
        if args:
            arg_code = "\n".join([
                f"{key} = {repr(value)}"
                for key, value in args.items()
            ])
            code = arg_code + "\n\n" + code
            
        return await self.execute(code, **kwargs)
        
    async def batch_execute(
        self,
        tasks: List[Dict[str, Any]],
        max_concurrent: int = 5
    ) -> List[Dict[str, Any]]:
        """Execute multiple tasks in parallel"""
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def execute_with_semaphore(task):
            async with semaphore:
                return await self.execute(**task)
                
        results = await asyncio.gather(
            *[execute_with_semaphore(task) for task in tasks],
            return_exceptions=True
        )
        
        # Convert exceptions to error results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    'success': False,
                    'error': str(result),
                    'stdout': '',
                    'stderr': '',
                    'exit_code': -1
                })
            else:
                processed_results.append(result)
                
        return processed_results
        
    async def pull_image(self, image: str) -> bool:
        """Pull a Docker image if not present"""
        try:
            self.docker_client.images.pull(image)
            logger.info(f"Pulled Docker image: {image}")
            return True
        except Exception as e:
            logger.error(f"Failed to pull image {image}: {e}")
            return False
            
    async def list_images(self) -> List[str]:
        """List available Docker images"""
        try:
            images = self.docker_client.images.list()
            return [
                tag for image in images 
                for tag in image.tags
            ]
        except Exception as e:
            logger.error(f"Failed to list images: {e}")
            return []
            
    async def get_pool_status(self) -> Dict[str, Any]:
        """Get container pool status"""
        status = {
            'total_containers': 0,
            'busy_containers': 0,
            'idle_containers': 0,
            'by_image': {}
        }
        
        for image, containers in self.container_pool.containers.items():
            busy = sum(1 for c in containers if c.is_busy)
            idle = len(containers) - busy
            
            status['total_containers'] += len(containers)
            status['busy_containers'] += busy
            status['idle_containers'] += idle
            status['by_image'][image] = {
                'total': len(containers),
                'busy': busy,
                'idle': idle
            }
            
        return status
        
    # Private methods
    
    def _prepare_script(
        self, 
        code: str,
        files: Optional[Dict[str, str]] = None
    ) -> str:
        """Prepare execution script with proper error handling"""
        script_parts = [
            "import sys",
            "import traceback",
            "import json",
            "",
            "# User-provided files",
        ]
        
        # Add any additional files
        if files:
            for filename, content in files.items():
                # Escape the content
                escaped_content = content.replace('\\', '\\\\').replace('"', '\\"')
                script_parts.append(f'with open("{filename}", "w") as f:')
                script_parts.append(f'    f.write("{escaped_content}")')
                
        script_parts.extend([
            "",
            "# User code execution",
            "try:",
            "    exec_globals = {}",
            "    exec_locals = {}",
            f"    exec({repr(code)}, exec_globals, exec_locals)",
            "    # Extract result if defined",
            "    if 'result' in exec_locals:",
            "        print(json.dumps({'result': exec_locals['result']}))",
            "    elif 'result' in exec_globals:",
            "        print(json.dumps({'result': exec_globals['result']}))",
            "except Exception as e:",
            "    traceback.print_exc()",
            "    sys.exit(1)"
        ])
        
        return "\n".join(script_parts)
        
    async def _execute_in_container(
        self,
        container: Container,
        script: str,
        timeout: int
    ) -> Dict[str, Any]:
        """Execute script in container with timeout"""
        # Create temporary script file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False
        ) as f:
            f.write(script)
            script_path = f.name
            
        try:
            # Copy script to container
            with open(script_path, 'rb') as f:
                container.put_archive(
                    '/tmp',
                    self._create_tar_archive('script.py', f.read())
                )
                
            # Execute script
            exec_result = container.exec_run(
                cmd=['python', '/tmp/script.py'],
                stdout=True,
                stderr=True,
                demux=True
            )
            
            stdout = exec_result.output[0] if exec_result.output[0] else b''
            stderr = exec_result.output[1] if exec_result.output[1] else b''
            
            # Parse result
            result = {
                'success': exec_result.exit_code == 0,
                'stdout': stdout.decode('utf-8', errors='replace'),
                'stderr': stderr.decode('utf-8', errors='replace'),
                'exit_code': exec_result.exit_code
            }
            
            # Try to extract JSON result
            if result['success'] and result['stdout']:
                try:
                    import json
                    last_line = result['stdout'].strip().split('\n')[-1]
                    if last_line.startswith('{') and last_line.endswith('}'):
                        parsed = json.loads(last_line)
                        if 'result' in parsed:
                            result['result'] = parsed['result']
                except Exception:
                    pass
                    
            return result
            
        finally:
            # Clean up temp file
            os.unlink(script_path)
            
    def _create_tar_archive(self, filename: str, content: bytes) -> bytes:
        """Create a tar archive with a single file"""
        import tarfile
        import io
        
        tar_stream = io.BytesIO()
        tar = tarfile.TarFile(fileobj=tar_stream, mode='w')
        
        # Create tarinfo
        tarinfo = tarfile.TarInfo(name=filename)
        tarinfo.size = len(content)
        tarinfo.mtime = time.time()
        
        # Add file to archive
        tar.addfile(tarinfo, io.BytesIO(content))
        tar.close()
        
        return tar_stream.getvalue()
        
    async def _cleanup_loop(self):
        """Periodic cleanup of idle containers"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self.container_pool.cleanup_idle(self.docker_client)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
