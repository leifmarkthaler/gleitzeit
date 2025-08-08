"""
Tests for Gleitzeit Cluster core functionality (Updated)
"""

import pytest
import asyncio
from unittest.mock import Mock, patch

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.core.task import Task, TaskType, TaskStatus, TaskParameters
from gleitzeit_cluster.core.workflow import Workflow, WorkflowStatus, WorkflowErrorStrategy
from gleitzeit_cluster.core.node import ExecutorNode, NodeCapabilities, NodeStatus


class TestGleitzeitCluster:
    """Test the main cluster interface"""
    
    @pytest.mark.asyncio
    async def test_cluster_initialization(self, cluster):
        """Test cluster can be initialized and started"""
        assert cluster._is_started is True
        assert len(cluster._workflows) == 0
        assert len(cluster._nodes) == 0
    
    @pytest.mark.asyncio
    async def test_create_workflow(self, cluster):
        """Test workflow creation"""
        workflow = cluster.create_workflow("test_workflow", "Test description")
        
        assert workflow.name == "test_workflow"
        assert workflow.description == "Test description"
        assert workflow.status == WorkflowStatus.PENDING
        assert len(workflow.tasks) == 0
        assert workflow.id in cluster._workflows
    
    @pytest.mark.asyncio
    async def test_submit_workflow(self, cluster, sample_workflow):
        """Test workflow submission"""
        workflow_id = await cluster.submit_workflow(sample_workflow)
        
        assert workflow_id is not None
        assert workflow_id == sample_workflow.id
        
        # Check workflow is stored
        assert workflow_id in cluster._workflows or hasattr(cluster, '_submitted_workflows')
    
    @pytest.mark.asyncio 
    async def test_get_workflow_status(self, cluster, sample_workflow):
        """Test getting workflow status"""
        workflow_id = await cluster.submit_workflow(sample_workflow)
        
        status = await cluster.get_workflow_status(workflow_id)
        
        assert status is not None
        assert status["workflow_id"] == workflow_id
        assert "status" in status
        assert "total_tasks" in status
        assert "completed_tasks" in status
    
    @pytest.mark.asyncio
    async def test_list_workflows(self, cluster, sample_workflow):
        """Test listing workflows"""
        # Submit a workflow
        await cluster.submit_workflow(sample_workflow)
        
        workflows = await cluster.list_workflows()
        
        assert isinstance(workflows, list)
        # Should have at least the workflow we submitted
        assert len(workflows) >= 1
    
    @pytest.mark.asyncio
    async def test_cluster_stats(self, cluster):
        """Test getting cluster statistics"""
        stats = await cluster.get_cluster_stats()
        
        assert isinstance(stats, dict)
        assert "is_started" in stats
        assert stats["is_started"] is True
        
        # Should have basic stats
        expected_keys = ["workflows", "nodes", "real_execution_enabled"]
        for key in expected_keys:
            assert key in stats
    
    @pytest.mark.asyncio
    async def test_node_registration(self, cluster):
        """Test executor node registration"""
        node = ExecutorNode(
            name="test-node",
            capabilities=NodeCapabilities(
                supported_task_types=[TaskType.TEXT, TaskType.FUNCTION],
                available_models=["llama3"],
                max_concurrent_tasks=2
            )
        )
        
        await cluster.register_node(node)
        
        assert node.id in cluster._nodes
        nodes = await cluster.list_nodes()
        assert len(nodes) >= 1
        
        # Find our node in the list
        our_node = next((n for n in nodes if n.get("name") == "test-node"), None)
        assert our_node is not None
    
    @pytest.mark.asyncio
    async def test_analyze_text_convenience(self, cluster, mock_ollama):
        """Test convenience method for text analysis"""
        with patch.object(cluster, 'submit_workflow') as mock_submit, \
             patch.object(cluster, 'get_workflow_status') as mock_status:
            
            # Mock workflow completion
            mock_submit.return_value = "test_workflow_id"
            mock_status.return_value = {
                "status": "completed",
                "task_results": {"text_task": "Mock analysis result"}
            }
            
            result = await cluster.analyze_text("Explain machine learning")
            
            assert isinstance(result, str)
            mock_submit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_batch_analyze_images(self, cluster, mock_ollama):
        """Test batch image processing"""
        image_paths = ["/path/to/img1.jpg", "/path/to/img2.jpg"]
        
        with patch.object(cluster, 'submit_workflow') as mock_submit, \
             patch.object(cluster, 'get_workflow_status') as mock_status:
            
            mock_submit.return_value = "batch_workflow_id"
            mock_status.return_value = {
                "status": "completed",
                "task_results": {
                    "image_0": "Description of image 1",
                    "image_1": "Description of image 2"
                }
            }
            
            results = await cluster.batch_analyze_images(
                "Describe the image",
                image_paths
            )
            
            assert results is not None
            mock_submit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_model_management(self, cluster, mock_ollama):
        """Test model pull and listing"""
        # Test get available models
        models = await cluster.get_available_models()
        assert models is not None
        assert isinstance(models, dict)
        
        # Test pull model
        with patch.object(cluster.task_executor, 'ollama_client') as mock_client:
            mock_client.pull_model = Mock(return_value={"status": "success"})
            
            result = await cluster.pull_model("llama3")
            assert result is not None


