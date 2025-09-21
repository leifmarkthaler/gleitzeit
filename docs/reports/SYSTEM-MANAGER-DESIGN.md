# System Manager Architecture Plan

## Current Gaps Identified

1. **No centralized lifecycle management** - Components (hubs, providers, workers) are initialized ad-hoc
2. **Limited health monitoring** - No unified health check system across components
3. **No graceful shutdown coordination** - Components shut down independently without coordination
4. **Missing deployment orchestration** - No system to manage distributed deployments
5. **Resource allocation inefficiencies** - Stateful ResourceManager conflicts with horizontal scaling needs
6. **No service discovery** - Components can't dynamically find each other in distributed setup

## Proposed System Manager Design

### Core Responsibilities

The System Manager would be a **centralized orchestration component** that manages the entire Gleitzeit system lifecycle:

```
┌─────────────────────────────────────────────────────┐
│                  System Manager                      │
│            (Lifecycle & Coordination)                │
├─────────────────────────────────────────────────────┤
│ • Service Registry & Discovery                       │
│ • Health Monitoring & Alerting                       │
│ • Resource Coordination                              │
│ • Configuration Management                           │
│ • Deployment Orchestration                           │
│ • Graceful Shutdown Coordination                     │
└──────────────┬──────────────┬───────────────────────┘
               │              │
    ┌──────────▼───┐   ┌──────▼──────────┐
    │ Control Plane│   │   Data Plane     │
    └──────────────┘   └──────────────────┘
```

## Architecture Components

### 1. Service Registry
- **Purpose**: Track all active components in the system
- **Features**:
  - Auto-registration of providers, hubs, workers
  - Service discovery API
  - Load balancing metadata
  - Version tracking

### 2. Health Monitor
- **Purpose**: Unified health checking across all components
- **Features**:
  - Periodic health checks
  - Dependency health aggregation
  - Alert generation on failures
  - Auto-recovery triggers

### 3. Configuration Manager
- **Purpose**: Centralized configuration with hot-reload
- **Features**:
  - Environment-specific configs
  - Dynamic reconfiguration without restart
  - Secret management integration
  - Configuration validation

### 4. Deployment Coordinator
- **Purpose**: Manage distributed deployments
- **Features**:
  - Rolling updates
  - Blue-green deployments
  - Canary releases
  - Rollback capability

### 5. Resource Coordinator
- **Purpose**: Global resource allocation strategy (replaces stateful ResourceManager)
- **Features**:
  - Works with stateless Resource Service
  - Global resource policies
  - Multi-tenant resource isolation
  - Resource quota enforcement

## Implementation Strategy

### Phase 1: Core Infrastructure
```python
class SystemManager:
    """Central system orchestration and management"""
    
    def __init__(self, config: SystemConfig):
        self.service_registry = ServiceRegistry()
        self.health_monitor = HealthMonitor()
        self.config_manager = ConfigurationManager()
        self.resource_coordinator = ResourceCoordinator()
        self.deployment_coordinator = DeploymentCoordinator()
        
    async def start_system(self, deployment_spec: DeploymentSpec):
        """Bootstrap entire Gleitzeit system"""
        # 1. Initialize persistence layer
        # 2. Start resource service
        # 3. Initialize hubs
        # 4. Register providers
        # 5. Start workers
        # 6. Enable health monitoring
        
    async def shutdown_system(self):
        """Graceful system shutdown"""
        # 1. Stop accepting new workflows
        # 2. Wait for active tasks to complete
        # 3. Shutdown workers
        # 4. Release resources
        # 5. Cleanup persistence
```

### Phase 2: Service Discovery
```python
class ServiceRegistry:
    """Dynamic service registration and discovery"""
    
    async def register_service(self, service: ServiceSpec):
        # Store in persistence (Redis/etcd)
        # Emit SERVICE_REGISTERED event
        
    async def discover_service(self, criteria: ServiceCriteria):
        # Query available services
        # Return endpoints with health status
        
    async def watch_services(self, service_type: str):
        # Stream service changes
```

### Phase 3: Health Management
```python
class HealthMonitor:
    """System-wide health monitoring"""
    
    async def check_component_health(self, component_id: str):
        # Probe health endpoint
        # Check dependencies
        # Calculate aggregate health
        
    async def handle_unhealthy_component(self, component: Component):
        # Attempt recovery
        # Redirect traffic if needed
        # Alert operators
```

## Integration Points

### With Existing Components

1. **ExecutionEngineV2**: Register as service, report health
2. **Providers**: Auto-register capabilities, health endpoints
3. **Hubs**: Report resource availability, accept allocation policies
4. **Workers**: Register capacity, accept work assignments
5. **Persistence**: Monitor storage health, manage migrations

### New APIs Required

```python
# Service Registration API
POST /system/services/register
GET /system/services/discover
GET /system/services/{id}/health

# Configuration API  
GET /system/config/{component}
PUT /system/config/{component}
POST /system/config/reload

# Deployment API
POST /system/deployments/create
GET /system/deployments/{id}/status
POST /system/deployments/{id}/rollback

# Monitoring API
GET /system/health
GET /system/metrics
GET /system/alerts
```

## Deployment Modes

