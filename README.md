# Gleitzeit - Protocol-Based Workflow Orchestration

A flexible workflow orchestration system that executes LLM operations, Python scripts, and tool integrations through a unified protocol-based architecture. Supports both API and native execution modes.

## Quick Start

```bash
# Install
pip install gleitzeit

# Run a workflow (auto-detects best mode)
gleitzeit run workflow.yaml
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

### Available Methods

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

## Workflow Definition

Workflows are defined in YAML with tasks and dependencies:

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
Process multiple files efficiently:
```python
results = await client.batch_process(
    directory="documents",
    pattern="**/*.txt",  # Recursive
    prompt="Extract key points",
    model="llama3.2",
    max_concurrent=10
)
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