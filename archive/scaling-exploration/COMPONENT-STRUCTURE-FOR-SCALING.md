# Component Structure for Orchestration-Only Scaling
## Restructuring Client, Workflow, and API Architecture

**Date:** 2025-08-30  
**Based on:** Current implementation analysis  
**Goal:** Enable orchestration-only horizontal scaling

---

## Executive Summary

The current Gleitzeit architecture is **70% ready** for orchestration-only scaling. Key changes needed:

1. **Split ExecutionEngine** into orchestration and coordination components
2. **Convert NativeAdapter** to use orchestration services instead of direct engine
3. **Implement async task assignment** protocol for providers
4. **Distribute workflow management** across coordinator cluster

---

## Proposed Component Architecture

```
┌────────────────────────────────────────────────────────────┐
│                         CLIENT                             │
├────────────────────────────────────────────────────────────┤
│  ModularGleitzeitClient                                    │
│  ├── APIAdapter → HTTP calls to API Gateway               │
│  └── OrchestrationAdapter → Direct to Orchestration Layer │
│       (replaces NativeAdapter)                             │
└────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────┐
│                      API GATEWAY                           │
├────────────────────────────────────────────────────────────┤
│  Stateless API servers (3-10 instances)                   │
│  ├── Routes delegate to OrchestrationClient               │
│  └── No direct ExecutionEngine interaction                │
└────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────┐
│                  ORCHESTRATION LAYER                       │
├────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────┐                  │
│  │   WorkflowCoordinator Service       │                  │
│  │   - Workflow state management        │                  │
│  │   - Dependency resolution            │                  │
│  │   - Task readiness detection        │                  │
│  └─────────────────────────────────────┘                  │
│  ┌─────────────────────────────────────┐                  │
│  │   TaskScheduler Service             │                  │
│  │   - Task queuing                    │                  │
│  │   - Provider assignment             │                  │
│  │   - Retry orchestration             │                  │
│  └─────────────────────────────────────┘                  │
└────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────┐
│                    PROVIDER LAYER                          │
├────────────────────────────────────────────────────────────┤
│  Independent providers pull tasks from queues              │
│  ├── PythonProvider                                       │
│  ├── ShellProvider                                        │
│  ├── HTTPProvider                                         │
│  └── LLMProvider (via hubs)                               │
└────────────────────────────────────────────────────────────┘
```

---

## 1. Client Restructuring

### Current Structure (Keep Most)
```python
# Current - KEEP
ModularGleitzeitClient
├── WorkflowMixin       # Keep as-is
├── TaskMixin           # Keep as-is
├── MonitoringMixin     # Keep as-is
├── BatchProcessingMixin # Keep as-is
└── ... other mixins    # Keep as-is
```

### Replace NativeAdapter with OrchestrationAdapter

```python
# NEW: OrchestrationAdapter (replaces NativeAdapter)
class OrchestrationAdapter(BaseAdapter):
    """Adapter for orchestration-only operations"""
    
    def __init__(
        self,
        orchestration_endpoints: List[str],
        persistence_config: Dict[str, Any]
    ):
        # Connect to orchestration services, not ExecutionEngine
        self.workflow_client = WorkflowCoordinatorClient(
            endpoints=orchestration_endpoints
        )
        self.task_client = TaskSchedulerClient(
            endpoints=orchestration_endpoints
        )
        self.persistence = PersistenceFactory.create(persistence_config)
        
        # No ExecutionEngine instantiation!
        # No direct provider management!
    
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit to orchestration layer"""
        # Store workflow in persistence
        workflow_id = await self.persistence.store_workflow(workflow)
        
        # Notify WorkflowCoordinator
        await self.workflow_client.start_orchestration(workflow_id)
        
        return workflow_id
    
    async def submit_task(self, task: Task) -> str:
        """Submit to task scheduler"""
        # Store task
        task_id = await self.persistence.store_task(task)
        
        # Schedule for execution
        await self.task_client.schedule_task(task_id)
        
        return task_id
    
    async def get_workflow_status(self, workflow_id: str) -> WorkflowStatus:
        """Get status from orchestration layer"""
        return await self.workflow_client.get_status(workflow_id)
```

### Client Mode Selection

