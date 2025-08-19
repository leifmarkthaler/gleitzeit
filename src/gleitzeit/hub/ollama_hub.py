"""
Ollama Hub - Manages multiple Ollama instances
"""
import asyncio
import aiohttp
import logging
from typing import Dict, List, Any, Optional, Set
from datetime import datetime
import psutil
import subprocess

from .base import ResourceHub, ResourceInstance, ResourceStatus, ResourceMetrics, ResourceType
from .configs import OllamaConfig

logger = logging.getLogger(__name__)


class OllamaHub(ResourceHub[OllamaConfig]):
    """
    Hub for managing multiple Ollama instances
    
    Features:
    - Automatic discovery of running Ollama instances
    - Model-aware load balancing
    - GPU/CPU resource optimization
    - Automatic model pulling
    - Process management for local instances
    """
    
    def __init__(
        self,
        hub_id: str = "ollama-hub",
        auto_discover: bool = True,
        enable_metrics: bool = True,
        max_instances: int = 10,
        discovery_ports: Optional[List[int]] = None,
        persistence: Optional[Any] = None
    ):
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.OLLAMA,
            enable_metrics=enable_metrics,
            persistence=persistence
        )
        
        self.max_instances = max_instances
        self.auto_discover = auto_discover
        self.discovery_ports = discovery_ports or list(range(11434, 11439))
        self.model_cache: Dict[str, Set[str]] = {}  # instance_id -> set of models
        self.session: Optional[aiohttp.ClientSession] = None  # Shared session pool
        
        logger.info(f"Initialized OllamaHub {hub_id} with auto_discover={auto_discover}")
    
    async def initialize(self) -> None:
        """Initialize the hub and discover instances"""
        # Create shared session with connection pooling
        connector = aiohttp.TCPConnector(
            limit=100,  # Total connection pool limit
            limit_per_host=30,  # Per-host connection limit
            ttl_dns_cache=300  # DNS cache timeout
        )
        self.session = aiohttp.ClientSession(connector=connector)
        
        if self.auto_discover:
            await self.discover_instances()
    
    async def discover_instances(self) -> List[ResourceInstance[OllamaConfig]]:
        """Discover running Ollama instances"""
        discovered = []
        
        for port in self.discovery_ports:
            if await self._is_ollama_running("127.0.0.1", port):
                config = OllamaConfig(host="127.0.0.1", port=port)
                instance = await self.create_resource(config)
                if instance:
                    await self.register_instance_object(instance)
                    discovered.append(instance)
                    logger.info(f"Discovered Ollama instance at port {port}")
        
        return discovered
    
    async def _is_ollama_running(self, host: str, port: int) -> bool:
        """Check if Ollama is running at given host:port"""
        if not self.session:
            # Fallback if session not initialized
            async with aiohttp.ClientSession() as temp_session:
                try:
                    url = f"http://{host}:{port}/api/tags"
                    async with temp_session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                        return resp.status == 200
                except:
                    return False
        
        try:
            url = f"http://{host}:{port}/api/tags"
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                return resp.status == 200
        except:
            return False
    
    async def create_resource(self, config: OllamaConfig) -> Optional[ResourceInstance[OllamaConfig]]:
        """Create an Ollama resource instance"""
        instance_id = f"ollama-{config.host}-{config.port}"
        endpoint = f"http://{config.host}:{config.port}"
        
        # Check if it's actually running
        if not await self._is_ollama_running(config.host, config.port):
            logger.warning(f"Ollama not running at {endpoint}")
            return None
        
        # Get available models
        models = await self._get_available_models(endpoint)
        
        instance = ResourceInstance(
            id=instance_id,
            name=f"Ollama@{config.port}",
            type=ResourceType.OLLAMA,
            endpoint=endpoint,
            status=ResourceStatus.HEALTHY,
            config=config,
            capabilities=models,
            tags={"ollama", f"port:{config.port}"},
            metrics=ResourceMetrics()
        )
        
        return instance
    
    async def _get_available_models(self, endpoint: str) -> Set[str]:
        """Get list of available models from Ollama instance"""
        if not self.session:
            logger.warning("Session not initialized, using temporary session")
            async with aiohttp.ClientSession() as temp_session:
                try:
                    url = f"{endpoint}/api/tags"
                    async with temp_session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            models = {model['name'] for model in data.get('models', [])}
                            return models
                except Exception as e:
                    logger.error(f"Failed to get models from {endpoint}: {e}")
                return set()
        
        try:
            url = f"{endpoint}/api/tags"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = {model['name'] for model in data.get('models', [])}
                    return models
        except Exception as e:
            logger.error(f"Failed to get models from {endpoint}: {e}")
        
        return set()
    
    async def check_resource_health(self, instance: ResourceInstance[OllamaConfig]) -> ResourceMetrics:
        """Check health of an Ollama instance"""
        metrics = instance.metrics or ResourceMetrics()
        
        # Check if responsive
        if await self._is_ollama_running(instance.config.host, instance.config.port):
            instance.status = ResourceStatus.HEALTHY
            
            # Update available models
            models = await self._get_available_models(instance.endpoint)
            instance.capabilities = models
            
            # Update model cache
            self.model_cache[instance.id] = models
        else:
            instance.status = ResourceStatus.UNHEALTHY
            metrics.error_count += 1
        
        metrics.last_check = datetime.utcnow()
        return metrics
    
    async def start_instance(self, config: OllamaConfig) -> ResourceInstance[OllamaConfig]:
        """Start a new Ollama instance"""
        instance_id = f"ollama-{config.host}-{config.port}"
        endpoint = f"http://{config.host}:{config.port}"
        
        # Check if already running
        if await self._is_ollama_running(config.host, config.port):
            logger.info(f"Ollama already running at {endpoint}")
        else:
            # Start Ollama process
            env = config.environment.copy()
            env['OLLAMA_HOST'] = f"{config.host}:{config.port}"
            
            if config.gpu_layers is not None:
                env['OLLAMA_NUM_GPU'] = str(config.gpu_layers)
            
            if config.cpu_threads is not None:
                env['OLLAMA_NUM_THREAD'] = str(config.cpu_threads)
            
            try:
                process = subprocess.Popen(
                    ['ollama', 'serve'],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                config.process_id = process.pid
                
                # Wait for startup
                await asyncio.sleep(3)
                
                # Verify it started
                max_retries = 10
                for _ in range(max_retries):
                    if await self._is_ollama_running(config.host, config.port):
                        logger.info(f"Started Ollama at {endpoint} (PID: {process.pid})")
                        break
                    await asyncio.sleep(1)
                else:
                    logger.error(f"Failed to start Ollama at {endpoint}")
                    process.terminate()
                    raise RuntimeError(f"Ollama failed to start at {endpoint}")
                    
            except FileNotFoundError:
                logger.error("Ollama binary not found. Please install Ollama first.")
                raise
            except Exception as e:
                logger.error(f"Failed to start Ollama: {e}")
                raise
        
        # Create and register instance
        instance = await self.create_resource(config)
        if instance:
            await self.register_instance_object(instance)
            
            # Pull default models if specified
            if config.auto_pull_models and config.models:
                for model in config.models:
                    await self.ensure_model(instance.id, model)
        
        return instance
    
    async def stop_instance(self, instance_id: str) -> bool:
        """Stop an Ollama instance"""
        instance = await self.get_instance(instance_id)
        if not instance or not instance.config:
            return False
        
        if instance.config.process_id:
            try:
                process = psutil.Process(instance.config.process_id)
                process.terminate()
                
                # Wait for graceful shutdown
                try:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, process.wait, 10)
                except psutil.TimeoutExpired:
                    process.kill()
                
                logger.info(f"Stopped Ollama instance {instance_id} (PID: {instance.config.process_id})")
                
            except psutil.NoSuchProcess:
                logger.warning(f"Process {instance.config.process_id} not found")
            except Exception as e:
                logger.error(f"Failed to stop Ollama instance: {e}")
                return False
        
        await self.unregister_instance(instance_id)
        return True
    
    async def restart_instance(self, instance_id: str) -> bool:
        """Restart an Ollama instance"""
        instance = await self.get_instance(instance_id)
        if not instance or not instance.config:
            return False
        
        config = instance.config
        
        # Stop it first
        await self.stop_instance(instance_id)
        
        # Wait a bit
        await asyncio.sleep(2)
        
        # Start it again
        try:
            new_instance = await self.start_instance(config)
            return new_instance is not None
        except Exception as e:
            logger.error(f"Failed to restart instance {instance_id}: {e}")
            return False
    
    async def check_health(self, instance: ResourceInstance[OllamaConfig]) -> bool:
        """
        Check the health of an Ollama instance
        
        Args:
            instance: The resource instance to check
            
        Returns:
            True if healthy, False otherwise
        """
        if not instance.config:
            return False
            
        try:
            if not self.session:
                async with aiohttp.ClientSession() as session:
                    url = f"http://{instance.config.host}:{instance.config.port}/api/tags"
                    async with session.get(url, timeout=5) as response:
                        return response.status == 200
            else:
                url = f"http://{instance.config.host}:{instance.config.port}/api/tags"
                async with self.session.get(url, timeout=5) as response:
                    return response.status == 200
        except Exception as e:
            logger.debug(f"Health check failed for {instance.id}: {e}")
            return False
    
    async def collect_metrics(self, instance: ResourceInstance[OllamaConfig]) -> ResourceMetrics:
        """
        Collect metrics from an Ollama instance
        
        Args:
            instance: The resource instance to collect metrics from
            
        Returns:
            ResourceMetrics with current metrics
        """
        from gleitzeit.hub.base import ResourceMetrics
        
        metrics = ResourceMetrics(
            cpu_percent=0.0,
            memory_percent=0.0,
            memory_mb=0.0,
            request_count=0,
            error_count=0,
            avg_response_time_ms=0.0
        )
        
        # If we have tracked metrics, use them
        if instance.id in self.instances:
            stored_instance = self.instances[instance.id]
            if stored_instance.metrics:
                metrics = stored_instance.metrics
        
        # Try to get actual metrics from Ollama (if it provides them)
        if instance.config:
            try:
                if not self.session:
                    async with aiohttp.ClientSession() as session:
                        url = f"http://{instance.config.host}:{instance.config.port}/api/tags"
                        start_time = asyncio.get_event_loop().time()
                        async with session.get(url, timeout=5) as response:
                            latency = asyncio.get_event_loop().time() - start_time
                            if response.status == 200:
                                metrics.average_latency = latency
                                metrics.request_count += 1
                            else:
                                metrics.error_count += 1
                else:
                    url = f"http://{instance.config.host}:{instance.config.port}/api/tags"
                    start_time = asyncio.get_event_loop().time()
                    async with self.session.get(url, timeout=5) as response:
                        latency = asyncio.get_event_loop().time() - start_time
                        if response.status == 200:
                            metrics.average_latency = latency
                            metrics.request_count += 1
                        else:
                            metrics.error_count += 1
            except Exception:
                metrics.error_count += 1
        
        return metrics
    
    async def ensure_model(self, instance_id: str, model_name: str) -> bool:
        """Ensure a model is available on an instance"""
        instance = await self.get_instance(instance_id)
        if not instance:
            return False
        
        # Check if model already loaded
        if model_name in self.model_cache.get(instance_id, set()):
            return True
        
        try:
            # Pull the model
            logger.info(f"Pulling model {model_name} on {instance_id}")
            
            if not self.session:
                raise RuntimeError("Session not initialized")
            
            url = f"{instance.endpoint}/api/pull"
            data = {"name": model_name}
            
            async with self.session.post(url, json=data) as resp:
                    if resp.status == 200:
                        # Stream the response to track progress
                        async for line in resp.content:
                            pass  # Could parse progress here
                        
                        logger.info(f"Successfully pulled {model_name} on {instance_id}")
                        
                        # Update model cache
                        if instance_id not in self.model_cache:
                            self.model_cache[instance_id] = set()
                        self.model_cache[instance_id].add(model_name)
                        
                        return True
                    else:
                        logger.error(f"Failed to pull {model_name}: HTTP {resp.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Failed to pull model {model_name}: {e}")
            return False
    
    async def get_instance_for_model(
        self,
        model_name: str,
        strategy: str = "least_loaded"
    ) -> Optional[ResourceInstance[OllamaConfig]]:
        """Get an instance that has a specific model loaded"""
        # First try instances that already have the model
        instances_with_model = []
        for instance_id, models in self.model_cache.items():
            if model_name in models and instance_id in self.instances:
                instance = self.instances[instance_id]
                if instance.is_available():
                    instances_with_model.append(instance)
        
        if instances_with_model:
            if strategy == "least_loaded":
                return min(instances_with_model, key=lambda i: i.metrics.active_connections)
            else:
                return instances_with_model[0]
        
        # Try to find an instance that can load the model
        available = await self.list_instances(status=ResourceStatus.HEALTHY)
        if available:
            # Pick one and ensure the model
            instance = available[0]
            if await self.ensure_model(instance.id, model_name):
                return instance
        
        return None
    
    async def execute_on_instance(
        self,
        instance_id: str,
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a request on a specific instance"""
        instance = await self.get_instance(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")
        
        if not instance.is_available():
            raise RuntimeError(f"Instance {instance_id} is not available")
        
        # Track metrics
        start_time = datetime.utcnow()
        
        try:
            if not self.session:
                raise RuntimeError("Session not initialized")
            
            # Map method to Ollama API endpoint
            endpoint_map = {
                "llm/complete": "/api/generate",
                "llm/chat": "/api/chat",
                "llm/embeddings": "/api/embeddings"
            }
            
            endpoint = endpoint_map.get(method, "/api/generate")
            url = f"{instance.endpoint}{endpoint}"
            
            # Update metrics
            instance.metrics.active_connections += 1
            instance.metrics.total_requests += 1
            
            async with self.session.post(url, json=params) as resp:
                    result = await resp.json()
                    
                    # Update metrics
                    elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
                    instance.metrics.avg_response_time_ms = (
                        (instance.metrics.avg_response_time_ms * (instance.metrics.total_requests - 1) + elapsed) /
                        instance.metrics.total_requests
                    )
                    
                    if resp.status != 200:
                        instance.metrics.error_count += 1
                        raise RuntimeError(f"Ollama API error: {result}")
                    
                    return result
                    
        except Exception as e:
            instance.metrics.error_count += 1
            logger.error(f"Failed to execute on {instance_id}: {e}")
            raise
        finally:
            instance.metrics.active_connections -= 1
    
    async def cleanup(self) -> None:
        """Clean up resources"""
        # Stop all managed instances
        for instance_id, instance in list(self.instances.items()):
            if instance.config and instance.config.process_id:
                await self.stop_instance(instance_id)
        
        # Close the shared session
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
        
        await super().cleanup()