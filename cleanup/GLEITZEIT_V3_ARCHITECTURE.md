# Gleitzeit V3: Event-Driven Architecture

Gleitzeit V3 is a complete rewrite focusing on pure event-driven architecture, fault tolerance, and comprehensive observability.

## 🎯 Key Improvements Over V2

| Aspect | V2 | V3 |
|--------|----|----|
| **Scheduling** | 2-second polling loop | Pure event-driven reactions |
| **State Management** | Manual synchronization | Automatic event-based sync |
| **Parameter Substitution** | Manual, error-prone | Event-driven with audit trail |
| **Error Handling** | Limited retry logic | Comprehensive failure recovery |
| **Observability** | Basic logging | Complete event audit trail |
| **Fault Tolerance** | Provider failures cause issues | Automatic failover and reassignment |
| **Debugging** | Hard to trace execution | Event replay and analysis |

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Event Store   │    │   Event Bus     │    │  Components     │
│                 │◄──►│                 │◄──►│                 │
│ • Event History │    │ • Event Routing │    │ • Workflow Eng. │
│ • Audit Trail   │    │ • Filtering     │    │ • Providers     │
│ • Replay        │    │ • Validation    │    │ • Clients       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         ▲                       ▲                       ▲
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                    ┌─────────────────────┐
                    │   Socket.IO Hub     │
                    │                     │
                    │ • Message Routing   │
                    │ • Component Coord.  │
                    │ • Real-time Events  │
                    └─────────────────────┘
```

## 🔄 Event-Driven Lifecycle

### 1. Workflow Submission
```
Client → workflow:submit → Workflow Engine
     ↓
Workflow Engine → workflow:submitted → Event Store + Observers
     ↓
For each task → task:created → Dependency Analyzer
     ↓
Ready tasks → task:ready → Assignment Coordinator
```

### 2. Task Assignment
```
task:ready → Assignment Coordinator
     ↓
Find providers → assignment:candidate_found
     ↓
Validate match → assignment:validated → assignment:approved
     ↓
Assign to provider → task:assigned → Parameter Resolver
```

### 3. Parameter Resolution
```
task:assigned → parameters:resolve_requested → Parameter Resolver
     ↓
Check dependencies → Substitute ${task_ID_result} patterns
     ↓
parameters:resolved → Provider Executor
     ↓
Execute task → task:started → task:completed/failed
```

### 4. Dependency Propagation
```
task:completed → Dependency Analyzer
     ↓
Check dependent tasks → dependency:satisfied
     ↓
Unblock waiting tasks → task:ready (cycle continues)
```

## 📊 Event Schema

Every event follows a standardized envelope:

```json
{
  "event_id": "uuid",
  "event_type": "task:completed",
  "timestamp": "2025-08-11T10:30:00Z",
  "sequence_number": 123,
  "source_component": "workflow_engine",
  "correlation_id": "workflow_abc123",
  "workflow_id": "abc123",
  "task_id": "def456",
  "provider_id": "provider_1",
  "severity": "info",
  "payload": { ... },
  "metadata": { ... }
}
```

## 🎛️ Event Types

### Workflow Events
- `workflow:submitted` - New workflow received
- `workflow:state_changed` - Status updates
- `workflow:completed` - Execution finished
- `workflow:failed` - Execution failed

### Task Events
- `task:created` - Task instantiated
- `task:ready` - Dependencies satisfied
- `task:assigned` - Provider allocated
- `task:completed` - Execution successful
- `task:failed` - Execution failed

### Provider Events
- `provider:registered` - New provider available
- `provider:available` - Ready for tasks
- `provider:busy` - At capacity
- `provider:heartbeat` - Health update

### Assignment Events
- `assignment:requested` - Need provider for task
- `assignment:candidate_found` - Potential match
- `assignment:approved` - Assignment confirmed
- `assignment:executed` - Task sent to provider

### Parameter Events
- `parameters:resolve_requested` - Need substitution
- `parameters:resolved` - Substitution complete
- `parameters:resolution_failed` - Missing dependencies

## 🔧 Core Components

### Event Bus
- **Purpose**: Central nervous system for all communication
- **Features**: 
  - Event validation and schema checking
  - Filtering and routing
  - Acknowledgments and retries
  - Dead letter queue for failed events

### Event Store
- **Purpose**: Persistent event history for replay and debugging
- **Features**:
  - Time-based queries
  - Workflow/task event filtering
  - Event stream processing
  - Automatic cleanup

### Workflow Engine
- **Purpose**: Orchestrates workflow execution through events
- **Features**:
  - Reactive task scheduling
  - Dependency graph management
  - Parameter substitution
  - Failure recovery

### Provider Health System
- **Purpose**: Monitors and manages provider health
- **Features**:
  - Automatic heartbeat monitoring
  - Health score calculation
  - Load balancing
  - Automatic failover

## 🎯 Parameter Substitution

V3 makes parameter substitution explicit and auditable:

### Pattern Recognition
```python
# Original task parameters
{
  "prompt": "Analyze: ${task_abc123_result}",
  "context": "Previous result: ${task_def456_result}"
}

