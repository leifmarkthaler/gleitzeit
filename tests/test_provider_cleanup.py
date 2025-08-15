#!/usr/bin/env python3
"""
Test Provider Cleanup and Session Management
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse

class SessionProvider:
    """Provider with session management"""
    
    def __init__(self):
        self.sessions = []
        self.initialized = False
        self.shutdown_called = False
    
    def get_supported_methods(self):
        return ["session/create", "session/close"]
    
    async def initialize(self):
        """Initialize provider"""
        self.initialized = True
        self.sessions = []
    
    async def cleanup(self):
        """Cleanup provider"""
        self.shutdown_called = True
        # Close all sessions
        for session in self.sessions:
            session["closed"] = True
        self.sessions.clear()
    
    async def handle_request(self, method: str, params: dict) -> dict:
        """Handle incoming request"""
        if method == "session/create":
            session_id = f"session-{len(self.sessions) + 1}"
            self.sessions.append({"id": session_id, "closed": False})
            return {"session_id": session_id}
        elif method == "session/close":
            session_id = params.get("session_id")
            for session in self.sessions:
                if session["id"] == session_id:
                    session["closed"] = True
            return {"status": "closed"}
        raise ValueError(f"Method not found: {method}")
    
    async def execute(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """Execute request (legacy compatibility)"""
        try:
            result = await self.handle_request(request.method, request.params or {})
            return JSONRPCResponse(result=result, id=request.id)
        except Exception as e:
            return JSONRPCResponse(error={"code": -32601, "message": str(e)}, id=request.id)

async def test_provider_initialization():
    """Test provider initialization"""
    provider = SessionProvider()
    assert not provider.initialized
    
    await provider.initialize()
    assert provider.initialized
    assert len(provider.sessions) == 0
    print("✅ Provider initialization test passed")

async def test_session_creation():
    """Test session creation and management"""
    provider = SessionProvider()
    await provider.initialize()
    
    # Create sessions
    request1 = JSONRPCRequest(method="session/create", params={}, id="1")
    response1 = await provider.execute(request1)
    assert response1.result["session_id"] == "session-1"
    
    request2 = JSONRPCRequest(method="session/create", params={}, id="2")
    response2 = await provider.execute(request2)
    assert response2.result["session_id"] == "session-2"
    
    assert len(provider.sessions) == 2
    assert all(not s["closed"] for s in provider.sessions)
    print("✅ Session creation test passed")

async def test_session_cleanup():
    """Test session cleanup on shutdown"""
    provider = SessionProvider()
    await provider.initialize()
    
    # Create some sessions
    for i in range(3):
        request = JSONRPCRequest(method="session/create", params={}, id=str(i))
        await provider.execute(request)
    
    assert len(provider.sessions) == 3
    assert all(not s["closed"] for s in provider.sessions)
    
    # Shutdown provider
    await provider.cleanup()
    
    assert provider.shutdown_called
    assert len(provider.sessions) == 0
    print("✅ Session cleanup test passed")

async def test_graceful_shutdown():
    """Test graceful shutdown with pending operations"""
    provider = SessionProvider()
    await provider.initialize()
    
    # Create sessions
    tasks = []
    for i in range(5):
        request = JSONRPCRequest(method="session/create", params={}, id=str(i))
        tasks.append(provider.execute(request))
    
    # Execute all requests
    await asyncio.gather(*tasks)
    
    assert len(provider.sessions) == 5
    
    # Close specific session
    close_request = JSONRPCRequest(
        method="session/close", 
        params={"session_id": "session-3"}, 
        id="close-1"
    )
    await provider.execute(close_request)
    
    # Check session 3 is closed
    session_3 = next(s for s in provider.sessions if s["id"] == "session-3")
    assert session_3["closed"]
    
    # Shutdown should close all remaining sessions
    await provider.cleanup()
    assert len(provider.sessions) == 0
    print("✅ Graceful shutdown test passed")

async def main():
    """Run all tests"""
    print("🧪 Testing Provider Cleanup & Session Management")
    print("=" * 50)
    
    try:
        await test_provider_initialization()
        await test_session_creation()
        await test_session_cleanup()
        await test_graceful_shutdown()
        
        print("\n✅ All provider cleanup tests PASSED")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))