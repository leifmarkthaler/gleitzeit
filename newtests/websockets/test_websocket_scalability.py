"""
Test WebSocket scalability and performance characteristics.
"""

import asyncio
import json
import pytest
import websockets
import time
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor


class TestWebSocketScalability:
    """Test WebSocket scalability and concurrent connection handling."""
    
    @pytest.fixture
    def ws_url(self) -> str:
        """WebSocket URL for testing."""
        return "ws://localhost:8080/events/stream"
    
    @pytest.mark.asyncio
    async def test_multiple_concurrent_connections(self, ws_url: str):
        """Test handling multiple concurrent WebSocket connections."""
        num_connections = 10
        connections = []
        
        try:
            # Open multiple connections concurrently
            tasks = []
            for i in range(num_connections):
                task = asyncio.create_task(
                    websockets.connect(f"{ws_url}?client_id=scale_test_{i}")
                )
                tasks.append(task)
            
            # Wait for all connections
            connections = await asyncio.gather(*tasks)
            assert len(connections) == num_connections
            
            # Verify all connections are functional
            for i, ws in enumerate(connections):
                # Get connection message
                conn_msg = json.loads(await ws.recv())
                assert conn_msg.get("type") == "connection"
                
                # Get auth message
                auth_msg = json.loads(await ws.recv())
                assert auth_msg.get("type") == "auth"
            
        finally:
            # Clean up all connections
            for ws in connections:
                if ws and not ws.closed:
                    await ws.close()
    
    @pytest.mark.asyncio
    async def test_connection_establishment_time(self, ws_url: str):
        """Test WebSocket connection establishment performance."""
        times = []
        
        for i in range(5):
            start = time.time()
            
            async with websockets.connect(f"{ws_url}?client_id=perf_test_{i}") as ws:
                # Wait for connection and auth
                await ws.recv()  # connection
                await ws.recv()  # auth
                
                elapsed = time.time() - start
                times.append(elapsed)
        
        avg_time = sum(times) / len(times)
        max_time = max(times)
        
        # Connection should be fast (under 1 second average)
        assert avg_time < 1.0, f"Average connection time too high: {avg_time:.3f}s"
        assert max_time < 2.0, f"Max connection time too high: {max_time:.3f}s"
        
        print(f"Connection times - Avg: {avg_time:.3f}s, Max: {max_time:.3f}s")
    
    @pytest.mark.asyncio
    async def test_subscription_performance(self, ws_url: str):
        """Test performance of subscription operations."""
        async with websockets.connect(ws_url) as websocket:
            # Skip initial messages
            await websocket.recv()  # connection
            await websocket.recv()  # auth
            
            # Time multiple subscriptions
            subscription_times = []
            event_types_list = [
                ["task:*"],
                ["workflow:*"],
                ["provider:*"],
                ["engine:*"],
                ["*"]
            ]
            
            for event_types in event_types_list:
                start = time.time()
                
                # Send subscription
                subscribe_msg = json.dumps({
                    "type": "subscribe",
                    "event_types": event_types
                })
                await websocket.send(subscribe_msg)
                
                # Wait for confirmation
                response = await websocket.recv()
                data = json.loads(response)
                assert data.get("status") == "subscribed"
                
                elapsed = time.time() - start
                subscription_times.append(elapsed)
            
            avg_time = sum(subscription_times) / len(subscription_times)
            
            # Subscriptions should be fast (under 100ms average)
            assert avg_time < 0.1, f"Average subscription time too high: {avg_time:.3f}s"
    
    @pytest.mark.asyncio
    async def test_message_throughput(self, ws_url: str):
        """Test message throughput for ping/pong operations."""
        async with websockets.connect(ws_url) as websocket:
            # Skip initial messages
            await websocket.recv()  # connection
            await websocket.recv()  # auth
            
            # Send multiple ping messages and measure throughput
            num_messages = 100
            start = time.time()
            
            for i in range(num_messages):
                # Send ping
                ping_msg = json.dumps({"type": "ping", "seq": i})
                await websocket.send(ping_msg)
                
                # Receive pong
                pong = json.loads(await websocket.recv())
                assert pong.get("type") == "pong"
            
            elapsed = time.time() - start
            throughput = num_messages / elapsed
            
            print(f"Message throughput: {throughput:.1f} messages/second")
            
            # Should handle at least 50 messages per second
            assert throughput > 50, f"Throughput too low: {throughput:.1f} msg/s"
    
    @pytest.mark.asyncio
    async def test_connection_memory_stability(self, ws_url: str):
        """Test that connections don't leak memory (basic check)."""
        # Open and close connections repeatedly
        for iteration in range(3):
            connections = []
            
            # Open 5 connections
            for i in range(5):
                ws = await websockets.connect(f"{ws_url}?client_id=mem_test_{iteration}_{i}")
                connections.append(ws)
                await ws.recv()  # connection
                await ws.recv()  # auth
            
            # Keep them open briefly
            await asyncio.sleep(0.5)
            
            # Close all connections
            for ws in connections:
                await ws.close()
            
            # Brief pause between iterations
            await asyncio.sleep(0.1)
        
        # If we get here without errors, basic stability is OK
        assert True
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self, ws_url: str):
        """Test concurrent operations on multiple connections."""
        num_connections = 5
        connections = []
        
        try:
            # Open connections
            for i in range(num_connections):
                ws = await websockets.connect(f"{ws_url}?client_id=concurrent_op_{i}")
                connections.append(ws)
                await ws.recv()  # connection
                await ws.recv()  # auth
            
            # Perform concurrent operations
            tasks = []
            for i, ws in enumerate(connections):
                # Each connection does different operations
                if i % 3 == 0:
                    # Subscribe
                    task = asyncio.create_task(self._subscribe_task(ws, ["task:*"]))
                elif i % 3 == 1:
                    # Ping
                    task = asyncio.create_task(self._ping_task(ws))
                else:
                    # Multiple operations
                    task = asyncio.create_task(self._mixed_operations(ws))
                
                tasks.append(task)
            
            # Wait for all operations
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Check no exceptions
            for result in results:
                if isinstance(result, Exception):
                    raise result
            
        finally:
            # Clean up
            for ws in connections:
                if ws and not ws.closed:
                    await ws.close()
    
    async def _subscribe_task(self, ws, event_types: List[str]) -> bool:
        """Helper: Subscribe to events."""
        subscribe_msg = json.dumps({
            "type": "subscribe",
            "event_types": event_types
        })
        await ws.send(subscribe_msg)
        response = json.loads(await ws.recv())
        return response.get("status") == "subscribed"
    
    async def _ping_task(self, ws) -> bool:
        """Helper: Send ping and wait for pong."""
        ping_msg = json.dumps({"type": "ping"})
        await ws.send(ping_msg)
        response = json.loads(await ws.recv())
        return response.get("type") == "pong"
    
    async def _mixed_operations(self, ws) -> bool:
        """Helper: Perform multiple operations."""
        # Subscribe
        await self._subscribe_task(ws, ["*"])
        # Ping
        await self._ping_task(ws)
        return True
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("num_connections", [1, 5, 10])
    async def test_scaling_connections(self, ws_url: str, num_connections: int):
        """Test scaling with different numbers of connections."""
        connections = []
        
        try:
            start = time.time()
            
            # Open connections
            for i in range(num_connections):
                ws = await websockets.connect(f"{ws_url}?client_id=scale_{num_connections}_{i}")
                connections.append(ws)
            
            # Verify all connected
            for ws in connections:
                conn_msg = json.loads(await ws.recv())
                assert conn_msg.get("type") == "connection"
                auth_msg = json.loads(await ws.recv())
                assert auth_msg.get("type") == "auth"
            
            elapsed = time.time() - start
            
            print(f"{num_connections} connections established in {elapsed:.3f}s")
            
            # Should complete in reasonable time
            assert elapsed < num_connections * 0.5  # Max 500ms per connection
            
        finally:
            # Clean up
            for ws in connections:
                if ws and not ws.closed:
                    await ws.close()