# Circuit Breaker Pattern Documentation

## Overview

Gleitzeit implements the Circuit Breaker pattern to protect against cascading failures when external services become unavailable. The circuit breaker monitors for failures and automatically "opens" to fail fast when a service is down, preventing unnecessary resource consumption and improving system resilience.

## Key Concepts

### Circuit States

The circuit breaker has three states:

1. **CLOSED** (Normal Operation)
   - All requests pass through to the service
   - Failures are counted but requests continue
   - This is the normal operating state

2. **OPEN** (Fail Fast)
   - Requests fail immediately without attempting the service call
   - Triggered after crossing the failure threshold
   - Remains open for a configured timeout period
   - Returns `CircuitOpenError` immediately

3. **HALF_OPEN** (Testing Recovery)
   - Allows limited test requests through
   - If test requests succeed, circuit closes
   - If test requests fail, circuit reopens
   - Automatically transitions from OPEN after timeout

```
    [CLOSED] ---(failures >= threshold)---> [OPEN]
        ^                                      |
        |                                      | (timeout expires)
        |                                      v
        +<---(successes >= threshold)--- [HALF_OPEN]
                                              |
                                              | (any failure)
                                              v
                                           [OPEN]
```

## Configuration

### Basic Configuration

```python
from gleitzeit.core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

config = CircuitBreakerConfig(
    failure_threshold=5,        # Open after 5 failures
    success_threshold=2,        # Close after 2 successes in half-open
    reset_timeout=60,          # Try recovery after 60 seconds
    half_open_max_calls=3      # Max 3 concurrent test calls
)

breaker = CircuitBreaker("service_name", config)
```

### Handler Configuration

Configure circuit breakers in handler initialization:

```yaml
# In workflow YAML
config:
  handlers:
    ollama:
      base_url: "http://localhost:11434"
      circuit_breaker:
        failure_threshold: 5
        success_threshold: 2
        reset_timeout: 60
        half_open_max_calls: 3
```

Or programmatically:

```python
handler = OllamaHandler({
    'base_url': 'http://localhost:11434',
    'circuit_breaker': {
        'failure_threshold': 5,
        'success_threshold': 2,
        'reset_timeout': 60,
        'half_open_max_calls': 3
    }
})
```

### Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `failure_threshold` | 5 | Number of failures before opening circuit |
| `success_threshold` | 2 | Number of successes in half-open before closing |
| `reset_timeout` | 60 | Seconds before attempting recovery |
| `half_open_max_calls` | 3 | Maximum concurrent calls in half-open state |
| `failure_exceptions` | `(Exception,)` | Exception types that count as failures |
| `exclude_exceptions` | `()` | Exception types that don't count as failures |

## Usage

### Basic Usage

```python
from gleitzeit.core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitOpenError

# Create circuit breaker
config = CircuitBreakerConfig(failure_threshold=3)
breaker = CircuitBreaker("external_api", config)

# Use with async function
async def call_external_api(data):
    response = await http_client.post("https://api.example.com", json=data)
    return response.json()

# Execute through circuit breaker
try:
    result = await breaker.call(call_external_api, {"key": "value"})
except CircuitOpenError as e:
    # Circuit is open - service is down
    logger.error(f"Service unavailable: {e}")
    # Handle gracefully - maybe use cached data or default response
except Exception as e:
    # Other errors (connection timeout, etc.)
    logger.error(f"API call failed: {e}")
```

### Integration with Handlers

The circuit breaker is integrated into handlers that call external services:

```python
class OllamaHandler(BaseHandler):
    def __init__(self, config):
        # Initialize circuit breaker
        self.circuit_breaker = CircuitBreaker(
            name=f"ollama_{self.base_url}",
            config=CircuitBreakerConfig.for_external_service()
        )

    async def execute(self, task):
        # Check if circuit is open first
        if self.circuit_breaker.is_open():
            return TaskResult(
                status=TaskStatus.FAILED,
                error="Service unavailable (circuit breaker open)"
            )

        # Execute through circuit breaker
        try:
            result = await self.circuit_breaker.call(
                self._make_api_request,
                task.params
            )
            return TaskResult(status=TaskStatus.COMPLETED, result=result)
        except CircuitOpenError:
            return TaskResult(
                status=TaskStatus.FAILED,
                error="Service unavailable"
            )
```

