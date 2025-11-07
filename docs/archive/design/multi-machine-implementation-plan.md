# Multi-Machine Redis Port Locks: Implementation Plan

## Executive Summary
This document provides a detailed, phased implementation plan for transitioning Gleitzeit from file-based local port locks to Redis-based distributed port coordination, enabling true multi-machine deployments.

## Implementation Phases Overview

```
Phase 0: Foundation (Week 1)
├── Redis connection improvements
├── Instance identity enhancements
└── Compatibility layer setup

Phase 1: Port Management (Week 2-3)
├── RedisPortManager implementation
├── Parallel operation with file-based
└── Migration tools

Phase 2: Service Registry (Week 4-5)
├── Multi-instance service support
├── Service discovery API
└── Health check integration

Phase 3: Multi-Machine Support (Week 6-7)
├── Machine registry
├── Machine-scoped operations
└── Cross-machine coordination

Phase 4: Monitoring & Tools (Week 8)
├── Enhanced PS command
├── Machine-aware monitoring
└── Diagnostic tools

Phase 5: Production Rollout (Week 9-10)
├── Gradual deployment
├── Performance validation
└── Cleanup & documentation
```

---

## Phase 0: Foundation (Week 1)

### Objectives
- Strengthen Redis infrastructure
- Enhance instance identity for multi-machine
- Create compatibility layer for gradual migration

### Tasks

#### 0.1 Redis Connection Management
**File:** `src/gleitzeit/core/redis_manager.py` (NEW)
```python
class RedisManager:
    """Centralized Redis connection management with retry and failover"""

    def __init__(self, urls: List[str], timeout: int = 5):
        self.primary_url = urls[0]
        self.fallback_urls = urls[1:] if len(urls) > 1 else []
        self.connection_pool = None
        self.health_check_interval = 30

    async def get_connection(self) -> aioredis.Redis:
        """Get Redis connection with automatic failover"""

    async def execute_with_retry(self, func, max_retries=3):
        """Execute Redis operation with retry logic"""
```

**Deliverables:**
- [ ] Redis connection pooling
- [ ] Automatic failover support
- [ ] Connection health monitoring
- [ ] Retry logic for transient failures

#### 0.2 Enhanced Instance Identity
**File:** `src/gleitzeit/core/instance.py` (MODIFY)
```python
class InstanceIdentity:
    def __init__(self, ...):
        # ADD: Machine awareness
        self.machine_id = self._get_machine_id()
        self.machine_ip_internal = self._get_internal_ip()
        self.machine_ip_external = self._get_external_ip()
        self.region = os.getenv('GLEITZEIT_REGION', 'default')
        self.zone = os.getenv('GLEITZEIT_ZONE', 'default')
        self.machine_tags = self._get_machine_tags()
```

**Deliverables:**
- [ ] Machine ID detection (hostname + MAC hash)
- [ ] Internal/external IP detection
- [ ] Region/zone configuration
- [ ] Machine capability detection

#### 0.3 Feature Flag System
**File:** `src/gleitzeit/core/feature_flags.py` (NEW)
```python
class FeatureFlags:
    """Control feature rollout"""

    FLAGS = {
        'redis_port_manager': False,  # Use Redis for ports
        'multi_machine_mode': False,   # Enable multi-machine
        'service_discovery': False,    # Enable discovery API
        'machine_registry': False,     # Use machine registry
    }

    @classmethod
    def is_enabled(cls, flag: str) -> bool:
        return os.getenv(f'GLEITZEIT_FF_{flag.upper()}',
                        str(cls.FLAGS.get(flag, False))) == 'True'
```

**Deliverables:**
- [ ] Feature flag framework
- [ ] Environment variable overrides
- [ ] Configuration file support
- [ ] Runtime flag updates

---

## Phase 1: Port Management (Week 2-3)

### Objectives
- Implement Redis-based port manager
- Run parallel with file-based system
- Provide migration tools

### Tasks

#### 1.1 RedisPortManager Implementation
**File:** `src/gleitzeit/core/redis_port_manager.py` (NEW)

```python
class RedisPortManager:
    """Redis-based distributed port management"""

    async def allocate_port(self, service_name: str,
                           machine_scope: bool = True) -> int:
        """Allocate port with machine scoping option"""

    async def release_port(self, port: int) -> None:
        """Release allocated port"""

    async def refresh_ttl(self, port: int) -> None:
        """Refresh port allocation TTL"""

    async def get_allocated_ports(self, machine_id: str = None) -> Dict:
        """Get all allocated ports (optionally by machine)"""
```

