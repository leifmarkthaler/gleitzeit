# ModularStreamSystemManager Architecture Documentation

## Executive Summary

The **ModularStreamSystemManager** is the production-ready, stream-based system manager for Gleitzeit. It replaces both the legacy SystemManager and the incomplete StreamSystemManager with a clean, modular architecture using composable mixins.

## Architecture Overview

### Core Design Principles

1. **Pure Redis Streams** - All event processing through Redis Streams (no polling)
2. **Modular Composition** - Functionality split into focused mixins
3. **Stateless Processing** - Business state in Redis, only handlers in memory
4. **Horizontal Scalability** - Multiple instances can run concurrently
5. **Zero-Polling** - Blocking reads on streams for efficiency

### Mixin Architecture

```
ModularStreamSystemManager
├── BaseSystemMixin          # Core infrastructure, persistence, service registry
├── StreamCoreMixin          # Redis Streams infrastructure, event scheduling
├── StreamEventsMixin        # Event bus compatibility layer
├── StreamTimersMixin        # Timer management via streams
├── StreamSignalsMixin       # Signal handling via streams
├── StreamExecutionMixin     # Workflow/task execution engine
├── StreamMonitoringMixin    # Health monitoring, logging, telemetry
├── StreamProvidersMixin     # Provider hub and pooling
└── StreamAuthMixin          # Authentication and authorization
```

## Component Details

### StreamCoreMixin
- **StreamEventScheduler**: Schedules events via Redis Streams
- **MultiplexedStreamConsumer**: Single consumer for all event streams
- **ConsumerGroupManager**: Manages Redis consumer groups
- **HandlerRegistry**: Validates event contracts

### StreamExecutionMixin
- **ExecutionEngineV2**: Event-driven task execution
- **StatelessTaskOrchestrator**: Orchestrates task dependencies
- **QueueManager**: Manages task queues via streams
- **PoolingAdapter**: Provider connection pooling

### StreamTimersMixin
- **StreamTimerManager**: Timer creation and firing via streams
- Supports delay timers and scheduled events
- Automatic timer expiry and cancellation

### StreamSignalsMixin
- **StreamSignalManager**: Cross-workflow signaling
- Signal broadcasting and targeted delivery
- Signal expiry and persistence

### StreamMonitoringMixin
- **LogCollector**: Centralized logging (with buffer)
- **HealthMonitor**: Component health checking
- **WebSocketManager**: Real-time event streaming
- OpenTelemetry integration

## Stateless Architecture

### What's Stateless (in Redis)
- All workflow and task state
- Event queues and streams
- Timer and signal data
- User sessions and auth tokens
- Service registry and health data

### What's In Memory (Acceptable)
- **Event Handlers**: Function references for processing
- **Provider Connections**: Connection pools
- **Operational State**: Instance ID, start time
- **Buffers**: Log buffer (flushes to Redis)

### Why This Is Acceptable
1. Handlers are code, not data - same across instances
2. If instance dies, another can take over processing
3. Redis Streams maintain event ordering and reliability
4. Consumer groups ensure exactly-once processing

## Event Flow

```
1. Event Created → Redis Stream (XADD)
2. MultiplexedStreamConsumer → XREADGROUP (blocking)
3. Event Router → Handler Lookup
4. Handler Execution → Business Logic
5. Acknowledgment → XACK to Redis
```

## Scalability Features

- **Multiple Instances**: Each gets unique consumer ID
- **Consumer Groups**: Ensure events processed once
- **Sharding**: Events distributed across shards
- **No Coordination**: Instances work independently
- **Automatic Failover**: Dead consumers detected and replaced

## Fixed Issues (from our session)

1. ✅ Event handler registration for health_monitor.check
2. ✅ Event handler registration for log_collector.flush
3. ✅ StreamSignalManager method reference fix
4. ✅ AuthManager component registry parameter fix
5. ✅ WebSocketManager shutdown method
6. ✅ HealthMonitor iteration safety
7. ✅ Timer data validation

## Configuration

```python
# Recommended configuration for production
stream_config = {
    "total_shards": 64,           # Number of stream shards
    "consumer_group": "gleitzeit-processors",
    "monitoring_interval": 30,     # Health check interval
    "validate_contracts": True,    # Validate event contracts
    "max_batch_size": 100,        # Events per batch
    "block_timeout": 5000         # Stream block timeout (ms)
}
```

## Usage Example

```python
from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode

# Create configuration
config = SystemConfig()
config.deployment_mode = DeploymentMode.PRODUCTION

# Create and start manager
manager = await ModularStreamSystemManager.create(
    config=config,
    stream_config={
        "total_shards": 64,
        "consumer_group": "production-processors"
    },
    create_if_missing=True,
    start_system=True
)

# System is now running with stream-based processing
```

## Monitoring & Observability

- Stream lag monitoring via StreamMonitor
- Consumer group health via ConsumerGroupManager
- Component health via HealthMonitor
- OpenTelemetry tracing support
- WebSocket real-time event streaming
- Comprehensive logging with LogCollector

## Benefits Over Old Implementations

### vs SystemManager
- No polling loops
- True horizontal scalability
- Cleaner modular architecture
- Stream-based timer/signal management
- Better separation of concerns

### vs StreamSystemManager
- Actually complete and working
- Modular instead of monolithic
- Properly tested mixins
- Fixed initialization order
- No inheritance complexity