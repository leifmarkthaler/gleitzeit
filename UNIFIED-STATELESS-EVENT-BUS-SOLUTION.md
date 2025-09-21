# Unified Stateless Event Bus Solution
Generated: 2025-09-16

## Goal
Create a single, unified stateless event bus flow without separate event paths or competing architectures.

## Current Problems

### 1. Multiple Event Bus Implementations
- **EventBus** (wrapper) → delegates to StatelessEventBus
- **StatelessEventBus** → direct handler execution (no streams)
- **StatelessEventBusAdapter** → writes to Redis streams (unused)
- **RedisPubSubBus** → pub/sub pattern (legacy)
- **StreamEventBus** → alias for StatelessEventBusAdapter

### 2. No Event Bus Connected
- WorkflowManager created with `event_bus=None`
- TaskExecutor can't emit events
- No task progression triggering

### 3. Mixed Execution Patterns
- Direct handler execution (StatelessEventBus)
- Stream-based consumption (StatelessEventBusAdapter)
- Two parallel architectures that don't work together

## Proposed Solution: Single Stateless Flow

### Architecture Principles
1. **One EventBus class** - Single entry point
2. **Stateless handlers only** - No in-memory state
3. **Direct execution** - No streams, no polling
4. **Redis for coordination** - Handler registry only

### Implementation Plan

#### Step 1: Fix Dependencies.py
```python
# In /src/gleitzeit/api/dependencies.py
async def get_workflow_manager(client: GleitzeitClient = Depends(get_client)):
    # ... existing code ...

    # Create EventBus (which uses StatelessEventBus internally)
    from gleitzeit.events import EventBus
    event_bus = EventBus(persistence=persistence)

    workflow_manager = await WorkflowManagerFactory.create(
        persistence=persistence,
        event_bus=event_bus,  # Now connected!
        execution_engine=None,
        dependency_resolver=None
    )
```

#### Step 2: Register Task Progression Handler
The StatelessEventBus needs a handler registered for TASK_COMPLETED events:

```python
# In WorkflowManager or StatelessTaskOrchestrator initialization
async def setup_event_handlers(self):
    """Register handlers for task progression."""
    await self.event_bus.register_handler(
        EventType.TASK_COMPLETED,
        self._handle_task_completed,
        priority=1
    )
```

#### Step 3: Fix Task Progression Logic
```python
# In StatelessTaskOrchestrator
async def _handle_task_completed(self, event: GleitzeitEvent):
    """Handle task completion and trigger next tasks."""
    task_id = event.data.get('task_id')
    workflow_id = event.data.get('workflow_id')

    if not workflow_id:
        return

    # Get workflow to check for next tasks
    workflow = await self.persistence.get_workflow(workflow_id)
    if not workflow:
        return

    # Find tasks that depend on the completed task
    for task in workflow.tasks:
        if task.status == TaskStatus.PENDING:
            # Check if all dependencies are satisfied
            if await self._check_dependencies_met(task, workflow):
                # Queue the task for execution
                await self.queue_manager.enqueue_task(task)

                # Update status to QUEUED
                task.status = TaskStatus.QUEUED
                await self.persistence.save_task(task)
```

#### Step 4: Implement Missing Method
```python
# In UnifiedDependencyManager
async def get_dependent_tasks(self, task_id: str) -> List[str]:
    """Get tasks that depend on the given task."""
    # This was called but didn't exist
    workflow_id = await self._get_workflow_id_for_task(task_id)
    if not workflow_id:
        return []

    workflow = await self.persistence.get_workflow(workflow_id)
    dependent_tasks = []

    for task in workflow.tasks:
        if task_id in task.dependencies:
            dependent_tasks.append(task.id)

    return dependent_tasks
```

## Why This Works

### Single Path Benefits
1. **No competing systems** - One event flow only
2. **Synchronous handlers** - Direct execution, no delays
3. **Stateless operation** - Handlers fetch fresh state from Redis
4. **No polling loops** - Event-driven progression

### How Events Flow
```
Task Completes
    ↓
TaskExecutor.emit(TASK_COMPLETED)
    ↓
EventBus.emit() → StatelessEventBus.emit()
    ↓
Load handlers from Redis
    ↓
Execute handlers directly (including task progression)
    ↓
Next task queued
```

## What We DON'T Need

### Remove/Ignore These Components
1. **StatelessEventBusAdapter** - Don't use streams
2. **StreamEventScheduler** - No stream processing needed
3. **StatelessEventConsumer** - No consumption loops
4. **Stream infrastructure** - Keep it simple

### Why Not Streams?
- **Complexity** - Consumer groups, acknowledgments, etc.
- **Latency** - Extra hop through Redis streams
- **Debugging** - Harder to trace event flow
- **Not needed** - Direct execution works fine for task progression

## Migration Steps

### Phase 1: Connect Event Bus (Immediate)
1. Update dependencies.py to create EventBus
2. Pass it to WorkflowManagerFactory
3. Verify events are being emitted

### Phase 2: Fix Task Progression (Next)
1. Implement get_dependent_tasks() method
2. Fix _handle_task_completed logic
3. Ensure handlers are registered

### Phase 3: Clean Up Status Management
1. Set EXECUTING before task runs
2. Remove duplicate status setters
3. Fix atomic transitions

### Phase 4: Remove Unused Code (Later)
1. Remove StatelessEventBusAdapter
2. Remove stream consumer code
3. Simplify event system

## Expected Outcome

After implementation:
1. **Tasks progress automatically** via events
2. **Single event flow** through StatelessEventBus
3. **No polling loops** needed
4. **Simpler architecture** to maintain

## Key Insight

The system already has EventBus → StatelessEventBus delegation working. We just need to:
1. **Connect it** (pass event_bus to WorkflowManager)
2. **Register handlers** (for task progression)
3. **Fix the logic** (implement missing methods)

No need for complex stream architectures when direct handler execution works perfectly for this use case.