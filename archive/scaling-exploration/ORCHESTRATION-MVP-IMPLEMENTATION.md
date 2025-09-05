# Orchestration MVP Implementation Plan

## Overview
Start with a minimal viable orchestration system with one instance of each component, then scale up once proven to work.

## MVP Architecture (Phase 1)

```
┌──────────────────────────────────────────────────┐
│                 MVP Architecture                  │
│                                                   │
│  ┌─────────────────────────────────────────┐     │
│  │         Single Node Setup                │     │
│  │                                          │     │
│  │  ┌──────────────────────────────┐       │     │
│  │  │  WorkflowCoordinator (1)      │       │     │
│  │  │  - No leader election needed  │       │     │
│  │  │  - Direct task scheduling     │       │     │
│  │  └──────────────────────────────┘       │     │
│  │              ↓                           │     │
│  │  ┌──────────────────────────────┐       │     │
│  │  │  TaskScheduler (embedded)     │       │     │
│  │  │  - Simple provider selection  │       │     │
│  │  │  - Direct task assignment     │       │     │
│  │  └──────────────────────────────┘       │     │
│  │              ↓                           │     │
│  │  ┌──────────────────────────────┐       │     │
│  │  │  Provider Pull Queue          │       │     │
│  │  │  - Redis-backed queue         │       │     │
│  │  │  - Providers pull tasks       │       │     │
│  │  └──────────────────────────────┘       │     │
│  └─────────────────────────────────────────┘     │
│                                                   │
└──────────────────────────────────────────────────┘
```

## Implementation Steps

### Step 1: Create Minimal WorkflowCoordinator (Week 1)

