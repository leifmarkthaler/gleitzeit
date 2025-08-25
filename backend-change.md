# Backend Architecture Change: Hybrid SQL Persistence

## Problem Statement

The current SQL adapter implementation has significant issues with concurrent task status updates, leading to race conditions where:
- Tasks are marked as completed but then overwritten as queued
- Multiple concurrent saves create conflicting states
- Transaction isolation issues prevent proper status tracking
- Batch processing fails because tasks appear incomplete despite successful execution

## Current Architecture Issues

### SQL Adapter Problems
1. **Concurrent Updates**: Multiple parts of the system update task status simultaneously, causing overwrites
2. **Transaction Isolation**: Different database connections see different states
3. **Event Bus Integration**: SQL backend struggles with real-time event-driven architecture
4. **Status Tracking**: Task statuses frequently revert to earlier states due to race conditions

### Working Components
- Redis adapter works correctly with full event-driven architecture
- In-memory adapter handles real-time task coordination well
- Event bus properly coordinates task execution

## Proposed Solution: Hybrid SQL Backend

### Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   Event Bus                         │
│              (In-Memory Coordination)                │
└─────────────────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
┌───────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐
│   Memory     │ │   Redis    │ │    SQL     │
│   Adapter    │ │  Adapter   │ │  Adapter   │
│              │ │            │ │            │
│ • Real-time  │ │ • Full     │ │ • Archive  │
│   task coord │ │   persist  │ │   only     │
│ • Event bus  │ │ • Events   │ │ • No events│
│ • Queues     │ │ • Queues   │ │ • Read-only│
└──────────────┘ └────────────┘ └────────────┘
```

### Key Changes

#### 1. SQL Adapter Becomes Archive-Only
- **Purpose**: Long-term storage and audit trail
- **Responsibilities**:
  - Store completed workflows and tasks
  - Store failed workflows and tasks  
  - Provide historical query capabilities
  - Generate reports and analytics
- **NOT Responsible For**:
  - Real-time task coordination
  - Queue management
  - Event processing
  - Status transitions during execution

#### 2. Memory Adapter Handles Real-Time Coordination
When SQL persistence is configured:
- Memory adapter manages all active tasks
- Event bus coordinates execution
- Queues exist only in memory
- Status transitions happen in memory

#### 3. SQL Write Points
SQL adapter only writes at terminal states:
- When task reaches `COMPLETED` status
- When task reaches `FAILED` status (after all retries)
- When workflow reaches `completed` or `failed` status

## Implementation Plan

### Phase 1: Modify Persistence Factory
```python
class PersistenceFactory:
    @staticmethod
    async def create_adapter(persistence_type: str):
        if persistence_type == "sql":
            # Create hybrid setup with memory monitoring
            memory_adapter = MemoryPersistenceAdapter(
                max_memory_mb=1024,  # Configurable via env var
                enable_monitoring=True
            )
            sql_adapter = SQLPersistenceAdapter(archive_only=True)
            return HybridPersistenceAdapter(
                runtime=memory_adapter,
                archive=sql_adapter
            )
        elif persistence_type == "redis":
            # Redis remains unchanged
            return UnifiedRedisAdapter()
        else:
            # Pure memory mode with monitoring
            return MemoryPersistenceAdapter(
                max_memory_mb=512,
                enable_monitoring=True
            )
```

### Phase 2: Add Memory Monitoring to MemoryPersistenceAdapter
```python
import psutil
import sys
from dataclasses import dataclass
from typing import Dict, Optional
import asyncio

@dataclass
class MemoryStats:
    used_mb: float
    max_mb: float
    task_count: int
    workflow_count: int
    result_count: int
    
