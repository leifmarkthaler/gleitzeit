"""
Python Execution Protocol Specification for Gleitzeit

Defines the standard Python protocol with JSON-RPC 2.0 compliance
and proper parameter substitution support for code execution.
"""

from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType

# Python file parameter
FILE_PARAM = ParameterSpec(
    type=ParameterType.STRING,
    description="Path to Python file to execute (relative to scripts directory)",
    required=True,
    min_length=1
)

# Context parameter for shared variables
CONTEXT_PARAM = ParameterSpec(
    type=ParameterType.OBJECT,
    description="Context variables available to the code",
    required=False,
    default={},
    additional_properties=True
)

# Timeout parameter
TIMEOUT_PARAM = ParameterSpec(
    type=ParameterType.INTEGER,
    description="Execution timeout in seconds",
    required=False,
    default=30,
    minimum=1,
    maximum=300
)

# Response schema for Python execution
PYTHON_RESPONSE_SCHEMA = ParameterSpec(
    type=ParameterType.OBJECT,
    description="Python execution response",
    properties={
        "result": ParameterSpec(
            type=ParameterType.STRING,
            description="String representation of the execution result",
            required=True
        ),
        "output": ParameterSpec(
            type=ParameterType.STRING,
            description="Standard output captured during execution",
            required=False
        ),
        "error": ParameterSpec(
            type=ParameterType.STRING,
            description="Error message if execution failed",
            required=False
        ),
        "execution_time": ParameterSpec(
            type=ParameterType.NUMBER,
            description="Execution time in seconds",
            required=False
        ),
        "success": ParameterSpec(
            type=ParameterType.BOOLEAN,
            description="Whether execution was successful",
            required=True
        )
    },
    additional_properties=True
)

# Python/Execute method
PYTHON_EXECUTE_METHOD = MethodSpec(
    name="python/execute",
    description="Execute Python file with parameter substitution support",
    params_schema={
        "file": FILE_PARAM,
        "context": CONTEXT_PARAM,
        "timeout": TIMEOUT_PARAM
    },
    returns_schema=PYTHON_RESPONSE_SCHEMA,
    examples=[
        {
            "description": "Execute calculation script",
            "request": {
                "file": "scripts/calculate.py",
                "context": {"x": 5, "y": 3}
            },
            "response": {
                "result": "8",
                "output": "Sum: 8\n",
                "success": True,
                "execution_time": 0.001
            }
        },
        {
            "description": "Script with parameter substitution",
            "request": {
                "file": "scripts/process_data.py",
                "context": {"input_value": "${task1.result}"}
            },
            "response": {
                "result": "49",
                "output": "Square of 7 is 49\n",
                "success": True,
                "execution_time": 0.002
            }
        }
    ]
)

# Complete Python Protocol Specification
PYTHON_PROTOCOL_V1 = ProtocolSpec(
    name="python",
    version="v1",
    description="Python code execution protocol with sandboxed execution and parameter substitution",
    methods={
        "python/execute": PYTHON_EXECUTE_METHOD
    },
    author="Gleitzeit Team",
    license="MIT",
    tags=["python", "code-execution", "scripting", "computation"]
)