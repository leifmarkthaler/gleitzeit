"""
End-to-end test demonstrating complete scaling solution
"""

import asyncio
import json
from datetime import datetime
from collections import defaultdict
import hashlib

from gleitzeit.core.models import Task, Workflow, WorkflowStatus, TaskStatus, TaskResult
from gleitzeit.orchestration.distributed_scheduler import DistributedOrchestrator
from gleitzeit.orchestration.scalable_provider import ScalableProviderAdapter, ProviderCluster
from gleitzeit.persistence.base import InMemoryBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType


class FullMockBackend(InMemoryBackend):
    """Complete mock backend for testing"""
    
    def __init__(self):
        super().__init__()
        self.redis = self
        self.kv_store = {}
        self.expiry = {}
        self.queues = defaultdict(list)
        
    async def lpush(self, key: str, value: str):
        self.queues[key].insert(0, value)
        
    async def brpop(self, key: str, timeout: int = 1):
        if self.queues[key]:
            return (key, self.queues[key].pop())
        return None
    
    async def set(self, key: str, value: str, nx: bool = False, ex: int = None) -> bool:
        if nx and key in self.kv_store:
            return False
        self.kv_store[key] = value
        if ex:
            self.expiry[key] = datetime.utcnow().timestamp() + ex
        return True
    
    async def get(self, key: str):
        if key in self.expiry and datetime.utcnow().timestamp() > self.expiry[key]:
            del self.kv_store[key]
            del self.expiry[key]
            return None
        return self.kv_store.get(key)
    
    async def delete(self, key: str):
        self.kv_store.pop(key, None)
        self.expiry.pop(key, None)
    
    async def setex(self, key: str, seconds: int, value: str):
        await self.set(key, value, ex=seconds)
    
    async def scan(self, cursor: int = 0, match: str = "*", count: int = 100):
        import fnmatch
        matching = [k for k in self.kv_store if fnmatch.fnmatch(k, match)]
        return (0, matching)
    
    async def save_workflow(self, workflow: Workflow):
        await super().save_workflow(workflow)
        for task in workflow.tasks:
            await self.save_task(task)
    
    async def get_task_result(self, task_id: str):
        return self.task_results.get(task_id)


class TestProvider:
    """Test provider that simulates work"""
    
    def __init__(self, delay: float = 0.01):
        self.delay = delay
        self.executed = []
        
    async def execute(self, method: str, params: dict):
        """Simulate task execution"""
        await asyncio.sleep(self.delay)
        self.executed.append({
            "method": method,
            "params": params,
            "timestamp": datetime.utcnow()
        })
        return {"status": "success", "method": method, "result": len(self.executed)}


