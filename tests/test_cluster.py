"""
Tests for Gleitzeit Cluster core functionality
"""

import pytest
import asyncio
from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.core.task import TaskType, TaskStatus
from gleitzeit_cluster.core.workflow import WorkflowStatus, WorkflowErrorStrategy
from gleitzeit_cluster.core.node import ExecutorNode, NodeCapabilities, NodeStatus


class TestGleitzeitCluster:
    """Test the main cluster interface"""
    
    @pytest.fixture
    async def cluster(self):
        """Create test cluster"""
        cluster = GleitzeitCluster()
        await cluster.start()
        yield cluster
        await cluster.stop()
    
    async def test_cluster_initialization(self, cluster):
        """Test cluster can be initialized and started"""
        assert cluster._is_started is True
        assert len(cluster._workflows) == 0
        assert len(cluster._nodes) == 0
    
    async def test_create_workflow(self, cluster):
        """Test workflow creation"""
        workflow = cluster.create_workflow("test_workflow", "Test description")
        
        assert workflow.name == "test_workflow"
        assert workflow.description == "Test description"
        assert workflow.status == WorkflowStatus.PENDING
        assert len(workflow.tasks) == 0
        assert workflow.id in cluster._workflows
    
    async def test_add_text_task(self, cluster):
        """Test adding text tasks to workflow"""
        workflow = cluster.create_workflow("test_workflow")
        
        task = workflow.add_text_task(
            name="test_task",
            prompt="Test prompt", 
            model="llama3"
        )
        
        assert task.name == "test_task"
        assert task.task_type == TaskType.TEXT_PROMPT
        assert task.parameters.prompt == "Test prompt"
        assert task.parameters.model_name == "llama3"
        assert task.workflow_id == workflow.id
        assert task.id in workflow.tasks
    
    async def test_add_vision_task(self, cluster):
        """Test adding vision tasks to workflow"""
        workflow = cluster.create_workflow("vision_workflow")
        
        task = workflow.add_vision_task(
            name="analyze_image",
            prompt="Describe this image",
            image_path="/path/to/image.jpg",
            model="llava"
        )
        
        assert task.name == "analyze_image"
        assert task.task_type == TaskType.VISION_TASK
        assert task.parameters.image_path == "/path/to/image.jpg"
        assert task.requirements.requires_gpu is True
    
    async def test_task_dependencies(self, cluster):
        """Test task dependency handling"""
        workflow = cluster.create_workflow("dependency_test")
        
        task1 = workflow.add_text_task("task1", "First task")
        task2 = workflow.add_text_task("task2", "Second task", dependencies=[task1.id])
        
        # Initially, only task1 should be ready
        ready_tasks = workflow.get_ready_tasks()
        assert len(ready_tasks) == 1
        assert ready_tasks[0].id == task1.id
        
        # After completing task1, task2 should be ready
        workflow.mark_task_completed(task1.id, "Result 1")
        ready_tasks = workflow.get_ready_tasks()
        assert len(ready_tasks) == 1
        assert ready_tasks[0].id == task2.id
    
    async def test_workflow_execution(self, cluster):
        """Test basic workflow execution"""
        workflow = cluster.create_workflow("execution_test")
        workflow.add_text_task("task1", "Analyze trends")
        workflow.add_text_task("task2", "Generate summary")
        
        result = await cluster.execute_workflow(workflow)
        
        assert result.status == WorkflowStatus.COMPLETED
        assert result.total_tasks == 2
        assert result.completed_tasks == 2
        assert result.failed_tasks == 0
        assert len(result.results) == 2
    
    async def test_error_handling_stop_strategy(self, cluster):
        """Test stop-on-error strategy"""
        workflow = cluster.create_workflow("error_test") 
        workflow.error_strategy = WorkflowErrorStrategy.STOP_ON_FIRST_ERROR
        
        # Add task that will fail (nonexistent model)
        task1 = workflow.add_text_task("failing_task", "Test", model="nonexistent")
        task2 = workflow.add_text_task("second_task", "Test", dependencies=[task1.id])
        
        # In the mock implementation, we can simulate failure
        workflow.mark_task_failed(task1.id, "Model not found")
        
        assert workflow.is_failed()
        assert task1.id in workflow.failed_tasks
    
    async def test_node_registration(self, cluster):
        """Test executor node registration"""
        node = ExecutorNode(
            name="test-node",
            capabilities=NodeCapabilities(
                supported_task_types={TaskType.TEXT_PROMPT},
                available_models=["llama3"],
                max_concurrent_tasks=2
            )
        )
        
        await cluster.register_node(node)
        
        assert node.id in cluster._nodes
        nodes = await cluster.list_nodes()
        assert len(nodes) == 1
        assert nodes[0]["name"] == "test-node"
    
    async def test_quick_text_analysis(self, cluster):
        """Test convenience method for text analysis"""
        result = await cluster.analyze_text("Explain machine learning")
        
        assert isinstance(result, str)
        assert "Mock result" in result  # From mock implementation
    
    async def test_batch_image_analysis(self, cluster):
        """Test batch image processing"""
        image_paths = ["/path/to/img1.jpg", "/path/to/img2.jpg"]
        
        results = await cluster.batch_analyze_images(
            "Describe the image",
            image_paths
        )
        
        assert len(results) == 2
        assert "/path/to/img1.jpg" in results
        assert "/path/to/img2.jpg" in results


