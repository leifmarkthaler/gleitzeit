# Horizontal Scaling Architecture for Gleitzeit

## Current State Analysis

### What We Have Now (Good Foundation)
- **Unified Redis Streams** - Natural partitioning via consumer groups
- **Stateless System Manager** - Can run multiple instances
- **Shared Redis Backend** - Centralized state storage
- **Consumer Groups** - Built-in work distribution

### Scaling Challenges
1. **Workflow Affinity** - Tasks in a workflow should stay together for efficiency
2. **Resource Locality** - Minimize data transfer between nodes
3. **Load Distribution** - Even distribution across nodes
4. **Failure Handling** - Workflow recovery if a node fails

## Scaling Strategy Options

### Option 1: Namespace-Based Partitioning (Your Suggestion)
```
Namespace: "customer-a"
├── Workflow-1 → Node-1
│   ├── Task-1a
│   ├── Task-1b
│   └── Task-1c
└── Workflow-2 → Node-1
    └── Task-2a

Namespace: "customer-b"  
├── Workflow-3 → Node-2
│   └── Task-3a
└── Workflow-4 → Node-2
    ├── Task-4a
    └── Task-4b
```

**Pros:**
- Clean isolation between tenants/customers
- Simple routing logic
- Good for multi-tenant SaaS

**Cons:**
- Uneven load if namespaces have different activity
- Hard to rebalance without moving entire namespaces
- Single namespace can't scale beyond one node

### Option 2: Consistent Hashing with Workflow Affinity ⭐ (RECOMMENDED)
```
Workflow ID → Hash → Node Assignment
workflow-abc123 → hash(abc123) → Node-2
  All tasks for workflow-abc123 → Node-2

Consumer Groups:
- node-1-consumers (handles hash range 0-33%)
- node-2-consumers (handles hash range 34-66%)  
- node-3-consumers (handles hash range 67-100%)
```

**Pros:**
- Even distribution of workflows
- Tasks stay with their workflow
- Dynamic rebalancing possible
- Scales smoothly

**Cons:**
- More complex routing
- Need consistent hash implementation

### Option 3: Stream Partitioning with Sticky Sessions
```
Redis Streams Partitions:
- gleitzeit:events:stream:0 → Node-1
- gleitzeit:events:stream:1 → Node-2
- gleitzeit:events:stream:2 → Node-3

Workflow → Partition mapping via modulo
```

**Pros:**
- Leverages Redis Streams natively
- Good throughput
- Clear ownership

**Cons:**
- Rebalancing requires stream migration
- Complex partition management

## Recommended Architecture: Hybrid Approach

### Core Design: Consistent Hashing + Smart Routing

```python
class ScalingArchitecture:
    """
    Hybrid scaling using consistent hashing with workflow affinity
    and optional namespace isolation.
    """
    
    def __init__(self):
        self.nodes = {}  # node_id -> node_info
        self.hash_ring = ConsistentHashRing()
        self.namespace_affinity = {}  # Optional namespace → node mapping
    
    def route_workflow(self, workflow_id: str, namespace: Optional[str] = None):
        """Route workflow to appropriate node."""
        
        # 1. Check for namespace affinity (optional)
        if namespace and namespace in self.namespace_affinity:
            return self.namespace_affinity[namespace]
        
        # 2. Use consistent hashing for even distribution
        node = self.hash_ring.get_node(workflow_id)
        
        # 3. Ensure all tasks for workflow go to same node
        self.workflow_assignments[workflow_id] = node
        
        return node
    
    def get_task_node(self, task_id: str, workflow_id: str):
        """Tasks always follow their workflow."""
        return self.workflow_assignments.get(workflow_id)
```

### Implementation Plan

#### 1. Node Identity & Discovery
```yaml
# Each node configuration
node:
  id: "node-1"
  region: "us-east-1"
  capacity: 100  # Max concurrent workflows
  specialization: ["python", "gpu"]  # Optional capabilities
  
service_discovery:
  method: "redis"  # Use Redis for coordination
  heartbeat_interval: 5s
  node_timeout: 30s
```

#### 2. Consumer Group Partitioning
```python
# Each node creates its own consumer group
consumer_group = f"gleitzeit-{node_id}"

# Stream key sharding
def get_stream_shard(workflow_id: str, num_shards: int = 10):
    """Determine which stream shard to use."""
    hash_value = hashlib.md5(workflow_id.encode()).hexdigest()
    shard = int(hash_value, 16) % num_shards
    return f"gleitzeit:events:stream:{shard}"
```

#### 3. Workflow Routing Layer
```python
class WorkflowRouter:
    """
    Routes workflows to nodes based on multiple strategies.
    """
    
    def __init__(self, strategy="consistent_hash"):
        self.strategy = strategy
        self.nodes = self._discover_nodes()
        
    async def submit_workflow(self, workflow: Workflow, hints: Dict = None):
        """
        Submit workflow with routing hints.
        
        Hints can include:
        - namespace: Customer/tenant isolation
        - affinity: Prefer specific node characteristics
        - priority: High priority workflows to dedicated nodes
        """
        
        # Determine target node
        if hints.get("namespace"):
            node = self._get_namespace_node(hints["namespace"])
        elif hints.get("affinity"):
            node = self._get_affinity_node(hints["affinity"])
        else:
            node = self._get_hash_node(workflow.id)
        
        # Record assignment
        await self._record_assignment(workflow.id, node.id)
        
        # Route to node's stream partition
        stream_key = self._get_node_stream(node.id)
        await self._emit_to_stream(stream_key, workflow)
```

