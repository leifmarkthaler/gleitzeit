# Gleitzeit Python API Reference

## Table of Contents
- [Installation](#installation)
- [Quick Start](#quick-start)
- [GleitzeitClient Class](#gleitzeitclient-class)
- [Workflow Management](#workflow-management)
- [Batch Processing](#batch-processing)
- [Task Execution](#task-execution)
- [Advanced Examples](#advanced-examples)
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
        # Run a workflow from file
        results = await client.run_workflow("workflow.yaml")
        print(f"Workflow completed with {len(results)} task results")

asyncio.run(main())
```

## GleitzeitClient Class

### Constructor

```python
GleitzeitClient(
    persistence: str = "sqlite",
    db_path: Optional[str] = None,
    redis_url: Optional[str] = None,
    ollama_url: str = "http://localhost:11434",
    debug: bool = False
)
```

**Parameters:**
- `persistence` (str): Backend type for storing tasks and results
  - `"sqlite"` (default): File-based persistence
  - `"redis"`: Redis backend for distributed processing
  - `"memory"`: In-memory storage (useful for testing)
- `db_path` (Optional[str]): Path to SQLite database file
- `redis_url` (Optional[str]): Redis connection URL
- `ollama_url` (str): Ollama API endpoint for LLM operations
- `debug` (bool): Enable debug logging

**Example:**
```python
# Production setup with SQLite
client = GleitzeitClient(persistence="sqlite", db_path="/data/workflows.db")

# Distributed setup with Redis
client = GleitzeitClient(
    persistence="redis",
    redis_url="redis://localhost:6379/0"
)

# Testing with in-memory storage
client = GleitzeitClient(persistence="memory", debug=True)
```

### Context Manager

The client supports async context manager for automatic resource management:

```python
async with GleitzeitClient() as client:
    # Resources are automatically initialized
    results = await client.run_workflow("workflow.yaml")
    # Resources are automatically cleaned up
```

## Workflow Management

### run_workflow()

Execute a workflow from file or dictionary.

```python
async def run_workflow(
    workflow: Union[str, Dict[str, Any], Path]
) -> Dict[str, Any]
```

**Parameters:**
- `workflow`: Path to YAML/JSON file or workflow dictionary

**Returns:** Dictionary mapping task IDs to results

**Example:**
```python
async with GleitzeitClient() as client:
    # From YAML file
    results = await client.run_workflow("workflow.yaml")
    
    # From dictionary
    workflow_dict = {
        "name": "Data Processing",
        "tasks": [
            {
                "name": "Process Data",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "file": "process_data.py",
                    "args": {"input": "data.csv"}
                }
            }
        ]
    }
    results = await client.run_workflow(workflow_dict)
```

### create_workflow()

Create a workflow programmatically.

```python
async def create_workflow(
    name: str,
    tasks: List[Dict[str, Any]],
    description: Optional[str] = None
) -> Workflow
```

**Parameters:**
- `name`: Workflow name
- `tasks`: List of task definitions
- `description`: Optional workflow description

**Returns:** Workflow object

**Example:**
```python
async with GleitzeitClient() as client:
    workflow = await client.create_workflow(
        name="Multi-Stage Processing",
        description="Process data through multiple stages",
        tasks=[
            {
                "name": "Load Data",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "import pandas as pd; df = pd.read_csv('data.csv'); result = df.to_dict()"
                }
            },
            {
                "name": "Transform Data",
                "protocol": "python/v1",
                "method": "python/execute",
                "dependencies": ["Load Data"],
                "params": {
                    "code": "data = ${Load Data.result}; # Transform data here"
                }
            },
            {
                "name": "Generate Report",
                "protocol": "llm/v1",
                "method": "llm/chat",
                "dependencies": ["Transform Data"],
                "params": {
                    "model": "llama3.2:latest",
                    "messages": [{
                        "role": "user",
                        "content": "Analyze this data: ${Transform Data.result}"
                    }]
                }
            }
        ]
    )
    
    results = await client.run_workflow(workflow)
```

### get_workflow_status()

Get the status of a running or completed workflow.

```python
async def get_workflow_status(workflow_id: str) -> Optional[Workflow]
```

**Example:**
```python
workflow = await client.run_workflow_async("workflow.yaml")
status = await client.get_workflow_status(workflow.id)
print(f"Status: {status.status}, Progress: {status.completed_tasks}/{status.total_tasks}")
```

## Batch Processing

### batch_process()

Process multiple files in parallel.

```python
async def batch_process(
    directory: Optional[str] = None,
    files: Optional[List[str]] = None,
    pattern: str = "*",
    method: str = "llm/chat",
    prompt: str = "Analyze this file",
    model: str = "llama3.2:latest",
    max_concurrent: int = 5
) -> BatchResult
```

**Parameters:**
- `directory`: Directory to scan for files
- `files`: List of specific file paths
- `pattern`: Glob pattern for file matching
- `method`: Processing method to use
- `prompt`: Prompt for LLM methods
- `model`: Model to use for processing
- `max_concurrent`: Maximum parallel tasks

**Returns:** BatchResult object with processing results

**Example:**
```python
async with GleitzeitClient() as client:
    # Process all Python files in directory
    results = await client.batch_process(
        directory="src",
        pattern="**/*.py",
        method="llm/chat",
        prompt="Find potential bugs in this code",
        max_concurrent=10
    )
    
    print(f"Processed {results.total_files} files")
    print(f"Successful: {results.successful}")
    print(f"Failed: {results.failed}")
    
    # Access individual results
    for file_path, result in results.results.items():
        if result['status'] == 'success':
            print(f"{file_path}: {result['content'][:100]}...")
```

### batch_vision()

Process images in batch using vision models.

```python
async def batch_vision(
    directory: str,
    pattern: str = "*.{jpg,png,jpeg}",
    prompt: str = "Describe this image",
    model: str = "llava:latest"
) -> BatchResult
```

**Example:**
```python
async with GleitzeitClient() as client:
    results = await client.batch_vision(
        directory="images",
        pattern="*.png",
        prompt="Extract any text from this image"
    )
    
    # Save results to file
    results.save_to_json("vision_results.json")
    results.save_to_markdown("vision_results.md")
```

### batch_python()

Execute Python scripts on multiple data files.

```python
async def batch_python(
    script: str,
    data_files: List[str],
    max_concurrent: int = 5
) -> BatchResult
```

**Example:**
```python
async with GleitzeitClient() as client:
    # Process CSV files with a Python script
    results = await client.batch_python(
        script="process_csv.py",
        data_files=["data1.csv", "data2.csv", "data3.csv"],
        max_concurrent=3
    )
```

## Task Execution

### execute_python()

Execute Python code or scripts.

```python
async def execute_python(
    code: Optional[str] = None,
    file: Optional[str] = None,
    args: Optional[Dict[str, Any]] = None,
    timeout: int = 30
) -> Dict[str, Any]
```

**Parameters:**
- `code`: Python code to execute
- `file`: Path to Python file
- `args`: Arguments to pass to the script
- `timeout`: Execution timeout in seconds

**Example:**
```python
async with GleitzeitClient() as client:
    # Execute code directly
    result = await client.execute_python(
        code="import math; result = math.sqrt(16)",
        timeout=5
    )
    print(result['result'])  # 4.0
    
    # Execute a script file
    result = await client.execute_python(
        file="scripts/analyze.py",
        args={"input_file": "data.csv", "output_format": "json"}
    )
```

### chat()

Simple LLM chat completion.

```python
async def chat(
    prompt: str,
    model: str = "llama3.2:latest",
    temperature: float = 0.7
) -> str
```

**Example:**
```python
async with GleitzeitClient() as client:
    response = await client.chat(
        "Explain workflow orchestration in 2 sentences",
        model="llama3.2:latest"
    )
    print(response)
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

**Example:**
```python
async with GleitzeitClient() as client:
    description = await client.vision(
        "diagram.png",
        prompt="Explain the architecture shown in this diagram"
    )
```

## Advanced Examples

### Example 1: Data Processing Pipeline

```python
import asyncio
from gleitzeit import GleitzeitClient
from pathlib import Path

async def data_pipeline():
    async with GleitzeitClient() as client:
        # Create a complex workflow
        workflow = {
            "name": "Data Pipeline",
            "description": "Multi-stage data processing",
            "tasks": [
                {
                    "name": "Extract Data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "file": "extractors/db_extract.py",
                        "args": {"database": "production"}
                    }
                },
                {
                    "name": "Validate Data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "dependencies": ["Extract Data"],
                    "params": {
                        "file": "validators/data_validator.py",
                        "args": {"data": "${Extract Data.result}"}
                    }
                },
                {
                    "name": "Transform Data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "dependencies": ["Validate Data"],
                    "params": {
                        "file": "transformers/data_transformer.py",
                        "args": {"validated_data": "${Validate Data.result}"}
                    }
                },
                {
                    "name": "Generate Report",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "dependencies": ["Transform Data"],
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [{
                            "role": "system",
                            "content": "You are a data analyst. Generate insights from the data."
                        }, {
                            "role": "user",
                            "content": "Analyze: ${Transform Data.result}"
                        }]
                    }
                },
                {
                    "name": "Save Results",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "dependencies": ["Transform Data", "Generate Report"],
                    "params": {
                        "code": """
import json
from datetime import datetime

data = ${Transform Data.result}
report = "${Generate Report.response}"

output = {
    'timestamp': datetime.now().isoformat(),
    'data': data,
    'analysis': report
}

with open('results.json', 'w') as f:
    json.dump(output, f, indent=2)

result = f"Saved {len(data)} records with analysis"
"""
                    }
                }
            ]
        }
        
        results = await client.run_workflow(workflow)
        return results

asyncio.run(data_pipeline())
```

### Example 2: Document Batch Analysis

```python
import asyncio
from gleitzeit import GleitzeitClient

async def analyze_documents():
    async with GleitzeitClient(persistence="redis") as client:
        # First pass: Summarize all documents
        summaries = await client.batch_process(
            directory="documents",
            pattern="**/*.md",
            method="llm/chat",
            prompt="Create a 3-sentence summary",
            max_concurrent=10
        )
        
        # Second pass: Extract key topics
        topics_workflow = {
            "name": "Topic Extraction",
            "tasks": []
        }
        
        for file_path, summary in summaries.results.items():
            if summary['status'] == 'success':
                topics_workflow['tasks'].append({
                    "name": f"Extract_{Path(file_path).stem}",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [{
                            "role": "user",
                            "content": f"Extract 5 key topics from: {summary['content']}"
                        }]
                    }
                })
        
        # Run topic extraction
        topics = await client.run_workflow(topics_workflow)
        
        # Generate final report
        all_topics = "\n".join([str(result) for result in topics.values()])
        report = await client.chat(
            f"Create a comprehensive report from these topics:\n{all_topics}"
        )
        
        return report

asyncio.run(analyze_documents())
```

### Example 3: Parallel Processing with Dependencies

```python
import asyncio
from gleitzeit import GleitzeitClient

async def parallel_processing():
    async with GleitzeitClient() as client:
        workflow = {
            "name": "Parallel Processing",
            "tasks": [
                # Three parallel data sources
                {
                    "name": "Source_A",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"file": "fetch_source_a.py"}
                },
                {
                    "name": "Source_B",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"file": "fetch_source_b.py"}
                },
                {
                    "name": "Source_C",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"file": "fetch_source_c.py"}
                },
                # Merge when all complete
                {
                    "name": "Merge_Data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "dependencies": ["Source_A", "Source_B", "Source_C"],
                    "params": {
                        "code": """
a = ${Source_A.result}
b = ${Source_B.result}
c = ${Source_C.result}
result = {'merged': a + b + c, 'count': len(a) + len(b) + len(c)}
"""
                    }
                },
                # Parallel analysis
                {
                    "name": "Statistical_Analysis",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "dependencies": ["Merge_Data"],
                    "params": {"file": "stats_analysis.py"}
                },
                {
                    "name": "ML_Prediction",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "dependencies": ["Merge_Data"],
                    "params": {"file": "ml_predict.py"}
                },
                # Final report combining both analyses
                {
                    "name": "Final_Report",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "dependencies": ["Statistical_Analysis", "ML_Prediction"],
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [{
                            "role": "user",
                            "content": "Create report from stats: ${Statistical_Analysis.result} and predictions: ${ML_Prediction.result}"
                        }]
                    }
                }
            ]
        }
        
        results = await client.run_workflow(workflow)
        return results["Final_Report"]

asyncio.run(parallel_processing())
```

## Error Handling

The client uses specific error classes for different scenarios:

```python
from gleitzeit.core.errors import (
    ProviderError,
    TaskError,
    WorkflowError,
    ErrorCode
)

async def robust_workflow():
    async with GleitzeitClient() as client:
        try:
            results = await client.run_workflow("workflow.yaml")
        except WorkflowError as e:
            if e.code == ErrorCode.WORKFLOW_VALIDATION_FAILED:
                print(f"Invalid workflow: {e.message}")
                # Fix workflow and retry
            elif e.code == ErrorCode.WORKFLOW_CIRCULAR_DEPENDENCY:
                print(f"Circular dependency detected: {e.data}")
        except TaskError as e:
            if e.code == ErrorCode.TASK_TIMEOUT:
                print(f"Task timed out: {e.data['task_id']}")
                # Retry with longer timeout
        except ProviderError as e:
            if e.code == ErrorCode.PROVIDER_NOT_AVAILABLE:
                print(f"Provider offline: {e.data['provider_id']}")
                # Use fallback provider
```

## Best Practices

1. **Always use context managers** for automatic resource cleanup
2. **Set appropriate timeouts** for long-running tasks
3. **Use batch processing** for multiple similar operations
4. **Leverage dependencies** for complex workflows
5. **Handle errors specifically** using error codes
6. **Use Redis backend** for distributed processing
7. **Enable debug mode** during development

## See Also

- [Workflow YAML Format](./WORKFLOW_FORMAT.md)
- [Error Reference](./ERROR_REFERENCE.md)
- [CLI Usage](./CLI_USAGE.md)