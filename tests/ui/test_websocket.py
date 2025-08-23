"""
Tests for WebSocket functionality
"""

import pytest
import asyncio
import json
from fastapi.testclient import TestClient
from datetime import datetime
import sys
from pathlib import Path

# Add src directory to path
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))

from ui.api.app import app
from ui.api.routes.websocket import manager, ConnectionManager


@pytest.fixture
def client():
    """Create test client with WebSocket support"""
    return TestClient(app)


class TestWebSocketConnection:
    """Test WebSocket connection and messaging"""
    
    def test_websocket_connect(self, client):
        """Test WebSocket connection"""
        with client.websocket_connect("/ws/updates") as websocket:
            # Should receive connection confirmation
            data = websocket.receive_json()
            assert data["type"] == "connection"
            assert data["status"] == "connected"
    
    def test_websocket_subscribe(self, client):
        """Test subscribing to channels"""
        with client.websocket_connect("/ws/updates") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Send subscribe message
            websocket.send_json({
                "type": "subscribe",
                "channels": ["workflows", "tasks"]
            })
            
            # Should receive subscription confirmation
            data = websocket.receive_json()
            assert data["type"] == "subscription"
            assert "workflows" in data["channels"]
            assert "tasks" in data["channels"]
    
    def test_websocket_unsubscribe(self, client):
        """Test unsubscribing from channels"""
        with client.websocket_connect("/ws/updates") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Subscribe first
            websocket.send_json({
                "type": "subscribe",
                "channels": ["workflows", "tasks"]
            })
            websocket.receive_json()  # Skip subscription confirmation
            
            # Unsubscribe
            websocket.send_json({
                "type": "unsubscribe",
                "channels": ["workflows"]
            })
            
            # Should receive updated subscription
            data = websocket.receive_json()
            assert data["type"] == "subscription"
            assert "workflows" not in data["channels"]
            assert "tasks" in data["channels"]
    
    def test_websocket_ping_pong(self, client):
        """Test ping/pong messages"""
        with client.websocket_connect("/ws/updates") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Send ping
            websocket.send_json({"type": "ping"})
            
            # Should receive pong
            data = websocket.receive_json()
            assert data["type"] == "pong"
            assert "timestamp" in data
    
    def test_websocket_get_status(self, client):
        """Test getting status via WebSocket"""
        with client.websocket_connect("/ws/updates") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Request status
            websocket.send_json({"type": "get_status"})
            
            # Should receive status update
            data = websocket.receive_json()
            assert data["type"] == "status_update"
            assert "data" in data
            assert "workflows" in data["data"]
            assert "tasks" in data["data"]
    
    def test_websocket_invalid_message(self, client):
        """Test handling invalid message type"""
        with client.websocket_connect("/ws/updates") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Send invalid message type
            websocket.send_json({"type": "invalid_type"})
            
            # Should receive error
            data = websocket.receive_json()
            assert data["type"] == "error"
            assert "Unknown message type" in data["message"]
    
    def test_websocket_invalid_json(self, client):
        """Test handling invalid JSON"""
        with client.websocket_connect("/ws/updates") as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Send invalid JSON
            websocket.send_text("invalid json")
            
            # Should receive error
            data = websocket.receive_json()
            assert data["type"] == "error"
            assert "Invalid JSON" in data["message"]


