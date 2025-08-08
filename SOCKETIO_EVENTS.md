# Socket.IO Event Architecture for Gleitzeit Cluster

## Overview

Socket.IO provides real-time, bidirectional communication between cluster components, enabling:

- **Live Updates**: Real-time workflow and task progress
- **Event Broadcasting**: Instant notifications across all connected clients
- **Node Coordination**: Dynamic executor node registration and health monitoring
- **Dashboard Support**: Live web dashboard updates
- **Distributed Coordination**: Cross-node task assignment and completion

## Architecture Components

### 1. **Socket.IO Server** (Coordination Hub)
- Central event broker for all cluster communication
- Manages rooms for workflow-specific events
- Handles authentication and authorization
- Maintains connection state for all nodes and clients

### 2. **Cluster Manager** (Primary Client)
- Emits workflow submission events
- Listens for task completion notifications
- Manages workflow lifecycle events
- Coordinates with Redis for persistent state

### 3. **Executor Nodes** (Worker Clients)
- Register capabilities on connection
- Listen for task assignments
- Emit task progress and completion events
- Send heartbeat signals

### 4. **Web Dashboard** (Observer Client)
- Subscribe to workflow events
- Receive real-time progress updates
- Display live cluster statistics
- Monitor node health

---

## Event Namespaces

### `/cluster` - Main cluster coordination
Primary namespace for core cluster operations

### `/executor` - Executor node management
Dedicated namespace for executor node coordination

### `/dashboard` - Web dashboard updates
Read-only namespace for monitoring clients

---

## Event Catalog

### 1. Connection Events

#### `connect`
**Direction**: Client → Server  
**Payload**: 
```json
{
  "client_type": "cluster|executor|dashboard",
  "client_id": "uuid",
  "metadata": {}
}
```

#### `disconnect`
**Direction**: Client → Server  
**Payload**: None (automatic)

#### `authenticate`
**Direction**: Client → Server  
**Payload**:
```json
{
  "token": "auth_token",
  "client_id": "uuid"
}
```

### 2. Workflow Events

#### `workflow:submit`
**Direction**: Cluster → Server → Executors  
**Payload**:
```json
{
  "workflow_id": "uuid",
  "name": "workflow_name",
  "tasks": [
    {
      "task_id": "uuid",
      "task_type": "TEXT_PROMPT|VISION_TASK|etc",
      "priority": "urgent|high|normal|low",
      "parameters": {},
      "dependencies": []
    }
  ],
  "metadata": {}
}
```

#### `workflow:started`
**Direction**: Server → All Clients  
**Payload**:
```json
{
  "workflow_id": "uuid",
  "timestamp": "2024-01-01T00:00:00Z",
  "total_tasks": 10
}
```

#### `workflow:completed`
**Direction**: Server → All Clients  
**Payload**:
```json
{
  "workflow_id": "uuid",
  "status": "completed|failed|cancelled",
  "completed_tasks": 10,
  "failed_tasks": 0,
  "execution_time": 45.2,
  "timestamp": "2024-01-01T00:00:00Z"
}
```

#### `workflow:progress`
**Direction**: Server → Dashboard  
**Payload**:
```json
{
  "workflow_id": "uuid",
  "progress_percentage": 75,
  "completed_tasks": 15,
  "total_tasks": 20,
  "current_task": "task_name"
}
```