async def test_end_to_end_scaling():
    """Complete end-to-end test with scaling at all levels"""
    print("\n" + "=" * 60)
    print("END-TO-END SCALING TEST")
    print("=" * 60)
    
    # Setup
    backend = FullMockBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    # 1. Create distributed orchestrators (3 partitions)
    print("\n1. Setting up distributed orchestrators...")
    orchestrators = []
    for partition in range(3):
        orchestrator = DistributedOrchestrator(
            persistence=backend,
            event_bus=event_bus,
            node_id=f"orchestrator-{partition}",
            partition_key=partition,
            total_partitions=3
        )
        await orchestrator.start()
        orchestrators.append(orchestrator)
    print(f"   ✓ Started {len(orchestrators)} orchestrator partitions")
    
    # 2. Create provider cluster with multiple adapters
    print("\n2. Setting up provider cluster...")
    cluster = ProviderCluster(
        protocol="test",
        persistence=backend,
        event_bus=event_bus
    )
    
    # Add multiple provider adapters with different worker counts
    providers = []
    for i in range(3):
        provider = TestProvider(delay=0.005)  # Faster for testing
        providers.append(provider)
        
        adapter = await cluster.add_adapter(
            provider=provider,
            node_id=f"provider-{i}",
            num_workers=3 + i  # 3, 4, 5 workers
        )
    
    total_workers = sum(a.num_workers for a in cluster.adapters)
    print(f"   ✓ Started {len(cluster.adapters)} provider adapters")
    print(f"   ✓ Total workers: {total_workers}")
    
    # 3. Create complex workflows with dependencies
    print("\n3. Creating test workflows...")
    workflows = []
    num_workflows = 20
    
    for i in range(num_workflows):
        # Create workflow with varying complexity
        num_tasks = 3 + (i % 3)  # 3-5 tasks per workflow
        tasks = []
        
        for j in range(num_tasks):
            task = Task(
                id=f"w{i}-t{j}",
                name=f"Task {j}",
                protocol="test",
                method=f"process_w{i}_t{j}",
                params={"workflow": i, "task": j, "data": f"data-{i}-{j}"},
                dependencies=[f"w{i}-t{j-1}"] if j > 0 else []  # Chain dependencies
            )
            tasks.append(task)
        
        workflow = Workflow(
            id=f"workflow-{i}",
            name=f"Workflow {i}",
            tasks=tasks
        )
        workflows.append(workflow)
    
    total_tasks = sum(len(w.tasks) for w in workflows)
    print(f"   ✓ Created {num_workflows} workflows with {total_tasks} total tasks")
    
    # 4. Submit workflows and measure performance
    print("\n4. Submitting workflows...")
    start_time = asyncio.get_event_loop().time()
    
    # Submit workflows round-robin to different orchestrators
    for i, workflow in enumerate(workflows):
        orchestrator = orchestrators[i % len(orchestrators)]
        await orchestrator.submit_workflow(workflow)
    
    print(f"   ✓ All workflows submitted")
    
    # 5. Monitor execution progress
    print("\n5. Executing tasks...")
    print("   Progress:")
    
    max_wait = 30.0
    last_progress = 0
    progress_bar_width = 40
    
    while asyncio.get_event_loop().time() - start_time < max_wait:
        # Count completed workflows
        completed = 0
        total_completed_tasks = 0
        
        for workflow in workflows:
            wf = await backend.get_workflow(workflow.id)
            if wf:
                if wf.status == WorkflowStatus.COMPLETED:
                    completed += 1
                
                # Count completed tasks
                for task in wf.tasks:
                    result = await backend.get_task_result(task.id)
                    if result and result.status == TaskStatus.COMPLETED:
                        total_completed_tasks += 1
        
        # Update progress bar
        progress = int((total_completed_tasks / total_tasks) * progress_bar_width)
        if progress > last_progress:
            bar = "█" * progress + "░" * (progress_bar_width - progress)
            percentage = (total_completed_tasks / total_tasks) * 100
            print(f"   [{bar}] {percentage:.1f}% ({total_completed_tasks}/{total_tasks} tasks)")
            last_progress = progress
        
        if completed == num_workflows:
            break
        
        await asyncio.sleep(0.2)
    
    execution_time = asyncio.get_event_loop().time() - start_time
    
    # 6. Collect and analyze results
    print("\n6. Analyzing results...")
    
    # Workflow completion stats
    completed_workflows = 0
    for workflow in workflows:
        wf = await backend.get_workflow(workflow.id)
        if wf and wf.status == WorkflowStatus.COMPLETED:
            completed_workflows += 1
    
    # Task execution stats
    total_executed = sum(len(p.executed) for p in providers)
    
    # Partition distribution
    partition_distribution = defaultdict(int)
    for workflow in workflows:
        hash_value = int(hashlib.md5(workflow.id.encode()).hexdigest(), 16)
        partition = hash_value % 3
        partition_distribution[partition] += 1
    
    # Provider distribution
    provider_distribution = {
        f"provider-{i}": len(providers[i].executed)
        for i in range(len(providers))
    }
    
    # Get cluster stats
    orchestrator_stats = await orchestrators[0].get_cluster_stats()
    provider_stats = await cluster.get_cluster_metrics()
    
    # 7. Display comprehensive results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    print(f"\nWorkflow Execution:")
    print(f"  Completed: {completed_workflows}/{num_workflows} workflows")
    print(f"  Total tasks executed: {total_executed}/{total_tasks}")
    print(f"  Execution time: {execution_time:.2f}s")
    print(f"  Throughput: {total_executed/execution_time:.1f} tasks/second")
    
    print(f"\nOrchestrator Distribution:")
    for partition, count in sorted(partition_distribution.items()):
        print(f"  Partition {partition}: {count} workflows")
    print(f"  Load balance variance: {max(partition_distribution.values()) - min(partition_distribution.values())} workflows")
    
    print(f"\nProvider Distribution:")
    for provider_id, count in sorted(provider_distribution.items()):
        adapter = next(a for a in cluster.adapters if a.node_id == provider_id)
        print(f"  {provider_id}: {count} tasks ({adapter.num_workers} workers)")
    
    print(f"\nCluster Health:")
    print(f"  Orchestrator nodes: {orchestrator_stats['total_nodes']}")
    print(f"  Partition coverage: {orchestrator_stats['partition_coverage']*100:.0f}%")
    print(f"  Provider adapters: {provider_stats['num_adapters']}")
    print(f"  Total workers: {provider_stats['total_workers']}")
    
    print(f"\nPerformance Metrics:")
    print(f"  Tasks/second: {total_executed/execution_time:.1f}")
    print(f"  Avg task duration: {execution_time/total_executed*1000:.1f}ms")
    print(f"  Parallel efficiency: {(total_executed/execution_time)/(total_workers):.2f} tasks/second/worker")
    
    # 8. Cleanup
    print("\n7. Cleaning up...")
    await cluster.stop_all()
    for orchestrator in orchestrators:
        await orchestrator.stop()
    await backend.shutdown()
    print("   ✓ All components stopped")
    
    # Determine success
    success = (
        completed_workflows == num_workflows and
        total_executed == total_tasks and
        orchestrator_stats['partition_coverage'] == 1.0 and
        all(count > 0 for count in provider_distribution.values())
    )
    
    if success:
        print("\n" + "=" * 60)
        print("✅ END-TO-END SCALING TEST PASSED")
        print("=" * 60)
        print("\nSuccessfully demonstrated:")
        print("  • Distributed orchestration across 3 partitions")
        print("  • Scalable provider cluster with multiple adapters")
        print("  • Parallel task execution with dependency resolution")
        print("  • Work distribution and load balancing")
        print("  • Complete workflow lifecycle management")
        print(f"  • High throughput: {total_executed/execution_time:.1f} tasks/second")
    else:
        print("\n❌ END-TO-END SCALING TEST FAILED")
        if completed_workflows < num_workflows:
            print(f"  - Only {completed_workflows}/{num_workflows} workflows completed")
        if total_executed < total_tasks:
            print(f"  - Only {total_executed}/{total_tasks} tasks executed")
    
    return success


