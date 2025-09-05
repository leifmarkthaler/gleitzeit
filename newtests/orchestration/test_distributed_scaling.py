"""
Test distributed scaling with multiple scheduler instances
"""

import asyncio
import json
from datetime import datetime
from collections import deque, defaultdict
import hashlib

from gleitzeit.core.models import Task, Workflow, WorkflowStatus, TaskStatus, TaskResult
from gleitzeit.orchestration.distributed_scheduler import DistributedOrchestrator, DistributedTaskScheduler
from gleitzeit.persistence.base import InMemoryBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType


class MockRedisBackend(InMemoryBackend):
    """Enhanced InMemoryBackend with Redis-like operations for testing"""
    
    def __init__(self):
        super().__init__()
        self.queues = {}
        self.redis = self  # Mock redis
        self.kv_store = {}  # Key-value store for SET/GET
        self.expiry = {}   # Track expiry times
        
    async def lpush(self, key: str, value: str):
        """Add to queue"""
        if key not in self.queues:
            self.queues[key] = deque()
        self.queues[key].appendleft(value)
        
    async def brpop(self, key: str, timeout: int = 1):
        """Pop from queue"""
        if key in self.queues and self.queues[key]:
            return (key, self.queues[key].pop())
        return None
    
    async def set(self, key: str, value: str, nx: bool = False, ex: int = None) -> bool:
        """SET with NX (only if not exists) and EX (expiry)"""
        if nx and key in self.kv_store:
            return False
        
        self.kv_store[key] = value
        if ex:
            self.expiry[key] = datetime.utcnow().timestamp() + ex
        return True
    
    async def get(self, key: str) -> str:
        """GET value"""
        # Check expiry
        if key in self.expiry:
            if datetime.utcnow().timestamp() > self.expiry[key]:
                del self.kv_store[key]
                del self.expiry[key]
                return None
        
        return self.kv_store.get(key)
    
    async def delete(self, key: str):
        """DELETE key"""
        self.kv_store.pop(key, None)
        self.expiry.pop(key, None)
    
    async def setex(self, key: str, seconds: int, value: str):
        """SET with expiry"""
        await self.set(key, value, ex=seconds)
    
    async def scan(self, cursor: int = 0, match: str = "*", count: int = 100):
        """SCAN for keys (simplified)"""
        import fnmatch
        matching_keys = [k for k in self.kv_store.keys() if fnmatch.fnmatch(k, match)]
        return (0, matching_keys)  # Simplified: return all at once
    
    async def save_workflow(self, workflow: Workflow):
        """Override to ensure all tasks are saved too"""
        await super().save_workflow(workflow)
        for task in workflow.tasks:
            await self.save_task(task)
    
    async def get_task_result(self, task_id: str) -> TaskResult:
        """Override to handle None properly"""
        return self.task_results.get(task_id)


class DistributedProvider:
    """Provider that tracks which partition executed each task"""
    
    def __init__(self, protocol_name="test"):
        self.protocol_name = protocol_name
        self.executed_by_partition = defaultdict(list)
        self.total_executed = 0
        
    async def execute(self, method: str, params: dict, partition: int):
        """Execute task and track partition"""
        self.executed_by_partition[partition].append({
            "method": method,
            "params": params,
            "timestamp": datetime.utcnow()
        })
        self.total_executed += 1
        await asyncio.sleep(0.01)  # Simulate work
        return {"status": "success", "method": method, "partition": partition}


class PartitionedAdapter:
    """Adapter that processes tasks from a specific partition's queue"""
    
    def __init__(self, provider, backend, event_bus, protocol, partition):
        self.provider = provider
        self.backend = backend
        self.event_bus = event_bus
        self.protocol = protocol
        self.partition = partition
        self.running = False
        self.processed_count = 0
        
    async def start(self):
        """Start processing tasks for this partition"""
        self.running = True
        queue_key = f"provider:queue:{self.protocol}"
        
        while self.running:
            result = await self.backend.brpop(queue_key, timeout=1)
            if result:
                _, task_json = result
                await self._execute_task(task_json)
            else:
                await asyncio.sleep(0.01)
    
    async def _execute_task(self, task_json: str):
        """Execute task"""
        task_data = json.loads(task_json)
        task_id = task_data["task_id"]
        workflow_id = task_data["workflow_id"]
        
        # Update task status
        if task_id in self.backend.tasks:
            self.backend.tasks[task_id].status = TaskStatus.EXECUTING
        
        # Emit task started
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            data={
                "task_id": task_id,
                "workflow_id": workflow_id,
                "partition": self.partition,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        try:
            # Execute with partition tracking
            result = await self.provider.execute(
                task_data["method"],
                task_data["params"],
                self.partition
            )
            
            self.processed_count += 1
            
            # Save result
            task_result = TaskResult(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                result=result,
                completed_at=datetime.utcnow()
            )
            await self.backend.save_task_result(task_result)
            
            # Emit completed
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_COMPLETED,
                data={
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "result": result,
                    "partition": self.partition,
                    "timestamp": datetime.utcnow().isoformat()
                }
            ))
            
        except Exception as e:
            # Save failure
            task_result = TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                completed_at=datetime.utcnow()
            )
            await self.backend.save_task_result(task_result)
            
            # Emit failed
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_FAILED,
                data={
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "error": str(e),
                    "is_permanent": True,
                    "timestamp": datetime.utcnow().isoformat()
                }
            ))
    
    async def stop(self):
        """Stop adapter"""
        self.running = False


