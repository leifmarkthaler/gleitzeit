"""
Workflow Template Protocol Definition for Gleitzeit

Defines the template/v1 protocol for pre-built workflow templates.
Templates provide convenient shortcuts for common multi-step workflow patterns.
"""

from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType

# Workflow template protocol methods
template_protocol = ProtocolSpec(
    name="template",
    version="v1",
    description="Protocol for pre-built workflow templates that generate common multi-step patterns",
    methods={
        "template/research": MethodSpec(
            name="template/research",
            description="Generate a multi-step research workflow template",
            params_schema={
                "topic": ParameterSpec(
                    type=ParameterType.STRING,
                    required=True,
                    description="The research topic to investigate"
                ),
                "depth": ParameterSpec(
                    type=ParameterType.STRING,
                    required=False,
                    description="Research depth: shallow, medium, deep",
                    default="medium",
                    enum=["shallow", "medium", "deep"]
                ),
                "max_steps": ParameterSpec(
                    type=ParameterType.INTEGER,
                    required=False,
                    description="Maximum number of research steps to perform",
                    default=5,
                    minimum=1,
                    maximum=10
                )
            },
            returns_schema=ParameterSpec(
                type=ParameterType.OBJECT,
                properties={
                    "template_type": ParameterSpec(type=ParameterType.STRING),
                    "workflow_id": ParameterSpec(type=ParameterType.STRING),
                    "topic": ParameterSpec(type=ParameterType.STRING),
                    "status": ParameterSpec(type=ParameterType.STRING),
                    "steps_planned": ParameterSpec(type=ParameterType.INTEGER),
                    "execution_time": ParameterSpec(type=ParameterType.NUMBER),
                    "report": ParameterSpec(type=ParameterType.STRING),
                    "workflow_tasks": ParameterSpec(type=ParameterType.ARRAY),
                    "success": ParameterSpec(type=ParameterType.BOOLEAN)
                }
            )
        ),
        "template/code": MethodSpec(
            name="template/code",
            description="Generate a code development workflow template",
            params_schema={
                "task": ParameterSpec(
                    type=ParameterType.STRING,
                    required=True,
                    description="The coding task to complete"
                ),
                "language": ParameterSpec(
                    type=ParameterType.STRING,
                    required=False,
                    description="Programming language to use",
                    default="python",
                    enum=["python", "javascript", "typescript", "java", "go", "rust"]
                )
            },
            returns_schema=ParameterSpec(
                type=ParameterType.OBJECT,
                properties={
                    "template_type": ParameterSpec(type=ParameterType.STRING),
                    "workflow_id": ParameterSpec(type=ParameterType.STRING),
                    "task": ParameterSpec(type=ParameterType.STRING),
                    "language": ParameterSpec(type=ParameterType.STRING),
                    "status": ParameterSpec(type=ParameterType.STRING),
                    "steps_planned": ParameterSpec(type=ParameterType.INTEGER),
                    "execution_time": ParameterSpec(type=ParameterType.NUMBER),
                    "code": ParameterSpec(type=ParameterType.STRING),
                    "review": ParameterSpec(type=ParameterType.STRING),
                    "documentation": ParameterSpec(type=ParameterType.STRING),
                    "test_result": ParameterSpec(type=ParameterType.OBJECT),
                    "workflow_tasks": ParameterSpec(type=ParameterType.ARRAY),
                    "success": ParameterSpec(type=ParameterType.BOOLEAN)
                }
            )
        ),
        "template/analyze": MethodSpec(
            name="template/analyze",
            description="Generate a content analysis workflow template",
            params_schema={
                "content": ParameterSpec(
                    type=ParameterType.STRING,
                    required=True,
                    description="Content to analyze"
                ),
                "question": ParameterSpec(
                    type=ParameterType.STRING,
                    required=False,
                    description="Specific question to answer about the content",
                    default="Provide a comprehensive analysis"
                )
            },
            returns_schema=ParameterSpec(
                type=ParameterType.OBJECT,
                properties={
                    "template_type": ParameterSpec(type=ParameterType.STRING),
                    "workflow_id": ParameterSpec(type=ParameterType.STRING),
                    "status": ParameterSpec(type=ParameterType.STRING),
                    "execution_time": ParameterSpec(type=ParameterType.NUMBER),
                    "analysis": ParameterSpec(type=ParameterType.STRING),
                    "success": ParameterSpec(type=ParameterType.BOOLEAN)
                }
            )
        ),
        "template/chat": MethodSpec(
            name="template/chat",
            description="Generate a conversational workflow template",
            params_schema={
                "message": ParameterSpec(
                    type=ParameterType.STRING,
                    required=True,
                    description="Message to respond to"
                ),
                "session_id": ParameterSpec(
                    type=ParameterType.STRING,
                    required=False,
                    description="Session identifier for conversation continuity"
                )
            },
            returns_schema=ParameterSpec(
                type=ParameterType.OBJECT,
                properties={
                    "template_type": ParameterSpec(type=ParameterType.STRING),
                    "workflow_id": ParameterSpec(type=ParameterType.STRING),
                    "session_id": ParameterSpec(type=ParameterType.STRING),
                    "status": ParameterSpec(type=ParameterType.STRING),
                    "execution_time": ParameterSpec(type=ParameterType.NUMBER),
                    "response": ParameterSpec(type=ParameterType.STRING),
                    "success": ParameterSpec(type=ParameterType.BOOLEAN)
                }
            )
        )
    }
)

# Export the protocol
TEMPLATE_PROTOCOL_V1 = template_protocol