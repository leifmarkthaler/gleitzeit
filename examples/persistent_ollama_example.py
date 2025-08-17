"""
Example: Using PersistentHubProvider with OllamaProvider

This example demonstrates how to use Redis persistence with the Ollama provider
for production deployments with state persistence and distributed coordination.
"""

import asyncio
import logging
from datetime import datetime

from gleitzeit.providers.persistent_hub_provider import PersistentHubProvider
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.hub.base import ResourceInstance, ResourceStatus, ResourceType
from gleitzeit.hub.configs import OllamaConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PersistentOllamaProvider(PersistentHubProvider):
    """
    Production-ready Ollama provider with Redis persistence
    
    Features:
    - State persistence across restarts
    - Distributed resource locking
    - Metrics history storage
    - Shared resource pools across instances
    """
    
    def __init__(self, persistence_adapter=None, **kwargs):
        super().__init__(
            provider_id="ollama-production",
            protocol_id="llm/v1",
            name="Persistent Ollama Provider",
            description="Ollama with Redis state management",
            resource_config_class=OllamaConfig,
            persistence_adapter=persistence_adapter,
            enable_persistence=True,
            persistence_interval=60,  # Save state every minute
            enable_distributed_locking=True,
            **kwargs
        )
        self.default_model = "llama3.2"
    
    def get_supported_methods(self) -> list[str]:
        """Return supported LLM methods"""
        return [
            "llm/complete",
            "llm/chat", 
            "llm/vision",
            "llm/embeddings",
            "llm/list_models"
        ]
    
    async def create_resource(self, config: OllamaConfig) -> ResourceInstance[OllamaConfig]:
        """Create a new Ollama instance"""
        logger.info(f"Creating Ollama resource at {config.host}:{config.port}")
        
        instance = ResourceInstance(
            id=f"ollama-{config.host}-{config.port}",
            name=f"Ollama@{config.host}:{config.port}",
            type=ResourceType.OLLAMA,
            endpoint=f"http://{config.host}:{config.port}",
            status=ResourceStatus.STARTING,
            capabilities=set(self.get_supported_methods()),
            tags={"production", "ollama"},
            config=config
        )
        
        # In production, you would actually start/connect to Ollama here
        # For demo, we'll just mark it as healthy
        instance.status = ResourceStatus.HEALTHY
        
        return instance
    
    async def destroy_resource(self, instance: ResourceInstance[OllamaConfig]):
        """Stop and cleanup Ollama instance"""
        logger.info(f"Destroying resource: {instance.id}")
        instance.status = ResourceStatus.STOPPED
        # In production, stop the Ollama process here
    
    async def execute_on_resource(
        self,
        instance: ResourceInstance[OllamaConfig],
        method: str,
        params: dict
    ) -> dict:
        """Execute LLM method on Ollama instance"""
        logger.info(f"Executing {method} on {instance.id}")
        
        # Update metrics
        instance.metrics.request_count += 1
        instance.metrics.active_connections += 1
        
        try:
            # In production, make actual HTTP request to Ollama
            # For demo, return mock response
            if method == "llm/complete":
                response = {
                    "response": f"Completion from {instance.id}",
                    "model": params.get("model", self.default_model),
                    "created_at": datetime.utcnow().isoformat()
                }
            elif method == "llm/chat":
                response = {
                    "response": f"Chat response from {instance.id}",
                    "model": params.get("model", self.default_model),
                    "created_at": datetime.utcnow().isoformat()
                }
            else:
                response = {"error": f"Method {method} not implemented"}
            
            # Update metrics
            instance.metrics.avg_response_time_ms = 25.5
            
            return response
            
        finally:
            instance.metrics.active_connections -= 1
    
    async def check_resource_health(self, instance: ResourceInstance[OllamaConfig]) -> bool:
        """Check Ollama instance health"""
        # In production, make health check request to Ollama
        # For demo, return based on status
        return instance.status == ResourceStatus.HEALTHY
    
    async def discover_resources(self) -> list[OllamaConfig]:
        """Auto-discover Ollama instances"""
        # In production, scan network for Ollama instances
        # For demo, return empty list
        return []


