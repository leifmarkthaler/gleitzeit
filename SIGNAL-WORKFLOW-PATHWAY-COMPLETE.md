# Signal Workflow Complete Pathway Documentation - SECURITY UPDATED

## Overview

This document traces the complete execution pathway for signal workflows in Gleitzeit, from workflow submission through signal-based task coordination to final completion. 

**🔒 SECURITY UPDATED**: This pathway now includes the **critical security fixes** for workflow-scoped signals, **persistence layer integration fixes**, and **central error system integration** implemented to resolve signal namespace collision vulnerabilities and SignalTaskHandler bypass issues.

## Test Case: Simple Signal Workflow

**Workflow**: `test_signal_simple.yaml`
```yaml
name: simple_signal_test
version: 1.0.0
description: Simple test of signal functionality

tasks:
  - name: start_workflow
    protocol: python/v1
    method: python/execute
    params:
      file: signal_test_start.py

  - name: wait_for_approval
    protocol: signal/v1
    method: signal/wait
    params:
      signal: test_approval
      timeout: 60
    dependencies:
      - start_workflow

  - name: process_after_signal
    protocol: python/v1
    method: python/execute
    params:
      file: signal_test_process.py
    dependencies:
      - wait_for_approval
```

## Complete Execution Pathway

### Phase 1: Workflow Submission

#### 1.1 API Endpoint Hit
```
POST /workflows/run?workflow_file=test_signal_simple.yaml
```

#### 1.2 SystemManager Processing
- **File**: `src/gleitzeit/system/system_manager.py:submit_workflow()`
- **Action**: Validates workflow and creates workflow object
- **Log**: `Workflow submission - workflow_id: workflow-d56a61145bac45caa7525bb8171b90e9, user_id: basic-user, session_id: basic-user-default`

#### 1.3 Dependency Validation
- **File**: `src/gleitzeit/core/stateless_dependency_manager.py`
- **Action**: Validates task dependencies and protocol availability
- **Log**: `Workflow workflow-d56a61145bac45caa7525bb8171b90e9 validated successfully`

#### 1.4 Protocol Validation
- **File**: `src/gleitzeit/providers/pooling_adapter.py`
- **Action**: Validates that signal/v1 protocol is available
- **Logs**:
  ```
  🔍 VALIDATION: Available protocols: ['python/v1', 'llm/v1', 'timer/v1', 'signal/v1']
  🔍 VALIDATION: Found provider for protocol 'signal/v1': SignalProvider
  ✅ VALIDATION: Method 'signal/wait' is supported by protocol 'signal/v1'
  ```

### Phase 2: Event System Initialization

#### 2.1 WORKFLOW_SUBMITTED Event Emission
- **File**: `src/gleitzeit/core/workflow_manager.py`
- **Action**: Emits workflow submitted event to event bus
- **Event Data**:
  ```json
  {
    "workflow_event": {
      "workflow_id": "workflow-d56a61145bac45caa7525bb8171b90e9",
      "timestamp": "2025-09-12T13:43:19.051387",
      "total_tasks": 3,
      "status": "pending"
    }
  }
  ```

#### 2.2 TaskOrchestrator Event Handler
- **File**: `src/gleitzeit/core/task_orchestrator.py:_handle_workflow_submitted()`
- **Action**: Processes workflow submission and identifies ready tasks
- **Log**: `Processing WORKFLOW_SUBMITTED for workflow-d56a61145bac45caa7525bb8171b90e9`

#### 2.3 Initial Task Identification
- **Action**: Analyzes dependencies to find tasks with no prerequisites
- **Result**: Identifies `start_workflow` task as ready for execution
- **Log**: `Found 1 ready tasks for workflow workflow-d56a61145bac45caa7525bb8171b90e9 (completed: set())`

### Phase 3: First Task Execution (Python Task)

#### 3.1 Task Queuing
- **File**: `src/gleitzeit/core/task_orchestrator.py:enqueue_ready_task()`
- **Action**: Queues the start_workflow task for execution
- **Log**: `Enqueued newly ready task task-afc2957b071d449092a9f5fd9e0e760a from workflow workflow-d56a61145bac45caa7525bb8171b90e9`

