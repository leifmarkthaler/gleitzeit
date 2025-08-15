"""
MCP Protocol Specification for Gleitzeit V4

Defines the MCP (Model Context Protocol) as a standard Gleitzeit protocol,
leveraging the existing protocol framework.
"""

from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType


def create_mcp_protocol() -> ProtocolSpec:
    """Create MCP protocol specification"""
    
    # Define common MCP methods
    methods = {
        # Core MCP methods
        "initialize": MethodSpec(
            name="initialize",
            description="Initialize MCP connection",
            parameters={
                "protocolVersion": ParameterSpec(
                    name="protocolVersion",
                    type=ParameterType.STRING,
                    description="MCP protocol version",
                    required=True
                ),
                "capabilities": ParameterSpec(
                    name="capabilities",
                    type=ParameterType.OBJECT,
                    description="Client capabilities",
                    required=True
                ),
                "clientInfo": ParameterSpec(
                    name="clientInfo", 
                    type=ParameterType.OBJECT,
                    description="Client information",
                    required=True
                )
            },
            returns=ParameterSpec(
                name="result",
                type=ParameterType.OBJECT,
                description="Server capabilities and info"
            )
        ),
        
        # Tool operations
        "tools/list": MethodSpec(
            name="tools/list",
            description="List available tools",
            parameters={},
            returns=ParameterSpec(
                name="tools",
                type=ParameterType.ARRAY,
                description="Array of available tools"
            )
        ),
        
        "tools/call": MethodSpec(
            name="tools/call",
            description="Call a tool",
            parameters={
                "name": ParameterSpec(
                    name="name",
                    type=ParameterType.STRING,
                    description="Tool name",
                    required=True
                ),
                "arguments": ParameterSpec(
                    name="arguments",
                    type=ParameterType.OBJECT,
                    description="Tool arguments",
                    required=False
                )
            },
            returns=ParameterSpec(
                name="result",
                type=ParameterType.OBJECT,
                description="Tool execution result"
            )
        ),
        
        # Resource operations
        "resources/list": MethodSpec(
            name="resources/list",
            description="List available resources",
            parameters={},
            returns=ParameterSpec(
                name="resources",
                type=ParameterType.ARRAY,
                description="Array of available resources"
            )
        ),
        
        "resources/read": MethodSpec(
            name="resources/read",
            description="Read a resource",
            parameters={
                "uri": ParameterSpec(
                    name="uri",
                    type=ParameterType.STRING,
                    description="Resource URI",
                    required=True
                )
            },
            returns=ParameterSpec(
                name="contents",
                type=ParameterType.ARRAY,
                description="Resource contents"
            )
        ),
        
        # Prompt operations
        "prompts/list": MethodSpec(
            name="prompts/list",
            description="List available prompts",
            parameters={},
            returns=ParameterSpec(
                name="prompts",
                type=ParameterType.ARRAY,
                description="Array of available prompts"
            )
        ),
        
        "prompts/get": MethodSpec(
            name="prompts/get",
            description="Get a prompt",
            parameters={
                "name": ParameterSpec(
                    name="name",
                    type=ParameterType.STRING,
                    description="Prompt name",
                    required=True
                ),
                "arguments": ParameterSpec(
                    name="arguments",
                    type=ParameterType.OBJECT,
                    description="Prompt arguments",
                    required=False
                )
            },
            returns=ParameterSpec(
                name="result",
                type=ParameterType.OBJECT,
                description="Generated prompt"
            )
        ),
        
        # Health check
        "ping": MethodSpec(
            name="ping",
            description="Health check ping",
            parameters={},
            returns=ParameterSpec(
                name="status",
                type=ParameterType.STRING,
                description="Ping response"
            )
        )
    }
    
    return ProtocolSpec(
        name="mcp",
        version="v1",
        description="Model Context Protocol (MCP) 2024-11-05",
        methods=methods
    )


# Create the MCP protocol instance
mcp_protocol = create_mcp_protocol()