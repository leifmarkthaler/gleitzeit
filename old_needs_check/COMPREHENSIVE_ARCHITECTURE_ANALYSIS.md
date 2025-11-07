# Comprehensive Architecture Analysis - Gleitzeit 0.0.7

## Executive Summary

Gleitzeit has a **dual-personality architecture**: a sophisticated distributed workflow orchestration system that operates in simplified local mode due to incomplete integration and a critical subprocess management bug.

## 1. ACTUAL ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────┐
│                    CLI Entry Point                       │
│                   (gleitzeit serve)                      │
└─────────────────┬───────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────┐
│              DUAL ORCHESTRATION LAYER                    │
│  ┌────────────────────┐    ┌────────────────────┐      │
│  │ ProcessOrchestrator │    │  WorkerOrchestrator│      │
│  │  (Modern Pattern)   │    │  (Legacy Pattern)  │      │
│  └────────┬───────────┘    └────────────────────┘      │
└───────────┼──────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────┐
│                  MANAGEMENT LAYER                        │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐ │
│  │ServiceManager│  │ WorkerManager │  │ProcessManager│ │
│  │  (API, UI)   │  │   (Workers)   │  │(Core Procs) │ │
│  └──────┬───────┘  └───────┬───────┘  └──────┬───────┘ │
└─────────┼───────────────────┼──────────────────┼────────┘
          │                   │                  │
          ▼                   ▼                  ▼
┌─────────────────────────────────────────────────────────┐
│                   EXECUTION LAYER                        │
│     subprocess.Popen (BLOCKING - BROKEN!)                │
│     AsyncSubprocessPool (EXISTS BUT UNUSED)              │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                 INFRASTRUCTURE LAYER                     │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │    Redis    │  │  Port System │  │   Instance    │  │
│  │(Distributed)│  │ (3 Conflicts)│  │  Management   │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## 2. COMPONENT HIERARCHY & RELATIONSHIPS

### 2.1 Entry Flow
```
CLI (main.py)
  → serve command
    → ProcessOrchestrator.start()
      → ServiceManager.start_all_services()
        → ProcessManager.start_service()
          → subprocess.Popen() [DEADLOCK HERE]
      → WorkerManager.start_all_workers()
        → ProcessManager.start_worker()
          → subprocess.Popen() [DEADLOCK HERE]
```

### 2.2 Actual Dependencies
```python
# What's actually imported and used:
ProcessOrchestrator:
  - ServiceManager (used)
  - WorkerManager (used)
  - ProcessManager (used)
  - PortManager (used)
  - Redis (partially used)

# What exists but isn't used:
  - CircuitBreaker (isolated in ollama handler)
  - LeaderElection (only in 2 workers)
  - AsyncSubprocessPool (only for tasks)
  - RetryService (only for workflows)
  - HealthMonitor (only as HTTP endpoint)
```

## 3. DATA FLOW ANALYSIS

### 3.1 State Management Chaos
```
Three Parallel State Systems:
1. Redis State
   - port:machine:{id}:{service} → port allocations
   - service_lock:{service} → distributed locks
   - instance:{id}:services → service registry

2. Filesystem State
   - /var/run/gleitzeit/locks/port_{port}.lock
   - /tmp/gleitzeit/pids/{service}.pid

3. OS Process State
   - Actual running processes
   - Actual port bindings

PROBLEM: These don't sync!
```

### 3.2 Port Allocation Flow
```
1. PortManager.allocate_port() → Checks Redis
2. ProcessManager._acquire_port_lock() → Creates filesystem lock
3. subprocess.Popen() → OS binds port
4. If crash: Redis + filesystem remain, OS clears
   Result: "Port already in use" on restart
```

## 4. WORKER SYSTEM ARCHITECTURE

### 4.1 Worker Types & Responsibilities
```
Discovered Workers:
├── dependency_worker.py    → Workflow dependencies
├── executor_worker.py      → Task execution
├── monitor_worker.py       → Resource monitoring
├── pending_recovery.py     → Recover pending tasks
├── recovery_worker.py      → Failed task recovery
├── retry_worker.py         → Task retries
├── scheduler_worker.py     → Cron/scheduled tasks
├── signal_worker.py        → Signal handling
├── task_worker.py          → Core task processing
├── timer_worker.py         → Timer events
├── trigger_worker.py       → Event triggers
└── workflow_worker.py      → Workflow orchestration

Each worker:
- Has Redis queue (workflow:queue:{type}:{shard})
- Implements BaseWorker interface
- Can scale horizontally via sharding
```

### 4.2 Worker Sharding System
```python
# 16 shards distributed across workers
Shard Assignment:
  Worker 1: shards [0, 1, 2, 3]
  Worker 2: shards [4, 5, 6, 7]
  Worker 3: shards [8, 9, 10, 11]
  Worker 4: shards [12, 13, 14, 15]

# Enables horizontal scaling
# BUT: All on same machine currently
```

## 5. DISTRIBUTED COORDINATION (What Exists)

### 5.1 Leader Election System
```python
# core/leader_election.py - FULLY IMPLEMENTED
LeaderElection:
  - Redis-based with Lua scripts
  - TTL-based leadership (30s default)
  - Automatic failover
  - Split-brain prevention

PROBLEM: Only used in 2 workers!
```

### 5.2 Instance Management
```python
# core/instance.py - FULLY IMPLEMENTED
InstanceIdentity:
  - Unique ID generation
  - Machine fingerprinting
  - Capability detection (CPU, RAM, GPU)
  - Redis registration

WORKS: But no coordination between instances
```

### 5.3 Service Discovery
```python
# api/discovery.py - PARTIALLY IMPLEMENTED
ServiceRegistry:
  - Redis-based registry
  - Health endpoints defined
  - Service metadata

MISSING: Dynamic updates, health monitoring
```

