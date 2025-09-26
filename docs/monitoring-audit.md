# Gleitzeit Monitoring Audit & Design

## Executive Summary
This document audits the current monitoring capabilities in Gleitzeit 0.0.7's layered architecture and proposes comprehensive monitoring endpoints and CLI commands for complete observability.

## Current State Audit

### 1. Existing HTTP Endpoints

#### System Routes (`/system/*`)
| Endpoint | Method | Current Implementation | Purpose |
|----------|--------|----------------------|----------|
| `/system/status` | GET | ✅ Implemented | Overall system status (workers, queues, orchestrator) |
| `/system/metrics` | GET | ✅ Implemented | Workflow and task aggregated metrics |
| `/system/workers` | GET | ✅ Implemented | Worker status information |
| `/system/metrics/workflows` | GET | ✅ Implemented | Workflow-specific metrics |
| `/system/metrics/tasks` | GET | ✅ Implemented | Task-specific metrics |
| `/system/redis/info` | GET | ✅ Implemented | Redis server information |

#### Workflow Routes (`/workflows/*`)
| Endpoint | Method | Current Implementation | Purpose |
|----------|--------|----------------------|----------|
| `/workflows/list` | GET | ✅ Implemented | List all workflows |
| `/workflows/{id}` | GET | ✅ Implemented | Get workflow details |
| `/workflows/{id}/tasks` | GET | ✅ Implemented | Get workflow tasks |

### 2. Internal Monitoring Methods

#### ProcessOrchestrator
- `get_full_status()` - Returns comprehensive status including instance, services, workers

#### ServiceManager
- `get_service_status()` - Returns status of API and UI services

#### WorkerManager
- `get_worker_status()` - Returns worker counts, assignments, shards
- `health_check_workers()` - Performs health checks on all workers

#### SmartProcessManager
- `get_service_status()` - Low-level process information
- `monitor_services()` - Active monitoring with restart logic

### 3. CLI Commands

#### Current Commands
- `gleitzeit serve` - Start services with monitoring
- `gleitzeit workflow submit/status/cancel` - Workflow operations
- `gleitzeit monitor events/failures/metrics` - Basic monitoring
- `gleitzeit replay timeline/status/diff` - Workflow replay

### 4. Gaps Identified

1. **Process-Level Monitoring**
   - No endpoint for process restart history
   - Missing endpoint for port allocation status
   - No endpoint for instance identity details

2. **Layer-Specific Monitoring**
   - No dedicated endpoints per architecture layer
   - Missing aggregated layer health status

3. **Real-time Monitoring**
   - No WebSocket endpoints for live updates
   - Missing streaming endpoints for logs

4. **CLI Gaps**
   - No command to check process status
   - Missing commands for worker management
   - No command to view restart history

## Proposed Design

### 1. New HTTP Endpoints

#### Process Management Endpoints
```yaml
# Process-level monitoring
GET /processes/status
  Response: {
    "instance": {...},
    "services": {...},
    "workers": {...},
    "restarts": {...}
  }

GET /processes/restarts
  Response: {
    "services": {
      "api": {"count": 2, "last": "2025-09-24T10:00:00Z"},
      ...
    }
  }

GET /processes/ports
  Response: {
    "allocated": {"8000": "api", "8004": "ui"},
    "available": [8001, 8002, 8003],
    "conflicts": []
  }

GET /processes/{name}/logs
  Query: ?lines=100&follow=true
  Response: Stream of log lines

# Layer-specific endpoints
GET /layers/status
  Response: {
    "orchestrator": {"status": "healthy", ...},
    "service_manager": {"status": "healthy", ...},
    "worker_manager": {"status": "healthy", ...},
    "process_manager": {"status": "healthy", ...}
  }

GET /layers/{layer}/metrics
  Response: Layer-specific metrics

# Instance endpoints
GET /instance/info
  Response: {
    "id": "...",
    "name": "...",
    "role": "...",
    "capabilities": {...},
    "port_offset": 0
  }

GET /instance/health
  Response: {
    "healthy": true,
    "checks": {
      "redis": "ok",
      "processes": "ok",
      "disk_space": "ok"
    }
  }

# Worker-specific endpoints
GET /workers/{name}/status
  Response: Detailed worker status

GET /workers/{name}/shards
  Response: Shard assignment details

POST /workers/{type}/scale
  Body: {"replicas": 5}
  Response: Scaling status

# Real-time endpoints
WS /monitor/stream
  Streams: Real-time events

GET /monitor/tail/{stream}
  Response: SSE stream of events
```

### 2. New CLI Commands

#### Process Management Commands
```bash
# Process status commands
gleitzeit ps                          # List all processes (like docker ps)
gleitzeit ps --json                   # JSON output
gleitzeit ps --watch                  # Auto-refresh display

# Process inspection
gleitzeit inspect <process-name>      # Detailed process info
gleitzeit logs <process-name>         # View process logs
gleitzeit logs -f <process-name>      # Follow logs

# Restart management
gleitzeit restart <process-name>      # Restart specific process
gleitzeit restart --all               # Restart all processes
gleitzeit restart-history             # View restart history

# Instance commands
gleitzeit instance info               # Current instance details
gleitzeit instance list               # List all instances
gleitzeit instance health             # Health check

# Layer monitoring
gleitzeit layers status               # Status of all layers
gleitzeit layers --layer orchestrator # Specific layer status
```

