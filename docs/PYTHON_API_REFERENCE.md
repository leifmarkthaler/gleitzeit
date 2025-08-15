# Gleitzeit Python API Reference

## Table of Contents
- [Installation](#installation)
- [Quick Start](#quick-start)
- [GleitzeitClient Class](#gleitzeitclient-class)
- [Core Methods](#core-methods)
- [Workflow Methods](#workflow-methods)
- [Batch Processing Methods](#batch-processing-methods)
- [Convenience Functions](#convenience-functions)
- [Examples](#examples)
- [Error Handling](#error-handling)

## Installation

```bash
# Using pip
pip install -e .

# Using uv (recommended)
uv pip install -e .
```

## Quick Start

```python
import asyncio
from gleitzeit import GleitzeitClient

async def main():
    # Using context manager (recommended)
    async with GleitzeitClient() as client:
        response = await client.chat("Hello, how are you?")
        print(response)

asyncio.run(main())
```

## GleitzeitClient Class

### Constructor

```python
GleitzeitClient(
    persistence: str = "sqlite",
    db_path: Optional[str] = None,
    redis_url: Optional[str] = None,
    ollama_url: str = "http://localhost:11434"
)
```

**Parameters:**
- `persistence` (str): Backend type for storing tasks and results
  - `"sqlite"` (default): File-based persistence
  - `"redis"`: Redis backend for shared state
  - `"memory"`: In-memory storage (useful for testing)
- `db_path` (Optional[str]): Path to SQLite database file. Auto-generated if not provided
- `redis_url` (Optional[str]): Redis connection URL (default: `"redis://localhost:6379/0"`)
- `ollama_url` (str): Ollama API endpoint for LLM operations

**Example:**
```python
# Default SQLite backend
client = GleitzeitClient()

# Memory backend for testing
client = GleitzeitClient(persistence="memory")

# Redis backend with custom URL
client = GleitzeitClient(
    persistence="redis",
    redis_url="redis://localhost:6379/1"
)
```

### Async Context Manager

The client supports async context manager protocol for automatic resource management:

```python
async with GleitzeitClient() as client:
    # Client is automatically initialized
    result = await client.chat("Hello")
    # Client is automatically shut down when exiting
```

### Manual Lifecycle Management

```python
client = GleitzeitClient()
await client.initialize()  # Initialize resources
# ... use client ...
await client.shutdown()    # Clean up resources
```

## Core Methods

### chat()

Simple chat completion with an LLM.

```python
async def chat(
    prompt: str,
    model: str = "llama3.2:latest",
    system: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None
) -> str
```

**Parameters:**
- `prompt` (str): The user prompt/question
- `model` (str): LLM model to use (default: `"llama3.2:latest"`)
- `system` (Optional[str]): System prompt to set context
- `temperature` (float): Sampling temperature (0.0-2.0, default: 0.7)
- `max_tokens` (Optional[int]): Maximum tokens to generate

**Returns:** Generated text response as string

**Example:**
```python
async with GleitzeitClient() as client:
    # Simple chat
    response = await client.chat("What is the capital of France?")
    
    # With system prompt
    response = await client.chat(
        prompt="Translate: Hello, how are you?",
        system="You are a Spanish translator. Respond only in Spanish.",
        temperature=0.3
    )
```

### vision()

Analyze images using vision models.

```python
async def vision(
    image_path: str,
    prompt: str = "Describe this image",
    model: str = "llava:latest"
) -> str
```

**Parameters:**
- `image_path` (str): Path to the image file
- `prompt` (str): Question or instruction about the image
- `model` (str): Vision model to use (default: `"llava:latest"`)

**Returns:** Image analysis response as string

**Example:**
```python
async with GleitzeitClient() as client:
    description = await client.vision(
        image_path="photo.jpg",
        prompt="What objects are visible in this image?"
    )
```

### execute_python()

Execute a Python script file with optional context.

```python
async def execute_python(
    script_file: str,
    context: Optional[Dict[str, Any]] = None,
    timeout: int = 10
) -> Any
```

**Parameters:**
- `script_file` (str): Path to Python script file
- `context` (Optional[Dict[str, Any]]): Variables to pass to the script
- `timeout` (int): Execution timeout in seconds (default: 10)

**Returns:** Script execution result (type depends on script)

**Example:**
```python
async with GleitzeitClient() as client:
    # Execute script with context
    result = await client.execute_python(
        script_file="scripts/process_data.py",
        context={"data": [1, 2, 3], "multiplier": 2},
        timeout=30
    )
```

**Script example (`process_data.py`):**
```python
# The 'context' variable is automatically available
data = context['data']
multiplier = context['multiplier']

result = [x * multiplier for x in data]
# The 'result' variable is returned
```

## Workflow Methods

### run_workflow()

Run a workflow from a YAML file, dictionary, or Workflow object.

```python
async def run_workflow(
    workflow: Union[str, Path, Dict, Workflow]
) -> Dict[str, Any]
```

**Parameters:**
- `workflow`: Can be:
  - Path to YAML file (str or Path)
  - Dictionary defining the workflow
  - Workflow object

**Returns:** Dictionary of task results keyed by task ID

**Example:**
```python
async with GleitzeitClient() as client:
    # From YAML file
    results = await client.run_workflow("workflows/analysis.yaml")
    
    # From dictionary
    workflow_dict = {
        "name": "Simple Workflow",
        "tasks": [
            {
                "id": "task1",
                "method": "llm/chat",
                "params": {
                    "model": "llama3.2:latest",
                    "messages": [{"role": "user", "content": "Hello"}]
                }
            }
        ]
    }
    results = await client.run_workflow(workflow_dict)
    
    # Access results
    for task_id, result in results.items():
        print(f"{task_id}: {result}")
```

### create_workflow()

Create a workflow programmatically.

```python
async def create_workflow(
    name: str,
    tasks: List[Dict[str, Any]]
) -> Workflow
```

**Parameters:**
- `name` (str): Workflow name
- `tasks` (List[Dict[str, Any]]): List of task definitions

**Returns:** Workflow object that can be run with `run_workflow()`

**Example:**
```python
async with GleitzeitClient() as client:
    workflow = await client.create_workflow(
        name="Data Processing Pipeline",
        tasks=[
            {
                "id": "generate",
                "method": "python/execute",
                "params": {
                    "file": "scripts/generate_data.py",
                    "timeout": 5
                }
            },
            {
                "id": "analyze",
                "method": "llm/chat",
                "dependencies": ["generate"],
                "params": {
                    "model": "llama3.2:latest",
                    "messages": [{
                        "role": "user",
                        "content": "Analyze this data: ${generate.result}"
                    }]
                }
            }
        ]
    )
    
    results = await client.run_workflow(workflow)
```

## Batch Processing Methods

### batch_process()

Process multiple files in batch.

```python
async def batch_process(
    directory: Optional[str] = None,
    files: Optional[List[str]] = None,
    pattern: str = "*",
    method: str = "llm/chat",
    prompt: str = "Analyze this file",
    model: str = "llama3.2:latest",
    protocol: str = "llm/v1"
) -> Dict[str, Any]
```

**Parameters:**
- `directory` (Optional[str]): Directory to scan for files
- `files` (Optional[List[str]]): List of specific file paths
- `pattern` (str): Glob pattern for file matching (default: `"*"`)
- `method` (str): Processing method (default: `"llm/chat"`)
- `prompt` (str): Prompt for LLM processing
- `model` (str): Model to use
- `protocol` (str): Protocol to use

**Returns:** Dictionary with batch processing results

**Example:**
```python
async with GleitzeitClient() as client:
    # Process all text files in a directory
    results = await client.batch_process(
        directory="documents",
        pattern="*.txt",
        prompt="Summarize this document",
        model="llama3.2:latest"
    )
    
    # Process specific files
    results = await client.batch_process(
        files=["doc1.txt", "doc2.txt"],
        prompt="Extract key points"
    )
```

### batch_chat()

Batch process text files with LLM (convenience method).

```python
async def batch_chat(
    directory: str,
    pattern: str = "*.txt",
    prompt: str = "Summarize this document",
    model: str = "llama3.2:latest"
) -> Dict[str, Any]
```

**Parameters:**
- `directory` (str): Directory containing files
- `pattern` (str): File pattern to match
- `prompt` (str): Prompt for each file
- `model` (str): LLM model to use

**Returns:** Batch processing results

**Example:**
```python
async with GleitzeitClient() as client:
    results = await client.batch_chat(
        directory="reports",
        pattern="*.md",
        prompt="Generate a 3-point summary"
    )
```

## Status and Results Methods

### get_workflow_status()

Get the status of a workflow.

```python
async def get_workflow_status(workflow_id: str) -> Optional[Workflow]
```

### get_task_result()

Get the result of a specific task.

```python
async def get_task_result(task_id: str) -> Optional[Any]
```

### list_workflows()

List recent workflows.

```python
async def list_workflows(limit: int = 20) -> List[Workflow]
```

## Convenience Functions

For quick one-off operations without managing client lifecycle:

```python
from gleitzeit.client import chat, vision, run_workflow, batch_process, execute_python

# Quick chat
response = await chat("Hello, world!")

# Quick vision analysis
description = await vision("image.jpg", "What is this?")

# Quick workflow execution
results = await run_workflow("workflow.yaml")

# Quick batch processing
results = await batch_process("docs", "*.txt", "Summarize")

# Quick Python execution
result = await execute_python("script.py", {"x": 10})
```

## Examples

### Example 1: Simple Chat Application

```python
import asyncio
from gleitzeit import GleitzeitClient

async def chat_loop():
    async with GleitzeitClient(persistence="memory") as client:
        print("Chat started. Type 'quit' to exit.")
        
        while True:
            user_input = input("\nYou: ")
            if user_input.lower() == 'quit':
                break
            
            response = await client.chat(user_input)
            print(f"AI: {response}")

asyncio.run(chat_loop())
```

### Example 2: Document Analysis Pipeline

```python
import asyncio
from gleitzeit import GleitzeitClient

async def analyze_documents():
    async with GleitzeitClient() as client:
        # Create analysis workflow
        workflow = await client.create_workflow(
            name="Document Analysis",
            tasks=[
                {
                    "id": "summarize",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [{
                            "role": "user",
                            "content": "Summarize the key points from this document: [document content]"
                        }]
                    }
                },
                {
                    "id": "extract_entities",
                    "method": "llm/chat",
                    "dependencies": ["summarize"],
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [{
                            "role": "user",
                            "content": "Extract all named entities from: ${summarize.response}"
                        }]
                    }
                }
            ]
        )
        
        results = await client.run_workflow(workflow)
        return results

asyncio.run(analyze_documents())
```

### Example 3: Mixed Python and LLM Processing

```python
import asyncio
from gleitzeit import GleitzeitClient

async def data_pipeline():
    async with GleitzeitClient() as client:
        workflow = await client.create_workflow(
            name="Data Pipeline",
            tasks=[
                {
                    "id": "generate_data",
                    "method": "python/execute",
                    "params": {
                        "file": "scripts/generate_data.py",
                        "context": {"count": 100},
                        "timeout": 10
                    }
                },
                {
                    "id": "analyze_data",
                    "method": "llm/chat",
                    "dependencies": ["generate_data"],
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [{
                            "role": "user",
                            "content": "Analyze this dataset and provide insights: ${generate_data.result}"
                        }],
                        "temperature": 0.5
                    }
                }
            ]
        )
        
        results = await client.run_workflow(workflow)
        
        # Access specific results
        data = results["generate_data"].result
        analysis = results["analyze_data"].result["response"]
        
        return {"data": data, "analysis": analysis}

asyncio.run(data_pipeline())
```

### Example 4: Batch Processing Documents

```python
import asyncio
from gleitzeit import GleitzeitClient

async def batch_analyze():
    async with GleitzeitClient() as client:
        # Process all markdown files
        results = await client.batch_chat(
            directory="documentation",
            pattern="*.md",
            prompt="Create a one-paragraph summary",
            model="llama3.2:latest"
        )
        
        print(f"Processed {results['total_files']} files")
        print(f"Successful: {results['successful']}")
        print(f"Failed: {results['failed']}")
        
        # Access individual file results
        for file_result in results.get('file_results', []):
            print(f"\nFile: {file_result['file_path']}")
            print(f"Summary: {file_result['result'][:200]}...")

asyncio.run(batch_analyze())
```

## Error Handling

The client methods raise exceptions for various error conditions:

```python
import asyncio
from gleitzeit import GleitzeitClient

async def safe_execution():
    async with GleitzeitClient() as client:
        try:
            result = await client.chat("Hello", model="invalid-model")
        except RuntimeError as e:
            print(f"Chat failed: {e}")
        
        try:
            result = await client.run_workflow("non_existent.yaml")
        except FileNotFoundError as e:
            print(f"Workflow file not found: {e}")
        except ValueError as e:
            print(f"Invalid workflow: {e}")
        
        try:
            result = await client.execute_python(
                "script.py",
                timeout=1  # Very short timeout
            )
        except TimeoutError as e:
            print(f"Script execution timed out: {e}")

asyncio.run(safe_execution())
```

## Configuration

### Environment Variables

The client respects these environment variables:

```bash
# Persistence backend
export GLEITZEIT_PERSISTENCE_BACKEND=sqlite  # or redis, memory

# Database paths
export GLEITZEIT_SQLITE_PATH=~/.gleitzeit/gleitzeit.db
export GLEITZEIT_REDIS_URL=redis://localhost:6379/0

# LLM Provider
export GLEITZEIT_OLLAMA_URL=http://localhost:11434

# Logging
export GLEITZEIT_LOG_LEVEL=INFO
```

### Backend Comparison

| Backend | Use Case | Persistence | Concurrency | Setup |
|---------|----------|-------------|-------------|-------|
| SQLite | Default, single-user | Yes | Limited | None |
| Redis | Multi-user, distributed | Yes | Excellent | Redis server |
| Memory | Testing, temporary | No | Good | None |

## Advanced Usage

### Custom Provider Configuration

```python
client = GleitzeitClient(
    persistence="sqlite",
    db_path="/custom/path/gleitzeit.db",
    ollama_url="http://remote-server:11434"
)
```

### Workflow with Conditional Logic

```python
workflow = await client.create_workflow(
    name="Conditional Processing",
    tasks=[
        {
            "id": "check_data",
            "method": "python/execute",
            "params": {
                "file": "scripts/validate_data.py"
            }
        },
        {
            "id": "process_valid",
            "method": "llm/chat",
            "dependencies": ["check_data"],
            "params": {
                "model": "llama3.2:latest",
                "messages": [{
                    "role": "user",
                    "content": "Process: ${check_data.result}"
                }]
            }
        }
    ]
)
```

### Parameter Substitution

Tasks can reference results from previous tasks using `${task_id.field}` syntax:

```python
tasks=[
    {
        "id": "task1",
        "method": "llm/chat",
        "params": {"messages": [{"role": "user", "content": "Generate a topic"}]}
    },
    {
        "id": "task2",
        "dependencies": ["task1"],
        "method": "llm/chat",
        "params": {
            "messages": [{
                "role": "user",
                "content": "Write about: ${task1.response}"  # Reference task1's response
            }]
        }
    }
]
```

## Performance Considerations

1. **Use memory backend for testing** - Faster, no disk I/O
2. **Batch processing is parallel** - Files are processed concurrently
3. **Set appropriate timeouts** - Prevent hanging on long operations
4. **Use Redis for distributed setups** - Better concurrency support
5. **Reuse client instances** - Avoid initialization overhead

## Troubleshooting

### Common Issues

1. **"Ollama not available"**
   - Ensure Ollama is running: `ollama serve`
   - Check the URL: default is `http://localhost:11434`

2. **"Task depends on unknown task"**
   - Ensure dependency task IDs match exactly
   - Dependencies must be defined before dependent tasks

3. **"Backend not initialized"**
   - Always use `async with` or call `await client.initialize()`

4. **Timeout errors**
   - Increase timeout for long-running operations
   - Check if scripts/models are actually running

## API Versioning

Current version: **0.0.4**

The API follows semantic versioning:
- **Major**: Breaking changes
- **Minor**: New features, backward compatible
- **Patch**: Bug fixes

## Support

- GitHub Issues: https://github.com/yourusername/gleitzeit/issues
- Documentation: https://gleitzeit.readthedocs.io
- Examples: `/examples` directory in the repository