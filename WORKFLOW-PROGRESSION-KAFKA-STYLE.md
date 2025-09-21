# Workflow Progression with Kafka-Style Workers - Complete Code Flow

## Overview

This document traces the complete workflow progression flow with Kafka-style workers, showing exactly how events flow through the system and where each step happens in the code.

## Task Status States

Before diving into the event flow, it's important to understand the task status progression:

| Status | Description | When Set |
|--------|-------------|----------|
| **PENDING** | Task created but not ready to run (waiting for dependencies) | Initial status for ALL tasks |
| **QUEUED** | Task ready to execute (dependencies satisfied) | When deps met or no deps |
| **EXECUTING** | Task currently running | When TaskExecutor starts |
| **COMPLETED** | Task finished successfully | After successful execution |
| **FAILED** | Task failed | After execution error |

## The Complete Event Flow

### Step 1: Workflow Submission

**Entry Point**: User submits workflow via API
```
POST /api/v1/workflows/
```

**Code Path**:
```python
# src/gleitzeit/api/routes/workflows.py:41
async def submit_workflow():
    workflow_id = await system_manager.submit_workflow_authenticated(workflow, session_id)

# src/gleitzeit/system/mixins/stream_auth.py:121
async def submit_workflow_authenticated(self, workflow, session_id):
    validated_workflow = self.workflow_loader.load_workflow_from_dict(workflow_dict)
    return await self.workflow_manager.submit_workflow(validated_workflow)
```

**WorkflowManager Processing**:
```python
# src/gleitzeit/core/workflow_manager.py:142-247
async def submit_workflow(self, workflow: Workflow):
    # Step 1: Validate workflow
    validation_errors = await self.dependency_manager.validate_workflow(workflow)

    # Step 2: Validate provider availability (lines 156-190)
    for task in workflow.tasks:
        is_available = await pooling_adapter.validate_provider_availability(
            protocol=task.protocol,
            method=task.method
        )

    # Step 3: Set initial status (lines 212-213)
    workflow.status = WorkflowStatus.PENDING
    workflow.created_at = datetime.utcnow()

    # Step 4: Persist workflow and tasks (lines 223-232)
    await self.persistence.save_workflow(workflow)
    for task in workflow.tasks:
        task.workflow_id = workflow.id
        task.status = TaskStatus.PENDING  # ← ALL tasks start as PENDING!
        await self.persistence.save_task(task)

    # Step 5: EMIT WORKFLOW_SUBMITTED EVENT (lines 235-247)
    event = GleitzeitEvent(
        event_type=EventType.WORKFLOW_SUBMITTED,
        data={"workflow_event": event_data.to_dict()},
        source="WorkflowManager"
    )
    await self.event_bus.emit(event)  # → Goes to Redis Stream!

    # Step 6: Submit to execution engine (line 257)
    await self.execution_engine.submit_workflow(workflow)
```

### Step 2: Initial Task Scheduling (PENDING → QUEUED for Independent Tasks)

**ExecutionEngine delegates to TaskOrchestrator**:
```python
# src/gleitzeit/core/execution_engine_v2.py:369-401
async def submit_workflow(self, workflow: Workflow):
    # Delegate to orchestrator (line 389)
    await self.task_orchestrator.submit_workflow(workflow)
```

**TaskOrchestrator finds and schedules initial tasks**:
```python
# src/gleitzeit/core/stateless_task_orchestrator.py:363-403
async def submit_workflow(self, workflow):
    # Store workflow (line 375)
    await self.persistence.save_workflow(workflow)

    # Find tasks with no dependencies (lines 382-392)
    for task in workflow.tasks:
        if not task.dependencies:
            # Enqueue task - this will change PENDING → QUEUED!
            await self.queue_manager.enqueue_task(task)

            # EMIT TASK_READY EVENT (lines 398-403)
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_READY,
                data={
                    "task_id": task.id,
                    "workflow_id": task.workflow_id
                }
            ))
```