**Deliverables:**
- [ ] Atomic port allocation with Lua scripts
- [ ] TTL-based automatic cleanup
- [ ] Machine-scoped allocation support
- [ ] Port conflict detection
- [ ] Port range pre-allocation

#### 1.2 Hybrid Port Manager
**File:** `src/gleitzeit/core/hybrid_port_manager.py` (NEW)

```python
class HybridPortManager:
    """Manages both file and Redis port systems during migration"""

    def __init__(self, file_manager, redis_manager):
        self.file_manager = file_manager
        self.redis_manager = redis_manager
        self.mode = self._determine_mode()

    async def allocate_port(self, service_name: str) -> int:
        if self.mode == 'parallel':
            # Allocate in both, prefer Redis
            redis_port = await self.redis_manager.allocate_port(service_name)
            file_port = self.file_manager.allocate_port(service_name)
            self._log_discrepancy(redis_port, file_port)
            return redis_port
```

**Deliverables:**
- [ ] Parallel operation mode
- [ ] Discrepancy logging
- [ ] Automatic fallback on Redis failure
- [ ] Migration status tracking

#### 1.3 Migration Tools
**File:** `src/gleitzeit/cli/migrate_commands.py` (NEW)

```python
@click.command('migrate-ports')
@click.option('--dry-run', is_flag=True)
def migrate_ports(dry_run: bool):
    """Migrate port allocations from file to Redis"""

@click.command('validate-ports')
def validate_ports():
    """Validate port allocation consistency"""
```

**Deliverables:**
- [ ] Port migration script
- [ ] Validation tool
- [ ] Rollback capability
- [ ] Progress reporting

---

## Phase 2: Service Registry (Week 4-5)

### Objectives
- Enable multiple instances of same service type
- Implement service discovery
- Add health monitoring

### Tasks

#### 2.1 Service Registry Implementation
**File:** `src/gleitzeit/core/service_registry.py` (NEW)

```python
class ServiceRegistry:
    """Multi-instance service registry"""

    async def register_service(self, service_type: str,
                              instance_id: str,
                              machine_id: str,
                              endpoint: str) -> None:
        """Register a service instance"""

    async def discover_services(self, service_type: str,
                               region: str = None) -> List[ServiceInstance]:
        """Discover all instances of a service type"""

    async def update_health(self, service_type: str,
                           instance_id: str,
                           healthy: bool) -> None:
        """Update service health status"""
```

**Deliverables:**
- [ ] Service registration with TTL
- [ ] Multi-instance support
- [ ] Region-aware discovery
- [ ] Health status tracking

#### 2.2 Update Process Manager
**File:** `src/gleitzeit/core/process_manager.py` (MODIFY)

```python
async def claim_service(self, service_name: str, port: int):
    """Updated to support multiple instances"""

    if FeatureFlags.is_enabled('multi_machine_mode'):
        # Machine-scoped ownership
        ownership_key = f"service:ownership:{self.machine_id}:{service_name}"
        # Register in service instances
        await self.service_registry.register_service(
            service_name, self.instance.instance_id,
            self.instance.machine_id, f"http://{self.instance.machine_ip}:{port}"
        )
    else:
        # Legacy single-instance mode
        ownership_key = f"service:ownership:{service_name}"
```

**Deliverables:**
- [ ] Multi-instance claim logic
- [ ] Service registry integration
- [ ] Backward compatibility
- [ ] Ownership conflict resolution

#### 2.3 Service Discovery API
**File:** `src/gleitzeit/api/discovery.py` (NEW)

```python
@router.get("/discovery/services/{service_type}")
async def discover_services(service_type: str,
                           region: Optional[str] = None,
                           healthy_only: bool = True):
    """REST API for service discovery"""

@router.get("/discovery/health/{service_type}/{instance_id}")
async def get_service_health(service_type: str, instance_id: str):
    """Get health status of specific service instance"""
```

**Deliverables:**
- [ ] Discovery REST endpoints
- [ ] Health check endpoints
- [ ] Load balancer integration format
- [ ] WebSocket subscriptions for changes

---

## Phase 3: Multi-Machine Support (Week 6-7)

### Objectives
- Implement machine registry
- Enable cross-machine coordination
- Support geographic distribution

### Tasks

#### 3.1 Machine Registry
**File:** `src/gleitzeit/core/machine_registry.py` (NEW)

```python
class MachineRegistry:
    """Registry for all machines in the cluster"""

    async def register_machine(self, machine_id: str,
                              machine_info: MachineInfo) -> None:
        """Register a machine in the cluster"""

    async def get_machines(self, region: str = None) -> List[MachineInfo]:
        """Get all registered machines"""

    async def update_machine_health(self, machine_id: str) -> None:
        """Update machine heartbeat"""
```

