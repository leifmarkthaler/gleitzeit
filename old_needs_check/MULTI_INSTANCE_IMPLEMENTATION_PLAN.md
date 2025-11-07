# Multi-Instance Gleitzeit Implementation Plan

## Overview
Transform Gleitzeit from single-instance to multi-instance, multi-machine architecture with service discovery, federation, and intelligent routing.

## Phase 1: Foundation (Week 1-2)
**Goal**: Instance identification and core abstractions

### 1.1 Instance Identity System
```python
# src/gleitzeit/core/instance.py
class InstanceIdentity:
    """Core identity for each Gleitzeit instance"""
    def __init__(self):
        self.instance_id = self._generate_instance_id()
        self.machine_id = socket.gethostname()
        self.deployment_id = f"{self.machine_id}:{self.instance_id}"
        self.started_at = datetime.utcnow()
        self.capabilities = self._detect_capabilities()
```

**Tasks**:
- [ ] Create `core/instance.py` with InstanceIdentity class
- [ ] Add instance ID generation logic (UUID + readable prefix)
- [ ] Implement capability detection (GPU, memory, CPU cores)
- [ ] Add instance configuration loading from YAML/env
- [ ] Create instance metadata serialization

**Files to modify**:
- `/src/gleitzeit/core/instance.py` (new)
- `/src/gleitzeit/config/instance_config.yaml` (new)
- `/src/gleitzeit/cli/serve.py` (integrate InstanceIdentity)

### 1.2 Configuration Management
```yaml
# config/instance_config.yaml
instance:
  name: "${GLEITZEIT_INSTANCE_NAME:-default}"
  role: "${GLEITZEIT_ROLE:-standalone}"
  port_offset: "${GLEITZEIT_PORT_OFFSET:-0}"

networking:
  bind_address: "${GLEITZEIT_BIND_ADDRESS:-0.0.0.0}"
  advertise_address: "${GLEITZEIT_ADVERTISE_ADDRESS:-auto}"

redis:
  url: "${REDIS_URL:-redis://localhost:6379}"
  namespace: "gleitzeit:${instance.name}"
```

**Tasks**:
- [ ] Create configuration schema for instances
- [ ] Implement environment variable interpolation
- [ ] Add configuration validation
- [ ] Create configuration merger for CLI overrides
- [ ] Add configuration hot-reload support

---

## Phase 2: Service Registry (Week 2-3)
**Goal**: Service discovery and registration in Redis

### 2.1 Service Registry Implementation
```python
# src/gleitzeit/core/registry.py
class ServiceRegistry:
    """Manages service registration and discovery"""
    async def register_service(self, service_info: ServiceInfo):
        # Register with TTL and health info

    async def discover_service(self, service_name: str) -> List[ServiceInfo]:
        # Find available service instances

    async def heartbeat_loop(self):
        # Maintain service registration TTLs
```

**Tasks**:
- [ ] Create ServiceInfo data model
- [ ] Implement Redis-based service registry
- [ ] Add TTL-based health checking
- [ ] Create service discovery with filtering
- [ ] Implement heartbeat mechanism
- [ ] Add service deregistration on shutdown

**Files to create/modify**:
- `/src/gleitzeit/core/registry.py` (new)
- `/src/gleitzeit/models/service.py` (new)
- `/src/gleitzeit/api/main.py` (register API service)
- `/src/gleitzeit/ui/api/app.py` (register UI service)

### 2.2 Health Checking System
```python
# src/gleitzeit/core/health.py
class HealthChecker:
    """Monitors service health across instances"""
    async def check_service_health(self, service_endpoint: str):
        # HTTP health check

    async def check_instance_health(self, instance_id: str):
        # Check all services in instance
```

**Tasks**:
- [ ] Implement HTTP health check endpoints
- [ ] Add Redis connectivity checks
- [ ] Create resource usage monitoring
- [ ] Implement health status aggregation
- [ ] Add alerting for unhealthy services

---

## Phase 3: Process Management Reform (Week 3-4)
**Goal**: Fix startup loop with instance-aware process management

