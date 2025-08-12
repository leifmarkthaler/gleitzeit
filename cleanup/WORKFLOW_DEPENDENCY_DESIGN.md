# Workflow & Dependency Resolution Design Analysis

## Current Architecture Overview

### Core Components

1. **ExecutionEngine** (`execution_engine.py`)
   - Primary orchestrator for workflow execution
   - Manages task submission and execution
   - Triggers dependency checks after task completion
   - Maintains dual state tracking (internal `task_results` + persistence)

2. **DependencyResolver** (`dependency_resolver.py`)
   - Builds and analyzes dependency graphs
   - Detects circular dependencies
   - Calculates execution order (topological sort)
   - Suggests missing dependencies from parameter references

3. **Workflow Model** (`models.py`)
   - Contains task list with dependency relationships
   - Tracks completed/failed tasks
   - Provides basic dependency satisfaction checks

4. **Event System** (`events.py`)
   - Emits task completion/failure events
   - Enables reactive dependency processing

### Current Dependency Resolution Flow

```
Task Completes → _check_workflow_completion() → Check Persistence & Memory
                                               → Find Ready Tasks
                                               → Submit to Queue
                                               → Event Emission
```

### Strengths of Current Design

1. **Event-Driven Architecture**: Naturally reactive to task completions
2. **Dual State Tracking**: Checks both memory and persistence for resilience
3. **Separation of Concerns**: DependencyResolver handles graph analysis separately
4. **Parameter Substitution**: Supports dynamic ${task.id.result} references
5. **Circular Dependency Detection**: Prevents infinite loops at submission time

### Identified Weaknesses & Failure Points

#### 1. Race Conditions
- **Problem**: Multiple tasks completing simultaneously might trigger redundant dependency checks
- **Impact**: Tasks could be submitted multiple times to the queue

#### 2. State Inconsistency
- **Problem**: Memory state (`task_results`) and persistence can diverge
- **Impact**: Dependency checks might miss completed tasks or double-submit

#### 3. Lost Events
- **Problem**: If workflow completion check fails, dependent tasks never get submitted
- **Impact**: Workflow hangs with ready tasks never executing

#### 4. No Retry for Dependency Resolution
- **Problem**: If dependency check or task submission fails, there's no retry mechanism
- **Impact**: Transient failures can permanently break workflow progression

#### 5. Limited Failure Handling
- **Problem**: When a task fails, dependent tasks become permanently blocked
- **Impact**: No way to handle partial failures or alternative paths

#### 6. Missing Workflow State Persistence
- **Problem**: `workflow_states` dict is only in memory
- **Impact**: System restart loses all workflow tracking

## Proposed Improvements (Event-Based Architecture)

### 1. Idempotent Dependency Resolution

```python
class DependencyResolutionTracker:
    """Track which tasks have been submitted to prevent duplicates"""
    
    def __init__(self):
        self.submitted_tasks: Set[str] = set()
        self.resolution_attempts: Dict[str, int] = {}
        self.lock = asyncio.Lock()
    
    async def mark_submitted(self, task_id: str) -> bool:
        """Returns True if task was newly submitted, False if already submitted"""
        async with self.lock:
            if task_id in self.submitted_tasks:
                return False
            self.submitted_tasks.add(task_id)
            return True
    
    async def should_retry_resolution(self, workflow_id: str) -> bool:
        """Check if we should retry dependency resolution for a workflow"""
        attempts = self.resolution_attempts.get(workflow_id, 0)
        return attempts < 3  # Max 3 attempts
```

### 2. Event-Driven Dependency Monitor

