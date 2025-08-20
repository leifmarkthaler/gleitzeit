# Gleitzeit Scaling Implementation Draft

## Current State Analysis

Gleitzeit v0.0.5 has a solid foundation for scaling but is currently limited to single-instance execution. The architecture includes:

- **Event-driven coordination** via Socket.IO (`hub/central_hub.py`)
- **Redis pub/sub** for state changes and coordination
- **Resource management system** with auto-scaling capabilities
- **Protocol-based provider abstraction** for extensibility
- **Distributed locking** mechanisms (Redis SET NX, SQL row-level)

## Scaling Approaches

### 1. Horizontal Worker Scaling (Phase 1 - Immediate)

**Concept**: Multiple ExecutionEngine instances sharing work from a central Redis queue.

```python
# Worker Pool Implementation
class DistributedExecutionEngine(ExecutionEngine):
    def __init__(
        self, 
        worker_id: str,
        hub_url: str = "redis://localhost:6379",
        worker_pool_size: int = 3
    ):
        super().__init__()
        self.worker_id = worker_id
        self.hub_url = hub_url
        self.sio = socketio.AsyncClient()
        
    async def start_distributed(self):
        # Connect to coordination hub
        await self.sio.connect(self.hub_url)
        await self.register_worker()
        
        # Start processing tasks from shared queue
        await self.process_distributed_queue()
    
    async def register_worker(self):
        await self.sio.emit('register_worker', {
            'worker_id': self.worker_id,
            'capabilities': self.get_provider_capabilities(),
            'max_concurrent': self.max_concurrent_tasks,
            'status': 'ready'
        })

# Load Balancer for Task Distribution
class TaskLoadBalancer:
    async def assign_task(self, task: Task) -> str:
        workers = await self.get_available_workers()
        
        # Scoring function considers:
        # - Current load (task count)
        # - Provider availability 
        # - Resource requirements
        # - Network latency
        best_worker = min(workers, key=lambda w: (
            w.current_load * 0.4 +
            w.latency_ms * 0.3 +
            (0 if w.has_required_providers(task) else 100) +
            w.queue_depth * 0.3
        ))
        
        await self.redis.lpush(f"worker:{best_worker.id}:tasks", task.json())
        await self.notify_worker_assignment(best_worker.id, task.id)
        
        return best_worker.id
```

**Benefits**:
- Simple to implement with existing Redis infrastructure
- Linear scaling of processing capacity
- Fault tolerance through worker redundancy
- Maintains workflow consistency through task affinity

**Implementation Steps**:
1. Modify ExecutionEngine to support distributed mode
2. Add worker registration and discovery
3. Implement task routing and load balancing
4. Add health monitoring and failover logic

### 2. Event-Driven Coordination (Phase 2 - Enhanced)

**Concept**: Expand the existing Socket.IO hub for full distributed coordination.

```python
# Enhanced Central Hub
class ScalableCentralHub(CentralHub):
    def __init__(self):
        super().__init__()
        self.worker_registry: Dict[str, WorkerInfo] = {}
        self.task_assignments: Dict[str, str] = {}  # task_id -> worker_id
        self.load_balancer = TaskLoadBalancer()
        
    async def handle_task_submission(self, workflow: Workflow):
        # Analyze task dependencies and resource requirements
        task_plan = await self.create_execution_plan(workflow)
        
        # Assign tasks to optimal workers
        for task in task_plan.tasks:
            worker_id = await self.load_balancer.assign_task(task)
            self.task_assignments[task.id] = worker_id
            
            # Send task to specific worker
            await self.sio.emit('execute_task', task.dict(), room=f"worker_{worker_id}")
    
    async def handle_worker_heartbeat(self, worker_id: str, metrics: Dict[str, Any]):
        # Update worker health and load metrics
        self.worker_registry[worker_id].update_metrics(metrics)
        
        # Trigger rebalancing if needed
        if self.should_rebalance():
            await self.rebalance_tasks()

# Regional Hub for Geographic Distribution
class RegionalHub(ScalableCentralHub):
    def __init__(self, region: str, peer_hubs: List[str]):
        super().__init__()
        self.region = region
        self.peer_hubs = peer_hubs
        
    async def handle_cross_region_request(self, task: Task):
        # Route to closest available region
        target_region = await self.select_optimal_region(task)
        if target_region != self.region:
            await self.forward_to_region(task, target_region)
        else:
            await self.handle_task_submission(task)
```

