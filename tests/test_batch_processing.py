"""
Tests for Batch Processing functionality
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.core.task import Task, TaskType, TaskParameters
from gleitzeit_cluster.core.workflow import Workflow


class TestBatchProcessing:
    """Test basic batch processing functionality"""
    
    @pytest.mark.asyncio
    async def test_async_batch_process_function(self, cluster):
        """Test async_batch_process function execution"""
        workflow = Workflow(name="batch_test")
        
        batch_task = Task(
            name="Process Batch Items",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="async_batch_process",
                kwargs={
                    "items": ["item1", "item2", "item3"],
                    "delay": 0.1  # Fast for testing
                }
            )
        )
        workflow.add_task(batch_task)
        
        workflow_id = await cluster.submit_workflow(workflow)
        assert workflow_id is not None
        
        # Check workflow structure
        status = await cluster.get_workflow_status(workflow_id)
        assert status["total_tasks"] == 1
        assert status["workflow_id"] == workflow_id
    
    @pytest.mark.asyncio
    async def test_batch_text_analysis_workflow(self, cluster):
        """Test batch text analysis workflow structure"""
        workflow = Workflow(name="batch_text_analysis")
        
        texts = [
            "The quick brown fox",
            "Machine learning is powerful",
            "Climate change requires action"
        ]
        
        # Create analysis tasks for each text
        for i, text in enumerate(texts):
            # Word count task
            word_task = Task(
                id=f"words_{i}",
                name=f"Count Words - Text {i+1}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="count_words",
                    kwargs={"text": text}
                )
            )
            
            # Keywords task
            keywords_task = Task(
                id=f"keywords_{i}",
                name=f"Keywords - Text {i+1}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="extract_keywords",
                    kwargs={
                        "text": text,
                        "max_keywords": 3
                    }
                )
            )
            
            workflow.add_task(word_task)
            workflow.add_task(keywords_task)
        
        # Summary task with dependencies
        summary_task = Task(
            id="summary",
            name="Batch Summary",
            task_type=TaskType.TEXT,
            parameters=TaskParameters(
                prompt="Summarize results: {{words_0.result}}, {{keywords_0.result}}",
                model_name="llama3"
            ),
            dependencies=[f"words_{i}" for i in range(3)] + [f"keywords_{i}" for i in range(3)]
        )
        workflow.add_task(summary_task)
        
        # Verify workflow structure
        assert len(workflow.tasks) == 7  # 3 texts * 2 tasks + 1 summary
        
        # Check dependencies
        summary_deps = workflow.tasks["summary"].dependencies
        assert len(summary_deps) == 6  # 3 words + 3 keywords tasks
        
        # Submit workflow
        workflow_id = await cluster.submit_workflow(workflow)
        assert workflow_id is not None
    
    @pytest.mark.asyncio
    async def test_batch_data_processing_workflow(self, cluster):
        """Test batch data processing workflow"""
        workflow = Workflow(name="batch_data_processing")
        
        datasets = [
            [1, 2, 3, 4, 5],
            [10, 20, 30, 40, 50],
            [100, 200, 300, 400, 500]
        ]
        
        # Create analysis tasks for each dataset
        for i, dataset in enumerate(datasets):
            analyze_task = Task(
                id=f"analyze_{i}",
                name=f"Analyze Dataset {i+1}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="analyze_numbers",
                    kwargs={"numbers": dataset}
                )
            )
            workflow.add_task(analyze_task)
        
        # Aggregate task
        all_data = [item for dataset in datasets for item in dataset]
        aggregate_task = Task(
            id="aggregate",
            name="Aggregate Results",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="aggregate",
                kwargs={
                    "data": all_data,
                    "operation": "statistics"
                }
            )
        )
        workflow.add_task(aggregate_task)
        
        # Submit workflow
        workflow_id = await cluster.submit_workflow(workflow)
        assert workflow_id is not None
        
        status = await cluster.get_workflow_status(workflow_id)
        assert status["total_tasks"] == 4  # 3 analysis + 1 aggregate


class TestBatchConvenienceMethods:
    """Test batch processing convenience methods"""
    
    @pytest.mark.asyncio
    async def test_batch_analyze_images_method(self, cluster, mock_ollama):
        """Test batch image analysis convenience method"""
        image_paths = [
            "/path/to/image1.jpg",
            "/path/to/image2.jpg", 
            "/path/to/image3.jpg"
        ]
        
        with patch.object(cluster, 'submit_workflow') as mock_submit, \
             patch.object(cluster, 'get_workflow_status') as mock_status:
            
            mock_submit.return_value = "batch_image_workflow_id"
            mock_status.return_value = {
                "status": "completed",
                "task_results": {
                    "image_0": "Description of image 1",
                    "image_1": "Description of image 2", 
                    "image_2": "Description of image 3"
                }
            }
            
            results = await cluster.batch_analyze_images(
                "Describe the image",
                image_paths
            )
            
            assert results is not None
            mock_submit.assert_called_once()
            
            # Verify workflow was created with correct structure
            workflow_arg = mock_submit.call_args[0][0]
            assert isinstance(workflow_arg, Workflow)
            assert len(workflow_arg.tasks) == len(image_paths)
    
    @pytest.mark.asyncio
    async def test_batch_text_processing_method(self, cluster):
        """Test batch text processing using workflow creation"""
        texts = [
            "First text to analyze",
            "Second text to analyze",
            "Third text to analyze"
        ]
        
        # Create batch text processing workflow manually (since no direct method exists)
        workflow = Workflow(name="batch_text_processing")
        
        for i, text in enumerate(texts):
            task = Task(
                id=f"text_{i}",
                name=f"Process Text {i+1}",
                task_type=TaskType.TEXT,
                parameters=TaskParameters(
                    prompt=f"Analyze: {text}",
                    model_name="llama3"
                )
            )
            workflow.add_task(task)
        
        workflow_id = await cluster.submit_workflow(workflow)
        assert workflow_id is not None
        
        status = await cluster.get_workflow_status(workflow_id)
        assert status["total_tasks"] == len(texts)


class TestBatchFunctionRegistry:
    """Test batch processing functions in function registry"""
    
    def test_async_batch_process_function_exists(self, cluster):
        """Test that async_batch_process function is available"""
        if hasattr(cluster, 'function_registry'):
            functions = cluster.function_registry.list_functions()
            assert "async_batch_process" in functions
            
            func_info = cluster.function_registry.get_function_info("async_batch_process")
            if func_info:
                assert "batch" in func_info.get("description", "").lower()
    
    def test_batch_related_functions(self, cluster):
        """Test availability of batch-related functions"""
        if hasattr(cluster, 'function_registry'):
            functions = cluster.function_registry.list_functions()
            
            # Functions commonly used in batch processing
            expected_functions = [
                "analyze_numbers",
                "count_words", 
                "extract_keywords",
                "text_stats",
                "aggregate"
            ]
            
            available_functions = [f for f in expected_functions if f in functions]
            assert len(available_functions) > 0  # At least some batch functions should exist


@pytest.mark.integration
class TestBatchProcessingIntegration:
    """Integration tests for batch processing workflows"""
    
    @pytest.mark.asyncio
    async def test_simple_batch_workflow_execution(self, cluster):
        """Test simple batch workflow execution"""
        workflow = Workflow(name="simple_batch")
        
        # Create parallel tasks
        for i in range(3):
            task = Task(
                id=f"batch_task_{i}",
                name=f"Batch Task {i+1}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="current_timestamp",
                    kwargs={}
                )
            )
            workflow.add_task(task)
        
        workflow_id = await cluster.submit_workflow(workflow)
        
        # All tasks should be ready initially (no dependencies)
        ready_tasks = workflow.get_ready_tasks()
        assert len(ready_tasks) == 3
        
        status = await cluster.get_workflow_status(workflow_id)
        assert status["total_tasks"] == 3
    
    @pytest.mark.asyncio
    async def test_batch_with_dependencies(self, cluster):
        """Test batch processing with task dependencies"""
        workflow = Workflow(name="batch_with_deps")
        
        # Parallel processing stage
        stage1_tasks = []
        for i in range(2):
            task = Task(
                id=f"stage1_{i}",
                name=f"Stage 1 Task {i+1}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="fibonacci",
                    kwargs={"n": 5}
                )
            )
            workflow.add_task(task)
            stage1_tasks.append(f"stage1_{i}")
        
        # Aggregation stage (depends on all stage 1 tasks)
        aggregate_task = Task(
            id="aggregate",
            name="Aggregate Results",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="current_timestamp",
                kwargs={}
            ),
            dependencies=stage1_tasks
        )
        workflow.add_task(aggregate_task)
        
        # Initially, only stage 1 tasks should be ready
        ready_tasks = workflow.get_ready_tasks()
        assert len(ready_tasks) == 2  # Both stage 1 tasks
        
        # After completing stage 1, aggregate should be ready
        workflow.completed_tasks.add("stage1_0")
        workflow.completed_tasks.add("stage1_1")
        ready_tasks = workflow.get_ready_tasks()
        assert len(ready_tasks) == 1  # Aggregate task
        assert ready_tasks[0].id == "aggregate"
    
    @pytest.mark.asyncio
    async def test_large_batch_workflow(self, cluster):
        """Test workflow with many batch tasks"""
        workflow = Workflow(name="large_batch")
        
        # Create 10 parallel tasks
        for i in range(10):
            task = Task(
                id=f"large_batch_{i}",
                name=f"Large Batch Task {i+1}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="fibonacci",
                    kwargs={"n": 3}  # Small computation
                )
            )
            workflow.add_task(task)
        
        workflow_id = await cluster.submit_workflow(workflow)
        status = await cluster.get_workflow_status(workflow_id)
        
        assert status["total_tasks"] == 10
        assert len(workflow.get_ready_tasks()) == 10  # All tasks ready


@pytest.mark.integration
class TestBatchProcessingErrors:
    """Test error handling in batch processing"""
    
    @pytest.mark.asyncio
    async def test_batch_with_failing_tasks(self, cluster):
        """Test batch processing with some failing tasks"""
        workflow = Workflow(name="batch_with_errors")
        
        # Mix of valid and invalid tasks
        valid_task = Task(
            id="valid_task",
            name="Valid Task",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="current_timestamp",
                kwargs={}
            )
        )
        
        invalid_task = Task(
            id="invalid_task", 
            name="Invalid Task",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="non_existent_function",
                kwargs={}
            )
        )
        
        workflow.add_task(valid_task)
        workflow.add_task(invalid_task)
        
        workflow_id = await cluster.submit_workflow(workflow)
        assert workflow_id is not None
        
        status = await cluster.get_workflow_status(workflow_id)
        assert status["total_tasks"] == 2
    
    @pytest.mark.asyncio
    async def test_batch_timeout_handling(self, cluster):
        """Test batch processing with potential timeouts"""
        workflow = Workflow(name="batch_timeout_test")
        
        # Task with long duration (but short for testing)
        timeout_task = Task(
            name="Potentially Long Task",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="async_timer",
                kwargs={"duration": 0.5}  # Short for testing
            )
        )
        workflow.add_task(timeout_task)
        
        workflow_id = await cluster.submit_workflow(workflow)
        assert workflow_id is not None


@pytest.mark.slow
class TestBatchPerformance:
    """Performance tests for batch processing"""
    
    @pytest.mark.asyncio
    async def test_concurrent_batch_workflows(self, cluster):
        """Test multiple concurrent batch workflows"""
        workflows = []
        
        # Create multiple batch workflows
        for batch_id in range(3):
            workflow = Workflow(name=f"concurrent_batch_{batch_id}")
            
            for task_id in range(2):  # Small batches for testing
                task = Task(
                    id=f"batch_{batch_id}_task_{task_id}",
                    name=f"Batch {batch_id} Task {task_id}",
                    task_type=TaskType.FUNCTION,
                    parameters=TaskParameters(
                        function_name="current_timestamp",
                        kwargs={}
                    )
                )
                workflow.add_task(task)
            
            workflows.append(workflow)
        
        # Submit all workflows concurrently
        workflow_ids = []
        for workflow in workflows:
            workflow_id = await cluster.submit_workflow(workflow)
            workflow_ids.append(workflow_id)
        
        # All should be submitted successfully
        assert len(workflow_ids) == 3
        assert len(set(workflow_ids)) == 3  # All unique
        
        # Check status of all workflows
        for workflow_id in workflow_ids:
            status = await cluster.get_workflow_status(workflow_id)
            assert status is not None
            assert status["total_tasks"] == 2


if __name__ == "__main__":
    pytest.main([__file__])