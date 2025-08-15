# Gleitzeit V4 - Command Line Interface Reference

## Overview

Gleitzeit V4 provides a comprehensive command-line interface for managing tasks, workflows, and system components. All commands support both single-task execution and complex workflow orchestration with automatic persistence.

## Global Options

```bash
# Global CLI options (available for all commands)
--config TEXT     Configuration file path
-v, --verbose     Verbose output  
--help           Show help message
```

## Command Categories

### 🚀 Task Commands (`task`)

Submit and manage individual tasks. Tasks automatically get assigned to single-task workflows.

#### Submit a Task
```bash
python cli.py task submit [OPTIONS]

# Required Options:
--protocol TEXT       Protocol identifier (e.g., llm/v1, mcp/v1)
--method TEXT         Method name (e.g., llm/chat, python/execute)

# Optional Options:
--params TEXT         JSON parameters (default: {})
--priority TEXT       Priority: urgent, high, normal, low (default: normal)  
--timeout INTEGER     Task timeout in seconds
--depends-on TEXT     Task dependencies (comma-separated task IDs)
--queue TEXT          Target queue name
--wait               Wait for task completion and show result
--output-file TEXT   Save response to JSON file
```

**Examples:**
```bash
# Simple LLM chat task
python cli.py task submit --protocol llm/v1 --method llm/chat \
  --params '{"model": "llama3.2:latest", "messages": [{"role": "user", "content": "Hello"}]}' \
  --wait

# Python code execution with output file
python cli.py task submit --protocol python/v1 --method python/execute \
  --params '{"code": "print(2 + 2)"}' \
  --wait --output-file result.json

# High priority task with dependencies
python cli.py task submit --protocol llm/v1 --method llm/chat \
  --params '{"model": "llama3.2:latest", "messages": [{"role": "user", "content": "Analyze results"}]}' \
  --priority high --depends-on task-123,task-456
```

#### Check Task Status
```bash
python cli.py task status TASK_ID

# Shows task execution status and result if completed
```

### 📋 Workflow Commands (`workflow`)

Manage complex multi-task workflows with dependencies and orchestration.

#### Submit Workflow from File
```bash
python cli.py workflow submit [OPTIONS] WORKFLOW_FILE

# Options:
--params TEXT       JSON parameters for workflow template variables
--wait             Wait for workflow completion
--output-file TEXT Save response to JSON file
```

**Examples:**
```bash
# Submit YAML workflow
python cli.py workflow submit my_workflow.yaml --wait

# Submit with template parameters
python cli.py workflow submit workflow.yaml \
  --params '{"model": "llama3.2", "input": "test data"}' \
  --output-file workflow_result.json
```

#### Create from Template
```bash
python cli.py workflow from-template [OPTIONS]

# Interactive workflow creation from templates
```

#### List Templates and Active Workflows
```bash
# List available workflow templates
python cli.py workflow list-templates

# List currently running workflows  
python cli.py workflow list-active
```

### 💾 Backend Commands (`backend`)

Access and manage the persistence layer (Redis, SQLite, or in-memory).

#### Get Results
```bash
# Get single task result
python cli.py backend get-result TASK_ID

# Get all results from workflows matching name
python cli.py backend get-results-by-workflow "workflow name"

# Examples:
python cli.py backend get-results-by-workflow "Single Task"
python cli.py backend get-results-by-workflow "Data Processing"
```

#### Get Task/Workflow Details  
```bash
# Get task details
python cli.py backend get-task TASK_ID

# Get workflow details
python cli.py backend get-workflow WORKFLOW_ID
```

#### List Tasks and Workflows
```bash
# List tasks with filtering
python cli.py backend list-tasks [OPTIONS]
--status TEXT           Filter by status: queued, executing, completed, failed
--workflow-id TEXT      Filter by workflow ID
--workflow-name TEXT    Filter by workflow name
--limit INTEGER         Limit results (default: 20)

# List workflows with filtering
python cli.py backend list-workflows [OPTIONS]  
--name-filter TEXT      Filter by name (case-insensitive substring match)
--limit INTEGER         Limit results (default: 20)
```

**Examples:**
```bash
# Find completed tasks
python cli.py backend list-tasks --status completed

# Find tasks from specific workflow
python cli.py backend list-tasks --workflow-name "Data Analysis"

# List recent workflows
python cli.py backend list-workflows --limit 10
```

