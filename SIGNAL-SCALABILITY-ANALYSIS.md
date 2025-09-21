# Signal System Scalability Analysis

## Current Issues

### 1. NOT Stateless
- SignalMonitorService stores `_stream_positions` in memory (line 34)
- Uses local `self.running` flag (line 32)
- Has `_monitor_task` as instance variable
- Stream positions lost on restart

### 2. NOT Scalable
- No consumer groups for Redis Streams
- Multiple instances would process same signals
- No distributed coordination
- Every instance runs monitoring (if not distributed mode)

### 3. Architecture Problems
- Signal monitoring tied to specific instance
- No proper leader election for distributed mode
- Stream positions not persisted to Redis

## Required Changes for Scalability

### 1. Use Redis Streams Consumer Groups
```python
# Current (WRONG):
self._stream_positions: Dict[str, str] = {}  # In-memory!

# Should be:
# Use Redis consumer groups with XREADGROUP
# Redis tracks positions automatically
```

### 2. Proper Distributed Coordination
```python
# Need to use Redis locks/leader election
# Only ONE instance should process signals
# Or use consumer groups for distribution
```

### 3. Stateless Operation
- Remove ALL instance variables for state
- Store everything in Redis
- Use Redis for coordination

## Correct Architecture

### Option 1: Single Leader Pattern (Like Timer)
- One instance monitors all signals
- Leader election via Redis lock
- Failover to another instance if leader dies

### Option 2: Distributed Consumer Groups
- Each instance joins consumer group
- Redis distributes signals across instances
- Built-in acknowledgment and retry

### Option 3: Event-Driven (Best for Gleitzeit)
- Signals go to task queue
- Workers process signals like any other task
- No separate monitor service needed

## Recommendation

**Use Option 3: Event-Driven via Task Queue**

Reasons:
1. Aligns with Gleitzeit's architecture
2. Truly stateless and scalable
3. No separate monitoring service
4. Leverages existing infrastructure

## Implementation Plan

### Phase 1: Remove Stateful Components
- Remove `_stream_positions` dict
- Remove `running` flag
- Use Redis for all state

### Phase 2: Use Consumer Groups
- Create consumer group for signals
- Use XREADGROUP for processing
- Implement proper acknowledgment

### Phase 3: Integrate with Task Queue
- Signals become tasks
- Process via existing workers
- No separate monitor needed

## Code Changes Required

### 1. SignalMonitorService
- Remove in-memory state
- Use Redis consumer groups
- Or remove entirely (event-driven)

### 2. SignalManager
- Don't start local monitoring
- Use distributed coordination
- Or delegate to task queue

### 3. SignalProvider
- Return tasks to queue
- Let workers process signals
- Maintain SLEEPING status

## Scalability Testing

Must verify:
1. Multiple instances don't duplicate processing
2. Signals distributed across instances
3. Failover works correctly
4. No signal loss on restart
5. Stream positions persisted