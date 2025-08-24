# Architecture Fix: Centralized Event Emission

## Decision: Events ONLY from Execution Engine

### Principles
1. **Execution Engine** is the sole source of task/workflow events
2. **Persistence Adapters** only save/retrieve data, never emit events
3. **Event Handlers** update persistence based on events
4. **Clear Flow**: Execute → Emit Event → Handle Event → Persist

### Implementation Steps

#### Step 1: Remove Event Emission from Persistence Adapters
- [ ] Remove all event emission from `unified_redis_events.py`
- [ ] Remove all event emission from `unified_sqlalchemy_events.py`
- [ ] Remove all event emission from `unified_memory_events.py`
- [ ] Keep only data operations in persistence adapters

#### Step 2: Fix Execution Engine Event Flow
```python
# Correct flow in execution_engine.py
async def _execute_task(self, task: Task):
    # 1. Execute task
    result = await self._route_task_to_provider(task, params)
    
    # 2. Update task object
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    
    # 3. Save to persistence DIRECTLY (no events)
    await self.persistence.save_task(task)
    await self.persistence.save_task_result(result)
    
    # 4. Emit event ONCE
    event = create_task_completed_event(...)
    await self.event_bus.emit(event)
    
    # 5. Let handlers do additional work (queue updates, etc)
```

#### Step 3: Simplify Event Handlers
- `PersistenceTaskHandler` - Remove, no longer needed
- `TaskCompletedHandler` - Only handles queue/dependency updates
- `WorkflowCompletedHandler` - Only handles workflow completion

#### Step 4: Fix the Flow
```
Current (Broken) Flow:
ExecutionEngine → emit(TASK_COMPLETED) → PersistenceHandler → save_task() → emit(TASK_COMPLETED) → Loop!

New (Clean) Flow:
ExecutionEngine → save_task() → emit(TASK_COMPLETED) → QueueHandler → update_queue()
```

### Benefits
1. **No Event Storms** - Each event emitted exactly once
2. **No Race Conditions** - Clear sequential flow
3. **Backend Agnostic** - Works the same for Redis, SQL, Memory
4. **Testable** - Can test each component independently
5. **Maintainable** - Clear responsibilities

### Migration Path
1. **Phase 1**: Add feature flag to disable persistence adapter events
2. **Phase 2**: Update execution engine to save before emitting
3. **Phase 3**: Remove event emission from persistence adapters
4. **Phase 4**: Clean up redundant event handlers

### Code Changes Required

#### execution_engine.py
```python
async def _execute_task(self, task: Task):
    try:
        # Execute
        provider_result = await self._route_task_to_provider(task, params)
        
        # Create result
        task_result = TaskResult(
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            result=provider_result,
            ...
        )
        
        # Update task
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        
        # SAVE FIRST (no events from persistence)
        await self.persistence.save_task(task)
        await self.persistence.save_task_result(task_result)
        
        # THEN EMIT EVENT (single source)
        if self.event_bus:
            event = create_task_completed_event(...)
            await self.event_bus.emit(event)
        
        # Queue/workflow updates happen via event handlers
        
    except Exception as e:
        # Similar pattern for failures
        task.status = TaskStatus.FAILED
        await self.persistence.save_task(task)
        
        if self.event_bus:
            event = create_task_failed_event(...)
            await self.event_bus.emit(event)
```

#### persistence/unified_redis.py (not events version)
```python
async def save_task(self, task: Task) -> None:
    """Just save the task, no events"""
    # Only Redis operations, no event emission
    task_data = self._serialize_task(task)
    await self.redis.hset(task_key, mapping=task_data)
    # That's it! No events!
```

#### client.py
```python
async def _init_native_client(self):
    # Create event bus
    event_bus = EventBus()
    
    # Create persistence WITHOUT event bus
    # (adapters don't need it anymore)
    self._persistence_adapter = await PersistenceFactory.create(
        **factory_kwargs
        # NO event_bus parameter
    )
    
    # Register only necessary handlers
    # Remove PersistenceTaskHandler - not needed!
    
    # Queue handler for dependency resolution
    queue_handler = TaskQueueHandler(queue_manager)
    event_bus.register(EventType.TASK_COMPLETED, queue_handler)
    
    # Workflow handler for completion
    workflow_handler = WorkflowCompletionHandler(persistence)
    event_bus.register(EventType.TASK_COMPLETED, workflow_handler)
```

### Testing Strategy
1. **Unit Tests**: Test execution engine emits correct events
2. **Integration Tests**: Test full flow with different backends
3. **Load Tests**: Verify no event storms under load
4. **Regression Tests**: Ensure existing workflows still work

### Rollback Plan
If issues arise:
1. Re-enable persistence adapter events via feature flag
2. Revert execution engine changes
3. Investigate specific failure patterns
4. Iterate on solution

### Success Metrics
- [ ] All tasks complete successfully with all backends
- [ ] No "stuck" tasks in executing state
- [ ] No duplicate events in logs
- [ ] No race condition warnings
- [ ] Performance improvement (fewer events = faster)

### Timeline
- Day 1: Remove event emission from persistence adapters
- Day 2: Update execution engine flow
- Day 3: Clean up event handlers
- Day 4: Testing and validation
- Day 5: Documentation and deployment