#### Statistics
```bash
# Show backend statistics
python cli.py backend stats

# Displays task counts by status, workflow statistics, etc.
```

### 📦 Batch Processing Commands (`batch`)

Process multiple files in parallel with a single command.

#### Process Files in Batch
```bash
gleitzeit batch <directory> [OPTIONS]

# Required:
<directory>          Directory containing files to process

# Options:
--pattern TEXT       File pattern to match (default: "*")
--prompt TEXT        Prompt to use for each file (default: "Analyze this file")
--model TEXT         Model to use (default: "llama3.2:latest")
--vision            Use vision model for image files
--output PATH        Save results to file (JSON or Markdown)
```

**Examples:**
```bash
# Process all text files in a directory
gleitzeit batch examples/documents --pattern "*.txt" --prompt "Summarize this document"

# Process images with vision model
gleitzeit batch examples/images --pattern "*.png" --vision --prompt "Describe what you see"

# Save results to markdown file
gleitzeit batch /path/to/docs --pattern "*.md" --output results.md

# Save results as JSON
gleitzeit batch /path/to/docs --pattern "*.txt" --output results.json
```

**Output Formats:**
- **JSON**: Complete structured data with all file results
- **Markdown**: Human-readable report with summaries and statistics
- **Console**: Real-time progress and summary (default)

### 🔧 System Commands (`system`)

Manage the execution engine and system configuration.

#### Start Execution Engine
```bash
python cli.py system start [OPTIONS]

# Options:
--mode TEXT    Execution mode: single, workflow, event (default: event)
```

**Execution Modes:**
- `single`: Single-shot execution (process one task and exit)
- `workflow`: Workflow-only mode (process complete workflows)  
- `event`: Event-driven mode (continuous processing)

#### System Status
```bash
python cli.py system status

# Shows:
# - Execution engine status
# - Active tasks and workflows
# - Queue statistics  
# - Provider health
# - Persistence backend status
```

#### Configuration
```bash
python cli.py system config

# Display current configuration
# - Persistence backend settings
# - Provider configurations
# - Queue settings
# - Execution parameters
```

### 🔌 Provider Commands (`provider`)

Manage execution providers (LLM, Python, MCP, etc.).

#### List Providers
```bash
python cli.py provider list

# Shows registered providers with:
# - Provider ID and name
# - Supported protocols  
# - Health status
# - Available methods
```

#### Check Provider Health
```bash
python cli.py provider health PROVIDER_ID

# Performs health check on specific provider
# Returns status, response time, capabilities
```

### 📊 Queue Commands (`queue`)

Monitor and manage task queues.

#### Queue Statistics
```bash
python cli.py queue stats [QUEUE_NAME]

# Options:
QUEUE_NAME    Specific queue name or 'all' for global stats

# Shows:
# - Queue sizes and task counts
# - Throughput statistics
# - Processing rates
# - Error rates
```

## Configuration Files

### CLI Configuration
```bash
# Use custom config file
python cli.py --config /path/to/config.json task submit ...

# Default locations:
# ~/.gleitzeit/config.json
# ./config.json
```

### Workflow Files
Support both YAML and JSON formats:

**YAML Example:**
```yaml
name: "Data Processing Workflow"
description: "Process and analyze data"
tasks:
  - id: "fetch_data"  
    name: "Fetch Data"
    protocol: "web-search/v1"
    method: "search"
    params:
      query: "machine learning trends"
      limit: 10
    priority: "high"
    
  - id: "analyze_data"
    name: "Analyze Results" 
    protocol: "llm/v1"
    method: "llm/chat"
    params:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: "Analyze this data: ${fetch_data.results}"
    dependencies: ["fetch_data"]
```

## Environment Variables

```bash
# Persistence Configuration
GLEITZEIT_PERSISTENCE_BACKEND=redis    # redis, sqlite, none
GLEITZEIT_REDIS_URL=redis://localhost:6379/0
GLEITZEIT_SQLITE_PATH=~/.gleitzeit/gleitzeit.db

# Execution Settings  
GLEITZEIT_MAX_CONCURRENT_TASKS=10
GLEITZEIT_DEFAULT_TIMEOUT=300

# Provider Settings
GLEITZEIT_OLLAMA_URL=http://localhost:11434
GLEITZEIT_PYTHON_SECURITY_MODE=restricted

# Resource Management
GLEITZEIT_PROVIDER_CLEANUP_TIMEOUT=30
GLEITZEIT_SESSION_CLEANUP_ENABLED=true

# Logging
GLEITZEIT_LOG_LEVEL=INFO
```

