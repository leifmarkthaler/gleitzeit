# Gleitzeit - Task and Workflow Orchestration

A protocol-based orchestration system designed for coordinating LLM workflows with multi-task, multi-method execution patterns.

**Version:** 0.0.4

## Core Features

- **LLM Workflow Coordination** - Orchestrate complex LLM interactions and chains
- **Multi-Task Workflows** - Combine different task types (LLM, Python, vision) in workflows
- **Dynamic Batch Processing** - Automatically discover and process files with glob patterns
- **Protocol-Based** - JSON-RPC 2.0 foundation with extensible provider system
- **Multiple Backends** - SQLite, Redis, or in-memory persistence
- **Dependency Management** - Tasks can depend on outputs from previous tasks
- **YAML Workflows** - Define complex workflows declaratively
- **Parameter Substitution** - Pass data between tasks with type preservation
- **Vision Support** - Process images with vision models (llava)
- **Python Integration** - Execute Python scripts with context passing

## Quick Start

### Requirements

- Python 3.8 or higher
- Redis (optional, for Redis backend)
- Ollama (optional, for LLM provider)

### Installation

#### Using uv (Recommended)
[uv](https://github.com/astral-sh/uv) is a fast Python package installer and resolver written in Rust.

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install in development mode
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit
uv pip install -e .

# Or install directly from GitHub
uv pip install git+https://github.com/leifmarkthaler/gleitzeit.git

# Build the package
uv build
```

#### Using pip
```bash
# Clone and install in development mode
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit
pip install -e .

# Or install directly from GitHub
pip install git+https://github.com/leifmarkthaler/gleitzeit.git
```

### Basic Usage

#### CLI Usage
```bash
# Submit a workflow
gleitzeit workflow submit examples/llm_workflow.yaml

# Check workflow status
gleitzeit workflow status WORKFLOW_ID

# View system status  
gleitzeit system status

# View help
gleitzeit --help

# Batch process multiple files
gleitzeit batch examples/documents --pattern "*.txt" --prompt "Summarize this document"

# Batch process images with vision model
gleitzeit batch examples/images --pattern "*.png" --vision --prompt "Describe this image"
```

#### Python API Usage
```python
import asyncio
from gleitzeit import GleitzeitClient

async def main():
    async with GleitzeitClient() as client:
        # Simple chat
        response = await client.chat("Tell me a joke")
        print(response)
        
        # Run a workflow
        results = await client.run_workflow("examples/simple_llm_workflow.yaml")
        
        # Batch process files
        batch_results = await client.batch_chat(
            directory="examples/documents",
            pattern="*.txt",
            prompt="Summarize this document"
        )

asyncio.run(main())
```

## Documentation

### Python API Documentation
- [Python API Reference](docs/PYTHON_API_REFERENCE.md) - Complete Python client API documentation
- [Python API Quick Reference](docs/PYTHON_API_QUICK_REFERENCE.md) - Concise API quick reference

### Core Documentation
- [Architecture Overview](docs/GLEITZEIT_V4_ARCHITECTURE.md) - System architecture and design
- [Batch Processing Guide](docs/BATCH_PROCESSING_DESIGN.md) - Dynamic batch processing implementation
- [Batch Quick Reference](docs/BATCH_QUICK_REFERENCE.md) - Quick guide for batch workflows
- [Provider Implementation Guide](docs/PROVIDER_IMPLEMENTATION_GUIDE.md) - How to implement providers correctly
- [Workflow Parameter Substitution](docs/WORKFLOW_PARAMETER_SUBSTITUTION.md) - Using task results in subsequent tasks
- [Protocols and Providers](docs/PROTOCOLS_PROVIDERS_EXECUTION.md) - Protocol-based execution system

## Dynamic Batch Processing

Process multiple files automatically with pattern matching:

```yaml
# batch_analysis.yaml
name: "Dynamic Batch Analysis"
type: "batch"  # Enables dynamic file discovery

batch:
  directory: "documents"
  pattern: "*.txt"  # Glob pattern for files

template:
  method: "llm/chat"
  model: "llama3.2:latest"
  messages:
    - role: "user"
      content: "Summarize this document"
```

Run it:
```bash
# Using YAML workflow
gleitzeit run batch_analysis.yaml

# Or using CLI directly
gleitzeit batch documents --pattern "*.txt" --prompt "Summarize"
```

## Workflow Examples

### Dependent Tasks
```yaml
name: "Research Pipeline"
tasks:
  - id: "generate_topic"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Generate a research topic"

  - id: "research_topic"
    method: "llm/chat"
    dependencies: ["generate_topic"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Research: ${generate_topic.response}"
```

### Mixed Providers
```yaml
name: "Data Processing Pipeline"
tasks:
  - id: "generate_data"
    method: "python/execute"
    parameters:
      file: "scripts/generate_data.py"

  - id: "analyze_data"
    method: "llm/chat"
    dependencies: ["generate_data"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Analyze this data: ${generate_data.result}"
```

Run it:
```bash
gleitzeit workflow submit research_workflow.yaml
```

## Provider Support

### LLM Provider (Ollama)
Coordinate LLM interactions:
```bash
gleitzeit task submit llm/chat --model "llama3" --messages '[{"role":"user","content":"Explain async programming"}]'
```

### Python Provider
Add computational steps to workflows:
- Process LLM outputs
- Transform data between workflow steps
- Implement custom logic within workflow chains

### MCP Provider
Built-in Model Context Protocol support with SimpleMCPProvider:

```yaml
# MCP tools in workflows
- id: "echo_message"
  method: "mcp/tool.echo"
  parameters:
    message: "Hello MCP!"

- id: "calculate"
  method: "mcp/tool.add"
  parameters:
    a: 10
    b: 20
    
# Available built-in tools:
# - mcp/tool.echo    # Echo messages with metadata
# - mcp/tool.add     # Add two numbers
# - mcp/tool.multiply # Multiply two numbers
# - mcp/tool.concat  # Concatenate strings
```

## Architecture

- **Tasks** specify protocols and methods using JSON-RPC 2.0
- **Workflows** chain multiple tasks with dependency resolution
- **Providers** implement protocol interfaces (LLM, Python, MCP)
- **Registry** manages provider lifecycle and routing
- **Queue System** handles task scheduling and dependencies
- **Persistence** stores workflows, results, and execution state

## CLI Commands

### Workflow Management
```bash
# Submit workflow from YAML
gleitzeit workflow submit workflow.yaml

# List workflows
gleitzeit workflow list

# Get workflow status and results
gleitzeit workflow status WORKFLOW_ID
```

### Task Management
```bash
# List submitted tasks
gleitzeit task list

# Get task result
gleitzeit task result TASK_ID
```

### Provider Management
```bash
# List available providers
gleitzeit provider list

# Check provider health
gleitzeit provider health PROVIDER_ID
```

### Backend Operations
```bash
# View system statistics
gleitzeit backend get-stats

# Get workflow results
gleitzeit backend get-results-by-workflow WORKFLOW_NAME
```

## Configuration

Set environment variables for customization:

```bash
# Persistence backend
export GLEITZEIT_PERSISTENCE_BACKEND=sqlite  # redis, sqlite, none

# Database connections
export GLEITZEIT_REDIS_URL=redis://localhost:6379/0
export GLEITZEIT_SQLITE_PATH=~/.gleitzeit/gleitzeit.db

# LLM Provider settings
export GLEITZEIT_OLLAMA_URL=http://localhost:11434

# Logging
export GLEITZEIT_LOG_LEVEL=INFO

# MCP Provider settings (enabled by default)
# SimpleMCPProvider with built-in tools is automatically registered
```

## Workflow Patterns

### LLM Chain Pattern
```yaml
tasks:
  - name: "step1"
    protocol: "llm/v1"
    method: "llm/chat"
    # ... initial prompt
  
  - name: "step2" 
    protocol: "llm/v1"
    method: "llm/chat"
    params:
      messages:
        - role: "user"
          content: "Continue from: ${step1.content}"
    dependencies: ["step1"]
```

### Mixed Task Pattern
```yaml
tasks:
  - name: "llm_analysis"
    protocol: "llm/v1"
    method: "llm/chat"
    # ... LLM task
    
  - name: "data_processing"
    protocol: "python/v1" 
    method: "python/execute"
    params:
      code: "result = process_llm_output('${llm_analysis.content}')"
    dependencies: ["llm_analysis"]
    
  - name: "mcp_integration"
    protocol: "mcp/v1"
    method: "tool.external_api"
    params:
      data: "${data_processing.result}"
    dependencies: ["data_processing"]
```

## Batch Processing

Process multiple files in parallel with a single command or API call.

### Basic Batch Usage

```bash
# Process text files with LLM
gleitzeit batch examples/documents --pattern "*.txt" --prompt "Summarize this document"

# Process specific file types with custom prompt
gleitzeit batch /path/to/docs --pattern "*.md" --prompt "Extract key points"

# Process images with vision model
gleitzeit batch examples/images --pattern "*.png" --vision --prompt "Describe what you see"

# Process files with Python scripts (workflow-based)
gleitzeit run examples/batch_python_workflow.yaml

# Save results to file
gleitzeit batch examples/documents --pattern "*.txt" --output results.json
gleitzeit batch examples/documents --pattern "*.txt" --output results.md
```


### Batch Workflow Examples

```yaml
# Dynamic batch text analysis with LLM
name: "Batch Document Analysis"
type: "batch"
batch:
  directory: "examples/documents"
  pattern: "*.txt"
template:
  method: "llm/chat"
  model: "llama3.2:latest"
  messages:
    - role: "user"
      content: "Summarize this document in 2 sentences"
```

```yaml
# Process files with Python scripts
name: "Python Batch Processing"
type: "batch"
protocol: "python/v1"
batch:
  directory: "examples/documents"
  pattern: "*.txt"
template:
  method: "python/execute"
  file: "examples/scripts/read_text_file.py"
  timeout: 10
```

```yaml
# Batch image description with vision model
name: "Batch Image Processing"
type: "batch"
batch:
  directory: "examples/images"
  pattern: "*.png"
template:
  method: "llm/vision"
  model: "llava:latest"
  messages:
    - role: "user"
      content: "Describe the visual elements"
```

### Batch Results

Results are automatically saved and can be exported in multiple formats:

- **JSON**: Structured data with all details
- **Markdown**: Human-readable report with summaries

Results include:
- Batch ID and timestamp
- Processing statistics (total, successful, failed)
- Individual file results
- Processing time metrics

## Testing

### Workflow Test Suite
```bash
# Run validation tests only (fast)
python tests/workflow_test_suite.py

# Run full execution tests
python tests/workflow_test_suite.py --execute
```

The test suite validates and executes all example workflows:
- ✅ Simple LLM workflows
- ✅ Dependent task workflows
- ✅ Parallel execution
- ✅ Mixed provider workflows (LLM + Python)
- ✅ Vision/image processing
- ✅ Dynamic batch processing
- ✅ Python workflows with context passing
- ✅ Parameter substitution

See [Test Report](tests/TEST_REPORT.md) for detailed results.

## Development

### MCP Provider Implementation

The SimpleMCPProvider offers built-in MCP functionality:

1. **Built-in Tools**: Echo, add, multiply, and concat operations
2. **Protocol Integration**: Full compatibility with Gleitzeit's protocol system  
3. **Backend Persistence**: Results automatically saved to SQLite/Redis
4. **Parameter Substitution**: Use results from previous tasks with `${task_id.field}`

Example workflow: `examples/simple_mcp_workflow.yaml`  
Full documentation: [MCP Usage Guide](docs/MCP_USAGE_GUIDE.md)

### Project Structure
```
├── core/               # Core execution engine, models, protocols
├── providers/          # Provider implementations (LLM, Python, MCP)
├── persistence/        # Backend storage implementations  
├── task_queue/         # Queue management and scheduling
├── tests/              # Test suite and test runners
├── docs/               # Documentation and architecture guides
├── cli.py              # Main CLI interface
└── registry.py         # Provider registry and management
```

## Examples

See the `examples/` directory for workflow templates:
- `simple_llm_workflow.yaml` - Basic LLM text generation
- `dependent_workflow.yaml` - Tasks with dependencies
- `parallel_workflow.yaml` - Parallel task execution
- `mixed_workflow.yaml` - LLM + Python workflows
- `vision_workflow.yaml` - Image analysis with vision models
- `batch_text_dynamic.yaml` - Dynamic batch text processing
- `batch_image_dynamic.yaml` - Dynamic batch image processing
- `python_only_workflow.yaml` - Python execution with data passing

## Documentation

- `docs/CLI_COMMANDS.md` - Complete CLI reference
- `docs/PROVIDER_LIFECYCLE_MANAGEMENT.md` - Provider development guide
- `docs/GLEITZEIT_V4_DESIGN.md` - Architecture overview

## License

MIT License - see [LICENSE](LICENSE) file for details.