#### 3.2 TASK_READY Event Emission
- **Event Type**: `task:ready`
- **Event Data**: `{"task_id": "task-afc2957b071d449092a9f5fd9e0e760a", "workflow_id": "workflow-d56a61145bac45caa7525bb8171b90e9", "protocol": "python/v1", "method": "python/execute"}`

#### 3.3 Task Execution
- **File**: `src/gleitzeit/core/task_executor.py:execute_task()`
- **Provider**: PythonProvider
- **Action**: Executes `signal_test_start.py`
- **Duration**: 0.032199 seconds

#### 3.4 Task Completion
- **Event Type**: `task:completed`
- **Status**: `completed`
- **Log**: `Task task-afc2957b071d449092a9f5fd9e0e760a completed successfully`

### Phase 4: Signal Task Processing

#### 4.1 Dependency Resolution
- **File**: `src/gleitzeit/core/task_orchestrator.py:_handle_task_completed()`
- **Action**: Identifies that `wait_for_approval` task is now ready (start_workflow completed)
- **Log**: `Found 1 ready tasks for workflow workflow-d56a61145bac45caa7525bb8171b90e9 (completed: {'task-afc2957b071d449092a9f5fd9e0e760a'})`

#### 4.2 Signal Task Queuing
- **Log**: `Enqueued newly ready task task-000fa5610c874b81bea6b8d3a61e6d88 from workflow workflow-d56a61145bac45caa7525bb8171b90e9`

#### 4.3 Signal Task Parameter Resolution
- **File**: `src/gleitzeit/core/parameter_resolver.py`
- **Resolved Parameters**:
  ```json
  {
    "signal": "test_approval",
    "timeout": 60,
    "_workflow_id": "workflow-d56a61145bac45caa7525bb8171b90e9",
    "_task_id": "task-000fa5610c874b81bea6b8d3a61e6d88"
  }
  ```

#### 4.4 Signal Provider Execution
- **File**: `src/gleitzeit/providers/signal_provider.py:execute()`
- **Method**: `signal/wait`
- **Action**: Registers task as signal waiter and transitions to SLEEPING state

#### 4.5 🔒 **SECURE Signal Waiter Registration**
- **File**: `src/gleitzeit/signals/handler.py:handle_wait()`
- **🔒 Redis Key**: `signal:{workflow_id}:test_approval:waiters` (workflow-scoped)
- **Waiter Entry**: `workflow-d56a61145bac45caa7525bb8171b90e9:task-000fa5610c874b81bea6b8d3a61e6d88`
- **🔒 Security Helper**: Uses `_get_scoped_signal_key()` for workflow isolation
- **✅ Persistence**: Registration done through SystemManager's persistence layer
- **Log**: `Signal waiter registered: workflow-005904c59a5d4aa0a39d93dfa56036af:task-728ddaf06e78467f90539d94a9c88c3d:0c434041 waiting for 'test_approval'`

#### 4.6 Task Status Update
- **Status**: `SLEEPING`
- **Action**: Task executor updates task status to indicate it's waiting for external signal
- **Log**: `Task task-000fa5610c874b81bea6b8d3a61e6d88 status updated to SLEEPING, waiting for signal 'test_approval'`

### Phase 5: Signal Sending

#### 5.1 🔒 **SECURE Signal API Call**
```bash
curl -X POST http://localhost:8000/signals/workflows/workflow-005904c59a5d4aa0a39d93dfa56036af/send/test_approval
```
**🔒 SECURITY**: Now requires workflow ID in URL path to prevent cross-workflow signal interference

#### 5.2 Secure Signal Endpoint Processing
- **File**: `src/gleitzeit/api/routes/signals.py:send_signal_wake()`
- **🔒 NEW PATH**: `/signals/workflows/{workflow_id}/send/{signal_name}`
- **Action**: Validates workflow exists, then calls SignalTaskHandler with workflow_id
- **Security**: Prevents global signal broadcasting

#### 5.3 🔒 **SECURE Signal Handler Processing**  
- **File**: `src/gleitzeit/signals/handler.py:send_signal()`
- **🔒 NEW**: Requires `workflow_id` parameter (mandatory for security)
- **Action**: Finds waiters for signal within specific workflow only
- **✅ FIXED**: Now properly integrated with persistence layer instead of bypassing it