# After substitution
{
  "prompt": "Analyze: {'files': ['a.txt', 'b.py']}",
  "context": "Previous result: Temperature is 22°C"
}
```

### Event Flow
1. `task:assigned` → `parameters:resolve_requested`
2. Parameter Resolver checks workflow.task_results
3. Substitutes patterns with actual values
4. `parameters:resolved` with substitution audit
5. Task execution with resolved parameters

## 🔍 Observability Features

### Real-Time Monitoring
- All state changes generate events
- Event stream can be monitored live
- Health metrics automatically collected
- Performance data tracked per provider

### Debugging and Replay
- Complete event history stored
- Workflow execution can be replayed
- Event filtering for specific debugging
- Audit trail for compliance

### Metrics and Analytics
- Task execution times
- Provider performance
- Failure rates and patterns
- System throughput

## 🛡️ Fault Tolerance

### Provider Failures
- Heartbeat monitoring detects disconnections
- Tasks automatically reassigned to healthy providers
- Health scores prevent tasks going to unhealthy providers
- Graceful degradation when providers overloaded

### Event Delivery
- Events have acknowledgments and timeouts
- Failed events go to dead letter queue
- Automatic retry with exponential backoff
- Event store preserves ordering

### Workflow Recovery
- Partial workflow state can be recovered
- Event replay rebuilds exact state
- Failed tasks can be retried
- Dependency chains remain intact

## 🚀 Running the Demo

```bash
cd /Users/leifmarkthaler/github/gleitzeit
python gleitzeit_v3_demo.py
```

The demo shows:
1. **System Startup**: Providers register and emit heartbeats
2. **Workflow Submission**: MCP → LLM dependency chain
3. **Event Monitoring**: Real-time event stream display  
4. **Parameter Substitution**: MCP results injected into LLM prompt
5. **Health Monitoring**: Provider health checks and metrics
6. **Completion**: Final results and system statistics

## 📈 Benefits of Event-Driven Architecture

### Scalability
- Components can be distributed across machines
- Event bus handles routing automatically
- Horizontal scaling by adding more providers
- No single point of failure

### Maintainability
- Clear separation of concerns
- Components only know about their events
- Easy to add new functionality
- Comprehensive debugging information

### Reliability
- Automatic failure recovery
- Event ordering preserved
- State can be reconstructed from events
- Comprehensive error handling

### Observability
- Complete audit trail
- Real-time monitoring
- Performance analytics
- Compliance tracking

## 🔮 Future Enhancements

1. **Event Streaming**: Kafka integration for high throughput
2. **Multi-tenancy**: Workflow isolation and resource quotas
3. **Advanced Analytics**: ML-based performance optimization
4. **GraphQL API**: Query event history and system state
5. **Workflow Visualization**: Real-time execution diagrams
6. **Policy Engine**: Rule-based task routing and constraints

The V3 architecture provides a solid foundation for building highly scalable, observable, and fault-tolerant distributed task execution systems.