async def main():
    """Demonstrate persistent Ollama provider"""
    
    print("\n" + "="*60)
    print("Persistent Ollama Provider Example")
    print("="*60)
    
    # Create persistence adapter using factory
    # It will automatically select the best available backend
    print("\n🔍 Creating persistence adapter...")
    adapter = await PersistenceFactory.create()
    
    backend_type = adapter.__class__.__name__
    if "Redis" in backend_type:
        print("📦 Using Redis persistence backend")
    elif "SQL" in backend_type:
        print("💿 Using SQL persistence backend")
    else:
        print("💾 Using in-memory persistence (for testing)")
    
    # Create provider with persistence
    provider = PersistentOllamaProvider(
        persistence_adapter=adapter,
        instance_id="demo-instance-1",  # Unique ID for this provider instance
        max_instances=5
    )
    
    try:
        # Initialize provider
        await provider.initialize()
        print(f"\n✅ Provider initialized: {provider.provider_id}")
        print(f"   Instance ID: {provider.instance_id}")
        print(f"   Persistence: {'Redis' if use_redis else 'In-Memory'}")
        print(f"   Distributed locking: {provider.enable_distributed_locking}")
        
        # Create some Ollama instances
        print("\n📋 Creating Ollama instances...")
        configs = [
            OllamaConfig(host="localhost", port=11434),
            OllamaConfig(host="localhost", port=11435),
            OllamaConfig(host="localhost", port=11436),
        ]
        
        for config in configs:
            instance = await provider.create_resource(config)
            await provider.register_instance(instance)
            print(f"   ✓ Registered: {instance.id}")
        
        # Get provider status
        status = await provider.get_distributed_status()
        print(f"\n📊 Provider Status:")
        print(f"   Total instances: {len(provider.instances)}")
        print(f"   Healthy: {sum(1 for i in provider.instances.values() if i.status == ResourceStatus.HEALTHY)}")
        print(f"   Persistence enabled: {status['persistence']['enabled']}")
        print(f"   Locked resources: {status['persistence']['locked_resources']}")
        
        # Simulate some work
        print("\n🔄 Simulating workload...")
        for i in range(5):
            # Get an available instance (with locking)
            instance = await provider.get_instance()
            if instance:
                print(f"   Request {i+1}: Using {instance.id}")
                
                # Execute a task
                result = await provider.execute_on_resource(
                    instance,
                    "llm/complete",
                    {"prompt": f"Test prompt {i+1}", "model": "llama3.2"}
                )
                
                # Release the instance
                await provider.release_instance(instance.id)
                
                await asyncio.sleep(0.5)
        
        # Show metrics
        print("\n📈 Metrics Summary:")
        for instance_id, instance in provider.instances.items():
            metrics = instance.metrics
            print(f"   {instance_id}:")
            print(f"     - Requests: {metrics.request_count}")
            print(f"     - Avg response time: {metrics.avg_response_time_ms:.1f}ms")
            print(f"     - Active connections: {metrics.active_connections}")
        
        # Get metrics history (if persistence is enabled)
        if provider.enable_persistence:
            print("\n📜 Metrics History:")
            all_history = await provider.get_all_metrics_history(hours=1)
            for instance_id, history in all_history.items():
                print(f"   {instance_id}: {len(history)} snapshots")
        
        # Simulate restart scenario
        print("\n🔄 Simulating provider restart...")
        await provider.shutdown()
        print("   Provider shut down")
        
        # Create new provider instance
        provider2 = PersistentOllamaProvider(
            persistence_adapter=adapter,
            instance_id="demo-instance-2",  # Different instance ID
            max_instances=5
        )
        
        await provider2.initialize()
        print(f"   New provider initialized: {provider2.instance_id}")
        print(f"   Recovered instances: {len(provider2.instances)}")
        
        if provider2.instances:
            print("\n   Recovered instances:")
            for instance_id in provider2.instances:
                print(f"     - {instance_id}")
        
        await provider2.shutdown()
        
    except Exception as e:
        logger.error(f"Error: {e}")
        raise
    
    finally:
        await adapter.shutdown()
        print("\n✅ Example completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())