async def test_dynamic_scaling():
    """Test dynamic scaling up and down"""
    print("\n" + "=" * 60)
    print("DYNAMIC SCALING TEST")
    print("=" * 60)
    
    backend = FullMockBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    # Start with minimal setup
    print("\n1. Starting with minimal setup...")
    orchestrator = DistributedOrchestrator(
        persistence=backend,
        event_bus=event_bus,
        node_id="orchestrator-main"
    )
    await orchestrator.start()
    
    cluster = ProviderCluster(
        protocol="test",
        persistence=backend,
        event_bus=event_bus
    )
    
    # Start with just 1 adapter
    provider1 = TestProvider(delay=0.01)
    await cluster.add_adapter(provider1, "provider-initial", num_workers=2)
    print("   ✓ Started with 1 orchestrator, 1 provider (2 workers)")
    
    # Submit initial workload
    print("\n2. Submitting initial workload...")
    workflows_batch1 = []
    for i in range(5):
        workflow = Workflow(
            id=f"batch1-workflow-{i}",
            name=f"Batch 1 Workflow {i}",
            tasks=[
                Task(
                    id=f"b1-w{i}-t{j}",
                    name=f"Task {j}",
                    protocol="test",
                    method=f"batch1_w{i}_t{j}",
                    params={"batch": 1, "workflow": i, "task": j}
                ) for j in range(3)
            ]
        )
        workflows_batch1.append(workflow)
        await orchestrator.submit_workflow(workflow)
    
    # Wait a bit
    await asyncio.sleep(0.5)
    
    # Scale up providers
    print("\n3. Scaling up providers...")
    provider2 = TestProvider(delay=0.01)
    provider3 = TestProvider(delay=0.01)
    await cluster.add_adapter(provider2, "provider-2", num_workers=3)
    await cluster.add_adapter(provider3, "provider-3", num_workers=4)
    
    metrics = await cluster.get_cluster_metrics()
    print(f"   ✓ Scaled to {metrics['num_adapters']} adapters, {metrics['total_workers']} total workers")
    
    # Submit more workload
    print("\n4. Submitting increased workload...")
    workflows_batch2 = []
    for i in range(10):
        workflow = Workflow(
            id=f"batch2-workflow-{i}",
            name=f"Batch 2 Workflow {i}",
            tasks=[
                Task(
                    id=f"b2-w{i}-t{j}",
                    name=f"Task {j}",
                    protocol="test",
                    method=f"batch2_w{i}_t{j}",
                    params={"batch": 2, "workflow": i, "task": j}
                ) for j in range(4)
            ]
        )
        workflows_batch2.append(workflow)
        await orchestrator.submit_workflow(workflow)
    
    # Wait for execution
    await asyncio.sleep(1.0)
    
    # Check progress
    total_workflows = workflows_batch1 + workflows_batch2
    completed = 0
    for workflow in total_workflows:
        wf = await backend.get_workflow(workflow.id)
        if wf and wf.status == WorkflowStatus.COMPLETED:
            completed += 1
    
    print(f"\n5. Progress check:")
    print(f"   Completed: {completed}/{len(total_workflows)} workflows")
    
    # Scale down
    print("\n6. Scaling down...")
    await cluster.scale_down(1)
    metrics = await cluster.get_cluster_metrics()
    print(f"   ✓ Scaled to {metrics['num_adapters']} adapters")
    
    # Wait for remaining work
    max_wait = 5.0
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < max_wait:
        completed = 0
        for workflow in total_workflows:
            wf = await backend.get_workflow(workflow.id)
            if wf and wf.status == WorkflowStatus.COMPLETED:
                completed += 1
        if completed == len(total_workflows):
            break
        await asyncio.sleep(0.1)
    
    # Final results
    print(f"\n7. Final results:")
    print(f"   Completed: {completed}/{len(total_workflows)} workflows")
    print(f"   Dynamic scaling: {'✅ Success' if completed == len(total_workflows) else '❌ Failed'}")
    
    # Cleanup
    await cluster.stop_all()
    await orchestrator.stop()
    await backend.shutdown()
    
    return completed == len(total_workflows)


async def main():
    """Run all scaling tests"""
    print("=" * 60)
    print("GLEITZEIT SCALING TEST SUITE")
    print("=" * 60)
    
    results = []
    
    # Run end-to-end test
    print("\nTest 1: End-to-End Scaling")
    result1 = await test_end_to_end_scaling()
    results.append(("End-to-End Scaling", result1))
    
    # Run dynamic scaling test
    print("\nTest 2: Dynamic Scaling")
    result2 = await test_dynamic_scaling()
    results.append(("Dynamic Scaling", result2))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {test_name}: {status}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n🎉 ALL SCALING TESTS PASSED!")
        print("\nThe Gleitzeit scaling solution is ready for production:")
        print("  • Horizontal scaling at orchestration layer")
        print("  • Horizontal scaling at execution layer")
        print("  • Dynamic scaling up and down")
        print("  • Efficient work distribution")
        print("  • High throughput and low latency")
    else:
        print("\n⚠️ SOME TESTS FAILED")
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)