```python
# src/gleitzeit/orchestration/coordinator_mvp.py
import asyncio
import logging
from typing import Dict, Optional, List
from datetime import datetime
import json

from gleitzeit.core.models import Workflow, Task, WorkflowStatus, TaskStatus
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.core.event_bus import EventBus

logger = logging.getLogger(__name__)

class WorkflowCoordinatorMVP:
    """
    Minimal Workflow Coordinator - single instance version
    No leader election, direct coordination
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        event_bus: EventBus,
        node_id: str = "coordinator-mvp"
    ):
        self.persistence = persistence
        self.event_bus = event_bus
        self.node_id = node_id
        
        # In-memory tracking (will move to Redis later)
        self.active_workflows: Dict[str, Workflow] = {}
        self.workflow_states: Dict[str, Dict] = {}
        
        # Simple task scheduler (embedded for MVP)
        self.task_scheduler = TaskSchedulerMVP(persistence, event_bus)
        
        # Subscribe to events
        self._setup_event_handlers()
        
    def _setup_event_handlers(self):
        """Setup event subscriptions"""
        self.event_bus.subscribe("task:completed", self._handle_task_completed)
        self.event_bus.subscribe("task:failed", self._handle_task_failed)
        
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit workflow for execution"""
        logger.info(f"Submitting workflow {workflow.id}")
        
        # Store workflow
        self.active_workflows[workflow.id] = workflow
        
        # Initialize state
        self.workflow_states[workflow.id] = {
            "status": WorkflowStatus.PENDING,
            "total_tasks": len(workflow.tasks),
            "completed_tasks": set(),
            "failed_tasks": set(),
            "task_states": {t.id: TaskStatus.PENDING for t in workflow.tasks}
        }
        
        # Start coordination
        asyncio.create_task(self._coordinate_workflow(workflow.id))
        
        # Emit event
        await self.event_bus.publish(
            "workflow:submitted",
            {"workflow_id": workflow.id, "timestamp": datetime.utcnow().isoformat()}
        )
        
        return workflow.id
    
    async def _coordinate_workflow(self, workflow_id: str):
        """Coordinate workflow execution"""
        workflow = self.active_workflows.get(workflow_id)
        if not workflow:
            logger.error(f"Workflow {workflow_id} not found")
            return
            
        state = self.workflow_states[workflow_id]
        state["status"] = WorkflowStatus.RUNNING
        
        logger.info(f"Starting coordination for workflow {workflow_id}")
        
        # Find and schedule ready tasks
        await self._schedule_ready_tasks(workflow_id)
        
    async def _schedule_ready_tasks(self, workflow_id: str):
        """Schedule tasks with no pending dependencies"""
        workflow = self.active_workflows[workflow_id]
        state = self.workflow_states[workflow_id]
        
        for task in workflow.tasks:
            if state["task_states"][task.id] != TaskStatus.PENDING:
                continue
                
            # Check dependencies
            deps_met = all(
                state["task_states"].get(dep_id) == TaskStatus.COMPLETED
                for dep_id in task.dependencies
            )
            
            if deps_met:
                # Schedule task
                logger.info(f"Scheduling task {task.id}")
                state["task_states"][task.id] = TaskStatus.QUEUED
                
                await self.task_scheduler.schedule_task(task, workflow_id)
                
                await self.event_bus.publish(
                    "task:scheduled",
                    {
                        "task_id": task.id,
                        "workflow_id": workflow_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
    
    async def _handle_task_completed(self, event_type: str, data: dict):
        """Handle task completion"""
        task_id = data.get("task_id")
        workflow_id = data.get("workflow_id")
        
        if not workflow_id or workflow_id not in self.workflow_states:
            return
            
        logger.info(f"Task {task_id} completed for workflow {workflow_id}")
        
        state = self.workflow_states[workflow_id]
        state["task_states"][task_id] = TaskStatus.COMPLETED
        state["completed_tasks"].add(task_id)
        
        # Check for newly ready tasks
        await self._schedule_ready_tasks(workflow_id)
        
        # Check if workflow is complete
        if len(state["completed_tasks"]) == state["total_tasks"]:
            await self._complete_workflow(workflow_id)
    
    async def _handle_task_failed(self, event_type: str, data: dict):
        """Handle task failure"""
        task_id = data.get("task_id")
        workflow_id = data.get("workflow_id")
        
        if not workflow_id or workflow_id not in self.workflow_states:
            return
            
        logger.error(f"Task {task_id} failed for workflow {workflow_id}")
        
        state = self.workflow_states[workflow_id]
        state["task_states"][task_id] = TaskStatus.FAILED
        state["failed_tasks"].add(task_id)
        
        # For MVP, fail the workflow on any task failure
        await self._fail_workflow(workflow_id, f"Task {task_id} failed")
    
    async def _complete_workflow(self, workflow_id: str):
        """Mark workflow as completed"""
        logger.info(f"Workflow {workflow_id} completed")
        
        state = self.workflow_states[workflow_id]
        state["status"] = WorkflowStatus.COMPLETED
        
        await self.event_bus.publish(
            "workflow:completed",
            {
                "workflow_id": workflow_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        # Cleanup
        del self.active_workflows[workflow_id]
    
    async def _fail_workflow(self, workflow_id: str, reason: str):
        """Mark workflow as failed"""
        logger.error(f"Workflow {workflow_id} failed: {reason}")
        
        state = self.workflow_states[workflow_id]
        state["status"] = WorkflowStatus.FAILED
        state["failure_reason"] = reason
        
        await self.event_bus.publish(
            "workflow:failed",
            {
                "workflow_id": workflow_id,
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        # Cleanup
        del self.active_workflows[workflow_id]


class TaskSchedulerMVP:
    """
    Minimal Task Scheduler - embedded in coordinator for MVP
    """
    
    def __init__(self, persistence: PersistenceBackend, event_bus: EventBus):
        self.persistence = persistence
        self.event_bus = event_bus
        
    async def schedule_task(self, task: Task, workflow_id: str):
        """Schedule task for execution"""
        # For MVP, just put in Redis queue for providers to pull
        task_data = {
            "task_id": task.id,
            "workflow_id": workflow_id,
            "protocol": task.protocol,
            "method": task.method,
            "params": task.params,
            "metadata": task.metadata,
            "queued_at": datetime.utcnow().isoformat()
        }
        
        # Add to provider queue (Redis list)
        queue_key = f"provider:queue:{task.protocol}"
        await self.persistence.redis.lpush(queue_key, json.dumps(task_data))
        
        logger.info(f"Task {task.id} queued for protocol {task.protocol}")
```

