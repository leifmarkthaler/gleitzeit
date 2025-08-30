"""
Test advanced features in Gleitzeit Client
"""
import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from gleitzeit.client import GleitzeitClient, ClientMode


@pytest.fixture
async def client():
    """Create a test client with mocked adapter"""
    client = GleitzeitClient(mode=ClientMode.API, api_host="localhost", api_port=8000)
    
    # Mock the adapter
    mock_adapter = AsyncMock()
    client._adapter = mock_adapter
    client._initialized = True
    
    return client


class TestAdvancedWorkflowFeatures:
    """Test advanced workflow operations"""
    
    @pytest.mark.asyncio
    async def test_get_workflow_timeline(self, client):
        """Test getting workflow execution timeline"""
        workflow_id = "wf-123"
        expected_timeline = {
            "workflow_id": workflow_id,
            "start_time": "2025-01-01T10:00:00",
            "end_time": "2025-01-01T10:30:00",
            "tasks": [
                {"task_id": "t1", "start": "10:00:00", "end": "10:05:00", "duration": 300},
                {"task_id": "t2", "start": "10:05:00", "end": "10:15:00", "duration": 600}
            ]
        }
        
        client._adapter.get_workflow_timeline.return_value = expected_timeline
        
        result = await client.get_workflow_timeline(workflow_id)
        
        assert result == expected_timeline
        client._adapter.get_workflow_timeline.assert_called_once_with(workflow_id)
    
    @pytest.mark.asyncio
    async def test_get_workflow_dependencies(self, client):
        """Test getting workflow dependency graph"""
        workflow_id = "wf-123"
        expected_deps = {
            "workflow_id": workflow_id,
            "nodes": ["task1", "task2", "task3"],
            "edges": [
                {"from": "task1", "to": "task2"},
                {"from": "task1", "to": "task3"}
            ]
        }
        
        client._adapter.get_workflow_dependencies.return_value = expected_deps
        
        result = await client.get_workflow_dependencies(workflow_id)
        
        assert result == expected_deps
        client._adapter.get_workflow_dependencies.assert_called_once_with(workflow_id)
    
    @pytest.mark.asyncio
    async def test_get_workflow_critical_path(self, client):
        """Test getting workflow critical path"""
        workflow_id = "wf-123"
        expected_path = {
            "workflow_id": workflow_id,
            "path": ["task1", "task2", "task5"],
            "total_duration": 1800,
            "bottleneck": "task2"
        }
        
        client._adapter.get_workflow_critical_path.return_value = expected_path
        
        result = await client.get_workflow_critical_path(workflow_id)
        
        assert result == expected_path
        client._adapter.get_workflow_critical_path.assert_called_once_with(workflow_id)
    
    @pytest.mark.asyncio
    async def test_export_workflow(self, client):
        """Test exporting workflow definition"""
        workflow_id = "wf-123"
        expected_export = """
name: Test Workflow
tasks:
  - name: Task 1
    protocol: python/v1
"""
        
        client._adapter.export_workflow.return_value = expected_export
        
        result = await client.export_workflow(workflow_id, format="yaml")
        
        assert result == expected_export
        client._adapter.export_workflow.assert_called_once_with(workflow_id, "yaml")
    
    @pytest.mark.asyncio
    async def test_retry_workflow(self, client):
        """Test retrying a failed workflow"""
        workflow_id = "wf-123"
        expected_result = {
            "original_workflow_id": workflow_id,
            "new_workflow_id": "wf-456",
            "status": "submitted",
            "retry_from": None
        }
        
        client._adapter.retry_workflow.return_value = expected_result
        
        result = await client.retry_workflow(workflow_id)
        
        assert result == expected_result
        client._adapter.retry_workflow.assert_called_once_with(workflow_id, None)
    
    @pytest.mark.asyncio
    async def test_retry_workflow_from_task(self, client):
        """Test retrying workflow from specific task"""
        workflow_id = "wf-123"
        from_task = "task-456"
        expected_result = {
            "original_workflow_id": workflow_id,
            "new_workflow_id": "wf-789",
            "status": "submitted",
            "retry_from": from_task
        }
        
        client._adapter.retry_workflow.return_value = expected_result
        
        result = await client.retry_workflow(workflow_id, from_task)
        
        assert result == expected_result
        client._adapter.retry_workflow.assert_called_once_with(workflow_id, from_task)
    
    @pytest.mark.asyncio
    async def test_bulk_cancel_workflows(self, client):
        """Test bulk workflow cancellation"""
        workflow_ids = ["wf-1", "wf-2", "wf-3"]
        expected_result = {
            "cancelled": 2,
            "failed": 1,
            "results": [
                {"workflow_id": "wf-1", "status": "cancelled"},
                {"workflow_id": "wf-2", "status": "cancelled"},
                {"workflow_id": "wf-3", "error": "Already completed"}
            ]
        }
        
        client._adapter.bulk_cancel_workflows.return_value = expected_result
        
        result = await client.bulk_cancel_workflows(workflow_ids)
        
        assert result == expected_result
        client._adapter.bulk_cancel_workflows.assert_called_once_with(workflow_ids)
    
    @pytest.mark.asyncio
    async def test_bulk_delete_workflows(self, client):
        """Test bulk workflow deletion"""
        workflow_ids = ["wf-1", "wf-2", "wf-3"]
        expected_result = {
            "deleted": 3,
            "failed": 0,
            "results": [
                {"workflow_id": "wf-1", "deleted": True},
                {"workflow_id": "wf-2", "deleted": True},
                {"workflow_id": "wf-3", "deleted": True}
            ]
        }
        
        client._adapter.bulk_delete_workflows.return_value = expected_result
        
        result = await client.bulk_delete_workflows(workflow_ids)
        
        assert result == expected_result
        client._adapter.bulk_delete_workflows.assert_called_once_with(workflow_ids)
    
    @pytest.mark.asyncio
    async def test_get_workflow_templates(self, client):
        """Test getting workflow templates"""
        expected_templates = [
            {"id": "tmpl-1", "name": "Data Processing", "category": "etl"},
            {"id": "tmpl-2", "name": "ML Training", "category": "ml"}
        ]
        
        client._adapter.get_workflow_templates.return_value = expected_templates
        
        result = await client.get_workflow_templates(category="ml")
        
        assert result == expected_templates
        client._adapter.get_workflow_templates.assert_called_once_with("ml")


