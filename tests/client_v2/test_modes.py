"""
Test different client modes (native, API, auto)
"""

import pytest
import asyncio
from unittest.mock import patch, AsyncMock

from gleitzeit import Client


class TestClientModes:
    """Test client mode selection and initialization"""
    
    @pytest.mark.asyncio
    async def test_native_mode(self):
        """Test native mode initialization and execution"""
        async with Client(mode="native") as client:
            assert client.get_mode() == "native"
            assert client.is_native_mode
            assert not client.is_api_mode
            
            # Test task execution in native mode
            result = await client.execute_task(
                protocol="mcp/v1",
                method="mcp/tool.echo",
                params={"message": "test native"},
                name="Native Test"
            )
            
            assert result is not None
            assert result.status == "completed"
            assert "test native" in str(result.result)
    
    @pytest.mark.asyncio
    async def test_api_mode_with_server(self):
        """Test API mode with auto-start server"""
        async with Client(
            mode="api",
            auto_start_server=True,
            keep_server_running=True
        ) as client:
            assert client.get_mode() == "api"
            assert client.is_api_mode
            assert not client.is_native_mode
            
            # Test task execution in API mode
            result = await client.execute_task(
                protocol="mcp/v1",
                method="mcp/tool.add",
                params={"a": 5, "b": 10},
                name="API Test"
            )
            
            assert result is not None
            assert result.status == "completed"
            assert result.result.get("result") == 15
    
    @pytest.mark.asyncio
    async def test_auto_mode_selection(self):
        """Test auto mode selects appropriate backend"""
        async with Client(mode="auto") as client:
            mode = client.get_mode()
            assert mode in ["api", "native"]
            
            # Should be able to execute regardless of selected mode
            result = await client.execute_task(
                protocol="mcp/v1",
                method="mcp/tool.multiply",
                params={"a": 3, "b": 7},
                name="Auto Mode Test"
            )
            
            assert result is not None
            assert result.status == "completed"
            assert result.result.get("result") == 21
    
    @pytest.mark.asyncio
    async def test_string_mode_input(self):
        """Test that string mode inputs work correctly"""
        modes = ["native", "api", "auto"]
        
        for mode_str in modes:
            if mode_str == "api":
                # For API mode, ensure server is available
                async with Client(
                    mode=mode_str,
                    auto_start_server=True
                ) as client:
                    assert client.get_mode() in ["api", "native"]
            else:
                async with Client(mode=mode_str) as client:
                    assert client.get_mode() in ["api", "native"]
    
    @pytest.mark.asyncio
    async def test_client_constants(self):
        """Test client mode constants"""
        # Test that constants are available
        assert Client.NATIVE == "native"
        assert Client.API == "api"
        assert Client.AUTO == "auto"
        
        # Test using constants
        async with Client(mode=Client.NATIVE) as client:
            assert client.get_mode() == "native"
    
    @pytest.mark.asyncio
    async def test_api_mode_no_server_fallback(self):
        """Test API mode behavior when server is not available and auto-start is disabled"""
        with pytest.raises(RuntimeError, match="API server not available"):
            async with Client(
                mode="api",
                api_host="localhost",
                api_port=19999,  # Use unlikely port
                auto_start_server=False
            ) as client:
                pass
    
    @pytest.mark.asyncio
    async def test_mode_not_initialized(self):
        """Test mode before initialization"""
        client = Client()
        assert client.get_mode() == "not initialized"
        assert not client.is_api_mode
        assert not client.is_native_mode


@pytest.mark.skip(reason="Server lifecycle tests can timeout in CI")
class TestServerLifecycle:
    """Test server auto-start and shutdown behavior"""
    
    @pytest.mark.asyncio
    async def test_server_auto_start(self):
        """Test that server auto-starts when needed"""
        # Kill any existing server first
        import subprocess
        subprocess.run(["pkill", "-f", "gleitzeit.*serve"], capture_output=True)
        await asyncio.sleep(2)
        
        async with Client(
            mode="api",
            auto_start_server=True,
            keep_server_running=False
        ) as client:
            assert client.get_mode() == "api"
            
            # Server should be running now
            result = await client.execute_task(
                protocol="mcp/v1",
                method="mcp/tool.echo",
                params={"message": "server test"},
                name="Server Test"
            )
            assert result.status == "completed"
    
    @pytest.mark.asyncio
    async def test_keep_server_running_flag(self):
        """Test keep_server_running flag behavior"""
        async with Client(
            mode="api",
            auto_start_server=True,
            keep_server_running=True
        ) as client:
            assert client.get_mode() == "api"
            
        # After exiting, server should still be running
        # Try connecting again without auto-start
        async with Client(
            mode="api",
            auto_start_server=False
        ) as client:
            # Should connect to existing server
            assert client.get_mode() == "api"
    
    @pytest.mark.asyncio
    async def test_multiple_clients_same_server(self):
        """Test multiple clients connecting to same server"""
        # First client
        async with Client(mode="api", auto_start_server=True) as client1:
            result1 = await client1.execute_task(
                protocol="mcp/v1",
                method="mcp/tool.add",
                params={"a": 1, "b": 2},
                name="Client 1 Task"
            )
            
            # Second client while first is still active
            async with Client(mode="api", auto_start_server=False) as client2:
                result2 = await client2.execute_task(
                    protocol="mcp/v1",
                    method="mcp/tool.multiply",
                    params={"a": 3, "b": 4},
                    name="Client 2 Task"
                )
                
                assert result1.status == "completed"
                assert result2.status == "completed"
                assert result1.result["result"] == 3
                assert result2.result["result"] == 12