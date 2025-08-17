"""
Docker Hub - Manages Docker containers as compute resources
"""
import asyncio
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

try:
    import docker
    from docker.models.containers import Container
    DOCKER_AVAILABLE = True
except ImportError:
    docker = None
    Container = Any
    DOCKER_AVAILABLE = False

from .base import ResourceHub, ResourceInstance, ResourceStatus, ResourceMetrics, ResourceType
from .configs import DockerConfig

logger = logging.getLogger(__name__)


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
        enable_container_reuse: bool = True,
        enable_metrics: bool = True,
        max_instances: int = 20,
        default_image: str = "python:3.11-slim",
        persistence: Optional[Any] = None
    ):
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.DOCKER,
            enable_metrics=enable_metrics,
            persistence=persistence
        )
        
        self.max_instances = max_instances
        self.enable_container_reuse = enable_container_reuse
        self.default_image = default_image
        self.docker_client = None
        self.container_pool: Dict[str, List[Container]] = {}  # image -> available containers
        
        if not DOCKER_AVAILABLE:
            logger.warning("Docker SDK not available. Install with: pip install docker")
        
        logger.info(f"Initialized DockerHub {hub_id}")
    
    async def initialize(self) -> None:
        """Initialize the Docker hub"""
        if DOCKER_AVAILABLE:
            try:
                self.docker_client = docker.from_env()
                # Test connection
                self.docker_client.ping()
                logger.info("Connected to Docker daemon")
                
                # Clean up any orphaned containers
                await self._cleanup_orphaned_containers()
            except Exception as e:
                logger.error(f"Failed to connect to Docker: {e}")
                self.docker_client = None
    
    async def _cleanup_orphaned_containers(self):
        """Clean up any orphaned containers from previous runs"""
        if not self.docker_client:
            return
        
        try:
            containers = self.docker_client.containers.list(
                all=True,
                filters={"label": f"gleitzeit.hub={self.hub_id}"}
            )
            
            for container in containers:
                if container.status in ["exited", "dead"]:
                    logger.info(f"Removing orphaned container {container.short_id}")
                    container.remove(force=True)
        except Exception as e:
            logger.error(f"Failed to cleanup orphaned containers: {e}")
    
    async def create_resource(self, config: DockerConfig) -> Optional[ResourceInstance[DockerConfig]]:
        """Create a Docker container resource"""
        if not self.docker_client:
            logger.error("Docker client not available")
            return None
        
        try:
            # Prepare container configuration
            container_config = {
                "image": config.image,
                "command": config.command,
                "environment": config.environment,
                "volumes": config.volumes,
                "ports": config.ports,
                "mem_limit": config.memory_limit,
                "cpu_quota": int(config.cpu_limit * 100000),  # Convert to Docker CPU quota
                "network_mode": config.network_mode,
                "labels": {
                    **config.labels,
                    "gleitzeit.hub": self.hub_id,
                    "gleitzeit.created": datetime.utcnow().isoformat()
                },
                "auto_remove": config.auto_remove,
                "detach": config.detach,
                "privileged": config.privileged,
                "user": config.user,
                "working_dir": config.working_dir,
                "name": config.name,
                "restart_policy": config.restart_policy
            }
            
            # Remove None values
            container_config = {k: v for k, v in container_config.items() if v is not None}
            
            # Check if we can reuse a container
            if self.enable_container_reuse and config.image in self.container_pool:
                available = self.container_pool[config.image]
                if available:
                    container = available.pop()
                    logger.info(f"Reusing container {container.short_id} for {config.image}")
                    config.container_id = container.id
                    
                    # Start the container if needed
                    if container.status != "running":
                        container.start()
                    
                    instance = self._create_instance_from_container(container, config)
                    return instance
            
            # Create new container
            logger.info(f"Creating new container from {config.image}")
            container = self.docker_client.containers.run(**container_config)
            config.container_id = container.id
            
            instance = self._create_instance_from_container(container, config)
            return instance
            
        except Exception as e:
            logger.error(f"Failed to create Docker container: {e}")
            return None
    
    def _create_instance_from_container(
        self,
        container: Container,
        config: DockerConfig
    ) -> ResourceInstance[DockerConfig]:
        """Create a ResourceInstance from a Docker container"""
        # Get container details
        container.reload()
        
        # Determine endpoint based on exposed ports
        endpoint = None
        if container.ports:
            # Get the first exposed port
            for internal_port, mappings in container.ports.items():
                if mappings:
                    host_port = mappings[0]['HostPort']
                    endpoint = f"http://localhost:{host_port}"
                    break
        
        instance = ResourceInstance(
            id=container.short_id,
            name=container.name or container.short_id,
            type=ResourceType.DOCKER,
            endpoint=endpoint or f"container://{container.short_id}",
            status=self._get_container_status(container),
            config=config,
            capabilities={config.image, "docker", "container"},
            tags={"docker", f"image:{config.image}"},
            metrics=ResourceMetrics()
        )
        
        return instance
    
    def _get_container_status(self, container: Container) -> ResourceStatus:
        """Map Docker container status to ResourceStatus"""
        container.reload()
        
        status_map = {
            "running": ResourceStatus.HEALTHY,
            "created": ResourceStatus.STARTING,
            "restarting": ResourceStatus.STARTING,
            "paused": ResourceStatus.UNHEALTHY,
            "exited": ResourceStatus.STOPPED,
            "dead": ResourceStatus.STOPPED,
            "removing": ResourceStatus.STOPPING
        }
        
        return status_map.get(container.status, ResourceStatus.UNKNOWN)
    
    async def check_resource_health(self, instance: ResourceInstance[DockerConfig]) -> ResourceMetrics:
        """Check health of a Docker container"""
        metrics = instance.metrics or ResourceMetrics()
        
        if not self.docker_client or not instance.config.container_id:
            instance.status = ResourceStatus.UNKNOWN
            return metrics
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            container.reload()
            
            # Update status
            instance.status = self._get_container_status(container)
            
            # Get container stats
            stats = container.stats(stream=False)
            
            # Update metrics
            if stats:
                # CPU usage
                cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                           stats['precpu_stats']['cpu_usage']['total_usage']
                system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                              stats['precpu_stats']['system_cpu_usage']
                if system_delta > 0:
                    metrics.cpu_usage_percent = (cpu_delta / system_delta) * 100
                
                # Memory usage
                memory_usage = stats['memory_stats'].get('usage', 0)
                memory_limit = stats['memory_stats'].get('limit', 1)
                metrics.memory_usage_mb = memory_usage / (1024 * 1024)
                metrics.memory_usage_percent = (memory_usage / memory_limit) * 100
            
            metrics.last_check = datetime.utcnow()
            
        except docker.errors.NotFound:
            instance.status = ResourceStatus.STOPPED
            logger.warning(f"Container {instance.id} not found")
        except Exception as e:
            instance.status = ResourceStatus.UNKNOWN
            metrics.error_count += 1
            logger.error(f"Failed to check container health: {e}")
        
        return metrics
    
    async def start_instance(self, config: DockerConfig) -> ResourceInstance[DockerConfig]:
        """Start a new Docker container"""
        instance = await self.create_resource(config)
        if instance:
            await self.register_instance(instance)
        return instance
    
    async def stop_instance(self, instance_id: str) -> bool:
        """Stop a Docker container"""
        instance = await self.get_instance(instance_id)
        if not instance or not instance.config.container_id:
            return False
        
        if not self.docker_client:
            return False
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            
            if self.enable_container_reuse and not instance.config.auto_remove:
                # Stop but keep for reuse
                container.stop(timeout=10)
                logger.info(f"Stopped container {instance_id} for reuse")
                
                # Add to pool
                image = instance.config.image
                if image not in self.container_pool:
                    self.container_pool[image] = []
                self.container_pool[image].append(container)
            else:
                # Stop and remove
                container.stop(timeout=10)
                container.remove()
                logger.info(f"Stopped and removed container {instance_id}")
            
            await self.unregister_instance(instance_id)
            return True
            
        except docker.errors.NotFound:
            logger.warning(f"Container {instance_id} not found")
            await self.unregister_instance(instance_id)
            return True
        except Exception as e:
            logger.error(f"Failed to stop container: {e}")
            return False
    
    async def restart_instance(self, instance_id: str) -> bool:
        """Restart a Docker container"""
        instance = await self.get_instance(instance_id)
        if not instance or not instance.config.container_id:
            return False
        
        if not self.docker_client:
            return False
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            container.restart(timeout=10)
            logger.info(f"Restarted container {instance_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to restart container: {e}")
            return False
    
    async def check_health(self, instance: ResourceInstance[DockerConfig]) -> bool:
        """
        Check the health of a Docker container
        
        Args:
            instance: The resource instance to check
            
        Returns:
            True if healthy, False otherwise
        """
        if not instance.config or not instance.config.container_id:
            return False
        
        if not self.docker_client:
            return False
            
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            container.reload()
            return container.status == "running"
        except Exception as e:
            logger.debug(f"Health check failed for {instance.id}: {e}")
            return False
    
    async def collect_metrics(self, instance: ResourceInstance[DockerConfig]) -> ResourceMetrics:
        """
        Collect metrics from a Docker container
        
        Args:
            instance: The resource instance to collect metrics from
            
        Returns:
            ResourceMetrics with current metrics
        """
        from gleitzeit.hub.base import ResourceMetrics
        
        metrics = ResourceMetrics(
            cpu_usage=0.0,
            memory_usage=0.0,
            gpu_usage=0.0,
            request_count=0,
            error_count=0,
            average_latency=0.0,
            active_requests=0
        )
        
        if not instance.config or not instance.config.container_id:
            return metrics
        
        if not self.docker_client:
            return metrics
            
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            stats = container.stats(stream=False)
            
            # Calculate CPU usage
            cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                       stats["precpu_stats"]["cpu_usage"]["total_usage"]
            system_delta = stats["cpu_stats"]["system_cpu_usage"] - \
                          stats["precpu_stats"]["system_cpu_usage"]
            if system_delta > 0:
                metrics.cpu_usage = (cpu_delta / system_delta) * 100.0
            
            # Calculate memory usage
            if "memory_stats" in stats and "usage" in stats["memory_stats"]:
                metrics.memory_usage = stats["memory_stats"]["usage"] / (1024 * 1024)  # Convert to MB
                
        except Exception as e:
            logger.debug(f"Failed to collect metrics for {instance.id}: {e}")
            metrics.error_count += 1
        
        return metrics
    
    async def execute_in_container(
        self,
        instance_id: str,
        command: str,
        environment: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Execute a command in a running container"""
        instance = await self.get_instance(instance_id)
        if not instance or not instance.config.container_id:
            raise ValueError(f"Instance {instance_id} not found")
        
        if not self.docker_client:
            raise RuntimeError("Docker client not available")
        
        try:
            container = self.docker_client.containers.get(instance.config.container_id)
            
            # Execute command
            result = container.exec_run(
                command,
                environment=environment,
                stdout=True,
                stderr=True
            )
            
            return {
                "exit_code": result.exit_code,
                "output": result.output.decode('utf-8') if result.output else "",
                "success": result.exit_code == 0
            }
            
        except Exception as e:
            logger.error(f"Failed to execute in container: {e}")
            raise
    
    async def cleanup(self) -> None:
        """Clean up all Docker containers"""
        if self.docker_client:
            # Stop all managed containers
            for instance_id, instance in list(self.instances.items()):
                if instance.config and instance.config.container_id:
                    await self.stop_instance(instance_id)
            
            # Clean up pooled containers
            for image, containers in self.container_pool.items():
                for container in containers:
                    try:
                        container.stop(timeout=5)
                        container.remove()
                    except:
                        pass
            
            self.container_pool.clear()
        
        await super().cleanup()