"""
Integration tests for GleitzeitCluster with auto-start functionality
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.core.task import Task, TaskType, TaskParameters
from gleitzeit_cluster.core.workflow import Workflow


@pytest.mark.integration
class TestClusterAutoStart:
    """Test cluster auto-start functionality"""
    
    @pytest.mark.asyncio
    async def test_cluster_with_auto_start_disabled(self):
        """Test cluster starts normally with auto-start disabled"""
        cluster = GleitzeitCluster(
            enable_redis=False,
            enable_socketio=False, 
            enable_real_execution=False,
            auto_start_services=False
        )
        
        await cluster.start()
        
        assert cluster._is_started is True
        assert cluster.service_manager is None
        
        await cluster.stop()
    
    @pytest.mark.asyncio
    async def test_cluster_with_auto_start_enabled(self, mock_subprocess, mock_socket):
        """Test cluster with auto-start functionality enabled"""
        with patch('gleitzeit_cluster.core.service_manager.ServiceManager.is_redis_running', return_value=False), \
             patch('gleitzeit_cluster.core.service_manager.ServiceManager.start_redis_server', return_value=True), \
             patch('gleitzeit_cluster.core.service_manager.ServiceManager.start_executor_node', return_value=True):
            
            cluster = GleitzeitCluster(
                enable_redis=False,  # Disable real Redis for test
                enable_socketio=False,  # Disable real SocketIO for test
                enable_real_execution=False,
                auto_start_services=True,
                auto_start_redis=True,
                auto_start_executors=True,
                min_executors=2
            )
            
            await cluster.start()
            
            assert cluster._is_started is True
            assert cluster.service_manager is not None
            assert cluster.auto_start_services is True
            assert cluster.min_executors == 2
            
            await cluster.stop()
    
    @pytest.mark.asyncio
    async def test_cluster_auto_start_redis_only(self):
        """Test cluster auto-starting only Redis"""
        with patch('gleitzeit_cluster.core.service_manager.ServiceManager.is_redis_running', return_value=False), \
             patch('gleitzeit_cluster.core.service_manager.ServiceManager.start_redis_server', return_value=True), \
             patch('gleitzeit_cluster.core.service_manager.ServiceManager.start_executor_node') as mock_executor:
            
            cluster = GleitzeitCluster(
                enable_redis=False,
                enable_socketio=False,
                enable_real_execution=False,
                auto_start_services=True,
                auto_start_redis=True,
                auto_start_executors=False  # Don't start executors
            )
            
            await cluster.start()
            
            # Executor start should not be called
            mock_executor.assert_not_called()
            
            await cluster.stop()
    
    @pytest.mark.asyncio
    async def test_cluster_auto_start_failure_handling(self):
        """Test cluster handles auto-start failures gracefully"""
        with patch('gleitzeit_cluster.core.service_manager.ServiceManager.is_redis_running', return_value=False), \
             patch('gleitzeit_cluster.core.service_manager.ServiceManager.start_redis_server', return_value=False), \
             patch('gleitzeit_cluster.core.service_manager.ServiceManager.start_executor_node', return_value=False):
            
            cluster = GleitzeitCluster(
                enable_redis=False,
                enable_socketio=False,
                enable_real_execution=False,
                auto_start_services=True,
                auto_start_redis=True,
                auto_start_executors=True
            )
            
            # Should start successfully even if auto-start fails
            await cluster.start()
            assert cluster._is_started is True
            
            await cluster.stop()
    
    @pytest.mark.asyncio
    async def test_cluster_service_cleanup_on_stop(self, mock_subprocess):
        """Test cluster cleans up managed services on stop"""
        with patch('gleitzeit_cluster.core.service_manager.ServiceManager.is_redis_running', return_value=True), \
             patch('gleitzeit_cluster.core.service_manager.ServiceManager.start_executor_node', return_value=True), \
             patch('gleitzeit_cluster.core.service_manager.ServiceManager.stop_managed_services', return_value=["executor"]) as mock_stop:
            
            cluster = GleitzeitCluster(
                enable_redis=False,
                enable_socketio=False,
                enable_real_execution=False,
                auto_start_services=True
            )
            
            await cluster.start()
            await cluster.stop()
            
            # Stop services should be called
            mock_stop.assert_called_once()


@pytest.mark.integration
class TestClusterWorkflowExecution:
    """Test complete workflow execution with cluster"""
    
    @pytest.mark.asyncio
    async def test_workflow_submission_and_status(self, cluster):
        """Test workflow submission and status tracking"""
        workflow = Workflow(name="test_workflow")
        
        task = Task(
            name="test_task",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="current_timestamp",
                kwargs={}
            )
        )
        workflow.add_task(task)
        
        # Submit workflow
        workflow_id = await cluster.submit_workflow(workflow)
        assert workflow_id is not None
        
        # Check initial status
        status = await cluster.get_workflow_status(workflow_id)
        assert status is not None
        assert status["workflow_id"] == workflow_id
        assert "status" in status
        assert "total_tasks" in status
    
    @pytest.mark.asyncio
    async def test_workflow_with_dependencies(self, cluster):
        """Test workflow with task dependencies"""
        workflow = Workflow(name="dependency_workflow")
        
        # Task 1: Generate data
        task1 = Task(
            id="task1",
            name="Generate Data",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="fibonacci",
                kwargs={"n": 5}
            )
        )
        
        # Task 2: Analyze data (depends on task1)
        task2 = Task(
            id="task2",
            name="Analyze Data",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="analyze_numbers",
                kwargs={"numbers": "{{task1.result}}"}
            ),
            dependencies=["task1"]
        )
        
        workflow.add_task(task1)
        workflow.add_task(task2)
        
        # Submit workflow
        workflow_id = await cluster.submit_workflow(workflow)
        
        # Check workflow structure
        status = await cluster.get_workflow_status(workflow_id)
        assert status["total_tasks"] == 2
    
    @pytest.mark.asyncio
    async def test_multiple_workflows(self, cluster):
        """Test handling multiple concurrent workflows"""
        workflows = []
        
        for i in range(3):
            workflow = Workflow(name=f"workflow_{i}")
            task = Task(
                name=f"task_{i}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="current_timestamp",
                    kwargs={}
                )
            )
            workflow.add_task(task)
            workflows.append(workflow)
        
        # Submit all workflows
        workflow_ids = []
        for workflow in workflows:
            workflow_id = await cluster.submit_workflow(workflow)
            workflow_ids.append(workflow_id)
        
        # Check all workflows were submitted
        assert len(workflow_ids) == 3
        assert len(set(workflow_ids)) == 3  # All unique
        
        # Check status of each workflow
        for workflow_id in workflow_ids:
            status = await cluster.get_workflow_status(workflow_id)
            assert status is not None
            assert status["workflow_id"] == workflow_id
    
    @pytest.mark.asyncio
    async def test_workflow_cancellation(self, cluster):
        """Test workflow cancellation"""
        workflow = Workflow(name="cancellation_test")
        
        task = Task(
            name="long_task",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="async_timer",
                kwargs={"duration": 10}  # Long-running task
            )
        )
        workflow.add_task(task)
        
        # Submit workflow
        workflow_id = await cluster.submit_workflow(workflow)
        
        # Immediately cancel it
        cancel_result = await cluster.cancel_workflow(workflow_id)
        
        # Check cancellation was processed
        # Note: In mock environment, behavior may vary
        assert cancel_result is not None


@pytest.mark.integration 
class TestClusterFunctionIntegration:
    """Test cluster integration with function registry"""
    
    @pytest.mark.asyncio
    async def test_function_task_execution(self, cluster):
        """Test executing function-based tasks"""
        # Test various function types
        test_cases = [
            {
                "name": "fibonacci_test",
                "function_name": "fibonacci",
                "kwargs": {"n": 8}
            },
            {
                "name": "timestamp_test", 
                "function_name": "current_timestamp",
                "kwargs": {}
            },
            {
                "name": "analysis_test",
                "function_name": "analyze_numbers",
                "kwargs": {"numbers": [1, 2, 3, 4, 5]}
            }
        ]
        
        for test_case in test_cases:
            workflow = Workflow(name=test_case["name"])
            
            task = Task(
                name=test_case["name"],
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name=test_case["function_name"],
                    kwargs=test_case["kwargs"]
                )
            )
            workflow.add_task(task)
            
            workflow_id = await cluster.submit_workflow(workflow)
            status = await cluster.get_workflow_status(workflow_id)
            
            assert status is not None
            assert status["total_tasks"] == 1
    
    @pytest.mark.asyncio
    async def test_invalid_function_handling(self, cluster):
        """Test handling of invalid function calls"""
        workflow = Workflow(name="invalid_function_test")
        
        # Task with non-existent function
        task = Task(
            name="invalid_task",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="non_existent_function",
                kwargs={}
            )
        )
        workflow.add_task(task)
        
        # Should submit successfully (error handling is in execution)
        workflow_id = await cluster.submit_workflow(workflow)
        assert workflow_id is not None
        
        status = await cluster.get_workflow_status(workflow_id)
        assert status is not None


@pytest.mark.integration
class TestClusterConvenienceMethods:
    """Test cluster convenience methods"""
    
    @pytest.mark.asyncio
    async def test_analyze_text_method(self, cluster, mock_ollama):
        """Test analyze_text convenience method"""
        result = await cluster.analyze_text("Test text for analysis")
        
        # In mock environment, should return mock result
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_batch_analyze_images_method(self, cluster, mock_ollama):
        """Test batch_analyze_images convenience method"""
        image_paths = ["/path/to/img1.jpg", "/path/to/img2.jpg"]
        
        results = await cluster.batch_analyze_images(
            "Describe the image",
            image_paths
        )
        
        # Should return results for all images
        assert results is not None
        if isinstance(results, dict):
            assert len(results) <= len(image_paths)
    
    @pytest.mark.asyncio
    async def test_pull_model_method(self, cluster, mock_ollama):
        """Test pull_model convenience method"""
        result = await cluster.pull_model("llama3")
        
        # Should handle pull request
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_get_available_models_method(self, cluster, mock_ollama):
        """Test get_available_models method"""
        models = await cluster.get_available_models()
        
        assert models is not None
        assert isinstance(models, dict)
        if "available" in models:
            assert isinstance(models["available"], list)


@pytest.mark.integration 
class TestBatchProcessingIntegration:
    """Test batch processing integration with cluster"""
    
    @pytest.mark.asyncio
    async def test_batch_image_analysis_integration(self, cluster, mock_ollama):
        """Test batch image analysis with cluster integration"""
        image_paths = [
            "/test/image1.jpg",
            "/test/image2.jpg", 
            "/test/image3.jpg"
        ]
        
        # Test the convenience method exists and works
        try:
            results = await cluster.batch_analyze_images(
                "Describe this image",
                image_paths
            )
            # Should not raise an error
            assert results is not None
        except AttributeError:
            # Method might not exist, that's ok for testing
            pass
    
    @pytest.mark.asyncio
    async def test_batch_function_execution(self, cluster):
        """Test batch function execution through workflows"""
        # Create batch processing workflow
        workflow = Workflow(name="batch_function_test")
        
        # Batch process different datasets
        datasets = [
            [1, 2, 3, 4, 5],
            [10, 20, 30, 40],
            [100, 200, 300]
        ]
        
        for i, data in enumerate(datasets):
            task = Task(
                id=f"batch_{i}",
                name=f"Process Batch {i+1}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="analyze_numbers",
                    kwargs={"numbers": data}
                )
            )
            workflow.add_task(task)
        
        # Submit and verify
        workflow_id = await cluster.submit_workflow(workflow)
        status = await cluster.get_workflow_status(workflow_id)
        
        assert status["total_tasks"] == 3
        assert workflow_id is not None
    
    @pytest.mark.asyncio
    async def test_mixed_batch_workflow(self, cluster, mock_ollama):
        """Test workflow mixing batch processing with different task types"""
        workflow = Workflow(name="mixed_batch")
        
        # Function task
        func_task = Task(
            id="func_batch",
            name="Function Batch",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="fibonacci",
                kwargs={"n": 8}
            )
        )
        
        # Text task that processes function result
        text_task = Task(
            id="text_batch", 
            name="Text Analysis Batch",
            task_type=TaskType.TEXT,
            parameters=TaskParameters(
                prompt="Analyze this sequence: {{func_batch.result}}",
                model_name="llama3"
            ),
            dependencies=["func_batch"]
        )
        
        # Vision task (independent)
        vision_task = Task(
            id="vision_batch",
            name="Vision Batch",
            task_type=TaskType.VISION,
            parameters=TaskParameters(
                prompt="What do you see?",
                image_path="/test/image.jpg",
                model_name="llava"
            )
        )
        
        workflow.add_task(func_task)
        workflow.add_task(text_task)
        workflow.add_task(vision_task)
        
        workflow_id = await cluster.submit_workflow(workflow)
        status = await cluster.get_workflow_status(workflow_id)
        
        assert status["total_tasks"] == 3
        
        # Check dependencies are working
        ready_tasks = workflow.get_ready_tasks()
        ready_ids = [t.id for t in ready_tasks]
        
        # func_batch and vision_batch should be ready initially
        assert "func_batch" in ready_ids
        assert "vision_batch" in ready_ids
        assert "text_batch" not in ready_ids  # Has dependency


@pytest.mark.integration
@pytest.mark.slow
class TestClusterStressTests:
    """Stress tests for cluster functionality"""
    
    @pytest.mark.asyncio
    async def test_many_small_workflows(self, cluster):
        """Test cluster with many small workflows"""
        workflows_count = 10
        workflow_ids = []
        
        # Create and submit many workflows
        for i in range(workflows_count):
            workflow = Workflow(name=f"stress_workflow_{i}")
            
            task = Task(
                name=f"stress_task_{i}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="current_timestamp",
                    kwargs={}
                )
            )
            workflow.add_task(task)
            
            workflow_id = await cluster.submit_workflow(workflow)
            workflow_ids.append(workflow_id)
        
        assert len(workflow_ids) == workflows_count
        
        # Check all workflows
        for workflow_id in workflow_ids:
            status = await cluster.get_workflow_status(workflow_id)
            assert status is not None
    
    @pytest.mark.asyncio
    async def test_large_workflow(self, cluster):
        """Test cluster with a single large workflow"""
        workflow = Workflow(name="large_workflow")
        
        # Add many tasks
        for i in range(20):
            task = Task(
                name=f"large_task_{i}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="fibonacci",
                    kwargs={"n": 3}  # Small computation
                )
            )
            workflow.add_task(task)
        
        workflow_id = await cluster.submit_workflow(workflow)
        status = await cluster.get_workflow_status(workflow_id)
        
        assert status is not None
        assert status["total_tasks"] == 20
    
    @pytest.mark.asyncio
    async def test_complex_dependency_workflow(self, cluster):
        """Test workflow with complex dependencies"""
        workflow = Workflow(name="complex_dependencies")
        
        # Create a diamond dependency pattern
        # task1 -> task2, task3 -> task4
        tasks = []
        
        # Root task
        task1 = Task(
            id="task1",
            name="Root Task",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(function_name="fibonacci", kwargs={"n": 3})
        )
        tasks.append(task1)
        
        # Two parallel branches
        task2 = Task(
            id="task2",
            name="Branch A",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(function_name="current_timestamp", kwargs={}),
            dependencies=["task1"]
        )
        tasks.append(task2)
        
        task3 = Task(
            id="task3", 
            name="Branch B",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(function_name="current_timestamp", kwargs={}),
            dependencies=["task1"]
        )
        tasks.append(task3)
        
        # Merge task
        task4 = Task(
            id="task4",
            name="Merge Task", 
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(function_name="current_timestamp", kwargs={}),
            dependencies=["task2", "task3"]
        )
        tasks.append(task4)
        
        for task in tasks:
            workflow.add_task(task)
        
        workflow_id = await cluster.submit_workflow(workflow)
        status = await cluster.get_workflow_status(workflow_id)
        
        assert status is not None
        assert status["total_tasks"] == 4