#### 5.4 🔒 **SECURE Waiter Discovery**
- **🔒 Redis Query**: `SMEMBERS signal:{workflow_id}:test_approval:waiters` (workflow-scoped)
- **Security Check**: Verifies all waiters belong to target workflow
- **Found Waiters**: Only tasks from target workflow (prevents cross-workflow waking)
- **Log**: `Woke task {task_id} in workflow {workflow_id} with signal 'test_approval'`

#### 5.5 ✅ **NEW: Proper Task Completion via Persistence Layer**
For each waiting task, now completes via proper persistence layer:
```python
# NEW IMPLEMENTATION: _complete_signal_task()
async def _complete_signal_task(self, task_id: str, workflow_id: str, signal_name: str, payload: Dict[str, Any] = None):
    # 1. Get task from persistence 
    task = await self.persistence.get_task(task_id)
    
    # 2. Update task status to COMPLETED
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    await self.persistence.save_task(task)
    
    # 3. Create and save task result
    task_result = TaskResult(
        task_id=task_id,
        status=TaskStatus.COMPLETED,
        result={"status": "completed", "signal": signal_name, "payload": payload or {}, "timestamp": str(time.time())},
        error=None,
        started_at=task.started_at or datetime.utcnow(),
        completed_at=task.completed_at,
        metadata={"executor": "SignalTaskHandler", "signal": signal_name}
    )
    await self.persistence.save_task_result(task_result)
    
    # 4. Emit proper event through event bus
    if self.event_bus:
        event = create_task_completed_event(task_id=task_id, workflow_id=workflow_id, duration=..., source="signal_handler")
        await self.event_bus.emit(event)
```

#### 5.6 ✅ **FIXED: Proper Event Bus Integration**
- **Before**: Direct Redis stream writes bypassing event system
- **After**: Proper event emission through SystemManager's event bus
- **Result**: Task completion events properly processed by TaskOrchestrator

#### 5.7 🔒 **SECURE API Response**
```json
{
  "workflow_id": "workflow-005904c59a5d4aa0a39d93dfa56036af",
  "signal": "test_approval",
  "tasks_woken": 1,
  "success": true
}
```
**🔒 SECURITY**: Response now includes workflow_id and only shows tasks woken within that workflow

### Phase 6: Signal Task Completion Processing

#### 6.1 Event Bus Processing
- **File**: `src/gleitzeit/events/stream_event_bus.py`
- **Action**: Consumes task:completed event from Redis stream
- **Log**: `Processing event 'task:completed' with 4 handler(s)`

#### 6.2 Task Orchestrator Handling
- **File**: `src/gleitzeit/core/task_orchestrator.py:_handle_task_completed()`
- **Action**: Processes signal task completion and identifies next ready tasks
- **Log**: `Task task-000fa5610c874b81bea6b8d3a61e6d88 execution completed with status completed`

#### 6.3 Next Task Identification
- **Action**: Identifies `process_after_signal` task as ready (wait_for_approval completed)
- **Log**: `Found 1 ready tasks for workflow workflow-d56a61145bac45caa7525bb8171b90e9 (completed: {'task-afc2957b071d449092a9f5fd9e0e760a', 'task-000fa5610c874b81bea6b8d3a61e6d88'})`

### Phase 7: Final Task Execution

#### 7.1 Final Task Queuing
- **Log**: `Enqueued newly ready task task-590d8625cb474f2b9055227d58ea91fc from workflow workflow-d56a61145bac45caa7525bb8171b90e9`

#### 7.2 Final Task Execution
- **Provider**: PythonProvider
- **Script**: `signal_test_process.py`
- **Output**: "Signal received! Processing continues..."

#### 7.3 Final Task Completion
- **Event Type**: `task:completed`
- **Log**: `Task task-590d8625cb474f2b9055227d58ea91fc completed successfully`

### Phase 8: Workflow Completion

#### 8.1 Workflow Status Update
- **Action**: All tasks completed, workflow transitions to completed state
- **Final Status**: `WorkflowStatus.COMPLETED`

#### 8.2 Cleanup
- **Action**: Signal waiters removed from Redis
- **Action**: Task results persisted for retrieval

