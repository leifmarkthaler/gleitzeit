"""
Comprehensive integration tests for GleitzeitClient

These tests focus on realistic usage scenarios combining multiple features.
"""

import pytest
import asyncio
import tempfile
from pathlib import Path

from gleitzeit.client import GleitzeitClient, create_client


class TestClientUsagePatterns:
    """Test common client usage patterns"""
    
    @pytest.mark.asyncio
    async def test_batch_processing_pattern(self, memory_client):
        """Test batch processing pattern with multiple tasks"""
        # Simulate batch processing workflow
        file_tasks = []
        
        # Submit multiple file processing tasks
        for i in range(10):
            task = await memory_client.submit_task(
                name=f"Process file_{i}.txt",
                protocol="python/v1",
                method="execute",
                params={
                    "code": f"# Process file_{i}.txt\nresult = 'processed_{i}'"
                },
                metadata={"file_index": i, "batch_id": "batch_001"}
            )
            file_tasks.append(task)
        
        # Verify all tasks were created
        assert len(file_tasks) == 10
        
        # Get statistics
        stats = await memory_client.get_task_statistics()
        assert stats["total"] >= 10
        assert stats["queued"] >= 10
        
        # Simulate checking completion (in real scenario, would wait)
        for task in file_tasks:
            retrieved = await memory_client.get_task(task.id)
            assert retrieved is not None
            assert retrieved.metadata["batch_id"] == "batch_001"
    
    @pytest.mark.asyncio
    async def test_pipeline_pattern(self, memory_client):
        """Test data pipeline pattern with dependent tasks"""
        # Create a data processing pipeline
        workflow = await memory_client.submit_workflow(
            name="Data Processing Pipeline",
            tasks=[
                {
                    "name": "extract",
                    "protocol": "python/v1",
                    "method": "execute",
                    "params": {"code": "data = {'users': 1000, 'active': 750}"}
                },
                {
                    "name": "transform",
                    "protocol": "python/v1",
                    "method": "execute",
                    "params": {
                        "code": "stats = ${extract.data}; conversion_rate = stats['active'] / stats['users']"
                    },
                    "dependencies": ["extract"]
                },
                {
                    "name": "analyze",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Analyze conversion rate: ${transform.conversion_rate}"
                            }
                        ]
                    },
                    "dependencies": ["transform"]
                },
                {
                    "name": "report",
                    "protocol": "python/v1",
                    "method": "execute",
                    "params": {
                        "code": "report = f'Analysis: {analysis}'"
                    },
                    "dependencies": ["analyze"]
                }
            ]
        )
        
        # Verify pipeline structure
        tasks = await memory_client.get_workflow_tasks(workflow.id)
        assert len(tasks) == 4
        
        # Check dependencies
        task_by_name = {t.name: t for t in tasks}
        assert task_by_name["extract"].dependencies == []
        assert task_by_name["transform"].dependencies == ["extract"]
        assert task_by_name["analyze"].dependencies == ["transform"]
        assert task_by_name["report"].dependencies == ["analyze"]
    
    @pytest.mark.asyncio
    async def test_resource_monitoring_pattern(self, memory_client):
        """Test resource monitoring and utilization tracking"""
        # Register multiple resources across different hubs
        resources = [
            ("compute-hub", "gpu-1", {"type": "GPU", "status": "healthy", "memory": 8192}),
            ("compute-hub", "gpu-2", {"type": "GPU", "status": "healthy", "memory": 8192}),
            ("compute-hub", "gpu-3", {"type": "GPU", "status": "maintenance", "memory": 8192}),
            ("storage-hub", "disk-1", {"type": "DISK", "status": "healthy", "capacity": 1000}),
            ("storage-hub", "disk-2", {"type": "DISK", "status": "healthy", "capacity": 2000}),
        ]
        
        for hub_id, instance_id, data in resources:
            registered = await memory_client.register_resource(
                hub_id=hub_id,
                instance_id=instance_id,
                instance_data=data
            )
            assert registered
        
        # Monitor utilization
        compute_util = await memory_client.get_resource_utilization("compute-hub")
        storage_util = await memory_client.get_resource_utilization("storage-hub")
        
        assert compute_util["total_instances"] == 3
        assert compute_util["healthy_instances"] == 2  # One in maintenance
        
        assert storage_util["total_instances"] == 2
        assert storage_util["healthy_instances"] == 2
        
        # Save performance metrics
        await memory_client.save_resource_metrics(
            hub_id="compute-hub",
            instance_id="gpu-1",
            metrics={
                "gpu_utilization": 85.0,
                "memory_usage": 6144,
                "temperature": 72
            }
        )
        
        # Retrieve metrics
        metrics = await memory_client.get_resource_metrics("compute-hub", "gpu-1")
        assert metrics is not None
        assert metrics.custom_metrics["gpu_utilization"] == 85.0
    
    @pytest.mark.asyncio
    async def test_multi_workflow_coordination(self, memory_client):
        """Test coordinating multiple workflows"""
        workflows = []
        
        # Submit multiple workflows for different purposes
        workflow_configs = [
            ("User Analytics", [
                {"name": "fetch_users", "protocol": "python/v1", "method": "execute"},
                {"name": "analyze_behavior", "protocol": "llm/v1", "method": "chat", "dependencies": ["fetch_users"]}
            ]),
            ("System Monitoring", [
                {"name": "check_health", "protocol": "python/v1", "method": "execute"},
                {"name": "generate_alerts", "protocol": "llm/v1", "method": "chat", "dependencies": ["check_health"]}
            ]),
            ("Content Processing", [
                {"name": "scan_content", "protocol": "python/v1", "method": "execute"},
                {"name": "moderate_content", "protocol": "llm/v1", "method": "chat", "dependencies": ["scan_content"]},
                {"name": "publish", "protocol": "python/v1", "method": "execute", "dependencies": ["moderate_content"]}
            ])
        ]
        
        for name, tasks in workflow_configs:
            workflow = await memory_client.submit_workflow(
                name=name,
                tasks=tasks,
                metadata={"category": name.split()[0].lower()}
            )
            workflows.append(workflow)
        
        # Verify all workflows
        assert len(workflows) == 3
        
        total_tasks = 0
        for workflow in workflows:
            tasks = await memory_client.get_workflow_tasks(workflow.id)
            total_tasks += len(tasks)
            
            # Verify each workflow has proper structure
            assert len(tasks) >= 2
        
        # Check overall statistics
        stats = await memory_client.get_task_statistics()
        assert stats["total"] >= total_tasks