**QueueManager.enqueue_task() transitions status**:
```python
# src/gleitzeit/task_queue/task_queue.py:110-136
async def enqueue_task(self, task: Task):
    # Check dependencies (lines 120-132)
    if task.dependencies:
        if not await self._are_dependencies_satisfied(task):
            # Dependencies not satisfied, keep as PENDING
            task.status = TaskStatus.PENDING
            await self.persistence.save_task(task)
            return  # Don't queue yet!

    # No dependencies or dependencies satisfied
    # Change status: PENDING → QUEUED (line 135)
    task.status = TaskStatus.QUEUED
    await self.persistence.save_task(task)
```

**Event Goes to Redis Stream**:
```python
# src/gleitzeit/events/streamlined_event_bus.py:49-123
async def emit(self, event: Union[GleitzeitEvent, Dict[str, Any]]) -> str:
    # Build stream key (line 103)
    stream_key = f"gleitzeit:events:stream:{event_type.replace('_', ':').lower()}"
    # For TASK_READY → "gleitzeit:events:stream:task:ready"

    # Ensure consumer group exists (lines 106-117)
    await self.redis.xgroup_create(
        stream_key,
        self.consumer_group,  # "gleitzeit-processors"
        id='0',
        mkstream=True
    )

    # Add to Redis Stream (line 119)
    msg_id = await self.redis.xadd(stream_key, event_data)
    # Event is now in Redis Stream waiting for consumption!
```

### Step 3: Worker Consumes TASK_READY Event (AUTOMATIC!)

**This is the KEY difference - Worker is continuously running**:
```python
# src/gleitzeit/workers/stream_worker.py:42-96
async def _consume_loop(self):
    """Main consumption loop - this is the KEY addition!"""
    streams = {
        "gleitzeit:events:stream:task:ready": ">",
        "gleitzeit:events:stream:task:completed": ">",
        # ... other streams
    }

    while self._running:
        # THIS BLOCKS UNTIL EVENTS ARRIVE! (lines 59-66)
        messages = await self.redis.xreadgroup(
            self.consumer_group,    # "gleitzeit-processors"
            self.worker_id,         # "worker-0"
            streams,
            count=10,
            block=5000  # ← THE MAGIC! Blocks for 5 seconds or until message arrives
        )

        if messages:
            # Process immediately! (line 70)
            await self._process_messages(messages)

async def _process_messages(self, messages):
    for stream_key, stream_messages in messages.items():
        for msg_id, data in stream_messages:
            # Decode event type (line 79)
            event_type = data.get(b'event_type', b'').decode()

            # Get registered handlers (lines 82-83)
            normalized_type = event_type.lower().replace('_', ':')
            handlers = self.event_bus._handlers.get(normalized_type, [])

            # Call handlers! (lines 92-96)
            for handler in handlers:
                await handler(event)  # ← This triggers the handler!

            # ACK the message (line 99)
            await self.redis.xack(stream_key, self.consumer_group, msg_id)
```

### Step 4: TASK_READY Handler Executes Task

**Handler was registered during initialization**:
```python
# src/gleitzeit/core/stateless_task_orchestrator.py:115
self.event_bus.register(EventType.TASK_READY, self._handle_task_ready)
```

**Handler processes the task**:
```python
# src/gleitzeit/core/stateless_task_orchestrator.py:457-484
async def _handle_task_ready(self, event: GleitzeitEvent):
    task_id = event.data.get("task_id")

    # Skip if already processing (lines 466-468)
    if task_id in self._active_tasks:
        return

    # Get task from persistence (lines 472-474)
    task = await self.persistence.get_task(task_id)

    # Skip if already completed (lines 476-478)
    if task.status == TaskStatus.COMPLETED:
        return

    # Process the task! (line 480)
    await self._process_task(task)

# src/gleitzeit/core/stateless_task_orchestrator.py:289-320
async def _process_task(self, task: Task):
    # Check dependencies (lines 305-308)
    ready = await self.dependency_manager.check_dependencies(task)
    if not ready:
        return

    # Execute task with semaphore (lines 311-320)
    async with self._semaphore:
        task_future = asyncio.create_task(self._execute_task(task))
        self._active_tasks[task.id] = task_future
        await task_future

# src/gleitzeit/core/stateless_task_orchestrator.py:322-361
async def _execute_task(self, task: Task):
    # Execute through TaskExecutor (line 329)
    task_result = await self.task_executor.execute_task(task)
    # TaskExecutor handles all status updates and event emission
```

