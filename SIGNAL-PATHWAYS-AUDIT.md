# Signal Pathways Audit

## Overview
Multiple signal implementations exist in the codebase, creating divergent pathways and potential confusion.

## Signal Implementations Found

### 1. **SignalWorker** (NEW - Our Implementation)
**Location**: `src/gleitzeit/workers/signal_worker.py`
**Purpose**: Dedicated worker with leader election for processing signals
**Storage**:
- Waiters: `signal:waiters:{workflow_id}:{signal_name}`
- Metadata: `signal:metadata:{workflow_id}:{task_id}`
- Timeouts: `signal:timeouts`
**Process**: Reads from `workflow:signals:{workflow_id}` streams

### 2. **StatelessSignalManager**
**Location**: `src/gleitzeit/signals/stateless_signal_manager.py`
**Purpose**: Stateless signal processing utility
**Storage**:
- Pending signals: `signals:pending` (LIST)
- Processed: `signals:processed`
- Handlers: `signals:handlers:*`
- Metadata: `signals:meta:*`
- Workflow signals: `signals:workflow:*`
**Process**: Uses different key patterns, processes from pending list

### 3. **StatelessStreamSignalsMixin**
**Location**: `src/gleitzeit/system/mixins/stateless_stream_signals.py`
**Purpose**: Mixin for system manager signal support
**Methods**:
- `process_signals_once()` - calls StatelessSignalManager
- `send_signal()` - calls StatelessSignalManager
- `register_signal_handler()` - calls StatelessSignalManager
**Integration**: Wraps StatelessSignalManager

### 4. **UnifiedRedisAdapter Signal Methods**
**Location**: `src/gleitzeit/persistence/unified_redis.py`
**Method**: `register_signal_waiter()`
**Storage**: `signal:waiters:{workflow_id}:{signal}` (matches our pattern!)
**Purpose**: Persistence layer signal support

### 5. **SignalProvider**
**Location**: `src/gleitzeit/providers/signal_provider.py`
**Current State**: MIXED!
- Line 144: Uses our pattern `signal:waiters:{workflow_id}:{signal_name}` ✅
- Line 181: Calls `StatelessSignalManager.send_signal()` ❌
- Comment line 29: References non-existent `SignalMonitorService`

## Divergent Pathways

### Pathway 1: NEW SignalWorker Flow (What we want)
```
Task wait → SignalProvider stores in signal:waiters:{workflow_id}:{signal_name}
API sends → Stores in workflow:signals:{workflow_id} stream
SignalWorker → Reads stream, matches waiters, emits task:ready
```

### Pathway 2: StatelessSignalManager Flow (Old)
```
Signal sent → StatelessSignalManager.send_signal()
Stored in → signals:pending LIST
Processing → StatelessSignalManager.process_signals() pops from list
Handlers → Registered handlers in signals:handlers:*
```

### Pathway 3: Mixed/Broken
```
SignalProvider uses BOTH:
- Stores waiters in our pattern ✅
- But "send" method calls StatelessSignalManager ❌
```

## Key Conflicts

### 1. **Storage Pattern Mismatch**
- **SignalWorker**: `signal:waiters:{workflow_id}:{signal_name}`
- **StatelessSignalManager**: `signals:handlers:*`, `signals:pending`
- **Different data structures**: Sets vs Lists vs Hashes

### 2. **Processing Model**
- **SignalWorker**: Stream-based (XREADGROUP)
- **StatelessSignalManager**: List-based (RPOP from pending)

### 3. **Signal Sending**
- **API (fixed)**: Writes to `workflow:signals:{workflow_id}` stream
- **StatelessSignalManager**: Writes to `signals:pending` list
- **SignalProvider send**: Still uses StatelessSignalManager

### 4. **Registry Confusion**
- `registry_stateless.py` line 99: "Signal protocol handled by StreamSystemManager"
- But StreamSystemManager uses StatelessStreamSignalsMixin
- Which calls StatelessSignalManager (not SignalWorker)

## Recommendations

### 1. **Remove StatelessSignalManager References**
The SignalProvider should NOT call StatelessSignalManager at all.

### 2. **Clean Up SignalProvider**
Remove the "send" method from SignalProvider - signals should only be sent via API endpoints.

### 3. **Fix System Manager Integration**
The ModularStreamSystemManager should NOT use StatelessStreamSignalsMixin if we're using SignalWorker.

### 4. **Unify Storage Patterns**
Decide on ONE pattern:
- Use SignalWorker pattern everywhere (recommended)
- Remove StatelessSignalManager completely

### 5. **Update Registry**
Make it clear that signal/v1 protocol is handled by SignalProvider + SignalWorker, not StreamSystemManager.

## Files to Fix

### Priority 1: SignalProvider
```python
# Remove line 181-186 (StatelessSignalManager.send_signal)
# Remove "send" from supported_methods
# Update comments to reference SignalWorker
```

### Priority 2: Remove StatelessSignalManager Usage
- `system/mixins/stateless_stream_signals.py` - entire file may be unnecessary
- `system/modular_stream_system_manager.py` line 363-364 - remove process_signals_once

### Priority 3: Clean Documentation
- Update comments referencing SignalMonitorService
- Update registry comments about StreamSystemManager handling signals

## Impact Analysis

### Working Correctly
- ✅ SignalWorker implementation
- ✅ API endpoints (after our fix)
- ✅ SignalProvider wait method
- ✅ UnifiedRedisAdapter.register_signal_waiter()

### Broken/Conflicting
- ❌ SignalProvider send method (uses wrong system)
- ❌ StatelessStreamSignalsMixin (different storage pattern)
- ❌ Registry claiming StreamSystemManager handles signals

### Unused/Dead Code
- StatelessSignalManager (if we use SignalWorker)
- StatelessStreamSignalsMixin (if we use SignalWorker)
- SignalProvider send method (signals sent via API)

## Conclusion

We have **TWO competing signal systems**:
1. **New**: SignalWorker + updated SignalProvider (stream-based, per-workflow)
2. **Old**: StatelessSignalManager + StatelessStreamSignalsMixin (list-based, global)

They use different storage patterns and processing models. The SignalProvider is caught between both, using the new storage pattern but calling the old manager for sending.

**Recommendation**: Commit to the SignalWorker approach and remove/disable the StatelessSignalManager system to avoid confusion and bugs.