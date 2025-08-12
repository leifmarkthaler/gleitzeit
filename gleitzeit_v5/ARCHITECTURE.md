# Gleitzeit V5 - Pure Socket.IO Distributed Architecture

## Design Philosophy

Gleitzeit V5 is a **pure event-driven distributed system** where **every component is a Socket.IO client** connecting to a central event hub. No component has direct dependencies on others - all communication happens through Socket.IO events.

## Core Principles

1. **Pure Socket.IO**: Every component is a Socket.IO client, no local method calls
2. **Event-Only Communication**: All coordination happens through events
3. **Distributed by Design**: Any component can run on any server
4. **Dynamic Discovery**: Components connect/disconnect dynamically
5. **Fault Tolerant**: Component failures don't crash the system
6. **Horizontally Scalable**: Add more instances of any component type

## System Architecture

```
                    Central Event Hub (Server)
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼────┐        ┌───▼───┐         ┌───▼───┐
   │Component│        │Component│       │Component│
   │ Node A  │        │ Node B  │       │ Node C  │
   └─────────┘        └─────────┘       └─────────┘
        │                  │                  │
   ┌────▼────┐        ┌───▼───┐         ┌───▼───┐
   │QueueMgr │        │DepRes │         │ExecEng│
   │Registry │        │ Persist│         │Provider│
   │   CLI   │        │   ...  │         │  ...   │
   └─────────┘        └─────────┘       └─────────┘
```

## Component Types

### 1. Central Event Hub (`central_hub.py`)
- **Role**: Pure event router and coordinator
- **Responsibilities**: 
  - Route events between components
  - Maintain component registry
  - Handle connect/disconnect
  - Provide observability
- **Does NOT**: Execute business logic, store state

### 2. Queue Manager Client (`queue_manager_client.py`)
- **Role**: Manages task queues
- **Events**: 
  - Receives: `enqueue_task`, `request_next_task`, `task_priority_changed`
  - Emits: `task_enqueued`, `task_available`, `queue_stats_changed`

### 3. Dependency Resolver Client (`dependency_resolver_client.py`)
- **Role**: Analyzes workflow dependencies
- **Events**:
  - Receives: `analyze_workflow`, `task_completed`, `check_dependencies`
  - Emits: `workflow_analyzed`, `dependencies_satisfied`, `execution_blocked`

### 4. Protocol Registry Client (`protocol_registry_client.py`)
- **Role**: Manages protocol specifications and provider routing
- **Events**:
  - Receives: `register_protocol`, `register_provider`, `find_provider`
  - Emits: `protocol_registered`, `provider_registered`, `provider_found`

### 5. Persistence Client (`persistence_client.py`)
- **Role**: Handles data persistence
- **Events**:
  - Receives: `save_task`, `save_workflow`, `save_result`, `query_data`
  - Emits: `data_saved`, `data_retrieved`, `persistence_error`

### 6. Execution Engine Client (`execution_engine_client.py`)
- **Role**: Executes tasks
- **Events**:
  - Receives: `execute_task`, `cancel_task`
  - Emits: `task_started`, `task_completed`, `task_failed`, `capacity_update`

### 7. Provider Client (`provider_client.py`)
- **Role**: Implements protocol methods
- **Events**:
  - Receives: `execute_method`, `health_check`, `initialize`, `shutdown`
  - Emits: `method_result`, `health_status`, `provider_error`

### 8. CLI Client (`cli_client.py`)
- **Role**: Command-line interface
- **Events**:
  - Emits: `submit_workflow`, `query_status`, `list_components`
  - Receives: `workflow_submitted`, `status_response`, `component_list`

## Event Flow Examples

### Workflow Submission Flow
```
1. CLI Client → 'submit_workflow' → Central Hub
2. Central Hub → 'analyze_workflow' → Dependency Resolver Client
3. Dependency Resolver Client → 'workflow_analyzed' → Central Hub
4. Central Hub → 'enqueue_task' → Queue Manager Client (ready tasks)
5. Queue Manager Client → 'task_enqueued' → Central Hub
6. Central Hub → 'execute_task' → Execution Engine Client
7. Execution Engine Client → 'task_started' → Central Hub
```

### Task Execution Flow  
```
1. Execution Engine Client → 'find_provider' → Central Hub
2. Central Hub → 'find_provider' → Protocol Registry Client
3. Protocol Registry Client → 'provider_found' → Central Hub
4. Central Hub → 'execute_method' → Provider Client
5. Provider Client → 'method_result' → Central Hub
6. Central Hub → 'task_completed' → Execution Engine Client
7. Execution Engine Client → 'task_completed' → Central Hub
```

### Dependency Resolution Flow
```
1. Central Hub → 'task_completed' → Dependency Resolver Client
2. Dependency Resolver Client → 'check_dependencies' (internal)
3. Dependency Resolver Client → 'dependencies_satisfied' → Central Hub
4. Central Hub → 'enqueue_task' → Queue Manager Client (newly ready tasks)
5. Queue Manager Client → 'task_enqueued' → Central Hub
6. Central Hub → 'execute_task' → Execution Engine Client
```

## Component Registration and Discovery

### Dynamic Component Registration
```python
# Each component registers itself on connect
@sio.event
async def connect():
    await sio.emit('register_component', {
        'component_type': 'queue_manager',
        'component_id': 'queue-mgr-001',
        'capabilities': ['task_queuing', 'priority_scheduling'],
        'version': '5.0.0'
    })

# Central Hub maintains component registry
@hub.sio.on('register_component')
async def handle_component_registration(sid, data):
    component_type = data['component_type']
    self.components[component_type][sid] = {
        'id': data['component_id'],
        'capabilities': data['capabilities'],
        'connected_at': datetime.utcnow(),
        'last_heartbeat': datetime.utcnow()
    }
    
    await self.sio.emit('component_registered', {
        'component_id': data['component_id'],
        'assigned_sid': sid
    }, room=sid)
```