### 3. Provider Pool Scaling (Phase 3 - Advanced)

**Concept**: Scale individual providers (Ollama, Docker, MCP) independently.

```python
# Ollama Provider Pool
class ScalableOllamaProvider(OllamaProvider):
    def __init__(self, endpoints: List[str], load_balancer: str = "round_robin"):
        self.endpoints = endpoints
        self.load_balancer = self.create_load_balancer(load_balancer)
        self.health_checker = ProviderHealthChecker(endpoints)
        
    async def chat(self, messages: List[Dict], model: str, **kwargs) -> Dict[str, Any]:
        # Select optimal endpoint
        endpoint = await self.load_balancer.select_endpoint(
            model=model,
            estimated_tokens=self.estimate_tokens(messages)
        )
        
        # Execute with fallback chain
        try:
            return await self.execute_on_endpoint(endpoint, messages, model, **kwargs)
        except Exception as e:
            # Try next available endpoint
            fallback_endpoint = await self.load_balancer.get_fallback_endpoint(endpoint)
            if fallback_endpoint:
                return await self.execute_on_endpoint(fallback_endpoint, messages, model, **kwargs)
            raise

# Docker Provider Pool with Resource Management
class ScalableDockerProvider(PythonProvider):
    def __init__(self, docker_swarm_config: Dict[str, Any]):
        self.swarm = DockerSwarmManager(docker_swarm_config)
        self.resource_allocator = ResourceAllocator()
        
    async def execute(self, code: str, **kwargs) -> Dict[str, Any]:
        # Calculate resource requirements
        resources = await self.estimate_resources(code)
        
        # Allocate container with appropriate resources
        container = await self.swarm.create_container(
            cpu_limit=resources.cpu,
            memory_limit=resources.memory,
            timeout=kwargs.get('timeout', 30)
        )
        
        try:
            return await container.execute_code(code)
        finally:
            await self.swarm.cleanup_container(container.id)
```

## Infrastructure Requirements

### Phase 1: Basic Scaling
- **Redis Cluster**: 3-node cluster for high availability
- **Load Balancer**: nginx/HAProxy for request distribution
- **Monitoring**: Prometheus + Grafana for metrics
- **Service Discovery**: Redis-based worker registry

### Phase 2: Enhanced Coordination
- **Message Queue**: Redis Streams for reliable event delivery
- **Distributed Tracing**: OpenTelemetry integration
- **Config Management**: Consul/etcd for dynamic configuration
- **Log Aggregation**: ELK stack or similar

### Phase 3: Production Scale
- **Container Orchestration**: Kubernetes with HPA
- **Service Mesh**: Istio for traffic management
- **Database**: PostgreSQL cluster for persistent state
- **Object Storage**: S3-compatible for large artifacts

## Auto-Scaling Implementation

```python
class AutoScaler:
    def __init__(self, min_workers: int = 2, max_workers: int = 20):
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.scale_up_threshold = 0.8    # CPU/queue utilization
        self.scale_down_threshold = 0.3
        self.cooldown_period = 300       # 5 minutes
        
    async def check_scaling_conditions(self):
        metrics = await self.get_cluster_metrics()
        
        # Scale up conditions
        if (metrics.avg_cpu > self.scale_up_threshold or 
            metrics.queue_depth > metrics.worker_count * 5):
            if self.can_scale_up():
                await self.scale_up()
                
        # Scale down conditions  
        elif (metrics.avg_cpu < self.scale_down_threshold and
              metrics.queue_depth < metrics.worker_count * 2):
            if self.can_scale_down():
                await self.scale_down()
    
    async def scale_up(self):
        new_worker_count = min(
            self.current_workers + self.calculate_scale_factor(),
            self.max_workers
        )
        
        for i in range(new_worker_count - self.current_workers):
            await self.launch_worker(f"worker-{uuid.uuid4()}")
    
    async def scale_down(self):
        # Gracefully drain workers
        workers_to_remove = self.select_workers_for_removal()
        for worker in workers_to_remove:
            await self.drain_worker(worker.id)
            await self.terminate_worker(worker.id)
```

## Kubernetes Deployment

