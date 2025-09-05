# Gleitzeit Orchestration-Only Scaling Architecture
## Separating Orchestration from Execution

**Date:** 2025-08-30  
**Key Principle:** Scale orchestration, not execution

---

## Executive Summary

Gleitzeit should scale **orchestration and management** (workflow coordination, task scheduling, dependency resolution) while **providers handle actual execution** independently. This creates a lightweight, highly scalable orchestration layer that delegates work to providers which manage their own resources.

**Core Architecture:**
- **Gleitzeit Cluster**: Scales horizontally for orchestration
- **Provider Pools**: Independent execution resources (not scaled by Gleitzeit)
- **Clean Separation**: Orchestration ≠ Execution

---

## Conceptual Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ORCHESTRATION LAYER                      │
│                  (Scales Horizontally)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────┐              │
│  │      Workflow Orchestration Cluster      │              │
│  │                                          │              │
│  │  • Workflow Coordinators (3-10)          │              │
│  │  • Task Schedulers (3-10)                │              │
│  │  • Dependency Resolvers                  │              │
│  │  • State Management                      │              │
│  │                                          │              │
│  │  Responsibilities:                       │              │
│  │  - Track workflow/task state             │              │
│  │  - Resolve dependencies                  │              │
│  │  - Schedule tasks for execution          │              │
│  │  - Monitor completion                    │              │
│  │  - Handle retries (orchestration only)   │              │
│  └─────────────────────────────────────────┘              │
│                         ↓                                   │
│              Task Assignment Protocol                       │
│                         ↓                                   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     EXECUTION LAYER                         │
│                (Managed Independently)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Provider   │  │   Provider   │  │   Provider   │    │
│  │   Pool A     │  │   Pool B     │  │   Pool C     │    │
│  │              │  │              │  │              │    │
│  │  • Python    │  │  • Shell     │  │  • HTTP      │    │
│  │  • 10 workers│  │  • 5 workers │  │  • 20 workers│    │
│  │  • Self-     │  │  • Docker    │  │  • Lambda    │    │
│  │    managed   │  │    based     │  │    based     │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                             │
│  Providers handle:                                         │
│  - Actual task execution                                   │
│  - Resource management                                     │
│  - Scaling their own workers                               │
│  - Load balancing within pool                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Revised Component Architecture

### 1. Orchestration Components (Scale These)

#### Task Scheduler Service
```python
class LightweightTaskScheduler:
    """Schedules tasks but doesn't execute them"""
    
    def __init__(self, scheduler_id: str, redis: Redis):
        self.scheduler_id = scheduler_id
        self.redis = redis
        # No execution resources, just orchestration
        
    async def schedule_task(self, task: Task) -> str:
        """Schedule task for execution by provider"""
        # 1. Find capable provider
        provider = await self.find_provider(task.protocol)
        
        # 2. Create execution request
        execution_request = ExecutionRequest(
            task_id=task.id,
            protocol=task.protocol,
            method=task.method,
            params=task.params,
            timeout=task.timeout
        )
        
        # 3. Queue for provider (don't execute)
        await self.redis.lpush(
            f"provider:{provider.id}:queue",
            execution_request.to_json()
        )
        
        # 4. Track scheduling
        await self.redis.hset(
            f"task:{task.id}:scheduling",
            mapping={
                'scheduled_at': time.time(),
                'provider_id': provider.id,
                'scheduler_id': self.scheduler_id
            }
        )
        
        return task.id
```

#### Workflow Coordinator
```python
class LightweightWorkflowCoordinator:
    """Coordinates workflows without executing tasks"""
    
    def __init__(self, coordinator_id: str, redis: Redis):
        self.coordinator_id = coordinator_id
        self.redis = redis
        # No execution, pure coordination
        
    async def coordinate_workflow(self, workflow_id: str):
        """Orchestrate workflow execution"""
        # 1. Track workflow state
        state = await self.get_workflow_state(workflow_id)
        
        # 2. Find ready tasks (dependency resolution)
        ready_tasks = await self.find_ready_tasks(workflow_id, state)
        
        # 3. Schedule tasks (don't execute)
        for task in ready_tasks:
            await self.schedule_task_for_execution(task)
            
        # 4. Monitor completion (via events)
        # Providers emit completion events
        # We just track state changes
```

