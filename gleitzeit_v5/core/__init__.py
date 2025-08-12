"""
Gleitzeit V5 Core Module

Core functionality for distributed task execution with protocol-based providers
and JSON-RPC 2.0 compliance.
"""

from .protocol import (
    ParameterType,
    ParameterSpec, 
    MethodSpec,
    ProtocolSpec,
    ProtocolRegistry,
    get_protocol_registry,
    register_protocol,
    get_protocol
)

from .jsonrpc import (
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCBatch,
    parse_jsonrpc_request,
    parse_jsonrpc_response
)

__all__ = [
    # Protocol system
    'ParameterType',
    'ParameterSpec',
    'MethodSpec', 
    'ProtocolSpec',
    'ProtocolRegistry',
    'get_protocol_registry',
    'register_protocol',
    'get_protocol',
    
    # JSON-RPC system
    'JSONRPCError',
    'JSONRPCRequest',
    'JSONRPCResponse', 
    'JSONRPCBatch',
    'parse_jsonrpc_request',
    'parse_jsonrpc_response'
]