```python
class ModularGleitzeitClient:
    def __init__(self, mode: str = "auto", **kwargs):
        if mode == "auto":
            mode = self._detect_best_mode()
        
        if mode == "api":
            self.adapter = APIAdapter(**kwargs)
        elif mode == "orchestration":
            # NEW: Direct orchestration connection
            self.adapter = OrchestrationAdapter(**kwargs)
        elif mode == "native":
            # DEPRECATED: Will be removed
            raise DeprecationWarning(
                "Native mode deprecated. Use 'orchestration' mode instead."
            )
```

---

## 2. Workflow Management Restructuring

### Extract WorkflowCoordinator Service

```python
# NEW: Standalone WorkflowCoordinator service
class WorkflowCoordinatorService:
    """Distributed workflow coordination service"""
    
    def __init__(
        self,
        coordinator_id: str,
        redis: Redis,
        persistence: PersistenceBackend
    ):
        self.coordinator_id = coordinator_id
        self.redis = redis
        self.persistence = persistence
        self.owned_workflows: Set[str] = set()
        
    async def run(self):
        """Main coordination loop"""
        # Subscribe to workflow events
        await self.subscribe_to_events([
            'WORKFLOW_SUBMITTED',
            'TASK_COMPLETED',
            'TASK_FAILED'
        ])
        
        while True:
            # Process owned workflows
            for workflow_id in self.owned_workflows:
                await self.coordinate_workflow(workflow_id)
            
            await asyncio.sleep(0.1)
    
    async def start_orchestration(self, workflow_id: str):
        """Start orchestrating a workflow"""
        # Try to claim ownership
        if await self.claim_workflow(workflow_id):
            self.owned_workflows.add(workflow_id)
            await self.initialize_workflow_state(workflow_id)
            await self.schedule_ready_tasks(workflow_id)
    
    async def coordinate_workflow(self, workflow_id: str):
        """Orchestrate workflow execution"""
        state = await self.get_workflow_state(workflow_id)
        
        # Check for newly ready tasks
        ready_tasks = await self.find_ready_tasks(workflow_id, state)
        
        for task_id in ready_tasks:
            await self.submit_task_for_scheduling(task_id)
        
        # Check completion
        if self.is_workflow_complete(state):
            await self.complete_workflow(workflow_id)
            self.owned_workflows.remove(workflow_id)
    
    async def find_ready_tasks(
        self,
        workflow_id: str,
        state: WorkflowState
    ) -> List[str]:
        """Find tasks with satisfied dependencies"""
        workflow = await self.persistence.get_workflow(workflow_id)
        ready = []
        
        for task in workflow.tasks:
            if state.task_states.get(task.id) == TaskStatus.PENDING:
                if await self.dependencies_satisfied(task, state):
                    ready.append(task.id)
        
        return ready
```

### Distributed Workflow State

```python
# NEW: Distributed workflow state management
class DistributedWorkflowState:
    """Workflow state in Redis"""
    
    def __init__(self, redis: Redis):
        self.redis = redis
    
    async def initialize(self, workflow_id: str, tasks: List[Task]):
        """Initialize workflow state"""
        state = {
            'workflow_id': workflow_id,
            'status': 'running',
            'tasks_total': len(tasks),
            'tasks_completed': 0,
            'tasks_failed': 0,
            'task_states': {
                task.id: TaskStatus.PENDING 
                for task in tasks
            }
        }
        
        await self.redis.hset(
            f"workflow:{workflow_id}:state",
            mapping={
                'data': json.dumps(state),
                'updated_at': time.time()
            }
        )
    
    async def update_task_status(
        self,
        workflow_id: str,
        task_id: str,
        status: TaskStatus
    ):
        """Update task status atomically"""
        # Use Lua script for atomic update
        lua_script = """
        local key = KEYS[1]
        local task_id = ARGV[1]
        local new_status = ARGV[2]
        
        local state = redis.call('hget', key, 'data')
        local data = cjson.decode(state)
        
        local old_status = data.task_states[task_id]
        data.task_states[task_id] = new_status
        
        if new_status == 'completed' and old_status ~= 'completed' then
            data.tasks_completed = data.tasks_completed + 1
        elseif new_status == 'failed' and old_status ~= 'failed' then
            data.tasks_failed = data.tasks_failed + 1
        end
        
        redis.call('hset', key, 'data', cjson.encode(data))
        redis.call('hset', key, 'updated_at', ARGV[3])
        
        return 1
        """
        
        await self.redis.eval(
            lua_script,
            1,
            f"workflow:{workflow_id}:state",
            task_id,
            status,
            time.time()
        )
```

---

## 3. API Structure Changes

### API Routes Update