#### Dependency Resolver
```python
class StatelessDependencyResolver:
    """Resolves dependencies without execution context"""
    
    async def resolve_dependencies(
        self,
        task: Task,
        workflow_state: WorkflowState
    ) -> bool:
        """Check if task dependencies are satisfied"""
        for dep_id in task.dependencies:
            dep_state = workflow_state.task_states.get(dep_id)
            if dep_state != TaskStatus.COMPLETED:
                return False
        return True
    
    async def get_task_results_for_params(
        self,
        task: Task,
        workflow_id: str
    ) -> Dict[str, Any]:
        """Get dependency results for parameter substitution"""
        # Just fetch results, don't execute anything
        results = {}
        for dep_id in task.dependencies:
            result = await self.redis.hget(
                f"task:{dep_id}:result",
                "data"
            )
            results[dep_id] = json.loads(result)
        return results
```

### 2. Provider Interface (Don't Scale These)

#### Provider Protocol
```python
class ProviderInterface(Protocol):
    """Standard interface for all providers"""
    
    async def execute_task(self, request: ExecutionRequest) -> TaskResult:
        """Execute a single task"""
        ...
    
    async def get_capacity(self) -> ProviderCapacity:
        """Report current capacity"""
        ...
    
    async def health_check(self) -> HealthStatus:
        """Report health status"""
        ...
```

#### Provider Implementation Example
```python
class PythonProvider:
    """Python execution provider (manages own resources)"""
    
    def __init__(self, provider_config: Dict):
        self.id = f"python-provider-{uuid.uuid4().hex[:8]}"
        self.max_workers = provider_config.get('max_workers', 10)
        
        # Provider manages its own worker pool
        self.executor = ProcessPoolExecutor(max_workers=self.max_workers)
        self.current_tasks = {}
        
    async def run(self):
        """Provider main loop"""
        while True:
            # 1. Pull task from queue
            task_json = await self.redis.brpop(
                f"provider:{self.id}:queue",
                timeout=1
            )
            
            if task_json:
                # 2. Execute with own resources
                request = ExecutionRequest.from_json(task_json)
                asyncio.create_task(self.execute_task(request))
                
            # 3. Report capacity periodically
            await self.report_capacity()
            
    async def execute_task(self, request: ExecutionRequest):
        """Execute task with provider's resources"""
        # This is where actual execution happens
        # Provider manages its own scaling/resources
        try:
            result = await self.executor.submit(
                execute_python_code,
                request.params['code']
            )
            
            # Report completion to orchestration layer
            await self.emit_task_completed(request.task_id, result)
        except Exception as e:
            await self.emit_task_failed(request.task_id, str(e))
    
    async def scale_workers(self, new_count: int):
        """Provider handles its own scaling"""
        # Provider decides how to scale
        # Not controlled by Gleitzeit orchestration
        self.executor._max_workers = new_count
```

---

## Scaling Characteristics

### What Scales Horizontally (Orchestration)

| Component | Scaling Factor | Resource Usage | Instances |
|-----------|---------------|----------------|-----------|
| **API Gateway** | Request rate | Low (routing) | 3-10 |
| **Workflow Coordinator** | Active workflows | Low (state tracking) | 3-10 |
| **Task Scheduler** | Task throughput | Low (scheduling) | 3-10 |
| **Dependency Resolver** | Workflow complexity | Low (graph traversal) | 2-5 |
| **Event Router** | Event rate | Low (pub/sub) | 2-5 |

**Total Resource Usage:** Minimal - mostly I/O bound operations

### What Doesn't Scale (Execution)

| Component | Management | Scaling | Resources |
|-----------|------------|---------|-----------|
| **Python Provider** | Self-managed | Internal pool | High (CPU) |
| **Shell Provider** | Self-managed | Docker containers | Medium |
| **HTTP Provider** | Self-managed | Connection pool | Low |
| **LLM Provider** | Self-managed | GPU instances | Very High |
| **MCP Provider** | Self-managed | Server processes | Variable |

**Key Point:** Providers manage their own resources and scaling

---

## Lightweight Orchestration Stack

### Minimal Resource Requirements