```python
class DependencyMonitor:
    """Separate service that monitors task events and triggers dependency checks"""
    
    async def start(self):
        """Subscribe to task events and trigger dependency resolution"""
        await self.event_bus.subscribe(EventType.TASK_COMPLETED, self.handle_task_completed)
        await self.event_bus.subscribe(EventType.TASK_FAILED, self.handle_task_failed)
        
        # Periodic reconciliation for missed events
        asyncio.create_task(self.periodic_reconciliation())
    
    async def handle_task_completed(self, event: GleitzeitEvent):
        """React to task completion by scheduling dependency check"""
        task_id = event.data.get("task_id")
        workflow_id = event.data.get("workflow_id")
        
        if workflow_id:
            # Schedule with deduplication and delay to batch multiple completions
            await self.schedule_dependency_check(workflow_id, delay=0.5)
    
    async def periodic_reconciliation(self):
        """Periodically check for stuck workflows"""
        while True:
            await asyncio.sleep(30)  # Every 30 seconds
            
            # Find workflows with ready but unsubmitted tasks
            stuck_workflows = await self.find_stuck_workflows()
            for workflow_id in stuck_workflows:
                await self.trigger_dependency_resolution(workflow_id)
```

### 3. Workflow State Persistence

```python
class WorkflowStatePersistence:
    """Persist workflow states for recovery"""
    
    async def save_workflow_state(self, workflow_id: str, state: WorkflowState):
        """Save workflow state to persistence"""
        await self.persistence.save(f"workflow_state:{workflow_id}", {
            "status": state.status,
            "completed_tasks": list(state.completed_tasks),
            "failed_tasks": list(state.failed_tasks),
            "submitted_tasks": list(state.submitted_tasks),
            "last_check": state.last_dependency_check,
            "retry_count": state.retry_count
        })
    
    async def recover_workflow_states(self) -> Dict[str, WorkflowState]:
        """Recover all workflow states after restart"""
        states = {}
        for key in await self.persistence.scan("workflow_state:*"):
            workflow_id = key.split(":", 1)[1]
            state_data = await self.persistence.get(key)
            states[workflow_id] = WorkflowState(**state_data)
        return states
```

### 4. Dependency Resolution with Retry & Circuit Breaker

```python
class ResilientDependencyResolver:
    """Enhanced dependency resolver with retry and circuit breaker"""
    
    async def resolve_dependencies(self, workflow_id: str) -> List[Task]:
        """Resolve dependencies with retry logic"""
        
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(TransientError)
        )
        async def _resolve():
            # Check circuit breaker
            if self.circuit_breaker.is_open(workflow_id):
                raise CircuitOpenError(f"Circuit breaker open for {workflow_id}")
            
            try:
                # Get completed tasks from both sources
                completed = await self.get_completed_tasks(workflow_id)
                
                # Find ready tasks
                ready_tasks = await self.find_ready_tasks(workflow_id, completed)
                
                # Mark successful resolution
                self.circuit_breaker.record_success(workflow_id)
                
                return ready_tasks
                
            except Exception as e:
                self.circuit_breaker.record_failure(workflow_id)
                raise
        
        return await _resolve()
```

### 5. Failed Task Recovery Strategy

```python
class FailureRecoveryStrategy:
    """Handle task failures with configurable strategies"""
    
    async def handle_task_failure(self, task: Task, error: str):
        """Determine how to handle a failed task"""
        
        strategy = task.metadata.get("failure_strategy", "block")
        
        if strategy == "skip":
            # Mark as completed with error flag, allow dependents to proceed
            await self.mark_as_skipped(task)
            await self.emit_event(EventType.TASK_SKIPPED, task)
            
        elif strategy == "alternative":
            # Submit alternative task if defined
            alt_task_id = task.metadata.get("alternative_task")
            if alt_task_id:
                await self.submit_alternative(alt_task_id)
                
        elif strategy == "compensate":
            # Run compensation task to undo previous work
            comp_task = task.metadata.get("compensation_task")
            if comp_task:
                await self.submit_compensation(comp_task)
                
        else:  # "block" - default
            # Block dependent tasks (current behavior)
            pass
```

### 6. Enhanced Event Flow with Guarantees

```python
class GuaranteedEventProcessor:
    """Process events with at-least-once delivery guarantee"""
    
    async def process_task_event(self, event: GleitzeitEvent):
        """Process task event with acknowledgment"""
        
        event_id = event.id
        
        # Check if already processed (idempotency)
        if await self.is_processed(event_id):
            return
        
        try:
            # Process the event
            if event.event_type == EventType.TASK_COMPLETED:
                await self.handle_task_completion(event)
            elif event.event_type == EventType.TASK_FAILED:
                await self.handle_task_failure(event)
            
            # Mark as processed
            await self.mark_processed(event_id)
            
            # Acknowledge event
            await self.acknowledge_event(event_id)
            
        except Exception as e:
            # Event will be redelivered
            logger.error(f"Failed to process event {event_id}: {e}")
            raise
```

