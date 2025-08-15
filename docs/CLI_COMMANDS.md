# Gleitzeit CLI Commands

## Overview

Gleitzeit provides a simple command-line interface for running workflows and managing batch processing tasks.

## Installation

After installing Gleitzeit, the `gleitzeit` (or `gz`) command will be available:

```bash
# Using pip
pip install -e .

# Using uv (recommended)
uv pip install -e .
```

## Global Options

```bash
gleitzeit [OPTIONS] COMMAND [ARGS]

Options:
  -v, --verbose  Enable verbose logging
  --debug        Enable debug logging
  --version      Show version
  --help         Show help message
```

## Commands

### `run` - Execute Workflows

Execute a workflow from a YAML file.

```bash
gleitzeit run WORKFLOW_FILE [OPTIONS]

Options:
  -w, --watch              Watch execution progress
  --backend TYPE           Persistence backend (sqlite|redis)
  --output FILE           Save results to JSON file
```

**Examples:**

```bash
# Run a simple workflow
gleitzeit run examples/llm_workflow.yaml

# Run with progress monitoring
gleitzeit run workflow.yaml --watch

# Save results to file
gleitzeit run workflow.yaml --output results.json

# Use Redis backend
gleitzeit run workflow.yaml --backend redis
```

### `batch` - Batch Process Files

Process multiple files in a directory using a single prompt/model.

```bash
gleitzeit batch DIRECTORY [OPTIONS]

Options:
  --pattern PATTERN        File pattern to match (default: *)
  --prompt TEXT           Prompt for each file (default: "Analyze this file")
  --model MODEL           LLM model to use (default: llama3.2:latest)
  --vision                Use vision model for images
  --output FILE           Save results to file
  --format FORMAT         Output format (json|markdown)
```

**Examples:**

```bash
# Process all text files
gleitzeit batch documents --pattern "*.txt" --prompt "Summarize this document"

# Process images with vision model
gleitzeit batch images --pattern "*.png" --vision --prompt "Describe this image"

# Save results as markdown
gleitzeit batch reports --pattern "*.md" --output results.md --format markdown

# Use specific model
gleitzeit batch docs --model "mistral:latest" --prompt "Extract key points"
```

### `status` - System Status

Show system status and recent workflow information.

```bash
gleitzeit status [OPTIONS]

Options:
  --backend TYPE    Backend to query (sqlite|redis)
```

**Example:**

```bash
# Check system status
gleitzeit status

# Check Redis backend status
gleitzeit status --backend redis
```

**Output includes:**
- Persistence backend status
- Recent workflows (last 10)
- Provider availability
- Ollama connection status

### `init` - Create Workflow Template

Create a new workflow template file.

```bash
gleitzeit init NAME [OPTIONS]

Options:
  --type TYPE    Type of workflow (python|llm|mixed) (default: python)
```

**Examples:**

```bash
# Create Python workflow template
gleitzeit init my_workflow --type python

# Create LLM workflow template
gleitzeit init chat_workflow --type llm

# Create mixed workflow template
gleitzeit init complex_workflow --type mixed
```

**Generated templates:**
- `python` - Python code execution workflow
- `llm` - LLM text generation workflow  
- `mixed` - Combination of Python and LLM tasks

### `config` - Show Configuration

Display current Gleitzeit configuration.

```bash
gleitzeit config
```

**Shows:**
- Configuration file location
- Persistence settings
- Provider configurations
- Execution settings

### `exec` - Execute Python Code

Execute Python code directly (for testing).

```bash
gleitzeit exec CODE [OPTIONS]

Options:
  --timeout SECONDS    Execution timeout (default: 10)
```

**Examples:**

```bash
# Simple calculation
gleitzeit exec "print(2 + 2)"

# Multi-line code
gleitzeit exec "import math; print(math.pi)"

# With timeout
gleitzeit exec "import time; time.sleep(5); print('done')" --timeout 10
```

## Configuration

Gleitzeit uses a configuration file at `~/.gleitzeit/config.yaml`:

```yaml
persistence:
  backend: sqlite  # or redis
  sqlite:
    db_path: ~/.gleitzeit/workflows.db
  redis:
    host: localhost
    port: 6379
    db: 0

providers:
  python:
    enabled: true
  ollama:
    enabled: true
    endpoint: http://localhost:11434
    default_models:
      chat: llama3.2:latest
      vision: llava:latest

execution:
  max_concurrent_tasks: 5

batch:
  max_file_size: 1048576  # 1MB
  max_concurrent: 5
  results_directory: ~/.gleitzeit/batch_results
```

## Workflow Files

### Basic Workflow Structure

```yaml
name: "My Workflow"
description: "Workflow description"
tasks:
  - id: "task1"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: "Hello"
  
  - id: "task2"
    method: "python/execute"
    dependencies: ["task1"]
    parameters:
      code: "print('Task 1 said: ${task1.response}')"
```

### Batch Workflow Structure

```yaml
name: "Batch Processing"
type: "batch"
batch:
  directory: "documents"
  pattern: "*.txt"
template:
  method: "llm/chat"
  model: "llama3.2:latest"
  messages:
    - role: "user"
      content: "Summarize this document"
```

## Common Use Cases

### Document Summarization

```bash
# Single document
gleitzeit run examples/simple_llm_workflow.yaml

# Batch processing
gleitzeit batch documents --pattern "*.txt" --prompt "Create a 3-sentence summary"
```

### Image Analysis

```bash
# Single image
gleitzeit run examples/vision_workflow.yaml

# Batch images
gleitzeit batch images --pattern "*.jpg" --vision --prompt "Identify objects in this image"
```

### Code Review

```bash
# Create workflow for code review
cat > code_review.yaml << EOF
name: "Code Review"
tasks:
  - id: "review"
    method: "llm/chat"
    parameters:
      model: "codellama:latest"
      file_path: "main.py"
      messages:
        - role: "user"
          content: "Review this code for bugs and improvements"
EOF

gleitzeit run code_review.yaml
```

### Data Processing Pipeline

```bash
# Mixed Python and LLM workflow
gleitzeit run examples/mixed_workflow.yaml --watch
```

## Troubleshooting

### Ollama Not Available

```bash
# Start Ollama service
ollama serve

# Check connection
gleitzeit status
```

### Database Errors

```bash
# Reset SQLite database
rm ~/.gleitzeit/workflows.db
gleitzeit status  # Will recreate database
```

### Provider Issues

```bash
# Check system status
gleitzeit status

# Enable debug logging
gleitzeit --debug run workflow.yaml
```

## Environment Variables

```bash
# Set custom config location
export GLEITZEIT_CONFIG=~/custom/config.yaml

# Enable debug logging
export GLEITZEIT_DEBUG=1

# Set Redis connection
export REDIS_URL=redis://localhost:6379/0
```

## Exit Codes

- `0` - Success
- `1` - General error
- `2` - Invalid arguments
- `3` - File not found
- `4` - Provider error
- `5` - Task execution failed

## Quick Reference

```bash
# Run workflow
gleitzeit run workflow.yaml

# Batch process
gleitzeit batch docs --pattern "*.txt"

# Check status
gleitzeit status

# Create template
gleitzeit init my_workflow

# Show config
gleitzeit config

# Execute Python
gleitzeit exec "print('Hello')"
```