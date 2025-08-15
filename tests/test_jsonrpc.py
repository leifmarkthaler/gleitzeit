#!/usr/bin/env python3
"""
Test JSON-RPC 2.0 Protocol Implementation
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse, JSONRPCError

def test_request_creation():
    """Test JSON-RPC request creation"""
    request = JSONRPCRequest(
        method="test.method",
        params={"param1": "value1"},
        id="req-123"
    )
    
    assert request.jsonrpc == "2.0"
    assert request.method == "test.method"
    assert request.params["param1"] == "value1"
    assert request.id == "req-123"
    
    # Test serialization
    json_data = request.to_dict()
    assert json_data["jsonrpc"] == "2.0"
    assert json_data["method"] == "test.method"
    print("✅ Request creation test passed")

def test_response_creation():
    """Test JSON-RPC response creation"""
    # Success response
    response = JSONRPCResponse(
        result={"status": "success"},
        id="req-123"
    )
    
    assert response.jsonrpc == "2.0"
    assert response.result["status"] == "success"
    assert response.id == "req-123"
    assert response.error is None
    
    json_data = response.to_dict()
    assert "result" in json_data
    assert "error" not in json_data
    print("✅ Response creation test passed")

def test_error_response():
    """Test JSON-RPC error response"""
    error = JSONRPCError(
        code=-32600,
        message="Invalid Request",
        data={"detail": "Missing method"}
    )
    
    response = JSONRPCResponse(
        error=error,
        id="req-456"
    )
    
    assert response.error.code == -32600
    assert response.error.message == "Invalid Request"
    assert response.result is None
    
    json_data = response.to_dict()
    assert "error" in json_data
    assert "result" not in json_data
    print("✅ Error response test passed")

def test_notification():
    """Test JSON-RPC notification (no id)"""
    notification = JSONRPCRequest(
        method="notify.event",
        params={"event": "task_completed"}
    )
    
    assert notification.id is None
    json_data = notification.to_dict()
    assert "id" not in json_data
    print("✅ Notification test passed")

def main():
    """Run all tests"""
    print("🧪 Testing JSON-RPC 2.0 Protocol")
    print("=" * 50)
    
    try:
        test_request_creation()
        test_response_creation()
        test_error_response()
        test_notification()
        
        print("\n✅ All JSON-RPC tests PASSED")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())