#### Worker Management Commands
```bash
# Worker commands
gleitzeit workers list                # List all workers
gleitzeit workers status <name>       # Worker details
gleitzeit workers scale <type> <num>  # Scale workers
gleitzeit workers shards               # Show shard assignments
gleitzeit workers health              # Health check all workers
```

#### Monitoring Commands (Enhanced)
```bash
# Enhanced monitoring
gleitzeit monitor dashboard           # Interactive dashboard
gleitzeit monitor processes           # Process monitoring
gleitzeit monitor resources           # CPU/Memory usage
gleitzeit monitor queues              # Queue depths
gleitzeit monitor --export json       # Export monitoring data
```

#### Debugging Commands
```bash
# Debug commands
gleitzeit debug processes             # Process debug info
gleitzeit debug redis                 # Redis connectivity
gleitzeit debug config                # Configuration validation
gleitzeit debug ports                 # Port allocation info
```

### 3. Monitoring Dashboard Design

#### Terminal Dashboard Layout
```
┌─────────────────────────────────────────────────────────┐
│ Gleitzeit Monitor          Instance: production-001      │
├─────────────────────────────────────────────────────────┤
│ Services          │ Workers              │ Queues       │
├──────────────────┼─────────────────────┼───────────────┤
│ API    ✓ :8000   │ task_exec    2/2 ✓  │ load    : 0  │
│ UI     ✓ :8004   │ dependency   1/1 ✓  │ ready   : 5  │
│                  │ retry        1/1 ✓  │ complete: 42 │
│ Restarts: 0      │ loader       2/2 ✓  │ failed  : 3  │
├──────────────────┴─────────────────────┴───────────────┤
│ Recent Events                                           │
├─────────────────────────────────────────────────────────┤
│ 10:45:23 Workflow abc123 completed (3 tasks)           │
│ 10:45:20 Task xyz789 started on worker task_exec-0     │
│ 10:45:18 Worker dependency-0 processed 10 items        │
└─────────────────────────────────────────────────────────┘
[q]uit [r]efresh [l]ogs [w]orkers [s]ervices [h]elp
```

### 4. Metrics Collection Design

#### Metrics to Collect per Layer

**ProcessOrchestrator Metrics**
- Total uptime
- Startup time
- Configuration reload count
- Signal handling count

**ServiceManager Metrics**
- Service availability (%)
- Request count per service
- Response time per service
- Port conflicts resolved

**WorkerManager Metrics**
- Worker utilization (%)
- Tasks per worker
- Shard balance score
- Scale events

**SmartProcessManager Metrics**
- Process start/stop events
- Restart counts and reasons
- Memory usage per process
- CPU usage per process
- File descriptor count

### 5. Health Check Framework

#### Health Check Levels
```python
class HealthStatus(Enum):
    HEALTHY = "healthy"      # All checks pass
    DEGRADED = "degraded"    # Some non-critical issues
    UNHEALTHY = "unhealthy"  # Critical issues
    UNKNOWN = "unknown"      # Cannot determine

# Health check interface
class HealthCheck:
    async def check(self) -> HealthCheckResult:
        pass

# Implementations
class RedisHealthCheck(HealthCheck)
class ProcessHealthCheck(HealthCheck)
class DiskSpaceHealthCheck(HealthCheck)
class PortHealthCheck(HealthCheck)
class WorkerHealthCheck(HealthCheck)
```

### 6. Alerting Integration Points

#### Alert Triggers
- Process restart threshold exceeded
- Worker failure rate > threshold
- Queue depth > threshold
- Redis connection lost
- Disk space < threshold
- Port conflicts detected

#### Alert Channels (Future)
- Webhook notifications
- Email alerts
- Slack integration
- PagerDuty integration
- Custom script execution

## Implementation Priority

### Phase 1 - Core Monitoring (Immediate)
1. Implement `gleitzeit ps` command
2. Add `/processes/status` endpoint
3. Implement `gleitzeit logs` command
4. Add process restart history tracking

### Phase 2 - Enhanced Visibility
1. Worker management CLI commands
2. Layer-specific endpoints
3. Health check framework
4. Terminal dashboard

### Phase 3 - Advanced Features
1. Real-time streaming endpoints
2. Metrics aggregation
3. Alert system
4. Export capabilities

## Testing Strategy

### Monitoring Test Cases
1. **Process Monitoring**
   - Verify restart counts are tracked
   - Test process status accuracy
   - Validate port allocation tracking

2. **Worker Monitoring**
   - Test shard assignment visibility
   - Verify worker health checks
   - Test scaling operations

3. **Performance Testing**
   - Monitor endpoint response times
   - Test with high process counts
   - Validate metric collection overhead

## Documentation Requirements

1. **API Documentation**
   - OpenAPI spec for all endpoints
   - Response schema documentation
   - Example requests/responses

2. **CLI Documentation**
   - Man pages for commands
   - Help text for all options
   - Usage examples

3. **Monitoring Guide**
   - Best practices
   - Troubleshooting guide
   - Performance tuning

## Conclusion

The current monitoring capabilities provide a solid foundation, but significant gaps exist in process-level visibility, layer-specific monitoring, and CLI tooling. The proposed design addresses these gaps with:

1. **Comprehensive Endpoints**: 15+ new endpoints for complete visibility
2. **Rich CLI Commands**: 20+ new commands for operations and debugging
3. **Real-time Monitoring**: Streaming and WebSocket support
4. **Health Framework**: Structured health checking at all layers
5. **Future-Ready**: Extensible design for alerts and integrations

This design maintains the clean separation of the layered architecture while providing deep observability into each layer's operation.