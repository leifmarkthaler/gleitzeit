# Gleitzeit Workflow Examples

This directory contains example workflows demonstrating various Gleitzeit features.

## Signal Communication Examples (NEW)

### signal_workflow.yaml
Demonstrates the new signal send and broadcast capabilities:
- **signal/send** - Send signals to current workflow (default) or specific workflows
- **signal/broadcast** - Send signals system-wide
- **signal/wait** - Wait for signals
- **signal/wait_any** - Wait for any of multiple signals

Key features:
- Internal workflow signaling
- Cross-workflow communication
- System-wide broadcasting
- Signal acknowledgment patterns

### signal_consumer_workflow.yaml
Shows how to build workflows that receive and process signals:
- Receiving broadcast signals (system-wide events)
- Receiving targeted signals from specific workflows
- Sending acknowledgments back to senders
- Waiting for multiple signals before proceeding

## Validation Examples

### validation_workflow.yaml
Comprehensive validation workflow showing:
- Input parameter validation
- Schema validation with JSON Schema
- Range and constraint checking
- Error handling and reporting

### simple_validation_test.yaml
Minimal validation example for testing the validation framework.

## HTTP/API Integration Examples

### http_workflow.yaml
Comprehensive HTTP handler demonstration:
- **GET/POST/PUT/DELETE/PATCH** - All HTTP methods
- **Authentication** - Bearer tokens, Basic auth, API keys
- **Error handling** - Expected status codes, timeouts
- **Rate limiting** - Control request frequency
- **Response parsing** - JSON, text, binary formats
- **JSONPath extraction** - Extract specific data from responses
- **Form data** - Submit form-encoded data

Key features:
- External API integration (GitHub, httpbin)
- Parallel HTTP requests
- Authentication patterns
- Error recovery strategies

## LLM Integration Examples

### ollama_example.py
Python script demonstrating:
- Integration with Ollama LLM
- Dynamic prompt generation
- Response processing
- Error handling for LLM tasks

## Running Examples

### Using the CLI
```bash
# Submit a workflow
gleitzeit submit examples/signal_workflow.yaml

# Submit with specific workflow ID
gleitzeit submit examples/signal_consumer_workflow.yaml --workflow-id consumer-1

# Monitor workflow status
gleitzeit status <workflow-id>
```

### Using Python
```python
import asyncio
from gleitzeit import submit_workflow

async def run_example():
    # Load and submit workflow
    with open('examples/signal_workflow.yaml', 'r') as f:
        workflow = yaml.safe_load(f)

    workflow_id = await submit_workflow(workflow)
    print(f"Submitted workflow: {workflow_id}")

asyncio.run(run_example())
```

## Signal Patterns

### Pattern 1: Internal Coordination
Use signals within a workflow for task coordination:
```yaml
tasks:
  - id: process
    type: python
    code: "# Process data"

  - id: signal_done
    type: signal
    signal_action: send
    signal_name: process-complete
    dependencies: [process]

  - id: cleanup
    type: signal
    signal_action: wait
    signal_name: process-complete
    dependencies: [signal_done]
```

### Pattern 2: Producer-Consumer
One workflow produces data, others consume:
```yaml
# Producer
- id: produce
  type: signal
  signal_action: send
  signal_name: data-ready
  target_workflows: [consumer-1, consumer-2]

# Consumer
- id: consume
  type: signal
  signal_action: wait
  signal_name: data-ready
```

### Pattern 3: System Events
Broadcast system-wide events:
```yaml
# Broadcaster
- id: alert
  type: signal
  signal_action: broadcast
  signal_name: system-alert

# Listeners (any workflow)
- id: handle_alert
  type: signal
  signal_action: wait
  signal_name: system-alert
```

## HTTP Patterns

### Pattern 1: Sequential API Calls
Chain API calls where each depends on the previous:
```yaml
tasks:
  - id: get_user
    type: http
    method: http/get
    params:
      url: https://api.example.com/user/123

  - id: get_user_posts
    type: http
    method: http/get
    params:
      url: https://api.example.com/user/123/posts
    dependencies: [get_user]
```

### Pattern 2: Parallel API Calls
Make multiple API calls simultaneously:
```yaml
tasks:
  - id: fetch_a
    type: http
    method: http/get
    params:
      url: https://api.example.com/a

  - id: fetch_b
    type: http
    method: http/get
    params:
      url: https://api.example.com/b

  - id: combine_results
    type: python
    dependencies: [fetch_a, fetch_b]
```

### Pattern 3: Error Recovery
Handle API failures gracefully:
```yaml
tasks:
  - id: primary_api
    type: http
    method: http/get
    params:
      url: https://primary.api.com/data
      expected_status: [200, 503]  # Accept service unavailable

  - id: fallback_api
    type: http
    method: http/get
    params:
      url: https://backup.api.com/data
    dependencies: [primary_api]
    when: "{{ primary_api.status == 503 }}"  # Only if primary fails
```

## Testing Workflows

### Test Signal Communication
```bash
# Start Redis (required)
redis-server

# Run signal tests
python test_signal_send.py
python test_signal_broadcast.py

# Monitor signals in Redis
redis-cli MONITOR | grep signal
```

### Test Validation
```bash
# Submit validation workflow
gleitzeit submit examples/validation_workflow.yaml

# Check validation results
gleitzeit logs <workflow-id>
```

## Best Practices

1. **Signal Naming**: Use descriptive, namespaced signal names
   - Good: `user:registration:complete`
   - Bad: `done`

2. **Timeouts**: Always set timeouts on wait operations
   ```yaml
   signal_action: wait
   timeout: 60  # seconds
   ```

3. **Payloads**: Include context in signal payloads
   ```yaml
   payload:
     workflow_id: "${WORKFLOW_ID}"
     timestamp: "${TIMESTAMP}"
     data: actual_data
   ```

4. **Error Handling**: Handle signal timeouts gracefully
   ```yaml
   - id: wait_with_fallback
     type: signal
     signal_action: wait
     timeout: 30
     on_timeout: continue  # or fail
   ```

## Documentation

For complete documentation, see:
- [Signal Send/Broadcast Documentation](../docs/SIGNAL_SEND_BROADCAST.md)
- [Handler System Documentation](../HANDLER_SYSTEM_DOCUMENTATION.md)
- [Workflow Syntax Guide](../docs/workflow_syntax.md)