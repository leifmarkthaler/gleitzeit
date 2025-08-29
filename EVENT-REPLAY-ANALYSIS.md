# Event Replay Capability Analysis

## Current State: LIMITED REPLAY

The event persistence system currently captures event metadata but **not** the full workflow/task definitions needed for complete replay.

## What's Currently Captured

### Event Types and Data

1. **workflow:submitted**
   - workflow_id
   - workflow_name  
   - total_tasks
   - status
   - ❌ **Missing: Full workflow definition with tasks**

2. **task:submitted**
   - task_id
   - task_name
   - protocol
   - method
   - status
   - priority
   - ❌ **Missing: Task parameters, dependencies, handler**

3. **task:completed/failed**
   - task_id
   - status
   - error_message (if failed)
   - duration
   - ❌ **Missing: Actual result data**

4. **log:message**
   - Detailed execution logs
   - ✅ Good for debugging/audit trail

## Replay Capabilities

### ✅ What CAN be replayed:
- **Event sequence** - The order of operations
- **Timeline reconstruction** - When things happened
- **Status transitions** - How workflow/tasks progressed
- **Error analysis** - What failed and why
- **Performance metrics** - Durations and timings

### ❌ What CANNOT be replayed:
- **Full workflow re-execution** - Missing task definitions and parameters
- **Result reproduction** - Missing actual result data
- **Dependency resolution** - Missing task dependency information
- **State restoration** - Missing intermediate state data

## Replay Use Cases

### 1. Audit Trail (✅ SUPPORTED)
```python
# Can reconstruct what happened
events = await client.get_events(workflow_id="wf_123")
for event in events:
    print(f"{event['timestamp']}: {event['event_type']} - {event['data']}")
```

### 2. Debugging (✅ SUPPORTED)
```python
# Can analyze failures
failed_events = [e for e in events if 'failed' in e['event_type']]
for event in failed_events:
    print(f"Failed: {event['data']['error_message']}")
```

### 3. Performance Analysis (✅ SUPPORTED)
```python
# Can measure execution times
start = next(e for e in events if e['event_type'] == 'workflow:submitted')
end = next(e for e in events if e['event_type'] == 'workflow:completed')
duration = end['timestamp'] - start['timestamp']
```

### 4. Workflow Re-execution (❌ NOT SUPPORTED)
```python
# CANNOT reconstruct and re-run workflow
# Would need full workflow definition in events
```

### 5. State Restoration (❌ NOT SUPPORTED)
```python
# CANNOT restore to a previous state
# Would need complete state snapshots
```

## How to Enable Full Replay

To enable full replay capability, we would need to:

### Option 1: Enhanced Event Data Capture
Modify event creation to include full definitions:

```python
# In execution_engine.py
workflow_data = WorkflowEventData(
    workflow_id=workflow.id,
    workflow_name=workflow.name,
    total_tasks=len(workflow.tasks),
    status=WorkflowStatus.PENDING,
    # Add these:
    workflow_definition=workflow.to_dict(),  # Full workflow
    tasks=[task.to_dict() for task in workflow.tasks]  # All tasks
)
```

### Option 2: Event Sourcing Pattern
Implement proper event sourcing:

```python
class WorkflowAggregate:
    def __init__(self):
        self.events = []
    
    def apply_event(self, event):
        # Rebuild state from event
        if event.type == "workflow:created":
            self.workflow = Workflow.from_dict(event.data)
        elif event.type == "task:completed":
            self.results[event.task_id] = event.result
    
    def replay_from_events(self, events):
        for event in events:
            self.apply_event(event)
        return self.get_current_state()
```

### Option 3: Snapshot + Events
Combine snapshots with events:

```python
# Periodically save full state snapshots
async def save_snapshot(workflow_id):
    snapshot = {
        'workflow': workflow.to_dict(),
        'tasks': [t.to_dict() for t in tasks],
        'results': current_results,
        'timestamp': datetime.now()
    }
    await persistence.save_snapshot(workflow_id, snapshot)

# Replay from nearest snapshot + events
async def replay(workflow_id, target_time):
    snapshot = await get_nearest_snapshot(workflow_id, target_time)
    events = await get_events_after(snapshot['timestamp'])
    state = restore_from_snapshot(snapshot)
    return apply_events_to_state(state, events)
```

## Current Limitations

1. **Storage Size**: Full definitions would increase event size significantly
2. **Performance**: Larger events = slower queries
3. **Privacy**: Full task parameters might contain sensitive data
4. **Complexity**: True event sourcing requires significant refactoring

## Recommendations

### For Audit/Debugging (Current Use Case)
✅ **Current implementation is sufficient**
- Events provide good visibility into execution flow
- Error tracking and performance analysis work well
- Log messages provide detailed context

### For Workflow Re-execution (Future Enhancement)
Would need to implement one of:
1. **Quick fix**: Add workflow/task definitions to events (increases storage)
2. **Proper solution**: Implement event sourcing pattern
3. **Hybrid**: Use persistence for definitions, events for execution trail

### For State Machine Replay (Advanced Use Case)
Would require:
- Complete event sourcing implementation
- State reconstruction logic
- Point-in-time recovery capability

## Conclusion

The current event persistence implementation is **good for observability** but **not designed for replay**. It serves well for:
- ✅ Audit trails
- ✅ Debugging
- ✅ Performance monitoring
- ✅ Error analysis

But cannot support:
- ❌ Workflow re-execution from events
- ❌ Point-in-time state restoration
- ❌ True event replay

To enable full replay capability would require enhancing events to include complete workflow/task definitions and results, which is a significant architectural decision with storage and performance implications.