### Step 5: TaskExecutor Executes and Emits TASK_COMPLETED (QUEUED → EXECUTING → COMPLETED)

**TaskExecutor performs the actual execution**:
```python
# src/gleitzeit/core/task_executor.py:103-187
async def execute_task(self, task: Task) -> TaskResult:
    # Update status: QUEUED → EXECUTING (lines 120-123)
    task.status = TaskStatus.EXECUTING
    task.started_at = datetime.utcnow()
    await self.persistence.save_task(task)

    # EMIT TASK_STARTED EVENT (line 126)
    await self._emit_task_started(task)

    # Get provider and execute (lines 129-165)
    provider = await self._get_provider(task.protocol)
    result = await provider.execute(
        method=task.method,
        parameters=task.parameters,
        context={"task_id": task.id, "workflow_id": task.workflow_id}
    )

    # Update task status: EXECUTING → COMPLETED/FAILED (lines 167-180)
    if result.success:
        task.status = TaskStatus.COMPLETED  # ← Final status!
        # EMIT TASK_COMPLETED EVENT (line 184)
        await self._emit_task_completed(task, task_result)
    else:
        task.status = TaskStatus.FAILED  # ← Final status!
        # EMIT TASK_FAILED EVENT (line 187)
        await self._emit_task_failed(task, result.error)

# src/gleitzeit/core/task_executor.py:321-333
async def _emit_task_completed(self, task: Task, result: TaskResult):
    event = create_task_completed_event(
        task_id=task.id,
        workflow_id=task.workflow_id,
        duration=(result.completed_at - result.started_at).total_seconds(),
        source="task_executor"
    )
    await self.event_bus.emit(event)  # → Goes to Redis Stream!
```

### Step 6: Worker Consumes TASK_COMPLETED (AUTOMATIC!)

**Same worker loop gets the TASK_COMPLETED event**:
```python
# src/gleitzeit/workers/stream_worker.py:59-70
# The SAME consumption loop gets the next event!
messages = await self.redis.xreadgroup(
    self.consumer_group,
    self.worker_id,
    {"gleitzeit:events:stream:task:completed": ">"},  # ← Gets this stream too!
    block=5000
)
# Immediately processes TASK_COMPLETED event
```

### Step 7: TASK_COMPLETED Handler Triggers Next Tasks (PENDING → QUEUED for Dependents)

**Handler checks for dependent tasks**:
```python
# src/gleitzeit/core/stateless_task_orchestrator.py:486-524
async def _handle_task_completed(self, event: GleitzeitEvent):
    task_id = event.data.get("task_id")
    workflow_id = event.data.get("workflow_id")

    # Check for newly ready tasks (lines 509-524)
    if self.dependency_manager:
        # Get tasks that depend on this completed task
        newly_ready = await self.dependency_manager.get_dependent_tasks(task_id)

        for dependent_task_id in newly_ready:
            task = await self.persistence.get_task(dependent_task_id)
            # Task is currently PENDING (waiting for dependencies)

            # Check if all dependencies are satisfied
            ready = await self.dependency_manager.check_dependencies(task)
            if ready:
                # Enqueue the newly ready task
                # This will change status: PENDING → QUEUED!
                await self.queue_manager.enqueue_task(task)

                # EMIT TASK_READY FOR NEXT TASK! (lines 520-524)
                await self.event_bus.emit(GleitzeitEvent(
                    event_type=EventType.TASK_READY,
                    data={"task_id": task.id, "workflow_id": task.workflow_id}
                ))
                # This triggers Step 3 again for the next task!
```

