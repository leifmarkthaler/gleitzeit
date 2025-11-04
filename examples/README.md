# Gleitzeit Examples

This directory contains working examples demonstrating various features of the Gleitzeit workflow orchestration system.

## 🐍 Python Client Examples (NEW)

**All examples verified working with Gleitzeit 0.0.7** - Uses correct `inputs` pattern for dependencies.

| Example | Description | Key Features |
|---------|-------------|--------------|
| **[01_quick_start.py](01_quick_start.py)** | Basic workflow submission | Simple single-task workflow, result retrieval |
| **[02_sequential_tasks.py](02_sequential_tasks.py)** | Task dependencies | Sequential execution, `depends_on`, `inputs` variable |
| **[03_parallel_tasks.py](03_parallel_tasks.py)** | Parallel execution | Concurrent tasks, result aggregation |
| **[04_websocket_monitoring.py](04_websocket_monitoring.py)** | Real-time monitoring | WebSocket events, callbacks |
| **[05_batch_submission.py](05_batch_submission.py)** | Batch operations | Submit multiple workflows efficiently |
| **[06_etl_pipeline.py](06_etl_pipeline.py)** | Complete ETL pipeline | Extract-Transform-Load with validation |
| **[07_ollama_llm.py](07_ollama_llm.py)** | Ollama LLM integration | Local LLM with llama3.2:latest |
| **[08_timer_tasks.py](08_timer_tasks.py)** | Timer delays | Scheduled delays, rate limiting, backoff patterns |
| **[09_signal_communication.py](09_signal_communication.py)** | Signal-based coordination | Send/broadcast signals for workflow communication |

### Running Examples

```bash
# From gleitzeit root directory
export PYTHONPATH="${PWD}/src:${PYTHONPATH}"

# Run any example
python3 examples/01_quick_start.py
python3 examples/02_sequential_tasks.py
python3 examples/03_parallel_tasks.py
python3 examples/04_websocket_monitoring.py
python3 examples/05_batch_submission.py
python3 examples/06_etl_pipeline.py
python3 examples/07_ollama_llm.py
python3 examples/08_timer_tasks.py
python3 examples/09_signal_communication.py
```

### Legacy Python Examples

| Example | Description | Status |
|---------|-------------|--------|
| [client_example.py](client_example.py) | Original client example | ⚠️ Legacy - needs testing |
| [client_examples.py](client_examples.py) | Multiple client patterns | ⚠️ Legacy - needs testing |
| [ollama_example.py](ollama_example.py) | Ollama LLM integration | ✅ Updated (llama3.2:latest) |

## 📄 YAML Workflow Examples

Pre-defined workflow configurations:

### Signal Communication
- **[signal_workflow.yaml](signal_workflow.yaml)** - Signal send/broadcast/wait patterns
- **[signal_consumer_workflow.yaml](signal_consumer_workflow.yaml)** - Signal consumers

### Validation
- **[validation_workflow.yaml](validation_workflow.yaml)** - Comprehensive validation
- **[simple_validation_test.yaml](simple_validation_test.yaml)** - Basic validation

### HTTP Integration
- **[http_workflow.yaml](http_workflow.yaml)** - HTTP requests, auth, rate limiting

### Advanced Patterns
- **[circuit_breaker_workflow.yaml](circuit_breaker_workflow.yaml)** - Circuit breaker pattern
- **[workflow_composition.yaml](workflow_composition.yaml)** - Nested workflows
- **[parent_workflow.yaml](parent_workflow.yaml)** / **[child_workflow.yaml](child_workflow.yaml)** - Parent-child

## 🔑 Key Concepts

### 1. Task Dependencies with `inputs`

⚠️ **IMPORTANT:** Use `inputs` to access dependency results, not `dependencies`.

```python
# ✅ CORRECT
{
    'id': 'process',
    'type': 'python',
    'depends_on': ['fetch'],
    'params': {
        'code': '''
# Access previous task result via inputs
fetch_result = inputs.get("fetch", {})
data = fetch_result.get("data", [])
'''
    }
}
```

```python
# ❌ WRONG (deprecated)
fetch_result = dependencies.get("fetch", {})  # Won't work!
```

### 2. Parallel vs Sequential Execution

```python
# Parallel: tasks without dependencies run concurrently
workflow = {
    'tasks': [
        {'id': 'task_a', ...},  # Runs immediately
        {'id': 'task_b', ...},  # Runs immediately (parallel with task_a)
        {'id': 'task_c', ...},  # Runs immediately (parallel with a & b)
        {'id': 'combine', 'depends_on': ['task_a', 'task_b', 'task_c'], ...}  # Waits for all
    ]
}

# Sequential: use depends_on to enforce order
workflow = {
    'tasks': [
        {'id': 'step1', ...},                      # Runs first
        {'id': 'step2', 'depends_on': ['step1']},  # Waits for step1
        {'id': 'step3', 'depends_on': ['step2']}   # Waits for step2
    ]
}
```

### 3. WebSocket vs Polling

```python
# Polling (simple but less efficient)
status = await client.wait_for_workflow(workflow_id, timeout=300)

# WebSocket (real-time, more efficient)
await client.wait_for_workflow_async(
    workflow_id,
    on_complete=lambda e: print("Done!"),
    on_failure=lambda e: print(f"Failed: {e}"),
    timeout=300
)
```

## 📖 Documentation

- **[CLIENT_GUIDE.md](../docs/CLIENT_GUIDE.md)** - Complete client documentation with all 60+ methods
- **[QUICK_START.md](../docs/api/QUICK_START.md)** - API reference and REST examples
- **[WebSocket Guide](../docs/python-client-websocket-examples.md)** - Real-time monitoring
- **[Test Suite](../tests/client/)** - More working examples

## ✅ Example Output

### Quick Start
```
============================================================
Quick Start Example
============================================================
✓ Connected to Gleitzeit API
✓ Submitted workflow: workflow-abc123
✓ Workflow completed with status: completed
✓ Result: {'message': 'Hello, World!', 'status': 'success'}
```

### ETL Pipeline
```
============================================================
ETL Pipeline Example
============================================================
✓ Connected to Gleitzeit API
✓ Submitted ETL pipeline: workflow-def456

⏳ Running ETL pipeline...
✓ ETL Pipeline completed: completed

📊 Pipeline Statistics:
   Total tasks: 4
   Completed: 4
   Failed: 0

📥 Load Results:
   Loaded: 5 records
   Status: success
```

---

**Last Updated:** November 4, 2025
**Version:** 0.0.7
**Status:** ✅ All Python examples tested and verified working