### Step 2: Create Provider Pull Interface (Week 1)

```python
# src/gleitzeit/orchestration/provider_pull.py
import asyncio
import json
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from gleitzeit.providers.base import Provider
from gleitzeit.core.event_bus import EventBus

logger = logging.getLogger(__name__)

class ProviderPullAdapter:
    """
    Adapter for providers to pull tasks from queue
    Replaces push-based task execution
    """
    
    def __init__(
        self,
        provider: Provider,
        event_bus: EventBus,
        redis_client,
        poll_interval: float = 1.0
    ):
        self.provider = provider
        self.event_bus = event_bus
        self.redis = redis_client
        self.poll_interval = poll_interval
        self.running = False
        self.protocol = provider.protocol_name
        
    async def start(self):
        """Start pulling tasks"""
        self.running = True
        logger.info(f"Starting pull adapter for {self.protocol}")
        
        while self.running:
            try:
                # Pull task from queue
                task_data = await self._pull_task()
                
                if task_data:
                    # Execute task
                    await self._execute_task(task_data)
                else:
                    # No tasks, wait before polling again
                    await asyncio.sleep(self.poll_interval)
                    
            except Exception as e:
                logger.error(f"Error in pull adapter: {e}")
                await asyncio.sleep(self.poll_interval)
    
    async def stop(self):
        """Stop pulling tasks"""
        self.running = False
        logger.info(f"Stopped pull adapter for {self.protocol}")
    
    async def _pull_task(self) -> Optional[Dict[str, Any]]:
        """Pull next task from queue"""
        queue_key = f"provider:queue:{self.protocol}"
        
        # Blocking pop with timeout
        result = await self.redis.brpop(queue_key, timeout=1)
        
        if result:
            _, task_json = result
            return json.loads(task_json)
        return None
    
    async def _execute_task(self, task_data: Dict[str, Any]):
        """Execute pulled task"""
        task_id = task_data["task_id"]
        workflow_id = task_data["workflow_id"]
        
        logger.info(f"Executing task {task_id} from workflow {workflow_id}")
        
        # Emit task started event
        await self.event_bus.publish(
            "task:started",
            {
                "task_id": task_id,
                "workflow_id": workflow_id,
                "provider": self.protocol,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        try:
            # Execute via provider
            result = await self.provider.execute(
                method=task_data["method"],
                params=task_data["params"]
            )
            
            # Emit success event
            await self.event_bus.publish(
                "task:completed",
                {
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "result": result,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
            logger.info(f"Task {task_id} completed successfully")
            
        except Exception as e:
            # Emit failure event
            await self.event_bus.publish(
                "task:failed",
                {
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
            logger.error(f"Task {task_id} failed: {e}")
```

### Step 3: Integration with Existing Client (Week 1)

```python
# src/gleitzeit/client/orchestration_adapter.py
from typing import Optional
from gleitzeit.client.native_adapter import NativeAdapter
from gleitzeit.orchestration.coordinator_mvp import WorkflowCoordinatorMVP

class OrchestrationAdapter(NativeAdapter):
    """
    Adapter that uses orchestration instead of direct execution
    Minimal changes to existing client interface
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Initialize coordinator (single instance for MVP)
        self.coordinator = WorkflowCoordinatorMVP(
            persistence=self.persistence,
            event_bus=self.event_bus
        )
        
        # Start provider pull adapters
        self._start_provider_adapters()
        
    def _start_provider_adapters(self):
        """Start pull adapters for each provider"""
        for protocol, provider in self.providers.items():
            adapter = ProviderPullAdapter(
                provider=provider,
                event_bus=self.event_bus,
                redis_client=self.persistence.redis
            )
            asyncio.create_task(adapter.start())
    
    async def execute_workflow(self, workflow: Workflow) -> WorkflowExecution:
        """Override to use coordinator"""
        # Submit to coordinator instead of execution engine
        workflow_id = await self.coordinator.submit_workflow(workflow)
        
        # Create execution object for compatibility
        execution = WorkflowExecution(
            workflow_id=workflow_id,
            status=WorkflowStatus.RUNNING
        )
        
        return execution
```

### Step 4: Simple Test Harness (Week 1)

