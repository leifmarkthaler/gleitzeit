"""
Docker Hub - Manages Docker containers as compute resources
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
from datetime import datetime
import json

try:
    import docker
    from docker.models.containers import Container
    from docker.errors import DockerException, ContainerError, ImageNotFound
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    Container = Any

from .base import ResourceHub, ResourceInstance, ResourceStatus, ResourceMetrics, ResourceType

logger = logging.getLogger(__name__)


@dataclass
class DockerConfig:
    """Configuration for a Docker container"""
    image: str = "python:3.11-slim"
    name: Optional[str] = None
    command: Optional[str] = None
    environment: Dict[str, str] = field(default_factory=dict)
    volumes: Dict[str, Dict[str, str]] = field(default_factory=dict)
    ports: Dict[str, int] = field(default_factory=dict)
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    network_mode: str = "bridge"
    labels: Dict[str, str] = field(default_factory=dict)
    restart_policy: Dict[str, Any] = field(default_factory=dict)
    auto_remove: bool = False
    detach: bool = True
    privileged: bool = False
    user: Optional[str] = None
    working_dir: Optional[str] = None
    container_id: Optional[str] = None  # Actual Docker container ID


class DockerHub(ResourceHub[DockerConfig]):
    """
    Hub for managing Docker containers as compute resources
    
    Features:
    - Container lifecycle management
    - Resource limit enforcement
    - Container pooling for reuse
    - Image management
    - Network isolation options
    - Volume management
    """
    
    def __init__(
        self,
        hub_id: str = "docker-hub",
        health_check_interval: int = 30,
        max_health_failures: int = 3,
        enable_auto_recovery: bool = True,
        enable_metrics: bool = True,
        enable_container_reuse: bool = True,
        max_containers_per_image: int = 10
    ):
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.DOCKER,
            health_check_interval=health_check_interval,
            max_health_failures=max_health_failures,
            enable_auto_recovery=enable_auto_recovery,
            enable_metrics=enable_metrics
        )
        
        self.enable_container_reuse = enable_container_reuse
        self.max_containers_per_image = max_containers_per_image
        
        # Docker client
        self.docker_client = None
        if DOCKER_AVAILABLE:
            try:
                self.docker_client = docker.from_env()
                self.docker_client.ping()
                logger.info("Docker client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Docker client: {e}")
                self.docker_client = None
        
        # Container pools by image
        self.container_pools: Dict[str, List[Container]] = {}
        self.pool_lock = asyncio.Lock()
    
    async def check_health(self, instance: ResourceInstance[DockerConfig]) -> bool:
        """Check health of a Docker container"""
        if not self.docker_client or not instance.config or not instance.config.container_id:
            return False
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            container.reload()
            
            # Check container status
            if container.status == 'running':
                # Check if container has health check
                if 'Health' in container.attrs.get('State', {}):
                    health = container.attrs['State']['Health']
                    return health.get('Status') == 'healthy'
                return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Health check failed for {instance.id}: {e}")
            return False
    
    async def collect_metrics(self, instance: ResourceInstance[DockerConfig]) -> ResourceMetrics:
        """Collect metrics from a Docker container"""
        metrics = ResourceMetrics()
        
        if not self.docker_client or not instance.config or not instance.config.container_id:
            return metrics
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            
            # Get container stats
            stats = container.stats(stream=False)
            
            # CPU metrics
            cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                       stats['precpu_stats']['cpu_usage']['total_usage']
            system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                          stats['precpu_stats']['system_cpu_usage']
            
            if system_delta > 0:
                metrics.cpu_percent = (cpu_delta / system_delta) * 100.0
            
            # Memory metrics
            memory_usage = stats['memory_stats'].get('usage', 0)
            memory_limit = stats['memory_stats'].get('limit', 1)
            metrics.memory_mb = memory_usage / 1024 / 1024
            metrics.memory_percent = (memory_usage / memory_limit) * 100.0
            
            # Network I/O
            networks = stats.get('networks', {})
            for net_stats in networks.values():
                metrics.network_io_mb += (net_stats.get('rx_bytes', 0) + 
                                         net_stats.get('tx_bytes', 0)) / 1024 / 1024
            
            # Disk I/O
            blkio_stats = stats.get('blkio_stats', {})
            for entry in blkio_stats.get('io_service_bytes_recursive', []):
                if entry.get('op') in ['Read', 'Write']:
                    metrics.disk_io_mb += entry.get('value', 0) / 1024 / 1024
            
            # Container-specific metrics
            metrics.custom_metrics['container_status'] = container.status
            metrics.custom_metrics['image'] = container.image.tags[0] if container.image.tags else 'unknown'
            metrics.custom_metrics['created'] = container.attrs['Created']
            
        except Exception as e:
            logger.error(f"Failed to collect metrics for {instance.id}: {e}")
        
        metrics.last_updated = datetime.utcnow()
        return metrics
    
    async def start_instance(self, config: DockerConfig) -> ResourceInstance[DockerConfig]:
        """Start a new Docker container"""
        if not self.docker_client:
            raise RuntimeError("Docker client not available")
        
        # Check for reusable container
        if self.enable_container_reuse and config.image in self.container_pools:
            async with self.pool_lock:
                pool = self.container_pools[config.image]
                for container in pool:
                    try:
                        container.reload()
                        if container.status == 'exited':
                            # Restart the container
                            container.start()
                            logger.info(f"Reused container {container.short_id} from pool")
                            
                            config.container_id = container.id
                            instance_id = f"docker-{container.short_id}"
                            
                            # Register the instance
                            return await self._register_container_instance(
                                container, instance_id, config
                            )
                    except Exception as e:
                        logger.debug(f"Could not reuse container: {e}")
        
        # Create new container
        try:
            # Ensure image exists
            try:
                self.docker_client.images.get(config.image)
            except ImageNotFound:
                logger.info(f"Pulling image {config.image}")
                self.docker_client.images.pull(config.image)
            
            # Prepare container configuration
            container_config = {
                'image': config.image,
                'command': config.command,
                'environment': config.environment,
                'volumes': config.volumes,
                'mem_limit': config.memory_limit,
                'nano_cpus': int(config.cpu_limit * 1e9),
                'network_mode': config.network_mode,
                'labels': config.labels,
                'restart_policy': config.restart_policy,
                'auto_remove': config.auto_remove,
                'detach': config.detach,
                'privileged': config.privileged,
                'user': config.user,
                'working_dir': config.working_dir
            }
            
            # Add name if specified
            if config.name:
                container_config['name'] = config.name
            
            # Add ports if specified
            if config.ports:
                container_config['ports'] = config.ports
            
            # For Python containers, keep them running with a sleep command if no command specified
            if 'python' in config.image and not config.command:
                container_config['command'] = 'sh -c "while true; do sleep 30; done"'
            
            # Remove None values
            container_config = {k: v for k, v in container_config.items() if v is not None}
            
            # Create and start container
            container = self.docker_client.containers.run(**container_config)
            config.container_id = container.id
            
            logger.info(f"Started Docker container {container.short_id} ({config.image})")
            
            # Add to pool if reuse enabled
            if self.enable_container_reuse:
                async with self.pool_lock:
                    if config.image not in self.container_pools:
                        self.container_pools[config.image] = []
                    
                    if len(self.container_pools[config.image]) < self.max_containers_per_image:
                        self.container_pools[config.image].append(container)
            
            instance_id = f"docker-{container.short_id}"
            return await self._register_container_instance(container, instance_id, config)
            
        except Exception as e:
            logger.error(f"Failed to start Docker container: {e}")
            raise
    
    async def stop_instance(self, instance_id: str) -> bool:
        """Stop a Docker container"""
        instance = await self.get_instance(instance_id)
        if not instance or not instance.config or not instance.config.container_id:
            return False
        
        if not self.docker_client:
            return False
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            
            # Stop the container
            container.stop(timeout=10)
            
            # Remove from pool if present
            if self.enable_container_reuse and instance.config.image in self.container_pools:
                async with self.pool_lock:
                    pool = self.container_pools[instance.config.image]
                    pool = [c for c in pool if c.id != container.id]
                    self.container_pools[instance.config.image] = pool
            
            # Remove container if auto_remove is False (otherwise Docker does it)
            if not instance.config.auto_remove:
                container.remove()
            
            logger.info(f"Stopped Docker container {instance_id}")
            
        except Exception as e:
            logger.error(f"Failed to stop container {instance_id}: {e}")
            return False
        
        await self.unregister_instance(instance_id)
        return True
    
    async def restart_instance(self, instance_id: str) -> bool:
        """Restart a Docker container"""
        instance = await self.get_instance(instance_id)
        if not instance or not instance.config or not instance.config.container_id:
            return False
        
        if not self.docker_client:
            return False
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            container.restart(timeout=10)
            
            logger.info(f"Restarted Docker container {instance_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to restart container {instance_id}: {e}")
            return False
    
    async def execute_in_container(
        self,
        instance_id: str,
        command: str,
        workdir: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        user: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute a command in a running container"""
        instance = await self.get_instance(instance_id)
        if not instance or not instance.config or not instance.config.container_id:
            raise ValueError(f"Instance {instance_id} not found")
        
        if not self.docker_client:
            raise RuntimeError("Docker client not available")
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            
            # Execute command
            exec_result = container.exec_run(
                cmd=command,
                workdir=workdir,
                environment=environment,
                user=user,
                demux=True
            )
            
            stdout, stderr = exec_result.output
            
            return {
                'success': exec_result.exit_code == 0,
                'exit_code': exec_result.exit_code,
                'stdout': stdout.decode() if stdout else '',
                'stderr': stderr.decode() if stderr else ''
            }
            
        except Exception as e:
            logger.error(f"Failed to execute in container {instance_id}: {e}")
            raise
    
    async def copy_to_container(
        self,
        instance_id: str,
        source_path: str,
        dest_path: str
    ) -> bool:
        """Copy files to a container"""
        instance = await self.get_instance(instance_id)
        if not instance or not instance.config or not instance.config.container_id:
            return False
        
        if not self.docker_client:
            return False
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            
            with open(source_path, 'rb') as f:
                data = f.read()
            
            container.put_archive(dest_path, data)
            return True
            
        except Exception as e:
            logger.error(f"Failed to copy to container {instance_id}: {e}")
            return False
    
    async def copy_from_container(
        self,
        instance_id: str,
        source_path: str,
        dest_path: str
    ) -> bool:
        """Copy files from a container"""
        instance = await self.get_instance(instance_id)
        if not instance or not instance.config or not instance.config.container_id:
            return False
        
        if not self.docker_client:
            return False
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            
            bits, stat = container.get_archive(source_path)
            
            with open(dest_path, 'wb') as f:
                for chunk in bits:
                    f.write(chunk)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to copy from container {instance_id}: {e}")
            return False
    
    async def _register_container_instance(
        self,
        container: Container,
        instance_id: str,
        config: DockerConfig
    ) -> ResourceInstance[DockerConfig]:
        """Register a Docker container as an instance"""
        # Determine endpoint based on ports
        endpoint = f"docker://{container.short_id}"
        if config.ports:
            # Use first exposed port as primary endpoint
            first_port = list(config.ports.values())[0]
            endpoint = f"http://localhost:{first_port}"
        
        # Set tags based on configuration
        tags = {'docker', config.network_mode}
        if config.privileged:
            tags.add('privileged')
        if config.image:
            tags.add(config.image.split(':')[0])  # Add base image name
        
        # Set capabilities based on image
        capabilities = set()
        if 'python' in config.image:
            capabilities.add('python')
        if 'node' in config.image:
            capabilities.add('node')
        if 'java' in config.image or 'openjdk' in config.image:
            capabilities.add('java')
        
        return await self.register_instance(
            instance_id=instance_id,
            name=config.name or f"Container-{container.short_id}",
            endpoint=endpoint,
            metadata={
                'container_id': container.id,
                'image': config.image,
                'created': container.attrs['Created']
            },
            tags=tags,
            capabilities=capabilities,
            config=config
        )
    
    async def cleanup_stopped_containers(self):
        """Clean up stopped containers"""
        if not self.docker_client:
            return
        
        try:
            # Get all containers
            containers = self.docker_client.containers.list(all=True)
            
            for container in containers:
                # Check if container is managed by this hub
                if container.labels.get('gleitzeit.hub') == self.hub_id:
                    if container.status in ['exited', 'dead']:
                        logger.info(f"Removing stopped container {container.short_id}")
                        container.remove()
        
        except Exception as e:
            logger.error(f"Failed to cleanup containers: {e}")
    
    async def get_container_logs(
        self,
        instance_id: str,
        tail: int = 100,
        since: Optional[datetime] = None
    ) -> str:
        """Get logs from a container"""
        instance = await self.get_instance(instance_id)
        if not instance or not instance.config or not instance.config.container_id:
            return ""
        
        if not self.docker_client:
            return ""
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            
            kwargs = {'tail': tail}
            if since:
                kwargs['since'] = since
            
            logs = container.logs(**kwargs)
            return logs.decode() if isinstance(logs, bytes) else str(logs)
            
        except Exception as e:
            logger.error(f"Failed to get logs for {instance_id}: {e}")
            return ""
    
    async def stop(self):
        """Stop the Docker hub and cleanup"""
        # Stop all managed containers
        for instance_id in list(self.instances.keys()):
            await self.stop_instance(instance_id)
        
        # Cleanup pools
        self.container_pools.clear()
        
        await super().stop()