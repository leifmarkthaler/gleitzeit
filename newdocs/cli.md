# CLI Reference

Command-line interface for Gleitzeit with Ollama integration.

## Prerequisites

```bash
# Ensure Ollama is installed and running
ollama serve

# List available models
ollama list
```

## Basic Commands

### `gleitzeit run`
Execute a workflow file.

```bash
# Run a workflow
gleitzeit run workflow.yaml

# With input parameters
gleitzeit run pipeline.yaml --input name="Alice" --input age=30

# With specific output directory
gleitzeit run workflow.yaml --output results/

# Debug mode (verbose output)
gleitzeit run workflow.yaml --debug

# Quiet mode (minimal output)
gleitzeit run workflow.yaml --quiet
```

### `gleitzeit chat`
Quick chat with an Ollama model.

```bash
# Chat with default model (llama3.2)
gleitzeit chat "What is Python?"

# With specific Ollama model
gleitzeit chat "Explain recursion" --model mistral

# Use code-specific model
gleitzeit chat "Review this code: def add(a,b): return a+b" --model codellama

# Save response to file
gleitzeit chat "Write a poem" --output poem.txt

# With system prompt
gleitzeit chat "Review this code" --system "You are a code reviewer"
```

### `gleitzeit batch`
Process multiple files with Ollama models.

```bash
# Process all text files
gleitzeit batch documents --pattern "*.txt" --prompt "Summarize" --model llama3.2

# Recursive search
gleitzeit batch data --pattern "**/*.txt" --prompt "Extract key points" --model mistral

# Process images with vision model
gleitzeit batch images --pattern "*.jpg" --prompt "Describe this image" --model llava

# Save results to directory
gleitzeit batch docs --pattern "*.md" --prompt "Analyze" --output analysis/

# Limit concurrent processing
gleitzeit batch large_files --pattern "*" --prompt "Process" --max-concurrent 3
```

## Workflow Management

### `gleitzeit init`
Create a new workflow template.

```bash
# Interactive workflow creation
gleitzeit init

# Create from template
gleitzeit init --template basic

# Available templates:
# - basic: Simple LLM chat workflow
# - batch: Batch file processing
# - pipeline: Multi-step pipeline with Python scripts
# - parallel: Parallel task execution

# Create in specific directory
gleitzeit init my-workflow --dir workflows/
```

### `gleitzeit validate`
Validate workflow syntax.

```bash
# Validate single file
gleitzeit validate workflow.yaml

# Validate all workflows in directory
gleitzeit validate workflows/

# Check model availability
gleitzeit validate workflow.yaml --check-models

# Verbose validation
gleitzeit validate workflow.yaml --verbose
```

### `gleitzeit list`
List available resources.

```bash
# List available Ollama models
gleitzeit list models

# List running workflows
gleitzeit list workflows

# List workflow templates
gleitzeit list templates

# List Python scripts in current directory
gleitzeit list scripts
```

## Configuration

### `gleitzeit config`
Manage Gleitzeit configuration.

```bash
# Show current configuration
gleitzeit config show

# Set default Ollama model
gleitzeit config set default_model mistral

# Set Ollama endpoint (if not default)
gleitzeit config set ollama_url http://localhost:11434

# Set Python scripts directory
gleitzeit config set scripts_dir ./scripts

# Get specific value
gleitzeit config get default_model

# Reset to defaults
gleitzeit config reset
```

## Monitoring

### `gleitzeit status`
Check system status.

```bash
# Overall status
gleitzeit status

# Check Ollama status
gleitzeit status ollama

# Check specific model availability
gleitzeit status model llama3.2

# JSON output for scripting
gleitzeit status --json
```

### `gleitzeit logs`
View execution logs.

```bash
# Tail logs
gleitzeit logs

# Last N lines
gleitzeit logs --lines 100

# Filter by level
gleitzeit logs --level error
gleitzeit logs --level warning

# Follow logs (real-time)
gleitzeit logs --follow

# Filter by component
gleitzeit logs --component executor
gleitzeit logs --component ollama
```

## Python Script Management

### `gleitzeit script`
Manage Python scripts for workflows.

```bash
# Create new script from template
gleitzeit script create process_data.py

# Test a script with sample data
gleitzeit script test process_data.py --args '{"input": "test"}'

# List all scripts
gleitzeit script list

# Validate script format
gleitzeit script validate *.py
```

## Development Commands

### `gleitzeit test`
Test workflows without full execution.

```bash
# Dry run (validate only, no execution)
gleitzeit test workflow.yaml --dry-run

# Test with sample data
gleitzeit test workflow.yaml --input-file sample.json

# Check all dependencies
gleitzeit test workflow.yaml --check-deps

# Performance test
gleitzeit test workflow.yaml --benchmark
```

### `gleitzeit debug`
Debug workflow execution.

