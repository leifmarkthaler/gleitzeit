# CLI Reference

Complete command-line interface documentation.

## Installation

```bash
pip install gleitzeit

# Verify installation
gleitzeit --version
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

# Debug mode
gleitzeit run workflow.yaml --debug

# Quiet mode (minimal output)
gleitzeit run workflow.yaml --quiet
```

### `gleitzeit chat`
Quick chat with an LLM.

```bash
# Simple chat
gleitzeit chat "What is Python?"

# With specific model
gleitzeit chat "Explain recursion" --model gpt-4

# Save response to file
gleitzeit chat "Write a poem" --output poem.txt

# With system prompt
gleitzeit chat "Review this code" --system "You are a code reviewer"
```

### `gleitzeit batch`
Process multiple files.

```bash
# Process all text files
gleitzeit batch documents --pattern "*.txt" --prompt "Summarize"

# Recursive search
gleitzeit batch data --pattern "**/*.json" --prompt "Extract metrics"

# With specific model
gleitzeit batch reports --pattern "*.pdf" --prompt "Analyze" --model gpt-4

# Save results
gleitzeit batch docs --pattern "*.md" --prompt "Translate to Spanish" --output translations/

# Limit concurrency
gleitzeit batch large_files --pattern "*" --prompt "Process" --max-concurrent 3
```

## Workflow Management

### `gleitzeit init`
Create a new workflow template.

```bash
# Interactive workflow creation
gleitzeit init

# Create from template
gleitzeit init --template document-analyzer

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

# Verbose validation
gleitzeit validate workflow.yaml --verbose
```

### `gleitzeit list`
List available resources.

```bash
# List available models
gleitzeit list models

# List available providers
gleitzeit list providers

# List workflow templates
gleitzeit list templates

# List running tasks
gleitzeit list tasks
```

## Configuration

### `gleitzeit config`
Manage configuration.

```bash
# Show current configuration
gleitzeit config show

# Set configuration value
gleitzeit config set default_model gpt-4
gleitzeit config set ollama_url http://localhost:11434

# Get specific value
gleitzeit config get default_model

# Reset to defaults
gleitzeit config reset
```

### `gleitzeit auth`
Manage API keys.

```bash
# Set API key
gleitzeit auth set openai sk-...
gleitzeit auth set anthropic sk-ant-...

# List configured providers
gleitzeit auth list

# Test authentication
gleitzeit auth test openai

# Remove API key
gleitzeit auth remove openai
```

## Monitoring

### `gleitzeit status`
Check system status.

```bash
# Overall status
gleitzeit status

# Detailed status
gleitzeit status --detailed

# Check specific component
gleitzeit status ollama
gleitzeit status redis

# JSON output
gleitzeit status --json
```

### `gleitzeit logs`
View logs.

```bash
# Tail logs
gleitzeit logs

# Last N lines
gleitzeit logs --lines 100

# Filter by level
gleitzeit logs --level error
gleitzeit logs --level warning

# Follow logs
gleitzeit logs --follow

# Filter by component
gleitzeit logs --component executor
gleitzeit logs --component provider:ollama
```

### `gleitzeit stats`
View statistics.

```bash
# Overall statistics
gleitzeit stats

# Task statistics
gleitzeit stats tasks

# Provider statistics
gleitzeit stats providers

# Time range
gleitzeit stats --since "1 hour ago"
gleitzeit stats --since "2024-01-01"
```

## Development

### `gleitzeit test`
Test workflows.

```bash
# Test workflow without executing
gleitzeit test workflow.yaml --dry-run

# Test with sample data
gleitzeit test workflow.yaml --sample-data sample.json

# Performance test
gleitzeit test workflow.yaml --benchmark

# Test all workflows
gleitzeit test workflows/ --all
```

### `gleitzeit debug`
Debug workflows.

```bash
# Start interactive debugger
gleitzeit debug workflow.yaml

# Set breakpoint at task
gleitzeit debug workflow.yaml --break-at task1

# Step through execution
gleitzeit debug workflow.yaml --step

# Inspect variables
gleitzeit debug workflow.yaml --inspect
```

## Advanced Options

### Global Flags

```bash
# Version
gleitzeit --version

# Help
gleitzeit --help
gleitzeit run --help

# Verbose output
gleitzeit --verbose run workflow.yaml

# Quiet mode
gleitzeit --quiet run workflow.yaml

# Config file
gleitzeit --config custom.yaml run workflow.yaml

# Output format
gleitzeit --format json status
gleitzeit --format yaml list models
```

### Environment Variables

```bash
# API Keys
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

# Configuration
export GLEITZEIT_CONFIG_PATH=~/.gleitzeit/config.yaml
export GLEITZEIT_LOG_LEVEL=DEBUG
export GLEITZEIT_OLLAMA_URL=http://localhost:11434

# Persistence
export GLEITZEIT_REDIS_URL=redis://localhost:6379
export GLEITZEIT_SQL_DB_PATH=~/.gleitzeit/db.sqlite

# Performance
export GLEITZEIT_MAX_WORKERS=10
export GLEITZEIT_TIMEOUT=300
```

## Examples

### Quick Tasks

```bash
# Summarize a document
gleitzeit chat "Summarize this:" < document.txt

# Translate text
echo "Hello world" | gleitzeit chat "Translate to Spanish"

# Analyze code
gleitzeit chat "Review this Python code:" < script.py
```

### Batch Operations

```bash
# Process all markdown files
gleitzeit batch docs --pattern "*.md" \
  --prompt "Convert to HTML" \
  --output html/

# Analyze logs
gleitzeit batch /var/log --pattern "*.log" \
  --prompt "Find errors and warnings" \
  --output analysis/
```

### Workflow Pipelines

```bash
# Chain commands
gleitzeit run extract.yaml | gleitzeit run transform.yaml | gleitzeit run load.yaml

# Conditional execution
gleitzeit run check.yaml && gleitzeit run process.yaml || gleitzeit run error.yaml

# Parallel execution
gleitzeit run task1.yaml & gleitzeit run task2.yaml & wait
```

### Automation

```bash
# Cron job
0 8 * * * gleitzeit run daily_report.yaml --output /reports/$(date +\%Y\%m\%d).txt

# Watch directory
while true; do
  inotifywait -e create documents/
  gleitzeit batch documents --pattern "*.new" --prompt "Process"
done

# Process queue
while read -r file; do
  gleitzeit run process.yaml --input file="$file"
done < queue.txt
```

## Troubleshooting

### Common Issues

```bash
# Check if Ollama is running
gleitzeit status ollama

# Test model availability
gleitzeit chat "test" --model llama3.2 --debug

# Validate workflow syntax
gleitzeit validate workflow.yaml --verbose

# Check logs for errors
gleitzeit logs --level error --lines 50

# Reset configuration
gleitzeit config reset
```

### Debug Commands

```bash
# Verbose execution
gleitzeit --verbose run workflow.yaml

# Dry run (no execution)
gleitzeit run workflow.yaml --dry-run

# Show execution plan
gleitzeit run workflow.yaml --plan

# Profile performance
gleitzeit run workflow.yaml --profile
```

## Tips

1. **Use `--help`** on any command for details
2. **Set API keys** as environment variables for security
3. **Use `--debug`** for troubleshooting
4. **Save common workflows** as templates
5. **Use `--output`** to save results
6. **Chain commands** with pipes for complex operations
7. **Use `--quiet`** in scripts for cleaner output