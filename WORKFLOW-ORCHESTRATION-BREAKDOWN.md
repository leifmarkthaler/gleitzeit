# Why Workflow Orchestration Broke with Event Bus
Generated: 2025-09-16

## The Core Architecture Problem

### Original Design (Working)
The workflow system had clear separation of responsibilities:

1. **WorkflowManager** - High-level workflow coordination
2. **TaskOrchestrator** - Task execution and dependency management
3. **TaskExecutor** - Individual task execution

The key was that **TaskOrchestrator** handled task progression directly in a synchronous manner.

### What Changed (Broken)
The system moved to an event-driven architecture where:
- Task completion triggers events
- Events are supposed to trigger next task scheduling
- Multiple components compete to update status

## The Critical Breakage Point

### OLD TaskOrchestrator (Working)
```python
async def _handle_task_completed(self, event):
    # Get task and workflow
    task = await self.persistence.get_task(task_id)
    if task and task.workflow_id:
        # DIRECTLY CHECK FOR WORKFLOW PROGRESSION
        await self._check_workflow_progression(task.workflow_id)

async def _check_workflow_progression(self, workflow_id):
    # Get workflow
    workflow = await self.persistence.get_workflow(workflow_id)

    # Check all tasks, find ready ones
    for task in workflow.tasks:
        if task.status == PENDING and dependencies_satisfied(task):
            # DIRECTLY ENQUEUE NEXT TASKS
            await self.queue_manager.enqueue_task(task)
```

### NEW StatelessTaskOrchestrator (Broken)
```python
async def _handle_task_completed(self, event):
    # Check for newly ready tasks
    if self.dependency_manager:
        # CALLS NON-EXISTENT METHOD!
        newly_ready = await self.dependency_manager.get_dependent_tasks(task_id)

        for dependent_task_id in newly_ready:
            task = await self.persistence.get_task(dependent_task_id)
            if task:
                ready = await self.dependency_manager.check_dependencies(task)
                if ready:
                    await self.queue_manager.enqueue_task(task)
```

## The Multiple Problems

### Problem 1: Missing Method
The new orchestrator calls `dependency_manager.get_dependent_tasks()` which doesn't exist. This breaks the entire task progression chain.

### Problem 2: Status Management Chaos
With the event-driven system, status updates happen in multiple places:

1. **TaskQueue** - Sets PENDING, QUEUED, EXECUTING
2. **TaskExecutor** - Should set EXECUTING, tries to transition to COMPLETED
3. **Event Handlers** - Try to set statuses based on events
4. **StatelessDependencyManager** - Also sets statuses
5. **Multiple persistence layers** - Each trying to update status

### Problem 3: Race Conditions
The asynchronous event system creates timing issues:
- Task completes before EXECUTING status is set
- Events arrive out of order
- Multiple handlers try to update the same task

### Problem 4: Lost Synchronous Control
The old system had direct control flow:
```
Task Completes → Check Dependencies → Enqueue Next Tasks
```

The new system relies on events:
```
Task Completes → Emit Event → ??? → Event Handler → Check Dependencies → ???
```

## Why It Worked Before

The original TaskOrchestrator:
1. **Directly managed task progression** - No reliance on events
2. **Had _check_workflow_progression** - Comprehensive dependency checking
3. **Synchronously updated status** - Status set BEFORE execution
4. **Single responsibility** - One component managed orchestration

## Why It's Broken Now

The StatelessTaskOrchestrator:
1. **Relies on broken dependency_manager method** - Core functionality missing
2. **No workflow progression logic** - Removed _check_workflow_progression
3. **Asynchronous status updates** - Creates race conditions
4. **Distributed responsibility** - Multiple components fighting over status

## The Solution Path

### Immediate Fix Needed
1. **Implement get_dependent_tasks()** in UnifiedDependencyManager
2. **Ensure EXECUTING status is set BEFORE task execution**
3. **Remove duplicate status updates from multiple components**

### Architectural Fix Needed
1. **Return to synchronous status management** in TaskExecutor
2. **Centralize task progression logic** in one component
3. **Use events for monitoring only**, not for core workflow logic
4. **Restore _check_workflow_progression** functionality

## Key Insight

The move to event-driven architecture broke the fundamental workflow progression mechanism. The system went from:
- **Direct, synchronous task chaining** (worked)
- To **Event-based, asynchronous hoping** (broken)

The event bus should be used for monitoring and coordination, not as the primary mechanism for task progression. Core workflow logic needs to be deterministic and synchronous.