class TestAdvancedTaskFeatures:
    """Test advanced task operations"""
    
    @pytest.mark.asyncio
    async def test_get_queue_status(self, client):
        """Test getting task queue status"""
        expected_status = {
            "queues": {
                "default": {"size": 10, "processing": 3},
                "priority": {"size": 5, "processing": 2}
            },
            "total_pending": 15,
            "total_processing": 5
        }
        
        client._adapter.get_queue_status.return_value = expected_status
        
        result = await client.get_queue_status()
        
        assert result == expected_status
        client._adapter.get_queue_status.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_bulk_cancel_tasks(self, client):
        """Test bulk task cancellation"""
        task_ids = ["task-1", "task-2", "task-3"]
        expected_result = {
            "cancelled": 2,
            "failed": 1,
            "results": [
                {"task_id": "task-1", "status": "cancelled"},
                {"task_id": "task-2", "status": "cancelled"},
                {"task_id": "task-3", "error": "Already completed"}
            ]
        }
        
        client._adapter.bulk_cancel_tasks.return_value = expected_result
        
        result = await client.bulk_cancel_tasks(task_ids)
        
        assert result == expected_result
        client._adapter.bulk_cancel_tasks.assert_called_once_with(task_ids)
    
    @pytest.mark.asyncio
    async def test_bulk_retry_tasks(self, client):
        """Test bulk task retry"""
        task_ids = ["task-1", "task-2", "task-3"]
        expected_result = {
            "retried": 3,
            "failed": 0,
            "results": [
                {"task_id": "task-1", "new_task_id": "task-10"},
                {"task_id": "task-2", "new_task_id": "task-11"},
                {"task_id": "task-3", "new_task_id": "task-12"}
            ]
        }
        
        client._adapter.bulk_retry_tasks.return_value = expected_result
        
        result = await client.bulk_retry_tasks(task_ids)
        
        assert result == expected_result
        client._adapter.bulk_retry_tasks.assert_called_once_with(task_ids)
    
    @pytest.mark.asyncio
    async def test_get_bulk_task_status(self, client):
        """Test getting status of multiple tasks"""
        task_ids = ["task-1", "task-2", "task-3"]
        expected_status = {
            "task-1": "executing",
            "task-2": "completed",
            "task-3": "failed"
        }
        
        client._adapter.get_bulk_task_status.return_value = expected_status
        
        result = await client.get_bulk_task_status(task_ids)
        
        assert result == expected_status
        client._adapter.get_bulk_task_status.assert_called_once_with(task_ids)


