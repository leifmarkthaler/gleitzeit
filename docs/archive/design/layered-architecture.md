# Gleitzeit Layered Process Management Architecture

## Overview

Gleitzeit 0.0.7 introduces a layered architecture for process management that provides clear separation of concerns, better maintainability, and more flexible deployment options. This architecture replaces the previous monolithic orchestrator with a modular, layered approach.

## Architecture Layers

```
┌─────────────────────────────────────────────┐
│           ProcessOrchestrator               │  Layer 4: Orchestration
│         (Top-level coordination)            │
└─────────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
┌──────────────┐       ┌──────────────┐
│ServiceManager│       │WorkerManager │        Layer 3: Domain Management
│ (API, UI)    │       │  (Workers)   │
└──────────────┘       └──────────────┘
        │                       │
        └───────────┬───────────┘
                    ▼
        ┌───────────────────────┐
        │  SmartProcessManager  │              Layer 2: Process Lifecycle
        │ (Core process mgmt)   │
        └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │    PortManager +      │              Layer 1: Resource Management
        │  Instance Identity    │
        └───────────────────────┘
```

## Layer Descriptions

### Layer 1: Resource Management
**Components:** `PortManager`, `Instance Identity`
- **Responsibility:** Low-level resource allocation and identity management
- **Key Features:**
  - Port allocation with conflict detection
  - Instance identification (ID, name, role)
  - Machine capabilities detection
  - Port offset calculation for multi-instance deployments

### Layer 2: Process Lifecycle Management
**Component:** `SmartProcessManager`
- **Responsibility:** Core process lifecycle management with distributed coordination
- **Key Features:**
  - Process start/stop/restart with health monitoring
  - Distributed locking via Redis
  - Service ownership tracking
  - Graceful shutdown handling
  - Process state persistence
  - Automatic restart policies

### Layer 3: Domain-Specific Management
**Components:** `ServiceManager`, `WorkerManager`

#### ServiceManager
- **Responsibility:** Service-specific logic for API and UI servers
- **Key Features:**
  - API server configuration and startup
  - UI server configuration and startup
  - Service health monitoring
  - Environment variable setup
  - CORS configuration

#### WorkerManager
- **Responsibility:** Worker-specific logic with shard assignment
- **Key Features:**
  - Worker pool management
  - Shard assignment (round-robin distribution)
  - Worker type configuration
  - Auto-scaling capabilities
  - Worker health monitoring
  - Dynamic worker configuration

### Layer 4: Orchestration
**Component:** `ProcessOrchestrator`
- **Responsibility:** Top-level coordination and sequencing
- **Key Features:**
  - Startup sequencing (services before workers)
  - Configuration management
  - Unified lifecycle management
  - Status aggregation
  - Signal handling

## Key Design Principles

### 1. Single Responsibility
Each layer has a clearly defined responsibility:
- Resource management handles ports and identity
- Process management handles lifecycle
- Domain managers handle service/worker specifics
- Orchestrator handles coordination

### 2. Dependency Injection
Higher layers depend on lower layer abstractions:
```python
# Example: ServiceManager depends on ProcessManager
class ServiceManager:
    def __init__(self, process_manager: SmartProcessManager, port_manager: PortManager):
        self.process_manager = process_manager
        self.port_manager = port_manager
```

### 3. Separation of Concerns
- **ProcessManager:** Doesn't know about services vs workers
- **ServiceManager:** Doesn't know about worker sharding
- **WorkerManager:** Doesn't know about API/UI specifics
- **Orchestrator:** Knows how to coordinate but delegates specifics

## Implementation Files

- `/src/gleitzeit/core/process_manager.py` - SmartProcessManager implementation
- `/src/gleitzeit/core/service_manager.py` - ServiceManager for API/UI
- `/src/gleitzeit/core/worker_manager.py` - WorkerManager with sharding
- `/src/gleitzeit/core/process_orchestrator.py` - Top-level orchestration
- `/src/gleitzeit/core/ports.py` - Port management
- `/src/gleitzeit/core/instance.py` - Instance identity

## Configuration Example

```yaml
# gleitzeit_workers.yaml
serve:
  api:
    enabled: true
    host: 0.0.0.0
    port: 8000
  ui:
    enabled: true
    host: 0.0.0.0
    port: 8004

workers:
  task_execution:
    enabled: true
    count: 2
    worker_class: gleitzeit.workers.task_execution_worker.TaskExecutionWorker
    max_concurrent: 10
    batch_size: 10
    block_timeout: 5000

  dependency:
    enabled: true
    count: 1
    worker_class: gleitzeit.workers.dependency_worker.DependencyWorker
```

