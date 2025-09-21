# Workflow Execution Integration - Complete Stateless Solution

## Overview

The Gleitzeit system now has a complete stateless workflow execution pipeline with the following architecture:

```
Client Request → API → NativeAdapter → WorkflowManager → ExecutionEngine
                 ↓                         ↓
             SystemManager        StatelessDependencyManager
                                  (with Atomic Operations)
```

## Key Components

### 1. SystemManager Integration
**Location**: `src/gleitzeit/system/system_manager.py`

The SystemManager now:
- **ALWAYS** creates `StatelessWorkflowManager` (line 780-787)
- **ALWAYS** uses `StatelessDependencyManager` with atomic operations (line 751-753)
- Detects Redis for atomic operations automatically
- Properly initializes and manages the workflow execution pipeline

### 2. Native Adapter Enhancement
**Location**: `src/gleitzeit/client/adapters/native.py`

Enhanced to:
- Accept SystemManager via `set_system_manager()` method
- Use WorkflowManager for actual workflow execution
- Maintain backward compatibility (stores in persistence if no manager available)

Key change:
```python
async def submit_workflow(self, workflow: Workflow):
    # Store in persistence
    await self.persistence.create_workflow(workflow_dict)
    
    # Execute via WorkflowManager if available
    if self.workflow_manager:
        result = await self.workflow_manager.execute_workflow(workflow)
        return {"success": True, "workflow_id": workflow.id, "execution": result}
```

### 3. API Dependencies Update
**Location**: `src/gleitzeit/api/dependencies.py`

The API now:
- Creates and initializes SystemManager on startup
- Passes SystemManager to SharedClientPool
- Connects all clients to the SystemManager for workflow execution
- Properly shuts down SystemManager on API shutdown

### 4. SharedClientPool Integration
**Location**: `src/gleitzeit/api/shared_dependencies.py`

Updated to:
- Accept optional SystemManager parameter
- Connect all created clients to SystemManager
- Enable workflow execution through the stateless pipeline

## Workflow Execution Flow

### 1. Submission Path
```
1. Client submits workflow via API
2. API uses NativeAdapter (via dependency injection)
3. NativeAdapter stores workflow in persistence
4. NativeAdapter calls WorkflowManager.execute_workflow()
5. WorkflowManager validates and starts execution
6. ExecutionEngine submits to task queue
```

### 2. Task Execution Path
```
1. StatelessDependencyManager identifies ready tasks
2. Workers claim tasks atomically (via atomic_ops.claim_task)
3. Task execution tracked in persistence
4. Status updates trigger dependency resolution
5. Workflow completion checked atomically
```

### 3. Atomic Operations
All critical operations use atomic Redis operations:
- **Task Claiming**: Lua script ensures only one worker claims a task
- **Status Transitions**: Validated state machine transitions
- **Workflow Completion**: Distributed lock prevents premature completion

## Configuration

### Default Setup
The system automatically configures itself:
```python
# In API dependencies
system_manager = SystemManager(persistence=persistence)
await system_manager.initialize()
await system_manager.start_system()
```

### Redis Detection
Atomic operations are automatically enabled if Redis is available:
```python
# In SystemManager
redis_client = None
if hasattr(self.persistence, 'redis'):
    redis_client = self.persistence.redis
    logger.info("Redis client available for atomic operations")
```

## Benefits

1. **Fully Stateless**: No in-memory workflow state
2. **Race-Condition Free**: Atomic operations throughout
3. **Horizontally Scalable**: Add API/worker instances anytime
4. **Production Ready**: Safe for distributed deployment
5. **Backward Compatible**: Same API interface

## Testing

To verify the integration:

```python
# Submit workflow via API
curl -X POST http://localhost:8000/workflows \
  -H "Content-Type: application/json" \
  -d '{"workflow": {"id": "test-1", "tasks": [...]}}'

# Workflow will be:
# 1. Stored in persistence
# 2. Executed via WorkflowManager
# 3. Tasks claimed atomically
# 4. Completion tracked safely
```

## Monitoring

Key metrics to track:
- Workflow submission rate
- Task claim success/failure ratio
- Atomic operation latency
- System manager health

## Future Improvements

1. **Event-Driven Execution**: Add event bus integration for workflow submission events
2. **Metrics Collection**: Add prometheus metrics for workflow/task execution
3. **Advanced Scheduling**: Implement workflow scheduling in StatelessWorkflowManager
4. **Resource Limits**: Add per-workflow resource limits and quotas