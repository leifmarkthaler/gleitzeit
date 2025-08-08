# Redis Data Schema for Gleitzeit Cluster

## Overview

Redis serves as the persistent storage and message queue backbone for the Gleitzeit distributed workflow system, providing:

- **Persistent Workflow State**: Workflows survive cluster restarts
- **Distributed Task Queues**: Reliable task distribution across nodes
- **Real-time Coordination**: Event-driven updates and synchronization
- **Results Storage**: Task outputs and workflow results
- **Node Management**: Executor node registration and health tracking

## Key Design Principles

1. **Atomic Operations**: Use Redis transactions for state consistency
2. **Expiration Policies**: Automatic cleanup of completed workflows
3. **Pub/Sub Events**: Real-time notifications for state changes
4. **Sharded Queues**: Multiple priority queues for load balancing
5. **Backup Strategy**: All critical state is persistently stored

---

## Data Structures

### 1. Workflows

#### Workflow Storage
```
Key: "workflow:{workflow_id}"
Type: Hash
TTL: 7 days (configurable)
Fields:
  - id: workflow UUID
  - name: workflow name
  - description: workflow description  
  - status: PENDING|RUNNING|COMPLETED|FAILED|CANCELLED
  - error_strategy: stop|continue|retry|skip
  - created_at: ISO timestamp
  - started_at: ISO timestamp (nullable)
  - completed_at: ISO timestamp (nullable)
  - total_tasks: integer
  - completed_tasks: integer
  - failed_tasks: integer
  - metadata: JSON string
```

#### Workflow Index
```
Key: "workflows:active"
Type: Set
Members: workflow_id list (for active workflows)

Key: "workflows:completed"  
Type: Sorted Set
Score: completion timestamp
Members: workflow_id list
```

#### Workflow Tasks List
```
Key: "workflow:{workflow_id}:tasks"
Type: List
Members: task_id list (execution order)
```

#### Workflow Results
```
Key: "workflow:{workflow_id}:results"
Type: Hash
Fields: {task_id: result_json, ...}

Key: "workflow:{workflow_id}:errors"
Type: Hash  
Fields: {task_id: error_message, ...}
```

### 2. Tasks

#### Task Storage
```
Key: "task:{task_id}"
Type: Hash
TTL: 7 days (inherits from workflow)
Fields:
  - id: task UUID
  - workflow_id: parent workflow UUID
  - name: task name
  - task_type: TEXT_PROMPT|VISION_TASK|PYTHON_FUNCTION|HTTP_REQUEST|FILE_OPERATION
  - status: PENDING|QUEUED|ASSIGNED|PROCESSING|COMPLETED|FAILED|RETRYING|CANCELLED
  - priority: LOW|NORMAL|HIGH|URGENT
  - parameters: JSON string (TaskParameters)
  - requirements: JSON string (TaskRequirements) 
  - dependencies: JSON array of task_ids
  - assigned_node_id: executor node UUID (nullable)
  - result: JSON string (nullable)
  - error: error message (nullable)
  - retry_count: integer
  - max_retries: integer
  - created_at: ISO timestamp
  - queued_at: ISO timestamp (nullable)
  - started_at: ISO timestamp (nullable)
  - completed_at: ISO timestamp (nullable)
  - metadata: JSON string
```

#### Task Dependencies
```
Key: "task:{task_id}:dependencies"
Type: Set
Members: dependent_task_id list

Key: "task:{task_id}:dependents"  
Type: Set
Members: task_id list (tasks that depend on this one)
```

### 3. Task Queues

#### Priority Queues
```
Key: "queue:tasks:urgent"
Type: Sorted Set
Score: queued_timestamp  
Members: task_id list

Key: "queue:tasks:high"
Key: "queue:tasks:normal" 
Key: "queue:tasks:low"
(Same structure as urgent queue)
```

#### Task Assignment
```
Key: "queue:assigned"
Type: Hash
Fields: {task_id: node_id, ...}

Key: "queue:processing"
Type: Sorted Set
Score: assignment_timestamp
Members: task_id list
```

#### Dead Letter Queue
```
Key: "queue:failed"
Type: Sorted Set  
Score: failure_timestamp
Members: task_id list (for manual retry/inspection)
```

### 4. Executor Nodes

#### Node Registration
```
Key: "node:{node_id}"
Type: Hash
TTL: 60 seconds (refreshed by heartbeat)
Fields:
  - id: node UUID
  - name: node name
  - host: hostname/IP
  - status: STARTING|READY|BUSY|OFFLINE|ERROR
  - capabilities: JSON string (NodeCapabilities)
  - current_tasks: integer (current workload)
  - max_tasks: integer (capacity)
  - last_heartbeat: ISO timestamp
  - last_task_completed: ISO timestamp
  - total_tasks_completed: integer
  - total_tasks_failed: integer
  - metadata: JSON string
```

#### Node Index
```
Key: "nodes:active"
Type: Set
Members: node_id list

Key: "nodes:by_capability:{capability}"
Type: Set  
Members: node_id list (e.g., "nodes:by_capability:gpu")
```