## Usage

### Starting with the new architecture:
```bash
# Using the new layered architecture
python -m gleitzeit.cli.main serve --config gleitzeit_workers.yaml --restart

# With custom instance name
python -m gleitzeit.cli.main serve --instance-name "production" --port-offset 100
```

### The startup sequence:
1. **Initialize** ProcessOrchestrator with configuration
2. **Create** SmartProcessManager with Redis connection
3. **Initialize** ServiceManager and WorkerManager
4. **Start Services** (API, UI) first - they're required by workers
5. **Start Workers** with shard assignments
6. **Monitor** all processes and handle signals

## Restart Policies and Options

### Automatic Restart Policy
The SmartProcessManager includes sophisticated restart logic with exponential backoff:

**Default Configuration:**
- **Max restart attempts**: 3 attempts per process
- **Exponential backoff**: Starting at 2 seconds, doubling each time
- **Maximum backoff**: 300 seconds (5 minutes)
- **Stable uptime threshold**: 30 seconds (resets restart counter)

**How it works:**
1. When a process dies unexpectedly, the monitor checks the restart count
2. If under the limit (3 attempts), it calculates backoff time: `2^restart_count` seconds
3. After waiting for the backoff period, it restarts the process
4. If the process runs stable for 30+ seconds, the restart counter resets to 0

**Example restart timeline:**
```
Process crashes → Wait 2 seconds → Restart (attempt 1)
Process crashes → Wait 4 seconds → Restart (attempt 2)
Process crashes → Wait 8 seconds → Restart (attempt 3)
Process crashes → Stop trying (exceeded max attempts)

OR if stable:
Process crashes → Wait 2 seconds → Restart → Runs for 35 seconds
Process crashes → Wait 2 seconds → Restart (counter reset, attempt 1)
```

### Command-line Options

#### `--restart` flag
Forces termination of existing processes before starting new ones:
```bash
# Kill all existing Gleitzeit processes and start fresh
python -m gleitzeit.cli.main serve --restart
```

This is useful for:
- Development iterations
- Forcing a clean restart after configuration changes
- Recovering from stuck processes

### Process Tracking
Each process maintains detailed restart information in `ProcessInfo`:
```python
ProcessInfo:
  restart_count: int        # Current restart attempt number
  last_restart_at: datetime # Timestamp of last restart
  status: str              # starting, running, failed, stopped
  exit_code: Optional[int] # Process exit code if terminated
```

### Configuration via YAML
Restart behavior can be configured (though not currently exposed):
```yaml
performance:
  process:
    restart_policy: "on-failure"    # When to restart
    max_restart_attempts: 3         # Maximum retry attempts
    restart_backoff_seconds: 5      # Initial backoff time
```

### Distributed Coordination
The restart mechanism includes distributed coordination via Redis:
- Prevents multiple instances from restarting the same service
- Maintains service ownership across restarts
- Tracks restart attempts globally

## Benefits of the Layered Architecture

### 1. Maintainability
- Clear boundaries between components
- Easy to locate functionality
- Reduced coupling between layers

### 2. Testability
- Each layer can be tested independently
- Mock lower layers for unit testing
- Integration testing at each layer

### 3. Flexibility
- Easy to add new service types
- Simple to implement new worker types
- Can disable layers (e.g., run without workers)

### 4. Scalability
- Independent scaling of services and workers
- Multi-instance deployment support
- Distributed locking for coordination

### 5. Debugging
- Clear error propagation through layers
- Layer-specific logging
- Isolated failure domains

## Migration from Old Architecture

The old monolithic orchestrator has been replaced with the layered approach:

**Before:**
```python
# Old: Everything in one orchestrator
orchestrator = Orchestrator(config)
orchestrator.start_everything()
```

**After:**
```python
# New: Layered with clear separation
process_manager = SmartProcessManager(redis_url)
service_manager = ServiceManager(process_manager, port_manager)
worker_manager = WorkerManager(process_manager, config)
orchestrator = ProcessOrchestrator(config, redis_url)
```

## Future Enhancements

The layered architecture enables future improvements:

1. **Plugin System**: New managers can be added as plugins
2. **Remote Workers**: Workers can run on different machines
3. **Service Mesh**: Services can discover each other
4. **Health Aggregation**: Centralized health monitoring
5. **Configuration Hot-Reload**: Update configuration without restart

## Conclusion

The layered architecture in Gleitzeit 0.0.7 provides a robust, maintainable, and scalable foundation for process management. Each layer has a clear purpose, making the system easier to understand, test, and extend.