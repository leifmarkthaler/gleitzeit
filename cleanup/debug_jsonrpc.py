#!/usr/bin/env python3
"""
Debug script to test JSONRPCResponse creation
"""

from gleitzeit_v4.core.jsonrpc import JSONRPCResponse

# Test creating a success response
try:
    result = {"simple": "test"}  # Try with simple result first
    
    # Try creating response directly
    print("Creating response directly...")
    response = JSONRPCResponse(id="test-id", result=result)
    print(f"Direct response created: {response}")
    
    print("Creating response via success method...")
    response2 = JSONRPCResponse.success("test-id", result)
    print(f"Success response created: {response2}")
    
except Exception as e:
    print(f"Error creating response: {e}")
    import traceback
    traceback.print_exc()