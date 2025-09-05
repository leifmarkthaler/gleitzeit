# Workflow Management Structure for Orchestration Scaling

## Overview
This document defines the structure for workflow management in the orchestration-only scaling architecture, building on the component structure defined in COMPONENT-STRUCTURE-FOR-SCALING.md.

## Current State Analysis

### Existing Components
1. **WorkflowManager** (677 lines)
   - Template management
   - Workflow execution
   - Event-driven scheduling
   - Lifecycle management
   - Direct ExecutionEngine coupling

2. **TaskQueue** (Persistence-backed)
   - Priority-based ordering
   - Dependency checking
   - Already uses persistence backend

3. **ExecutionEngine** (1,707 lines)
   - Monolithic execution control
   - Direct provider instantiation
   - In-memory task tracking

## Proposed Workflow Management Structure

### 1. Core Workflow Services

#### WorkflowCoordinatorService
```python
# src/gleitzeit/orchestration/workflow_coordinator.py
class WorkflowCoordinatorService:
    """
    Distributed workflow coordination service
    Manages workflow lifecycle across cluster
    """
    
    def __init__(
        self,
        redis_client: Redis,
        node_id: str,
        event_bus: EventBus
    ):
        self.redis = redis_client
        self.node_id = node_id
        self.event_bus = event_bus
        self.is_leader = False
        
        # Workflow state tracking
        self.workflow_states = {}  # workflow_id -> state
        self.workflow_locks = {}   # workflow_id -> lock
        
    async def coordinate_workflow(self, workflow: Workflow):
        """Coordinate workflow execution across nodes"""
        # 1. Register workflow in Redis
        await self._register_workflow(workflow)
        
        # 2. Publish workflow event
        await self.event_bus.publish(
            "workflow:submitted",
            {"workflow_id": workflow.id, "node_id": self.node_id}
        )
        
        # 3. Start coordination if leader
        if self.is_leader:
            await self._coordinate_execution(workflow)
    
    async def _coordinate_execution(self, workflow: Workflow):
        """Leader coordinates workflow execution"""
        # Analyze dependencies
        execution_plan = await self._create_execution_plan(workflow)
        
        # Distribute tasks to schedulers
        for batch in execution_plan.batches:
            await self._distribute_task_batch(batch)
```

#### TaskSchedulerService
```python
# src/gleitzeit/orchestration/task_scheduler.py
class TaskSchedulerService:
    """
    Distributed task scheduling service
    Manages task assignment and provider routing
    """
    
    def __init__(
        self,
        redis_client: Redis,
        node_id: str,
        provider_registry: ProviderRegistry
    ):
        self.redis = redis_client
        self.node_id = node_id
        self.provider_registry = provider_registry
        
        # Task assignment tracking
        self.assigned_tasks = {}  # task_id -> provider_id
        self.task_queues = {}     # provider_id -> task_queue
        
    async def schedule_task(self, task: Task) -> str:
        """Schedule task to appropriate provider"""
        # 1. Find available provider
        provider = await self._find_provider(task)
        
        # 2. Create task assignment
        assignment = TaskAssignment(
            task_id=task.id,
            provider_id=provider.id,
            node_id=self.node_id,
            assigned_at=datetime.utcnow()
        )
        
        # 3. Store in Redis
        await self._store_assignment(assignment)
        
        # 4. Queue for provider
        await self._queue_for_provider(task, provider)
        
        return assignment.id
```

### 2. Workflow State Management

#### Distributed State Store
```python
# src/gleitzeit/orchestration/state_store.py
class WorkflowStateStore:
    """
    Redis-backed workflow state management
    """
    
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.state_prefix = "workflow:state:"
        self.lock_prefix = "workflow:lock:"
        
    async def get_workflow_state(self, workflow_id: str) -> WorkflowState:
        """Get workflow state from Redis"""
        key = f"{self.state_prefix}{workflow_id}"
        data = await self.redis.get(key)
        if data:
            return WorkflowState.from_json(data)
        return None
    
    async def update_workflow_state(
        self, 
        workflow_id: str, 
        state: WorkflowState,
        ttl: int = 3600
    ):
        """Update workflow state with TTL"""
        key = f"{self.state_prefix}{workflow_id}"
        await self.redis.setex(
            key, 
            ttl, 
            state.to_json()
        )
    
    async def acquire_workflow_lock(
        self, 
        workflow_id: str,
        node_id: str,
        ttl: int = 30
    ) -> bool:
        """Acquire distributed lock for workflow"""
        key = f"{self.lock_prefix}{workflow_id}"
        return await self.redis.set(
            key, 
            node_id, 
            nx=True, 
            ex=ttl
        )
```