### 3.1 Smart Process Manager
```python
# src/gleitzeit/core/process_manager.py
class SmartProcessManager:
    """Instance-aware process management"""
    def __init__(self, instance_identity: InstanceIdentity):
        self.instance = instance_identity
        self.owned_processes = {}
        self.registry = ServiceRegistry()

    async def start_service(self, service_name: str):
        # Check if already running (locally or remotely)
        # Claim ownership if available
        # Start with proper isolation
```

**Tasks**:
- [ ] Refactor current serve.py to use SmartProcessManager
- [ ] Implement process ownership tracking
- [ ] Add distributed locking for service claims
- [ ] Create exponential backoff for restarts
- [ ] Add process group isolation
- [ ] Implement graceful shutdown coordination

**Files to modify**:
- `/src/gleitzeit/core/process_manager.py` (new)
- `/src/gleitzeit/cli/serve.py` (major refactor)
- `/src/gleitzeit/utils/process.py` (new, process utilities)

### 3.2 Port Management
```python
# src/gleitzeit/core/ports.py
class PortManager:
    """Manages port allocation for services"""
    def get_service_port(self, service_name: str) -> int:
        # Calculate port based on instance offset

    def find_available_port(self, base_port: int) -> int:
        # Find next available port in range
```

**Tasks**:
- [ ] Implement port offset calculation
- [ ] Add port availability checking
- [ ] Create port reservation system
- [ ] Add port conflict resolution
- [ ] Implement port range management

---

## Phase 4: Cross-Instance Communication (Week 4-5)
**Goal**: Enable instances to communicate and coordinate

### 4.1 Instance Client
```python
# src/gleitzeit/client/instance_client.py
class InstanceClient:
    """Client for cross-instance communication"""
    async def get_remote_client(self, instance_id: str):
        # Get or create client for remote instance

    async def route_workflow(self, workflow: dict):
        # Route to appropriate instance
```

**Tasks**:
- [ ] Create instance discovery mechanism
- [ ] Implement HTTP client pooling
- [ ] Add authentication between instances
- [ ] Create request routing logic
- [ ] Implement circuit breaker pattern
- [ ] Add request tracing

### 4.2 Workflow Router
```python
# src/gleitzeit/routing/workflow_router.py
class WorkflowRouter:
    """Routes workflows to appropriate instances"""
    async def determine_target_instance(self, workflow: dict):
        # Use routing rules and sharding

    async def balance_load(self):
        # Distribute workflows based on load
```

**Tasks**:
- [ ] Implement routing rule engine
- [ ] Add consistent hashing for sharding
- [ ] Create load balancing algorithms
- [ ] Add sticky session support
- [ ] Implement workflow migration
- [ ] Create routing metrics

---

## Phase 5: Federation & Clustering (Week 5-6)
**Goal**: Full multi-machine federation

### 5.1 Cluster Management
```python
# src/gleitzeit/cluster/manager.py
class ClusterManager:
    """Manages cluster membership and coordination"""
    async def join_cluster(self):
        # Join existing cluster or create new

    async def elect_leader(self):
        # Leader election for coordination
```

**Tasks**:
- [ ] Implement cluster membership protocol
- [ ] Add leader election (using Redis)
- [ ] Create cluster state synchronization
- [ ] Add split-brain protection
- [ ] Implement cluster resharding
- [ ] Add cluster monitoring

### 5.2 Data Synchronization
```python
# src/gleitzeit/sync/data_sync.py
class DataSynchronizer:
    """Synchronizes data across instances"""
    async def sync_workflow_state(self):
        # Sync workflow state across instances
```

**Tasks**:
- [ ] Implement state synchronization protocol
- [ ] Add conflict resolution
- [ ] Create eventual consistency guarantees
- [ ] Add data versioning
- [ ] Implement sync checkpoints

---

## Phase 6: Monitoring & Operations (Week 6-7)
**Goal**: Operational excellence for multi-instance deployment

### 6.1 Metrics & Monitoring
```python
# src/gleitzeit/monitoring/metrics.py
class MetricsCollector:
    """Collects metrics across all instances"""
    async def collect_instance_metrics(self):
        # Gather metrics from all instances
```

