# Loop and Background Task Audit Checklist

## Files with asyncio.create_task, loops, or while True

### ✅ Already Archived (Confirmed No Loops)
- [x] `src/gleitzeit/timers/stream_timer_manager.py` → `archive/old-looped-components/`
- [x] `src/gleitzeit/signals/stream_signal_manager.py` → `archive/old-looped-components/`
- [x] `src/gleitzeit/scheduler/stream_event_scheduler.py` → `archive/old-looped-components/`
- [x] `src/gleitzeit/scheduler/hybrid_event_scheduler.py` → `archive/old-looped-components/`
- [x] `src/gleitzeit/scheduler/redis_event_scheduler.py` → `archive/old-looped-components/`
- [x] `src/gleitzeit/scheduler/stream_monitor.py` → `archive/old-looped-components/`
- [x] `src/gleitzeit/scheduler/consumer_group_manager.py` → `archive/old-looped-components/`

### 🔍 Need to Check - Core Components
- [ ] `src/gleitzeit/core/event_driven_retry_manager.py` - Check for retry loops
- [ ] `src/gleitzeit/core/workflow_manager.py` - Has `asyncio.create_task` for handler registration
- [ ] `src/gleitzeit/core/workflow_loader_v2.py` - Check what loops exist
- [ ] `src/gleitzeit/core/stateless_task_orchestrator.py` - Name says stateless but has loops?
- [ ] `src/gleitzeit/core/log_collector.py` - Check for flush loops

### 🔍 Need to Check - System Components
- [ ] `src/gleitzeit/system/leader_election.py` - Likely has election loops
- [ ] `src/gleitzeit/system/reconciliation_service.py` - Check reconciliation loops
- [ ] `src/gleitzeit/system/config_manager.py` - Check for config watch loops
- [ ] `src/gleitzeit/system/health_monitor.py` - Likely has monitoring loops
- [ ] `src/gleitzeit/system/service_registry.py` - Check for heartbeat loops
- [ ] `src/gleitzeit/system/system_manager.py` - Main system manager (deprecated?)
- [ ] `src/gleitzeit/system/reconciliation_manager.py` - Check reconciliation loops
- [ ] `src/gleitzeit/system/stateless_reconciliation_manager.py` - Should be stateless
- [ ] `src/gleitzeit/system/tick_coordinator.py` - Tick-based, likely has loops
- [ ] `src/gleitzeit/system/distributed_registry.py` - Check for sync loops
- [ ] `src/gleitzeit/system/resource_coordinator.py` - Resource monitoring loops?

### 🔍 Need to Check - System Mixins
- [ ] `src/gleitzeit/system/mixins/stream_providers.py` - Provider management
- [ ] `src/gleitzeit/system/mixins/base.py` - Base mixin

### 🔍 Need to Check - Provider Components
- [ ] `src/gleitzeit/providers/stream_integration.py` - Stream integration loops?
- [ ] `src/gleitzeit/providers/pooling_adapter.py` - Pool management loops?
- [ ] `src/gleitzeit/providers/provider_pool.py` - Pool lifecycle loops?

### 🔍 Need to Check - Event System
- [ ] `src/gleitzeit/events/consumer_lifecycle.py` - Consumer heartbeat loops?
- [ ] `src/gleitzeit/events/redis_pubsub_bus.py` - PubSub loops?
- [ ] `src/gleitzeit/events/base.py` - Base event class

### 🔍 Need to Check - API/WebSocket
- [ ] `src/gleitzeit/api/main.py` - API server loops
- [ ] `src/gleitzeit/api/shared_dependencies.py` - Shared dependencies
- [ ] `src/gleitzeit/api/stateless_websocket_manager.py` - WebSocket loops
- [ ] `src/gleitzeit/api/websocket_manager.py` - WebSocket management
- [ ] `src/gleitzeit/api/routes/signals.py` - Signal endpoints
- [ ] `src/gleitzeit/api/routes/events.py` - Event endpoints
- [ ] `src/gleitzeit/ui/api/routes/websocket_unified.py` - Unified WebSocket

### 🔍 Need to Check - Client Components
- [ ] `src/gleitzeit/client/mixins/event_task.py` - Event handling
- [ ] `src/gleitzeit/client/mixins/event_workflow.py` - Workflow events
- [ ] `src/gleitzeit/client/mixins/workflow.py` - Workflow management
- [ ] `src/gleitzeit/client/mixins/streaming.py` - Streaming support
- [ ] `src/gleitzeit/client/events/client_event_bus.py` - Client-side event bus
- [ ] `src/gleitzeit/client/events/websocket_manager.py` - Client WebSocket

### 🔍 Need to Check - Other Components
- [ ] `src/gleitzeit/registry.py` - Registry management
- [ ] `src/gleitzeit/cli/main.py` - CLI interface
- [ ] `src/gleitzeit/scaling/node_registry.py` - Node management
- [ ] `src/gleitzeit/persistence/unified_redis.py` - Redis persistence
- [ ] `src/gleitzeit/hub/base.py` - Hub base class
- [ ] `src/gleitzeit/hub/mcp_hub.py` - MCP hub implementation

## CRITICAL FINDINGS - Multiple Consumer Groups Still Exist!

### Consumer Groups Found:
1. **StreamlinedEventBus**: `gleitzeit-{instance_id}`
2. **StatelessStreamCoreMixin**: `gleitzeit-processors` (default)
3. **WebSocket Routes**: `websocket_consumers`
4. **SignalProvider**: `signal-processors` ⚠️ DUPLICATE!
5. **System Manager**: `gleitzeit-workers`

### Files Actually Reading from Redis Streams:
- `src/gleitzeit/events/stateless_stream_consumer.py` ✓ (Used by StreamlinedEventBus)
- `src/gleitzeit/persistence/unified_redis.py` ✓ (Redis adapter)
- `src/gleitzeit/core/log_collector.py` ❓ (Check why)
- `src/gleitzeit/system/reconciliation_manager.py` ❓ (Check why)
- `src/gleitzeit/ui/api/routes/websocket_unified.py` ⚠️ (Own consumer group!)

## Categories for Decision

### 1. 🗑️ Should Archive (Has Loops)
Files with background loops that violate stateless architecture

### 2. ✅ Can Keep (No Real Loops)
Files that use create_task only for initialization or one-time operations

### 3. 🔧 Need to Fix
Files that have loops but are essential and need to be converted to stateless

### 4. ❓ Need More Context
Files where the loop usage is unclear

## Next Steps
1. Check each file to categorize it
2. Archive files with loops that shouldn't exist
3. Fix essential files to be stateless
4. Document any legitimate uses of async operations