### 7. Workflow Checkpointing

```python
class WorkflowCheckpoint:
    """Create restorable checkpoints for workflows"""
    
    async def create_checkpoint(self, workflow_id: str):
        """Create a checkpoint of current workflow state"""
        
        checkpoint = {
            "timestamp": datetime.utcnow(),
            "workflow_id": workflow_id,
            "completed_tasks": await self.get_completed_tasks(workflow_id),
            "task_results": await self.get_task_results(workflow_id),
            "workflow_state": await self.get_workflow_state(workflow_id)
        }
        
        checkpoint_id = f"checkpoint:{workflow_id}:{checkpoint['timestamp'].timestamp()}"
        await self.persistence.save(checkpoint_id, checkpoint)
        
        return checkpoint_id
    
    async def restore_from_checkpoint(self, checkpoint_id: str):
        """Restore workflow to a previous checkpoint"""
        checkpoint = await self.persistence.get(checkpoint_id)
        
        # Restore state
        await self.restore_workflow_state(checkpoint["workflow_state"])
        await self.restore_task_results(checkpoint["task_results"])
        
        # Re-trigger dependency resolution
        await self.trigger_resolution(checkpoint["workflow_id"])
```

## Implementation Priority

### Phase 1: Core Resilience (High Priority)
1. **Idempotent Task Submission** - Prevent duplicate task submissions
2. **Workflow State Persistence** - Survive system restarts
3. **Event Deduplication** - Handle duplicate events gracefully

### Phase 2: Recovery Mechanisms (Medium Priority)
1. **Periodic Reconciliation** - Detect and fix stuck workflows
2. **Retry Logic for Resolution** - Handle transient failures
3. **Circuit Breaker** - Prevent cascade failures

### Phase 3: Advanced Features (Lower Priority)
1. **Alternative Task Paths** - Handle failures gracefully
2. **Workflow Checkpointing** - Enable rollback/recovery
3. **Compensation Tasks** - Undo failed operations

## Testing Strategy

### 1. Chaos Engineering Tests
```python
async def test_random_task_failures():
    """Randomly fail tasks to test recovery"""
    
async def test_event_loss():
    """Simulate lost events to test reconciliation"""
    
async def test_concurrent_completions():
    """Complete multiple tasks simultaneously"""
```

### 2. State Consistency Tests
```python
async def test_persistence_memory_sync():
    """Verify state consistency between memory and persistence"""
    
async def test_restart_recovery():
    """Test workflow recovery after system restart"""
```

### 3. Performance Tests
```python
async def test_large_dependency_graph():
    """Test with 1000+ tasks with complex dependencies"""
    
async def test_high_concurrency():
    """Test with 100+ concurrent workflows"""
```

## Monitoring & Observability

### Key Metrics
1. **Dependency Resolution Latency** - Time from task completion to dependent submission
2. **Stuck Workflow Count** - Workflows with ready but unsubmitted tasks
3. **Resolution Retry Rate** - Frequency of resolution retries
4. **Event Processing Lag** - Time between event emission and processing

### Health Checks
1. **Workflow Progress Check** - Alert if workflow doesn't progress for X minutes
2. **Event Queue Depth** - Alert if events backing up
3. **State Consistency Check** - Periodic validation of memory vs persistence

## Conclusion

The current design provides a solid foundation with its event-driven architecture and separation of concerns. The proposed improvements focus on:

1. **Resilience**: Handle failures gracefully without manual intervention
2. **Consistency**: Ensure state consistency across components
3. **Observability**: Know when things go wrong
4. **Recovery**: Automatic recovery from failure scenarios

These improvements maintain the event-based architecture while adding layers of reliability and fault tolerance that are essential for production systems.