class TestWorkflowLogic:
    """Test workflow logic and state management"""
    
    def test_workflow_progress_calculation(self):
        """Test workflow progress calculation"""
        from gleitzeit_cluster.core.workflow import Workflow
        
        workflow = Workflow(name="progress_test")
        workflow.add_text_task("task1", "Test 1")
        workflow.add_text_task("task2", "Test 2") 
        workflow.add_text_task("task3", "Test 3")
        
        progress = workflow.get_progress()
        assert progress["total_tasks"] == 3
        assert progress["completed_tasks"] == 0
        assert progress["progress_percent"] == 0.0
        
        # Complete one task
        task_id = list(workflow.tasks.keys())[0]
        workflow.mark_task_completed(task_id, "Result")
        
        progress = workflow.get_progress()
        assert progress["completed_tasks"] == 1
        assert progress["progress_percent"] == 33.33 or abs(progress["progress_percent"] - 33.33) < 0.1
    
    def test_task_retry_logic(self):
        """Test task retry logic"""
        from gleitzeit_cluster.core.task import Task, TaskType
        
        task = Task(
            name="retry_test",
            task_type=TaskType.TEXT_PROMPT,
            max_retries=3
        )
        
        assert task.can_retry() is False  # Not failed yet
        
        task.update_status(TaskStatus.FAILED, "Connection error")
        assert task.can_retry() is True
        assert task.retry_count == 0
        
        # Simulate retries
        for i in range(3):
            assert task.can_retry() is True
            task.retry_count += 1
            
        # After max retries
        assert task.can_retry() is False


class TestNodeManagement:
    """Test executor node management"""
    
    def test_node_capabilities(self):
        """Test node capability checking"""
        node = ExecutorNode(
            name="test-node",
            capabilities=NodeCapabilities(
                supported_task_types={TaskType.TEXT_PROMPT, TaskType.VISION_TASK},
                available_models=["llama3", "llava"],
                has_gpu=True,
                max_concurrent_tasks=2
            )
        )
        
        # Should be able to handle text tasks
        assert node.can_execute_task(TaskType.TEXT_PROMPT, ["llama3"]) is True
        
        # Should be able to handle vision tasks
        assert node.can_execute_task(TaskType.VISION_TASK, ["llava"]) is True
        
        # Should not handle unsupported task types
        assert node.can_execute_task(TaskType.HTTP_REQUEST) is False
        
        # Should not handle unavailable models
        assert node.can_execute_task(TaskType.TEXT_PROMPT, ["gpt-4"]) is False
    
    def test_node_load_scoring(self):
        """Test node load calculation"""
        from gleitzeit_cluster.core.node import NodeResources
        
        node = ExecutorNode(
            name="load-test",
            capabilities=NodeCapabilities(max_concurrent_tasks=4)
        )
        
        # Low load
        node.update_resources(NodeResources(
            cpu_usage_percent=25.0,
            memory_usage_percent=30.0,
            active_tasks=1
        ))
        
        load_score = node.get_load_score()
        assert 0.0 <= load_score <= 1.0
        assert load_score < 0.5  # Should be low load
        
        # High load
        node.update_resources(NodeResources(
            cpu_usage_percent=90.0,
            memory_usage_percent=85.0,
            active_tasks=4  # At capacity
        ))
        
        load_score = node.get_load_score()
        assert load_score > 0.8  # Should be high load


if __name__ == "__main__":
    pytest.main([__file__])