**Deliverables:**
- [ ] Machine registration
- [ ] Heartbeat mechanism
- [ ] Machine capability storage
- [ ] Stale machine cleanup

#### 3.2 Cross-Machine Worker Coordination
**File:** `src/gleitzeit/core/worker_manager.py` (MODIFY)

```python
async def distribute_shards_globally(self):
    """Distribute shards across all machines"""

    machines = await self.machine_registry.get_machines()
    workers = await self._get_all_workers(machines)

    # Intelligent shard distribution based on:
    # - Machine capabilities
    # - Network latency
    # - Current load
    distribution = self._calculate_optimal_distribution(workers, machines)
    await self._apply_shard_distribution(distribution)
```

**Deliverables:**
- [ ] Global shard distribution
- [ ] Load-aware assignment
- [ ] Rebalancing capability
- [ ] Failover handling

#### 3.3 Network Topology Awareness
**File:** `src/gleitzeit/core/network_topology.py` (NEW)

```python
class NetworkTopology:
    """Understand network topology for optimal routing"""

    async def measure_latency(self, from_machine: str,
                             to_machine: str) -> float:
        """Measure network latency between machines"""

    async def get_nearest_service(self, service_type: str,
                                 from_machine: str) -> ServiceInstance:
        """Find nearest service instance"""
```

**Deliverables:**
- [ ] Latency measurement
- [ ] Region proximity detection
- [ ] Optimal routing decisions
- [ ] Network partition detection

---

## Phase 4: Monitoring & Tools (Week 8)

### Objectives
- Enhanced monitoring for multi-machine
- Diagnostic and debugging tools
- Performance optimization

### Tasks

#### 4.1 Enhanced PS Command
**File:** `src/gleitzeit/cli/process_commands.py` (MODIFY)

```python
@process.command('ps')
@click.option('--machine', help='Filter by machine')
@click.option('--region', help='Filter by region')
@click.option('--format', type=click.Choice(['table', 'json', 'yaml']))
def ps(machine: str, region: str, format: str):
    """Enhanced ps with multi-machine support"""

    # Show columns: NAME, INSTANCE, MACHINE, REGION, PORT, STATUS
    # Group by machine/region
    # Show connection status
```

**Deliverables:**
- [ ] Machine column in output
- [ ] Region filtering
- [ ] Connection status indicators
- [ ] Export formats (JSON, YAML)

#### 4.2 Diagnostic Tools
**File:** `src/gleitzeit/cli/diagnose_commands.py` (NEW)

```python
@click.command('diagnose')
@click.option('--check', type=click.Choice(['ports', 'services', 'machines', 'all']))
def diagnose(check: str):
    """Diagnose multi-machine setup"""

    # Check port conflicts
    # Verify service discovery
    # Test machine connectivity
    # Validate Redis keys
```

**Deliverables:**
- [ ] Port conflict detection
- [ ] Service discovery validation
- [ ] Machine connectivity tests
- [ ] Redis key consistency checks

#### 4.3 Performance Metrics
**File:** `src/gleitzeit/core/metrics.py` (MODIFY)

```python
class MultiMachineMetrics:
    """Metrics for multi-machine deployments"""

    async def record_port_allocation_time(self, duration: float, machine: str):
    async def record_service_discovery_time(self, duration: float):
    async def record_cross_machine_latency(self, from_m: str, to_m: str, latency: float):
```

**Deliverables:**
- [ ] Port allocation metrics
- [ ] Service discovery performance
- [ ] Cross-machine latency tracking
- [ ] Prometheus export

---

## Phase 5: Production Rollout (Week 9-10)

### Objectives
- Gradual production deployment
- Performance validation
- Clean up legacy code

### Tasks

#### 5.1 Staged Rollout Plan

**Week 9 - Development Environment:**
```bash
# Enable Redis port manager only
export GLEITZEIT_FF_REDIS_PORT_MANAGER=True

# Test and monitor for 3 days
# Check metrics, logs, discrepancies
```

**Week 9 - Staging Environment:**
```bash
# Enable Redis ports + service discovery
export GLEITZEIT_FF_REDIS_PORT_MANAGER=True
export GLEITZEIT_FF_SERVICE_DISCOVERY=True

# Load test with multiple instances
# Validate service discovery
```

**Week 10 - Production (Gradual):**
```bash
# Day 1: 10% of instances
export GLEITZEIT_FF_REDIS_PORT_MANAGER=True
export GLEITZEIT_FF_MULTI_MACHINE_MODE=True

# Day 3: 50% of instances
# Day 5: 100% of instances
```