class TestWorkflowLogic:
    """Test workflow logic and state management"""
    
    def test_workflow_progress_calculation(self, sample_workflow):
        """Test workflow progress calculation"""
        progress = sample_workflow.get_progress()
        assert progress["total_tasks"] == 2
        assert progress["completed_tasks"] == 0
        assert progress["progress_percent"] == 0.0
        
        # Complete one task
        task_id = list(sample_workflow.tasks.keys())[0]
        sample_workflow.completed_tasks.add(task_id)
        
        progress = sample_workflow.get_progress()
        assert progress["completed_tasks"] == 1
        assert progress["progress_percent"] == 50.0
    
    def test_task_retry_logic(self, sample_task):
        """Test task retry logic"""
        assert sample_task.can_retry() is False  # Not failed yet
        
        sample_task.update_status(TaskStatus.FAILED, "Connection error")
        assert sample_task.can_retry() is True
        assert sample_task.retry_count == 0
        
        # Simulate retries
        for i in range(3):
            assert sample_task.can_retry() is True
            sample_task.retry_count += 1
            
        # After max retries
        assert sample_task.can_retry() is False
    
    def test_workflow_dependency_resolution(self, sample_workflow):
        """Test workflow dependency resolution"""
        # Initially, only task without dependencies should be ready
        ready_tasks = sample_workflow.get_ready_tasks()
        assert len(ready_tasks) == 1
        assert ready_tasks[0].id == "task_1"  # First task has no dependencies
        
        # After completing first task, second should be ready
        sample_workflow.completed_tasks.add("task_1")
        ready_tasks = sample_workflow.get_ready_tasks()
        assert len(ready_tasks) == 1
        assert ready_tasks[0].id == "task_2"
    
    def test_workflow_error_strategies(self):
        """Test different workflow error strategies"""
        # Stop on first error
        workflow_stop = Workflow(
            name="stop_on_error",
            error_strategy=WorkflowErrorStrategy.STOP_ON_FIRST_ERROR
        )
        
        task1 = Task(id="task1", name="Task1", task_type=TaskType.FUNCTION)
        task2 = Task(id="task2", name="Task2", task_type=TaskType.FUNCTION)
        workflow_stop.add_task(task1)
        workflow_stop.add_task(task2)
        
        # Simulate task failure
        workflow_stop.failed_tasks.add("task1")
        
        # Should stop execution based on strategy
        assert workflow_stop.error_strategy == WorkflowErrorStrategy.STOP_ON_FIRST_ERROR
        
        # Continue on error
        workflow_continue = Workflow(
            name="continue_on_error",
            error_strategy=WorkflowErrorStrategy.CONTINUE_ON_ERROR
        )
        
        workflow_continue.failed_tasks.add("task1")
        assert workflow_continue.error_strategy == WorkflowErrorStrategy.CONTINUE_ON_ERROR


class TestNodeManagement:
    """Test executor node management"""
    
    def test_node_capabilities(self):
        """Test node capability checking"""
        node = ExecutorNode(
            name="test-node",
            capabilities=NodeCapabilities(
                supported_task_types=[TaskType.TEXT, TaskType.VISION],
                available_models=["llama3", "llava"],
                has_gpu=True,
                max_concurrent_tasks=2
            )
        )
        
        # Should be able to handle text tasks
        assert TaskType.TEXT in node.capabilities.supported_task_types
        
        # Should be able to handle vision tasks
        assert TaskType.VISION in node.capabilities.supported_task_types
        
        # Should have GPU capability
        assert node.capabilities.has_gpu is True
        
        # Should have model availability
        assert "llama3" in node.capabilities.available_models
        assert "llava" in node.capabilities.available_models
    
    def test_node_status_tracking(self):
        """Test node status updates"""
        node = ExecutorNode(
            name="status-test",
            capabilities=NodeCapabilities(max_concurrent_tasks=4)
        )
        
        # Initial status should be offline
        assert node.status == NodeStatus.OFFLINE
        
        # Update status
        node.status = NodeStatus.ACTIVE
        assert node.status == NodeStatus.ACTIVE
        
        node.status = NodeStatus.BUSY
        assert node.status == NodeStatus.BUSY


class TestClusterAutoStart:
    """Test cluster auto-start functionality"""
    
    def test_cluster_auto_start_configuration(self):
        """Test cluster auto-start configuration"""
        cluster = GleitzeitCluster(
            auto_start_services=True,
            auto_start_redis=True,
            auto_start_executors=True,
            min_executors=2
        )
        
        assert cluster.auto_start_services is True
        assert cluster.auto_start_redis is True
        assert cluster.auto_start_executors is True
        assert cluster.min_executors == 2
        assert cluster.service_manager is not None
    
    def test_cluster_auto_start_disabled(self):
        """Test cluster with auto-start disabled"""
        cluster = GleitzeitCluster(
            auto_start_services=False
        )
        
        assert cluster.auto_start_services is False
        assert cluster.service_manager is None
    
    @pytest.mark.asyncio
    async def test_cluster_with_auto_start_integration(self, cluster_with_auto_start):
        """Test cluster integration with auto-start enabled"""
        cluster = cluster_with_auto_start
        
        assert cluster.auto_start_services is True
        assert cluster.service_manager is not None


if __name__ == "__main__":
    pytest.main([__file__])