# Hub Development

Hubs in Gleitzeit manage collections of resources (like Ollama instances or Docker containers) and provide load balancing, health monitoring, and resource allocation. This guide covers developing custom hubs.

## Hub Architecture

### Core Concepts

- **Hub**: Manages a pool of similar resources
- **Resource**: Individual service instance (e.g., Ollama server, Docker container)
- **ResourceManager**: Orchestrates multiple hubs
- **Health Monitor**: Tracks resource availability and performance
- **Load Balancer**: Distributes requests across healthy resources

### Hub Lifecycle

```
Initialize → Register Resources → Health Check → Load Balance → Cleanup
```

## Base Hub Implementation

### Abstract Base Hub

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from gleitzeit.hub.base import BaseHub, Resource, ResourceConfig

class CustomHub(BaseHub):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.resources: List[Resource] = []
        self.resource_pool = {}
    
    async def initialize(self) -> None:
        """Initialize hub and register resources"""
        await super().initialize()
        await self._discover_resources()
        await self._register_resources()
    
    async def cleanup(self) -> None:
        """Clean up hub resources"""
        for resource in self.resources:
            await self._cleanup_resource(resource)
        await super().cleanup()
    
    @abstractmethod
    async def _discover_resources(self) -> List[ResourceConfig]:
        """Discover available resources"""
        pass
    
    @abstractmethod
    async def get_resource(self, criteria: Optional[Dict[str, Any]] = None) -> Resource:
        """Get available resource matching criteria"""
        pass
    
    @abstractmethod
    async def release_resource(self, resource: Resource) -> None:
        """Release resource back to pool"""
        pass
```

## Example: Database Hub

Let's create a hub that manages database connections:

```python
from typing import List, Dict, Any, Optional
import asyncio
import aioredis
import asyncpg
from gleitzeit.hub.base import BaseHub, Resource, ResourceConfig
from gleitzeit.common.health_monitor import HealthMonitor
from gleitzeit.common.load_balancer import LoadBalancer

class DatabaseResource(Resource):
    def __init__(self, config: ResourceConfig):
        super().__init__(config)
        self.connection = None
        self.db_type = config.metadata.get("type", "postgresql")
        self.connection_string = config.endpoint
    
    async def connect(self) -> None:
        """Establish database connection"""
        if self.db_type == "postgresql":
            self.connection = await asyncpg.connect(self.connection_string)
        elif self.db_type == "redis":
            self.connection = await aioredis.from_url(self.connection_string)
        else:
            raise ValueError(f"Unsupported database type: {self.db_type}")
        
        self.status = "healthy"
    
    async def disconnect(self) -> None:
        """Close database connection"""
        if self.connection:
            await self.connection.close()
            self.connection = None
        self.status = "stopped"
    
    async def health_check(self) -> bool:
        """Check if database connection is healthy"""
        try:
            if self.db_type == "postgresql":
                await self.connection.fetchval("SELECT 1")
            elif self.db_type == "redis":
                await self.connection.ping()
            return True
        except Exception:
            return False

class DatabaseHub(BaseHub):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.max_connections = config.get("max_connections", 10)
        self.connection_pools = {}
    
    async def _discover_resources(self) -> List[ResourceConfig]:
        """Discover database resources from configuration"""
        databases = self.config.get("databases", [])
        resources = []
        
        for db_config in databases:
            resource_config = ResourceConfig(
                id=db_config["name"],
                endpoint=db_config["connection_string"],
                metadata={
                    "type": db_config["type"],
                    "max_connections": db_config.get("max_connections", 5),
                    "timeout": db_config.get("timeout", 30)
                }
            )
            resources.append(resource_config)
        
        return resources
    
    async def _register_resources(self) -> None:
        """Register and initialize database resources"""
        resource_configs = await self._discover_resources()
        
        for config in resource_configs:
            resource = DatabaseResource(config)
            await resource.connect()
            
            # Add to health monitoring
            self.health_monitor.add_resource(resource)
            
            # Add to load balancer
            self.load_balancer.add_resource(resource)
            
            self.resources.append(resource)
    
    async def get_resource(self, criteria: Optional[Dict[str, Any]] = None) -> DatabaseResource:
        """Get available database connection"""
        db_type = criteria.get("type") if criteria else None
        
        # Filter resources by type if specified
        available_resources = self.resources
        if db_type:
            available_resources = [
                r for r in self.resources 
                if r.db_type == db_type and r.status == "healthy"
            ]
        
        if not available_resources:
            raise RuntimeError(f"No healthy {db_type or 'database'} resources available")
        
        # Use load balancer to select resource
        resource = self.load_balancer.select_resource(available_resources)
        
        # Mark resource as in use
        resource.active_connections += 1
        
        return resource
    
    async def release_resource(self, resource: DatabaseResource) -> None:
        """Release database resource"""
        resource.active_connections -= 1
        
        # Optional: Close connection if idle for too long
        if resource.active_connections == 0:
            await self._schedule_idle_cleanup(resource)
    
    async def execute_query(self, query: str, params: tuple = None, db_type: str = "postgresql") -> Any:
        """Execute query using available database resource"""
        resource = await self.get_resource({"type": db_type})
        
        try:
            if db_type == "postgresql":
                if params:
                    result = await resource.connection.fetch(query, *params)
                else:
                    result = await resource.connection.fetch(query)
            elif db_type == "redis":
                # Handle Redis commands
                result = await resource.connection.execute_command(query, *params or [])
            
            return result
            
        finally:
            await self.release_resource(resource)
