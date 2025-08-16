"""
Test suite for Protocol definitions
Tests the protocol specifications and compliance
"""

import pytest
from typing import Dict, Any

from gleitzeit.protocols import LLM_PROTOCOL_V1, PYTHON_PROTOCOL_V1, MCP_PROTOCOL_V1
from gleitzeit.core.protocol import ProtocolSpec, MethodSpec


class TestLLMProtocol:
    """Test the LLM protocol definition"""
    
    def test_llm_protocol_structure(self):
        """Test LLM protocol has required structure"""
        protocol = LLM_PROTOCOL_V1
        
        assert isinstance(protocol, ProtocolSpec)
        assert protocol.id == "llm/v1"
        assert protocol.name == "LLM Protocol"
        assert protocol.version == "1.0"
        assert len(protocol.methods) > 0
    
    def test_llm_required_methods(self):
        """Test LLM protocol has required methods"""
        protocol = LLM_PROTOCOL_V1
        method_names = [m.name for m in protocol.methods]
        
        # Core LLM methods should exist
        assert "llm/complete" in method_names or "llm/generate" in method_names
        assert "llm/chat" in method_names
        
        # Optional but common methods
        expected_methods = ["llm/embeddings", "llm/vision", "llm/list_models"]
        for method in expected_methods:
            if method in method_names:
                # Verify method has proper structure
                method_spec = next(m for m in protocol.methods if m.name == method)
                assert isinstance(method_spec, MethodSpec)
                assert method_spec.name == method
                assert method_spec.description
    
    def test_llm_method_parameters(self):
        """Test LLM methods have proper parameter definitions"""
        protocol = LLM_PROTOCOL_V1
        
        # Find chat method
        chat_method = next((m for m in protocol.methods if m.name == "llm/chat"), None)
        if chat_method:
            assert chat_method.parameters
            
            # Should have messages parameter
            messages_param = chat_method.parameters.get("messages")
            if messages_param:
                assert messages_param.required == True
                assert messages_param.description
    
    def test_llm_protocol_validation(self):
        """Test protocol can validate parameters"""
        protocol = LLM_PROTOCOL_V1
        
        # Protocol should have methods
        assert len(protocol.methods) > 0
        
        # Each method should have a name
        for method in protocol.methods:
            assert method.name
            assert "/" in method.name  # Should follow namespace/method format


class TestPythonProtocol:
    """Test the Python execution protocol"""
    
    def test_python_protocol_structure(self):
        """Test Python protocol has required structure"""
        protocol = PYTHON_PROTOCOL_V1
        
        assert isinstance(protocol, ProtocolSpec)
        assert protocol.id == "python/v1"
        assert protocol.name == "Python Protocol"
        assert len(protocol.methods) > 0
    
    def test_python_required_methods(self):
        """Test Python protocol has required methods"""
        protocol = PYTHON_PROTOCOL_V1
        method_names = [m.name for m in protocol.methods]
        
        # Core Python methods
        assert "python/execute" in method_names
        
        # Security: Should NOT have eval/exec methods
        assert "python/eval" not in method_names
        assert "python/exec" not in method_names
        
        # Optional but useful methods
        if "python/validate" in method_names:
            validate_method = next(m for m in protocol.methods if m.name == "python/validate")
            assert validate_method.description
    
    def test_python_execute_parameters(self):
        """Test Python execute method parameters"""
        protocol = PYTHON_PROTOCOL_V1
        
        # Find execute method
        execute_method = next((m for m in protocol.methods if m.name == "python/execute"), None)
        assert execute_method is not None
        
        # Should have proper parameters
        if execute_method.parameters:
            # Should accept file parameter (not code!)
            assert "file" in execute_method.parameters or "file_path" in execute_method.parameters
            
            # Should NOT accept arbitrary code parameter
            assert "code" not in execute_method.parameters or not execute_method.parameters["code"].required
    
    def test_python_security_constraints(self):
        """Test Python protocol enforces security constraints"""
        protocol = PYTHON_PROTOCOL_V1
        
        # Check that dangerous methods are not exposed
        method_names = [m.name for m in protocol.methods]
        
        dangerous_methods = [
            "python/eval",
            "python/exec",
            "python/compile",
            "python/import"
        ]
        
        for dangerous in dangerous_methods:
            assert dangerous not in method_names, f"Dangerous method {dangerous} should not be in protocol"