### Excluding Specific Exceptions

Some exceptions shouldn't trigger the circuit breaker:

```python
config = CircuitBreakerConfig(
    failure_threshold=5,
    # Don't count validation errors as service failures
    exclude_exceptions=(ValueError, ValidationError)
)

# These won't open the circuit
async def validate_and_call(data):
    if not data:
        raise ValueError("Invalid input")  # Won't count as failure
    return await api_call(data)  # Connection errors will count
```

## Monitoring

### Getting Circuit Status

```python
# Get current status
status = breaker.get_status()
print(f"State: {status['state']}")
print(f"Failures: {status['failure_count']}")
print(f"Stats: {status['stats']}")

# Output:
# State: closed
# Failures: 0
# Stats: {
#     'total_calls': 150,
#     'successful_calls': 145,
#     'failed_calls': 5,
#     'rejected_calls': 0,
#     'consecutive_failures': 0,
#     'consecutive_successes': 10
# }
```

### Manual Control

```python
# Manually reset circuit breaker
breaker.reset()  # Forces circuit to CLOSED state

# Check state
if breaker.is_open():
    logger.warning("Circuit is open - service is down")
elif breaker.is_closed():
    logger.info("Circuit is closed - normal operation")
```

## Workflow Examples

### Example 1: Protecting LLM Calls

```yaml
name: llm-workflow-with-circuit-breaker
tasks:
  - id: generate_summary
    method: ollama/generate
    params:
      model: llama2
      prompt: "Summarize this text: ${input.text}"
    # If Ollama is down, this fails fast after threshold

  - id: fallback_summary
    method: python/exec
    params:
      code: |
        # Simple fallback if LLM is unavailable
        text = workflow.get_param('input.text')
        return {"summary": text[:200] + "..."}
    when: "generate_summary.failed"
```

### Example 2: Database Operations

```python
class DatabaseHandler(BaseHandler):
    def __init__(self, config):
        # More aggressive settings for databases
        self.circuit_breaker = CircuitBreaker(
            name="postgres_main",
            config=CircuitBreakerConfig(
                failure_threshold=3,    # Open quickly
                success_threshold=1,    # One success to close
                reset_timeout=30,       # Try recovery sooner
                failure_exceptions=(psycopg2.OperationalError,)
            )
        )
```

### Example 3: Multi-Service Workflow

```yaml
name: multi-service-workflow
config:
  handlers:
    # Each service gets its own circuit breaker
    openai:
      circuit_breaker:
        failure_threshold: 5
        reset_timeout: 120

    ollama:
      circuit_breaker:
        failure_threshold: 3
        reset_timeout: 60

    database:
      circuit_breaker:
        failure_threshold: 2
        reset_timeout: 30

tasks:
  # If OpenAI is down, fails fast
  - id: gpt_analysis
    method: openai/completion
    params:
      prompt: "Analyze: ${data}"

  # If Ollama is down, fails fast independently
  - id: local_llm_backup
    method: ollama/generate
    params:
      prompt: "Analyze: ${data}"
    when: "gpt_analysis.failed"

  # Database has its own circuit breaker
  - id: store_result
    method: database/insert
    params:
      table: results
      data: "${gpt_analysis.result || local_llm_backup.result}"
```

## Behavior with Gleitzeit's Hard-Fail Approach

The circuit breaker **maintains Gleitzeit's hard-fail semantics**:

1. **Task still fails** - When circuit is open, task fails immediately
2. **Workflow still fails** - Failed task causes workflow failure as normal
3. **Faster failure** - Circuit breaker makes failure faster, not hidden
4. **No masking** - Failures are not hidden or automatically retried

The benefit is **faster failure** and **resource protection**, not failure recovery.

## Benefits

### 1. **Prevents Cascading Failures**
- Stops hammering down services
- Prevents timeout accumulation
- Reduces resource waste

### 2. **Fails Fast**
- Immediate failure when circuit is open
- No waiting for timeouts
- Better user experience

### 3. **Automatic Recovery**
- Tests service availability automatically
- Recovers without manual intervention
- Gradual recovery through half-open state

### 4. **Resource Protection**
- Prevents thread/connection exhaustion
- Reduces unnecessary network traffic
- Protects both client and server

### 5. **Visibility**
- Clear error messages about circuit state
- Statistics for monitoring
- State change tracking

