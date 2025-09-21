"""
Test WebSocket connection and basic functionality.
"""

import asyncio
import json
import pytest
import websockets
from typing import Dict, Any


class TestWebSocketConnection:
    """Test WebSocket connection establishment and basic operations."""
    
    @pytest.fixture
    def ws_url(self) -> str:
        """WebSocket URL for testing."""
        return "ws://localhost:8080/events/stream"
    
    @pytest.mark.asyncio
    async def test_connection_establishment(self, ws_url: str):
        """Test that WebSocket connection can be established."""
        async with websockets.connect(ws_url) as websocket:
            # Should receive connection confirmation
            msg = await websocket.recv()
            data = json.loads(msg)
            
            assert data.get("type") == "connection"
            assert data.get("status") == "connected"
            assert "connection_id" in data
            assert "timestamp" in data
    
    @pytest.mark.asyncio
    async def test_auto_authentication(self, ws_url: str):
        """Test that WebSocket automatically authenticates with basic user."""
        async with websockets.connect(ws_url) as websocket:
            # Skip connection message
            await websocket.recv()
            
            # Should receive auth message
            msg = await websocket.recv()
            data = json.loads(msg)
            
            assert data.get("type") == "auth"
            assert "user" in data
            
            user = data["user"]
            assert user.get("id") == "basic-user"
            assert user.get("username") == "basic"
            assert user.get("role") == "basic"
    
    @pytest.mark.asyncio
    async def test_ping_pong_keepalive(self, ws_url: str):
        """Test ping/pong keepalive mechanism."""
        async with websockets.connect(ws_url) as websocket:
            # Skip initial messages
            await websocket.recv()  # connection
            await websocket.recv()  # auth
            
            # Send ping
            ping_msg = json.dumps({"type": "ping"})
            await websocket.send(ping_msg)
            
            # Should receive pong
            msg = await websocket.recv()
            data = json.loads(msg)
            
            assert data.get("type") == "pong"
            assert "timestamp" in data
    
    @pytest.mark.asyncio
    async def test_multiple_connections(self, ws_url: str):
        """Test that multiple WebSocket connections can be established."""
        connections = []
        
        try:
            # Open 3 connections
            for i in range(3):
                ws = await websockets.connect(f"{ws_url}?client_id=test_client_{i}")
                connections.append(ws)
                
                # Verify each gets connection and auth messages
                conn_msg = await ws.recv()
                conn_data = json.loads(conn_msg)
                assert conn_data.get("type") == "connection"
                
                auth_msg = await ws.recv()
                auth_data = json.loads(auth_msg)
                assert auth_data.get("type") == "auth"
                assert auth_data.get("user", {}).get("username") == "basic"
            
            assert len(connections) == 3
            
        finally:
            # Clean up connections
            for ws in connections:
                await ws.close()
    
    @pytest.mark.asyncio
    async def test_client_id_parameter(self, ws_url: str):
        """Test that client_id parameter is accepted."""
        client_id = "test_client_123"
        uri = f"{ws_url}?client_id={client_id}"
        
        async with websockets.connect(uri) as websocket:
            # Should receive connection with our client_id
            msg = await websocket.recv()
            data = json.loads(msg)
            
            assert data.get("type") == "connection"
            # Connection ID should be our client_id or contain it
            connection_id = data.get("connection_id", "")
            assert client_id in connection_id or connection_id == client_id
    
    @pytest.mark.asyncio
    async def test_token_parameter_accepted(self, ws_url: str):
        """Test that token parameter is accepted (though uses basic user)."""
        uri = f"{ws_url}?token=test-token-456"
        
        async with websockets.connect(uri) as websocket:
            # Should connect successfully
            msg = await websocket.recv()
            data = json.loads(msg)
            assert data.get("type") == "connection"
            
            # Still authenticates as basic user
            auth_msg = await websocket.recv()
            auth_data = json.loads(auth_msg)
            assert auth_data.get("user", {}).get("username") == "basic"
    
    @pytest.mark.asyncio
    async def test_reconnection(self, ws_url: str):
        """Test that reconnection works properly."""
        client_id = "reconnect_test"
        uri = f"{ws_url}?client_id={client_id}"
        
        # First connection
        async with websockets.connect(uri) as ws1:
            await ws1.recv()  # connection
            auth1 = json.loads(await ws1.recv())
            user1 = auth1.get("user", {}).get("username")
        
        # Second connection with same client_id
        async with websockets.connect(uri) as ws2:
            await ws2.recv()  # connection
            auth2 = json.loads(await ws2.recv())
            user2 = auth2.get("user", {}).get("username")
        
        # Should get same basic user (stateless)
        assert user1 == user2 == "basic"
    
    @pytest.mark.asyncio
    async def test_invalid_message_handling(self, ws_url: str):
        """Test that invalid messages are handled gracefully."""
        async with websockets.connect(ws_url) as websocket:
            # Skip initial messages
            await websocket.recv()  # connection
            await websocket.recv()  # auth
            
            # Send invalid JSON
            await websocket.send("not valid json")
            
            # Should receive error response
            msg = await websocket.recv()
            data = json.loads(msg)
            
            assert data.get("type") == "error"
            assert "Invalid JSON" in data.get("message", "")
    
    @pytest.mark.asyncio
    async def test_unknown_message_type(self, ws_url: str):
        """Test that unknown message types are handled."""
        async with websockets.connect(ws_url) as websocket:
            # Skip initial messages
            await websocket.recv()  # connection
            await websocket.recv()  # auth
            
            # Send unknown message type
            unknown_msg = json.dumps({"type": "unknown_type", "data": "test"})
            await websocket.send(unknown_msg)
            
            # Should receive error response
            msg = await websocket.recv()
            data = json.loads(msg)
            
            assert data.get("type") == "error"
            assert "Unknown message type" in data.get("message", "")