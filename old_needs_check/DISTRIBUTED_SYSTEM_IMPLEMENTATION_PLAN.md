# Distributed System Implementation Plan - Gleitzeit 0.0.7

## Executive Summary
Transform Gleitzeit's half-implemented distributed architecture into a production-ready distributed workflow orchestration system with proper process management, health monitoring, and automatic recovery.

## Phase 1: Fix Core Process Management (Week 1)

### 1.1 Async Subprocess Management
**Problem:** Current subprocess.Popen with PIPE causes deadlock

**Solution:** Implement async subprocess handling with proper output streaming

```python
# New file: src/gleitzeit/core/async_process.py
class AsyncProcessManager:
    async def start_process(
        self,
        command: List[str],
        env: Dict[str, str],
        service_name: str
    ) -> AsyncProcess:
        # Use asyncio.create_subprocess_exec
        # Stream output to rotating log files
        # Non-blocking health checks
        # Graceful shutdown handling
```

**Deliverables:**
- [ ] AsyncProcessManager class
- [ ] Streaming log handler
- [ ] Process lifecycle events (started, healthy, unhealthy, stopped)
- [ ] Integration tests

### 1.2 Process Health Monitoring
**Problem:** Only checks if process exists, not if it's healthy

**Solution:** Implement proper health checks

```python
# New file: src/gleitzeit/core/health.py
class HealthMonitor:
    async def check_health(self, service: ServiceInfo) -> HealthStatus:
        # HTTP health endpoints for services
        # Process memory/CPU checks
        # Deadlock detection
        # Response time monitoring

class HealthStatus:
    healthy: bool
    latency_ms: float
    error_count: int
    last_check: datetime
    details: Dict[str, Any]
```

**Deliverables:**
- [ ] Health check protocol (HTTP, TCP, Process)
- [ ] Health status aggregation
- [ ] Configurable health thresholds
- [ ] Health history tracking

## Phase 2: Unified State Management (Week 2)

### 2.1 Single Source of Truth
**Problem:** Three separate systems (Redis, filesystem, OS) tracking same state

**Solution:** Redis as single source with local cache

```python
# Refactor: src/gleitzeit/core/state_manager.py
class DistributedStateManager:
    """Single source of truth for all component state"""

    def __init__(self):
        self.redis: Redis  # Primary state store
        self.local_cache: Dict  # Fast local reads
        self.sync_interval: int = 1  # seconds

    async def atomic_port_claim(
        self,
        port: int,
        instance_id: str,
        service: str
    ) -> bool:
        # Atomic Redis transaction
        # Update local cache
        # Emit state change event

    async def get_cluster_state(self) -> ClusterState:
        # All instances
        # All services
        # All ports
        # Health status
```

**Deliverables:**
- [ ] Unified state schema in Redis
- [ ] Atomic state operations (CAS)
- [ ] State synchronization protocol
- [ ] State recovery on restart

### 2.2 Event-Driven Architecture
**Problem:** No coordination between components

**Solution:** Event bus for component coordination

```python
# New file: src/gleitzeit/core/events.py
class EventBus:
    async def emit(self, event: Event):
        # Publish to Redis PubSub
        # Local handlers
        # Audit trail

    async def subscribe(self, pattern: str, handler: Callable):
        # Subscribe to events
        # Automatic reconnection
        # Event replay on recovery

# Event types
@dataclass
class ServiceStarted(Event):
    instance_id: str
    service_name: str
    port: int
    pid: int
    timestamp: datetime
```

**Deliverables:**
- [ ] Event bus implementation
- [ ] Event schema definitions
- [ ] Event persistence (audit log)
- [ ] Event replay mechanism

## Phase 3: Distributed Coordination (Week 3)

### 3.1 Leader Election
**Problem:** No coordination between instances

**Solution:** Redis-based leader election with Redlock