### 3. Workflow Execution Plans

#### ExecutionPlanBuilder
```python
# src/gleitzeit/orchestration/execution_plan.py
@dataclass
class ExecutionBatch:
    """Tasks that can execute in parallel"""
    batch_number: int
    tasks: List[Task]
    dependencies_met: Set[str]

@dataclass
class ExecutionPlan:
    """Complete execution plan for workflow"""
    workflow_id: str
    batches: List[ExecutionBatch]
    dependency_graph: Dict[str, Set[str]]
    estimated_duration: timedelta

class ExecutionPlanBuilder:
    """
    Builds execution plans from workflows
    """
    
    def build_plan(self, workflow: Workflow) -> ExecutionPlan:
        """Build execution plan with parallelization"""
        # 1. Build dependency graph
        graph = self._build_dependency_graph(workflow)
        
        # 2. Topological sort with batching
        batches = self._create_batches(graph, workflow.tasks)
        
        # 3. Estimate duration
        duration = self._estimate_duration(batches)
        
        return ExecutionPlan(
            workflow_id=workflow.id,
            batches=batches,
            dependency_graph=graph,
            estimated_duration=duration
        )
    
    def _create_batches(
        self, 
        graph: Dict[str, Set[str]], 
        tasks: List[Task]
    ) -> List[ExecutionBatch]:
        """Create parallel execution batches"""
        batches = []
        completed = set()
        remaining = {t.id: t for t in tasks}
        
        batch_num = 0
        while remaining:
            # Find tasks with met dependencies
            ready = []
            for task_id, task in remaining.items():
                deps = graph.get(task_id, set())
                if deps.issubset(completed):
                    ready.append(task)
            
            if not ready:
                raise ValueError("Circular dependency detected")
            
            # Create batch
            batch = ExecutionBatch(
                batch_number=batch_num,
                tasks=ready,
                dependencies_met=completed.copy()
            )
            batches.append(batch)
            
            # Update state
            for task in ready:
                completed.add(task.id)
                del remaining[task.id]
            
            batch_num += 1
        
        return batches
```

### 4. Workflow Templates

#### TemplateRegistry
```python
# src/gleitzeit/orchestration/template_registry.py
class TemplateRegistry:
    """
    Distributed template registry
    """
    
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.template_prefix = "template:"
        self.template_cache = {}
        
    async def register_template(
        self, 
        template: WorkflowTemplate
    ) -> str:
        """Register template in Redis"""
        key = f"{self.template_prefix}{template.id}"
        
        # Store template
        await self.redis.set(
            key,
            json.dumps(template.to_dict())
        )
        
        # Update index
        await self.redis.sadd(
            "template:index",
            template.id
        )
        
        # Cache locally
        self.template_cache[template.id] = template
        
        return template.id
    
    async def get_template(
        self, 
        template_id: str
    ) -> Optional[WorkflowTemplate]:
        """Get template by ID"""
        # Check cache
        if template_id in self.template_cache:
            return self.template_cache[template_id]
        
        # Load from Redis
        key = f"{self.template_prefix}{template_id}"
        data = await self.redis.get(key)
        
        if data:
            template = WorkflowTemplate.from_dict(
                json.loads(data)
            )
            self.template_cache[template_id] = template
            return template
        
        return None
```

### 5. Workflow Event Handlers

#### WorkflowEventProcessor
```python
# src/gleitzeit/orchestration/workflow_events.py
class WorkflowEventProcessor:
    """
    Processes workflow-related events
    """
    
    def __init__(
        self,
        event_bus: EventBus,
        state_store: WorkflowStateStore,
        coordinator: WorkflowCoordinatorService
    ):
        self.event_bus = event_bus
        self.state_store = state_store
        self.coordinator = coordinator
        
        # Register handlers
        self._register_handlers()
    
    def _register_handlers(self):
        """Register event handlers"""
        handlers = {
            "task:completed": self._handle_task_completed,
            "task:failed": self._handle_task_failed,
            "workflow:submitted": self._handle_workflow_submitted,
            "workflow:cancelled": self._handle_workflow_cancelled
        }
        
        for event_type, handler in handlers.items():
            self.event_bus.subscribe(event_type, handler)
    
    async def _handle_task_completed(self, event: Event):
        """Handle task completion"""
        workflow_id = event.data.get("workflow_id")
        task_id = event.data.get("task_id")
        
        if not workflow_id:
            return
        
        # Update workflow state
        state = await self.state_store.get_workflow_state(workflow_id)
        if state:
            state.completed_tasks.add(task_id)
            state.task_results[task_id] = event.data.get("result")
            
            # Check if workflow complete
            if self._is_workflow_complete(state):
                state.status = WorkflowStatus.COMPLETED
                await self._complete_workflow(workflow_id, state)
            else:
                # Schedule next tasks
                await self._schedule_ready_tasks(workflow_id, state)
            
            await self.state_store.update_workflow_state(
                workflow_id, 
                state
            )
```

