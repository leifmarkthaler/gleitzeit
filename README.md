# Gleitzeit

A workflow orchestration system for coordinating LLM tasks, Python code execution, and tool integrations.
Supports parallel task execution, dependency management, and batch file processing.

## Quick Start

Get up and running with Gleitzeit in 5 minutes!

### Prerequisites

- Python 3.8 or higher
- Ollama installed (for LLM features)
- Redis (optional, for production persistence)
- Docker (optional, for isolated Python execution)

### Installation
```bash
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit
uv pip install -e .
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

**Using CLI**
```bash
gleitzeit run hello_workflow.yaml
```

**Or using Python**
```python
import asyncio
from gleitzeit import GleitzeitClient

async with GleitzeitClient() as client:
    result = await client.run_workflow("workflow.yaml")
```

## Core Concepts

### Protocols & Providers
- **Protocols**: Define standardized interfaces (LLM, Python, MCP)
- **Providers**: Implement protocol methods (OllamaProvider, PythonProvider, MCPHubProvider)
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

### Persistence
Gleitzeit includes a unified persistence layer with automatic fallback:
-  **Redis** (if available) - High performance
-  **SQLite** (fallback) - Local database
-  **Memory** (last resort) - In-process storage

## Python Client

### Using GleitzeitClient

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

### How It Works Internally

The `GleitzeitClient` handles all the complexity for you. When you use it in `native` mode, it automatically:

1. Creates and configures the ExecutionEngine
2. Registers all necessary providers 
3. Starts the engine (no manual start needed!)
4. Submits your workflow
5. Handles cleanup on exit

Here's what happens under the hood:

```python
# This is what GleitzeitClient does internally (you don't need to do this!)
async with GleitzeitClient(mode="native") as client:
    # Client automatically:
    # - Creates ExecutionEngine
    # - Registers providers (Ollama, Python, MCP, etc.)
    # - Starts the engine
    # - Now you just submit workflows:
    
    result = await client.run_workflow("workflow.yaml")
    # The engine is already running, workflow executes automatically!
```

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

### Creating and Submitting Tasks Programmatically

```python
from gleitzeit import GleitzeitClient

async with GleitzeitClient() as client:
    # Submit individual task
    result = await client.execute_task({
        "method": "llm/chat",
        "parameters": {
            "model": "llama3.2",
            "messages": [{"role": "user", "content": "Hello!"}]
        }
    })
    
    # Or create a workflow programmatically
    workflow = {
        "name": "My Dynamic Workflow",
        "tasks": [
            {
                "id": "task1",
                "method": "llm/chat",
                "parameters": {
                    "model": "llama3.2",
                    "messages": [{"role": "user", "content": "Write a haiku"}]
                }
            },
            {
                "id": "task2",
                "method": "python/execute",
                "dependencies": ["task1"],
                "parameters": {
                    "code": "print('Task 1 result:', '${task1.response}')"
                }
            }
        ]
    }
    
    # Submit the workflow
    results = await client.run_workflow(workflow)
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

### MCP (Model Context Protocol) Integration

Use external MCP server tools (requires server configuration):

```yaml
name: "MCP Tools Example"
tasks:
  # Read file using filesystem MCP server
  - id: "read_config"
    method: "mcp/tool.fs.read"
    parameters:
      path: "./config.json"
  
  # Write file using filesystem MCP server
  - id: "save_output"
    method: "mcp/tool.fs.write"
    dependencies: ["read_config"]
    parameters:
      path: "./output.json"
      content: "Processed: ${read_config.content}"
  
  # Combine with LLM for analysis
  - id: "analyze"
    method: "llm/chat"
    dependencies: ["read_config"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Analyze this configuration: ${read_config.content}"
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
**Provider**: MCPHubProvider  
**Methods**:
- `mcp/tool.*` - Execute MCP tools from registered servers
- `mcp/tools/list` - List available tools
- `mcp/servers` - List MCP servers  
- `mcp/ping` - Health check

**External Servers**: Any MCP-compliant server (stdio/websocket/HTTP)  
**Note**: Configure servers in `~/.gleitzeit/config.yaml` or via environment

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

## Resource Hubs

### OllamaHub
Manages Ollama LLM server instances:
- Auto-discovers running instances on configurable ports 
- Health monitoring and metrics collection
- Model-aware load balancing
- Connection pooling for performance

### DockerHub (Optional)
Manages Docker containers for isolated Python execution:
- Container lifecycle management
- Resource limits enforcement
- Security isolation

### MCPHub
Manages MCP (Model Context Protocol) server instances:
- Supports stdio, WebSocket, and HTTP connections
- Automatic tool discovery and registration
- Health monitoring and auto-restart
- Tool routing and load balancing
- Configurable via YAML or environment variables

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
mcp:
  auto_discover: true
  servers:
    - name: "filesystem"
      connection_type: "stdio"
      command: ["npx", "-y", "@modelcontextprotocol/server-filesystem"]
      tool_prefix: "fs."
```

### Environment Variables
```bash
# Ollama settings
export GLEITZEIT_OLLAMA_URL=http://localhost:11434
export GLEITZEIT_DEFAULT_MODEL=llama3.2

# Persistence
export GLEITZEIT_PERSISTENCE_TYPE=auto  # auto|redis|sql|memory
export GLEITZEIT_REDIS_URL=redis://localhost:6379
export GLEITZEIT_SQL_DB_PATH=~/.gleitzeit/workflows.db


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
- [MCP Integration](docs/mcp.md) - Model Context Protocol support
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