```python
# New file: src/gleitzeit/core/leadership.py
class LeaderElection:
    async def acquire_leadership(self) -> bool:
        # Redlock algorithm
        # Leader heartbeat
        # Automatic failover
        # Split-brain prevention

    async def watch_leader(self) -> LeaderInfo:
        # Monitor current leader
        # Detect leader failure
        # Trigger new election

class CoordinatorRole:
    """Only leader can:"""
    # - Assign ports
    # - Rebalance shards
    # - Initiate recovery
    # - Update configuration
```

**Deliverables:**
- [ ] Leader election protocol
- [ ] Leader responsibilities
- [ ] Follower behavior
- [ ] Split-brain handling

### 3.2 Service Discovery
**Problem:** Services don't know about each other

**Solution:** Dynamic service registry

```python
# New file: src/gleitzeit/core/discovery.py
class ServiceRegistry:
    async def register(self, service: ServiceInfo):
        # Register in Redis
        # Health check endpoint
        # Metadata (version, capabilities)
        # TTL with refresh

    async def discover(self, service_type: str) -> List[ServiceInfo]:
        # Find healthy services
        # Load balancing hints
        # Proximity/affinity rules

    async def watch(self, service_type: str) -> AsyncIterator[ServiceChange]:
        # Real-time updates
        # Service added/removed/updated
```

**Deliverables:**
- [ ] Service registration protocol
- [ ] Service discovery API
- [ ] Load balancing policies
- [ ] Service mesh integration ready

## Phase 4: Reliability & Recovery (Week 4)

### 4.1 Circuit Breakers
**Problem:** Cascading failures

**Solution:** Circuit breaker pattern

```python
# New file: src/gleitzeit/core/circuit_breaker.py
class CircuitBreaker:
    async def call(self, func: Callable, *args, **kwargs):
        # Track failures
        # Open circuit on threshold
        # Half-open testing
        # Automatic recovery

    states = ["CLOSED", "OPEN", "HALF_OPEN"]

    async def get_metrics(self) -> CircuitMetrics:
        # Failure rate
        # Response times
        # Circuit state history
```

**Deliverables:**
- [ ] Circuit breaker implementation
- [ ] Configurable thresholds
- [ ] Metrics collection
- [ ] Dashboard integration

### 4.2 Automatic Recovery
**Problem:** Manual intervention required for failures

**Solution:** Self-healing system

```python
# New file: src/gleitzeit/core/recovery.py
class RecoveryManager:
    async def detect_failure(self, component: Component) -> FailureType:
        # Process died
        # Health check failed
        # Deadlock detected
        # Resource exhaustion

    async def recover(self, failure: Failure) -> RecoveryResult:
        # Restart with backoff
        # Rebalance load
        # Failover to standby
        # Alert if unrecoverable

    recovery_strategies = {
        FailureType.PROCESS_DIED: restart_with_backoff,
        FailureType.PORT_CONFLICT: find_alternative_port,
        FailureType.UNHEALTHY: restart_or_replace,
        FailureType.OVERLOADED: scale_horizontally,
    }
```

**Deliverables:**
- [ ] Failure detection system
- [ ] Recovery strategies
- [ ] Exponential backoff
- [ ] Recovery metrics

## Phase 5: Observability (Week 5)

### 5.1 Distributed Tracing
**Problem:** Can't trace requests across components

**Solution:** OpenTelemetry integration

```python
# New file: src/gleitzeit/core/tracing.py
class TracingManager:
    def trace_span(self, operation: str):
        # Create span
        # Propagate context
        # Add metadata
        # Export to collector

    async def trace_workflow(self, workflow_id: str):
        # End-to-end trace
        # Component interactions
        # Performance bottlenecks
```

**Deliverables:**
- [ ] OpenTelemetry setup
- [ ] Span creation/propagation
- [ ] Trace collection
- [ ] Visualization setup

### 5.2 Metrics & Alerting
**Problem:** No visibility into system health

**Solution:** Prometheus metrics + alerting