#### 5.2 Validation Checkpoints

**Before Each Stage:**
- [ ] Run migration validation tool
- [ ] Check port allocation metrics
- [ ] Verify zero port conflicts
- [ ] Test rollback procedure

**After Each Stage:**
- [ ] Monitor error rates
- [ ] Check performance metrics
- [ ] Review discrepancy logs
- [ ] Validate service discovery

#### 5.3 Cleanup Tasks

**After Successful Rollout:**
- [ ] Remove file-based PortManager
- [ ] Clean up `/tmp/gleitzeit_ports.json`
- [ ] Remove hybrid manager code
- [ ] Update documentation
- [ ] Archive migration tools

---

## Testing Strategy

### Unit Tests
```python
# test_redis_port_manager.py
def test_atomic_allocation()
def test_ttl_refresh()
def test_machine_scoping()
def test_conflict_detection()

# test_service_registry.py
def test_multi_instance_registration()
def test_service_discovery()
def test_health_updates()

# test_machine_registry.py
def test_machine_registration()
def test_heartbeat_mechanism()
def test_stale_cleanup()
```

### Integration Tests
```python
# test_multi_machine_integration.py
async def test_cross_machine_coordination()
async def test_service_discovery_across_machines()
async def test_shard_distribution_globally()
async def test_machine_failure_handling()
```

### Load Tests
```python
# test_load_multi_machine.py
async def test_high_volume_port_allocation()
async def test_service_discovery_under_load()
async def test_multi_region_latency()
```

### Chaos Engineering
- Redis network partition
- Machine sudden shutdown
- Port exhaustion scenario
- Service discovery cache poisoning

---

## Risk Mitigation

### Risk 1: Redis Becomes Single Point of Failure
**Mitigation:**
- Redis Sentinel for HA
- Redis Cluster for sharding
- Local cache with short TTL
- Fallback to file-based (emergency)

### Risk 2: Network Partitions
**Mitigation:**
- Optimistic allocation with reconciliation
- Regional Redis instances
- Eventually consistent model
- Partition detection and alerting

### Risk 3: Performance Degradation
**Mitigation:**
- Connection pooling
- Lua script optimization
- Batch operations
- Local caching layer

### Risk 4: Migration Failures
**Mitigation:**
- Feature flag rollback
- Parallel operation mode
- Comprehensive validation
- Automated rollback triggers

---

## Success Criteria

### Phase 0-1 Success Metrics
- Redis connection reliability > 99.9%
- Port allocation time < 10ms (p99)
- Zero port conflicts in parallel mode
- Migration tool validates 100% consistency

### Phase 2-3 Success Metrics
- Service discovery time < 20ms (p99)
- Multi-instance services working
- Cross-machine worker coordination functional
- Machine registry auto-cleanup working

### Phase 4-5 Success Metrics
- PS command shows all machines
- Diagnostic tools detect all issues
- Production rollout with zero downtime
- Performance metrics meet SLA

### Overall Project Success
- ✅ Multiple machines running Gleitzeit
- ✅ Automatic service discovery
- ✅ Zero port conflicts globally
- ✅ Geographic distribution working
- ✅ Load balancer integration complete
- ✅ < 5% performance overhead
- ✅ Full backward compatibility

---

## Timeline Summary

| Week | Phase | Key Deliverables |
|------|-------|-----------------|
| 1 | Foundation | Redis manager, Instance identity, Feature flags |
| 2-3 | Port Management | RedisPortManager, Hybrid operation, Migration tools |
| 4-5 | Service Registry | Multi-instance support, Discovery API, Health checks |
| 6-7 | Multi-Machine | Machine registry, Global coordination, Network topology |
| 8 | Monitoring | Enhanced PS, Diagnostic tools, Metrics |
| 9-10 | Rollout | Staged deployment, Validation, Cleanup |

## Resource Requirements

### Development Team
- 2 Senior Engineers (full-time)
- 1 DevOps Engineer (50%)
- 1 QA Engineer (50%)

### Infrastructure
- Redis Cluster (3 nodes minimum)
- Test machines (4 different regions)
- Load testing infrastructure
- Monitoring stack (Prometheus, Grafana)

### Dependencies
- Redis 7.0+
- Python asyncio improvements
- Network connectivity between machines
- Load balancer (HAProxy/NGINX)

---

## Conclusion

This implementation plan provides a systematic approach to transforming Gleitzeit into a truly distributed system. The phased approach minimizes risk while the parallel operation mode ensures zero downtime during migration. With proper testing and gradual rollout, Gleitzeit will gain the ability to scale horizontally across multiple machines globally.