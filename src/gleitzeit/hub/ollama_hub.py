"""
Ollama Hub - Manages multiple Ollama instances
"""
import asyncio
import aiohttp
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
from datetime import datetime
import psutil
import subprocess

from .base import ResourceHub, ResourceInstance, ResourceStatus, ResourceMetrics, ResourceType

logger = logging.getLogger(__name__)


@dataclass
class OllamaConfig:
    """Configuration for an Ollama instance"""
    host: str = "127.0.0.1"
    port: int = 11434
    models: List[str] = field(default_factory=list)
    max_concurrent: int = 4
    gpu_layers: Optional[int] = None
    cpu_threads: Optional[int] = None
    context_size: Optional[int] = None
    environment: Dict[str, str] = field(default_factory=dict)
    auto_pull_models: bool = True
    process_id: Optional[int] = None  # For managed instances


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
        health_check_interval: int = 30,
        max_health_failures: int = 3,
        enable_auto_recovery: bool = True,
        enable_metrics: bool = True,
        auto_discover: bool = True
    ):
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.OLLAMA,
            health_check_interval=health_check_interval,
            max_health_failures=max_health_failures,
            enable_auto_recovery=enable_auto_recovery,
            enable_metrics=enable_metrics
        )
        
        self.auto_discover = auto_discover
        self.model_cache: Dict[str, Set[str]] = {}  # instance_id -> set of loaded models
        self.discovery_task: Optional[asyncio.Task] = None
    
    async def check_health(self, instance: ResourceInstance[OllamaConfig]) -> bool:
        """Check health of an Ollama instance"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{instance.endpoint}/api/tags"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Update model cache
                        models = {model['name'] for model in data.get('models', [])}
                        self.model_cache[instance.id] = models
                        instance.capabilities = models
                        return True
                    return False
        except Exception as e:
            logger.debug(f"Health check failed for {instance.id}: {e}")
            return False
    
    async def collect_metrics(self, instance: ResourceInstance[OllamaConfig]) -> ResourceMetrics:
        """Collect metrics from an Ollama instance"""
        metrics = ResourceMetrics()
        
        try:
            # Get Ollama process metrics if we have the PID
            if instance.config and instance.config.process_id:
                try:
                    process = psutil.Process(instance.config.process_id)
                    metrics.cpu_percent = process.cpu_percent(interval=0.1)
                    memory_info = process.memory_info()
                    metrics.memory_mb = memory_info.rss / 1024 / 1024
                    metrics.memory_percent = process.memory_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Try to get Ollama-specific metrics
            async with aiohttp.ClientSession() as session:
                # Check for running models
                url = f"{instance.endpoint}/api/ps"
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            running_models = data.get('models', [])
                            metrics.active_connections = len(running_models)
                            metrics.custom_metrics['running_models'] = [
                                {
                                    'name': model.get('name'),
                                    'size': model.get('size'),
                                    'digest': model.get('digest')
                                }
                                for model in running_models
                            ]
                except:
                    pass
            
            # Update from instance's tracked metrics
            if hasattr(instance, '_request_metrics'):
                metrics.request_count = instance._request_metrics.get('total', 0)
                metrics.error_count = instance._request_metrics.get('errors', 0)
                
                response_times = instance._request_metrics.get('response_times', [])
                if response_times:
                    metrics.avg_response_time_ms = sum(response_times) / len(response_times)
                    sorted_times = sorted(response_times)
                    metrics.p95_response_time_ms = sorted_times[int(len(sorted_times) * 0.95)]
                    metrics.p99_response_time_ms = sorted_times[int(len(sorted_times) * 0.99)]
            
        except Exception as e:
            logger.error(f"Failed to collect metrics for {instance.id}: {e}")
        
        metrics.last_updated = datetime.utcnow()
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
                
                if not await self._is_ollama_running(config.host, config.port):
                    raise RuntimeError(f"Failed to start Ollama at {endpoint}")
                
                logger.info(f"Started Ollama instance at {endpoint} (PID: {process.pid})")
                
            except Exception as e:
                logger.error(f"Failed to start Ollama instance: {e}")
                raise
        
        # Register the instance
        instance = await self.register_instance(
            instance_id=instance_id,
            name=f"Ollama@{config.port}",
            endpoint=endpoint,
            metadata={
                'host': config.host,
                'port': config.port,
                'max_concurrent': config.max_concurrent
            },
            tags={'local'} if config.host in ['127.0.0.1', 'localhost'] else {'remote'},
            capabilities=set(config.models),
            config=config
        )
        
        # Initialize request tracking
        instance._request_metrics = {
            'total': 0,
            'errors': 0,
            'response_times': []
        }
        
        # Pull models if needed
        if config.auto_pull_models:
            for model in config.models:
                await self.ensure_model(instance_id, model)
        
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
                    process.wait(timeout=10)
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
        
        # Stop the instance
        if config.process_id:
            await self.stop_instance(instance_id)
            await asyncio.sleep(2)
        
        # Start it again
        try:
            new_instance = await self.start_instance(config)
            return new_instance is not None
        except Exception as e:
            logger.error(f"Failed to restart instance {instance_id}: {e}")
            return False
    
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
            
            async with aiohttp.ClientSession() as session:
                url = f"{instance.endpoint}/api/pull"
                data = {"name": model_name}
                
                async with session.post(url, json=data) as resp:
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
            async with aiohttp.ClientSession() as session:
                # Map method to Ollama API endpoint
                endpoint_map = {
                    'generate': '/api/generate',
                    'chat': '/api/chat',
                    'embeddings': '/api/embeddings'
                }
                
                endpoint = endpoint_map.get(method, f'/api/{method}')
                url = f"{instance.endpoint}{endpoint}"
                
                async with session.post(url, json=params) as resp:
                    response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
                    
                    # Update metrics
                    if hasattr(instance, '_request_metrics'):
                        instance._request_metrics['total'] += 1
                        instance._request_metrics['response_times'].append(response_time)
                        
                        # Keep only last 100 response times
                        if len(instance._request_metrics['response_times']) > 100:
                            instance._request_metrics['response_times'] = \
                                instance._request_metrics['response_times'][-100:]
                    
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        if hasattr(instance, '_request_metrics'):
                            instance._request_metrics['errors'] += 1
                        raise RuntimeError(f"Request failed: HTTP {resp.status}")
                        
        except Exception as e:
            if hasattr(instance, '_request_metrics'):
                instance._request_metrics['errors'] += 1
            raise
    
    async def _is_ollama_running(self, host: str, port: int) -> bool:
        """Check if Ollama is running at given host:port"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"http://{host}:{port}/api/tags"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    return resp.status == 200
        except:
            return False
    
    async def discover_instances(self, port_range: range = range(11434, 11440)) -> List[str]:
        """Discover running Ollama instances on local machine"""
        discovered = []
        
        for port in port_range:
            if await self._is_ollama_running("127.0.0.1", port):
                discovered.append(f"127.0.0.1:{port}")
                logger.info(f"Discovered Ollama instance at 127.0.0.1:{port}")
        
        return discovered
    
    async def auto_discover_and_register(self):
        """Automatically discover and register Ollama instances"""
        discovered = await self.discover_instances()
        
        for endpoint_str in discovered:
            host, port = endpoint_str.split(':')
            port = int(port)
            instance_id = f"ollama-{host}-{port}"
            
            if instance_id not in self.instances:
                config = OllamaConfig(host=host, port=port)
                endpoint = f"http://{host}:{port}"
                
                await self.register_instance(
                    instance_id=instance_id,
                    name=f"Ollama@{port}",
                    endpoint=endpoint,
                    metadata={'host': host, 'port': port, 'discovered': True},
                    tags={'local', 'discovered'},
                    config=config
                )
    
    async def start(self):
        """Start the Ollama hub"""
        await super().start()
        
        if self.auto_discover:
            # Do initial discovery
            await self.auto_discover_and_register()
            
            # Start periodic discovery
            async def discovery_loop():
                while self.running:
                    await asyncio.sleep(60)  # Check every minute
                    await self.auto_discover_and_register()
            
            self.discovery_task = asyncio.create_task(discovery_loop())
    
    async def stop(self):
        """Stop the Ollama hub"""
        if self.discovery_task:
            self.discovery_task.cancel()
            try:
                await self.discovery_task
            except asyncio.CancelledError:
                pass
        
        await super().stop()
    
    async def get_model_distribution(self) -> Dict[str, List[str]]:
        """Get which models are loaded on which instances"""
        distribution = {}
        
        for instance_id, models in self.model_cache.items():
            for model in models:
                if model not in distribution:
                    distribution[model] = []
                distribution[model].append(instance_id)
        
        return distribution