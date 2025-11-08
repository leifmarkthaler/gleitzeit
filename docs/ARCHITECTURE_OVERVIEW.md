# Gleitzeit Architecture Overview

**Version:** 0.0.7
**Last Updated:** November 2025

Complete overview of Gleitzeit's distributed workflow orchestration architecture.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Core Architecture](#core-architecture)
3. [Workers](#workers)
4. [Handlers](#handlers)
5. [Client SDK](#client-sdk)
6. [Advanced Topics](#advanced-topics)

---

## System Overview

Gleitzeit is a distributed workflow orchestration system built on Redis Streams with a unified worker architecture. All workers are equal peers that self-register and process events from Redis streams.

### Key Principles

- **Stateless Workers**: Workers are stateless and can be scaled horizontally
- **Event-Driven**: All communication happens through Redis streams
- **Self-Registration**: Workers register themselves and maintain heartbeats
- **Consolidated State**: Single source of truth for workflow state in Redis
- **Handler-Based Execution**: Extensible handler system for task execution

### System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         Clients                             │
│  (Python SDK, REST API, WebSocket)                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                      API Worker                             │
│  (FastAPI, Authentication, WebSocket)                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │    Redis Streams      │
         │   (Event Bus)         │
         └───────────┬───────────┘
                     │
         ┌───────────┴──────────────────────────────────────┐
         │                                                   │
         ▼                                                   ▼
┌────────────────────┐                           ┌────────────────────┐
│  Core Workers      │                           │  Support Workers   │
│  - Workflow Loader │                           │  - Reconciliation  │
│  - Workflow Submit │                           │  - Health Monitor  │
│  - Task Execution  │                           │  - Redis Monitor   │
│  - Dependency      │                           │  - Loki Exporter   │
│  - Timer           │                           │  - File Loader     │
│  - Signal          │                           │  - Replay          │
│  - Retry           │                           │                    │
│  - Monitor         │                           │                    │
└────────────────────┘                           └────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Task Handlers                            │
│  Python | HTTP | Timer | Signal | Validation | Ollama      │
│  vLLM | Workflow | File | Metrics                          │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Architecture

### Unified Worker Architecture

**📄 [UNIFIED_WORKER_ARCHITECTURE.md](UNIFIED_WORKER_ARCHITECTURE.md)**

All workers follow the same pattern:
- Self-register in Redis with heartbeats
- Listen to Redis streams
- Process events independently
- Stateless and horizontally scalable

**Key Concepts:**
- Worker registry: `{shard:0}:worker:registry:{type}:{id}`
- Heartbeat interval: 30 seconds
- TTL: 60 seconds
- Automatic cleanup of stale workers

### State Management

**📄 [CONSOLIDATED_STATE_ARCHITECTURE.md](CONSOLIDATED_STATE_ARCHITECTURE.md)**

Single source of truth for workflow state:
- **Key Pattern**: `workflow:state:{workflow_id}`
- **State Fields**: status, submitted_at, completed_tasks, failed_tasks, etc.
- **Two-Key Pattern**: `workflow:state` + `workflow:data`
- **Atomic Updates**: All state transitions are atomic

### Workflow Validation

**📄 [WORKFLOW_VALIDATION_ARCHITECTURE.md](WORKFLOW_VALIDATION_ARCHITECTURE.md)**

Stateless validation and transformation:
- In-memory handler registry with lazy loading
- Handler capabilities system
- Protocol-based validation
- Transform workflow → validate → route to execution

### Recovery System

**📄 [RECOVERY_SYSTEM.md](RECOVERY_SYSTEM.md)**

4-level recovery architecture:
1. **ACK Control**: Workers acknowledge messages
2. **Consumer Groups**: Redis manages message delivery
3. **XCLAIM Recovery**: Claim pending messages after timeout
4. **Retry Worker**: Exponential backoff for failed tasks

---

## Workers

Gleitzeit has **17 worker types** organized into core and support categories.

### Core Workers (Workflow Execution)

#### 1. **Workflow Loader Worker**
**File:** `workflow_loader_worker_v2.py`
**Purpose:** Validates and loads workflows, creates tasks
**Listens to:** `{shard:X}:workflow:load`
**Docs:** [WORKFLOW_VALIDATION_ARCHITECTURE.md](WORKFLOW_VALIDATION_ARCHITECTURE.md)

**Key Responsibilities:**
- Validate workflow structure
- Transform tasks (simplified → protocol-based schema)
- Create task records in Redis
- Emit workflow:submitted event

#### 2. **Workflow Submission Worker**
**File:** `workflow_submission_worker.py`
**Purpose:** Handles workflow submissions from workflow handler
**Listens to:** `{shard:X}:workflow:submission`
**Docs:** [WORKFLOW_HANDLER_EXECUTION_FLOW.md](WORKFLOW_HANDLER_EXECUTION_FLOW.md)

**Key Responsibilities:**
- Receive nested workflow submissions
- Route to workflow loader
- Track parent-child relationships

#### 3. **Task Execution Worker**
**File:** `task_execution_worker.py`
**Purpose:** Executes tasks using registered handlers
**Listens to:** `{shard:X}:task:ready`
**Docs:** [UNIFIED_WORKER_ARCHITECTURE.md](UNIFIED_WORKER_ARCHITECTURE.md)

**Key Responsibilities:**
- Load handler for task protocol
- Execute task with circuit breaker
- Store result in Redis
- Emit task:completed or task:failed events

#### 4. **Dependency Worker**
**File:** `dependency_worker.py`
**Purpose:** Manages task dependencies and readiness
**Listens to:** `{shard:X}:task:completed`, `{shard:X}:task:failed`, `{shard:X}:workflow:submitted`
**Docs:** [CONSOLIDATED_STATE_ARCHITECTURE.md](CONSOLIDATED_STATE_ARCHITECTURE.md)

**Key Responsibilities:**
- Track task completion
- Check dependency satisfaction
- Move tasks to ready state
- Resolve input variables from dependencies
- Update workflow state

#### 5. **Timer Worker**
**File:** `timer_worker.py`
**Purpose:** Manages timer tasks (sleep, delayed execution)
**Listens to:** Direct Redis scan of timer metadata
**Docs:** [timer-system.md](timer-system.md)

**Key Responsibilities:**
- Scan timer metadata every 1 second
- Check for expired timers
- Atomically delete and wake tasks
- Support both sleep and retry timers

#### 6. **Signal Worker**
**File:** `signal_worker.py`
**Purpose:** Manages signal communication (wait/send/broadcast)
**Listens to:** Direct Redis scan of signal metadata
**Docs:** [SIGNAL_SEND_BROADCAST.md](SIGNAL_SEND_BROADCAST.md)

**Key Responsibilities:**
- Leader election for signal processing
- Match signal senders with waiters
- Handle broadcast signals
- Timeout expired signal waits

#### 7. **Retry Worker**
**File:** `retry_worker.py`
**Purpose:** Handles task retries with exponential backoff
**Listens to:** `{shard:X}:task:retry`
**Docs:** [retry_mechanism.md](retry_mechanism.md)

**Key Responsibilities:**
- Classify errors (retryable vs non-retryable)
- Implement exponential backoff
- Track retry attempts
- Move to failed state after max retries

#### 8. **Workflow Monitor Worker**
**File:** `workflow_monitor_worker.py`
**Purpose:** Detects workflow completion and updates parent tasks
**Listens to:** `{shard:X}:task:completed`, `{shard:X}:task:failed`
**Docs:** [WORKFLOW_HANDLER_EXECUTION_FLOW.md](WORKFLOW_HANDLER_EXECUTION_FLOW.md)

**Key Responsibilities:**
- Detect when all tasks in workflow complete
- Mark workflow as completed or failed
- Wake parent task if workflow was invoked from another workflow

### Support Workers (Infrastructure)

#### 9. **API Worker**
**File:** `api_worker.py`
**Purpose:** Serves REST API and WebSocket connections
**Port:** 8000 (default)
**Docs:** [api/QUICK_START.md](api/QUICK_START.md), [api/API_AUTHENTICATION.md](api/API_AUTHENTICATION.md)

**Key Responsibilities:**
- Handle HTTP requests
- Manage WebSocket connections
- Session-based authentication
- Workflow submission endpoint
- Status and monitoring endpoints

#### 10. **UI Worker**
**File:** `ui_worker.py`
**Purpose:** Serves web UI for workflow monitoring
**Port:** 8004 (default)
**Docs:** [UNIFIED_WORKER_ARCHITECTURE.md](UNIFIED_WORKER_ARCHITECTURE.md)

**Key Responsibilities:**
- Serve HTML/CSS/JS frontend
- Real-time workflow status
- Task timeline visualization
- Event log viewing

#### 11. **Reconciliation Worker**
**File:** `reconciliation_worker.py`
**Purpose:** Cleanup and garbage collection

**Key Responsibilities:**
- Clean up orphaned tasks
- Remove expired workflows
- Prune old events from streams
- Maintain Redis memory usage

#### 12. **File Loader Worker**
**File:** `file_loader_worker.py`
**Purpose:** Loads workflow definitions from files

**Key Responsibilities:**
- Watch filesystem for workflow files
- Parse YAML/JSON workflow definitions
- Submit workflows automatically
- Hot-reload on file changes

#### 13. **Loki Exporter Worker**
**File:** `loki_exporter_worker.py`
**Purpose:** Exports logs to Grafana Loki

**Key Responsibilities:**
- Collect task execution logs
- Format logs for Loki
- Batch and push to Loki endpoint
- Add workflow/task metadata labels

#### 14. **Health Monitor Worker**
**File:** `health_monitor_worker.py`
**Purpose:** Monitors system health

**Key Responsibilities:**
- Track worker heartbeats
- Monitor Redis performance
- Alert on worker failures
- Expose health metrics

#### 15. **Redis Monitor Worker**
**File:** `redis_monitor_worker.py`
**Purpose:** Monitors Redis metrics

**Key Responsibilities:**
- Track stream lengths
- Monitor memory usage
- Detect slow commands
- Alert on Redis issues

#### 16. **Replay Worker**
**File:** `replay_worker.py`
**Purpose:** Replays events for debugging

**Key Responsibilities:**
- Capture event streams
- Store event history
- Replay events for debugging
- Support time-travel debugging

#### 17. **Time Advance Worker** ⚠️
**File:** `time_advance_worker.py`
**Status:** Deprecated (kept for backward compatibility)
**Note:** Replaced by direct timer scanning in TimerWorker

---

## Handlers

Gleitzeit has **10 handler types** for executing different task types.

### Core Handlers

#### **Python Handler**
**File:** `handlers/python.py`
**Protocol:** `python/v1`
**Methods:** `python/execute`
**Docs:** Documented in examples

Executes Python code in workflows.

#### **HTTP Handler**
**File:** `handlers/http.py`
**Protocol:** `http/v1`
**Methods:** `http/get`, `http/post`, `http/put`, `http/delete`, `http/patch`
**Docs:** [handlers/HTTP_HANDLER.md](handlers/HTTP_HANDLER.md)

Makes HTTP requests with full control over headers, body, timeout, etc.

#### **Timer Handler**
**File:** `handlers/timer.py`
**Protocol:** `timer/v1`
**Methods:** `timer/sleep`
**Docs:** [timer-system.md](timer-system.md)

Implements sleep/delay functionality for workflows.

#### **Signal Handler**
**File:** `handlers/signal.py`
**Protocol:** `signal/v1`
**Methods:** `signal/wait`, `signal/send`, `signal/broadcast`
**Docs:** [SIGNAL_SEND_BROADCAST.md](SIGNAL_SEND_BROADCAST.md)

Implements signal-based communication between tasks.

#### **Validation Handler**
**File:** `handlers/validation.py`
**Protocol:** `validation/v1`
**Methods:** `validation/evaluate`, `validation/assert`, `validation/gate`
**Docs:** [handlers/validation_handler.md](handlers/validation_handler.md)

Validates data and controls workflow flow with conditional logic.

#### **Workflow Handler**
**File:** `handlers/workflow.py`
**Protocol:** `workflow/v1`
**Methods:** `workflow/invoke`
**Docs:** [WORKFLOW_HANDLER_EXECUTION_FLOW.md](WORKFLOW_HANDLER_EXECUTION_FLOW.md)

Invokes nested workflows as tasks.

### LLM Handlers

#### **Ollama Handler**
**File:** `handlers/ollama.py`
**Protocol:** `ollama/v1`
**Methods:** `ollama/generate`, `ollama/chat`, `ollama/embeddings`
**Docs:** [handlers/ollama.md](handlers/ollama.md)

Integrates with Ollama for local LLM inference.

#### **vLLM Handler**
**File:** `handlers/vllm.py`
**Protocol:** `vllm/v1`
**Methods:** `vllm/completions`, `vllm/chat`, `vllm/models`
**Docs:** [vllm-handler-configuration.md](vllm-handler-configuration.md)

Integrates with vLLM for high-performance LLM inference.

### Utility Handlers

#### **File Handler**
**File:** `handlers/file.py`
**Protocol:** `file/v1`
**Methods:** `file/load`, `file/load_multiple`, `file/list`, `file/exists`, `file/metadata`
**Docs:** [handlers/FILE_HANDLER.md](handlers/FILE_HANDLER.md) 📝 *Coming soon*

Provides file operations for workflows.

#### **Metrics Handler**
**File:** `handlers/metrics.py`
**Protocol:** `metrics/v1`
**Methods:** `metrics/record`, `metrics/query`
**Docs:** [handlers/METRICS_HANDLER.md](handlers/METRICS_HANDLER.md) 📝 *Coming soon*

Records and queries workflow execution metrics.

---

## Client SDK

### Python Client

**📄 [CLIENT_GUIDE.md](CLIENT_GUIDE.md)**
**📄 [EASY_CLIENT_GUIDE.md](EASY_CLIENT_GUIDE.md)**

Complete Python SDK for interacting with Gleitzeit:
- Async and sync interfaces
- Session-based authentication
- Workflow submission and monitoring
- WebSocket support for real-time updates
- Task result retrieval

### REST API

**📄 [api/QUICK_START.md](api/QUICK_START.md)**
**📄 [api/API_AUTHENTICATION.md](api/API_AUTHENTICATION.md)**

REST API for workflow operations:
- `POST /workflows/submit` - Submit workflow
- `GET /workflows/{id}` - Get workflow status
- `GET /workflows/{id}/tasks` - Get workflow tasks
- `GET /tasks/{id}/result` - Get task result
- Authentication via sessions, JWT, or API keys

### WebSocket API

**📄 [python-client-websocket-examples.md](python-client-websocket-examples.md)**

Real-time workflow monitoring:
- Subscribe to workflow events
- Receive task completion notifications
- Stream task logs
- Monitor system status

---

## Advanced Topics

### Multi-Machine Deployment

**📄 [multi-machine-deployment.md](multi-machine-deployment.md)**
**📄 [api-server-multi-machine.md](api-server-multi-machine.md)**

Deploy Gleitzeit across multiple machines:
- Coordinator and worker roles
- Shared Redis instance
- Load balancing strategies
- High availability setup

### Circuit Breaker Pattern

**📄 [features/circuit_breaker.md](features/circuit_breaker.md)**

Fault tolerance for handler execution:
- Automatic failure detection
- Half-open recovery attempts
- Configurable thresholds
- Integration with all handlers

### Event Timeline

**📄 [features/event_timeline.md](features/event_timeline.md)**
**📄 [features/task_timeline.md](features/task_timeline.md)**

Track workflow and task execution:
- Event log with timestamps
- State transitions
- Error tracking
- Performance analysis

### Handler Tracking

**📄 [features/handler_tracking.md](features/handler_tracking.md)**

Monitor handler performance:
- Execution time metrics
- Success/failure rates
- Resource usage
- Handler-specific metrics

### Conditional Execution

**📄 [architecture/conditional_execution.md](architecture/conditional_execution.md)**

Control workflow flow with conditions:
- XOR pattern for branching
- Validation gates
- Dynamic task selection
- Conditional dependencies

### Patterns

**📄 [patterns/xor_pattern.md](patterns/xor_pattern.md)**

Common workflow patterns:
- XOR (exclusive choice)
- Fan-out/Fan-in
- Sequential pipelines
- Parallel processing

---

## Development

### Creating Custom Handlers

**📄 [HANDLER_DEVELOPMENT_GUIDE.md](HANDLER_DEVELOPMENT_GUIDE.md)** 📝 *Coming soon*

Learn how to create custom handlers:
- Handler base class
- Capabilities system
- Circuit breaker integration
- Testing guidelines
- Registration and deployment

### Configuration

**📄 [UNIFIED_WORKER_ARCHITECTURE.md](UNIFIED_WORKER_ARCHITECTURE.md#configuration)**

Configure Gleitzeit via `gleitzeit.yaml`:
- Worker scaling
- Port configuration
- Redis connection
- Log levels
- Feature flags

### Monitoring and Troubleshooting

**📄 [UNIFIED_WORKER_ARCHITECTURE.md](UNIFIED_WORKER_ARCHITECTURE.md#monitoring)**
**📄 [timer-system.md](timer-system.md#troubleshooting)**
**📄 [retry_mechanism.md](retry_mechanism.md#troubleshooting)**

Monitor system health:
- `gleitzeit ps` - List running services
- Worker registry inspection
- Stream length monitoring
- Error classification
- Performance metrics

---

## Quick Navigation

### By Role

**New Users:**
1. [QUICK_START.md](api/QUICK_START.md) - Get started in 5 minutes
2. [EASY_CLIENT_GUIDE.md](EASY_CLIENT_GUIDE.md) - Python SDK basics
3. [Examples](/examples/) - Working code examples

**Advanced Users:**
1. [UNIFIED_WORKER_ARCHITECTURE.md](UNIFIED_WORKER_ARCHITECTURE.md) - System architecture
2. [CONSOLIDATED_STATE_ARCHITECTURE.md](CONSOLIDATED_STATE_ARCHITECTURE.md) - State management
3. [RECOVERY_SYSTEM.md](RECOVERY_SYSTEM.md) - Fault tolerance

**Plugin Developers:**
1. [HANDLER_DEVELOPMENT_GUIDE.md](HANDLER_DEVELOPMENT_GUIDE.md) - Create handlers
2. [handlers/](/docs/handlers/) - Handler documentation
3. [WORKFLOW_VALIDATION_ARCHITECTURE.md](WORKFLOW_VALIDATION_ARCHITECTURE.md) - Validation system

### By Topic

**Workflows:**
- [WORKFLOW_VALIDATION_ARCHITECTURE.md](WORKFLOW_VALIDATION_ARCHITECTURE.md)
- [WORKFLOW_HANDLER_EXECUTION_FLOW.md](WORKFLOW_HANDLER_EXECUTION_FLOW.md)
- [CLIENT_GUIDE.md](CLIENT_GUIDE.md)

**State Management:**
- [CONSOLIDATED_STATE_ARCHITECTURE.md](CONSOLIDATED_STATE_ARCHITECTURE.md)
- [RECOVERY_SYSTEM.md](RECOVERY_SYSTEM.md)
- [retry_mechanism.md](retry_mechanism.md)

**Timing and Signals:**
- [timer-system.md](timer-system.md)
- [SIGNAL_SEND_BROADCAST.md](SIGNAL_SEND_BROADCAST.md)
- [signals-vs-timers-comparison.md](signals-vs-timers-comparison.md)

**Handlers:**
- [handlers/HTTP_HANDLER.md](handlers/HTTP_HANDLER.md)
- [handlers/validation_handler.md](handlers/validation_handler.md)
- [handlers/ollama.md](handlers/ollama.md)
- [vllm-handler-configuration.md](vllm-handler-configuration.md)

---

## Architecture Principles

### Design Philosophy

1. **Stateless Workers** - All workers are stateless and disposable
2. **Event-Driven** - Communication through Redis streams only
3. **Idempotent** - Operations can be retried safely
4. **Self-Healing** - Automatic recovery from failures
5. **Horizontally Scalable** - Add more workers for more throughput

### Key Technologies

- **Redis Streams** - Event bus and message queue
- **Consumer Groups** - Distribute work across workers
- **Atomic Operations** - Lua scripts for consistency
- **TTL-based Cleanup** - Automatic resource cleanup
- **Circuit Breakers** - Fault isolation

---

## Version Information

**Current Version:** 0.0.7
**Release Date:** November 2025
**Python Version:** 3.11+
**Redis Version:** 4.5.0+

---

## Additional Resources

- **Examples:** `/examples/` - 10+ working code examples
- **Tests:** `/tests/` - Unit and integration tests
- **Archive:** `/docs/archive/` - Historical design decisions
- **Config:** `/config/` - Example configuration files

---

## Need Help?

- **Documentation:** You're reading it!
- **Examples:** Check `/examples/` for working code
- **GitHub Issues:** Report bugs and request features
- **Architecture Review:** [DOCUMENTATION_REVIEW_SUMMARY.md](DOCUMENTATION_REVIEW_SUMMARY.md)

---

*Last Updated: November 8, 2025*