### Load Balancing and Routing
```python
# Central Hub routes events to least loaded component
async def route_to_component(self, component_type: str, event_name: str, data: dict):
    available_components = self.components[component_type]
    if not available_components:
        await self.sio.emit('no_components_available', {
            'component_type': component_type,
            'event': event_name
        })
        return
    
    # Simple round-robin (could be enhanced with load metrics)
    target_sid = self.get_next_component_round_robin(component_type)
    await self.sio.emit(event_name, data, room=target_sid)
```

## Fault Tolerance and Recovery

### Component Health Monitoring
```python
# Central Hub sends periodic heartbeats
async def send_heartbeats(self):
    while True:
        for component_type, components in self.components.items():
            for sid, component_info in components.items():
                await self.sio.emit('heartbeat', {
                    'timestamp': datetime.utcnow().isoformat()
                }, room=sid)
        await asyncio.sleep(30)  # Every 30 seconds

# Components respond to heartbeats
@sio.on('heartbeat')
async def handle_heartbeat(data):
    await sio.emit('heartbeat_response', {
        'component_id': self.component_id,
        'status': 'healthy',
        'metrics': self.get_health_metrics()
    })
```

### Automatic Failover
```python
@hub.sio.event
async def disconnect(sid):
    # Find which component disconnected
    disconnected_component = self.find_component_by_sid(sid)
    if disconnected_component:
        component_type = disconnected_component['type']
        
        # Handle specific component failures
        if component_type == 'execution_engine':
            await self.redistribute_active_tasks(disconnected_component['id'])
        elif component_type == 'queue_manager':
            await self.failover_queue_operations()
        
        # Remove from registry
        self.remove_component(sid)
        
        # Notify other components
        await self.sio.emit('component_disconnected', {
            'component_type': component_type,
            'component_id': disconnected_component['id']
        })
```

## Message Correlation and Tracing

### Correlation IDs
```python
# Every event includes correlation tracking
async def emit_with_correlation(self, event_name: str, data: dict, correlation_id: str = None):
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    
    enhanced_data = {
        **data,
        '_correlation_id': correlation_id,
        '_source_component': self.component_id,
        '_timestamp': datetime.utcnow().isoformat()
    }
    
    await self.sio.emit(event_name, enhanced_data)
```

### Distributed Tracing
```python
# Central Hub logs all events for observability
@hub.sio.event  
async def catch_all_events(event_name, data):
    trace_info = {
        'event': event_name,
        'correlation_id': data.get('_correlation_id'),
        'source': data.get('_source_component'),
        'timestamp': data.get('_timestamp'),
        'payload_size': len(str(data))
    }
    
    await self.trace_logger.log_event(trace_info)
    
    # Forward to appropriate handlers
    await self.route_event(event_name, data)
```

## Configuration and Deployment

### Environment-Based Configuration
```python
# Each component loads configuration from environment
class ComponentConfig:
    def __init__(self):
        self.hub_url = os.getenv('GLEITZEIT_HUB_URL', 'http://localhost:8000')
        self.component_id = os.getenv('COMPONENT_ID', f'{socket.gethostname()}-{uuid.uuid4().hex[:8]}')
        self.redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
```

### Docker Deployment
```yaml
# docker-compose.yml
version: '3.8'
services:
  central-hub:
    image: gleitzeit/central-hub:v5
    ports: ["8000:8000"]
    
  queue-manager:
    image: gleitzeit/queue-manager:v5
    environment:
      - GLEITZEIT_HUB_URL=http://central-hub:8000
      - REDIS_URL=redis://redis:6379
    depends_on: [central-hub, redis]
    
  execution-engine:
    image: gleitzeit/execution-engine:v5
    deploy:
      replicas: 3  # Scale horizontally
    environment:
      - GLEITZEIT_HUB_URL=http://central-hub:8000
    depends_on: [central-hub]
```

## Benefits of V5 Architecture

### 1. True Horizontal Scaling
- Add more instances of any component type
- Load automatically distributed
- No coordination needed between instances

### 2. Fault Tolerance
- Component failures don't affect others
- Automatic failover and redistribution
- Graceful degradation under load

### 3. Development Flexibility
- Components can be developed independently
- Easy to test individual components
- Simple deployment and updates

### 4. Observability
- All communication visible through events
- Distributed tracing built-in
- Real-time system monitoring

### 5. Protocol Flexibility
- Easy to add new protocols
- Providers can be written in any language
- MCP, HTTP, gRPC all supported

## Migration from V4

### Phase 1: Infrastructure
1. Create Central Event Hub
2. Implement base SocketIOComponent class
3. Set up event correlation system

### Phase 2: Core Components
1. Migrate Queue Manager to Socket.IO client
2. Migrate Dependency Resolver to Socket.IO client
3. Migrate Protocol Registry to Socket.IO client

### Phase 3: Execution Components
1. Migrate Execution Engine to Socket.IO client
2. Migrate Provider system to Socket.IO clients
3. Update CLI to Socket.IO client

### Phase 4: Advanced Features
1. Implement distributed persistence
2. Add monitoring and observability
3. Performance optimization

## Next Steps

1. **Create base SocketIOComponent class** - Common functionality for all clients
2. **Implement Central Event Hub** - Core routing and registry
3. **Build Queue Manager Client** - First distributed component
4. **Create integration tests** - Validate event flows
5. **Add observability tools** - Monitoring and tracing