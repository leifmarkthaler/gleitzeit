# CLI Reference

The Gleitzeit command-line interface provides commands for running workflows, managing configuration, and monitoring system status.

## Global Options

Options that work with all commands:

```bash
gleitzeit [OPTIONS] COMMAND [ARGS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--verbose` | `-v` | Enable verbose output |
| `--debug` | | Enable debug logging |
| `--config FILE` | | Use custom config file |
| `--help` | `-h` | Show help message |
| `--version` | | Show version |

## Commands

### gleitzeit run

Execute a workflow file.

```bash
gleitzeit run [OPTIONS] WORKFLOW_FILE
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--watch` | Watch file for changes and re-run | False |
| `--host` | API server host | localhost |
| `--port` | API server port | 8000 |
| `--local` | Force native mode (no API) | False |
| `--no-auto-start` | Don't auto-start API server | False |
| `--input KEY=VALUE` | Set input parameters | - |
| `--output FILE` | Save results to file | - |
| `--format` | Output format (json, yaml, text) | text |

**Examples:**

```bash
# Run a workflow
gleitzeit run workflow.yaml

# With input parameters
gleitzeit run pipeline.yaml --input topic="AI" --input length=500

# Watch for changes
gleitzeit run workflow.yaml --watch

# Force local execution
gleitzeit run workflow.yaml --local

# Save output
gleitzeit run workflow.yaml --output results.json --format json
```

### gleitzeit status

Check system and resource status.

```bash
gleitzeit status [OPTIONS]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--backend` | Check specific backend (redis, sqlite, memory) |
| `--resources` | Show resource details |
| `--json` | Output as JSON |

**Examples:**

```bash
# Basic status
gleitzeit status

# Check Redis backend
gleitzeit status --backend redis

# Detailed resource info
gleitzeit status --resources

# JSON output for scripting
gleitzeit status --json
```

**Output includes:**
- Ollama availability and models
- Persistence backend status
- API server status
- Resource availability

### gleitzeit init

Create a new workflow template.

```bash
gleitzeit init [OPTIONS] [NAME]
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--type` | Template type (basic, batch, pipeline, parallel) | basic |
| `--dir` | Output directory | . |
| `--force` | Overwrite existing file | False |

**Template Types:**
- `basic`: Simple single-task workflow
- `batch`: Batch file processing template
- `pipeline`: Multi-step pipeline
- `parallel`: Parallel task execution

**Examples:**

```bash
# Interactive creation
gleitzeit init

# Create specific template
gleitzeit init my-workflow --type pipeline

# Save to directory
gleitzeit init analysis --type batch --dir workflows/
```

### gleitzeit config

Manage configuration settings.

```bash
gleitzeit config [COMMAND] [OPTIONS]
```

**Subcommands:**

#### config show

Display current configuration:

```bash
gleitzeit config show [--json]
```

#### config set

Set configuration value:

```bash
gleitzeit config set KEY VALUE
```

#### config get

Get specific configuration value:

```bash
gleitzeit config get KEY
```

#### config reset

Reset to default configuration:

```bash
gleitzeit config reset [--confirm]
```

**Examples:**

```bash
# Show all config
gleitzeit config show

# Set default model
gleitzeit config set default_model mistral

# Set Ollama endpoint
gleitzeit config set ollama_url http://localhost:11434

# Get specific value
gleitzeit config get default_model

# Reset to defaults
gleitzeit config reset --confirm
```

**Configuration Keys:**
- `default_model`: Default Ollama model
- `ollama_url`: Ollama server URL
- `redis_url`: Redis connection URL
- `sql_db_path`: SQLite database path
- `max_concurrent`: Max parallel tasks
- `default_timeout`: Default task timeout

### gleitzeit batch

Process multiple files in batch.

```bash
gleitzeit batch [OPTIONS] DIRECTORY
```

**Options:**

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--pattern` | `-p` | File pattern (glob) | * |
| `--prompt` | | Prompt template | "Process this file" |
| `--model` | `-m` | Ollama model | llama3.2 |
| `--vision` | | Use vision model | False |
| `--output` | `-o` | Output directory | - |
| `--format` | | Output format | json |
| `--recursive` | `-r` | Search recursively | False |
| `--max-concurrent` | | Parallel limit | 5 |

**Examples:**

```bash
# Process text files
gleitzeit batch documents --pattern "*.txt" --prompt "Summarize"

# Recursive search
gleitzeit batch data --pattern "**/*.json" --recursive

# Image analysis
gleitzeit batch images --pattern "*.jpg" --vision --model llava

# Save results
gleitzeit batch docs --pattern "*.md" --output summaries/

# Custom model and concurrency
gleitzeit batch large_data --model mistral --max-concurrent 10
```

### gleitzeit serve

Start the API server.

```bash
gleitzeit serve [OPTIONS]
```

**Options:**

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--host` | `-h` | Server host | 0.0.0.0 |
| `--port` | `-p` | Server port | 8000 |
| `--reload` | | Auto-reload on changes | False |
| `--workers` | `-w` | Number of workers | 1 |

**Examples:**

```bash
# Start server
gleitzeit serve

# Custom port
gleitzeit serve --port 9000

# Development mode
gleitzeit serve --reload

# Production with workers
gleitzeit serve --workers 4
```

### gleitzeit list

List available resources.

```bash
gleitzeit list [RESOURCE]
```

**Resources:**
- `models`: Available Ollama models
- `workflows`: Recent workflows
- `templates`: Workflow templates
- `scripts`: Python scripts in current directory

**Examples:**

```bash
# List Ollama models
gleitzeit list models

# List workflow templates
gleitzeit list templates

# List Python scripts
gleitzeit list scripts
```

