"""
Test extended Gleitzeit Client functionality - Missing coverage
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Task, Workflow


@pytest.fixture
async def client():
    """Create a test client with mocked adapter"""
    client = GleitzeitClient(mode="native", api_host="localhost", api_port=8080)
    
    # Mock the adapter
    mock_adapter = AsyncMock()
    client._adapter = mock_adapter
    client._initialized = True
    
    return client


@pytest.fixture
async def uninitialized_client():
    """Create an uninitialized client"""
    client = GleitzeitClient(mode="native")
    # Don't set _adapter or _initialized
    return client


class TestClientLifecycle:
    """Test core client lifecycle methods"""
    
    @pytest.mark.asyncio
    async def test_initialize(self, uninitialized_client):
        """Test client initialization"""
        client = uninitialized_client
        
        # Mock the adapter initialization
        with patch.object(client, '_init_native_mode', new_callable=AsyncMock) as mock_init:
            await client.initialize()
            
            assert client._initialized == True
            mock_init.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_initialize_api_mode(self):
        """Test client initialization in API mode"""
        client = GleitzeitClient(mode=ClientMode.API, api_host="localhost", api_port=8000)
        
        with patch.object(client, '_init_api_mode', new_callable=AsyncMock) as mock_init:
            await client.initialize()
            
            assert client._initialized == True
            mock_init.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_initialize_auto_mode(self):
        """Test client initialization with auto mode detection"""
        client = GleitzeitClient(mode=ClientMode.AUTO)
        
        with patch.object(client, '_detect_best_mode', new_callable=AsyncMock) as mock_detect:
            with patch.object(client, '_init_native_mode', new_callable=AsyncMock) as mock_init:
                mock_detect.return_value = ClientMode.NATIVE
                
                await client.initialize()
                
                assert client.mode == ClientMode.NATIVE
                mock_detect.assert_called_once()
                mock_init.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_shutdown(self, client):
        """Test client shutdown"""
        # Setup mock server process
        mock_process = Mock()
        mock_process.poll.return_value = None
        client._server_process = mock_process
        client.keep_server_running = False
        
        # Keep a reference to the adapter before shutdown
        adapter_mock = client._adapter
        
        await client.shutdown()
        
        assert client._initialized == False
        assert client._adapter is None
        mock_process.terminate.assert_called_once()
        adapter_mock.shutdown.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_shutdown_keep_server_running(self, client):
        """Test shutdown with keep_server_running=True"""
        mock_process = Mock()
        client._server_process = mock_process
        client.keep_server_running = True
        
        # Keep a reference to the adapter before shutdown
        adapter_mock = client._adapter
        
        await client.shutdown()
        
        # Server process should not be terminated
        mock_process.terminate.assert_not_called()
        adapter_mock.shutdown.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_switch_mode(self, client):
        """Test switching client mode"""
        # Start in native mode
        assert client.mode == ClientMode.NATIVE
        
        # Keep a reference to the adapter before switch
        old_adapter = client._adapter
        
        # Mock the initialization methods
        with patch.object(client, '_init_api_mode', new_callable=AsyncMock) as mock_init_api:
            await client.switch_mode(ClientMode.API)
            
            assert client.mode == ClientMode.API
            old_adapter.shutdown.assert_called_once()
            mock_init_api.assert_called_once()


class TestEngineManagement:
    """Test execution engine management"""
    
    @pytest.mark.asyncio
    async def test_start_engine(self, client):
        """Test starting the execution engine"""
        # Mock the adapter's start_engine method
        mock_task = AsyncMock()
        client._adapter.start_engine = AsyncMock(return_value=mock_task)
        
        result = await client.start_engine(mode='EVENT_DRIVEN')
        
        assert result == mock_task
        client._adapter.start_engine.assert_called_once_with('EVENT_DRIVEN')
    
    @pytest.mark.asyncio
    async def test_start_engine_api_mode(self):
        """Test that API mode doesn't start engine"""
        client = GleitzeitClient(mode=ClientMode.API)
        client._initialized = True
        
        result = await client.start_engine()
        
        assert result is None  # API mode returns None
    
    @pytest.mark.asyncio
    async def test_stop_engine(self, client):
        """Test stopping the execution engine"""
        client._adapter.stop_engine = AsyncMock(return_value=True)
        
        result = await client.stop_engine()
        
        assert result == True
        client._adapter.stop_engine.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_raw(self, client):
        """Test executing raw adapter methods"""
        # Add a custom method to the adapter
        client._adapter.custom_method = AsyncMock(return_value={"custom": "result"})
        
        result = await client.execute_raw('custom_method', arg1='value1', arg2='value2')
        
        assert result == {"custom": "result"}
        client._adapter.custom_method.assert_called_once_with(arg1='value1', arg2='value2')
    
    @pytest.mark.asyncio
    async def test_execute_raw_sync_method(self, client):
        """Test executing raw sync methods"""
        # Add a sync method to the adapter
        client._adapter.sync_method = Mock(return_value="sync_result")
        
        result = await client.execute_raw('sync_method', 'arg1')
        
        assert result == "sync_result"
        client._adapter.sync_method.assert_called_once_with('arg1')
    
    @pytest.mark.asyncio
    async def test_execute_raw_nonexistent_method(self, client):
        """Test execute_raw with non-existent method"""
        # Create a mock adapter with specific methods only
        from unittest.mock import Mock
        mock_adapter = Mock(spec=['real_method'])  # Only has 'real_method'
        client._adapter = mock_adapter
        
        with pytest.raises(AttributeError, match="Adapter has no method 'fake_method'"):
            await client.execute_raw('fake_method')
    
    @pytest.mark.asyncio
    async def test_get_events(self, client):
        """Test getting persisted events"""
        expected_events = [
            {"id": "event1", "type": "task_started", "workflow_id": "wf1"},
            {"id": "event2", "type": "task_completed", "workflow_id": "wf1"}
        ]
        
        client._adapter.get_events = AsyncMock(return_value=expected_events)
        
        result = await client.get_events(workflow_id="wf1", event_type="task_started")
        
        assert result == expected_events
        client._adapter.get_events.assert_called_once_with(
            workflow_id="wf1",
            task_id=None,
            event_type="task_started",
            limit=1000
        )
    
    @pytest.mark.asyncio
    async def test_get_events_no_adapter_method(self, client):
        """Test get_events when adapter doesn't have the method"""
        # Remove the method if it exists
        if hasattr(client._adapter, 'get_events'):
            delattr(client._adapter, 'get_events')
        
        result = await client.get_events()
        
        assert result == []  # Returns empty list when method not available


