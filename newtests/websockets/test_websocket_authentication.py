"""
Test WebSocket authentication and authorization.
"""

import asyncio
import json
import pytest
import websockets
import aiohttp
from typing import Dict, Any, List


class TestWebSocketAuthentication:
    """Test WebSocket authentication consistency and behavior."""
    
    @pytest.fixture
    def ws_url(self) -> str:
        """WebSocket URL for testing."""
        return "ws://localhost:8080/events/stream"
    
    @pytest.fixture
    def api_url(self) -> str:
        """HTTP API URL for testing."""
        return "http://localhost:8080"
    
    @pytest.mark.asyncio
    async def test_auto_login_basic_user(self, ws_url: str):
        """Test that WebSocket auto-logs in as basic user."""
        async with websockets.connect(ws_url) as websocket:
            # Skip connection message
            await websocket.recv()
            
            # Get auth message
            auth_msg = await websocket.recv()
            auth_data = json.loads(auth_msg)
            
            assert auth_data.get("type") == "auth"
            user = auth_data.get("user", {})
            
            # Verify basic user details
            assert user.get("id") == "basic-user"
            assert user.get("username") == "basic"
            assert user.get("role") == "basic"
    
    @pytest.mark.asyncio
    async def test_no_auth_required(self, ws_url: str):
        """Test that no authentication credentials are required."""
        # Connect without any auth headers or tokens
        async with websockets.connect(ws_url) as websocket:
            # Should connect successfully
            conn_msg = await websocket.recv()
            conn_data = json.loads(conn_msg)
            assert conn_data.get("status") == "connected"
            
            # Should auto-authenticate
            auth_msg = await websocket.recv()
            auth_data = json.loads(auth_msg)
            assert auth_data.get("user", {}).get("username") == "basic"
    
    @pytest.mark.asyncio
    async def test_token_parameter_ignored(self, ws_url: str):
        """Test that token parameter is accepted but uses basic user."""
        # Connect with a token (should be ignored in basic mode)
        uri = f"{ws_url}?token=invalid-token-12345"
        
        async with websockets.connect(uri) as websocket:
            # Should connect successfully
            await websocket.recv()  # connection
            
            # Should still use basic user
            auth_msg = await websocket.recv()
            auth_data = json.loads(auth_msg)
            user = auth_data.get("user", {})
            
            assert user.get("username") == "basic"
            assert user.get("role") == "basic"
    
    @pytest.mark.asyncio
    async def test_consistency_with_http_api(self, ws_url: str, api_url: str):
        """Test that WebSocket auth is consistent with HTTP API."""
        ws_user = None
        http_user = None
        
        # Get WebSocket user
        async with websockets.connect(ws_url) as websocket:
            await websocket.recv()  # connection
            auth_msg = await websocket.recv()
            auth_data = json.loads(auth_msg)
            ws_user = auth_data.get("user", {})
        
        # Get HTTP API user
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{api_url}/auth/me") as resp:
                if resp.status == 200:
                    http_user = await resp.json()
        
        # Both should be basic user
        assert ws_user.get("username") == "basic"
        assert http_user.get("username") == "basic"
        assert ws_user.get("role") == http_user.get("role") == "basic"
    
    @pytest.mark.asyncio
    async def test_multiple_connections_same_user(self, ws_url: str):
        """Test that multiple connections all get the same basic user."""
        users = []
        
        # Open multiple connections
        for i in range(3):
            async with websockets.connect(f"{ws_url}?client_id=multi_{i}") as ws:
                await ws.recv()  # connection
                auth_msg = await ws.recv()
                auth_data = json.loads(auth_msg)
                users.append(auth_data.get("user", {}))
        
        # All should be basic user
        for user in users:
            assert user.get("username") == "basic"
            assert user.get("id") == "basic-user"
            assert user.get("role") == "basic"
        
        # All should be identical
        assert all(u == users[0] for u in users)
    
    @pytest.mark.asyncio
    async def test_auth_persists_during_session(self, ws_url: str):
        """Test that authentication persists for the session duration."""
        async with websockets.connect(ws_url) as websocket:
            # Get initial auth
            await websocket.recv()  # connection
            auth_msg = await websocket.recv()
            initial_auth = json.loads(auth_msg)
            initial_user = initial_auth.get("user", {})
            
            # Perform operations (subscribe, ping, etc.)
            subscribe_msg = json.dumps({
                "type": "subscribe",
                "event_types": ["test:*"]
            })
            await websocket.send(subscribe_msg)
            await websocket.recv()  # subscription response
            
            ping_msg = json.dumps({"type": "ping"})
            await websocket.send(ping_msg)
            await websocket.recv()  # pong
            
            # Auth should still be the same (no re-auth needed)
            # User doesn't change during session
            assert initial_user.get("username") == "basic"
    
    @pytest.mark.asyncio
    async def test_stateless_authentication(self, ws_url: str):
        """Test that authentication is stateless (no session persistence)."""
        client_id = "stateless_test"
        uri = f"{ws_url}?client_id={client_id}"
        
        # First connection
        user1 = None
        async with websockets.connect(uri) as ws1:
            await ws1.recv()  # connection
            auth1 = json.loads(await ws1.recv())
            user1 = auth1.get("user", {})
        
        # Wait a bit
        await asyncio.sleep(0.5)
        
        # Second connection with same client_id
        user2 = None
        async with websockets.connect(uri) as ws2:
            await ws2.recv()  # connection
            auth2 = json.loads(await ws2.recv())
            user2 = auth2.get("user", {})
        
        # Both should be basic user (no session state)
        assert user1.get("username") == "basic"
        assert user2.get("username") == "basic"
        assert user1 == user2  # Identical users
    
    @pytest.mark.asyncio
    async def test_auth_info_format(self, ws_url: str):
        """Test that auth info message has correct format."""
        async with websockets.connect(ws_url) as websocket:
            # Skip connection
            await websocket.recv()
            
            # Get auth message
            auth_msg = await websocket.recv()
            auth_data = json.loads(auth_msg)
            
            # Check message structure
            assert auth_data.get("type") == "auth"
            assert "user" in auth_data
            
            user = auth_data["user"]
            assert "id" in user
            assert "username" in user
            assert "role" in user
            
            # Check data types
            assert isinstance(user["id"], str)
            assert isinstance(user["username"], str)
            assert isinstance(user["role"], str)
    
    @pytest.mark.asyncio
    async def test_operations_allowed_for_basic_user(self, ws_url: str):
        """Test that basic user can perform allowed operations."""
        async with websockets.connect(ws_url) as websocket:
            # Skip initial messages
            await websocket.recv()  # connection
            await websocket.recv()  # auth
            
            # Test allowed operations
            operations = [
                {"type": "subscribe", "event_types": ["task:*"]},
                {"type": "subscribe", "event_types": ["workflow:*"]},
                {"type": "ping"},
            ]
            
            for op in operations:
                await websocket.send(json.dumps(op))
                response = await websocket.recv()
                response_data = json.loads(response)
                
                # Should not be an error
                assert response_data.get("type") != "error"
                
                # Should get appropriate response
                if op["type"] == "subscribe":
                    assert response_data.get("status") == "subscribed"
                elif op["type"] == "ping":
                    assert response_data.get("type") == "pong"