### gleitzeit validate

Validate workflow syntax.

```bash
gleitzeit validate [OPTIONS] WORKFLOW_FILE
```

**Options:**

| Option | Description |
|--------|-------------|
| `--check-models` | Verify model availability |
| `--check-scripts` | Verify script files exist |
| `--verbose` | Show detailed validation |

**Examples:**

```bash
# Basic validation
gleitzeit validate workflow.yaml

# Full validation
gleitzeit validate workflow.yaml --check-models --check-scripts

# Validate directory
gleitzeit validate workflows/
```

### gleitzeit logs

View execution logs.

```bash
gleitzeit logs [OPTIONS]
```

**Options:**

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--lines` | `-n` | Number of lines | 50 |
| `--follow` | `-f` | Follow logs | False |
| `--level` | | Filter by level | - |
| `--component` | | Filter by component | - |

**Examples:**

```bash
# View recent logs
gleitzeit logs

# Follow logs
gleitzeit logs --follow

# Show errors only
gleitzeit logs --level error

# Component-specific
gleitzeit logs --component ollama
```

### gleitzeit chat

Quick chat with an Ollama model.

```bash
gleitzeit chat [OPTIONS] PROMPT
```

**Options:**

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--model` | `-m` | Ollama model | llama3.2 |
| `--system` | | System prompt | - |
| `--temperature` | `-t` | Temperature (0-1) | 0.7 |
| `--output` | `-o` | Save to file | - |
| `--image` | | Include image (vision) | - |

**Examples:**

```bash
# Simple chat
gleitzeit chat "What is Python?"

# With specific model
gleitzeit chat "Explain recursion" --model codellama

# With system prompt
gleitzeit chat "Review this code" --system "You are a code reviewer"

# Save response
gleitzeit chat "Write a poem" --output poem.txt

# Image analysis
gleitzeit chat "What's in this image?" --image photo.jpg --model llava
```

## Environment Variables

Configure Gleitzeit using environment variables:

```bash
# Ollama configuration
export GLEITZEIT_OLLAMA_URL=http://localhost:11434
export GLEITZEIT_DEFAULT_MODEL=llama3.2

# Persistence
export GLEITZEIT_REDIS_URL=redis://localhost:6379
export GLEITZEIT_SQL_DB_PATH=~/.gleitzeit/db.sqlite
export GLEITZEIT_PERSISTENCE_TYPE=auto

# API server
export GLEITZEIT_API_HOST=0.0.0.0
export GLEITZEIT_API_PORT=8000

# Execution
export GLEITZEIT_MAX_WORKERS=10
export GLEITZEIT_DEFAULT_TIMEOUT=30

# Logging
export GLEITZEIT_LOG_LEVEL=INFO
export GLEITZEIT_LOG_FILE=~/.gleitzeit/gleitzeit.log
```

## Configuration File

Default location: `~/.gleitzeit/config.yaml`

```yaml
# Ollama settings
ollama:
  url: http://localhost:11434
  default_model: llama3.2
  discovery_ports: [11434, 11435, 11436]
  auto_discover: true

# Persistence
persistence:
  type: auto  # auto, redis, sqlite, memory
  redis:
    url: redis://localhost:6379
    key_prefix: gleitzeit
  sql:
    db_path: ~/.gleitzeit/workflows.db

# Execution
execution:
  max_parallel_tasks: 5
  default_timeout: 30
  continue_on_error: false

# Batch processing
batch:
  max_concurrent: 5
  max_file_size: 1048576  # 1MB

# API server
api:
  host: 0.0.0.0
  port: 8000
  auto_start: true
```

## Exit Codes

| Code | Description |
|------|-------------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | File not found |
| 4 | Validation error |
| 5 | Execution error |
| 6 | Connection error |
| 7 | Timeout error |

## Shell Completion

Enable tab completion for your shell:

### Bash

```bash
echo 'eval "$(_GLEITZEIT_COMPLETE=bash_source gleitzeit)"' >> ~/.bashrc
source ~/.bashrc
```

### Zsh

```bash
echo 'eval "$(_GLEITZEIT_COMPLETE=zsh_source gleitzeit)"' >> ~/.zshrc
source ~/.zshrc
```

### Fish

```bash
_GLEITZEIT_COMPLETE=fish_source gleitzeit > ~/.config/fish/completions/gleitzeit.fish
```

## Aliases

The CLI is also available as `gz` for convenience:

```bash
gz run workflow.yaml
gz status
gz chat "Hello"
```

## Examples

### Daily Workflow

```bash
#!/bin/bash
# daily.sh - Run daily analysis

# Check system is ready
gleitzeit status || exit 1

# Process new files
gleitzeit batch incoming --pattern "*.csv" \
  --prompt "Extract metrics" \
  --output metrics/

# Run analysis workflow
gleitzeit run analysis.yaml \
  --input date=$(date +%Y-%m-%d) \
  --output reports/daily_$(date +%Y%m%d).json

# Send summary
gleitzeit chat "Summarize today's metrics" \
  --model llama3.2 \
  > summary.txt
```

### Development Workflow

```bash
# Watch and run on changes
gleitzeit run dev_workflow.yaml --watch --local

# In another terminal, check logs
gleitzeit logs --follow --component executor

# Test with different models
for model in llama3.2 mistral codellama; do
  gleitzeit run test.yaml --input model=$model
done
```

### Production Deployment

```bash
# Start API server
gleitzeit serve --host 0.0.0.0 --port 8000 --workers 4

# In client scripts
export GLEITZEIT_API_HOST=api.example.com
export GLEITZEIT_API_PORT=8000
gleitzeit run workflow.yaml
```