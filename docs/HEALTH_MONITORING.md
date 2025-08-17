# Health Monitoring

Gleitzeit includes basic health monitoring capabilities to track component availability and detect failures.

## Overview

The health monitoring system provides:
- **Basic health checks** for providers and hubs
- **Circuit breaker pattern** to prevent cascading failures
- **Simple recovery mechanisms** for transient issues

## Components

### HealthMonitor

The `HealthMonitor` class tracks the health of system components:

```python
from gleitzeit.common.health_monitor import HealthMonitor

# Initialize health monitor
health_monitor = HealthMonitor()

# Add resources to monitor
health_monitor.add_resource(ollama_provider)
health_monitor.add_resource(docker_hub)

# Perform health check
health_status = await health_monitor.check_health()
```

### Circuit Breaker

The `CircuitBreaker` prevents repeated calls to failing components:

```python
from gleitzeit.common.circuit_breaker import CircuitBreaker, CircuitState

circuit_breaker = CircuitBreaker(
    failure_threshold=5,      # Failures before opening
    recovery_timeout=60,       # Seconds before retry
    half_open_requests=3,      # Test requests in half-open state
    success_threshold=2        # Successes to close circuit
)

# Circuit states
# - CLOSED: Normal operation
# - OPEN: Failing, reject requests  
# - HALF_OPEN: Testing recovery
```

## Provider Health Checks

### Ollama Provider

The Ollama provider includes basic connectivity checks:

```python
# Automatic health checks during operation
async def check_ollama_health(provider):
    try:
        # Check endpoint connectivity
        response = await provider.client.get("/api/tags")
        if response.status_code == 200:
            return {"status": "healthy"}
        else:
            return {"status": "unhealthy", "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

### Docker Hub

Docker hub monitors container availability:

```python
# Check Docker container health
async def check_docker_health(hub):
    active_containers = len(hub.active_containers)
    available_containers = hub.container_pool.qsize() if hasattr(hub, 'container_pool') else 0
    
    return {
        "status": "healthy" if available_containers > 0 else "degraded",
        "active_containers": active_containers,
        "available_containers": available_containers
    }
```

## Configuration

### Basic Configuration

```yaml
# ~/.gleitzeit/config.yaml
health_monitoring:
  enabled: true
  check_interval: 30  # seconds
  
  circuit_breaker:
    failure_threshold: 5
    recovery_timeout: 60
    half_open_requests: 3
```

## Usage in Workflows

Health monitoring is integrated into the execution engine:

```python
# ExecutionEngine monitors provider health
class ExecutionEngine:
    async def execute_task(self, task):
        provider = self.get_provider(task.method)
        
        # Check circuit breaker state
        if self.circuit_breaker.is_open(provider.name):
            raise ProviderUnavailableError(f"Provider {provider.name} is unavailable")
        
        try:
            result = await provider.execute(task)
            self.circuit_breaker.record_success(provider.name)
            return result
        except Exception as e:
            self.circuit_breaker.record_failure(provider.name)
            raise
```

## Monitoring Output

### CLI Status Command

```bash
# Check system health
gleitzeit status

# Output:
System Status: Healthy
Components:
  - Ollama Provider: Healthy (http://localhost:11434)
  - Python Execution: Healthy (Docker)
  - Persistence: Healthy (Redis)
Active Workflows: 2
Queued Tasks: 5
```

### Basic Metrics

The system tracks basic operational metrics:

- **Task success/failure rates**
- **Provider response times**
- **Queue lengths**
- **Active workflow count**

## Error Recovery

### Automatic Retry

Failed tasks are automatically retried with exponential backoff:

```python
retry_config = RetryConfig(
    max_attempts=3,
    initial_delay=1.0,
    max_delay=30.0,
    backoff_strategy=BackoffStrategy.EXPONENTIAL
)
```

### Provider Failover

When a provider fails, the system attempts recovery:

1. **Circuit breaker opens** after threshold failures
2. **Tasks queued** while provider recovers
3. **Periodic health checks** test recovery
4. **Circuit closes** after successful checks

## Limitations

Current health monitoring is basic and does not include:
- External alerting systems (email, Slack, etc.)
- Advanced metrics collection and storage
- Historical trend analysis
- Custom health check definitions
- Distributed monitoring across instances

For production deployments, consider integrating with external monitoring solutions like Prometheus, Grafana, or DataDog.