```python
# New file: src/gleitzeit/core/metrics.py
class MetricsCollector:
    # Component metrics
    process_uptime = Gauge('process_uptime_seconds')
    request_latency = Histogram('request_latency_ms')
    error_rate = Counter('errors_total')

    # Business metrics
    workflows_running = Gauge('workflows_running')
    tasks_completed = Counter('tasks_completed_total')

    # System metrics
    port_allocation = Gauge('ports_allocated')
    redis_connections = Gauge('redis_connections')
```

**Deliverables:**
- [ ] Prometheus metrics
- [ ] Grafana dashboards
- [ ] Alert rules
- [ ] SLO monitoring

## Phase 6: Production Hardening (Week 6)

### 6.1 Security
```python
# Security improvements
- mTLS between components
- Redis AUTH/ACL
- Secret management (Vault integration)
- Audit logging
- Rate limiting
```

### 6.2 Performance
```python
# Performance optimizations
- Connection pooling
- Lazy loading
- Caching strategy
- Batch operations
- Async everywhere
```

### 6.3 Testing
```python
# Comprehensive testing
- Chaos engineering tests
- Load testing
- Failure injection
- Network partition tests
- Recovery testing
```

## Implementation Priority

### Critical Path (Must Have)
1. **Week 1**: Fix subprocess management (stops the dying)
2. **Week 2**: Unified state management (single source of truth)
3. **Week 3**: Health monitoring (know what's running)
4. **Week 4**: Automatic recovery (self-healing)

### Important (Should Have)
5. **Week 5**: Leader election (distributed coordination)
6. **Week 6**: Observability (metrics & tracing)

### Nice to Have
7. Circuit breakers
8. Service discovery
9. Production hardening

## Success Metrics

### Technical Metrics
- **Process reliability**: 99.9% uptime per component
- **Recovery time**: < 10 seconds for process failure
- **Health check latency**: < 100ms
- **State consistency**: 100% (no split-brain)
- **Port conflicts**: 0 (proper management)

### Operational Metrics
- **Manual interventions**: < 1 per week
- **Failed starts**: < 0.1%
- **Orphan processes**: 0
- **Stale locks**: 0
- **Alert noise**: < 5 false positives/day

## Risk Mitigation

### Risk 1: Breaking existing functionality
**Mitigation**: Feature flags for new systems, gradual rollout

### Risk 2: Increased complexity
**Mitigation**: Comprehensive documentation, automation

### Risk 3: Performance degradation
**Mitigation**: Benchmarking, profiling, optimization

### Risk 4: Distributed system issues
**Mitigation**: Chaos testing, circuit breakers, timeouts

## Rollout Strategy

### Phase 1: Local Development
- Feature flag: `GLEITZEIT_DISTRIBUTED=false`
- All features work locally
- No Redis required mode

### Phase 2: Single Machine Distribution
- Multiple instances on one machine
- Redis required
- Full health monitoring

### Phase 3: Multi-Machine Distribution
- True distributed deployment
- Service mesh ready
- Full observability

## Dependencies

### Required Libraries
```toml
# Add to pyproject.toml
dependencies = [
    "asyncio-mqtt>=0.16.0",  # Event bus
    "prometheus-client>=0.19.0",  # Metrics
    "opentelemetry-api>=1.20.0",  # Tracing
    "tenacity>=8.2.0",  # Retry/backoff
    "circuitbreaker>=2.0.0",  # Circuit breakers
]
```

### Infrastructure Requirements
- Redis 7.0+ (for streams, modules)
- Prometheus (metrics)
- Grafana (dashboards)
- Jaeger (tracing)

## Timeline

- **Week 1-2**: Core fixes (subprocess, state)
- **Week 3-4**: Distribution (coordination, recovery)
- **Week 5-6**: Production (observability, hardening)
- **Week 7-8**: Testing & documentation
- **Week 9-10**: Rollout & monitoring

## Conclusion

This plan transforms Gleitzeit from a broken local system to a production-ready distributed workflow orchestrator. The implementation is prioritized to:
1. Fix critical bugs first (processes dying)
2. Build proper foundations (state, health)
3. Add distributed features (coordination, recovery)
4. Harden for production (observability, security)

Total effort: 10 weeks for full implementation
Minimum viable: 4 weeks for working system