class TestErrorRecoveryScenarios:
    """Test error recovery and resilience scenarios"""
    
    @pytest.mark.asyncio
    async def test_persistence_switching(self):
        """Test switching between persistence backends"""
        # Start with memory
        client1 = GleitzeitClient(persistence_type="memory")
        await client1.initialize()
        
        task = await client1.submit_task(
            name="Memory Task",
            protocol="python/v1",
            method="execute"
        )
        memory_task_id = task.id
        
        await client1.shutdown()
        
        # Switch to SQLite
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        
        try:
            client2 = GleitzeitClient(
                persistence_type="sql",
                sql_db_path=db_path
            )
            await client2.initialize()
            
            # Memory task should not exist in SQLite
            memory_task = await client2.get_task(memory_task_id)
            assert memory_task is None
            
            # Create new task in SQLite
            sql_task = await client2.submit_task(
                name="SQLite Task",
                protocol="python/v1",
                method="execute"
            )
            
            await client2.shutdown()
            
            # Reconnect to same SQLite database
            client3 = GleitzeitClient(
                persistence_type="sql",
                sql_db_path=db_path
            )
            await client3.initialize()
            
            # SQLite task should persist
            persistent_task = await client3.get_task(sql_task.id)
            assert persistent_task is not None
            assert persistent_task.name == "SQLite Task"
            
            await client3.shutdown()
            
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_graceful_degradation(self):
        """Test graceful degradation when operations fail"""
        client = GleitzeitClient(persistence_type="memory")
        await client.initialize()
        
        try:
            # Submit task that should work
            good_task = await client.submit_task(
                name="Good Task",
                protocol="python/v1",
                method="execute",
                params={"code": "result = 'success'"}
            )
            assert good_task is not None
            
            # Simulate adapter failure for specific operation
            original_save = client.adapter.save_task
            client.adapter.save_task = lambda task: False  # Simulate failure
            
            # This should handle the save failure gracefully
            # (In real implementation, might retry or log error)
            try:
                bad_task = await client.submit_task(
                    name="Bad Task",
                    protocol="python/v1",
                    method="execute"
                )
                # Depending on implementation, might succeed with warning
                # or raise an exception
            except Exception:
                # Expected if implementation throws on save failure
                pass
            
            # Restore original function
            client.adapter.save_task = original_save
            
            # Verify good task still retrievable
            retrieved = await client.get_task(good_task.id)
            assert retrieved is not None
            
        finally:
            await client.shutdown()