#### `workflow:error`
**Direction**: Server → All Clients  
**Payload**:
```json
{
  "workflow_id": "uuid",
  "error_message": "Error description",
  "task_id": "uuid",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### 3. Task Events

#### `task:assign`
**Direction**: Server → Executor  
**Payload**:
```json
{
  "task_id": "uuid",
  "workflow_id": "uuid",
  "task_type": "TEXT_PROMPT",
  "parameters": {
    "prompt": "...",
    "model": "llama3"
  },
  "timeout": 300
}
```

#### `task:accepted`
**Direction**: Executor → Server  
**Payload**:
```json
{
  "task_id": "uuid",
  "node_id": "executor_uuid",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

#### `task:progress`
**Direction**: Executor → Server → Dashboard  
**Payload**:
```json
{
  "task_id": "uuid",
  "workflow_id": "uuid",
  "progress": 50,
  "message": "Processing...",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

#### `task:completed`
**Direction**: Executor → Server → Cluster  
**Payload**:
```json
{
  "task_id": "uuid",
  "workflow_id": "uuid",
  "result": {},
  "execution_time": 2.5,
  "node_id": "executor_uuid",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

#### `task:failed`
**Direction**: Executor → Server → Cluster  
**Payload**:
```json
{
  "task_id": "uuid",
  "workflow_id": "uuid",
  "error": "Error message",
  "retry_count": 1,
  "node_id": "executor_uuid",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### 4. Node Events

#### `node:register`
**Direction**: Executor → Server  
**Payload**:
```json
{
  "node_id": "uuid",
  "name": "gpu-worker-1",
  "capabilities": {
    "task_types": ["TEXT_PROMPT", "VISION_TASK"],
    "models": ["llama3", "llava"],
    "has_gpu": true,
    "max_concurrent_tasks": 4
  },
  "metadata": {}
}
```

#### `node:heartbeat`
**Direction**: Executor → Server  
**Payload**:
```json
{
  "node_id": "uuid",
  "status": "ready|busy|offline",
  "current_tasks": 2,
  "cpu_usage": 45.2,
  "memory_usage": 60.1,
  "timestamp": "2024-01-01T00:00:00Z"
}
```

#### `node:status_change`
**Direction**: Server → Dashboard  
**Payload**:
```json
{
  "node_id": "uuid",
  "old_status": "ready",
  "new_status": "busy",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

#### `node:disconnected`
**Direction**: Server → All Clients  
**Payload**:
```json
{
  "node_id": "uuid",
  "name": "gpu-worker-1",
  "assigned_tasks": ["task_id_1", "task_id_2"],
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### 5. Cluster Management Events

#### `cluster:stats`
**Direction**: Dashboard → Server → Dashboard  
**Request**:
```json
{
  "request_id": "uuid"
}
```
**Response**:
```json
{
  "request_id": "uuid",
  "active_workflows": 5,
  "queued_tasks": 20,
  "processing_tasks": 8,
  "active_nodes": 3,
  "total_completed_tasks": 1000,
  "uptime": 86400
}
```

#### `cluster:broadcast`
**Direction**: Server → All Clients  
**Payload**:
```json
{
  "message_type": "info|warning|error",
  "message": "System message",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

---

## Room Structure

### Workflow Rooms
- **Pattern**: `workflow:{workflow_id}`
- **Members**: Cluster manager, assigned executors, dashboards
- **Purpose**: Workflow-specific event broadcasting

### Node Rooms
- **Pattern**: `node:{node_id}`
- **Members**: Specific executor node, cluster manager
- **Purpose**: Direct node communication

### Global Rooms
- **Pattern**: `global:updates`
- **Members**: All connected clients
- **Purpose**: System-wide announcements

---

## Client Implementation Patterns

### 1. Cluster Manager Client
```python
class ClusterSocketClient:
    async def connect(self):
        await self.sio.connect(url)
        await self.sio.emit('authenticate', {'token': token})
        
    async def submit_workflow(self, workflow):
        await self.sio.emit('workflow:submit', workflow.to_dict())
        
    @sio.on('task:completed')
    async def handle_task_completion(data):
        # Update workflow state
        # Store result in Redis
```

### 2. Executor Node Client
```python
class ExecutorSocketClient:
    async def register(self):
        await self.sio.emit('node:register', self.capabilities)
        
    @sio.on('task:assign')
    async def handle_task_assignment(data):
        # Accept task
        await self.sio.emit('task:accepted', {'task_id': data['task_id']})
        # Execute task
        result = await self.execute_task(data)
        # Report completion
        await self.sio.emit('task:completed', result)
```

### 3. Dashboard Client
```javascript
class DashboardSocket {
    connect() {
        this.socket.on('workflow:progress', (data) => {
            updateProgressBar(data.workflow_id, data.progress_percentage);
        });
        
        this.socket.on('node:status_change', (data) => {
            updateNodeStatus(data.node_id, data.new_status);
        });
    }
}
```

---

## Error Handling

### Connection Errors
- Automatic reconnection with exponential backoff
- Queue events during disconnection
- Replay queued events on reconnection

### Event Validation
- Schema validation for all events
- Reject malformed events with error response
- Log validation failures for debugging

### Timeout Handling
- Configurable timeout for event acknowledgments
- Automatic retry with backoff
- Dead letter queue for failed events

---

## Security Considerations

### Authentication
- JWT token-based authentication
- Token refresh on expiration
- Role-based event permissions

### Rate Limiting
- Per-client event rate limiting
- Throttle high-frequency events
- Protect against DoS attacks

### Encryption
- TLS/SSL for transport security
- Optional message-level encryption
- Secure token storage

---

## Performance Optimizations

### Event Batching
- Batch multiple task completions
- Aggregate progress updates
- Reduce network overhead

### Compression
- Enable Socket.IO compression
- Compress large payloads
- Binary data for file transfers

### Caching
- Cache frequently accessed data
- Client-side event deduplication
- Server-side result caching

---

This event architecture provides a robust foundation for real-time coordination in the Gleitzeit cluster, enabling responsive user interfaces, efficient task distribution, and comprehensive monitoring capabilities.