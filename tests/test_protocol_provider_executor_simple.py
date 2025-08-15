#!/usr/bin/env python3
"""
Test Protocol/Provider Framework
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType, get_protocol_registry
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse

def test_protocol_spec_creation():
    """Test protocol specification creation"""
    protocol = ProtocolSpec(
        name="compute",
        version="v1",
        description="Computation protocol",
        methods={
            "compute/add": MethodSpec(
                name="compute/add",
                description="Add two numbers",
                params_schema={
                    "a": ParameterSpec(type=ParameterType.NUMBER, required=True),
                    "b": ParameterSpec(type=ParameterType.NUMBER, required=True)
                }
            ),
            "compute/multiply": MethodSpec(
                name="compute/multiply",
                description="Multiply two numbers",
                params_schema={
                    "a": ParameterSpec(type=ParameterType.NUMBER, required=True),
                    "b": ParameterSpec(type=ParameterType.NUMBER, required=True)
                }
            )
        }
    )
    
    assert protocol.name == "compute"
    assert protocol.version == "v1"
    assert len(protocol.methods) == 2
    assert "compute/add" in protocol.methods
    print("✅ Protocol spec creation test passed")

def test_protocol_registry():
    """Test protocol registry"""
    registry = get_protocol_registry()
    
    # Register a protocol
    protocol = ProtocolSpec(
        name="test",
        version="v1",
        description="Test protocol",
        methods={
            "test/echo": MethodSpec(
                name="test/echo",
                description="Echo input",
                params_schema={}
            )
        }
    )
    
    registry.register(protocol)
    
    # Retrieve protocol
    retrieved = registry.get("test/v1")
    assert retrieved is not None
    assert retrieved.name == "test"
    assert len(retrieved.methods) == 1
    print("✅ Protocol registry test passed")

class ComputeProvider:
    """Provider implementing compute protocol"""
    
    def get_supported_methods(self):
        return ["compute/add", "compute/multiply"]
    
    async def initialize(self):
        pass
    
    async def cleanup(self):
        pass
    
    async def handle_request(self, method: str, params: dict) -> dict:
        """Handle computation request"""
        if method == "compute/add":
            a = params.get("a", 0)
            b = params.get("b", 0)
            return {"result": a + b}
        elif method == "compute/multiply":
            a = params.get("a", 0)
            b = params.get("b", 0)
            return {"result": a * b}
        raise ValueError(f"Method not found: {method}")
    
    async def execute(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """Execute computation (legacy compatibility)"""
        from gleitzeit.core.jsonrpc import JSONRPCError
        try:
            result = await self.handle_request(request.method, request.params or {})
            return JSONRPCResponse(result=result, id=request.id)
        except Exception as e:
            return JSONRPCResponse(
                error=JSONRPCError(code=-32601, message=str(e)), 
                id=request.id
            )

async def test_provider_execution():
    """Test provider execution with protocol"""
    provider = ComputeProvider()
    await provider.initialize()
    
    # Test addition
    add_request = JSONRPCRequest(
        method="compute/add",
        params={"a": 5, "b": 3},
        id="add-1"
    )
    add_response = await provider.execute(add_request)
    assert add_response.result["result"] == 8
    
    # Test multiplication
    mult_request = JSONRPCRequest(
        method="compute/multiply",
        params={"a": 4, "b": 7},
        id="mult-1"
    )
    mult_response = await provider.execute(mult_request)
    assert mult_response.result["result"] == 28
    
    await provider.cleanup()
    print("✅ Provider execution test passed")

async def test_method_validation():
    """Test method validation against protocol"""
    provider = ComputeProvider()
    
    # Check provider methods
    methods = provider.get_supported_methods()
    assert "compute/add" in methods
    assert "compute/multiply" in methods
    
    # Test invalid method
    invalid_request = JSONRPCRequest(
        method="compute/divide",
        params={"a": 10, "b": 2},
        id="div-1"
    )
    response = await provider.execute(invalid_request)
    assert response.error is not None
    assert response.error.code == -32601
    print("✅ Method validation test passed")

async def main():
    """Run all tests"""
    print("🧪 Testing Protocol/Provider Framework")
    print("=" * 50)
    
    try:
        test_protocol_spec_creation()
        test_protocol_registry()
        await test_provider_execution()
        await test_method_validation()
        
        print("\n✅ All protocol/provider tests PASSED")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))