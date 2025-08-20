# Gleitzeit - Protocol-Based Workflow Orchestration

A flexible workflow orchestration system that executes LLM operations, Python scripts, and tool integrations through a unified protocol-based architecture. Supports both API and native execution modes.

## Quick Start

Get up and running with Gleitzeit in 5 minutes!

### Prerequisites

- Python 3.8 or higher
- Ollama installed (for LLM features)
- Redis (optional, for production persistence)
- Docker (optional, for isolated Python execution)

### Installation

```bash
# Install from PyPI
pip install gleitzeit

# Or install from source
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit
pip install -e .
```

### Step 1: Start Ollama

```bash
# Start Ollama server
ollama serve

# In another terminal, pull a model
ollama pull llama3.2
```

### Step 2: Create Your First Workflow

Create `hello_workflow.yaml`:

```yaml
name: "Hello World Workflow"
tasks:
  - id: "greeting"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Say hello and tell me an interesting fact!"

  - id: "followup"
    method: "llm/chat"
    dependencies: ["greeting"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "That's interesting! Now tell me more about: ${greeting.response}"
```

### Step 3: Run the Workflow

```bash
# Using CLI
gleitzeit run hello_workflow.yaml

# Or using Python
python -c "
import asyncio
from gleitzeit import GleitzeitClient

async def main():
    async with GleitzeitClient() as client:
        results = await client.run_workflow('hello_workflow.yaml')
        for task_id, result in results.items():
            print(f'{task_id}: {result.get(\"response\", result)}')

asyncio.run(main())
"
```

## Architecture Overview

Gleitzeit uses a **dual-mode architecture**:
- **API Mode**: REST API server for production deployments
- **Native Mode**: Direct execution engine for development/testing
- **Auto Mode**: Automatically selects the best available mode

## Core Concepts

### Protocols & Providers
- **Protocols**: Define standardized interfaces (LLM, Python, MCP, Template)
- **Providers**: Implement protocol methods (OllamaProvider, PythonProvider, etc.)
- **Registry**: Maps methods to providers and validates calls

### Resource Management
- **Hubs**: Manage compute resources (OllamaHub for LLM servers, DockerHub for containers)
- **ResourceManager**: Orchestrates multiple hubs and allocates resources
- **Auto-discovery**: Automatically finds available Ollama instances

### Workflow Execution
- **ExecutionEngine**: Central orchestrator for workflow execution
- **TaskQueue**: Manages task scheduling with dependency resolution
- **Parallel Execution**: Independent tasks run concurrently
- **Parameter Substitution**: Pass results between tasks using `${task_id.field}`

## Python Client

### Using GleitzeitClient (Recommended)

```python
from gleitzeit import GleitzeitClient

async with GleitzeitClient() as client:
    # Auto-detects API or native mode
    result = await client.run_workflow("workflow.yaml")
    
    # Force specific mode
    async with GleitzeitClient(mode="api") as client:
        # Uses REST API
        pass
    
    async with GleitzeitClient(mode="native") as client:
        # Direct execution engine
        pass
```

### Using ExecutionEngine Directly

For advanced use cases, you can use the ExecutionEngine directly:

```python
import asyncio
from gleitzeit.core.execution_engine import ExecutionEngine, ExecutionMode
from gleitzeit.core.workflow_loader import load_workflow_from_file
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.protocols import LLM_PROTOCOL_V1, PYTHON_PROTOCOL_V1

async def run_with_engine():
    # Setup persistence and registry
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    registry = ProtocolProviderRegistry()
    registry.register_protocol(LLM_PROTOCOL_V1)
    registry.register_protocol(PYTHON_PROTOCOL_V1)
    
    # Register providers
    ollama_provider = OllamaProvider(provider_id="ollama")
    await ollama_provider.initialize()
    registry.register_provider("ollama", "llm/v1", ollama_provider)
    
    python_provider = PythonProvider(provider_id="python")
    await python_provider.initialize()
    registry.register_provider("python", "python/v1", python_provider)
    
    # Create execution engine
    engine = ExecutionEngine(
        registry=registry,
        persistence=persistence,
        queue_manager=QueueManager(),
        dependency_resolver=DependencyResolver(),
        max_concurrent_tasks=5
    )
    
    # Start engine in event-driven mode (runs in background)
    engine_task = asyncio.create_task(engine.start(ExecutionMode.EVENT_DRIVEN))
    await asyncio.sleep(0.1)  # Let it start
    
    try:
        # Load and submit workflow - execution happens automatically!
        workflow = load_workflow_from_file("workflow.yaml")
        await engine.submit_workflow(workflow)
        
        # Wait for completion
        while True:
            all_done = all(
                engine.get_task_result(task.id) is not None 
                for task in workflow.tasks
            )
            if all_done:
                break
            await asyncio.sleep(0.5)
        
        # Get results
        for task in workflow.tasks:
            result = engine.get_task_result(task.id)
            print(f"{task.id}: {result.status}")
            
    finally:
        # Cleanup
        await engine.stop()
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass
        await ollama_provider.cleanup()
        await python_provider.cleanup()

# Run the engine
asyncio.run(run_with_engine())
```

**Important Notes:**
- When using the ExecutionEngine directly, you must start it with `engine.start(ExecutionMode.EVENT_DRIVEN)` as a background task
- After starting the engine, `submit_workflow()` alone triggers execution - no need to call `_execute_workflow()`
- The engine handles task scheduling and execution automatically
- Always cleanup properly by stopping the engine and canceling the background task

### Available Client Methods

```python
# Run workflows
result = await client.run_workflow("workflow.yaml")
result = await client.run_workflow(workflow_dict)

# Chat with LLMs (via Ollama)
response = await client.chat("Hello", model="llama3.2")

# Execute Python scripts
result = await client.execute_python_script("script.py", args={"key": "value"})

# Batch process files
results = await client.batch_process(
    directory="docs",
    pattern="*.txt",
    prompt="Summarize",
    model="llama3.2"
)

# Direct task execution
task_result = await client.execute_task(task)
```

### Submitting Individual Tasks with Engine

```python
from gleitzeit.core.models import Task

# Create a task
task = Task(
    id="my-task",
    method="llm/chat",
    params={
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "Hello!"}]
    }
)

# Submit task (execution happens automatically if engine is running)
await engine.submit_task(task)

# Submit multiple tasks as a workflow
from gleitzeit.core.models import Workflow

workflow = Workflow(
    name="My Workflow",
    tasks=[
        Task(id="task1", method="llm/chat", params={...}),
        Task(id="task2", method="python/execute", params={...}, 
             dependencies=["task1"])  # task2 waits for task1
    ]
)

# Submit workflow - all tasks execute automatically with dependency resolution
await engine.submit_workflow(workflow)
```

## Workflow Examples

### Basic Workflow with Dependencies

```yaml
name: "Analysis Pipeline"
tasks:
  - id: "load_data"
    method: "python/execute"
    parameters:
      script: "scripts/load_data.py"
      args:
        input: "data.csv"
  
  - id: "analyze"
    method: "llm/chat"
    dependencies: ["load_data"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Analyze this data: ${load_data.result}"
  
  - id: "save_results"
    method: "python/execute"
    dependencies: ["analyze"]
    parameters:
      script: "scripts/save_results.py"
      args:
        content: "${analyze.response}"
        output: "report.md"
```

### Chain Task Results

Create a story by chaining LLM responses:

```yaml
name: "Story Chain"
tasks:
  - id: "character"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Create a unique character for a story in one sentence"

  - id: "setting"
    method: "llm/chat"
    dependencies: ["character"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Create a setting for this character: ${character.response}"

  - id: "plot"
    method: "llm/chat"
    dependencies: ["character", "setting"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: |
            Write a short story plot with:
            Character: ${character.response}
            Setting: ${setting.response}
```

### Multi-Model Workflow

Use different models for different tasks:

```yaml
name: "Multi-Model Analysis"
tasks:
  - id: "fast_response"
    method: "llm/chat"
    parameters:
      model: "llama3.2:1b"  # Fast small model
      messages:
        - role: "user"
          content: "Quick summary of quantum computing"

  - id: "detailed_response"
    method: "llm/chat"
    parameters:
      model: "llama3.2:7b"  # Larger model for detail
      messages:
        - role: "user"
          content: "Explain quantum computing in detail with examples"

  - id: "combine"
    method: "llm/chat"
    dependencies: ["fast_response", "detailed_response"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: |
            Combine these two explanations into one comprehensive summary:
            Quick: ${fast_response.response}
            Detailed: ${detailed_response.response}
```

## Supported Protocols

### LLM Protocol (`llm/v1`)
**Provider**: OllamaProvider  
**Methods**:
- `llm/chat` - Text generation with conversation history
- `llm/vision` - Image analysis with vision models
- `llm/generate` - Direct text generation
- `llm/embeddings` - Generate text embeddings

**Models**: Any Ollama model (llama3.2, mistral, codellama, llava, etc.)

### Python Protocol (`python/v1`)
**Provider**: PythonProvider  
**Methods**:
- `python/execute` - Execute Python script files
- `python/validate` - Validate Python syntax
- `python/info` - Get provider information

**Security**: Scripts run in subprocess isolation or Docker containers

### MCP Protocol (`mcp/v1`)
**Provider**: SimpleMCPProvider  
**Methods**: Tool-specific methods via Model Context Protocol

### Template Protocol (`template/v1`)
**Provider**: TemplateProvider  
**Methods**:
- `template/research` - Generate multi-step research workflows
- `template/code` - Generate code development workflows
- `template/analyze` - Generate analysis workflows
- `template/chat` - Generate chat workflows

## CLI Commands

```bash
# Run workflows
gleitzeit run workflow.yaml
gleitzeit run workflow.yaml --local    # Force native mode
gleitzeit run workflow.yaml --watch    # Watch for changes

# Check status
gleitzeit status
gleitzeit status --resources

# Batch processing
gleitzeit batch documents --pattern "*.txt" --prompt "Summarize"

# Configuration
gleitzeit config show
gleitzeit config set default_model llama3.2

# Start API server
gleitzeit serve --port 8000
```

## Persistence

Gleitzeit includes a unified persistence layer with automatic fallback:

1. **Redis** (if available) - High performance
2. **SQLite** (fallback) - Local database
3. **Memory** (last resort) - In-process storage

Configuration via environment variables:
```bash
export GLEITZEIT_REDIS_URL=redis://localhost:6379
export GLEITZEIT_SQL_DB_PATH=~/.gleitzeit/workflows.db
export GLEITZEIT_PERSISTENCE_TYPE=auto  # auto|redis|sql|memory
```

## Resource Hubs

### OllamaHub
Manages Ollama LLM server instances:
- Auto-discovers running instances on ports 11434-11439
- Health monitoring and metrics collection
- Model-aware load balancing
- Connection pooling for performance

### DockerHub (Optional)
Manages Docker containers for isolated Python execution:
- Container lifecycle management
- Resource limits enforcement
- Security isolation

## Deployment Modes

### Development Mode
```python
# Direct execution engine, no server needed
client = GleitzeitClient(mode="native")
```

### Production Mode
```bash
# Start API server
gleitzeit serve --port 8000

# Client connects to API
client = GleitzeitClient(mode="api", api_host="localhost", api_port=8000)
```

### Auto Mode (Default)
```python
# Automatically uses API if available, otherwise native
client = GleitzeitClient()  # mode="auto" is default
```

## Configuration

### Config File (`~/.gleitzeit/config.yaml`)
```yaml
default_model: llama3.2
ollama:
  discovery_ports: [11434, 11435, 11436]
  auto_discover: true
persistence:
  type: auto
  redis:
    url: redis://localhost:6379
batch:
  max_concurrent: 5
  max_file_size: 1048576
```

### Environment Variables
```bash
# Ollama settings
export GLEITZEIT_OLLAMA_URL=http://localhost:11434
export GLEITZEIT_DEFAULT_MODEL=llama3.2

# Persistence
export GLEITZEIT_PERSISTENCE_TYPE=redis
export GLEITZEIT_REDIS_URL=redis://localhost:6379

# API server
export GLEITZEIT_API_HOST=0.0.0.0
export GLEITZEIT_API_PORT=8000
```