```

## Hub Configuration

### Configuration Schema

```yaml
# Hub configuration example
hubs:
  database:
    type: "DatabaseHub"
    max_connections: 20
    health_check_interval: 30
    load_balancer:
      strategy: "round_robin"  # round_robin, least_connections, weighted
    databases:
      - name: "primary_db"
        type: "postgresql" 
        connection_string: "postgresql://user:pass@localhost:5432/main"
        max_connections: 10
        timeout: 30
      - name: "cache_db"
        type: "redis"
        connection_string: "redis://localhost:6379/0"
        max_connections: 5
        timeout: 10
    
  ollama:
    type: "OllamaHub"
    instances:
      - endpoint: "http://localhost:11434"
        models: ["llama3.2", "mistral"]
      - endpoint: "http://localhost:11435" 
        models: ["llava", "codellama"]
```

### Dynamic Configuration

```python
class DatabaseHub(BaseHub):
    async def add_database(self, db_config: Dict[str, Any]) -> None:
        """Dynamically add database to hub"""
        resource_config = ResourceConfig(
            id=db_config["name"],
            endpoint=db_config["connection_string"],
            metadata=db_config
        )
        
        resource = DatabaseResource(resource_config)
        await resource.connect()
        
        # Add to monitoring and load balancing
        self.health_monitor.add_resource(resource)
        self.load_balancer.add_resource(resource)
        self.resources.append(resource)
    
    async def remove_database(self, db_name: str) -> None:
        """Dynamically remove database from hub"""
        resource = next((r for r in self.resources if r.id == db_name), None)
        if resource:
            # Remove from monitoring and load balancing
            self.health_monitor.remove_resource(resource)
            self.load_balancer.remove_resource(resource)
            
            # Wait for active connections to finish
            while resource.active_connections > 0:
                await asyncio.sleep(1)
            
            await resource.disconnect()
            self.resources.remove(resource)
```

## Health Monitoring

### Custom Health Checks

```python
class DatabaseHub(BaseHub):
    async def _custom_health_check(self, resource: DatabaseResource) -> Dict[str, Any]:
        """Perform detailed health check"""
        health_data = {
            "status": "unknown",
            "latency": None,
            "active_connections": resource.active_connections,
            "error": None
        }
        
        try:
            start_time = asyncio.get_event_loop().time()
            
            # Perform health check query
            if resource.db_type == "postgresql":
                await resource.connection.fetchval("SELECT 1")
            elif resource.db_type == "redis":
                await resource.connection.ping()
            
            end_time = asyncio.get_event_loop().time()
            
            health_data.update({
                "status": "healthy",
                "latency": (end_time - start_time) * 1000  # ms
            })
            
        except Exception as e:
            health_data.update({
                "status": "unhealthy", 
                "error": str(e)
            })
        
        return health_data
    
    async def _handle_unhealthy_resource(self, resource: DatabaseResource) -> None:
        """Handle unhealthy resource"""
        # Remove from load balancer
        self.load_balancer.remove_resource(resource)
        
        # Try to reconnect
        try:
            await resource.disconnect()
            await resource.connect()
            
            # Re-add to load balancer if successful
            self.load_balancer.add_resource(resource)
            
        except Exception as e:
            logger.error(f"Failed to reconnect to {resource.id}: {e}")
            # Schedule retry
            asyncio.create_task(self._retry_connection(resource))
```

## Load Balancing Strategies

### Custom Load Balancer

```python
from gleitzeit.common.load_balancer import LoadBalancerStrategy

class DatabaseLoadBalancer(LoadBalancerStrategy):
    def select_resource(self, resources: List[DatabaseResource]) -> DatabaseResource:
        """Select resource based on connection count and latency"""
        if not resources:
            raise RuntimeError("No resources available")
        
        # Filter healthy resources
        healthy_resources = [r for r in resources if r.status == "healthy"]
        if not healthy_resources:
            raise RuntimeError("No healthy resources available")
        
        # Score resources based on multiple factors
        scored_resources = []
        for resource in healthy_resources:
            # Lower score is better
            score = (
                resource.active_connections * 10 +  # Connection load
                resource.health_data.get("latency", 0) +  # Response time
                (100 if resource.db_type == "redis" else 0)  # Prefer PostgreSQL
            )
            scored_resources.append((score, resource))
        
        # Return resource with lowest score
        scored_resources.sort(key=lambda x: x[0])
        return scored_resources[0][1]