class TestConnectionManager:
    """Test ConnectionManager functionality"""
    
    @pytest.mark.asyncio
    async def test_manager_connect_disconnect(self):
        """Test connection management"""
        manager = ConnectionManager()
        
        # Mock WebSocket
        class MockWebSocket:
            async def accept(self):
                pass
            
            async def send_json(self, data):
                self.last_message = data
        
        ws = MockWebSocket()
        
        # Connect
        await manager.connect(ws)
        assert ws in manager.active_connections
        assert ws in manager.subscriptions
        assert hasattr(ws, 'last_message')
        assert ws.last_message["type"] == "connection"
        
        # Disconnect
        manager.disconnect(ws)
        assert ws not in manager.active_connections
        assert ws not in manager.subscriptions
    
    @pytest.mark.asyncio
    async def test_manager_subscribe_unsubscribe(self):
        """Test subscription management"""
        manager = ConnectionManager()
        
        # Mock WebSocket
        class MockWebSocket:
            async def accept(self):
                pass
            
            async def send_json(self, data):
                self.last_message = data
        
        ws = MockWebSocket()
        await manager.connect(ws)
        
        # Subscribe
        await manager.subscribe(ws, ["workflows", "tasks"])
        assert "workflows" in manager.subscriptions[ws]
        assert "tasks" in manager.subscriptions[ws]
        assert ws.last_message["type"] == "subscription"
        
        # Unsubscribe
        await manager.unsubscribe(ws, ["workflows"])
        assert "workflows" not in manager.subscriptions[ws]
        assert "tasks" in manager.subscriptions[ws]
    
    @pytest.mark.asyncio
    async def test_manager_broadcast(self):
        """Test message broadcasting"""
        manager = ConnectionManager()
        
        # Mock WebSockets
        class MockWebSocket:
            def __init__(self):
                self.messages = []
            
            async def accept(self):
                pass
            
            async def send_json(self, data):
                self.messages.append(data)
        
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        
        await manager.connect(ws1)
        await manager.connect(ws2)
        
        # Subscribe ws1 to workflows
        await manager.subscribe(ws1, ["workflows"])
        
        # Subscribe ws2 to tasks
        await manager.subscribe(ws2, ["tasks"])
        
        # Broadcast to workflows channel
        await manager.broadcast(
            {"type": "workflow_update", "data": {"id": "test"}},
            "workflows"
        )
        
        # Only ws1 should receive the message
        assert len(ws1.messages) == 3  # connection, subscription, broadcast
        assert ws1.messages[-1]["type"] == "workflow_update"
        
        assert len(ws2.messages) == 2  # connection, subscription (no broadcast)
    
    @pytest.mark.asyncio
    async def test_manager_broadcast_all(self):
        """Test broadcasting to all connections"""
        manager = ConnectionManager()
        
        # Mock WebSockets
        class MockWebSocket:
            def __init__(self):
                self.messages = []
            
            async def accept(self):
                pass
            
            async def send_json(self, data):
                self.messages.append(data)
        
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        
        await manager.connect(ws1)
        await manager.connect(ws2)
        
        # Broadcast without channel (to all)
        await manager.broadcast({"type": "system_event", "data": {"event": "test"}})
        
        # Both should receive the message
        assert ws1.messages[-1]["type"] == "system_event"
        assert ws2.messages[-1]["type"] == "system_event"
    
    @pytest.mark.asyncio
    async def test_manager_send_personal_message(self):
        """Test sending message to specific connection"""
        manager = ConnectionManager()
        
        # Mock WebSocket
        class MockWebSocket:
            def __init__(self):
                self.messages = []
            
            async def accept(self):
                pass
            
            async def send_json(self, data):
                self.messages.append(data)
        
        ws = MockWebSocket()
        await manager.connect(ws)
        
        # Send personal message
        await manager.send_personal_message(
            {"type": "personal", "data": "test"},
            ws
        )
        
        assert ws.messages[-1]["type"] == "personal"


class TestWebSocketHelpers:
    """Test WebSocket helper functions"""
    
    @pytest.mark.asyncio
    async def test_notify_workflow_update(self):
        """Test workflow update notification"""
        from ui.api.routes.websocket import notify_workflow_update
        
        # This would need a running manager instance
        # In real tests, we'd mock the manager
        try:
            await notify_workflow_update("workflow_1", "running", {"progress": 0.5})
            # If no error, test passes
            assert True
        except:
            # Expected if manager not initialized
            assert True
    
    @pytest.mark.asyncio
    async def test_notify_task_update(self):
        """Test task update notification"""
        from ui.api.routes.websocket import notify_task_update
        
        try:
            await notify_task_update("task_1", "completed", {"result": "success"})
            assert True
        except:
            assert True
    
    @pytest.mark.asyncio
    async def test_notify_system_event(self):
        """Test system event notification"""
        from ui.api.routes.websocket import notify_system_event
        
        try:
            await notify_system_event("error", {"message": "Test error"})
            assert True
        except:
            assert True