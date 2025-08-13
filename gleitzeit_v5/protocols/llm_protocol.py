"""
LLM Protocol Specification for Gleitzeit

Defines the standard LLM protocol with JSON-RPC 2.0 compliance
and proper parameter substitution support.
"""

from ..core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType

# Message parameter for chat method
MESSAGE_PARAM = ParameterSpec(
    type=ParameterType.OBJECT,
    description="A single chat message",
    required=True,
    properties={
        "role": ParameterSpec(
            type=ParameterType.STRING,
            description="Message role",
            required=True,
            enum=["system", "user", "assistant"]
        ),
        "content": ParameterSpec(
            type=ParameterType.STRING,
            description="Message content (supports parameter substitution)",
            required=True,
            min_length=1
        )
    },
    additional_properties=False
)

# Messages array parameter
MESSAGES_PARAM = ParameterSpec(
    type=ParameterType.ARRAY,
    description="Array of chat messages",
    required=True,
    min_length=1,
    items=MESSAGE_PARAM
)

# Model parameter
MODEL_PARAM = ParameterSpec(
    type=ParameterType.STRING,
    description="Model name to use for generation",
    required=False,
    default="llama3.2",
    min_length=1
)

# Temperature parameter
TEMPERATURE_PARAM = ParameterSpec(
    type=ParameterType.NUMBER,
    description="Sampling temperature (0.0 to 2.0)",
    required=False,
    default=0.7,
    minimum=0.0,
    maximum=2.0
)

# Max tokens parameter
MAX_TOKENS_PARAM = ParameterSpec(
    type=ParameterType.INTEGER,
    description="Maximum tokens to generate",
    required=False,
    default=500,
    minimum=1,
    maximum=4096
)

# Response schema for chat completion
CHAT_RESPONSE_SCHEMA = ParameterSpec(
    type=ParameterType.OBJECT,
    description="Chat completion response",
    properties={
        "response": ParameterSpec(
            type=ParameterType.STRING,
            description="Generated response text",
            required=True
        ),
        "model": ParameterSpec(
            type=ParameterType.STRING,
            description="Model used for generation",
            required=True
        ),
        "done": ParameterSpec(
            type=ParameterType.BOOLEAN,
            description="Whether generation is complete",
            required=True
        ),
        "total_duration": ParameterSpec(
            type=ParameterType.INTEGER,
            description="Total duration in nanoseconds",
            required=False
        ),
        "prompt_eval_count": ParameterSpec(
            type=ParameterType.INTEGER,
            description="Number of tokens in prompt",
            required=False
        ),
        "eval_count": ParameterSpec(
            type=ParameterType.INTEGER,
            description="Number of tokens generated",
            required=False
        )
    },
    additional_properties=True
)

# Text completion response schema
COMPLETION_RESPONSE_SCHEMA = ParameterSpec(
    type=ParameterType.OBJECT,
    description="Text completion response",
    properties={
        "text": ParameterSpec(
            type=ParameterType.STRING,
            description="Generated text",
            required=True
        ),
        "model": ParameterSpec(
            type=ParameterType.STRING,
            description="Model used for generation",
            required=True
        ),
        "done": ParameterSpec(
            type=ParameterType.BOOLEAN,
            description="Whether generation is complete",
            required=True
        )
    },
    additional_properties=True
)

# LLM/Chat method
LLM_CHAT_METHOD = MethodSpec(
    name="llm/chat",
    description="Chat completion with message history and parameter substitution support",
    params_schema={
        "model": MODEL_PARAM,
        "messages": MESSAGES_PARAM,
        "temperature": TEMPERATURE_PARAM,
        "max_tokens": MAX_TOKENS_PARAM
    },
    returns_schema=CHAT_RESPONSE_SCHEMA,
    examples=[
        {
            "description": "Simple chat completion",
            "request": {
                "model": "llama3.2",
                "messages": [
                    {"role": "user", "content": "What is 2+2?"}
                ]
            },
            "response": {
                "response": "2+2 equals 4.",
                "model": "llama3.2", 
                "done": True
            }
        },
        {
            "description": "Chat with parameter substitution",
            "request": {
                "model": "llama3.2",
                "messages": [
                    {"role": "user", "content": "Calculate the square of ${number-generation.result.response}"}
                ]
            },
            "response": {
                "response": "64",
                "model": "llama3.2",
                "done": True
            }
        }
    ]
)

# LLM/Complete method
LLM_COMPLETE_METHOD = MethodSpec(
    name="llm/complete",
    description="Text completion with parameter substitution support",
    params_schema={
        "model": MODEL_PARAM,
        "prompt": ParameterSpec(
            type=ParameterType.STRING,
            description="Text prompt (supports parameter substitution)",
            required=True,
            min_length=1
        ),
        "temperature": TEMPERATURE_PARAM,
        "max_tokens": MAX_TOKENS_PARAM
    },
    returns_schema=COMPLETION_RESPONSE_SCHEMA,
    examples=[
        {
            "description": "Simple text completion",
            "request": {
                "model": "llama3.2",
                "prompt": "The capital of France is"
            },
            "response": {
                "text": "Paris.",
                "model": "llama3.2",
                "done": True
            }
        },
        {
            "description": "Completion with parameter substitution",
            "request": {
                "model": "llama3.2",
                "prompt": "The square root of ${math-task.result.value} is"
            },
            "response": {
                "text": "8",
                "model": "llama3.2", 
                "done": True
            }
        }
    ]
)

# Complete LLM Protocol Specification
LLM_PROTOCOL_V1 = ProtocolSpec(
    name="llm",
    version="v1",
    description="Large Language Model protocol with chat and completion capabilities",
    methods={
        "llm/chat": LLM_CHAT_METHOD,
        "llm/complete": LLM_COMPLETE_METHOD
    },
    author="Gleitzeit Team",
    license="MIT",
    tags=["llm", "ai", "language-model", "chat", "completion"]
)