class TestPerformanceScenarios:
    """Test performance-related scenarios"""
    
    @pytest.mark.asyncio
    async def test_large_batch_submission(self, memory_client):
        """Test submitting large batch of tasks"""
        batch_size = 100
        tasks = []
        
        # Submit large batch
        for i in range(batch_size):
            task = await memory_client.submit_task(
                name=f"Batch Task {i:03d}",
                protocol="python/v1",
                method="execute",
                params={"code": f"result = {i}"},
                priority=i % 10,  # Varying priorities
                metadata={"batch": "large", "index": i}
            )
            tasks.append(task)
        
        assert len(tasks) == batch_size
        
        # Verify statistics
        stats = await memory_client.get_task_statistics()
        assert stats["total"] >= batch_size
        assert stats["queued"] >= batch_size
        
        # Spot check some tasks
        first_task = await memory_client.get_task(tasks[0].id)
        assert first_task.name == "Batch Task 000"
        
        last_task = await memory_client.get_task(tasks[-1].id)
        assert last_task.name == f"Batch Task {batch_size-1:03d}"
        
        middle_task = await memory_client.get_task(tasks[batch_size//2].id)
        assert middle_task.metadata["index"] == batch_size//2
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self, memory_client):
        """Test concurrent client operations"""
        # Define concurrent operations
        async def submit_tasks():
            tasks = []
            for i in range(20):
                task = await memory_client.submit_task(
                    name=f"Concurrent Task {i}",
                    protocol="python/v1",
                    method="execute"
                )
                tasks.append(task)
            return tasks
        
        async def register_resources():
            resources = []
            for i in range(10):
                success = await memory_client.register_resource(
                    hub_id="concurrent-hub",
                    instance_id=f"resource-{i}",
                    instance_data={"type": "TEST", "status": "healthy"}
                )
                resources.append(success)
            return resources
        
        async def submit_workflows():
            workflows = []
            for i in range(5):
                workflow = await memory_client.submit_workflow(
                    name=f"Concurrent Workflow {i}",
                    tasks=[
                        {"name": f"task-{i}-1", "protocol": "python/v1", "method": "execute"},
                        {"name": f"task-{i}-2", "protocol": "llm/v1", "method": "chat"}
                    ]
                )
                workflows.append(workflow)
            return workflows
        
        # Execute all operations concurrently
        results = await asyncio.gather(
            submit_tasks(),
            register_resources(),
            submit_workflows(),
            return_exceptions=True
        )
        
        # Verify all operations succeeded
        tasks, resources, workflows = results
        
        assert len(tasks) == 20
        assert all(resources)  # All resource registrations succeeded
        assert len(workflows) == 5
        
        # Verify system state
        stats = await memory_client.get_task_statistics()
        assert stats["total"] >= 30  # 20 individual + 10 from workflows
        
        utilization = await memory_client.get_resource_utilization("concurrent-hub")
        assert utilization["total_instances"] >= 10


class TestClientCompatibility:
    """Test client compatibility and edge cases"""
    
    @pytest.mark.asyncio
    async def test_empty_operations(self, memory_client):
        """Test operations with empty/minimal data"""
        # Submit task with minimal parameters
        minimal_task = await memory_client.submit_task(
            name="Minimal",
            protocol="python/v1",
            method="execute"
        )
        assert minimal_task is not None
        
        # Submit empty workflow
        empty_workflow = await memory_client.submit_workflow(
            name="Empty Workflow",
            tasks=[]
        )
        assert empty_workflow is not None
        assert len(empty_workflow.tasks) == 0
        
        # Register resource with minimal data
        minimal_resource = await memory_client.register_resource(
            hub_id="minimal-hub",
            instance_id="minimal-resource",
            instance_data={}
        )
        assert minimal_resource
    
    @pytest.mark.asyncio
    async def test_unicode_and_special_characters(self, memory_client):
        """Test handling of unicode and special characters"""
        # Task with unicode name
        unicode_task = await memory_client.submit_task(
            name="任务 🚀 Test",
            protocol="python/v1",
            method="execute",
            params={"code": "# Comment with émojis 😀"},
            metadata={"description": "Tëst with speçial chars"}
        )
        
        retrieved = await memory_client.get_task(unicode_task.id)
        assert retrieved.name == "任务 🚀 Test"
        assert "émojis" in retrieved.params["code"]
    
    @pytest.mark.asyncio
    async def test_large_data_handling(self, memory_client):
        """Test handling of large data in tasks"""
        # Create large parameter data
        large_text = "x" * 10000  # 10KB of text
        large_list = list(range(1000))
        
        large_task = await memory_client.submit_task(
            name="Large Data Task",
            protocol="python/v1",
            method="execute",
            params={
                "large_text": large_text,
                "large_list": large_list,
                "nested": {
                    "deep": {
                        "structure": large_list[:100]
                    }
                }
            }
        )
        
        retrieved = await memory_client.get_task(large_task.id)
        assert len(retrieved.params["large_text"]) == 10000
        assert len(retrieved.params["large_list"]) == 1000
        assert retrieved.params["nested"]["deep"]["structure"][0] == 0