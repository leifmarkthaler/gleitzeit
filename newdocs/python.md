# Python API

Simple, async Python API for programmatic workflow orchestration.

## Quick Start

```python
from gleitzeit import Client

async with Client() as client:
    response = await client.chat("Hello!")
    print(response)
```

## Client Initialization

```python
from gleitzeit import Client

# Default - connects to local instance
client = Client()

# Custom configuration
client = Client(
    base_url="http://localhost:8080",
    timeout=60,
    max_retries=3
)

# Always use context manager
async with Client() as client:
    # Your code here
    pass
```

## Core Methods

### Chat with LLMs

```python
# Simple chat
response = await client.chat("What is Python?")

# With specific model
response = await client.chat(
    "Explain async/await",
    model="gpt-4",
    temperature=0.7
)

# With conversation history
messages = [
    {"role": "system", "content": "You are a helpful assistant"},
    {"role": "user", "content": "What is Python?"},
    {"role": "assistant", "content": "Python is a programming language..."},
    {"role": "user", "content": "What makes it popular?"}
]
response = await client.chat_messages(messages)
```

### Execute Python Code

```python
# Simple execution
result = await client.execute_python("return 2 + 2")
print(result)  # 4

# Multi-line code
code = """
import json
data = {"name": "Alice", "age": 30}
return json.dumps(data)
"""
result = await client.execute_python(code)

# With timeout
result = await client.execute_python(
    code="import time; time.sleep(1); return 'done'",
    timeout=10
)
```

### Batch Process Files

```python
# Process all text files
results = await client.batch_process(
    directory="documents",
    pattern="*.txt",
    prompt="Summarize this document in 3 sentences"
)

# With options
results = await client.batch_process(
    directory="reports",
    pattern="**/*.pdf",  # Recursive
    prompt="Extract key metrics",
    model="gpt-4",
    max_concurrent=10,
    output_dir="summaries"
)

# Process with custom template
results = await client.batch_process(
    directory="data",
    pattern="*.json",
    template={
        "method": "llm/chat",
        "messages": [
            {"role": "system", "content": "You are a data analyst"},
            {"role": "user", "content": "Analyze: ${file_content}"}
        ]
    }
)
```

### Run Workflows

```python
# Run workflow from file
results = await client.run_workflow("pipeline.yaml")

# Run workflow from dict
workflow = {
    "name": "My Workflow",
    "tasks": [
        {
            "id": "task1",
            "method": "llm/chat",
            "parameters": {
                "messages": [{"role": "user", "content": "Hello"}]
            }
        }
    ]
}
results = await client.run_workflow(workflow)

# Get specific task result
results = await client.run_workflow("workflow.yaml")
task1_result = results["task1"]["response"]
```

## Advanced Usage

### Streaming Responses

```python
# Stream chat responses
async for chunk in client.chat_stream("Tell me a story"):
    print(chunk, end="")

# Stream with callback
async def on_token(token):
    print(f"Token: {token}")

await client.chat(
    "Explain quantum computing",
    stream=True,
    on_token=on_token
)
```

### Error Handling

```python
from gleitzeit.errors import GleitzeitError, TimeoutError, ValidationError

try:
    response = await client.chat("Hello")
except TimeoutError:
    print("Request timed out")
except ValidationError as e:
    print(f"Invalid parameters: {e}")
except GleitzeitError as e:
    print(f"Error: {e}")
```

### Parallel Execution

```python
import asyncio

async with Client() as client:
    # Run multiple tasks in parallel
    tasks = [
        client.chat("Question 1"),
        client.chat("Question 2"),
        client.chat("Question 3")
    ]
    responses = await asyncio.gather(*tasks)
```

### Custom Providers

```python
# Use specific provider
response = await client.chat(
    "Hello",
    provider="openai",
    api_key="sk-..."  # Or set OPENAI_API_KEY
)

# Configure Ollama endpoint
client = Client(ollama_url="http://localhost:11434")
```

## Practical Examples

### Document Q&A System

```python
async def document_qa(file_path: str, question: str):
    async with Client() as client:
        # Read document
        with open(file_path) as f:
            content = f.read()
        
        # Ask question
        response = await client.chat(
            f"Document: {content}\n\nQuestion: {question}",
            model="gpt-4"
        )
        return response

# Usage
answer = await document_qa("report.txt", "What are the key findings?")
```

### Data Processing Pipeline

```python
async def process_data(data: list):
    async with Client() as client:
        # Step 1: Analyze data
        analysis = await client.chat(
            f"Analyze this data: {data}",
            model="llama3.2"
        )
        
        # Step 2: Generate report
        report = await client.chat(
            f"Create a report based on: {analysis}",
            model="llama3.2"
        )
        
        # Step 3: Save results
        result = await client.execute_python(f"""
            report = '''{report}'''
            with open('report.md', 'w') as f:
                f.write(report)
            return 'Report saved'
        """)
        
        return report
```

### Batch Analysis with Progress

```python
async def analyze_documents_with_progress(directory: str):
    async with Client() as client:
        files = Path(directory).glob("*.txt")
        total = len(list(files))
        
        results = {}
        for i, file in enumerate(files, 1):
            print(f"Processing {i}/{total}: {file.name}")
            
            result = await client.chat(
                f"Summarize: {file.read_text()}",
                model="llama3.2"
            )
            results[file.name] = result
            
        return results
```

## Type Hints

```python
from typing import Dict, List, Optional, Any
from gleitzeit import Client
from gleitzeit.models import WorkflowResult, TaskResult

async def run_analysis(
    data: str,
    model: str = "llama3.2",
    temperature: float = 0.7
) -> str:
    async with Client() as client:
        response: str = await client.chat(
            prompt=data,
            model=model,
            temperature=temperature
        )
        return response

async def run_workflow(
    workflow_path: str
) -> Dict[str, TaskResult]:
    async with Client() as client:
        results: WorkflowResult = await client.run_workflow(workflow_path)
        return results.tasks
```

## Best Practices

1. **Always use context managers** - Ensures proper cleanup
2. **Handle errors gracefully** - Use try/except blocks
3. **Set appropriate timeouts** - Prevent hanging requests
4. **Use batch processing** - For multiple similar operations
5. **Configure retry logic** - For reliability
6. **Log important operations** - For debugging

## API Reference

### Client Methods

| Method | Description | Returns |
|--------|-------------|---------|
| `chat(prompt, **kwargs)` | Chat with LLM | `str` |
| `chat_messages(messages, **kwargs)` | Chat with message history | `str` |
| `execute_python(code, **kwargs)` | Execute Python code | `Any` |
| `batch_process(directory, pattern, prompt, **kwargs)` | Process files in batch | `Dict[str, str]` |
| `run_workflow(workflow, **kwargs)` | Run workflow | `WorkflowResult` |
| `chat_stream(prompt, **kwargs)` | Stream chat response | `AsyncIterator[str]` |

### Common Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `model` | `str` | LLM model to use | `"llama3.2"` |
| `temperature` | `float` | Randomness (0-1) | `0.7` |
| `max_tokens` | `int` | Maximum response length | `None` |
| `timeout` | `int` | Request timeout in seconds | `30` |
| `retry` | `bool` | Enable automatic retries | `True` |
| `max_retries` | `int` | Maximum retry attempts | `3` |