# Gleitzeit Python Client - WebSocket Usage Guide

The Gleitzeit Python client provides powerful WebSocket functionality for real-time workflow monitoring with automatic handling of edge cases like already-completed workflows and validation errors.

## Table of Contents

- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
- [Usage Patterns](#usage-patterns)
  - [Pattern 1: Event-Driven Callbacks](#pattern-1-event-driven-callbacks)
  - [Pattern 2: Async Event Streaming](#pattern-2-async-event-streaming)
  - [Pattern 3: Multiple Workflow Monitoring](#pattern-3-multiple-workflow-monitoring)
  - [Pattern 4: Task-Level Monitoring](#pattern-4-task-level-monitoring)
- [Advanced Features](#advanced-features)
- [Error Handling](#error-handling)
- [Best Practices](#best-practices)
- [Complete Examples](#complete-examples)

---

## Quick Start

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def main():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit workflow
        workflow = {
            "name": "my-workflow",
            "tasks": [{
                "id": "task1",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": "result = {'status': 'done'}"}
            }]
        }

        response = await client.submit_workflow(workflow)

        # Monitor with callbacks
        workflow_done = asyncio.Event()

        await client.wait_for_workflow_async(
            response.workflow_id,
            on_complete=lambda e: workflow_done.set(),
            on_failure=lambda e: print(f"Failed: {e}"),
            timeout=60
        )

        await workflow_done.wait()
        print("✓ Workflow completed!")

asyncio.run(main())
```

---

## Core Concepts

### WebSocket Events

The Gleitzeit server publishes events via WebSocket for real-time monitoring:

- **`workflow:started`** - Workflow execution begins
- **`workflow:completed`** - Workflow finished successfully
- **`workflow:failed`** - Workflow failed (includes validation errors)
- **`task:ready`** - Task is ready to execute
- **`task:started`** - Task execution begins
- **`task:completed`** - Task finished successfully
- **`task:failed`** - Task execution failed

### Already-Completed Detection

**Smart Feature:** The client automatically detects if a workflow/task has already completed before you subscribe to events. If so, it fires your callback immediately with the current state!

This prevents race conditions and ensures callbacks always fire, even for very fast workflows.

```python
# Even if the workflow completes in 1ms, your callback will fire!
await client.wait_for_workflow_async(
    workflow_id,
    on_complete=lambda e: print("Done!")  # ✓ Will always be called
)
```

### Ping/Pong Keepalive

WebSocket connections automatically send ping messages every 30 seconds to keep long-running connections alive. This is handled transparently - you don't need to do anything!

---

## Usage Patterns

### Pattern 1: Event-Driven Callbacks

**Best for:** Non-blocking workflow monitoring with custom success/error handlers

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def monitor_with_callbacks():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit your workflow
        response = await client.submit_workflow({
            "name": "data-pipeline",
            "tasks": [
                {
                    "id": "extract",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'records': 1000}"}
                },
                {
                    "id": "transform",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'transformed': True}"},
                    "dependencies": ["extract"]
                }
            ]
        })

        workflow_id = response.workflow_id
        workflow_done = asyncio.Event()

        # Define callbacks
        def on_success(event):
            print("✅ Pipeline completed successfully!")
            print(f"   Timestamp: {event.get('timestamp')}")
            workflow_done.set()

        def on_failure(event):
            error = event.get('data', {}).get('error')
            print(f"❌ Pipeline failed: {error}")
            # Send alert, rollback changes, etc.
            workflow_done.set()

        def on_task_complete(event):
            task_id = event.get('task_id')
            print(f"⚡ Task completed: {task_id}")

        # Start monitoring (non-blocking!)
        await client.wait_for_workflow_async(
            workflow_id,
            on_complete=on_success,
            on_failure=on_failure,
            on_task_complete=on_task_complete,
            timeout=300
        )

        # You can do other work here while workflow runs
        print("💼 Continuing with other tasks...")
        await asyncio.sleep(0.5)

        # Wait for completion
        await workflow_done.wait()

asyncio.run(monitor_with_callbacks())
```

**Output:**
```
💼 Continuing with other tasks...
⚡ Task completed: extract
⚡ Task completed: transform
✅ Pipeline completed successfully!
   Timestamp: 2025-10-19T12:00:00.123456
```

---

### Pattern 2: Async Event Streaming

**Best for:** Processing events as they arrive, custom event filtering

```python
async def stream_events():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit workflow
        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id

        # Stream events as async generator
        async for event in client.stream_workflow_events([workflow_id]):
            event_type = event.get('event_type', '')

            if 'task:started' in event_type:
                task_id = event.get('task_id')
                print(f"🚀 Task {task_id} started")

            elif 'task:completed' in event_type:
                task_id = event.get('task_id')
                result = event.get('data', {}).get('result')
                print(f"✓ Task {task_id} completed: {result}")

            elif 'workflow:completed' in event_type:
                print("✅ All done!")
                break

            elif 'workflow:failed' in event_type:
                error = event.get('data', {}).get('error')
                print(f"❌ Failed: {error}")
                break
```

---

### Pattern 3: Multiple Workflow Monitoring

**Best for:** Running multiple workflows concurrently with individual handlers

```python
async def monitor_multiple_workflows():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit multiple workflows
        workflows = []
        for i in range(5):
            response = await client.submit_workflow({
                "name": f"batch-job-{i}",
                "tasks": [{
                    "id": f"task-{i}",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": f"result = {{'job': {i}}}"}
                }]
            })
            workflows.append(response.workflow_id)

        # Track results
        completed_workflows = []

        def on_workflow_complete(wf_id, event):
            print(f"✓ Workflow {wf_id} completed")
            completed_workflows.append(wf_id)

        def on_all_complete(summary):
            print(f"\n📊 Summary:")
            print(f"   Total: {summary['total']}")
            print(f"   Completed: {summary['completed']}")
            print(f"   Failed: {summary['failed']}")

        # Monitor all workflows
        await client.watch_multiple_workflows(
            workflows,
            on_workflow_complete=on_workflow_complete,
            on_all_complete=on_all_complete,
            timeout=120
        )

        print(f"\n✅ All {len(completed_workflows)} workflows finished!")
```

**Output:**
```
✓ Workflow workflow-abc123 completed
✓ Workflow workflow-def456 completed
✓ Workflow workflow-ghi789 completed
✓ Workflow workflow-jkl012 completed
✓ Workflow workflow-mno345 completed

📊 Summary:
   Total: 5
   Completed: 5
   Failed: 0

✅ All 5 workflows finished!
```

---

### Pattern 4: Task-Level Monitoring

**Best for:** Monitoring specific tasks within a workflow

```python
async def monitor_specific_task():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit workflow with long-running task
        workflow = {
            "name": "ml-training",
            "tasks": [{
                "id": "train",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
import time
time.sleep(5)  # Simulate training
result = {'accuracy': 0.95, 'loss': 0.05}
"""
                }
            }]
        }

        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id

        # Wait a moment for task to be created
        await asyncio.sleep(0.5)

        # Get task ID from API
        tasks = await client.get_workflow_tasks(workflow_id)
        task_id = tasks[0].get('task_id')

        # Monitor specific task
        task_done = asyncio.Event()

        def on_task_complete(event):
            result = event.get('data', {}).get('result')
            print(f"🎯 Training complete!")
            print(f"   Accuracy: {result.get('accuracy')}")
            print(f"   Loss: {result.get('loss')}")
            task_done.set()

        await client.wait_for_task_ws(
            task_id,
            workflow_id,
            on_complete=on_task_complete,
            timeout=30
        )

        await task_done.wait()
```

**Output:**
```
🎯 Training complete!
   Accuracy: 0.95
   Loss: 0.05
```

---

## Advanced Features

### Connection Health Monitoring

Check WebSocket connection health and latency:

```python
async def check_connection():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        stats = await client.get_connection_stats()

        print(f"Status: {stats['status']}")           # healthy / error
        print(f"Connected: {stats['connected']}")     # True / False
        print(f"Latency: {stats['latency_ms']}ms")    # ping-pong time
        print(f"Connect time: {stats['connect_time_ms']}ms")
```

### Global Workflow Monitoring

Monitor all workflow activity in real-time:

```python
async def monitor_global_activity():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:

        def on_workflow_start(event):
            wf_id = event.get('workflow_id')
            print(f"🚀 New workflow started: {wf_id}")

        def on_workflow_complete(event):
            wf_id = event.get('workflow_id')
            print(f"✅ Workflow completed: {wf_id}")

        def on_task_event(event):
            event_type = event.get('event_type')
            task_id = event.get('task_id')
            print(f"⚡ Task event: {event_type} for {task_id}")

        # Monitor for 60 seconds
        await client.monitor_all_workflows(
            on_workflow_start=on_workflow_start,
            on_workflow_complete=on_workflow_complete,
            on_task_event=on_task_event,
            duration=60
        )
```

### Dynamic Subscription Management

Update which workflows you're monitoring on-the-fly:

```python
async def dynamic_monitoring():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        import websockets
        from urllib.parse import urlparse
        import json

        parsed = urlparse(client.api_url)
        ws_url = f"ws://{parsed.netloc}/ws/events"

        async with websockets.connect(ws_url) as websocket:
            await websocket.recv()  # connection msg

            # Subscribe to workflow1
            await client.unsubscribe(
                websocket,
                workflow_ids=["workflow-123"]
            )

            # Later, subscribe to workflow2 instead
            await websocket.send(json.dumps({
                "action": "subscribe",
                "workflow_ids": ["workflow-456"]
            }))
```

### Historical Event Retrieval

Get past events for a workflow (via REST API):

```python
async def get_history():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Get last 50 events for workflow
        events = await client.get_workflow_events_history(
            workflow_id="workflow-123",
            event_types=["task:completed", "workflow:completed"],
            limit=50
        )

        for event in events:
            print(f"{event['event_type']}: {event['timestamp']}")
```

### Signal Task Monitoring

Monitor signal coordination in real-time via WebSocket:

```python
async def monitor_signal_workflow():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Workflow with signal coordination
        workflow = {
            "name": "producer-consumer",
            "tasks": [
                {
                    "id": "producer",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'data': 'ready'}"}
                },
                {
                    "id": "send_signal",
                    "protocol": "signal/v1",
                    "method": "signal/send",
                    "params": {
                        "signal_name": "data_ready",
                        "payload": {"timestamp": "2025-10-19T12:00:00"}
                    },
                    "dependencies": ["producer"]
                },
                {
                    "id": "consumer",
                    "protocol": "signal/v1",
                    "method": "signal/wait",
                    "params": {
                        "signal_name": "data_ready",
                        "timeout": 30
                    }
                },
                {
                    "id": "process",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'processed': True}"},
                    "dependencies": ["consumer", "send_signal"]
                }
            ]
        }

        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id

        # Track signal events
        signal_events = []

        async for event in client.stream_workflow_events([workflow_id]):
            event_type = event.get('event_type', '')

            # Capture signal-related events
            if 'signal' in event_type or 'waiting' in event_type:
                signal_events.append(event)
                print(f"📡 {event_type}: {event.get('data', {})}")

            # Examples of signal events you can capture:
            # - task:waiting - Task entered waiting state for signal
            # - signal:sent - Signal was sent to workflow(s)
            # - signal:received - Waiting task received the signal
            # - signal:timeout - Signal wait timed out

            if event_type == 'workflow:completed':
                break

        print(f"\nCaptured {len(signal_events)} signal events")
```

#### Signal Event Types

WebSocket events for signal coordination:

- **`task:waiting`** - Task is waiting for a signal
  ```python
  {
      'event_type': 'task:waiting',
      'workflow_id': 'workflow-123',
      'task_id': 'consumer-task',
      'data': {
          'signal_name': 'data_ready',
          'signal_type': 'wait',  # or 'wait_any', 'wait_all'
          'timeout': 30
      }
  }
  ```

- **`signal:sent`** - Signal was emitted
  ```python
  {
      'event_type': 'signal:sent',
      'workflow_id': 'workflow-123',
      'data': {
          'signal_name': 'data_ready',
          'target_workflow': 'workflow-123',
          'payload': {'timestamp': '2025-10-19T12:00:00'}
      }
  }
  ```

- **`signal:received`** - Waiting task received signal
  ```python
  {
      'event_type': 'signal:received',
      'workflow_id': 'workflow-123',
      'task_id': 'consumer-task',
      'data': {
          'signal_name': 'data_ready',
          'payload': {'timestamp': '2025-10-19T12:00:00'}
      }
  }
  ```

- **`signal:timeout`** - Signal wait timed out
  ```python
  {
      'event_type': 'signal:timeout',
      'workflow_id': 'workflow-123',
      'task_id': 'consumer-task',
      'data': {
          'error': 'Signal wait timed out'
      }
  }
  ```

---

## Error Handling

### Validation Errors

Workflow validation errors are automatically detected and reported:

```python
async def handle_validation_errors():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit invalid workflow (missing params)
        invalid_workflow = {
            "name": "broken-workflow",
            "tasks": [{
                "id": "invalid_task",
                "protocol": "python/v1",
                "method": "python/execute"
                # Missing required 'params' field!
            }]
        }

        response = await client.submit_workflow(invalid_workflow)
        workflow_id = response.workflow_id

        # Wait for validation (happens asynchronously)
        await asyncio.sleep(2)

        # Check status via REST API
        status = await client.get_workflow_status(workflow_id)

        if status.status == 'failed':
            print(f"❌ Validation failed!")
            print(f"   Error: {status.error}")
            # Output: [WORKFLOW_VALIDATION_FAILED] Workflow validation failed:
            #         Task xxx: missing required parameter 'code' for method 'python/execute'

        # Or use WebSocket callbacks
        def on_failure(event):
            error = event.get('data', {}).get('error')
            if 'VALIDATION' in error:
                print("Validation error - fix workflow definition")
            else:
                print("Runtime error - check logs")

        await client.wait_for_workflow_async(
            workflow_id,
            on_failure=on_failure
        )
```

### Already-Completed Workflows

The client handles already-completed workflows automatically:

```python
async def handle_fast_workflows():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit very fast workflow
        response = await client.submit_workflow(fast_workflow)
        workflow_id = response.workflow_id

        # Even if workflow completes in 1ms...
        await asyncio.sleep(3)  # ...and we wait 3 seconds...

        # Callback will STILL fire immediately!
        def on_complete(event):
            # event['data']['already_completed'] == True
            print("✓ Callback fired even though workflow already done!")

        await client.wait_for_workflow_async(
            workflow_id,
            on_complete=on_complete
        )
```

### Connection Errors

Handle WebSocket connection failures:

```python
async def handle_connection_errors():
    try:
        async with GleitzeitClient(api_url="http://invalid:9999") as client:
            stats = await client.get_connection_stats()

            if stats['status'] == 'error':
                print("❌ Could not connect to server")
                print(f"   Check if server is running at {client.api_url}")

    except Exception as e:
        print(f"Connection error: {e}")
```

### Timeouts

All WebSocket methods support timeouts:

```python
async def handle_timeouts():
    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        response = await client.submit_workflow(long_workflow)

        try:
            await client.wait_for_workflow_async(
                response.workflow_id,
                on_complete=lambda e: print("Done!"),
                timeout=30  # Timeout after 30 seconds
            )
        except TimeoutError:
            print("⏱️ Workflow took too long")
            # Check status manually
            status = await client.get_workflow_status(response.workflow_id)
            print(f"Current status: {status.status}")
```

---

## Best Practices

### ✅ DO: Use Callbacks for Real-Time Processing

```python
# Good: Process results immediately when available
await client.wait_for_workflow_async(
    workflow_id,
    on_task_complete=lambda e: process_task_result(e),
    on_complete=lambda e: deploy_to_production()
)
```

### ✅ DO: Set Appropriate Timeouts

```python
# Good: Set realistic timeouts based on expected duration
await client.wait_for_workflow_async(
    workflow_id,
    timeout=300  # 5 minutes for data processing
)
```

### ✅ DO: Handle Both Success and Failure

```python
# Good: Always provide both callbacks
await client.wait_for_workflow_async(
    workflow_id,
    on_complete=handle_success,
    on_failure=handle_error  # Don't forget this!
)
```

### ❌ DON'T: Poll When You Can Stream

```python
# Bad: Polling in a loop
while True:
    status = await client.get_workflow_status(workflow_id)
    if status.status == 'completed':
        break
    await asyncio.sleep(1)

# Good: Use WebSocket callbacks
await client.wait_for_workflow_async(
    workflow_id,
    on_complete=lambda e: print("Done!")
)
```

### ❌ DON'T: Block the Event Loop

```python
# Bad: Blocking operations in callbacks
def on_complete(event):
    time.sleep(10)  # Blocks everything!

# Good: Use async or offload to thread
async def on_complete(event):
    await asyncio.sleep(10)  # Non-blocking
```

### ❌ DON'T: Forget Error Handling

```python
# Bad: No error handling
await client.wait_for_workflow_async(workflow_id)

# Good: Handle failures
await client.wait_for_workflow_async(
    workflow_id,
    on_failure=lambda e: send_alert(e)
)
```

---

## Complete Examples

### Example 1: Production ML Pipeline

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def ml_pipeline():
    """Complete ML training pipeline with monitoring."""

    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Define training workflow
        workflow = {
            "name": "ml-training-pipeline",
            "tasks": [
                {
                    "id": "prepare_data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": """
import pandas as pd
# Prepare training data
result = {'samples': 10000, 'features': 50}
"""
                    }
                },
                {
                    "id": "train_model",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": """
import time
time.sleep(2)  # Simulate training
result = {
    'model_id': 'model_v2.1',
    'accuracy': 0.95,
    'training_time': 120
}
"""
                    },
                    "dependencies": ["prepare_data"]
                },
                {
                    "id": "validate_model",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": """
result = {'validation_accuracy': 0.93, 'passed': True}
"""
                    },
                    "dependencies": ["train_model"]
                }
            ]
        }

        # Submit workflow
        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id
        print(f"🚀 Training job submitted: {workflow_id}\n")

        # Track progress
        workflow_done = asyncio.Event()
        task_results = {}

        def on_task_complete(event):
            task_id = event.get('task_id')
            result = event.get('data', {}).get('result')
            task_results[task_id] = result

            # Get task name from workflow definition
            task_name = next(
                (t['id'] for t in workflow['tasks'] if t['id'] in str(task_id)),
                'unknown'
            )
            print(f"✓ {task_name} completed")
            print(f"  Result: {result}\n")

        def on_success(event):
            print("🎉 Training pipeline completed successfully!")
            print("\n📊 Final Results:")
            for task_id, result in task_results.items():
                print(f"  {task_id}: {result}")

            # Deploy model to production
            model_id = task_results.get('train_model', {}).get('model_id')
            if model_id:
                print(f"\n🚀 Deploying {model_id} to production...")

            workflow_done.set()

        def on_failure(event):
            error = event.get('data', {}).get('error')
            print(f"❌ Training pipeline failed!")
            print(f"   Error: {error}")

            # Send alert
            print("   📧 Sending alert to ML team...")

            workflow_done.set()

        # Monitor workflow
        await client.wait_for_workflow_async(
            workflow_id,
            on_task_complete=on_task_complete,
            on_complete=on_success,
            on_failure=on_failure,
            timeout=600
        )

        # Wait for completion
        await workflow_done.wait()

if __name__ == "__main__":
    asyncio.run(ml_pipeline())
```

### Example 2: Batch Job Processor

```python
async def batch_processor():
    """Process multiple batch jobs concurrently."""

    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        # Submit batch jobs
        batch_jobs = []
        for i in range(10):
            workflow = {
                "name": f"batch-job-{i}",
                "tasks": [{
                    "id": f"process-{i}",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": f"""
import random
import time
time.sleep(random.uniform(0.5, 2))
result = {{'job_id': {i}, 'processed': True}}
"""
                    }
                }]
            }

            response = await client.submit_workflow(workflow)
            batch_jobs.append(response.workflow_id)

        print(f"🚀 Submitted {len(batch_jobs)} batch jobs\n")

        # Monitor all jobs
        completed = []
        failed = []

        def on_job_complete(wf_id, event):
            completed.append(wf_id)
            print(f"✓ Job {len(completed)}/{len(batch_jobs)} completed")

        def on_job_failed(wf_id, event):
            failed.append(wf_id)
            error = event.get('data', {}).get('error')
            print(f"❌ Job failed: {error}")

        def on_all_complete(summary):
            print(f"\n📊 Batch Processing Complete!")
            print(f"   Completed: {summary['completed']}")
            print(f"   Failed: {summary['failed']}")
            print(f"   Success rate: {summary['completed']/summary['total']*100:.1f}%")

        # Watch all jobs
        await client.watch_multiple_workflows(
            batch_jobs,
            on_workflow_complete=on_job_complete,
            on_workflow_failed=on_job_failed,
            on_all_complete=on_all_complete,
            timeout=300
        )

if __name__ == "__main__":
    asyncio.run(batch_processor())
```

---

## API Reference

### `wait_for_workflow_async()`

```python
await client.wait_for_workflow_async(
    workflow_id: str,
    on_event: Optional[Callable] = None,
    on_complete: Optional[Callable] = None,
    on_failure: Optional[Callable] = None,
    on_task_complete: Optional[Callable] = None,
    timeout: Optional[int] = None
) -> AsyncTask
```

**Parameters:**
- `workflow_id` - Workflow ID to monitor
- `on_event` - Called for every event (optional)
- `on_complete` - Called when workflow completes successfully
- `on_failure` - Called when workflow fails
- `on_task_complete` - Called for each completed task
- `timeout` - Timeout in seconds (optional)

**Returns:** Background async task

---

### `wait_for_task_ws()`

```python
await client.wait_for_task_ws(
    task_id: str,
    workflow_id: str,
    on_complete: Optional[Callable] = None,
    on_failure: Optional[Callable] = None,
    timeout: Optional[int] = None
) -> Dict[str, Any]
```

**Parameters:**
- `task_id` - Task ID to monitor (internal runtime ID)
- `workflow_id` - Workflow ID containing the task
- `on_complete` - Called when task completes
- `on_failure` - Called when task fails
- `timeout` - Timeout in seconds (optional)

**Returns:** Final task event

---

### `watch_multiple_workflows()`

```python
await client.watch_multiple_workflows(
    workflow_ids: List[str],
    on_workflow_complete: Optional[Callable] = None,
    on_all_complete: Optional[Callable] = None,
    on_workflow_failed: Optional[Callable] = None,
    timeout: Optional[int] = None
) -> Dict[str, Any]
```

**Parameters:**
- `workflow_ids` - List of workflow IDs to monitor
- `on_workflow_complete` - Called for each completed workflow
- `on_all_complete` - Called when all workflows finish
- `on_workflow_failed` - Called for each failed workflow
- `timeout` - Timeout in seconds (optional)

**Returns:** Summary dict with counts

---

### `get_connection_stats()`

```python
await client.get_connection_stats() -> Dict[str, Any]
```

**Returns:** Connection health statistics
```python
{
    'status': 'healthy',
    'connected': True,
    'latency_ms': 15.2,
    'connect_time_ms': 45.8
}
```

---

## Troubleshooting

### WebSocket Not Connecting

**Problem:** `get_connection_stats()` returns `connected: False`

**Solutions:**
- Check if server is running: `curl http://localhost:8000/health`
- Verify WebSocket endpoint: `curl -v http://localhost:8000/ws/events`
- Check firewall/proxy settings
- Try with `auto_login=False` if auth is failing

### Callbacks Not Firing

**Problem:** `on_complete` callback never called

**Solutions:**
- Check if workflow actually completed: `await client.get_workflow_status(workflow_id)`
- Increase timeout value
- Check for errors in workflow definition
- Verify WebSocket connection: `await client.get_connection_stats()`

### High Latency

**Problem:** `latency_ms` is very high (> 1000ms)

**Solutions:**
- Check network connection quality
- Verify server isn't overloaded
- Consider using regional deployment
- Check for DNS resolution issues

---

## Next Steps

- Check out [workflow-examples.md](workflow-examples.md) for workflow definition examples
- See [python-client-rest-api.md](python-client-rest-api.md) for REST API usage
- Read [architecture.md](architecture.md) to understand the system design

---

**Questions or issues?** Report them at https://github.com/anthropics/gleitzeit/issues
