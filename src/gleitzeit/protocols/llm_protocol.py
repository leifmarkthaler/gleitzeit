"""
LLM Protocol Specification for Gleitzeit

Defines the standard LLM protocol with JSON-RPC 2.0 compliance
and proper parameter substitution support.
"""

from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType

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
        "max_tokens": MAX_TOKENS_PARAM,
        "file_path": ParameterSpec(
            type=ParameterType.STRING,
            description="Path to text file to include in the conversation",
            required=False
        ),
        "files": ParameterSpec(
            type=ParameterType.ARRAY,
            description="Array of file paths for batch processing",
            required=False,
            items=ParameterSpec(
                type=ParameterType.STRING,
                description="File path"
            )
        ),
        "batch_mode": ParameterSpec(
            type=ParameterType.BOOLEAN,
            description="Enable batch mode to process files separately",
            required=False,
            default=False
        )
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

# Vision message parameter for vision method
VISION_MESSAGE_PARAM = ParameterSpec(
    type=ParameterType.OBJECT,
    description="A vision message with text and optional images",
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
        ),
        "images": ParameterSpec(
            type=ParameterType.ARRAY,
            description="Array of base64 encoded images",
            required=False,
            items=ParameterSpec(
                type=ParameterType.STRING,
                description="Base64 encoded image data"
            )
        )
    },
    additional_properties=False
)

# Vision messages array parameter
VISION_MESSAGES_PARAM = ParameterSpec(
    type=ParameterType.ARRAY,
    description="Array of vision messages",
    required=True,
    min_length=1,
    items=VISION_MESSAGE_PARAM
)

# Vision response schema
VISION_RESPONSE_SCHEMA = ParameterSpec(
    type=ParameterType.OBJECT,
    description="Vision analysis response",
    properties={
        "response": ParameterSpec(
            type=ParameterType.STRING,
            description="Vision analysis result",
            required=True
        ),
        "model": ParameterSpec(
            type=ParameterType.STRING,
            description="Model used for vision analysis",
            required=True
        ),
        "done": ParameterSpec(
            type=ParameterType.BOOLEAN,
            description="Whether analysis is complete",
            required=True
        ),
        "total_duration": ParameterSpec(
            type=ParameterType.INTEGER,
            description="Total duration in nanoseconds",
            required=False
        )
    },
    additional_properties=True
)

# LLM/Vision method
LLM_VISION_METHOD = MethodSpec(
    name="llm/vision",
    description="Vision analysis with multimodal LLM models",
    params_schema={
        "model": ParameterSpec(
            type=ParameterType.STRING,
            description="Vision model name to use",
            required=False,
            default="llava",
            min_length=1
        ),
        "messages": VISION_MESSAGES_PARAM,
        "temperature": TEMPERATURE_PARAM,
        "max_tokens": MAX_TOKENS_PARAM,
        "images": ParameterSpec(
            type=ParameterType.ARRAY,
            description="Array of base64 encoded images (alternative to embedding in messages)",
            required=False,
            items=ParameterSpec(
                type=ParameterType.STRING,
                description="Base64 encoded image data"
            )
        ),
        "image_path": ParameterSpec(
            type=ParameterType.STRING,
            description="Path to image file (alternative to base64 data)",
            required=False
        ),
        "image_paths": ParameterSpec(
            type=ParameterType.ARRAY,
            description="Array of image file paths for batch processing",
            required=False,
            items=ParameterSpec(
                type=ParameterType.STRING,
                description="Image file path"
            )
        ),
        "batch_mode": ParameterSpec(
            type=ParameterType.BOOLEAN,
            description="Enable batch mode to process images separately",
            required=False,
            default=False
        )
    },
    returns_schema=VISION_RESPONSE_SCHEMA,
    examples=[
        {
            "description": "Vision analysis with embedded image",
            "request": {
                "model": "llava",
                "messages": [
                    {
                        "role": "user",
                        "content": "What do you see in this image?",
                        "images": ["base64_image_data_here"]
                    }
                ]
            },
            "response": {
                "response": "I see a colorful geometric pattern with four distinct quadrants.",
                "model": "llava",
                "done": True
            }
        },
        {
            "description": "Vision analysis with separate images array",
            "request": {
                "model": "llava",
                "messages": [
                    {"role": "user", "content": "Describe the colors in this image"}
                ],
                "images": ["base64_image_data_here"]
            },
            "response": {
                "response": "The image contains red, blue, green, and yellow colors.",
                "model": "llava",
                "done": True
            }
        }
    ]
)

# Complete LLM Protocol Specification
LLM_PROTOCOL_V1 = ProtocolSpec(
    name="llm",
    version="v1",
    description="Large Language Model protocol with chat, completion, and vision capabilities",
    methods={
        "llm/chat": LLM_CHAT_METHOD,
        "llm/complete": LLM_COMPLETE_METHOD,
        "llm/vision": LLM_VISION_METHOD
    },
    author="Gleitzeit Team",
    license="MIT",
    tags=["llm", "ai", "language-model", "chat", "completion", "vision", "multimodal"]
)