## Advanced Features

### Parallel Task Execution
Tasks without dependencies run concurrently:
```yaml
tasks:
  - id: "task1"  # Runs immediately
    method: "llm/chat"
  - id: "task2"  # Runs in parallel with task1
    method: "llm/chat"
  - id: "combine"  # Waits for both
    dependencies: ["task1", "task2"]
    method: "python/execute"
```

### Batch Processing

Process multiple files in parallel:

#### Create Test Files
```bash
mkdir documents
echo "Python is a great language" > documents/python.txt
echo "JavaScript powers the web" > documents/javascript.txt
echo "Rust is fast and safe" > documents/rust.txt
```

#### Using CLI
```bash
gleitzeit batch documents \
  --pattern "*.txt" \
  --prompt "Summarize this file and rate the programming language mentioned from 1-10"
```

#### Using Python API
```python
results = await client.batch_process(
    directory="documents",
    pattern="**/*.txt",  # Recursive
    prompt="Extract key points",
    model="llama3.2",
    max_concurrent=10
)
```

#### Batch Workflow
```yaml
name: "Batch Document Analysis"
type: "batch"

batch:
  directory: "documents"
  pattern: "*.txt"

template:
  method: "llm/chat"
  model: "llama3.2"
  messages:
    - role: "user"
      content: "Analyze this document and provide a summary"
```

### Dynamic Workflows with Python

Create workflows programmatically:

```python
import asyncio
from gleitzeit import GleitzeitClient

async def dynamic_workflow():
    async with GleitzeitClient() as client:
        # Generate a question
        question = await client.execute_task({
            "method": "llm/chat",
            "parameters": {
                "model": "llama3.2",
                "messages": [
                    {"role": "user", "content": "Generate a random question about science"}
                ]
            }
        })
        
        # Answer the generated question
        answer = await client.execute_task({
            "method": "llm/chat",
            "parameters": {
                "model": "llama3.2",
                "messages": [
                    {"role": "user", "content": f"Answer this: {question['response']}"}
                ]
            }
        })
        
        # Fact-check the answer
        verification = await client.execute_task({
            "method": "llm/chat",
            "parameters": {
                "model": "llama3.2",
                "messages": [
                    {"role": "user", 
                     "content": f"Is this answer correct? {answer['response']}"}
                ]
            }
        })
        
        return {
            "question": question['response'],
            "answer": answer['response'],
            "verification": verification['response']
        }

result = asyncio.run(dynamic_workflow())
print(result)
```

### Error Handling & Retries
```yaml
tasks:
  - id: "resilient_task"
    method: "llm/chat"
    retry:
      max_attempts: 3
      delay: 2
      exponential_backoff: true
    parameters:
      timeout: 30
```

## Testing

```bash
# Run all tests
pytest

# Run specific test suites
pytest tests/unit/
pytest tests/integration/
pytest tests/workflows/

# Test with real execution
python tests/workflow_test_suite.py --execute
```

## Common Issues & Solutions

### Ollama Connection Issues
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama
killall ollama
ollama serve
```

### Workflow Debugging
```bash
# Enable debug mode
export GLEITZEIT_DEBUG=true
gleitzeit run workflow.yaml

# Check task details
gleitzeit status --verbose
```

### Performance Tips
- Use `--local` flag to force native mode for development
- Configure Redis for production persistence
- Adjust `max_concurrent` for batch processing based on resources
- Use smaller models (e.g., llama3.2:1b) for simple tasks

## Documentation

- [Installation](docs/installation.md) - Detailed installation guide
- [Core Concepts](docs/concepts.md) - Understand the architecture
- [Workflows](docs/workflows.md) - Creating complex workflows
- [CLI Reference](docs/cli.md) - Command-line interface
- [Python API](docs/api.md) - Complete API reference
- [Providers](docs/providers.md) - Available providers and creating custom ones
- [Configuration](docs/configuration.md) - Configuration options
- [Troubleshooting](docs/troubleshooting.md) - Common issues and solutions

## Requirements

- Python 3.8+
- Ollama (for LLM operations)
- Redis (optional, for persistence)
- Docker (optional, for isolated Python execution)

## License

MIT