```yaml
# Orchestration-only resource needs
Workflow Coordinator:
  CPU: 0.1 cores
  Memory: 256MB
  Storage: None (stateless)
  
Task Scheduler:
  CPU: 0.1 cores  
  Memory: 256MB
  Storage: None (stateless)

Event Router:
  CPU: 0.05 cores
  Memory: 128MB
  Storage: None (stateless)

# Compare to execution resources
Python Provider:
  CPU: 4-8 cores (for worker pool)
  Memory: 4-8GB (for execution)
  Storage: Variable (for artifacts)
```

### Deployment Example (Kubernetes)

```yaml
# Lightweight orchestration deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: workflow-coordinator
spec:
  replicas: 5  # Can run many coordinators
  template:
    spec:
      containers:
      - name: coordinator
        image: gleitzeit:orchestrator
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"  # 0.1 cores
          limits:
            memory: "512Mi"
            cpu: "200m"
---
# Separate provider deployment (not scaled by Gleitzeit)
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: python-provider
spec:
  replicas: 1  # Provider manages internal scaling
  template:
    spec:
      containers:
      - name: provider
        image: gleitzeit:python-provider
        resources:
          requests:
            memory: "4Gi"
            cpu: "4"  # Needs real resources
          limits:
            memory: "8Gi"
            cpu: "8"
```

---

## Communication Protocol

### Task Assignment Protocol
```python
# Lightweight protocol between orchestration and execution

@dataclass
class ExecutionRequest:
    """Request from orchestrator to provider"""
    task_id: str
    protocol: str
    method: str
    params: Dict[str, Any]
    timeout: Optional[int]
    priority: int = 0
    
    # No execution context, just the request

@dataclass
class ExecutionResponse:
    """Response from provider to orchestrator"""
    task_id: str
    status: TaskStatus
    result: Optional[Any]
    error: Optional[str]
    metrics: Optional[Dict]  # execution time, resources used
    
    # Provider reports back, orchestrator tracks

class OrchestratorProviderProtocol:
    """Communication between layers"""
    
    async def assign_task(
        self,
        task: Task,
        provider_id: str
    ) -> str:
        """Orchestrator assigns task to provider"""
        request = ExecutionRequest(
            task_id=task.id,
            protocol=task.protocol,
            method=task.method,
            params=task.params
        )
        
        # Push to provider queue
        await self.redis.lpush(
            f"provider:{provider_id}:queue",
            request.to_json()
        )
        
        return task.id
    
    async def handle_completion(
        self,
        response: ExecutionResponse
    ):
        """Provider reports completion to orchestrator"""
        # Update task state
        await self.redis.hset(
            f"task:{response.task_id}:state",
            mapping={
                'status': response.status,
                'completed_at': time.time()
            }
        )
        
        # Store result if successful
        if response.result:
            await self.redis.hset(
                f"task:{response.task_id}:result",
                'data',
                json.dumps(response.result)
            )
        
        # Emit event for workflow coordinator
        await self.emit_event(
            TaskCompletedEvent(
                task_id=response.task_id,
                status=response.status
            )
        )
```

---

## Provider Registration & Discovery

### Provider Self-Registration
```python
class ProviderRegistry:
    """Lightweight provider registry"""
    
    async def register_provider(
        self,
        provider_id: str,
        protocols: List[str],
        capacity: int,
        endpoint: str
    ):
        """Register provider capabilities"""
        await self.redis.hset(
            f"providers:{provider_id}",
            mapping={
                'protocols': json.dumps(protocols),
                'capacity': capacity,
                'endpoint': endpoint,
                'status': 'active',
                'registered_at': time.time()
            }
        )
        
        # Index by protocol for fast lookup
        for protocol in protocols:
            await self.redis.sadd(
                f"protocol:{protocol}:providers",
                provider_id
            )
    
    async def find_provider(
        self,
        protocol: str,
        method: str = None
    ) -> Optional[ProviderInfo]:
        """Find capable provider (don't care about resources)"""
        # Get all providers for protocol
        provider_ids = await self.redis.smembers(
            f"protocol:{protocol}:providers"
        )
        
        # Pick one (simple round-robin or random)
        # Let provider handle its own load balancing
        if provider_ids:
            selected_id = random.choice(list(provider_ids))
            info = await self.redis.hgetall(f"providers:{selected_id}")
            return ProviderInfo(**info)
        
        return None
```