class TestBatchProcessingExtended:
    """Test extended batch processing methods"""
    
    @pytest.mark.asyncio
    async def test_batch_process_with_progress(self, client):
        """Test batch processing with progress updates"""
        # This is a generator method, so we need to test differently
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            test_dir = Path(tmpdir)
            (test_dir / "file1.txt").write_text("content1")
            (test_dir / "file2.txt").write_text("content2")
            
            # Mock execute_task to return results
            mock_results = [
                Mock(output="result1"),
                Mock(output="result2")
            ]
            client.execute_task = AsyncMock(side_effect=mock_results)
            
            # Collect results from the generator
            results = []
            async for result in client.batch_process_with_progress(
                directory=str(test_dir),
                pattern="*.txt",
                method="test_method",
                prompt="test prompt"
            ):
                results.append(result)
            
            assert len(results) == 2
            assert results[0]["progress"]["completed"] == 1
            assert results[1]["progress"]["completed"] == 2
            assert results[1]["progress"]["percentage"] == 100.0
    
    @pytest.mark.asyncio
    async def test_batch_transform_files(self, client):
        """Test batch file transformation"""
        import tempfile
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            
            # Create test input files
            (input_dir / "file1.txt").write_text("input1")
            (input_dir / "file2.txt").write_text("input2")
            
            # Mock batch_process
            mock_result = {
                str(input_dir / "file1.txt"): "transformed1",
                str(input_dir / "file2.txt"): "transformed2"
            }
            client._adapter.batch_process.return_value = mock_result
            
            result = await client.batch_transform_files(
                input_dir=str(input_dir),
                output_dir=str(output_dir),
                pattern="*.txt",
                transformation="uppercase"
            )
            
            assert result["processed"] == 2
            assert result["output_directory"] == str(output_dir)
            assert len(result["files"]) == 2
            
            # Check output directory was created
            assert output_dir.exists()


class TestQueueExtended:
    """Test extended queue operations"""
    
    @pytest.mark.asyncio
    async def test_get_queue_health(self, client):
        """Test getting queue health status"""
        mock_queues = {
            "high_priority": {"size": 5, "status": "active"},
            "normal": {"size": 1500, "status": "active"},  # Overloaded
            "low_priority": {"size": 100, "status": "paused"}  # Paused
        }
        
        client._adapter.get_queues.return_value = mock_queues
        
        result = await client.get_queue_health()
        
        assert result["high_priority"]["status"] == "healthy"
        assert result["normal"]["status"] == "critical"  # Over 1000 items
        assert result["low_priority"]["status"] == "warning"  # Paused
        
        client._adapter.get_queues.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_rebalance_queues(self, client):
        """Test queue rebalancing recommendations"""
        mock_queues = {
            "high_priority": {"size": 150, "processing": 5, "status": "active"},
            "normal": {"size": 0, "processing": 0, "status": "active"},
            "low_priority": {"size": 50, "processing": 2, "status": "active"}
        }
        
        client._adapter.get_queues.return_value = mock_queues
        
        result = await client.rebalance_queues()
        
        assert result["analyzed"] == 3
        assert len(result["recommendations"]) > 0
        
        # Should recommend scaling up high_priority (>100 items)
        scale_up = [r for r in result["recommendations"] if r["action"] == "scale_up"]
        assert len(scale_up) > 0
        
        # Should recommend scaling down normal (idle)
        scale_down = [r for r in result["recommendations"] if r["action"] == "scale_down"]
        assert len(scale_down) > 0
    
    @pytest.mark.asyncio
    async def test_move_task_to_queue(self, client):
        """Test moving task to different queue"""
        task_id = "task-123"
        target_queue = "high_priority"
        
        # This method is not implemented in backend yet
        result = await client.move_task_to_queue(task_id, target_queue)
        
        assert result["task_id"] == task_id
        assert result["target_queue"] == target_queue
        assert result["status"] == "operation_not_implemented"