#### Node Task Assignment
```
Key: "node:{node_id}:tasks"
Type: Set
Members: assigned_task_id list

Key: "node:{node_id}:history"
Type: List (capped at 100)
Members: completed_task_id list (LIFO)
```

### 5. Event Streams

#### Workflow Events
```
Key: "events:workflow:{workflow_id}"
Type: Stream
Fields per entry:
  - event_type: workflow_created|workflow_started|workflow_completed|workflow_failed|workflow_cancelled
  - timestamp: milliseconds
  - data: JSON event payload
```

#### Task Events  
```
Key: "events:task:{task_id}"
Type: Stream
Fields per entry:
  - event_type: task_queued|task_assigned|task_started|task_completed|task_failed|task_retried
  - timestamp: milliseconds
  - node_id: executor node (if applicable)
  - data: JSON event payload
```

#### Global Event Stream
```
Key: "events:global"
Type: Stream (capped at 10000 entries)
Fields per entry:
  - event_type: workflow_*|task_*|node_*
  - entity_id: workflow_id|task_id|node_id
  - timestamp: milliseconds
  - data: JSON event payload
```

### 6. Pub/Sub Channels

#### Real-time Notifications
```
Channel: "notifications:workflow:{workflow_id}"
Payload: JSON event data

Channel: "notifications:node:{node_id}"  
Payload: JSON task assignment/completion data

Channel: "notifications:global"
Payload: JSON system events
```

#### Coordination Channels
```
Channel: "coordination:scheduler"
Payload: scheduler coordination messages

Channel: "coordination:machine_manager"
Payload: resource management messages
```

### 7. Configuration and Metadata

#### System Configuration
```
Key: "config:cluster"
Type: Hash
Fields:
  - cluster_id: unique cluster identifier
  - max_workflow_ttl: seconds
  - max_task_retries: integer
  - heartbeat_interval: seconds
  - cleanup_interval: seconds
  - version: system version
```

#### Statistics
```
Key: "stats:global"
Type: Hash  
Fields:
  - total_workflows: integer
  - active_workflows: integer
  - total_tasks: integer
  - completed_tasks: integer
  - failed_tasks: integer
  - active_nodes: integer
  - system_uptime: seconds
```

#### Locks (for coordination)
```
Key: "lock:workflow:{workflow_id}"
Type: String
TTL: 30 seconds
Value: node_id (who owns the lock)

Key: "lock:scheduler"
Type: String  
TTL: 10 seconds
Value: scheduler_instance_id
```

---

## Redis Operations Patterns

### 1. Workflow Submission
```lua
-- Atomic workflow creation
MULTI
HSET workflow:{workflow_id} [workflow_fields]
SADD workflows:active {workflow_id}
LPUSH workflow:{workflow_id}:tasks {task_ids...}
FOR EACH task_id:
    HSET task:{task_id} [task_fields]
    ZADD queue:tasks:{priority} {timestamp} {task_id}
PUBLISH notifications:global {"type":"workflow_created","id":"{workflow_id}"}
EXEC
```

### 2. Task Assignment
```lua
-- Atomic task assignment to node
MULTI
ZPOPMIN queue:tasks:{priority} 1
HSET task:{task_id} assigned_node_id {node_id} status ASSIGNED
SADD node:{node_id}:tasks {task_id}  
HSET queue:assigned {task_id} {node_id}
PUBLISH notifications:node:{node_id} {"type":"task_assigned","task_id":"{task_id}"}
EXEC
```

### 3. Task Completion
```lua
-- Atomic task completion
MULTI
HSET task:{task_id} status COMPLETED result {result} completed_at {timestamp}
SREM node:{node_id}:tasks {task_id}
HDEL queue:assigned {task_id}
HSET workflow:{workflow_id}:results {task_id} {result}
HINCRBY workflow:{workflow_id} completed_tasks 1
-- Check if workflow is complete and update status
PUBLISH notifications:workflow:{workflow_id} {"type":"task_completed","task_id":"{task_id}"}
EXEC
```

### 4. Node Heartbeat
```lua
-- Node health update
MULTI
HSET node:{node_id} last_heartbeat {timestamp} status READY
EXPIRE node:{node_id} 60
SADD nodes:active {node_id}
EXEC
```

---

## Performance Considerations

### Indexing Strategy
- **Workflow Queries**: Active workflows set for O(1) membership
- **Task Queues**: Sorted sets for O(log N) priority ordering  
- **Node Capabilities**: Sets for O(1) capability-based node selection
- **Event Streams**: Capped streams for memory efficiency

### Memory Management
- **TTL Policies**: Automatic cleanup of completed workflows (7 days default)
- **Stream Capping**: Global events limited to 10K entries
- **Node Expiration**: 60-second TTL on node registrations
- **Result Compression**: Optional JSON compression for large results

### Scalability Patterns  
- **Queue Sharding**: Multiple priority queues for load distribution
- **Node Partitioning**: Capability-based node selection
- **Event Streaming**: Separate streams per workflow/task for parallelism
- **Connection Pooling**: Redis connection pools per component

---

This schema provides a robust foundation for distributed workflow orchestration with Redis as the coordination backbone, enabling horizontal scaling, fault tolerance, and real-time monitoring capabilities.