---

## Benefits of This Architecture

### 1. True Separation of Concerns

**Orchestration Layer:**
- Workflow state management
- Dependency resolution
- Task scheduling
- Retry orchestration (not execution)
- Event coordination

**Execution Layer (Providers):**
- Actual task execution
- Resource management
- Worker pool scaling
- Load balancing within provider
- Execution optimization

### 2. Independent Scaling

```python
# Orchestration scales based on workflow/task count
orchestration_instances = ceil(active_workflows / 100)  # 1 per 100 workflows

# Providers scale based on execution needs
python_workers = ceil(python_tasks_per_second * avg_execution_time)
llm_instances = ceil(llm_requests / gpu_capacity)
```

### 3. Resource Efficiency

```yaml
# 1000 workflows/hour orchestration needs:
Total Orchestration Resources:
  CPU: 1-2 cores total
  Memory: 2-4 GB total
  Instances: 5-10 lightweight containers

# Execution resources (managed separately):
Python Provider Pool:
  CPU: 32 cores (for actual execution)
  Memory: 64 GB
  
LLM Provider Pool:
  GPUs: 4 x A100
  Memory: 320 GB
```

### 4. Provider Independence

Providers can:
- Use different scaling strategies (VMs, containers, Lambda)
- Optimize for their workload (CPU, GPU, I/O)
- Implement custom resource management
- Scale independently of orchestration

---

## Migration Path

### Phase 1: Extract Execution from Orchestration
1. Move execution logic to providers
2. Keep orchestration in lightweight services
3. Define clear protocol boundaries

### Phase 2: Implement Provider Pools
1. Create provider implementations
2. Each manages its own resources
3. Register with orchestration layer

### Phase 3: Scale Orchestration Only
1. Deploy multiple lightweight orchestrators
2. Use minimal resources
3. Let providers handle execution scaling

---

## Example Deployment Sizes

### Small (10 workflows/hour)
```yaml
Orchestration:
  - 1 coordinator (256MB RAM)
  - 1 scheduler (256MB RAM)
  - 1 Redis (1GB RAM)
  Total: ~1.5GB RAM, 0.5 CPU cores

Providers:
  - 1 Python provider (4GB RAM, 2 workers)
  - 1 Shell provider (2GB RAM, Docker)
  Total: 6GB RAM, 4 CPU cores
```

### Medium (1000 workflows/hour)
```yaml
Orchestration:
  - 3 coordinators (768MB RAM)
  - 3 schedulers (768MB RAM)
  - Redis cluster (4GB RAM)
  Total: ~5.5GB RAM, 2 CPU cores

Providers:
  - 2 Python providers (16GB RAM, 10 workers)
  - 2 Shell providers (8GB RAM)
  - 1 HTTP provider (2GB RAM)
  Total: 26GB RAM, 20 CPU cores
```

### Large (10000 workflows/hour)
```yaml
Orchestration:
  - 10 coordinators (2.5GB RAM)
  - 10 schedulers (2.5GB RAM)
  - Redis cluster (16GB RAM)
  Total: ~21GB RAM, 5 CPU cores

Providers:
  - Auto-scaled based on actual execution needs
  - Could be 100s of cores for execution
  - Managed independently (K8s HPA, AWS Lambda, etc.)
```

---

## Conclusion

By separating orchestration from execution:

1. **Gleitzeit becomes a lightweight orchestration layer** that scales easily
2. **Providers handle actual execution** with their own resource management
3. **Clean boundaries** enable independent scaling and optimization
4. **Resource efficiency** - orchestration needs minimal resources
5. **Provider flexibility** - each provider optimizes for its workload

This architecture allows Gleitzeit to handle millions of tasks while using minimal resources for orchestration, delegating the heavy lifting to specialized providers that manage their own scaling.

---

**Document Status:** Complete  
**Architecture Type:** Orchestration-focused  
**Resource Usage:** Minimal for orchestration  
**Scaling Capability:** Unlimited (orchestration), Provider-dependent (execution)