### Step 8: Workflow Completion Check

**After each task completes, check if workflow is done**:
```python
# src/gleitzeit/task_queue/task_queue.py:374-425
async def update_workflow_status(self, workflow_id: str):
    # Get all tasks for workflow (line 383)
    tasks = await self.persistence.list_tasks(
        filters={"workflow_id": workflow_id}
    )

    # Count completed and failed tasks (lines 385-392)
    completed_tasks = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
    failed_tasks = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
    total_tasks = len(tasks)

    # Check if all tasks are done (lines 394-399)
    if completed_tasks + failed_tasks == total_tasks:
        workflow = await self.persistence.get_workflow(workflow_id)
        workflow.status = WorkflowStatus.COMPLETED
        workflow.completed_at = datetime.utcnow()

        # Save workflow (line 404)
        await self.persistence.save_workflow(workflow)

        # EMIT WORKFLOW_COMPLETED EVENT (lines 407-424)
        workflow_completed_event = GleitzeitEvent(
            event_type=EventType.WORKFLOW_COMPLETED,
            data={
                "workflow_id": workflow_id,
                "workflow_name": workflow.name,
                "status": workflow.status.value,
                "completed_tasks": completed_tasks,
                "failed_tasks": failed_tasks,
                "task_results": task_results
            },
            source="queue_manager"
        )
        await self.event_bus.emit(workflow_completed_event)
```

### Step 9: Worker Consumes WORKFLOW_COMPLETED (AUTOMATIC!)

**WorkflowManager handles workflow completion**:
```python
# src/gleitzeit/core/workflow_manager.py:772-797
async def _on_workflow_completed(self, event):
    workflow_id = event.data.get('workflow_id')

    # Update workflow status in persistence (lines 778-781)
    workflow = await self.persistence.get_workflow(workflow_id)
    if workflow:
        workflow.status = WorkflowStatus.COMPLETED
        await self.persistence.save_workflow(workflow)

    # Update workflow executions (lines 784-795)
    executions = await self.workflow_persistence.list_workflow_executions(workflow_id=workflow_id)
    for exec in executions:
        if exec['status'] == WorkflowStatus.RUNNING.value:
            await self.workflow_persistence.save_workflow_execution(
                execution_id=exec['execution_id'],
                workflow_id=workflow_id,
                status=WorkflowStatus.COMPLETED.value,
                metadata={'completed_at': datetime.utcnow().isoformat()}
            )
```

## Task Status Transitions Throughout the Flow

Here's how task status changes as it moves through the system:

```
WORKFLOW SUBMITTED
    ↓
All tasks: status = PENDING
    ↓
Tasks with no dependencies:
    enqueue_task() → status = QUEUED
    ↓
Worker processes TASK_READY:
    TaskExecutor.execute_task() → status = EXECUTING
    ↓
Task completes:
    TaskExecutor → status = COMPLETED
    ↓
Dependent tasks:
    enqueue_task() → status changes from PENDING to QUEUED
    ↓
    [Cycle repeats for dependent tasks]
```

### Status Transition Code Locations:

| Transition | Location | Code |
|------------|----------|------|
| Initial → **PENDING** | workflow_manager.py:231 | `task.status = TaskStatus.PENDING` |
| **PENDING** → **QUEUED** | task_queue.py:135 | `task.status = TaskStatus.QUEUED` |
| **QUEUED** → **EXECUTING** | task_executor.py:120 | `task.status = TaskStatus.EXECUTING` |
| **EXECUTING** → **COMPLETED** | task_executor.py:167 | `task.status = TaskStatus.COMPLETED` |
| **EXECUTING** → **FAILED** | task_executor.py:170 | `task.status = TaskStatus.FAILED` |

