# Instructor Integration for Gleitzeit (Experimental/Not Integrated)

⚠️ **STATUS: Design Prototype Only - Not Actually Integrated** ⚠️

This is an experimental design for how [Instructor](https://github.com/jxnl/instructor) could be integrated with Gleitzeit to provide structured, validated LLM outputs using Pydantic models. **This code is not connected to Gleitzeit's execution engine and will not work without significant additional implementation.**

## Current State

### What Exists
- ✅ `InstructorProvider` class structure
- ✅ Schema conversion utilities (JSON Schema → Pydantic)
- ✅ Unit tests with mocks (18 passing)
- ✅ Demo code showing intended API
- ✅ Example workflow YAML

### What's Missing
- ❌ **Actual Instructor library integration** - Code imports but doesn't use Instructor
- ❌ **Registration with Gleitzeit** - Registry API mismatch prevents integration
- ❌ **Real LLM execution** - Would fail if called with actual requests
- ❌ **Workflow execution** - Cannot be used in real Gleitzeit workflows
- ❌ **Async implementation** - Instructor calls wrapped in sync executor (not implemented)

## Intended Features (Not Yet Implemented)

- **Structured Output Generation**: Would provide validated, typed responses from LLMs
- **Automatic Retries**: Would retry on validation failures with exponential backoff
- **Multi-Provider Support**: Would support OpenAI, Anthropic, Cohere, Mistral, and Ollama
- **Schema Validation**: Would use Pydantic models for validation
- **Workflow Integration**: Would work in Gleitzeit workflows

## Prerequisites (Not Yet Functional)

If this integration were complete, you would need:

```bash
# Install Instructor
pip install instructor

# Install provider SDKs as needed
pip install openai      # For OpenAI
pip install anthropic   # For Anthropic
pip install cohere      # For Cohere
pip install litellm     # For Ollama and other OpenAI-compatible APIs
```

## Intended API (Does Not Currently Work)

### How It Would Work (If Integrated)

```python
# This code shows the intended design but WILL NOT WORK
# because the provider is not integrated with Gleitzeit

from gleitzeit.experimental.instructor import InstructorProvider
from pydantic import BaseModel

class User(BaseModel):
    name: str
    age: int
    email: str

# This would create a provider (works)
provider = InstructorProvider(
    default_provider="openai",
    default_model="gpt-4"
)

# This would fail - no actual Instructor usage implemented
result = await provider.execute("llm/structured", {
    "schema": User.model_json_schema(),
    "messages": [
        {"role": "user", "content": "John Doe, 30 years old, john@example.com"}
    ]
})
# ❌ Would throw: "client.chat.completions.create" doesn't exist
```

### Workflow YAML

```yaml
name: "Structured Data Pipeline"
tasks:
  - id: "extract_info"
    method: "llm/structured"
    parameters:
      provider: "openai"
      model: "gpt-4"
      schema:
        name: "PersonInfo"
        properties:
          name:
            type: "string"
          age:
            type: "integer"
            minimum: 0
            maximum: 150
          email:
            type: "string"
            format: "email"
        required: ["name", "email"]
      messages:
        - role: "user"
          content: "Extract info: Jane Smith, 28, jane@techcorp.com"
```

## Supported Methods

### `llm/structured`
Generate structured output with schema validation.

**Parameters:**
- `schema`: Pydantic model or JSON Schema definition
- `messages`: List of chat messages
- `provider`: LLM provider (optional, uses default)
- `model`: Model name (optional, uses provider default)
- `max_retries`: Maximum validation retries (optional, default 3)

### `llm/extract`
Extract structured data from text.

**Parameters:**
- `text`: Text to extract from
- `schema`: Extraction schema
- `provider`: LLM provider (optional)
- `model`: Model name (optional)

### `llm/classify`
Classify text into predefined categories.

**Parameters:**
- `text`: Text to classify
- `categories`: List of category names
- `provider`: LLM provider (optional)
- `model`: Model name (optional)

## Provider Configuration

### OpenAI
```python
provider = InstructorProvider(
    default_provider="openai",
    default_model="gpt-4-turbo-preview"
)
# Requires: export OPENAI_API_KEY=...
```

### Anthropic
```python
provider = InstructorProvider(
    default_provider="anthropic",
    default_model="claude-3-opus-20240229"
)
# Requires: export ANTHROPIC_API_KEY=...
```

### Ollama (via LiteLLM)
```python
provider = InstructorProvider(
    default_provider="litellm",
    default_model="ollama/llama3.2"
)
# Requires: Ollama running locally
```

## Schema Definition

### Using Pydantic Models
```python
from pydantic import BaseModel, Field
from typing import List, Optional

class Product(BaseModel):
    name: str = Field(..., description="Product name")
    price: float = Field(..., gt=0, description="Price in USD")
    features: List[str] = Field(default_factory=list)
    in_stock: bool = Field(True)
    rating: Optional[float] = Field(None, ge=0, le=5)

# Use in provider
schema = Product.model_json_schema()
```

### Using JSON Schema
```python
schema = {
    "name": "Product",
    "properties": {
        "name": {"type": "string"},
        "price": {"type": "number", "minimum": 0},
        "features": {
            "type": "array",
            "items": {"type": "string"}
        },
        "in_stock": {"type": "boolean"}
    },
    "required": ["name", "price"]
}
```

## Advanced Examples

### Complex Nested Structures
```python
class Address(BaseModel):
    street: str
    city: str
    country: str

class Company(BaseModel):
    name: str
    employees: List[str]
    headquarters: Address
    revenue: float

# The provider handles nested structures automatically
```

### Extraction Pipeline
```yaml
tasks:
  - id: "extract_all"
    method: "llm/extract"
    parameters:
      text: "${input.document}"
      schema:
        name: "DocumentAnalysis"
        properties:
          entities:
            type: "array"
            items:
              type: "object"
              properties:
                name: {"type": "string"}
                type: {"type": "string"}
          key_points:
            type: "array"
            items: {"type": "string"}
          sentiment:
            type: "string"
            enum: ["positive", "negative", "neutral"]
          summary:
            type: "string"
            maxLength: 200
```

## Testing

Run the test suite:
```bash
# Run unit tests
pytest src/gleitzeit/experimental/instructor/test_instructor.py -v

# Run demo (shows API usage)
python src/gleitzeit/experimental/instructor/demo.py
```

## Limitations

- Requires Instructor library and provider SDKs to be installed
- API keys must be configured for each provider
- Synchronous Instructor calls are wrapped in async executor (minor performance impact)
- Complex schemas may require more tokens and increase costs

## Why This Doesn't Work Yet

### 1. Registry API Mismatch
The current code tries to register like this:
```python
registry.register_provider(provider)  # ❌ Wrong
```

But Gleitzeit's registry expects:
```python
registry.register_provider(
    provider_id="instructor",
    protocol_id="llm/structured", 
    provider_instance=provider,
    supported_methods={"llm/structured", "llm/extract", "llm/classify"}
)  # ✅ Correct
```

### 2. No Instructor Library Usage
The provider imports Instructor but never actually uses it:
```python
# Current (doesn't work):
response = client.chat.completions.create(...)  # ❌ client is never created

# Should be:
import instructor
from openai import OpenAI
client = instructor.from_openai(OpenAI())  # ✅ Properly wrapped client
response = client.chat.completions.create(
    response_model=PydanticModel,  # ✅ This is what Instructor does
    ...
)
```

### 3. No Integration Point
There's no code in Gleitzeit that loads or registers this provider. It would need to be added to Gleitzeit's startup sequence.

## What Would Be Needed for Real Integration

1. **Fix Registry Registration**
   - Update provider to match registry API
   - Add provider to Gleitzeit's startup

2. **Implement Instructor Usage**
   - Actually create Instructor clients
   - Use Instructor's response_model parameter
   - Handle validation and retries

3. **Async/Await Handling**
   - Instructor is synchronous
   - Need proper async wrapper or executor

4. **Test with Real LLMs**
   - Install dependencies
   - Set up API keys
   - Run actual LLM calls

5. **Update Workflow Engine**
   - Ensure method routing works
   - Test parameter substitution
   - Verify schema handling

## Actual Steps Needed to Make This Work

This is what someone would need to do to make this integration functional:

```python
# 1. Fix the provider registration
async def register_instructor_provider(registry):
    provider = InstructorProvider()
    await provider.initialize()
    
    # Use correct registry API
    registry.register_provider(
        provider_id="instructor",
        protocol_id="llm/structured",
        provider_instance=provider,
        supported_methods={"llm/structured", "llm/extract", "llm/classify"}
    )

# 2. Actually use Instructor in _structured_generate
import instructor
from openai import OpenAI

client = instructor.from_openai(OpenAI())
response = client.chat.completions.create(
    model=model,
    messages=messages,
    response_model=pydantic_model,  # ← This is the key Instructor feature
    max_retries=max_retries
)

# 3. Add to Gleitzeit startup
# In some initialization file:
from gleitzeit.experimental.instructor import setup_instructor
await setup_instructor(app.registry)
```

## Summary

**This is a design prototype showing how Instructor could be integrated with Gleitzeit, but it is not functional.** The code demonstrates the intended API and structure but lacks:

1. Actual Instructor library usage
2. Proper registration with Gleitzeit's registry
3. Integration with the execution engine
4. Real LLM provider connections
5. Async/sync handling

Consider this a **proof of concept** or **design document in code form** rather than a working integration.

## Resources

- [Instructor Documentation](https://instructor-ai.github.io/instructor/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [JSON Schema Specification](https://json-schema.org/)
- [Gleitzeit Documentation](../../README.md)

## License

This integration follows Gleitzeit's MIT license.