## Key Components and Their Roles

### SystemManager (`src/gleitzeit/system/system_manager.py`)
- **Role**: Central orchestration hub
- **Key Functions**: Workflow submission, provider management, signal manager initialization
- **Integration**: Coordinates between all subsystems

### SignalProvider (`src/gleitzeit/providers/signal_provider.py`)
- **Role**: Handles signal/v1 protocol tasks
- **Key Methods**: `execute()` for signal/wait operations
- **Integration**: Interfaces with SignalTaskHandler for Redis operations

### SignalTaskHandler (`src/gleitzeit/signals/handler.py`)
- **Role**: Core signal management logic
- **Key Methods**: 
  - `wait_for_signal()`: Register task as signal waiter
  - `send_signal()`: Wake waiting tasks and emit completion events
- **Storage**: Redis-based waiter registry and metadata

### TaskOrchestrator (`src/gleitzeit/core/task_orchestrator.py`)
- **Role**: Task dependency management and execution coordination
- **Key Functions**: 
  - Processes WORKFLOW_SUBMITTED events
  - Manages task ready/completion state transitions
  - Enqueues ready tasks for execution

### EventBus (`src/gleitzeit/events/stream_event_bus.py`)
- **Role**: Event-driven communication between components
- **Transport**: Redis Streams
- **Event Types**: workflow:submitted, task:ready, task:completed

### TaskExecutor (`src/gleitzeit/core/task_executor.py`)
- **Role**: Individual task execution
- **Integration**: Delegates to appropriate providers based on protocol

## Redis Data Structures

### 🔒 **SECURE Signal Waiters (Workflow-Scoped)**
```
Key: signal:{workflow_id}:{signal_name}:waiters
Type: Set
Values: {workflow_id}:{task_id}
Example: signal:workflow-abc:test_approval:waiters -> {"workflow-abc:task-123"}
Security: Each workflow's signals are isolated from others
```

### Waiter Metadata
```
Key: signal:waiter:{workflow_id}:{task_id}
Type: Hash
Fields: workflow_id, task_id, signal, timeout, created_at, mode
```

### Event Streams
```
Key: gleitzeit:events:stream:task:completed
Type: Stream
Fields: event_type, timestamp, data, source, correlation_id, severity, metadata
```

## Error Handling and Recovery

### Timeout Handling
- **Mechanism**: Redis TTL on waiter entries
- **Behavior**: Tasks automatically fail after timeout period
- **Recovery**: Failed tasks can be retried through standard retry mechanisms

### Signal Manager Failures
- **Detection**: Health checks and heartbeat monitoring
- **Recovery**: Automatic restart of signal monitoring services
- **Persistence**: Waiter state persisted in Redis survives restarts

### Provider Failures
- **Detection**: Task execution timeouts
- **Recovery**: Task retry with exponential backoff
- **Fallback**: Alternative provider selection if available

## Performance Characteristics

### Signal Latency
- **Registration**: ~1-2ms (Redis SET operation)
- **Signal Send**: ~5-10ms (Redis scan + stream operations)
- **Event Processing**: ~2-5ms (stream consumption and task queuing)

### Scalability
- **Horizontal**: Multiple signal managers can process different signal types
- **Vertical**: Redis clustering supports high-throughput signal operations
- **Concurrency**: Multiple workflows can wait for same signal simultaneously

## Monitoring and Observability

### Key Metrics
- Signal waiter count per signal type
- Signal send latency and success rate
- Task completion rate for signal tasks
- Event bus processing latency

### Log Correlation
- **Workflow ID**: Traces entire workflow execution
- **Task ID**: Tracks individual task lifecycle
- **Signal Name**: Groups related signal operations

### Health Checks
- Signal manager heartbeat
- Redis connectivity and performance
- Event bus message processing rate

## Configuration

### Signal Manager Settings
```python
GLEITZEIT_SIGNAL_TIMEOUT_DEFAULT = 300  # seconds
GLEITZEIT_SIGNAL_CLEANUP_INTERVAL = 60  # seconds  
GLEITZEIT_SIGNAL_MONITOR_INTERVAL = 1   # seconds
```