# Use custom load balancer
class DatabaseHub(BaseHub):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.load_balancer = DatabaseLoadBalancer()
```

## Resource Metrics

### Metrics Collection

```python
from gleitzeit.common.metrics import MetricsCollector

class DatabaseHub(BaseHub):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.metrics = MetricsCollector("database_hub")
    
    async def execute_query(self, query: str, **kwargs) -> Any:
        """Execute query with metrics collection"""
        start_time = asyncio.get_event_loop().time()
        resource = None
        
        try:
            resource = await self.get_resource(kwargs)
            
            # Record resource selection
            self.metrics.counter("queries_total").inc({
                "database": resource.id,
                "type": resource.db_type
            })
            
            # Execute query
            result = await self._execute_on_resource(resource, query, kwargs)
            
            # Record success
            self.metrics.counter("queries_success").inc({
                "database": resource.id
            })
            
            return result
            
        except Exception as e:
            # Record failure
            self.metrics.counter("queries_failed").inc({
                "database": resource.id if resource else "unknown",
                "error": type(e).__name__
            })
            raise
            
        finally:
            # Record timing
            duration = asyncio.get_event_loop().time() - start_time
            self.metrics.histogram("query_duration").observe(duration, {
                "database": resource.id if resource else "unknown"
            })
            
            if resource:
                await self.release_resource(resource)
```

## Hub Integration

### ResourceManager Integration

```python
from gleitzeit.hub.resource_manager import ResourceManager

# Register custom hub
resource_manager = ResourceManager()
resource_manager.register_hub_type("database", DatabaseHub)

# Initialize from configuration
await resource_manager.initialize_from_config({
    "hubs": {
        "database": {
            "type": "DatabaseHub",
            "databases": [...]
        }
    }
})

# Use hub through resource manager
async def execute_database_query(query: str) -> Any:
    hub = resource_manager.get_hub("database")
    return await hub.execute_query(query)
```

### Provider Integration

```python
# Use hub in provider
class DatabaseProvider(BaseProvider):
    def __init__(self, resource_manager: ResourceManager):
        self.resource_manager = resource_manager
        self.db_hub = resource_manager.get_hub("database")
    
    async def execute(self, method: str, parameters: dict) -> dict:
        if method == "database/query":
            result = await self.db_hub.execute_query(
                parameters["sql"],
                db_type=parameters.get("type", "postgresql")
            )
            
            return {
                "response": result,
                "metadata": {
                    "rows": len(result),
                    "database_type": parameters.get("type", "postgresql")
                }
            }
```

## Testing Hubs

### Unit Tests

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_database_hub_initialization():
    config = {
        "databases": [
            {
                "name": "test_db",
                "type": "postgresql",
                "connection_string": "postgresql://test"
            }
        ]
    }
    
    hub = DatabaseHub(config)
    
    # Mock database connection
    hub._create_connection = AsyncMock()
    
    await hub.initialize()
    
    assert len(hub.resources) == 1
    assert hub.resources[0].id == "test_db"

@pytest.mark.asyncio
async def test_resource_selection():
    hub = DatabaseHub({})
    
    # Add mock resources
    resource1 = MagicMock()
    resource1.status = "healthy"
    resource1.active_connections = 2
    
    resource2 = MagicMock()
    resource2.status = "healthy" 
    resource2.active_connections = 1
    
    hub.resources = [resource1, resource2]
    hub.load_balancer.select_resource = MagicMock(return_value=resource2)
    
    selected = await hub.get_resource()
    
    assert selected == resource2
    assert resource2.active_connections == 2  # Incremented
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_hub_with_real_database():
    # This would require a test database
    config = {
        "databases": [
            {
                "name": "test_postgres",
                "type": "postgresql",
                "connection_string": "postgresql://test:test@localhost:5432/test"
            }
        ]
    }
    
    hub = DatabaseHub(config)
    
    try:
        await hub.initialize()
        
        # Test query execution
        result = await hub.execute_query("SELECT 1 as test")
        assert result[0]["test"] == 1
        
    finally:
        await hub.cleanup()
```

## Best Practices

### Resource Management

1. **Connection pooling**: Reuse connections efficiently
2. **Graceful degradation**: Handle resource failures
3. **Resource limits**: Prevent resource exhaustion
4. **Cleanup**: Properly clean up resources on shutdown

### Error Handling

1. **Circuit breakers**: Prevent cascading failures
2. **Retry logic**: Handle transient failures
3. **Fallback strategies**: Provide alternatives when resources fail
4. **Monitoring**: Track errors and performance

### Performance

1. **Asynchronous operations**: Use async/await throughout
2. **Connection reuse**: Minimize connection overhead
3. **Load balancing**: Distribute load effectively
4. **Caching**: Cache expensive operations

### Configuration

1. **Validation**: Validate configuration on startup
2. **Hot reloading**: Support configuration changes
3. **Environment variables**: Use env vars for deployment-specific config
4. **Defaults**: Provide sensible defaults

Hubs provide a powerful abstraction for managing pools of resources while maintaining high availability and performance in distributed environments.