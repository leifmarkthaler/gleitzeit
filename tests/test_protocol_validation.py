#!/usr/bin/env python3
"""
Test Protocol Validation and Method Routing
"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType

def test_param_validation():
    """Test parameter validation using MethodSpec"""
    # Create a method with parameter specifications
    method = MethodSpec(
        name="test/user",
        description="Test user method",
        params_schema={
            "name": ParameterSpec(type=ParameterType.STRING, required=True),
            "age": ParameterSpec(type=ParameterType.INTEGER, required=True, minimum=0),
            "email": ParameterSpec(type=ParameterType.STRING, required=False)
        }
    )
    
    # Valid params
    valid_params = {
        "name": "John Doe",
        "age": 30,
        "email": "john@example.com"
    }
    
    # Should not raise exception for valid params
    try:
        method.validate_params(valid_params)
        print("✅ Valid parameter validation test passed")
    except Exception as e:
        assert False, f"Valid params failed validation: {e}"
    
    # Test missing required field
    invalid_params1 = {
        "name": "John Doe"
        # Missing required "age" field
    }
    
    try:
        method.validate_params(invalid_params1)
        assert False, "Should have failed validation for missing required field"
    except Exception:
        print("✅ Missing required field validation test passed")
    
    # Test with minimal valid params
    minimal_params = {
        "name": "Jane Doe",
        "age": 25
    }
    
    try:
        method.validate_params(minimal_params)
        print("✅ Minimal valid parameter validation test passed")
    except Exception as e:
        assert False, f"Minimal valid params failed validation: {e}"

def test_method_routing():
    """Test method routing based on protocol"""
    protocol = ProtocolSpec(
        name="api",
        version="v1",
        description="API protocol",
        methods={
            "api/users/get": MethodSpec(
                name="api/users/get",
                description="Get user",
                params_schema={
                    "user_id": ParameterSpec(type=ParameterType.STRING, required=True)
                }
            ),
            "api/users/create": MethodSpec(
                name="api/users/create",
                description="Create user",
                params_schema={
                    "name": ParameterSpec(type=ParameterType.STRING, required=True),
                    "email": ParameterSpec(type=ParameterType.STRING, required=True)
                }
            )
        }
    )
    
    # Find method by name
    get_method = protocol.get_method("api/users/get")
    assert get_method is not None
    assert get_method.description == "Get user"
    
    create_method = protocol.get_method("api/users/create")
    assert create_method is not None
    assert create_method.description == "Create user"
    
    # Test protocol ID
    assert protocol.protocol_id == "api/v1"
    
    # Test method listing
    method_names = protocol.list_methods()
    assert "api/users/get" in method_names
    assert "api/users/create" in method_names
    
    print("✅ Method routing test passed")

def test_protocol_validation():
    """Test protocol validation with method calls"""
    protocol = ProtocolSpec(
        name="user",
        version="v1",
        description="User management protocol",
        methods={
            "user/create": MethodSpec(
                name="user/create",
                description="Create a user",
                params_schema={
                    "name": ParameterSpec(type=ParameterType.STRING, required=True),
                    "email": ParameterSpec(type=ParameterType.STRING, required=True),
                    "age": ParameterSpec(type=ParameterType.INTEGER, required=False, minimum=0)
                }
            )
        }
    )
    
    # Valid method call
    valid_params = {
        "name": "Alice Smith",
        "email": "alice@example.com",
        "age": 25
    }
    
    try:
        protocol.validate_method_call("user/create", valid_params)
        print("✅ Valid method call validation test passed")
    except Exception as e:
        assert False, f"Valid method call failed validation: {e}"
    
    # Test invalid method
    try:
        protocol.validate_method_call("user/delete", {})
        assert False, "Should have failed for non-existent method"
    except ValueError:
        print("✅ Invalid method validation test passed")
    
    # Test method with missing required params
    invalid_params = {
        "name": "Bob Jones"
        # Missing required "email" field
    }
    
    try:
        protocol.validate_method_call("user/create", invalid_params)
        assert False, "Should have failed for missing required params"
    except Exception:
        print("✅ Missing required params validation test passed")

def test_parameter_types():
    """Test different parameter types"""
    method = MethodSpec(
        name="test/types",
        description="Test different parameter types",
        params_schema={
            "text": ParameterSpec(type=ParameterType.STRING, required=True),
            "number": ParameterSpec(type=ParameterType.NUMBER, required=True),
            "flag": ParameterSpec(type=ParameterType.BOOLEAN, required=True),
            "count": ParameterSpec(type=ParameterType.INTEGER, required=False, minimum=0)
        }
    )
    
    # Valid params with different types
    valid_params = {
        "text": "Hello World",
        "number": 3.14,
        "flag": True,
        "count": 42
    }
    
    try:
        method.validate_params(valid_params)
        print("✅ Parameter types validation test passed")
    except Exception as e:
        assert False, f"Valid parameter types failed validation: {e}"
    
    # Test optional parameter
    minimal_params = {
        "text": "Hello",
        "number": 2.5,
        "flag": False
        # "count" is optional
    }
    
    try:
        method.validate_params(minimal_params)
        print("✅ Optional parameter test passed")
    except Exception as e:
        assert False, f"Optional parameter test failed: {e}"

def main():
    """Run all tests"""
    print("🧪 Testing Protocol Validation & Method Routing")
    print("=" * 50)
    
    try:
        test_param_validation()
        test_method_routing()
        test_protocol_validation()
        test_parameter_types()
        
        print("\n✅ All protocol validation tests PASSED")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())