## Event Flow Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER SUBMITS WORKFLOW                     │
└────────────────────────────┬─────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│ WorkflowManager.submit_workflow()                                │
│ Location: src/gleitzeit/core/workflow_manager.py:142             │
│ Action: Emits WORKFLOW_SUBMITTED → Redis Stream                  │
└────────────────────────────┬─────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│ StatelessTaskOrchestrator.submit_workflow()                      │
│ Location: src/gleitzeit/core/stateless_task_orchestrator.py:363  │
│ Action: Emits TASK_READY for initial tasks → Redis Stream        │
└────────────────────────────┬─────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│ StreamWorker._consume_loop() [CONTINUOUSLY RUNNING!]             │
│ Location: src/gleitzeit/workers/stream_worker.py:42              │
│ Action: BLOCKS waiting, immediately gets TASK_READY              │
└────────────────────────────┬─────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│ StatelessTaskOrchestrator._handle_task_ready()                   │
│ Location: src/gleitzeit/core/stateless_task_orchestrator.py:457  │
│ Action: Calls TaskExecutor.execute_task()                        │
└────────────────────────────┬─────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│ TaskExecutor.execute_task()                                      │
│ Location: src/gleitzeit/core/task_executor.py:103                │
│ Action: Executes task, emits TASK_COMPLETED → Redis Stream       │
└────────────────────────────┬─────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│ StreamWorker._consume_loop() [STILL RUNNING!]                    │
│ Location: src/gleitzeit/workers/stream_worker.py:42              │
│ Action: Immediately gets TASK_COMPLETED                          │
└────────────────────────────┬─────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│ StatelessTaskOrchestrator._handle_task_completed()               │
│ Location: src/gleitzeit/core/stateless_task_orchestrator.py:486  │
│ Action: Checks dependencies, emits TASK_READY for next tasks     │
└────────────────────────────┬─────────────────────────────────────┘
                             ↓
                    [LOOP BACK TO STEP 4 FOR NEXT TASK]
                             ↓
                      [ALL TASKS COMPLETE]
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│ QueueManager.update_workflow_status()                            │
│ Location: src/gleitzeit/task_queue/task_queue.py:374             │
│ Action: Emits WORKFLOW_COMPLETED → Redis Stream                  │
└────────────────────────────┬─────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│ WorkflowManager._on_workflow_completed()                         │
│ Location: src/gleitzeit/core/workflow_manager.py:772             │
│ Action: Updates workflow status to COMPLETED                     │
└─────────────────────────────────────────────────────────────────┘
```

## Key Files and Their Roles

| File | Role | Key Methods |
|------|------|------------|
| **src/gleitzeit/workers/stream_worker.py** | Continuous event consumption | `_consume_loop()` - The magic blocking read |
| **src/gleitzeit/events/streamlined_event_bus.py** | Event emission to Redis | `emit()` - Writes to streams |
| **src/gleitzeit/core/workflow_manager.py** | Workflow lifecycle | `submit_workflow()`, `_on_workflow_completed()` |
| **src/gleitzeit/core/stateless_task_orchestrator.py** | Task orchestration | `_handle_task_ready()`, `_handle_task_completed()` |
| **src/gleitzeit/core/task_executor.py** | Task execution | `execute_task()`, `_emit_task_completed()` |
| **src/gleitzeit/task_queue/task_queue.py** | Queue and workflow status | `update_workflow_status()` |
| **src/gleitzeit/core/dependency_manager.py** | Dependency resolution | `check_dependencies()`, `get_dependent_tasks()` |

## The Magic: Blocking XREADGROUP

The entire system works because of this one line in `StreamWorker`:

```python
messages = await self.redis.xreadgroup(
    group, consumer, streams,
    block=5000  # ← THIS MAKES EVERYTHING AUTOMATIC!
)
```

This blocks waiting for messages, then immediately processes them when they arrive. No polling, no delays, no external triggers needed!

## Comparison: Without vs. With Workers

| Event | Without Workers | With Workers |
|-------|----------------|--------------|
| TASK_READY emitted | ✅ Goes to Redis | ✅ Goes to Redis |
| Event consumed | ❌ Never | ✅ Within milliseconds |
| Task executed | ❌ Never | ✅ Immediately |
| TASK_COMPLETED emitted | ❌ Never | ✅ After execution |
| Next task triggered | ❌ Never | ✅ Automatically |
| Workflow completes | ❌ Never | ✅ When all tasks done |

## Testing the Flow

To see this in action:

```bash
# Terminal 1: Start API
gleitzeit serve

