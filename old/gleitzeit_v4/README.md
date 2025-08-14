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

## Quick Start

### Installation

```bash
pip install -e .
```

### Basic Usage

```bash
# Submit a workflow
python cli.py workflow submit examples/llm_workflow.yaml

# Check workflow status
python cli.py workflow status WORKFLOW_ID

# View system status  
python cli.py system status

# View help
python cli.py --help
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
python cli.py workflow submit research_workflow.yaml
```

## Provider Support

### LLM Provider (Ollama)
Coordinate LLM interactions:
```bash
python cli.py task submit llm/chat --model "llama3" --messages '[{"role":"user","content":"Explain async programming"}]'
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
python cli.py workflow submit workflow.yaml

# List workflows
python cli.py workflow list

# Get workflow status and results
python cli.py workflow status WORKFLOW_ID
```

### Task Management
```bash
# List submitted tasks
python cli.py task list

# Get task result
python cli.py task result TASK_ID
```

### Provider Management
```bash
# List available providers
python cli.py provider list

# Check provider health
python cli.py provider health PROVIDER_ID
```

### Backend Operations
```bash
# View system statistics
python cli.py backend get-stats

# Get workflow results
python cli.py backend get-results-by-workflow WORKFLOW_NAME
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

## Development

### Running Tests
```bash
# Core system tests
PYTHONPATH=. python run_core_tests.py

# Workflow tests
PYTHONPATH=. python tests/test_comprehensive_cli.py
```

### Adding MCP Providers

MCP providers integrate seamlessly due to the JSON-RPC 2.0 foundation:

1. Register MCP server endpoint
2. Define protocol specification
3. Use in workflows like any other provider

### Project Structure
```
├── core/                 # Core execution engine, models, protocols
├── providers/           # Provider implementations (LLM, Python, MCP)
├── persistence/        # Backend storage implementations  
├── task_queue/         # Queue management and scheduling
├── tests/              # Test suite
├── examples/           # Workflow examples
├── cli.py              # Main CLI interface
└── registry.py         # Provider registry and management
```

## Examples

See the `examples/` directory for workflow templates:
- `llm_workflow.yaml` - LLM coordination patterns
- `mixed_workflow.yaml` - LLM + Python + MCP workflows
- `dependent_workflow.yaml` - Complex dependency chains

## Documentation

- `CLI_COMMANDS.md` - Complete CLI reference
- `PROVIDER_LIFECYCLE_MANAGEMENT.md` - Provider development guide
- `GLEITZEIT_V4_DESIGN.md` - Architecture overview

## License

See LICENSE file for details.