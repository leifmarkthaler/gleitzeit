"""
Tests for automatic protocol generation in providers
"""

import pytest
import asyncio
from typing import Dict, Any, List
from unittest.mock import Mock, patch, AsyncMock

import sys
import os
# Add the src directory to path to avoid import issues
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.providers.simple import SimpleProvider
from gleitzeit.providers.ultra_simple import UltraSimpleProvider, method
from gleitzeit.providers.factory import ProviderFactory
# Import from the actual module path used by the implementation
from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterType


class TestProtocolGeneration:
    """Test automatic protocol generation in base provider"""
    
    def test_simple_provider_generates_protocol(self):
        """Test that SimpleProvider can auto-generate protocol from methods"""
        
        class TestProvider(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                return {"success": True}
            
            def get_supported_methods(self):
                return ["method1", "method2", "method3"]
        
        # Create with auto-generation enabled
        provider = TestProvider(
            provider_id="test_provider",
            protocol_id="test/v1",
            auto_generate_protocol=True
        )
        
        # Check protocol was generated
        protocol = provider.get_generated_protocol()
        assert protocol is not None
        assert isinstance(protocol, ProtocolSpec)
        # protocol_id is constructed from name/version in ProtocolSpec
        assert protocol.protocol_id == "test-provider/v1"
        assert len(protocol.methods) == 3
        assert "method1" in protocol.methods
        assert "method2" in protocol.methods
        assert "method3" in protocol.methods
    
    def test_ultra_provider_generates_from_decorated_methods(self):
        """Test that UltraSimpleProvider generates protocol from @method decorators"""
        
        class TestUltraProvider(UltraSimpleProvider):
            @method("process")
            async def process_data(self, text: str, mode: str = "default"):
                """Process some text"""
                return {"processed": text}
            
            @method("analyze", "analyze_data")
            async def analyze(self, data: list):
                """Analyze data"""
                return {"count": len(data)}
        
        provider = TestUltraProvider(
            provider_id="ultra_test",
            auto_generate_protocol=True
        )
        
        protocol = provider.get_generated_protocol()
        assert protocol is not None
        assert len(protocol.methods) == 3  # process, analyze, analyze_data
        
        # Check method specs
        process_spec = protocol.methods.get("process")
        assert process_spec is not None
        assert process_spec.description == "Process some text"
        
        # Check that parameters were properly extracted
        assert "text" in process_spec.params_schema
        assert "mode" in process_spec.params_schema
        
        # Check text parameter
        text_param = process_spec.params_schema["text"]
        assert text_param.type == ParameterType.STRING
        assert text_param.required == True
        
        # Check mode parameter (has default)
        mode_param = process_spec.params_schema["mode"]
        assert mode_param.type == ParameterType.STRING
        assert mode_param.required == False
        assert mode_param.default == "default"
    
    def test_protocol_generation_disabled_by_default(self):
        """Test that protocol generation is disabled by default"""
        
        class TestProvider(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                return {"success": True}
        
        # Create without enabling auto-generation
        provider = TestProvider(
            provider_id="test",
            protocol_id="test/v1"
        )
        
        protocol = provider.get_generated_protocol()
        assert protocol is None
    
    def test_protocol_generation_with_no_methods(self):
        """Test protocol generation when no methods are discovered"""
        
        class EmptyProvider(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                return {"success": True}
            
            def get_supported_methods(self):
                return []  # No methods
        
        provider = EmptyProvider(
            provider_id="empty",
            protocol_id="empty/v1",
            auto_generate_protocol=True
        )
        
        protocol = provider.get_generated_protocol()
        assert protocol is None  # No protocol generated for empty provider
    
    def test_auto_protocol_id_generation(self):
        """Test that protocol_id is auto-generated if not provided"""
        
        class TestProvider(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                return {}
            
            def get_supported_methods(self):
                return ["test"]
        
        provider = TestProvider(
            provider_id="auto_proto_test",
            protocol_id=None,  # No protocol_id provided
            auto_generate_protocol=True
        )
        
        protocol = provider.get_generated_protocol()
        assert protocol is not None
        # When protocol_id is None, it generates name from provider_id
        assert protocol.protocol_id == "auto-proto-test/v1"
    
    def test_protocol_registration(self):
        """Test that protocol can be auto-registered with registry"""
        
        mock_registry = Mock()
        mock_registry.register_protocol = Mock()
        
        class TestProvider(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                return {}
            
            def get_supported_methods(self):
                return ["test"]
        
        provider = TestProvider(
            provider_id="reg_test",
            protocol_id="reg/v1",
            auto_generate_protocol=True,
            register_protocol=True,
            protocol_registry=mock_registry
        )
        
        # Check that register was called
        mock_registry.register_protocol.assert_called_once()
        called_protocol = mock_registry.register_protocol.call_args[0][0]
        assert isinstance(called_protocol, ProtocolSpec)
        assert called_protocol.protocol_id == "reg-test/v1"  # Generated from name
    
    def test_mcp_style_capabilities(self):
        """Test protocol generation from MCP-style capabilities"""
        
        class MCPStyleProvider(SimpleProvider):
            def __init__(self, **kwargs):
                # Simulate MCP capabilities
                self.capabilities = {
                    "read_file": {
                        "description": "Read a file",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"]
                        },
                        "outputSchema": {
                            "type": "object",
                            "properties": {"content": {"type": "string"}}
                        }
                    },
                    "write_file": {
                        "description": "Write a file",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"}
                            }
                        },
                        "outputSchema": {"type": "object"}
                    }
                }
                super().__init__(**kwargs)
            
            async def execute(self, method: str, params: Dict[str, Any]):
                return {"mcp": "result"}
        
        provider = MCPStyleProvider(
            provider_id="mcp_test",
            protocol_id="mcp/v1",
            auto_generate_protocol=True
        )
        
        protocol = provider.get_generated_protocol()
        assert protocol is not None
        assert len(protocol.methods) == 2
        
        # Check MCP methods were discovered
        read_spec = protocol.methods.get("read_file")
        assert read_spec is not None
        assert read_spec.description == "Read a file"
        
        # Check params_schema contains ParameterSpec objects
        assert "path" in read_spec.params_schema
        path_param = read_spec.params_schema["path"]
        assert path_param.type == ParameterType.STRING
        assert path_param.required == True
        
        # Check write_file method
        write_spec = protocol.methods.get("write_file")
        assert write_spec is not None
        assert "path" in write_spec.params_schema
        assert "content" in write_spec.params_schema
        
        # Both parameters should be strings
        assert write_spec.params_schema["path"].type == ParameterType.STRING
        assert write_spec.params_schema["content"].type == ParameterType.STRING


class TestFactoryProtocolGeneration:
    """Test protocol generation in ProviderFactory"""
    
    def test_factory_auto_generates_protocols(self):
        """Test factory can auto-generate protocols for providers"""
        
        factory = ProviderFactory(
            auto_generate_protocols=True,
            auto_register_protocols=False
        )
        
        class TestProvider(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                return {"success": True}
            
            def get_supported_methods(self):
                return ["method1", "method2"]
        
        provider = factory.create_provider(
            TestProvider,
            provider_id="factory_test",
            protocol_id="factory/v1"
        )
        
        # Check factory stored the generated protocol
        assert "factory_test" in factory.generated_protocols
        protocol = factory.generated_protocols["factory_test"]
        assert isinstance(protocol, ProtocolSpec)
        assert len(protocol.methods) == 2
    
    def test_factory_per_provider_override(self):
        """Test that per-provider settings override factory defaults"""
        
        # Factory with generation disabled
        factory = ProviderFactory(
            auto_generate_protocols=False
        )
        
        class TestProvider(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                return {}
            
            def get_supported_methods(self):
                return ["test"]
        
        # Override to enable generation for this provider
        provider = factory.create_provider(
            TestProvider,
            provider_id="override_test",
            generate_protocol=True  # Override factory default
        )
        
        # Protocol should be generated despite factory default
        assert "override_test" in factory.generated_protocols
    
    def test_factory_with_registry_integration(self):
        """Test factory can auto-register protocols with registry"""
        
        mock_registry = Mock()
        mock_registry.register_protocol = Mock()
        
        factory = ProviderFactory(
            auto_generate_protocols=True,
            auto_register_protocols=True,
            protocol_registry=mock_registry
        )
        
        class TestProvider(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                return {}
            
            def get_supported_methods(self):
                return ["test"]
        
        provider = factory.create_provider(
            TestProvider,
            provider_id="reg_factory_test",
            protocol_id="reg/v1"
        )
        
        # Check registration was called
        mock_registry.register_protocol.assert_called()
    
    def test_factory_handles_generation_errors_gracefully(self):
        """Test factory handles protocol generation errors without failing"""
        
        factory = ProviderFactory(
            auto_generate_protocols=True
        )
        
        class BrokenProvider(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                return {}
            
            def get_supported_methods(self):
                raise Exception("Broken method discovery")
        
        # Should create provider despite generation failure
        provider = factory.create_provider(
            BrokenProvider,
            provider_id="broken_test",
            protocol_id="broken/v1",
            validate=False  # Skip validation
        )
        
        assert provider is not None
        assert provider.provider_id == "broken_test"
        # No protocol generated due to error
        assert "broken_test" not in factory.generated_protocols


class TestMCPProviderProtocolGeneration:
    """Test MCP provider with protocol generation"""
    
    @pytest.mark.asyncio
    async def test_mcp_provider_initialization(self):
        """Test MCP provider basic initialization"""
        from src.gleitzeit.providers.mcp_provider import MCPProvider
        
        # Create MCP provider
        mcp = MCPProvider(
            mcp_endpoint="http://test-mcp:3000",
            provider_id="test_mcp"
        )
        
        assert mcp.provider_id == "test_mcp"
        assert mcp.protocol_id == "mcp-test_mcp/auto"
        assert mcp.auto_generate_protocol is True
        assert mcp.mcp_endpoint == "http://test-mcp:3000"
    
    @pytest.mark.asyncio
    async def test_mcp_provider_handshake_and_protocol_generation(self):
        """Test MCP provider discovers capabilities and generates protocol"""
        from src.gleitzeit.providers.mcp_provider import MCPProvider
        
        class MockMCPProvider(MCPProvider):
            async def _send_jsonrpc_request(self, method: str, params: Any):
                """Mock the JSON-RPC request"""
                if method == "initialize":
                    return {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "protocolVersion": "0.1.0",
                            "capabilities": {
                                "tools": {
                                    "read_file": {
                                        "description": "Read file contents",
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {"path": {"type": "string"}}
                                        }
                                    },
                                    "write_file": {
                                        "description": "Write file contents",
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {
                                                "path": {"type": "string"},
                                                "content": {"type": "string"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                return {"jsonrpc": "2.0", "id": 1, "result": {}}
        
        mcp = MockMCPProvider(
            mcp_endpoint="http://mock-mcp:3000",
            provider_id="mock_mcp"
        )
        
        # Mock the session
        mcp._session = Mock()
        
        # Initialize (discovers capabilities)
        await mcp._mcp_handshake()
        
        # Check capabilities were discovered
        assert len(mcp.mcp_capabilities) == 2
        assert "read_file" in mcp.mcp_capabilities
        assert "write_file" in mcp.mcp_capabilities
        
        # Check protocol generation would work
        assert mcp.capabilities == mcp._convert_to_protocol_capabilities()
        assert len(mcp.capabilities) == 2
    
    @pytest.mark.asyncio
    async def test_mcp_provider_execute(self):
        """Test MCP provider forwards execution to service"""
        from src.gleitzeit.providers.mcp_provider import MCPProvider, MCPCapability
        
        class MockMCPProvider(MCPProvider):
            async def _send_jsonrpc_request(self, method: str, params: Any):
                return {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"content": f"Executed {method}"}
                }
        
        mcp = MockMCPProvider(
            mcp_endpoint="http://mock-mcp:3000",
            provider_id="exec_test"
        )
        
        # Mock capabilities
        mcp.mcp_capabilities = {
            "test_method": MCPCapability(
                name="test_method",
                description="Test",
                input_schema={"type": "object"},
                output_schema={"type": "object"}
            )
        }
        mcp._session = Mock()
        
        # Execute method
        result = await mcp.execute("test_method", {"param": "value"})
        assert result == {"content": "Executed test_method"}
        
        # Try unknown method
        with pytest.raises(Exception) as exc:
            await mcp.execute("unknown_method", {})
        assert "not supported" in str(exc.value)
    
    def test_mcp_filesystem_provider(self):
        """Test specialized MCP filesystem provider"""
        from src.gleitzeit.providers.mcp_provider import MCPFileSystemProvider
        
        fs_provider = MCPFileSystemProvider(
            mcp_endpoint="http://fs-mcp:3000"
        )
        
        assert fs_provider.provider_id == "mcp_filesystem"
        assert fs_provider.protocol_id == "mcp-filesystem/auto"
        assert fs_provider.mcp_name == "filesystem"
    
    def test_mcp_search_provider(self):
        """Test specialized MCP search provider"""
        from src.gleitzeit.providers.mcp_provider import MCPSearchProvider
        
        search_provider = MCPSearchProvider(
            mcp_endpoint="http://search-mcp:3000"
        )
        
        assert search_provider.provider_id == "mcp_search"
        assert search_provider.protocol_id == "mcp-search/auto"
        assert search_provider.mcp_name == "search"


class TestProtocolGenerationIntegration:
    """Integration tests for protocol generation"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_protocol_generation(self):
        """Test complete flow from provider creation to protocol usage"""
        
        # Create registry mock
        mock_registry = Mock()
        mock_registry.register_protocol = Mock()
        
        # Create factory with all features enabled
        factory = ProviderFactory(
            auto_generate_protocols=True,
            auto_register_protocols=True,
            protocol_registry=mock_registry,
            debug_mode=True
        )
        
        # Create a provider
        class E2EProvider(UltraSimpleProvider):
            @method("process")
            async def process(self, data: str):
                """Process data"""
                return {"processed": data.upper()}
            
            @method("analyze")
            async def analyze(self, items: list):
                """Analyze items"""
                return {"count": len(items)}
        
        provider = factory.create_provider(
            E2EProvider,
            provider_id="e2e_test",
            protocol_id="e2e/v1"
        )
        
        # Verify protocol was generated
        assert "e2e_test" in factory.generated_protocols
        protocol = factory.generated_protocols["e2e_test"]
        assert protocol.protocol_id == "e2e-test/v1"  # Generated from name
        assert len(protocol.methods) == 2
        
        # Verify protocol was registered
        mock_registry.register_protocol.assert_called_once()
        
        # Verify provider works
        result = await provider.execute("process", {"data": "hello"})
        assert result == {"processed": "HELLO"}
        
        result = await provider.execute("analyze", {"items": [1, 2, 3]})
        assert result == {"count": 3}
    
    def test_mixed_providers_with_and_without_protocols(self):
        """Test factory handling mix of providers with/without protocol generation"""
        
        factory = ProviderFactory(
            auto_generate_protocols=False  # Disabled by default
        )
        
        class Provider1(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                return {"provider": "1"}
            
            def get_supported_methods(self):
                return ["method1"]
        
        class Provider2(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                return {"provider": "2"}
            
            def get_supported_methods(self):
                return ["method2"]
        
        # Create first without protocol
        p1 = factory.create_provider(
            Provider1,
            provider_id="p1",
            protocol_id="p1/v1"
        )
        
        # Create second with protocol
        p2 = factory.create_provider(
            Provider2,
            provider_id="p2",
            protocol_id="p2/v1",
            generate_protocol=True  # Enable for this one
        )
        
        # Check only p2 has protocol
        assert "p1" not in factory.generated_protocols
        assert "p2" in factory.generated_protocols
        
        protocol = factory.generated_protocols["p2"]
        assert "method2" in protocol.methods