#### 4. Node-Local Execution
```python
class NodeExecutor:
    """
    Executes workflows assigned to this node.
    """
    
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.consumer_group = f"node-{node_id}"
        
    async def start(self):
        """Start consuming from assigned partitions."""
        
        # Subscribe to node's streams
        streams = self._get_node_streams()
        
        # Process with consumer group
        while True:
            messages = await redis.xreadgroup(
                self.consumer_group,
                self.node_id,
                streams,
                block=1000
            )
            
            for stream, entries in messages:
                for msg_id, data in entries:
                    workflow_id = data['workflow_id']
                    
                    # Verify this workflow belongs to us
                    if self._should_process(workflow_id):
                        await self._process_workflow(workflow_id, data)
                    else:
                        # Re-route if needed (node failure recovery)
                        await self._reroute(workflow_id, data)
```

### Scaling Scenarios

#### Adding Nodes (Scale Out)
```python
async def add_node(new_node: Node):
    """Add new node to cluster."""
    
    # 1. Register node
    await redis.hset("nodes", new_node.id, new_node.to_json())
    
    # 2. Update hash ring
    hash_ring.add_node(new_node.id)
    
    # 3. Rebalance workflows (optional)
    if auto_rebalance:
        workflows_to_move = hash_ring.get_rebalanced_keys(new_node.id)
        for workflow_id in workflows_to_move:
            await migrate_workflow(workflow_id, new_node.id)
```

#### Node Failure (Automatic Recovery)
```python
async def handle_node_failure(failed_node_id: str):
    """Handle node failure with automatic recovery."""
    
    # 1. Detect failure via heartbeat timeout
    
    # 2. Remove from hash ring
    hash_ring.remove_node(failed_node_id)
    
    # 3. Reassign workflows
    orphaned_workflows = await get_node_workflows(failed_node_id)
    
    for workflow_id in orphaned_workflows:
        new_node = hash_ring.get_node(workflow_id)
        await reassign_workflow(workflow_id, new_node)
        
    # 4. Resume workflow execution
    await resume_orphaned_tasks(orphaned_workflows)
```

### Configuration Example

```yaml
# gleitzeit-scaling.yaml
scaling:
  strategy: "consistent_hash"  # or "namespace" or "hybrid"
  
  nodes:
    min: 2
    max: 10
    auto_scale: true
    
  partitioning:
    stream_shards: 10  # Number of stream partitions
    rebalance_threshold: 0.2  # 20% load difference triggers rebalance
    
  routing:
    default_strategy: "consistent_hash"
    namespace_isolation: false  # Set true for multi-tenant
    sticky_sessions: true  # Keep workflow on same node
    
  health:
    heartbeat_interval: 5s
    node_timeout: 30s
    failure_detection: "heartbeat"  # or "gossip"
    
  consumer_groups:
    pattern: "node-{node_id}"  # Consumer group naming
    max_pending: 1000  # Max pending messages per group
```

## Implementation Priority

### Phase 1: Basic Horizontal Scaling (Week 1)
1. **Node Registration** - Nodes register themselves in Redis
2. **Consumer Group per Node** - Each node has its own consumer group
3. **Simple Hash-based Routing** - Basic workflow distribution

### Phase 2: Workflow Affinity (Week 2)
1. **Workflow-to-Node Mapping** - Track assignments in Redis
2. **Task Routing** - Ensure tasks follow workflows
3. **Basic Rebalancing** - Manual rebalancing support

### Phase 3: Advanced Features (Week 3-4)
1. **Auto-scaling** - Add/remove nodes based on load
2. **Failure Recovery** - Automatic workflow migration
3. **Namespace Support** - Optional tenant isolation
4. **Monitoring** - Scaling metrics and dashboards

## Key Design Decisions

### Why Consistent Hashing?
- **Even Distribution** - Workflows spread evenly across nodes
- **Minimal Disruption** - Adding nodes only moves ~1/n workflows
- **Predictable** - Same workflow always goes to same node
- **Standard** - Well-understood algorithm

### Why Workflow Affinity?
- **Efficiency** - No cross-node communication for task dependencies
- **Caching** - Workflow context stays hot in memory
- **Simplicity** - Easier debugging and monitoring

### Why Redis Streams Consumer Groups?
- **Built-in Distribution** - Redis handles work distribution
- **Failure Recovery** - Automatic message redelivery
- **Back Pressure** - Natural flow control
- **No Additional Infrastructure** - Uses existing Redis

## Monitoring & Operations

### Key Metrics
```python
metrics = {
    "nodes": {
        "total": 5,
        "healthy": 5,
        "capacity_used": 0.65  # 65% capacity
    },
    "distribution": {
        "node-1": 145,  # workflows
        "node-2": 143,
        "node-3": 147,
        "node-4": 144,
        "node-5": 146
    },
    "performance": {
        "avg_workflow_time": 1.2,  # seconds
        "p99_workflow_time": 3.5,
        "tasks_per_second": 1250
    }
}
```

### Operations Commands
```bash
# Add new node
gleitzeit scale add --node-id node-6 --capacity 100

# Remove node (with graceful migration)
gleitzeit scale remove --node-id node-2 --migrate

# Rebalance cluster
gleitzeit scale rebalance --strategy even

# Show distribution
gleitzeit scale status
```

## Conclusion

**Recommended Approach: Consistent Hashing with Workflow Affinity**

This provides:
- ✅ Even load distribution
- ✅ Workflow/task locality  
- ✅ Smooth scaling
- ✅ Automatic failure recovery
- ✅ Optional namespace support

The beauty is that our unified Redis Streams architecture already supports this - we just need to add the routing layer on top!