```python
# tests/test_orchestration_mvp.py
import pytest
import asyncio
from gleitzeit.core.models import Task, Workflow
from gleitzeit.orchestration.coordinator_mvp import WorkflowCoordinatorMVP
from gleitzeit.persistence.redis_backend import RedisBackend
from gleitzeit.core.event_bus import EventBus

@pytest.fixture
async def coordinator():
    """Create test coordinator"""
    persistence = RedisBackend()
    await persistence.initialize()
    
    event_bus = EventBus()
    coordinator = WorkflowCoordinatorMVP(persistence, event_bus)
    
    yield coordinator
    
    await persistence.cleanup()

@pytest.mark.asyncio
async def test_simple_workflow(coordinator):
    """Test simple workflow execution"""
    # Create workflow with 3 sequential tasks
    task1 = Task(
        id="task-1",
        name="First Task",
        protocol="python",
        method="print",
        params={"message": "Task 1"}
    )
    
    task2 = Task(
        id="task-2", 
        name="Second Task",
        protocol="python",
        method="print",
        params={"message": "Task 2"},
        dependencies=["task-1"]
    )
    
    task3 = Task(
        id="task-3",
        name="Third Task", 
        protocol="python",
        method="print",
        params={"message": "Task 3"},
        dependencies=["task-2"]
    )
    
    workflow = Workflow(
        id="test-workflow-1",
        name="Test Workflow",
        tasks=[task1, task2, task3]
    )
    
    # Submit workflow
    workflow_id = await coordinator.submit_workflow(workflow)
    
    # Wait for completion (simplified for testing)
    await asyncio.sleep(5)
    
    # Check state
    state = coordinator.workflow_states[workflow_id]
    assert state["status"] == WorkflowStatus.COMPLETED
    assert len(state["completed_tasks"]) == 3

@pytest.mark.asyncio
async def test_parallel_tasks(coordinator):
    """Test workflow with parallel tasks"""
    # Create workflow with parallel tasks
    task1 = Task(id="task-1", name="Task 1", protocol="python", method="print")
    task2 = Task(id="task-2", name="Task 2", protocol="python", method="print")
    task3 = Task(
        id="task-3",
        name="Task 3",
        protocol="python",
        method="print",
        dependencies=["task-1", "task-2"]
    )
    
    workflow = Workflow(
        id="test-workflow-2",
        name="Parallel Test",
        tasks=[task1, task2, task3]
    )
    
    workflow_id = await coordinator.submit_workflow(workflow)
    
    # Check that task1 and task2 are scheduled in parallel
    await asyncio.sleep(1)
    
    state = coordinator.workflow_states[workflow_id]
    assert state["task_states"]["task-1"] == TaskStatus.QUEUED
    assert state["task_states"]["task-2"] == TaskStatus.QUEUED
    assert state["task_states"]["task-3"] == TaskStatus.PENDING
```

### Step 5: MVP Configuration (Week 1)

```python
# src/gleitzeit/orchestration/config_mvp.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class OrchestrationConfigMVP:
    """MVP Orchestration Configuration"""
    
    # Redis configuration
    redis_url: str = "redis://localhost:6379"
    redis_db: int = 0
    
    # Coordinator settings
    coordinator_enabled: bool = True
    coordinator_node_id: str = "coordinator-mvp"
    
    # Provider settings
    provider_poll_interval: float = 1.0
    provider_queue_timeout: int = 5
    
    # Event bus settings
    event_bus_enabled: bool = True
    event_buffer_size: int = 1000
    
    # Debug settings
    debug_mode: bool = False
    sync_execution: bool = False
    
    @classmethod
    def from_env(cls) -> "OrchestrationConfigMVP":
        """Load from environment variables"""
        import os
        
        return cls(
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
            coordinator_enabled=os.getenv("COORDINATOR_ENABLED", "true").lower() == "true",
            debug_mode=os.getenv("DEBUG_MODE", "false").lower() == "true"
        )
```

## Testing Strategy

### Phase 1: Unit Tests (Days 1-2)
```python
# Test individual components
- Test WorkflowCoordinatorMVP coordination logic
- Test TaskSchedulerMVP scheduling
- Test ProviderPullAdapter pulling mechanism
- Test event flow
```