## Common Workflows

### 1. Quick Task Execution
```bash
# Execute a simple task and get results
python cli.py task submit --protocol llm/v1 --method llm/chat \
  --params '{"model": "llama3.2:latest", "messages": [{"role": "user", "content": "What is 2+2?"}]}' \
  --wait
```

### 2. Workflow Processing
```bash
# Submit and monitor a workflow
python cli.py workflow submit complex_workflow.yaml --wait --output-file results.json
```

### 3. Result Analysis  
```bash
# Find and examine results
python cli.py backend list-workflows --name-filter "Analysis"
python cli.py backend get-results-by-workflow "Data Analysis"
```

### 4. System Monitoring
```bash
# Check system health
python cli.py system status
python cli.py provider list  
python cli.py backend stats
```

### 5. Background Processing
```bash
# Start system for continuous processing
python cli.py system start --mode event

# Submit tasks (in another terminal)
python cli.py task submit --protocol llm/v1 --method llm/chat \
  --params '{"model": "llama3.2", "messages": [{"role": "user", "content": "Background task"}]}'
```

## Architecture Features

### Automatic Workflow Creation
- Single tasks automatically get assigned to single-task workflows
- Maintains consistency across the event-driven architecture
- All tasks are trackable through the persistence layer

### Event-Driven Processing
- Real-time task processing with event coordination
- Automatic retry handling with exponential backoff
- Task dependency resolution and parallel execution

### Multiple Persistence Backends
- **Redis**: High-performance distributed storage with pub/sub
- **SQLite**: Local file-based storage for development  
- **In-Memory**: Fast ephemeral storage for testing

### Protocol-Based Providers
- **LLM Provider**: Ollama integration for language models
- **Python Provider**: Secure Python code execution
- **MCP Provider**: Model Context Protocol support
- **Extensible**: Easy addition of custom providers

## Troubleshooting

### Common Issues

**Task Submission Hangs:**
```bash
# Check system status
python cli.py system status

# Verify providers are healthy
python cli.py provider list
```

**No Results Found:**
```bash
# Check if persistence is working
python cli.py backend stats

# List recent tasks
python cli.py backend list-tasks --limit 5
```

**Provider Errors:**
```bash
# Check provider health
python cli.py provider health PROVIDER_ID

# Review system configuration  
python cli.py system config
```

### Debug Options
```bash
# Enable verbose logging
python cli.py -v task submit ...

# Check queue status
python cli.py queue stats all

# Monitor system status
python cli.py system status
```

## Testing and Validation

### Run Test Suite
```bash
# Core system tests
PYTHONPATH=. python run_core_tests.py

# Comprehensive CLI tests
PYTHONPATH=. python tests/test_comprehensive_cli.py

# Provider cleanup tests
PYTHONPATH=. python tests/test_provider_cleanup.py

# Architecture validation
PYTHONPATH=. python tests/test_core_architecture_isolated.py
```

### Test Coverage Areas
- **Provider Lifecycle Management**: HTTP session cleanup, resource management
- **Event-driven Architecture**: Task submission, completion, workflow orchestration
- **CLI Interface**: All commands, backend operations, error handling
- **Protocol Framework**: Validation, method routing, parameter handling
- **Persistence Layer**: SQLite, Redis backends, data integrity

### Health Monitoring
```bash
# System health check
python cli.py system status

# Provider health validation
python cli.py provider health --all

# Resource usage monitoring
python cli.py backend get-stats
```

## Version Information

**Gleitzeit V4** - Protocol-Based Task Execution System
- Event-driven architecture with centralized resource management
- Automatic workflow management and dependency resolution
- Multi-backend persistence (SQLite, Redis)
- Comprehensive CLI interface with full test coverage
- Production-ready reliability with HTTP session cleanup
- Centralized provider lifecycle management

### Key Features
- ✅ HTTP session lifecycle management
- ✅ Event-driven cleanup architecture
- ✅ Comprehensive test coverage (100% core tests passing)
- ✅ Error-resilient resource management
- ✅ Production-ready reliability

For more details, see:
- `PROVIDER_LIFECYCLE_MANAGEMENT.md` - Resource management and cleanup
- `PROVIDER_SECURITY_DOCUMENTATION.md` - Security model and best practices
- `CLI_COMMANDS.md` - Complete command reference