```python
# UPDATED: API routes use OrchestrationClient
class APIRouteBase:
    def __init__(self):
        # Use orchestration client instead of native client
        self.client = OrchestrationClient(
            endpoints=os.getenv('ORCHESTRATION_ENDPOINTS', '').split(',')
        )
    
    async def handle_request(self, method: str, *args, **kwargs):
        """Delegate to orchestration layer"""
        return await getattr(self.client, method)(*args, **kwargs)
```

### API Gateway Configuration

```python
# NEW: API gateway with load balancing
class APIGateway:
    def __init__(self):
        self.app = FastAPI(title="Gleitzeit API Gateway")
        
        # No ExecutionEngine!
        # No providers!
        # Just routing to orchestration layer
        
        self.orchestration_client = OrchestrationClient(
            endpoints=self.discover_orchestration_endpoints()
        )
        
        # Include route modules
        self.app.include_router(workflow_router)
        self.app.include_router(task_router)
        self.app.include_router(monitoring_router)
    
    async def discover_orchestration_endpoints(self) -> List[str]:
        """Discover orchestration service endpoints"""
        # Could use Kubernetes DNS, Consul, or Redis
        return await ServiceDiscovery.find_services('orchestration')
```

---

## 4. Task Scheduling Service

### Extract from ExecutionEngine

```python
# NEW: TaskScheduler service (extracted from ExecutionEngine)
class TaskSchedulerService:
    """Lightweight task scheduling service"""
    
    def __init__(
        self,
        scheduler_id: str,
        redis: Redis,
        persistence: PersistenceBackend
    ):
        self.scheduler_id = scheduler_id
        self.redis = redis
        self.persistence = persistence
        self.provider_registry = ProviderRegistry(redis)
    
    async def schedule_task(self, task_id: str):
        """Schedule task for execution"""
        # Get task details
        task = await self.persistence.get_task(task_id)
        
        # Find capable provider
        provider = await self.provider_registry.find_provider(
            protocol=task.protocol,
            method=task.method
        )
        
        if not provider:
            await self.handle_no_provider(task_id)
            return
        
        # Create execution request
        request = TaskExecutionRequest(
            task_id=task_id,
            protocol=task.protocol,
            method=task.method,
            params=task.params,
            timeout=task.timeout,
            scheduled_at=time.time(),
            scheduler_id=self.scheduler_id
        )
        
        # Queue for provider (don't execute!)
        await self.redis.lpush(
            f"provider:{provider.id}:queue",
            request.to_json()
        )
        
        # Update task state
        await self.persistence.update_task_status(
            task_id,
            TaskStatus.SCHEDULED
        )
        
        # Emit event
        await self.emit_event(
            TaskScheduledEvent(
                task_id=task_id,
                provider_id=provider.id
            )
        )
```

---

## 5. Provider Communication Protocol

### Async Task Assignment

```python
# NEW: Provider pulls tasks asynchronously
class ProviderTaskPuller:
    """Provider-side task puller"""
    
    def __init__(
        self,
        provider_id: str,
        redis: Redis,
        executor: TaskExecutor
    ):
        self.provider_id = provider_id
        self.redis = redis
        self.executor = executor
        self.queue_key = f"provider:{provider_id}:queue"
    
    async def run(self):
        """Pull and execute tasks"""
        while True:
            # Pull task from queue
            task_json = await self.redis.brpop(
                self.queue_key,
                timeout=1
            )
            
            if task_json:
                request = TaskExecutionRequest.from_json(task_json[1])
                
                # Execute asynchronously
                asyncio.create_task(
                    self.execute_and_report(request)
                )
    
    async def execute_and_report(self, request: TaskExecutionRequest):
        """Execute task and report result"""
        try:
            # Execute with provider's resources
            result = await self.executor.execute(
                request.method,
                request.params
            )
            
            # Report success
            await self.report_completion(
                request.task_id,
                TaskStatus.COMPLETED,
                result
            )
            
        except Exception as e:
            # Report failure
            await self.report_completion(
                request.task_id,
                TaskStatus.FAILED,
                error=str(e)
            )
    
    async def report_completion(
        self,
        task_id: str,
        status: TaskStatus,
        result: Any = None,
        error: str = None
    ):
        """Report task completion to orchestration layer"""
        # Store result
        if result:
            await self.redis.hset(
                f"task:{task_id}:result",
                'data',
                json.dumps(result)
            )
        
        # Update status
        await self.redis.hset(
            f"task:{task_id}:status",
            mapping={
                'status': status,
                'completed_at': time.time(),
                'error': error or ''
            }
        )
        
        # Emit completion event
        await self.redis.publish(
            'task_events',
            json.dumps({
                'event': 'TASK_COMPLETED',
                'task_id': task_id,
                'status': status,
                'provider_id': self.provider_id
            })
        )
```