```yaml
# gleitzeit-hub.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-hub
spec:
  replicas: 2  # HA for coordination
  template:
    spec:
      containers:
      - name: hub
        image: gleitzeit:latest
        command: ["python", "-m", "gleitzeit.hub.central_hub"]
        ports:
        - containerPort: 8000
        env:
        - name: REDIS_URL
          value: "redis://redis-cluster:6379"

---
# gleitzeit-workers.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-workers
spec:
  replicas: 5
  template:
    spec:
      containers:
      - name: worker
        image: gleitzeit:latest
        command: ["python", "-m", "gleitzeit.core.execution_engine"]
        env:
        - name: WORKER_MODE
          value: "distributed"
        - name: HUB_URL
          value: "http://gleitzeit-hub:8000"
        - name: WORKER_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2
            memory: 4Gi

---
# Auto-scaling config
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gleitzeit-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gleitzeit-workers
  minReplicas: 2
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Pods
    pods:
      metric:
        name: queue_depth_per_worker
      target:
        type: AverageValue
        averageValue: "5"
```

## Implementation Roadmap

### Week 1-2: Foundation
- [ ] Modify ExecutionEngine for distributed mode
- [ ] Implement worker registration and discovery
- [ ] Add basic load balancing logic
- [ ] Create health check endpoints

### Week 3-4: Coordination
- [ ] Enhance CentralHub for task routing
- [ ] Implement task assignment and tracking
- [ ] Add worker failure detection and recovery
- [ ] Create monitoring dashboard

### Week 5-6: Provider Scaling
- [ ] Implement Ollama provider pooling
- [ ] Add Docker Swarm integration
- [ ] Create resource allocation system
- [ ] Add provider auto-scaling

### Week 7-8: Production Ready
- [ ] Kubernetes deployment configs
- [ ] Distributed tracing integration
- [ ] Performance optimization
- [ ] Documentation and testing

## Testing Strategy

```python
# Distributed Testing Framework
class DistributedTestSuite:
    async def test_worker_scaling(self):
        # Start with 2 workers
        cluster = await self.create_test_cluster(workers=2)
        
        # Submit load that requires scaling
        workflows = [self.create_test_workflow() for _ in range(10)]
        await asyncio.gather(*[cluster.submit(w) for w in workflows])
        
        # Verify auto-scaling occurred
        assert await cluster.get_worker_count() > 2
        
        # Wait for load to decrease
        await asyncio.sleep(600)  # Cooldown period
        
        # Verify scale-down
        assert await cluster.get_worker_count() == 2
    
    async def test_failover(self):
        cluster = await self.create_test_cluster(workers=3)
        
        # Kill one worker mid-execution
        worker_to_kill = cluster.workers[0]
        workflow = self.create_long_running_workflow()
        
        task = asyncio.create_task(cluster.submit(workflow))
        await asyncio.sleep(5)  # Let it start
        
        await cluster.kill_worker(worker_to_kill.id)
        
        # Workflow should complete on remaining workers
        result = await task
        assert result.status == "completed"
```

## Performance Expectations

### Single Instance Baseline
- ~50 concurrent tasks
- ~500 tasks/hour throughput
- ~2GB memory usage

### 5-Worker Cluster
- ~250 concurrent tasks (5x scaling)
- ~2,500 tasks/hour throughput
- ~10GB total memory usage
- Sub-second task assignment latency

### 20-Worker Auto-Scaled Cluster
- ~1,000 concurrent tasks
- ~10,000 tasks/hour throughput
- ~40GB total memory usage
- <100ms p95 task assignment latency

## Security Considerations

- **Worker Authentication**: JWT tokens for worker registration
- **Network Encryption**: TLS for all inter-worker communication
- **Resource Isolation**: Container-based execution sandboxing
- **Rate Limiting**: Per-worker and per-user request limits
- **Audit Logging**: Complete task execution audit trail

## Migration Path

1. **Enable distributed mode** as opt-in feature
2. **Parallel operation** - run distributed alongside single-instance
3. **Gradual migration** - move workflows incrementally
4. **Feature parity** - ensure all features work in distributed mode
5. **Deprecate single-instance** - after proven stability

This architecture leverages Gleitzeit's existing event-driven foundation while adding the distributed coordination needed for horizontal scaling. The phased approach allows for incremental implementation and testing.