## Advanced Configuration

### Presets for Common Services

```python
# For external HTTP services
config = CircuitBreakerConfig.for_external_service()
# failure_threshold=5, success_threshold=2, reset_timeout=60

# For database connections
config = CircuitBreakerConfig.for_database()
# failure_threshold=3, success_threshold=1, reset_timeout=30

# Custom for specific needs
config = CircuitBreakerConfig(
    failure_threshold=10,     # Very tolerant
    success_threshold=5,      # Require strong recovery
    reset_timeout=300,        # Long timeout (5 min)
    half_open_max_calls=1     # Very careful testing
)
```

### Distributed Circuit Breakers (Future)

```python
# Share circuit state across workers (planned feature)
from gleitzeit.core.circuit_breaker import RedisBackedCircuitBreaker

breaker = RedisBackedCircuitBreaker(
    name="shared_service",
    config=config,
    redis_client=redis
)
# All workers share the same circuit state
```

## Testing

### Unit Testing with Circuit Breakers

```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_handler_with_circuit_breaker():
    # Create handler with circuit breaker
    handler = OllamaHandler({
        'circuit_breaker': {
            'failure_threshold': 2,
            'reset_timeout': 0.1  # Fast for testing
        }
    })

    # Mock the API call to fail
    handler._make_api_request = AsyncMock(
        side_effect=ConnectionError("Service down")
    )

    # First failures go through
    result1 = await handler.execute(task)
    assert result1.status == TaskStatus.FAILED

    result2 = await handler.execute(task)
    assert result2.status == TaskStatus.FAILED

    # Circuit should now be open
    result3 = await handler.execute(task)
    assert result3.status == TaskStatus.FAILED
    assert "circuit breaker open" in result3.error.lower()

    # API wasn't called for the third attempt
    assert handler._make_api_request.call_count == 2
```

### Integration Testing

```bash
# Test with service down
docker stop ollama
gleitzeit workflow submit examples/circuit_breaker_workflow.yaml
# Should fail fast after threshold

# Bring service back up
docker start ollama
# Wait for reset_timeout
sleep 60
gleitzeit workflow submit examples/circuit_breaker_workflow.yaml
# Should work normally
```

## Troubleshooting

### Circuit Won't Close

**Problem**: Circuit remains open even though service is back up

**Solutions**:
1. Check `reset_timeout` - may need to wait longer
2. Verify `success_threshold` - may need multiple successes
3. Check for intermittent failures reopening circuit
4. Manually reset if needed: `breaker.reset()`

### Circuit Opens Too Quickly

**Problem**: Normal transient errors open circuit

**Solutions**:
1. Increase `failure_threshold`
2. Exclude certain exception types
3. Add retry logic before circuit breaker
4. Use longer `reset_timeout` for unstable services

### Half-Open Thrashing

**Problem**: Circuit keeps alternating between half-open and open

**Solutions**:
1. Increase `success_threshold` for stronger confirmation
2. Reduce `half_open_max_calls` to test more carefully
3. Increase `reset_timeout` to reduce test frequency

## Best Practices

1. **Set appropriate thresholds** - Balance between tolerance and protection
2. **Use different configs per service** - Databases vs APIs have different needs
3. **Monitor circuit states** - Alert when circuits open frequently
4. **Test failure scenarios** - Ensure graceful degradation
5. **Document fallback behavior** - Clear expectations when services are down
6. **Don't hide failures** - Circuit breaker should make failures faster, not hidden

## Performance Considerations

- **Overhead**: < 0.1ms when circuit is closed
- **Memory**: ~1KB per circuit breaker instance
- **Thread safety**: Fully async-safe with locks
- **No network calls**: All decisions are local

## Future Enhancements

1. **Redis-backed state sharing** - Share circuit state across workers
2. **Monitoring dashboard** - Real-time circuit breaker status
3. **Adaptive thresholds** - Automatic adjustment based on patterns
4. **Health check probes** - Active service health checking
5. **Circuit breaker metrics** - Prometheus/Grafana integration

## Conclusion

The circuit breaker pattern in Gleitzeit provides essential protection against external service failures while maintaining the framework's hard-fail philosophy. By failing fast when services are down, it improves system resilience and resource utilization without compromising the predictable failure semantics that Gleitzeit provides.