class TestMonitoringFeatures:
    """Test monitoring and statistics operations"""
    
    @pytest.mark.asyncio
    async def test_get_detailed_task_statistics(self, client):
        """Test getting detailed task statistics"""
        start_time = datetime(2025, 1, 1)
        end_time = datetime(2025, 1, 2)
        expected_stats = {
            "total_tasks": 1000,
            "completed": 950,
            "failed": 30,
            "cancelled": 20,
            "average_duration": 45.5,
            "success_rate": 95.0
        }
        
        client._adapter.get_detailed_task_statistics.return_value = expected_stats
        
        result = await client.get_detailed_task_statistics(start_time, end_time)
        
        assert result == expected_stats
        client._adapter.get_detailed_task_statistics.assert_called_once_with(start_time, end_time)
    
    @pytest.mark.asyncio
    async def test_get_detailed_workflow_statistics(self, client):
        """Test getting detailed workflow statistics"""
        expected_stats = {
            "total_workflows": 100,
            "completed": 85,
            "failed": 10,
            "running": 5,
            "average_duration": 300.0,
            "success_rate": 85.0
        }
        
        client._adapter.get_detailed_workflow_statistics.return_value = expected_stats
        
        result = await client.get_detailed_workflow_statistics()
        
        assert result == expected_stats
        client._adapter.get_detailed_workflow_statistics.assert_called_once_with(None, None)
    
    @pytest.mark.asyncio
    async def test_get_system_statistics(self, client):
        """Test getting system statistics"""
        expected_stats = {
            "uptime": 86400,
            "tasks_per_hour": 150.0,
            "workflows_per_hour": 10.0,
            "active_workers": 5,
            "queue_depth": 25
        }
        
        client._adapter.get_system_statistics.return_value = expected_stats
        
        result = await client.get_system_statistics()
        
        assert result == expected_stats
        client._adapter.get_system_statistics.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_resource_limits(self, client):
        """Test getting resource limits"""
        expected_limits = {
            "max_workers": 10,
            "max_memory": "8GB",
            "max_cpu": "4 cores",
            "max_queue_size": 1000
        }
        
        client._adapter.get_resource_limits.return_value = expected_limits
        
        result = await client.get_resource_limits()
        
        assert result == expected_limits
        client._adapter.get_resource_limits.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_resource_usage(self, client):
        """Test getting current resource usage"""
        expected_usage = {
            "cpu_percent": 45.5,
            "memory_used": "3.2GB",
            "memory_percent": 40.0,
            "disk_used": "10GB",
            "network_io": {"sent": 1000000, "received": 2000000}
        }
        
        client._adapter.get_resource_usage.return_value = expected_usage
        
        result = await client.get_resource_usage()
        
        assert result == expected_usage
        client._adapter.get_resource_usage.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_event_stream(self, client):
        """Test getting event stream"""
        expected_events = {
            "events": [
                {"type": "task_started", "timestamp": "2025-01-01T10:00:00"},
                {"type": "task_completed", "timestamp": "2025-01-01T10:05:00"}
            ],
            "stream_id": "stream-123"
        }
        
        client._adapter.get_event_stream.return_value = expected_events
        
        result = await client.get_event_stream(filter="task_*", follow=True)
        
        assert result == expected_events
        client._adapter.get_event_stream.assert_called_once_with("task_*", True)
    
    @pytest.mark.asyncio
    async def test_get_provider_details(self, client):
        """Test getting provider details"""
        provider_id = "provider-123"
        expected_details = {
            "id": provider_id,
            "name": "Python Provider",
            "version": "1.0.0",
            "capabilities": ["execute", "analyze"],
            "status": "active"
        }
        
        client._adapter.get_provider_details.return_value = expected_details
        
        result = await client.get_provider_details(provider_id)
        
        assert result == expected_details
        client._adapter.get_provider_details.assert_called_once_with(provider_id)
    
    @pytest.mark.asyncio
    async def test_check_provider_health(self, client):
        """Test checking provider health"""
        provider_id = "provider-123"
        expected_health = {
            "provider_id": provider_id,
            "status": "healthy",
            "response_time": 0.5,
            "last_check": "2025-01-01T10:00:00"
        }
        
        client._adapter.check_provider_health.return_value = expected_health
        
        result = await client.check_provider_health(provider_id)
        
        assert result == expected_health
        client._adapter.check_provider_health.assert_called_once_with(provider_id)
    
    @pytest.mark.asyncio
    async def test_get_performance_metrics(self, client):
        """Test getting performance metrics"""
        expected_metrics = {
            "component": "api",
            "avg_latency": 50.5,
            "p95_latency": 100.0,
            "p99_latency": 200.0,
            "requests_per_second": 100.0,
            "error_rate": 0.01
        }
        
        client._adapter.get_performance_metrics.return_value = expected_metrics
        
        result = await client.get_performance_metrics(component="api")
        
        assert result == expected_metrics
        client._adapter.get_performance_metrics.assert_called_once_with("api", None, None)
    
    @pytest.mark.asyncio
    async def test_get_queue_metrics(self, client):
        """Test getting queue metrics"""
        expected_metrics = {
            "queues": {
                "default": {
                    "size": 10,
                    "processing_rate": 5.0,
                    "avg_wait_time": 2.5
                },
                "priority": {
                    "size": 3,
                    "processing_rate": 10.0,
                    "avg_wait_time": 0.5
                }
            }
        }
        
        client._adapter.get_queue_metrics.return_value = expected_metrics
        
        result = await client.get_queue_metrics()
        
        assert result == expected_metrics
        client._adapter.get_queue_metrics.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])