class TestReplayExtended:
    """Test extended replay operations"""
    
    @pytest.mark.asyncio
    async def test_debug_workflow(self, client):
        """Test workflow debugging with breakpoints"""
        workflow_id = "wf-123"
        breakpoints = ["task2", "task5"]
        
        mock_replay_service = Mock()
        mock_replay_service.replay = AsyncMock(return_value={
            "new_workflow_id": "wf-456",
            "mode": "debug",
            "breakpoints": breakpoints
        })
        
        with patch.object(client, '_get_replay_service', return_value=mock_replay_service):
            result = await client.debug_workflow(workflow_id, breakpoints)
        
        assert result["mode"] == "debug"
        assert result["breakpoints"] == breakpoints
        mock_replay_service.replay.assert_called_once_with(
            workflow_id, "debug", debug_breakpoints=breakpoints
        )
    
    @pytest.mark.asyncio
    async def test_restore_workflow_state(self, client):
        """Test restoring workflow state"""
        workflow_id = "wf-123"
        target_time = datetime(2025, 1, 1, 12, 0, 0)
        
        mock_replay_service = Mock()
        mock_replay_service.replay = AsyncMock(return_value={
            "workflow_id": workflow_id,
            "state": "restored",
            "target_time": target_time.isoformat()
        })
        
        with patch.object(client, '_get_replay_service', return_value=mock_replay_service):
            result = await client.restore_workflow_state(workflow_id, target_time)
        
        assert result["state"] == "restored"
        mock_replay_service.replay.assert_called_once_with(
            workflow_id, "restore", target_time=target_time
        )
    
    @pytest.mark.asyncio
    async def test_list_replayable_workflows(self, client):
        """Test listing replayable workflows"""
        expected_workflows = [
            {"id": "wf1", "status": "failed", "replayable": True},
            {"id": "wf2", "status": "completed", "replayable": True}
        ]
        
        mock_replay_service = Mock()
        mock_replay_service.list_replayable_workflows = AsyncMock(return_value=expected_workflows)
        
        with patch.object(client, '_get_replay_service', return_value=mock_replay_service):
            result = await client.list_replayable_workflows(status="failed", limit=50)
        
        assert result == expected_workflows
        mock_replay_service.list_replayable_workflows.assert_called_once_with("failed", None, 50)
    
    @pytest.mark.asyncio
    async def test_get_replay_history(self, client):
        """Test getting replay history for a workflow"""
        workflow_id = "wf-123"
        expected_history = [
            {"replay_id": "replay1", "timestamp": "2025-01-01T10:00:00", "mode": "re_execute"},
            {"replay_id": "replay2", "timestamp": "2025-01-01T11:00:00", "mode": "debug"}
        ]
        
        mock_replay_service = Mock()
        mock_replay_service.get_replay_history = AsyncMock(return_value=expected_history)
        
        with patch.object(client, '_get_replay_service', return_value=mock_replay_service):
            result = await client.get_replay_history(workflow_id)
        
        assert result == expected_history
        mock_replay_service.get_replay_history.assert_called_once_with(workflow_id)


class TestClientProperties:
    """Test client property access and state"""
    
    @pytest.mark.asyncio
    async def test_execution_engine_property(self, client):
        """Test execution_engine property access"""
        mock_engine = Mock()
        client._adapter.execution_engine = mock_engine
        
        assert client.execution_engine == mock_engine
        assert client._execution_engine == mock_engine  # Test alias
    
    @pytest.mark.asyncio
    async def test_execution_engine_no_adapter_support(self, client):
        """Test execution_engine when adapter doesn't have it"""
        # Remove execution_engine if it exists
        if hasattr(client._adapter, 'execution_engine'):
            delattr(client._adapter, 'execution_engine')
        
        assert client.execution_engine is None
    
    @pytest.mark.asyncio
    async def test_adapter_property(self, client):
        """Test adapter property access"""
        assert client.adapter == client._adapter
    
    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test using client as async context manager"""
        client = GleitzeitClient(mode="native")
        
        with patch.object(client, 'initialize', new_callable=AsyncMock) as mock_init:
            with patch.object(client, 'shutdown', new_callable=AsyncMock) as mock_shutdown:
                async with client as ctx_client:
                    assert ctx_client == client
                    mock_init.assert_called_once()
                
                mock_shutdown.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])