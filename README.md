# Gleitzeit - Task and Workflow Orchestration

A protocol-based orchestration system designed for coordinating LLM workflows with multi-task, multi-method execution patterns.

**Version:** 0.0.4

## Core Features

- **LLM Workflow Coordination** - Orchestrate complex LLM interactions and chains
- **Multi-Task Workflows** - Combine different task types (LLM, Python, MCP) in workflows
- **Protocol-Based** - JSON-RPC 2.0 foundation with native MCP support
- **Multiple Backends** - SQLite, Redis, or in-memory persistence
- **Dependency Management** - Tasks can depend on outputs from previous tasks
- **YAML Workflows** - Define complex workflows declaratively
- **Batch Processing** - Process multiple files (text, images) in parallel with a single command

## Quick Start

### Installation

```bash
# Clone and install in development mode
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit
pip install -e .
```

### Basic Usage

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

## LLM Workflow Example

Create an LLM workflow (`research_workflow.yaml`):

```yaml
name: "LLM Research Workflow"
description: "Multi-step research with LLM coordination"
tasks:
  - name: "initial_research"
    protocol: "llm/v1"
    method: "llm/chat"
    params:
      model: "llama3"
      messages:
        - role: "user"
          content: "Research the latest developments in async programming"

  - name: "analyze_findings"
    protocol: "llm/v1"
    method: "llm/chat"
    params:
      model: "llama3"
      messages:
        - role: "user"
          content: "Analyze these findings: ${initial_research.content}"
    dependencies: ["initial_research"]

  - name: "process_data"
    protocol: "python/v1"
    method: "python/execute"
    params:
      code: |
        # Process LLM output for next step
        analysis = "${analyze_findings.content}"
        result = {"processed": len(analysis.split()), "summary": analysis[:100]}
    dependencies: ["analyze_findings"]
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

### MCP Providers
Easy integration of Model Context Protocol providers:

```yaml
# MCP provider in workflow
- name: "mcp_task"
  protocol: "mcp/v1"  
  method: "tool.function_name"
  params:
    input: "${previous_task.output}"
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

# MCP Provider settings
export GLEITZEIT_MCP_SERVER_PATH=/path/to/mcp/server
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
# Process all text files in a directory
gleitzeit batch examples/documents --pattern "*.txt" --prompt "Summarize this document"

# Process specific file types with custom prompt
gleitzeit batch /path/to/docs --pattern "*.md" --prompt "Extract key points"

# Process images with vision model
gleitzeit batch examples/images --pattern "*.png" --vision --prompt "Describe what you see"

# Save results to file
gleitzeit batch examples/documents --pattern "*.txt" --output results.json
gleitzeit batch examples/documents --pattern "*.txt" --output results.md
```

### Batch Processing in Python

```python
from core.batch_processor import BatchProcessor
from core import ExecutionEngine

# Create batch processor
batch_processor = BatchProcessor()

# Scan directory for files
files = batch_processor.scan_directory("examples/documents", "*.txt")

# Create batch workflow
workflow = batch_processor.create_batch_workflow(
    files=files,
    method="llm/chat",
    prompt="Provide a summary",
    model="llama3.2:latest"
)

# Process batch with execution engine
result = await batch_processor.process_batch(
    execution_engine=engine,
    directory="examples/documents",
    pattern="*.txt",
    method="llm/chat",
    prompt="Summarize this document"
)

# Access results
print(f"Processed {result.total_files} files")
print(f"Success: {result.successful}, Failed: {result.failed}")

# Export results
result.save_to_file()  # Saves as JSON
print(result.to_markdown())  # Get markdown report
```

### Batch Workflow Examples

```yaml
# Batch text analysis
name: "Batch Document Analysis"
tasks:
  - name: "analyze_documents"
    protocol: "llm/v1"
    method: "llm/chat"
    params:
      model: "llama3.2:latest"
      directory: "examples/documents"
      file_pattern: "*.txt"
      batch_mode: true
      messages:
        - role: "user"
          content: "Summarize this document in 2 sentences"
```

```yaml
# Batch image description
name: "Batch Image Processing"
tasks:
  - name: "describe_images"
    protocol: "llm/v1"
    method: "llm/vision"
    params:
      model: "llava:latest"
      image_paths:
        - "examples/images/chart1.png"
        - "examples/images/chart2.png"
      batch_mode: true
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

## Development

### Running Tests
```bash
# Core system tests
PYTHONPATH=. python run_core_tests.py

# Workflow tests
PYTHONPATH=. python tests/test_comprehensive_cli.py

# Batch processing tests  
PYTHONPATH=. python tests/run_batch_tests.py
# Or run individual batch tests
PYTHONPATH=. python tests/test_batch_simple.py
PYTHONPATH=. python tests/test_batch_runner.py
```

### Adding MCP Providers

MCP providers integrate via the JSON-RPC 2.0 foundation:

1. Register MCP server endpoint
2. Define protocol specification
3. Use in workflows like any other provider

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
- `llm_workflow.yaml` - LLM coordination patterns
- `mixed_workflow.yaml` - LLM + Python + MCP workflows
- `dependent_workflow.yaml` - Complex dependency chains

## Documentation

- `docs/CLI_COMMANDS.md` - Complete CLI reference
- `docs/PROVIDER_LIFECYCLE_MANAGEMENT.md` - Provider development guide
- `docs/GLEITZEIT_V4_DESIGN.md` - Architecture overview

## License

MIT License - see [LICENSE](LICENSE) file for details.