### 6. Integration with Existing Components

#### Migration Path

**Phase 1: Extract Workflow Coordination (Week 1)**
```python
# Extract from ExecutionEngine
- Workflow submission logic -> WorkflowCoordinatorService
- Workflow state tracking -> WorkflowStateStore
- Event handlers -> WorkflowEventProcessor

# Keep in ExecutionEngine (temporarily)
- Task execution logic
- Provider management
```

**Phase 2: Extract Task Scheduling (Week 2)**
```python
# Extract from ExecutionEngine
- Task scheduling logic -> TaskSchedulerService
- Provider selection -> TaskSchedulerService
- Task assignment -> Redis-backed assignments

# Create provider pull interface
- Providers pull tasks from Redis queues
- No direct task push from scheduler
```

**Phase 3: Refactor WorkflowManager (Week 3)**
```python
# Refactor WorkflowManager to use new services
class WorkflowManager:
    def __init__(
        self,
        coordinator: WorkflowCoordinatorService,
        scheduler: TaskSchedulerService,
        template_registry: TemplateRegistry
    ):
        self.coordinator = coordinator
        self.scheduler = scheduler
        self.templates = template_registry
    
    async def execute_workflow(self, workflow: Workflow):
        """Delegate to coordinator"""
        return await self.coordinator.coordinate_workflow(workflow)
```

**Phase 4: Add Horizontal Scaling (Week 4)**
```python
# Add leader election
- Implement leader election for WorkflowCoordinator
- Add node health checking
- Implement failover handling

# Add load balancing
- Distribute workflows across coordinators
- Balance task scheduling across nodes
```

## Configuration

### Redis Keys Structure
```
workflow:state:{workflow_id}     # Workflow state
workflow:lock:{workflow_id}      # Workflow coordination lock
task:assignment:{task_id}        # Task assignment
task:queue:{provider_id}         # Provider task queue
template:{template_id}           # Workflow template
template:index                   # Template ID set
node:health:{node_id}           # Node health status
coordinator:leader              # Current coordinator leader
```

### Environment Variables
```bash
# Orchestration configuration
ORCHESTRATION_NODE_ID=node-1
ORCHESTRATION_COORDINATOR_ENABLED=true
ORCHESTRATION_SCHEDULER_ENABLED=true
ORCHESTRATION_LEADER_ELECTION_TTL=30
ORCHESTRATION_STATE_TTL=3600

# Redis configuration
REDIS_URL=redis://localhost:6379
REDIS_KEY_PREFIX=gleitzeit:
REDIS_POOL_SIZE=50
```

## Benefits

1. **Distributed Coordination**
   - Multiple coordinator nodes
   - Leader election for consistency
   - Automatic failover

2. **Scalable Task Scheduling**
   - Distributed schedulers
   - Provider-based load balancing
   - Pull model for providers

3. **Resilient State Management**
   - Redis-backed state
   - TTL-based cleanup
   - Distributed locks

4. **Clean Separation**
   - Orchestration vs execution
   - Coordinator vs scheduler
   - Templates vs instances

5. **Observable System**
   - Event-driven updates
   - Centralized state store
   - Clear execution plans

## Next Steps

1. **Implement WorkflowCoordinatorService**
   - Basic coordination logic
   - Leader election
   - State management

2. **Implement TaskSchedulerService**
   - Task assignment logic
   - Provider routing
   - Queue management

3. **Create ExecutionPlanBuilder**
   - Dependency analysis
   - Batch creation
   - Duration estimation

4. **Refactor WorkflowManager**
   - Use new services
   - Remove direct engine coupling
   - Maintain backward compatibility

5. **Add Monitoring**
   - Workflow metrics
   - Task distribution metrics
   - Node health metrics