### Phase 2: Integration Tests (Days 3-4)
```python
# Test component interactions
- Test workflow submission and execution
- Test task dependencies
- Test event propagation
- Test error handling
```

### Phase 3: System Tests (Days 5-7)
```python
# Test complete workflows
- Test sequential workflows
- Test parallel workflows
- Test workflows with failures
- Test retry logic (when added)
```

## Migration Path

### Week 1: MVP Implementation
1. **Day 1-2**: Implement WorkflowCoordinatorMVP
2. **Day 3**: Implement ProviderPullAdapter
3. **Day 4**: Integrate with existing client
4. **Day 5-7**: Testing and debugging

### Week 2: Add Persistence
1. Move workflow state to Redis
2. Add state recovery on restart
3. Implement proper cleanup

### Week 3: Add Resilience
1. Add retry manager (embedded)
2. Add error recovery
3. Add timeout handling

### Week 4: Scale Components
1. Add second coordinator instance
2. Implement leader election
3. Add multiple provider instances
4. Test distributed execution

## Running the MVP

### Docker Compose for MVP
```yaml
# docker-compose.mvp.yml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data

  gleitzeit-mvp:
    build:
      context: .
      dockerfile: Dockerfile.mvp
    environment:
      - REDIS_URL=redis://redis:6379
      - COORDINATOR_ENABLED=true
      - DEBUG_MODE=true
      - LOG_LEVEL=DEBUG
    depends_on:
      - redis
    volumes:
      - ./src:/app/src
      - ./tests:/app/tests

volumes:
  redis-data:
```

### Dockerfile for MVP
```dockerfile
# Dockerfile.mvp
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy source
COPY src/ ./src/
COPY tests/ ./tests/

# Run MVP
CMD ["python", "-m", "gleitzeit.orchestration.run_mvp"]
```

### Running Script
```python
# src/gleitzeit/orchestration/run_mvp.py
import asyncio
import logging
from gleitzeit.orchestration.config_mvp import OrchestrationConfigMVP
from gleitzeit.orchestration.coordinator_mvp import WorkflowCoordinatorMVP
from gleitzeit.persistence.redis_backend import RedisBackend
from gleitzeit.core.event_bus import EventBus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_mvp():
    """Run MVP orchestration system"""
    # Load config
    config = OrchestrationConfigMVP.from_env()
    
    # Initialize components
    persistence = RedisBackend(url=config.redis_url)
    await persistence.initialize()
    
    event_bus = EventBus()
    
    # Create coordinator
    coordinator = WorkflowCoordinatorMVP(
        persistence=persistence,
        event_bus=event_bus,
        node_id=config.coordinator_node_id
    )
    
    logger.info("MVP Orchestration System Started")
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")

if __name__ == "__main__":
    asyncio.run(run_mvp())
```

## Success Metrics

### MVP Goals
1. ✅ Successfully execute simple sequential workflow
2. ✅ Successfully execute parallel tasks
3. ✅ Providers pull tasks from queue
4. ✅ Events flow correctly between components
5. ✅ Workflow completes or fails properly

### Performance Targets (MVP)
- Workflow submission: < 100ms
- Task scheduling: < 50ms
- Event propagation: < 10ms
- End-to-end simple workflow: < 5s

## Next Steps After MVP

Once MVP is working:

1. **Add Distributed State** (Week 2)
   - Move state to Redis
   - Add state recovery
   - Implement snapshots

2. **Add Resilience** (Week 3)
   - Retry logic
   - Error recovery
   - Timeout handling

3. **Scale Horizontally** (Week 4)
   - Multiple coordinators
   - Leader election
   - Load balancing

4. **Production Features** (Week 5+)
   - Monitoring/metrics
   - OpenTelemetry
   - Admin UI
   - Performance optimization

## Summary

This MVP approach provides:
1. **Working system in 1 week**
2. **Testable architecture**
3. **Clear migration path**
4. **Minimal changes to existing code**
5. **Foundation for scaling**

The key is starting simple with single instances, proving the architecture works, then gradually adding distribution and resilience features.