# Terminal 2: Start workers
gleitzeit worker --workers 2

# Terminal 3: Submit workflow
gleitzeit workflow submit test_workflow.yaml

# Watch Terminal 2 - you'll see:
# - Worker consuming TASK_READY
# - Task executing
# - Worker consuming TASK_COMPLETED
# - Next task starting
# - etc...
```

The entire progression is **automatic and immediate** once workers are running!

## Example: Workflow with Dependencies

Let's trace a workflow with 3 tasks where B depends on A, and C depends on B:

```yaml
Workflow: A → B → C
```

### Initial State (After Submission):
- Task A: **PENDING** → **QUEUED** (no dependencies, immediately queued)
- Task B: **PENDING** (waiting for A to complete)
- Task C: **PENDING** (waiting for B to complete)

### Timeline with Status Transitions:

```
T+0ms:   Workflow submitted
         A: PENDING → QUEUED (no dependencies)
         B: PENDING (depends on A)
         C: PENDING (depends on B)

T+1ms:   TASK_READY(A) emitted → Redis Stream

T+2ms:   Worker consumes TASK_READY(A) [AUTOMATIC!]
         Handler: _handle_task_ready()

T+3ms:   Task A starts executing
         A: QUEUED → EXECUTING

T+100ms: Task A completes
         A: EXECUTING → COMPLETED
         TASK_COMPLETED(A) emitted → Redis Stream

T+101ms: Worker consumes TASK_COMPLETED(A) [AUTOMATIC!]
         Handler: _handle_task_completed()

T+102ms: Dependency check for B → all deps satisfied
         B: PENDING → QUEUED (via enqueue_task())
         TASK_READY(B) emitted → Redis Stream

T+103ms: Worker consumes TASK_READY(B) [AUTOMATIC!]
         Handler: _handle_task_ready()

T+104ms: Task B starts executing
         B: QUEUED → EXECUTING

T+200ms: Task B completes
         B: EXECUTING → COMPLETED
         TASK_COMPLETED(B) emitted → Redis Stream

T+201ms: Worker consumes TASK_COMPLETED(B) [AUTOMATIC!]
         Handler: _handle_task_completed()

T+202ms: Dependency check for C → all deps satisfied
         C: PENDING → QUEUED (via enqueue_task())
         TASK_READY(C) emitted → Redis Stream

T+203ms: Worker consumes TASK_READY(C) [AUTOMATIC!]
         Handler: _handle_task_ready()

T+204ms: Task C starts executing
         C: QUEUED → EXECUTING

T+300ms: Task C completes
         C: EXECUTING → COMPLETED
         TASK_COMPLETED(C) emitted → Redis Stream

T+301ms: Worker consumes TASK_COMPLETED(C) [AUTOMATIC!]

T+302ms: All tasks complete check → WORKFLOW_COMPLETED emitted

T+303ms: Worker consumes WORKFLOW_COMPLETED [AUTOMATIC!]

T+304ms: Workflow status → COMPLETED ✅
```

### Key Points:

1. **PENDING is the waiting state** - Tasks stay PENDING until dependencies are met
2. **enqueue_task() transitions PENDING → QUEUED** - Called when dependencies satisfied
3. **Workers only process QUEUED tasks** - PENDING tasks are not eligible for execution
4. **The chain reaction is automatic** - Each completion triggers the next task

Total time: **304ms** (vs. NEVER without workers running!)