---

## 6. Deployment Structure

### Services to Deploy

```yaml
# docker-compose.yml for development
version: '3.8'

services:
  # Orchestration Layer (Scales)
  workflow-coordinator:
    image: gleitzeit:orchestration
    command: workflow-coordinator
    deploy:
      replicas: 3
    environment:
      REDIS_URL: redis://redis:6379
      COORDINATOR_ID: "{{.Task.Name}}"
  
  task-scheduler:
    image: gleitzeit:orchestration
    command: task-scheduler
    deploy:
      replicas: 3
    environment:
      REDIS_URL: redis://redis:6379
      SCHEDULER_ID: "{{.Task.Name}}"
  
  api-gateway:
    image: gleitzeit:api
    command: api-gateway
    deploy:
      replicas: 3
    ports:
      - "8000:8000"
    environment:
      ORCHESTRATION_ENDPOINTS: "workflow-coordinator:9090,task-scheduler:9091"
  
  # Provider Layer (Independent)
  python-provider:
    image: gleitzeit:python-provider
    command: python-provider
    deploy:
      replicas: 1  # Provider manages internal scaling
    environment:
      REDIS_URL: redis://redis:6379
      MAX_WORKERS: 10
  
  # Infrastructure
  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
```

---

## 7. Migration Path

### Phase 1: Create New Components (Week 1-2)
1. [ ] Implement WorkflowCoordinatorService
2. [ ] Implement TaskSchedulerService
3. [ ] Create OrchestrationAdapter
4. [ ] Implement provider task pulling

### Phase 2: Update Existing (Week 2-3)
1. [ ] Update client to use OrchestrationAdapter
2. [ ] Update API to use orchestration client
3. [ ] Convert providers to pull model
4. [ ] Update persistence for distributed state

### Phase 3: Remove Old Components (Week 3-4)
1. [ ] Deprecate NativeAdapter
2. [ ] Remove ExecutionEngine from API
3. [ ] Clean up direct provider calls
4. [ ] Remove local state management

### Phase 4: Testing & Optimization (Week 4-5)
1. [ ] Integration testing
2. [ ] Load testing
3. [ ] Performance optimization
4. [ ] Documentation

---

## 8. Benefits of This Structure

### Clean Separation
- **Orchestration:** Workflow coordination, task scheduling, state management
- **Execution:** Providers handle actual task execution independently
- **API:** Thin routing layer to orchestration services

### Independent Scaling
- Scale orchestration based on workflow/task count
- Providers scale based on execution needs
- API scales based on request rate

### Resource Efficiency
```yaml
# 1000 workflows/hour needs:
Orchestration: 2GB RAM, 1 CPU (total for all services)
API Gateway: 1GB RAM, 0.5 CPU
Providers: Variable based on workload (managed independently)
```

### Flexibility
- Providers can be anywhere (Lambda, K8s, VMs)
- Orchestration can run on minimal infrastructure
- Easy to add new provider types

---

## 9. Key Changes Summary

| Component | Current | New | Benefit |
|-----------|---------|-----|---------|
| **Client** | NativeAdapter with ExecutionEngine | OrchestrationAdapter | Clean separation |
| **API** | Shared ExecutionEngine | Orchestration client | Stateless, scalable |
| **Workflow** | Mixed with ExecutionEngine | Dedicated coordinator | Distributed coordination |
| **Tasks** | ExecutionEngine scheduling | Dedicated scheduler | Lightweight scheduling |
| **Providers** | Direct calls | Pull from queues | Independent scaling |
| **State** | Local + Redis | Fully distributed | Horizontal scaling |

---

## Conclusion

This restructuring maintains the clean architecture of Gleitzeit while enabling true orchestration-only scaling. The changes are incremental and can be implemented alongside the existing system, allowing for gradual migration and testing.

The key insight is that **orchestration is lightweight** - it's just state tracking and decision making. The heavy lifting (execution) is delegated to providers that manage their own resources independently.

---

**Document Status:** Complete  
**Implementation Effort:** 4-5 weeks  
**Risk Level:** Medium (can be done incrementally)  
**Recommendation:** Start with Phase 1 components in parallel with existing system