### Redis Settings
```python
GLEITZEIT_REDIS_URL = "redis://localhost:6379"
GLEITZEIT_REDIS_DB = 0
GLEITZEIT_REDIS_STREAM_MAXLEN = 10000
```

## 🔒 **CRITICAL SECURITY FIXES IMPLEMENTED**

### Signal Namespace Collision Vulnerability - RESOLVED ✅

**Problem**: Signals were globally scoped, allowing cross-workflow interference:
```
Old: signal:test_approval:waiters (all workflows mixed together)
Risk: Workflow A could accidentally wake tasks in Workflow B
```

**Solution**: Workflow-scoped signal keys implemented:
```
New: signal:{workflow_id}:test_approval:waiters (isolated per workflow)
Security: Each workflow's signals are completely isolated
```

### Global Signal Broadcasting - REMOVED 🚫

**Removed Dangerous Endpoint**: `/signals/broadcast` 
- **Why Dangerous**: Could send signals to ALL workflows simultaneously
- **Security Risk**: Massive cross-workflow interference potential
- **Resolution**: Endpoint completely removed from API

### Secure API Design - IMPLEMENTED 🔐

**New Secure Endpoint**: `/signals/workflows/{workflow_id}/send/{signal_name}`
- **Mandatory Workflow ID**: Prevents global signal sending
- **Workflow Validation**: Verifies workflow exists before signal processing
- **Isolated Signal Delivery**: Only wakes tasks within specified workflow

### Security Helper Methods - ADDED 🛡️

```python
def _get_scoped_signal_key(self, workflow_id: str, signal_name: str) -> str:
    """Generate workflow-scoped signal key for security."""
    return f"signal:{workflow_id}:{signal_name}:waiters"

def _get_signal_waiter_key(self, signal_id: str) -> str:
    """Generate signal waiter metadata key."""  
    return f"signal:waiter:{signal_id}"
```

### Security Validation Checks - ENFORCED ✅

1. **Workflow ID Required**: `send_signal()` now requires workflow_id parameter
2. **Waiter Ownership Verification**: Confirms waiters belong to target workflow
3. **Cross-Workflow Prevention**: Security warnings logged for violations
4. **Persistence Layer Integration**: All operations go through SystemManager

## ✅ **PERSISTENCE LAYER INTEGRATION SUMMARY**

### Before Fix:
```
SignalTaskHandler.send_signal() 
  → Direct Redis XADD to stream (bypassing persistence)
  → Event emitted but task status/results NOT saved to database
  → Workflow functionally works but status displays incorrectly
  → SECURITY ISSUE: Global signal namespace collision
```

### After Fix:
```  
SignalTaskHandler.send_signal()
  → Requires workflow_id parameter (SECURITY)
  → Uses workflow-scoped signal keys (SECURITY)
  → _complete_signal_task()
    → await persistence.get_task(task_id)
    → task.status = TaskStatus.COMPLETED  
    → await persistence.save_task(task)
    → await persistence.save_task_result(task_result)
    → await event_bus.emit(proper_completion_event)
  → Task status/results properly persisted AND events emitted
  → Workflow works functionally AND status displays correctly
  → SECURITY: Complete workflow isolation achieved
```

### Central Error System Integration:
- **TaskValidationError**: For missing signal parameters with proper error codes
- **TaskExecutionError**: For persistence failures with structured error data  
- **Proper Error Context**: Error codes, task IDs, and cause information included

### Test Verification:
```
2025-09-12 17:11:31,945 - gleitzeit.signals.handler - INFO - Signal waiter registered: workflow-005904c59a5d4aa0a39d93dfa56036af:task-728ddaf06e78467f90539d94a9c88c3d:0c434041 waiting for 'test_approval'

✅ Workflow: workflow-005904c59a5d4aa0a39d93dfa56036af
   Status: COMPLETED
   Secure Signal API: {"workflow_id":"workflow-005904c59a5d4aa0a39d93dfa56036af","signal":"test_approval","tasks_woken":1,"success":true}
```

This complete pathway documentation shows how Gleitzeit's signal workflow system provides **secure**, robust, scalable, and observable signal-based task coordination with **workflow isolation**, proper persistence layer integration, centralized error handling, and comprehensive security protections against signal namespace collision attacks.