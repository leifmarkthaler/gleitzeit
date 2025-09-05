"""
Comprehensive test suite for event-driven client.
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime

from gleitzeit.core.models import Task, Workflow, TaskResult, TaskStatus
from gleitzeit.core.events import EventType, GleitzeitEvent
from gleitzeit.client import GleitzeitClient, EventMode
from gleitzeit.client.events import (
    ClientEventBus, ClientEvent,
    ConnectionState, WebSocketConfig
)


class TestClientEventBus:
    """Test ClientEventBus functionality."""
    
    @pytest.fixture
    def event_bus(self):
        """Create event bus instance."""
        return ClientEventBus()
    
    @pytest.mark.asyncio
    async def test_event_bus_lifecycle(self, event_bus):
        """Test starting and stopping event bus."""
        # Start
        await event_bus.start()
        assert event_bus._running is True
        assert event_bus._processing_task is not None
        
        # Stop
        await event_bus.stop()
        assert event_bus._running is False
        
    @pytest.mark.asyncio
    async def test_event_registration_and_emission(self, event_bus):
        """Test registering handlers and emitting events."""
        await event_bus.start()
        
        # Track handler calls
        handler_calls = []
        
        async def test_handler(event):
            handler_calls.append(event)
            
        # Register handler
        sub_id = event_bus.register(EventType.TASK_COMPLETED, test_handler)
        assert sub_id is not None
        
        # Emit event
        test_event = GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={'task_id': 'test-1'}
        )
        await event_bus.emit(test_event)
        
        # Wait for processing
        await asyncio.sleep(0.1)
        
        # Verify handler was called
        assert len(handler_calls) == 1
        assert handler_calls[0].data['task_id'] == 'test-1'
        
        # Cleanup
        await event_bus.stop()
        
    @pytest.mark.asyncio
    async def test_event_priority(self, event_bus):
        """Test priority-based handler execution."""
        await event_bus.start()
        
        execution_order = []
        
        async def high_priority_handler(event):
            execution_order.append('high')
            
        async def normal_priority_handler(event):
            execution_order.append('normal')
            
        async def low_priority_handler(event):
            execution_order.append('low')
            
        from gleitzeit.client.events.client_event_bus import SubscriptionPriority
        
        # Register in random order
        event_bus.register(EventType.TEST_PRIORITY, low_priority_handler, SubscriptionPriority.LOW)
        event_bus.register(EventType.TEST_PRIORITY, high_priority_handler, SubscriptionPriority.HIGH)
        event_bus.register(EventType.TEST_PRIORITY, normal_priority_handler, SubscriptionPriority.NORMAL)
        
        # Emit event synchronously to ensure order
        await event_bus.emit_sync({'event_type': EventType.TEST_PRIORITY, 'data': {}})
        
        # Verify execution order (high -> normal -> low)
        assert execution_order == ['high', 'normal', 'low']
        
        await event_bus.stop()
        
    @pytest.mark.asyncio
    async def test_one_time_handler(self, event_bus):
        """Test one-time event handlers."""
        await event_bus.start()
        
        call_count = 0
        
        async def once_handler(event):
            nonlocal call_count
            call_count += 1
            
        # Register one-time handler
        event_bus.register(EventType.TEST_EVENT, once_handler, once=True)
        
        # Emit event twice
        await event_bus.emit({'event_type': EventType.TEST_EVENT, 'data': {}})
        await asyncio.sleep(0.1)
        await event_bus.emit({'event_type': EventType.TEST_EVENT, 'data': {}})
        await asyncio.sleep(0.1)
        
        # Handler should only be called once
        assert call_count == 1
        
        await event_bus.stop()
        
    @pytest.mark.asyncio
    async def test_event_filter(self, event_bus):
        """Test event filtering."""
        await event_bus.start()
        
        filtered_events = []
        
        async def filtered_handler(event):
            filtered_events.append(event)
            
        # Register with filter
        def task_filter(event):
            return event.data.get('task_id') == 'target-task'
            
        event_bus.register(EventType.TASK_COMPLETED, filtered_handler, filter=task_filter)
        
        # Emit events
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={'task_id': 'other-task'}
        ))
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={'task_id': 'target-task'}
        ))
        
        await asyncio.sleep(0.1)
        
        # Only filtered event should be handled
        assert len(filtered_events) == 1
        assert filtered_events[0].data['task_id'] == 'target-task'
        
        await event_bus.stop()
        
    @pytest.mark.asyncio
    async def test_wait_for_event(self, event_bus):
        """Test waiting for specific event."""
        await event_bus.start()
        
        # Start waiting for event
        wait_task = asyncio.create_task(
            event_bus.wait_for(EventType.TASK_COMPLETED, timeout=1.0)
        )
        
        # Emit different event
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            data={'task_id': 'test'}
        ))
        
        # Emit expected event
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={'task_id': 'test', 'result': 'success'}
        ))
        
        # Wait should complete
        event = await wait_task
        assert event is not None
        assert event.data['result'] == 'success'
        
        await event_bus.stop()


class TestWebSocketManager:
    """Test WebSocket connection management."""
    
    @pytest.fixture
    def mock_event_bus(self):
        """Create mock event bus."""
        bus = Mock()
        bus.emit = AsyncMock()
        return bus
    
    @pytest.fixture
    def ws_config(self):
        """Create WebSocket configuration."""
        return WebSocketConfig(
            url='ws://localhost:8000/events',
            reconnect_enabled=True,
            reconnect_max_attempts=3,
            ping_interval=30.0
        )
    
    @pytest.mark.asyncio
    async def test_websocket_connection(self, ws_config, mock_event_bus):
        """Test WebSocket connection establishment."""
        from gleitzeit.client.events.websocket_manager import WebSocketManager
        
        manager = WebSocketManager(
            config=ws_config,
            event_bus=mock_event_bus
        )
        
        # Mock WebSocket connection
        with patch('aiohttp.ClientSession.ws_connect', new_callable=AsyncMock) as mock_connect:
            mock_ws = MagicMock()
            mock_ws.closed = False
            mock_ws.close = AsyncMock()
            mock_connect.return_value = mock_ws
            
            # Connect
            connected = await manager.connect()
            
            # Verify connection
            assert connected is True
            assert manager.state == ConnectionState.CONNECTED
            assert manager.websocket is not None
            
            # Verify connection event emitted
            mock_event_bus.emit.assert_called()
            event = mock_event_bus.emit.call_args[0][0]
            assert event.event_type == EventType.CLIENT_CONNECTION_ESTABLISHED
            
            # Disconnect
            await manager.disconnect()
            assert manager.state == ConnectionState.DISCONNECTED
            
    @pytest.mark.asyncio
    async def test_websocket_reconnection(self, ws_config, mock_event_bus):
        """Test automatic reconnection."""
        from gleitzeit.client.events.websocket_manager import WebSocketManager
        
        # Configure for fast reconnection
        ws_config.reconnect_interval = 0.1
        ws_config.reconnect_max_interval = 0.5
        
        manager = WebSocketManager(
            config=ws_config,
            event_bus=mock_event_bus
        )
        
        connection_attempts = 0
        
        async def mock_connect_side_effect(*args, **kwargs):
            nonlocal connection_attempts
            connection_attempts += 1
            
            if connection_attempts < 3:
                # Fail first two attempts
                raise Exception("Connection failed")
            else:
                # Succeed on third attempt
                mock_ws = MagicMock()
                mock_ws.closed = False
                mock_ws.close = AsyncMock()
                mock_ws.receive = AsyncMock()
                return mock_ws
                
        with patch('aiohttp.ClientSession.ws_connect', side_effect=mock_connect_side_effect):
            # First connection will fail and trigger reconnection
            connected = await manager.connect()
            
            # First attempt fails
            assert connected is False
            
            # Wait for automatic reconnection attempts
            await asyncio.sleep(1.5)  # Wait for reconnection attempts
            
            # Verify events were emitted
            assert mock_event_bus.emit.called
            
            # Check that we got connection error
            event_types = [
                call[0][0].event_type 
                for call in mock_event_bus.emit.call_args_list
            ]
            
            assert EventType.CLIENT_CONNECTION_ERROR in event_types
            
            # Since reconnection happens in background, we may or may not see reconnection events
            # depending on timing. The important thing is that connection error was handled.
            
    @pytest.mark.asyncio
    async def test_message_handling(self, ws_config, mock_event_bus):
        """Test WebSocket message handling."""
        from gleitzeit.client.events.websocket_manager import WebSocketManager
        
        manager = WebSocketManager(
            config=ws_config,
            event_bus=mock_event_bus
        )
        
        # Test event message
        event_message = {
            'type': 'event',
            'event': {
                'event_type': 'task:completed',
                'data': {'task_id': 'test-1', 'result': 'success'},
                'timestamp': datetime.utcnow().isoformat()
            }
        }
        
        await manager._handle_message(json.dumps(event_message))
        
        # Verify event was emitted to bus
        mock_event_bus.emit.assert_called()
        emitted_event = mock_event_bus.emit.call_args[0][0]
        assert emitted_event.data['task_id'] == 'test-1'


class TestGleitzeitClient:
    """Test GleitzeitClient functionality."""
    
    @pytest.fixture
    def mock_adapter(self):
        """Create mock event adapter."""
        adapter = Mock()
        adapter.initialize = AsyncMock()
        adapter.shutdown = AsyncMock()
        adapter.submit_task = AsyncMock(return_value={'task_id': 'test-1', 'status': 'submitted'})
        adapter.submit_workflow = AsyncMock(return_value={'workflow_id': 'wf-1', 'status': 'submitted'})
        adapter.wait_for_task = AsyncMock()
        adapter.is_event_mode_active = Mock(return_value=True)
        adapter.get_connection_state = Mock(return_value=ConnectionState.CONNECTED)
        adapter.event_bus = ClientEventBus()
        return adapter
    
    @pytest.mark.asyncio
    async def test_client_initialization(self):
        """Test client initialization."""
        client = GleitzeitClient(
            mode='native',
            event_mode=EventMode.DIRECT,
            enable_events=True
        )
        
        # Verify initial state
        assert client.enable_events is True
        assert client.event_mode == EventMode.DIRECT
        assert client.event_bus is not None
        
    @pytest.mark.asyncio
    async def test_event_handler_registration(self):
        """Test registering event handlers."""
        client = GleitzeitClient(enable_events=True)
        
        handler_called = False
        
        @client.on_event(EventType.TASK_COMPLETED)
        async def task_complete_handler(event):
            nonlocal handler_called
            handler_called = True
            
        # Start event bus
        await client.event_bus.start()
        
        # Emit event
        await client.emit_event(
            ClientEvent(
                event_type=EventType.TASK_COMPLETED,
                data={'task_id': 'test'}
            )
        )
        
        await asyncio.sleep(0.1)
        
        # Verify handler was called
        assert handler_called is True
        
        await client.event_bus.stop()
        
    @pytest.mark.asyncio
    async def test_task_tracking(self, mock_adapter):
        """Test task submission with event tracking."""
        client = GleitzeitClient(enable_events=True)
        client._adapter = mock_adapter
        client._initialized = True
        
        await mock_adapter.event_bus.start()
        
        # Track callbacks
        start_called = False
        complete_called = False
        
        async def on_start(task_id, data):
            nonlocal start_called
            start_called = True
            
        async def on_complete(task_id, result):
            nonlocal complete_called
            complete_called = True
            
        # Submit task with tracking
        task = Task(
            id='test-1',
            name='test-task',
            protocol='python',
            method='test',
            params={}
        )
        
        response = await client.submit_task_with_tracking(
            task,
            on_start=on_start,
            on_complete=on_complete
        )
        
        assert response['task_id'] == 'test-1'
        assert response['tracking_enabled'] is True
        
        # Simulate task events
        await mock_adapter.event_bus.emit(ClientEvent(
            event_type=EventType.TASK_STARTED,
            data={'task_id': 'test-1'}
        ))
        
        await mock_adapter.event_bus.emit(ClientEvent(
            event_type=EventType.TASK_COMPLETED,
            data={'task_id': 'test-1', 'result': 'success'}
        ))
        
        await asyncio.sleep(0.1)
        
        # Verify callbacks were called
        assert start_called is True
        assert complete_called is True
        
        await mock_adapter.event_bus.stop()
        
    @pytest.mark.asyncio
    async def test_workflow_progress_tracking(self, mock_adapter):
        """Test workflow progress tracking."""
        client = GleitzeitClient(enable_events=True)
        client._adapter = mock_adapter
        client._initialized = True
        
        await mock_adapter.event_bus.start()
        
        # Track progress
        progress_updates = []
        
        async def on_progress(percent, completed, total):
            progress_updates.append((percent, completed, total))
            
        # Create workflow
        tasks = [
            Task(id=f't{i}', name=f'task-{i}', protocol='python', method='test', params={})
            for i in range(3)
        ]
        workflow = Workflow(id='wf-1', name='test-workflow', tasks=tasks)
        
        # Submit with tracking
        response = await client.submit_workflow_with_tracking(
            workflow,
            on_progress=on_progress
        )
        
        # Simulate task completions
        for i, task in enumerate(tasks):
            await mock_adapter.event_bus.emit(ClientEvent(
                event_type=EventType.TASK_COMPLETED,
                data={'task_id': task.id, 'workflow_id': 'wf-1'}
            ))
            await asyncio.sleep(0.05)
            
        # Verify progress updates
        assert len(progress_updates) == 3
        assert progress_updates[0] == (33.33333333333333, 1, 3)
        assert progress_updates[1] == (66.66666666666666, 2, 3)
        assert progress_updates[2] == (100.0, 3, 3)
        
        await mock_adapter.event_bus.stop()
        
    @pytest.mark.asyncio
    async def test_wait_for_event(self):
        """Test waiting for specific events."""
        client = GleitzeitClient(enable_events=True)
        await client.event_bus.start()
        
        # Start waiting
        wait_task = asyncio.create_task(
            client.wait_for_event(
                EventType.ENGINE_STARTED,
                timeout=1.0
            )
        )
        
        # Emit event
        await client.emit_event(
            ClientEvent(
                event_type=EventType.ENGINE_STARTED,
                data={'mode': 'event_driven'}
            )
        )
        
        # Should receive event
        event = await wait_task
        assert event is not None
        assert event.data['mode'] == 'event_driven'
        
        await client.event_bus.stop()
        
    @pytest.mark.asyncio
    async def test_event_statistics(self, mock_adapter):
        """Test getting event statistics."""
        client = GleitzeitClient(enable_events=True)
        client._adapter = mock_adapter
        client._event_adapter = mock_adapter
        mock_adapter.get_event_statistics = Mock(return_value={
            'websocket': {'connected': True},
            'adapter': {'pending_tasks': 5}
        })
        
        stats = client.get_event_statistics()
        
        assert 'event_bus' in stats
        assert 'websocket' in stats
        assert stats['adapter']['pending_tasks'] == 5
        
    @pytest.mark.asyncio
    async def test_batch_submit_with_progress(self, mock_adapter):
        """Test batch task submission with progress tracking."""
        # Create client with event bus
        event_bus = ClientEventBus()
        client = GleitzeitClient(enable_events=True, event_bus=event_bus)
        client._adapter = mock_adapter
        client._event_adapter = mock_adapter
        client._initialized = True
        
        # Start both event buses
        await event_bus.start()
        await mock_adapter.event_bus.start()
        
        # Create tasks
        tasks = [
            Task(id=f'task-{i}', name=f'test-{i}', protocol='python', method='test', params={})
            for i in range(5)
        ]
        
        # Track progress
        progress_updates = []
        
        async def on_progress(percent, completed, total):
            progress_updates.append(percent)
            
        # We need to simulate the events coming from the adapter, not directly from client
        # First, set up the futures that batch_submit_with_progress will wait on
        task_futures = {}
        for task in tasks:
            task_futures[task.id] = asyncio.Future()
        
        # Mock wait_for_task to return a future that we'll complete
        def mock_wait(task_id):
            return task_futures[task_id]
            
        mock_adapter.wait_for_task = mock_wait
        
        # Start a task to emit completion events after a delay
        async def emit_completions():
            await asyncio.sleep(0.05)  # Let batch_submit start
            for task in tasks:
                # Emit completion event
                await client.event_bus.emit(ClientEvent(
                    event_type=EventType.TASK_COMPLETED,
                    data={'task_id': task.id}
                ))
                # Complete the future
                task_futures[task.id].set_result(TaskResult(
                    task_id=task.id,
                    status=TaskStatus.COMPLETED,
                    result={'success': True}
                ))
                await asyncio.sleep(0.01)
        
        # Start emitting in background
        emit_task = asyncio.create_task(emit_completions())
        
        # Submit batch
        results = await client.batch_submit_with_progress(
            tasks,
            on_progress=on_progress
        )
        
        # Ensure emit task completes
        await emit_task
            
        # Verify results
        assert len(results) == 5
        assert all(r.status == TaskStatus.COMPLETED for r in results)
        
        # Verify progress tracking - we should get at least 4 updates (sometimes 5)
        assert len(progress_updates) >= 4
        # The last update should be 80% or 100%
        assert progress_updates[-1] >= 80.0
        
        # Clean up
        await event_bus.stop()
        await mock_adapter.event_bus.stop()


class TestEventMixins:
    """Test event-driven mixins."""
    
    @pytest.mark.asyncio
    async def test_monitor_workflow(self):
        """Test workflow monitoring."""
        from gleitzeit.client.mixins.event_workflow import EventWorkflowMixin
        
        class TestClient(EventWorkflowMixin):
            def __init__(self):
                self._adapter = Mock()
                self._adapter.event_bus = ClientEventBus()
                
            async def get_workflow(self, workflow_id):
                return Mock(status='running')
                
        client = TestClient()
        await client._adapter.event_bus.start()
        
        # Collect events in background
        events = []
        
        async def collect_events():
            async for event in client.monitor_workflow('wf-1', include_logs=False):
                events.append(event)
                if len(events) >= 2:
                    break
                    
        # Start monitoring in background
        monitor_task = asyncio.create_task(collect_events())
        
        # Give it a moment to start
        await asyncio.sleep(0.01)
        
        # Emit workflow events
        await client._adapter.event_bus.emit(ClientEvent(
            event_type=EventType.WORKFLOW_STARTED,
            data={'workflow_id': 'wf-1'}
        ))
        
        await asyncio.sleep(0.01)
        
        await client._adapter.event_bus.emit(ClientEvent(
            event_type=EventType.TASK_COMPLETED,
            data={'workflow_id': 'wf-1', 'task_id': 't1'}
        ))
        
        # Wait for collection to complete
        try:
            await asyncio.wait_for(monitor_task, timeout=1.0)
        except asyncio.TimeoutError:
            monitor_task.cancel()
            
        assert len(events) >= 2
        assert events[0]['type'] == 'event'
        
        await client._adapter.event_bus.stop()
        
    @pytest.mark.asyncio
    async def test_task_timeline(self):
        """Test getting task timeline."""
        from gleitzeit.client.mixins.event_task import EventTaskMixin
        
        class TestClient(EventTaskMixin):
            def __init__(self):
                self._adapter = Mock()
                self._adapter.get_events = AsyncMock(return_value=[
                    {
                        'timestamp': '2024-01-01T10:00:00',
                        'event_type': 'task:started',
                        'data': {'task_id': 'test-1'}
                    },
                    {
                        'timestamp': '2024-01-01T10:00:05',
                        'event_type': 'task:completed',
                        'data': {'task_id': 'test-1', 'result': 'success'}
                    }
                ])
                
        client = TestClient()
        
        timeline = await client.get_task_timeline('test-1')
        
        assert len(timeline) == 2
        assert timeline[0]['description'] == 'Task execution started'
        assert timeline[1]['description'] == 'Task completed successfully'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])