**Tasks**:
- [ ] Add Prometheus metrics endpoint
- [ ] Implement cross-instance metric aggregation
- [ ] Create performance dashboards
- [ ] Add distributed tracing
- [ ] Implement log aggregation
- [ ] Create alerting rules

### 6.2 Admin Tools
```python
# src/gleitzeit/admin/cli.py
@click.command()
def list_instances():
    """List all active Gleitzeit instances"""

@click.command()
def migrate_workflow(workflow_id, target_instance):
    """Migrate workflow to different instance"""
```

**Tasks**:
- [ ] Create instance management CLI
- [ ] Add cluster status commands
- [ ] Implement workflow migration tools
- [ ] Create debugging utilities
- [ ] Add backup/restore commands
- [ ] Implement rolling update support

---

## Testing Strategy

### Unit Tests
- [ ] Instance identity generation
- [ ] Service registry operations
- [ ] Port management logic
- [ ] Routing decisions
- [ ] Health checking

### Integration Tests
- [ ] Multi-instance startup
- [ ] Service discovery across instances
- [ ] Workflow routing
- [ ] Instance failure handling
- [ ] Cluster formation

### Chaos Testing
- [ ] Random instance kills
- [ ] Network partitions
- [ ] Redis failures
- [ ] Port conflicts
- [ ] Resource exhaustion

---

## Migration Path

### Stage 1: Backward Compatible (Week 1)
- New code works with single instance
- No breaking changes
- Feature flags for new functionality

### Stage 2: Opt-in Multi-Instance (Week 3)
- Enable with `--multi-instance` flag
- Documentation for setup
- Migration guide

### Stage 3: Default Multi-Instance (Week 6)
- Multi-instance by default
- Single instance via `--standalone`
- Deprecation notices

### Stage 4: Full Migration (Week 8)
- Remove legacy code
- Update all documentation
- Release as v0.1.0

---

## Risk Mitigation

### Technical Risks
1. **Data Consistency**: Use Redis transactions and locks
2. **Network Partitions**: Implement split-brain protection
3. **Performance Overhead**: Add caching and connection pooling
4. **Complexity**: Extensive documentation and examples

### Operational Risks
1. **Rollback Plan**: Keep feature flags for quick disable
2. **Monitoring**: Add comprehensive metrics from day 1
3. **Testing**: Automated test suite for all scenarios
4. **Documentation**: Step-by-step guides for operations

---

## Success Metrics

### Performance
- [ ] < 100ms service discovery latency
- [ ] < 1s instance startup time
- [ ] > 99.9% uptime per instance
- [ ] < 5% overhead vs single instance

### Scalability
- [ ] Support 100+ instances
- [ ] Handle 10k+ workflows/second
- [ ] Linear scaling with instances
- [ ] Automatic load balancing

### Reliability
- [ ] Zero data loss on instance failure
- [ ] < 5s recovery time
- [ ] Graceful degradation
- [ ] No startup loops 😄

---

## Documentation Deliverables

1. **Architecture Guide**: Complete system design
2. **Operations Manual**: Deployment and management
3. **API Reference**: All new APIs documented
4. **Migration Guide**: Step-by-step migration
5. **Troubleshooting Guide**: Common issues and solutions
6. **Performance Tuning**: Optimization guidelines

---

## Timeline Summary

- **Week 1-2**: Foundation & Configuration
- **Week 2-3**: Service Registry
- **Week 3-4**: Process Management
- **Week 4-5**: Cross-Instance Communication
- **Week 5-6**: Federation & Clustering
- **Week 6-7**: Monitoring & Operations
- **Week 7-8**: Testing & Documentation
- **Week 8**: Release

## Next Steps

1. Review and approve plan
2. Create detailed tickets for each task
3. Set up development environment
4. Begin Phase 1 implementation
5. Schedule weekly progress reviews

---

## Appendix: Key Design Decisions

### Why Redis for Coordination?
- Already required for Gleitzeit
- Supports distributed locks
- TTL for health checking
- Pub/sub for events

### Why Not Kubernetes?
- Keep deployment simple
- Work in any environment
- No orchestrator dependency
- Lower operational complexity

### Why Instance-Based Architecture?
- Clear ownership boundaries
- Easier debugging
- Natural sharding
- Flexible deployment