## 6. RESILIENCE MECHANISMS (Dormant)

### 6.1 Circuit Breaker
```python
# core/circuit_breaker.py - COMPLETE
States: CLOSED → OPEN → HALF_OPEN
Features:
  - Failure tracking
  - Automatic recovery
  - Configurable thresholds

ONLY USED: handlers/ollama.py for LLM calls
NOT USED: Process management, HTTP calls, Redis
```

### 6.2 Retry System
```python
# core/stateless_retry_service.py - COMPLETE
Features:
  - Exponential backoff
  - Retry budgets
  - Error classification

ONLY USED: Workflow task retries
NOT USED: Process failures, service starts
```

### 6.3 Event System
```python
# core/events.py - COMPLETE
60+ Event Types Defined:
  - Process events
  - Workflow events
  - System events

PROBLEM: Events emitted but not consumed for recovery
```

## 7. API & UI ARCHITECTURE

### 7.1 API Structure
```
api/
├── routes/
│   ├── health.py      → Health endpoints (unused by monitor)
│   ├── triggers.py    → Workflow triggers
│   ├── workflows.py   → Workflow management
│   └── tasks.py       → Task management
├── middleware/
│   ├── auth.py        → JWT authentication
│   └── security.py    → Security headers
└── main.py            → FastAPI app
```

### 7.2 UI Structure
```
ui/
├── api/
│   └── app.py         → FastAPI UI server
├── templates/         → Jinja2 templates
└── static/           → CSS, JS assets
```

## 8. CRITICAL ARCHITECTURAL ISSUES

### 8.1 The Subprocess Deadlock
```python
# THE CORE BUG - process_manager.py:803
proc = subprocess.Popen(
    command,
    stdout=subprocess.PIPE,  # Buffer fills
    stderr=subprocess.PIPE,  # Never read
    preexec_fn=os.setsid    # Process blocks
)
# Process dies but reported as "running"
```

### 8.2 Integration Gaps
```
Components That Don't Talk:
- CircuitBreaker ↔ ProcessManager
- LeaderElection ↔ ProcessOrchestrator
- RetryService ↔ ServiceManager
- HealthMonitor ↔ Monitor Loop
- EventSystem ↔ Recovery Actions
```

### 8.3 State Synchronization
```
Three Truth Sources:
1. Redis says port 8000 is allocated
2. Filesystem says port 8000 is locked
3. OS says nothing is on port 8000
Result: System confused, restart fails
```

## 9. ARCHITECTURAL PATTERNS DETECTED

### 9.1 Good Patterns
- **Layered Architecture**: Clear separation of concerns
- **Worker Pattern**: Scalable task processing
- **Sharding**: Horizontal scaling ready
- **Event-Driven**: Events defined (not used)
- **Circuit Breaker**: Resilience pattern (not integrated)

### 9.2 Anti-Patterns
- **Dual Orchestration**: Two competing patterns
- **State Sprawl**: Three state systems
- **Synchronous Blocking**: In async codebase
- **Zombie Abstractions**: Components built but unused
- **False Abstractions**: PortManager doesn't manage ports

## 10. ACTUAL VS INTENDED ARCHITECTURE

### Intended (From Code Structure):
```
Distributed Workflow Orchestrator
  - Multi-machine deployment
  - Leader-based coordination
  - Self-healing with circuit breakers
  - Event-driven recovery
  - Horizontally scalable
```

### Actual (What Runs):
```
Local Process Manager (Broken)
  - Single machine only
  - No coordination
  - Processes die silently
  - No recovery
  - Can't scale (processes die)
```

## 11. THE REAL ARCHITECTURE

### What Actually Works:
1. **Redis Operations**: Basic get/set/streams
2. **Worker Framework**: Task processing
3. **API/UI Servers**: When manually started
4. **Instance Identity**: Properly generated

### What's Broken:
1. **Process Lifecycle**: Subprocess deadlock
2. **State Management**: Three conflicting systems
3. **Recovery**: No automatic recovery
4. **Monitoring**: Only checks existence

### What's Dormant:
1. **Circuit Breakers**: Built, not wired
2. **Leader Election**: Implemented, not used
3. **Async Subprocess**: Exists, not used
4. **Health Monitoring**: Defined, not checked

## 12. ARCHITECTURE RECOMMENDATIONS

### Option 1: Fix & Integrate (2-3 weeks)
```python
# Fix subprocess deadlock
async def start_process():
    proc = await asyncio.create_subprocess_exec(...)

# Wire existing components
ProcessManager.with_circuit_breaker()
ProcessOrchestrator.with_leader_election()
ServiceManager.with_health_monitoring()
```

### Option 2: Simplify (1 week)
```python
# Remove distributed features
# Single instance mode only
# Direct process management
# No Redis coordination
```

### Option 3: Containerize (1 week)
```yaml
# Let Docker/K8s handle it
services:
  api:
    image: gleitzeit
    command: uvicorn api
  ui:
    image: gleitzeit
    command: uvicorn ui
  worker:
    image: gleitzeit
    command: python -m worker
    scale: 4
```

## CONCLUSION

Gleitzeit has **two architectures**:
1. **The Aspirational**: A sophisticated distributed system
2. **The Actual**: A broken local process manager

The gap isn't in missing code—it's in **missing integration**. The components exist but operate in isolation, while the core subprocess management uses blocking I/O that causes everything to fail.

**Fix Priority**:
1. Replace blocking subprocess (stops the dying)
2. Pick ONE state system (Redis)
3. Wire existing components together
4. Enable the distributed features

The architecture is **sound in design** but **broken in execution**.