async def test_single_scheduler():
    """Test with single scheduler instance (baseline)"""
    print("\n=== Testing Single Scheduler (Baseline) ===")
    
    # Setup
    backend = MockRedisBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    # Create single orchestrator
    orchestrator = DistributedOrchestrator(
        persistence=backend,
        event_bus=event_bus,
        node_id="single",
        partition_key=None,  # No partitioning
        total_partitions=1
    )
    
    # Create provider and adapter
    provider = DistributedProvider()
    adapter = PartitionedAdapter(provider, backend, event_bus, "test", 0)
    
    # Start components
    await orchestrator.start()
    adapter_task = asyncio.create_task(adapter.start())
    
    try:
        # Create multiple workflows
        workflows = []
        for i in range(5):
            workflow = Workflow(
                id=f"workflow-{i}",
                name=f"Test Workflow {i}",
                tasks=[
                    Task(
                        id=f"w{i}-task-1",
                        name=f"Task 1",
                        protocol="test",
                        method=f"method_{i}_1",
                        params={"workflow": i, "task": 1}
                    ),
                    Task(
                        id=f"w{i}-task-2",
                        name=f"Task 2",
                        protocol="test",
                        method=f"method_{i}_2",
                        params={"workflow": i, "task": 2},
                        dependencies=[f"w{i}-task-1"]
                    )
                ]
            )
            workflows.append(workflow)
        
        # Submit all workflows
        start_time = asyncio.get_event_loop().time()
        for workflow in workflows:
            await orchestrator.submit_workflow(workflow)
        
        # Wait for completion
        max_wait = 5.0
        completed = 0
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            completed = 0
            for workflow in workflows:
                wf = await backend.get_workflow(workflow.id)
                if wf and wf.status == WorkflowStatus.COMPLETED:
                    completed += 1
            
            if completed == len(workflows):
                break
            
            await asyncio.sleep(0.1)
        
        duration = asyncio.get_event_loop().time() - start_time
        
        # Results
        print(f"Completed workflows: {completed}/{len(workflows)}")
        print(f"Total tasks executed: {provider.total_executed}")
        print(f"Execution time: {duration:.2f}s")
        print(f"Tasks/second: {provider.total_executed/duration:.1f}")
        
        return {
            "completed": completed,
            "total_tasks": provider.total_executed,
            "duration": duration,
            "throughput": provider.total_executed/duration if duration > 0 else 0
        }
        
    finally:
        await adapter.stop()
        adapter_task.cancel()
        try:
            await adapter_task
        except asyncio.CancelledError:
            pass
        await orchestrator.stop()
        await backend.shutdown()