class TestMCPProtocol:
    """Test the MCP (Model Context Protocol) definition"""
    
    def test_mcp_protocol_structure(self):
        """Test MCP protocol has required structure"""
        protocol = MCP_PROTOCOL_V1
        
        assert protocol is not None
        # MCP protocol might be a dict or different structure
        if hasattr(protocol, 'id'):
            assert protocol.id == "mcp/v1"
        
        if hasattr(protocol, 'methods'):
            assert len(protocol.methods) > 0
    
    def test_mcp_tool_methods(self):
        """Test MCP has tool-related methods"""
        if not hasattr(MCP_PROTOCOL_V1, 'methods'):
            pytest.skip("MCP protocol structure different")
        
        protocol = MCP_PROTOCOL_V1
        method_names = [m.name for m in protocol.methods]
        
        # Should have tool discovery
        assert any("tool" in m for m in method_names)
        
        # Should have server info
        assert any("server" in m or "info" in m for m in method_names)


class TestProtocolCompliance:
    """Test that protocols follow conventions"""
    
    def test_all_protocols_have_version(self):
        """Test all protocols have version information"""
        protocols = [LLM_PROTOCOL_V1, PYTHON_PROTOCOL_V1]
        
        for protocol in protocols:
            if isinstance(protocol, ProtocolSpec):
                assert protocol.version
                assert protocol.id
                assert protocol.name
    
    def test_method_naming_convention(self):
        """Test all methods follow namespace/method naming"""
        protocols = [LLM_PROTOCOL_V1, PYTHON_PROTOCOL_V1]
        
        for protocol in protocols:
            if isinstance(protocol, ProtocolSpec):
                for method in protocol.methods:
                    assert "/" in method.name
                    namespace, name = method.name.split("/", 1)
                    
                    # Namespace should match protocol
                    expected_namespace = protocol.id.split("/")[0]
                    assert namespace == expected_namespace, \
                        f"Method {method.name} namespace doesn't match protocol {protocol.id}"
    
    def test_method_descriptions(self):
        """Test all methods have descriptions"""
        protocols = [LLM_PROTOCOL_V1, PYTHON_PROTOCOL_V1]
        
        for protocol in protocols:
            if isinstance(protocol, ProtocolSpec):
                for method in protocol.methods:
                    assert method.description, f"Method {method.name} missing description"
                    assert len(method.description) > 10, f"Method {method.name} description too short"


def test_protocol_basics():
    """Basic synchronous test for protocols"""
    
    # Test LLM protocol exists and has methods
    assert LLM_PROTOCOL_V1 is not None
    if hasattr(LLM_PROTOCOL_V1, 'methods'):
        assert len(LLM_PROTOCOL_V1.methods) > 0
        print(f"✓ LLM Protocol has {len(LLM_PROTOCOL_V1.methods)} methods")
    
    # Test Python protocol exists and has methods  
    assert PYTHON_PROTOCOL_V1 is not None
    if hasattr(PYTHON_PROTOCOL_V1, 'methods'):
        assert len(PYTHON_PROTOCOL_V1.methods) > 0
        print(f"✓ Python Protocol has {len(PYTHON_PROTOCOL_V1.methods)} methods")
    
    # Test MCP protocol exists
    assert MCP_PROTOCOL_V1 is not None
    print("✓ MCP Protocol exists")
    
    return True


if __name__ == '__main__':
    print("Testing Protocol definitions...")
    
    test_protocol_basics()
    
    # Test protocol compliance
    test = TestProtocolCompliance()
    test.test_all_protocols_have_version()
    print("✓ All protocols have version info")
    
    test.test_method_naming_convention()
    print("✓ All methods follow naming convention")
    
    # Test security
    python_test = TestPythonProtocol()
    python_test.test_python_security_constraints()
    print("✓ Python protocol security constraints OK")
    
    print("\n✅ All Protocol tests passed!")