### 1. Development Mode
- System Manager embedded in main process
- All components in single process
- In-memory service registry
- Local configuration

### 2. Production Mode
- System Manager as separate service
- Distributed components
- Redis/etcd service registry
- Centralized configuration

### 3. Kubernetes Mode
- System Manager as operator
- CRDs for Gleitzeit resources
- Native K8s service discovery
- ConfigMaps/Secrets integration

## Benefits

1. **Simplified Operations**: Single point for system management
2. **Better Observability**: Unified health and metrics
3. **Improved Reliability**: Coordinated failure handling
4. **Easier Scaling**: Centralized resource policies
5. **Zero-Downtime Updates**: Coordinated deployments
6. **Multi-Tenancy Support**: Resource isolation and quotas

## Migration Path

1. **Step 1**: Implement ServiceRegistry with existing components
2. **Step 2**: Add health monitoring to all components
3. **Step 3**: Migrate configuration to centralized manager
4. **Step 4**: Implement deployment coordination
5. **Step 5**: Replace ResourceManager with stateless coordinator

## Key Design Decisions

1. **Event-Driven**: Use existing event bus for coordination
2. **Stateless Workers**: System Manager doesn't hold worker state
3. **Pluggable Backends**: Support Redis, etcd, Consul for registry
4. **Graceful Degradation**: System works without manager (reduced features)
5. **API-First**: All operations available via REST/gRPC APIs

## Example Use Cases

### System Startup Sequence
```python
async def start_gleitzeit_system():
    # Initialize System Manager
    system_manager = SystemManager(config)
    
    # Start core infrastructure
    await system_manager.start_persistence()
    await system_manager.start_event_bus()
    
    # Initialize resource layer
    resource_service = await system_manager.start_resource_service()
    
    # Register and start hubs
    ollama_hub = await system_manager.register_hub("ollama", OllamaHub())
    docker_hub = await system_manager.register_hub("docker", DockerHub())
    
    # Register providers
    await system_manager.register_provider("llm/v1", OllamaProvider(ollama_hub))
    await system_manager.register_provider("python/v1", PythonProvider())
    
    # Start workers
    for i in range(config.worker_count):
        await system_manager.start_worker(f"worker-{i}")
    
    # Enable monitoring
    await system_manager.enable_health_monitoring()
    
    return system_manager
```

### Handling Component Failure
```python
async def handle_provider_failure(provider_id: str):
    # System Manager detects failure
    health_status = await system_manager.health_monitor.check_provider(provider_id)
    
    if health_status.is_unhealthy:
        # Attempt recovery
        if await system_manager.attempt_recovery(provider_id):
            return
        
        # Redirect traffic to backup
        backup_provider = await system_manager.find_backup_provider(provider_id)
        await system_manager.redirect_traffic(provider_id, backup_provider)
        
        # Alert operators
        await system_manager.send_alert(f"Provider {provider_id} failed, traffic redirected")
```

### Rolling Update
```python
async def perform_rolling_update(component_type: str, new_version: str):
    components = await system_manager.get_components(component_type)
    
    for component in components:
        # Drain traffic from component
        await system_manager.drain_component(component.id)
        
        # Update component
        await system_manager.update_component(component.id, new_version)
        
        # Health check new version
        if await system_manager.health_check(component.id):
            # Resume traffic
            await system_manager.resume_traffic(component.id)
        else:
            # Rollback
            await system_manager.rollback_component(component.id)
            raise UpdateFailedError(f"Failed to update {component.id}")
```

## Technical Considerations

### State Management
- System Manager maintains minimal state (service registry, health status)
- All operational state remains in persistence layer
- Use event sourcing for audit trail

### High Availability
- System Manager can run in HA mode with leader election
- Service registry replicated across instances
- Health monitoring continues during failover

### Performance
- Async health checks to avoid blocking
- Caching of service discovery results
- Batch configuration updates

### Security
- mTLS for component communication
- RBAC for configuration changes
- Audit logging for all operations

## Success Metrics

1. **Operational Efficiency**
   - Reduce deployment time by 70%
   - Decrease MTTR by 50%
   - Eliminate manual coordination tasks

2. **System Reliability**
   - 99.9% uptime for core services
   - < 5 second detection of failures
   - Zero-downtime deployments

3. **Scalability**
   - Support 100+ workers
   - Handle 10,000+ workflows/hour
   - Sub-second service discovery

## Next Steps

1. **Prototype Development**
   - Build minimal ServiceRegistry
   - Implement basic health monitoring
   - Test with existing components

2. **Integration Testing**
   - Test service discovery under load
   - Validate health check accuracy
   - Measure coordination overhead

3. **Production Readiness**
   - Add monitoring and alerting
   - Implement security features
   - Create operational runbooks

## Conclusion

The System Manager will transform Gleitzeit from a collection of components into a cohesive, self-managing system. By providing centralized coordination, health monitoring, and deployment orchestration, it will significantly improve operational efficiency while maintaining the stateless, event-driven architecture that enables horizontal scaling.

This design maintains backward compatibility while enabling new capabilities like zero-downtime deployments, automatic failover, and multi-tenant resource management. The phased implementation approach ensures we can deliver value incrementally while minimizing disruption to existing deployments.