async def test_distributed_schedulers():
    """Test with multiple distributed scheduler instances"""
    print("\n=== Testing Distributed Schedulers (3 Partitions) ===")
    
    # Setup
    backend = MockRedisBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    # Create 3 orchestrators with different partitions
    orchestrators = []
    for partition in range(3):
        orchestrator = DistributedOrchestrator(
            persistence=backend,
            event_bus=event_bus,
            node_id=f"node-{partition}",
            partition_key=partition,
            total_partitions=3
        )
        orchestrators.append(orchestrator)
    
    # Create provider and 3 adapters (simulating 3 workers)
    provider = DistributedProvider()
    adapters = []
    adapter_tasks = []
    
    for i in range(3):
        adapter = PartitionedAdapter(provider, backend, event_bus, "test", i)
        adapters.append(adapter)
    
    # Start all components
    for orchestrator in orchestrators:
        await orchestrator.start()
    
    for adapter in adapters:
        task = asyncio.create_task(adapter.start())
        adapter_tasks.append(task)
    
    try:
        # Create many workflows to distribute
        workflows = []
        for i in range(15):  # More workflows to see distribution
            workflow = Workflow(
                id=f"workflow-{i}",
                name=f"Test Workflow {i}",
                tasks=[
                    Task(
                        id=f"w{i}-task-1",
                        name=f"Task 1",
                        protocol="test",
                        method=f"method_{i}_1",
                        params={"workflow": i, "task": 1}
                    ),
                    Task(
                        id=f"w{i}-task-2",
                        name=f"Task 2",
                        protocol="test",
                        method=f"method_{i}_2",
                        params={"workflow": i, "task": 2},
                        dependencies=[f"w{i}-task-1"]
                    ),
                    Task(
                        id=f"w{i}-task-3",
                        name=f"Task 3",
                        protocol="test",
                        method=f"method_{i}_3",
                        params={"workflow": i, "task": 3},
                        dependencies=[f"w{i}-task-2"]
                    )
                ]
            )
            workflows.append(workflow)
        
        # Track which partition handles each workflow
        workflow_partitions = {}
        for workflow in workflows:
            hash_value = int(hashlib.md5(workflow.id.encode()).hexdigest(), 16)
            partition = hash_value % 3
            workflow_partitions[workflow.id] = partition
        
        # Submit all workflows (they'll be distributed)
        start_time = asyncio.get_event_loop().time()
        
        # Submit from first orchestrator (any can submit)
        for workflow in workflows:
            await orchestrators[0].submit_workflow(workflow)
        
        # Wait for completion
        max_wait = 10.0
        completed = 0
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            completed = 0
            for workflow in workflows:
                wf = await backend.get_workflow(workflow.id)
                if wf and wf.status == WorkflowStatus.COMPLETED:
                    completed += 1
            
            if completed == len(workflows):
                break
            
            await asyncio.sleep(0.1)
        
        duration = asyncio.get_event_loop().time() - start_time
        
        # Analyze distribution
        print(f"\nCompleted workflows: {completed}/{len(workflows)}")
        print(f"Total tasks executed: {provider.total_executed}")
        print(f"Execution time: {duration:.2f}s")
        print(f"Tasks/second: {provider.total_executed/duration:.1f}")
        
        # Show partition distribution
        print(f"\nWork distribution across partitions:")
        for partition in range(3):
            workflows_handled = sum(1 for p in workflow_partitions.values() if p == partition)
            tasks_executed = len(provider.executed_by_partition[partition])
            print(f"  Partition {partition}: {workflows_handled} workflows, {tasks_executed} tasks executed")
        
        # Check if work was actually distributed
        distribution_balanced = all(
            len(provider.executed_by_partition[p]) > 0 
            for p in range(3)
        )
        
        # Get cluster stats
        stats = await orchestrators[0].get_cluster_stats()
        print(f"\nCluster stats:")
        print(f"  Active nodes: {stats['total_nodes']}")
        print(f"  Partition coverage: {stats['partition_coverage']*100:.0f}%")
        
        return {
            "completed": completed,
            "total_tasks": provider.total_executed,
            "duration": duration,
            "throughput": provider.total_executed/duration if duration > 0 else 0,
            "distributed": distribution_balanced,
            "partition_coverage": stats['partition_coverage']
        }
        
    finally:
        # Stop all adapters
        for adapter in adapters:
            await adapter.stop()
        
        for task in adapter_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Stop all orchestrators
        for orchestrator in orchestrators:
            await orchestrator.stop()
        
        await backend.shutdown()


async def main():
    """Run scaling tests"""
    print("=" * 60)
    print("DISTRIBUTED SCALING TEST")
    print("=" * 60)
    
    # Run single scheduler test
    single_results = await test_single_scheduler()
    
    # Run distributed test
    distributed_results = await test_distributed_schedulers()
    
    # Compare results
    print("\n" + "=" * 60)
    print("PERFORMANCE COMPARISON")
    print("=" * 60)
    
    print(f"\nSingle Scheduler:")
    print(f"  Throughput: {single_results['throughput']:.1f} tasks/second")
    print(f"  Duration: {single_results['duration']:.2f}s")
    
    print(f"\nDistributed (3 partitions):")
    print(f"  Throughput: {distributed_results['throughput']:.1f} tasks/second")
    print(f"  Duration: {distributed_results['duration']:.2f}s")
    print(f"  Work distributed: {'✅' if distributed_results['distributed'] else '❌'}")
    
    # Calculate speedup
    speedup = distributed_results['throughput'] / single_results['throughput']
    print(f"\nSpeedup: {speedup:.2f}x")
    
    # Determine success
    success = (
        distributed_results['completed'] == 15 and
        distributed_results['distributed'] and
        distributed_results['partition_coverage'] == 1.0
    )
    
    if success:
        print("\n✅ DISTRIBUTED SCALING TEST PASSED")
        print("Successfully demonstrated:")
        print("- Work distribution across multiple schedulers")
        print("- Partition-based workflow assignment")
        print("- Parallel task execution")
        print("- Full partition coverage")
    else:
        print("\n❌ DISTRIBUTED SCALING TEST FAILED")
    
    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)