```bash
# Start interactive debugger
gleitzeit debug workflow.yaml

# Set breakpoint at specific task
gleitzeit debug workflow.yaml --break-at task1

# Step through execution
gleitzeit debug workflow.yaml --step

# Show task outputs
gleitzeit debug workflow.yaml --show-outputs
```

## Advanced Options

### Global Flags

```bash
# Version information
gleitzeit --version

# Help for any command
gleitzeit --help
gleitzeit run --help

# Verbose output
gleitzeit --verbose run workflow.yaml

# Quiet mode
gleitzeit --quiet run workflow.yaml

# Custom config file
gleitzeit --config custom.yaml run workflow.yaml

# Output format
gleitzeit --format json status
gleitzeit --format yaml list models
```

### Environment Variables

```bash
# Ollama Configuration
export GLEITZEIT_OLLAMA_URL=http://localhost:11434
export GLEITZEIT_DEFAULT_MODEL=llama3.2

# Gleitzeit Configuration
export GLEITZEIT_CONFIG_PATH=~/.gleitzeit/config.yaml
export GLEITZEIT_SCRIPTS_DIR=./scripts
export GLEITZEIT_LOG_LEVEL=DEBUG

# Persistence (if configured)
export GLEITZEIT_REDIS_URL=redis://localhost:6379
export GLEITZEIT_SQL_DB_PATH=~/.gleitzeit/db.sqlite

# Performance
export GLEITZEIT_MAX_WORKERS=10
export GLEITZEIT_TIMEOUT=300
```

## Working with Ollama Models

### Model Management

```bash
# List installed Ollama models
ollama list

# Pull new models for use with Gleitzeit
ollama pull llama3.2      # General purpose
ollama pull mistral        # Better reasoning
ollama pull codellama      # Code generation
ollama pull llava          # Vision/image analysis

# Remove unused models
ollama rm old-model
```

### Using Models in Workflows

```bash
# Specify model in CLI
gleitzeit chat "Hello" --model mistral

# Default model in config
gleitzeit config set default_model codellama

# Per-task model in workflow
# See workflow YAML: model: "llama3.2"
```

## Python Script Integration

### Script Requirements

Python scripts must:
1. Accept arguments as JSON via `sys.argv[1]`
2. Return results as JSON via `print(json.dumps(...))`
3. Handle errors gracefully

### Example Script

```python
#!/usr/bin/env python3
import sys
import json

# Get arguments
args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

# Process
result = {"processed": args.get("input", "").upper()}

# Output
print(json.dumps(result))
```

### Testing Scripts

```bash
# Test script directly
python my_script.py '{"input": "test data"}'

# Test via Gleitzeit
gleitzeit script test my_script.py --args '{"input": "test"}'

# Use in workflow
gleitzeit run workflow.yaml --scripts-dir ./my_scripts
```

## Examples

### Quick Tasks

```bash
# Summarize a file
gleitzeit chat "Summarize this:" < document.txt --model llama3.2

# Analyze code
gleitzeit chat "Review this Python code:" < script.py --model codellama

# Describe an image
gleitzeit chat "What's in this image?" --image photo.jpg --model llava
```

### Batch Operations

```bash
# Process all markdown files
gleitzeit batch docs --pattern "*.md" \
  --prompt "Convert to plain text" \
  --model llama3.2 \
  --output converted/

# Analyze all Python files
gleitzeit batch src --pattern "**/*.py" \
  --prompt "Find security issues" \
  --model codellama \
  --output security_report/
```

### Workflow Automation

```bash
# Daily report generation
0 8 * * * gleitzeit run daily_report.yaml --output /reports/$(date +\%Y\%m\%d).txt

# Process files as they arrive
while inotifywait -e create incoming/; do
  gleitzeit batch incoming --pattern "*.new" --prompt "Process" --model llama3.2
done

# Chain workflows
gleitzeit run extract.yaml && gleitzeit run transform.yaml && gleitzeit run load.yaml
```

## Troubleshooting

### Common Issues

```bash
# Check if Ollama is running
gleitzeit status ollama

# Test model availability
ollama run llama3.2 "test"

# Validate workflow
gleitzeit validate workflow.yaml --verbose

# Check logs for errors
gleitzeit logs --level error --lines 50

# Test Python script
python script.py '{"test": "data"}'
```

### Debug Commands

```bash
# Verbose execution
gleitzeit --verbose run workflow.yaml

# Dry run (no execution)
gleitzeit test workflow.yaml --dry-run

# Show execution plan
gleitzeit run workflow.yaml --plan

# Profile performance
gleitzeit run workflow.yaml --profile
```

## Tips

1. **Always verify Ollama is running** before executing workflows
2. **Pull models first** with `ollama pull model-name`
3. **Test Python scripts** independently before using in workflows
4. **Use appropriate models** - llama3.2 for speed, mistral for quality, codellama for code
5. **Set default model** in config to avoid specifying repeatedly
6. **Use `--debug`** flag for troubleshooting
7. **Check logs** when something goes wrong
8. **Validate workflows** before running in production