class MemoryPersistenceAdapter:
    def __init__(self, max_memory_mb: int = 1024, enable_monitoring: bool = True):
        self.max_memory_mb = max_memory_mb
        self.enable_monitoring = enable_monitoring
        self._monitor_task = None
        self._memory_warning_threshold = 0.8  # Warn at 80% usage
        self._memory_critical_threshold = 0.95  # Reject new tasks at 95%
        
        # Storage
        self.tasks: Dict[str, Task] = {}
        self.workflows: Dict[str, Workflow] = {}
        self.task_results: Dict[str, TaskResult] = {}
        
        if enable_monitoring:
            self._start_monitoring()
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage of this process in MB"""
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    
    def _get_memory_stats(self) -> MemoryStats:
        """Get detailed memory statistics"""
        return MemoryStats(
            used_mb=self._get_memory_usage(),
            max_mb=self.max_memory_mb,
            task_count=len(self.tasks),
            workflow_count=len(self.workflows),
            result_count=len(self.task_results)
        )
    
    async def _monitor_memory(self):
        """Background task to monitor memory usage"""
        while self.enable_monitoring:
            stats = self._get_memory_stats()
            usage_ratio = stats.used_mb / stats.max_mb
            
            if usage_ratio > self._memory_critical_threshold:
                logger.critical(
                    f"MEMORY CRITICAL: {stats.used_mb:.1f}MB / {stats.max_mb:.1f}MB "
                    f"({usage_ratio*100:.1f}%) - Tasks: {stats.task_count}, "
                    f"Workflows: {stats.workflow_count}"
                )
                # Trigger cleanup of completed tasks
                await self._cleanup_completed_tasks()
                
            elif usage_ratio > self._memory_warning_threshold:
                logger.warning(
                    f"Memory usage high: {stats.used_mb:.1f}MB / {stats.max_mb:.1f}MB "
                    f"({usage_ratio*100:.1f}%)"
                )
            
            await asyncio.sleep(10)  # Check every 10 seconds
    
    async def _check_memory_before_save(self) -> None:
        """Check memory before accepting new tasks"""
        if not self.enable_monitoring:
            return
            
        stats = self._get_memory_stats()
        usage_ratio = stats.used_mb / stats.max_mb
        
        if usage_ratio > self._memory_critical_threshold:
            raise MemoryError(
                f"Out of memory: {stats.used_mb:.1f}MB / {stats.max_mb:.1f}MB "
                f"({usage_ratio*100:.1f}%). Cannot accept new tasks. "
                f"Consider increasing max_memory_mb or using Redis backend."
            )
    
    async def save_task(self, task: Task):
        """Save task with memory check"""
        await self._check_memory_before_save()
        self.tasks[task.id] = task
    
    async def _cleanup_completed_tasks(self):
        """Remove completed tasks that have been archived"""
        cleaned = 0
        for task_id in list(self.tasks.keys()):
            task = self.tasks.get(task_id)
            if task and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                # Only remove if it's been archived (hybrid mode will handle this)
                if hasattr(self, '_archived_tasks') and task_id in self._archived_tasks:
                    del self.tasks[task_id]
                    if task_id in self.task_results:
                        del self.task_results[task_id]
                    cleaned += 1
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} completed tasks to free memory")
```

### Phase 3: Create HybridPersistenceAdapter
```python
class HybridPersistenceAdapter:
    def __init__(self, runtime: MemoryPersistenceAdapter, archive: SQLPersistenceAdapter):
        self.runtime = runtime  # For active task management with memory monitoring
        self.archive = archive  # For completed/failed storage
        self.runtime._archived_tasks = set()  # Track what's been archived
    
    async def save_task(self, task: Task):
        # Always save to runtime (with memory check)
        await self.runtime.save_task(task)
        
        # Only archive terminal states
        if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
            await self.archive.archive_task(task)
            self.runtime._archived_tasks.add(task.id)
            # Optionally trigger cleanup if memory is high
            stats = self.runtime._get_memory_stats()
            if stats.used_mb / stats.max_mb > 0.9:
                await self.runtime._cleanup_completed_tasks()
    
    async def get_task(self, task_id: str):
        # Always read from runtime for active tasks
        task = await self.runtime.get_task(task_id)
        if task:
            return task
        
        # Fall back to archive for completed tasks
        return await self.archive.get_task(task_id)
    
    async def get_memory_stats(self) -> MemoryStats:
        """Expose memory statistics"""
        return self.runtime._get_memory_stats()
```

### Phase 3: Simplify SQL Adapter
- Remove all event bus integration
- Remove queue management code
- Remove real-time status tracking
- Add `archive_only` mode flag
- Optimize for write-once, read-many pattern

### Phase 4: Update Batch Processor
- Use runtime adapter for status polling
- Only query archive for final results
- Remove complex status checking logic

### Phase 5: Add Configuration Options
```python
# Environment variables for memory configuration
GLEITZEIT_MAX_MEMORY_MB = int(os.getenv("GLEITZEIT_MAX_MEMORY_MB", "1024"))
GLEITZEIT_MEMORY_WARNING_THRESHOLD = float(os.getenv("GLEITZEIT_MEMORY_WARNING_THRESHOLD", "0.8"))
GLEITZEIT_MEMORY_CRITICAL_THRESHOLD = float(os.getenv("GLEITZEIT_MEMORY_CRITICAL_THRESHOLD", "0.95"))
GLEITZEIT_MEMORY_MONITOR_INTERVAL = int(os.getenv("GLEITZEIT_MEMORY_MONITOR_INTERVAL", "10"))

# Usage in factory
memory_adapter = MemoryPersistenceAdapter(
    max_memory_mb=GLEITZEIT_MAX_MEMORY_MB,
    enable_monitoring=True,
    warning_threshold=GLEITZEIT_MEMORY_WARNING_THRESHOLD,
    critical_threshold=GLEITZEIT_MEMORY_CRITICAL_THRESHOLD,
    monitor_interval=GLEITZEIT_MEMORY_MONITOR_INTERVAL
)
```

## Memory Monitoring Features

### Real-time Monitoring
- Background task checks memory usage every 10 seconds (configurable)
- Tracks process RSS (Resident Set Size) memory
- Monitors task, workflow, and result counts

### Thresholds and Actions
1. **Warning Threshold (80%)**:
   - Logs warning messages
   - Continues accepting tasks
   - Alerts operators to potential issues

2. **Critical Threshold (95%)**:
   - Logs critical messages
   - Triggers automatic cleanup of archived tasks
   - Rejects new tasks with MemoryError
   - Provides clear error messages with recommendations

### Memory Statistics API
```python
# Available through hybrid adapter
stats = await adapter.get_memory_stats()
print(f"Memory: {stats.used_mb}/{stats.max_mb} MB")
print(f"Tasks: {stats.task_count}")
print(f"Workflows: {stats.workflow_count}")
```

### Configuration
| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| GLEITZEIT_MAX_MEMORY_MB | 1024 | Maximum memory limit in MB |
| GLEITZEIT_MEMORY_WARNING_THRESHOLD | 0.8 | Warn at this usage ratio |
| GLEITZEIT_MEMORY_CRITICAL_THRESHOLD | 0.95 | Reject tasks at this ratio |
| GLEITZEIT_MEMORY_MONITOR_INTERVAL | 10 | Check interval in seconds |

## Benefits

### Immediate Benefits
1. **Eliminates Race Conditions**: No concurrent SQL updates during execution
2. **Simplifies SQL Adapter**: Becomes a simple archive store
3. **Preserves Redis Functionality**: Redis adapter remains unchanged
4. **Better Performance**: Memory operations for active tasks

### Long-term Benefits
1. **Clearer Separation of Concerns**: Runtime vs. archive storage
2. **Easier Debugging**: SQL database only contains final states
3. **Scalability**: Can use different storage backends for different purposes
4. **Reliability**: SQL write failures don't affect task execution

## Migration Strategy

### Breaking Changes
1. SQL persistence mode will work differently - no longer a full persistence backend
2. Existing SQL databases will need migration or can be used as read-only archives
3. Users relying on SQL for real-time task coordination must switch to Redis
4. Configuration remains the same (`GLEITZEIT_PERSISTENCE_TYPE=sql`) but behavior changes

### Testing Plan
1. Test batch processing with hybrid SQL backend
2. Verify completed tasks are archived correctly
3. Ensure failed tasks are archived with error details
4. Test workflow completion tracking
5. Verify historical queries work

## Risks and Mitigation

### Risk 1: Memory Usage  
- **Risk**: Large workflows might consume significant memory
- **Mitigation**: 
  - Active memory monitoring with configurable limits
  - Automatic cleanup of archived tasks when memory is high
  - Reject new tasks with MemoryError when approaching limit
  - Environment variables to tune memory thresholds
  - Clear error messages directing users to Redis for large workloads

### Risk 2: Data Loss on Crash
- **Risk**: Active tasks in memory lost on crash
- **Mitigation**: 
  - SQL archive provides audit trail of completed work
  - Recommend Redis for mission-critical deployments
  - Memory monitor logs warnings before OOM conditions

### Risk 3: Query Complexity
- **Risk**: Need to query both runtime and archive
- **Mitigation**: Unified query interface that checks both stores

## Alternative Considered

### Alternative 1: Fix SQL Adapter Concurrency
- **Pros**: Maintains single storage backend
- **Cons**: 
  - Complex to implement correctly
  - Performance overhead of SQL for real-time coordination
  - Fundamental mismatch between SQL transactions and event-driven architecture

### Alternative 2: Remove SQL Support
- **Pros**: Simplifies codebase
- **Cons**: 
  - Users want SQL for compliance/audit requirements
  - SQL valuable for analytics and reporting

## Recommendation

Proceed with the hybrid approach because:
1. It solves the immediate problem (batch processing with SQL)
2. It maintains backward compatibility
3. It provides clear separation between runtime and archive concerns
4. It preserves the benefits of both SQL (audit trail) and memory (performance)
5. It's easier to implement than fixing all SQL concurrency issues

## Implementation Timeline

- **Week 1**: Implement HybridPersistenceAdapter
- **Week 2**: Modify SQL adapter for archive-only mode
- **Week 3**: Update batch processor and testing
- **Week 4**: Documentation and migration guide

## Success Criteria

1. Batch processing works with SQL backend
2. No race conditions in task status updates
3. All completed/failed tasks archived to SQL
4. Performance improvement for SQL-backed deployments
5. Redis adapter continues to work unchanged