# CLI Reference

The Gleitzeit command-line interface provides tools for workflow execution, batch processing, and system management.

## Installation

```bash
# Install Gleitzeit
pip install -e .

# Verify installation
gleitzeit --version
```

## Quick Start

```bash
# Run a workflow (auto-starts API server if needed)
gleitzeit run examples/simple_workflow.yaml

# Process files in batch
gleitzeit batch documents/ --pattern "*.txt" --prompt "Summarize this"

# Check system status
gleitzeit status

# Manually start API server (optional - auto-starts with run command)
gleitzeit serve
```

## Global Options

```bash
gleitzeit [OPTIONS] COMMAND [ARGS]...
```

**Options:**
- `--verbose, -v`: Enable verbose logging
- `--debug`: Enable debug logging
- `--version`: Show version information
- `--help`: Show help message

## Commands Overview

| Command | Description |
|---------|-------------|
| `run` | Execute a workflow from a YAML or JSON file |
| `batch` | Process multiple files in batch |
| `serve` | Start the REST API server |
| `init` | Create a new workflow template |
| `config` | Show current configuration |
| `status` | Show system status and recent workflows |

## Commands

### run

Execute a workflow from a YAML or JSON file (uses API by default).

```bash
gleitzeit run WORKFLOW_FILE [OPTIONS]
```

**Arguments:**
- `WORKFLOW_FILE`: Path to workflow definition file

**Options:**
- `--watch, -w`: Watch execution progress in real-time
- `--host TEXT`: API server host (default: localhost)
- `--port INT`: API server port (default: 8000)
- `--local`: Run locally without API server (legacy mode)
- `--no-auto-start`: Do not auto-start API server (by default, server starts automatically)

**Examples:**

```bash
# Run via API (default) - auto-starts server if needed
gleitzeit run workflow.yaml

# Run and watch progress
gleitzeit run workflow.yaml --watch

# Disable auto-start (will fail if server not running)
gleitzeit run workflow.yaml --no-auto-start

# Use custom API server
gleitzeit run workflow.yaml --host api.example.com --port 9000

# Run locally without API (legacy mode)
gleitzeit run workflow.yaml --local

# Debug mode for troubleshooting
gleitzeit --debug run workflow.yaml
```

**Note:** By default, `run` uses the API server and automatically starts it if not running. Use `--no-auto-start` to disable this behavior.

### batch

Process multiple files in batch with parallel execution.

```bash
gleitzeit batch DIRECTORY [OPTIONS]
```

**Arguments:**
- `DIRECTORY`: Directory containing files to process

**Options:**
- `--pattern TEXT`: File pattern to match (default: "*")
- `--prompt TEXT`: Prompt to use for each file (default: "Analyze this file")
- `--model TEXT`: Model to use (default: "llama3.2:latest")
- `--vision`: Use vision model for images
- `--output PATH`: Save results to file

**Examples:**

```bash
# Process all text files
gleitzeit batch ./documents --pattern "*.txt" --prompt "Summarize this document"

# Process images with vision model
gleitzeit batch ./images --pattern "*.png" --vision --prompt "Describe this image"

# Save results to JSON
gleitzeit batch ./data --pattern "*.csv" --output results.json

# Use specific model
gleitzeit batch ./docs --model llama3.2:7b --prompt "Extract key points"
```

### status

Show system status and recent workflows.

```bash
gleitzeit status [OPTIONS]
```

**Options:**
- `--backend [sqlite|redis]`: Persistence backend to query

**Output includes:**
- System health status
- Persistence backend information
- Provider availability
- Recent workflow executions
- Queue statistics

**Example:**

```bash
# Show current status
gleitzeit status

# Query Redis backend specifically
gleitzeit status --backend redis
```

### serve

Start the Gleitzeit REST API server.

```bash
gleitzeit serve [OPTIONS]
```

**Options:**
- `-h, --host TEXT`: Host to bind the API server to (default: 0.0.0.0)
- `-p, --port INT`: Port to bind the API server to (default: 8000)
- `--reload`: Enable auto-reload for development
- `-w, --workers INT`: Number of worker processes (default: 1)

**Examples:**

```bash
# Start with defaults (0.0.0.0:8000)
gleitzeit serve

# Custom host and port
gleitzeit serve --host localhost --port 8080

# Development mode with auto-reload
gleitzeit serve --reload

# Production with multiple workers
gleitzeit serve --workers 4
```

**Notes:**
- API documentation is available at `/docs` when the server is running
- Use `CTRL+C` to stop the server
- Auto-reload and multiple workers cannot be used together

### init

Create a new workflow template.

```bash
gleitzeit init NAME [OPTIONS]
```

**Arguments:**
- `NAME`: Name for the new workflow

**Options:**
- `--type [python|llm|mixed]`: Type of workflow template (default: python)

**Templates:**
- `python`: Python code execution workflow
- `llm`: LLM-based text processing workflow
- `mixed`: Combined Python and LLM workflow

**Examples:**

```bash
# Create Python workflow
gleitzeit init data_processor --type python

# Create LLM workflow
gleitzeit init document_analyzer --type llm

# Create mixed workflow
gleitzeit init ai_pipeline --type mixed
```

### config

Show current configuration.

```bash
gleitzeit config
```

**Output includes:**
- Configuration file location
- Persistence settings
- Provider configurations
- Resource limits

**Example:**

```bash
gleitzeit config
```

## Workflow File Format

### YAML Format

```yaml
name: "Example Workflow"
version: "1.0"
description: "Process data with LLM and Python"

tasks:
  - id: fetch_data
    name: "Fetch Data"
    type: python
    provider: python
    params:
      code: |
        import json
        data = {"values": [1, 2, 3, 4, 5]}
        result = json.dumps(data)

  - id: analyze
    name: "Analyze Data"
    type: llm
    provider: ollama
    params:
      model: llama3.2
      messages:
        - role: user
          content: "Analyze this data: ${fetch_data.result}"
    depends_on:
      - fetch_data

outputs:
  data: fetch_data.result
  analysis: analyze.response
```

### JSON Format

```json
{
  "name": "Example Workflow",
  "version": "1.0",
  "tasks": [
    {
      "id": "task1",
      "type": "llm",
      "provider": "ollama",
      "params": {
        "model": "llama3.2",
        "messages": [
          {"role": "user", "content": "Hello"}
        ]
      }
    }
  ]
}
```

## Environment Variables

Configure Gleitzeit via environment variables:

```bash
# Persistence
export GLEITZEIT_PERSISTENCE_TYPE=redis
export GLEITZEIT_REDIS_URL=redis://localhost:6379
export GLEITZEIT_SQL_DB_PATH=~/.gleitzeit/gleitzeit.db

# Providers
export GLEITZEIT_OLLAMA_HOST=localhost
export GLEITZEIT_OLLAMA_PORT=11434

# Execution
export GLEITZEIT_MAX_PARALLEL_TASKS=10
export GLEITZEIT_TASK_TIMEOUT=300

# Logging
export GLEITZEIT_LOG_LEVEL=INFO
export GLEITZEIT_LOG_FILE=./gleitzeit.log
```

## Configuration File

Default location: `~/.gleitzeit/config.yaml`

```yaml
persistence:
  backend: redis
  redis:
    url: redis://localhost:6379
    key_prefix: gleitzeit
  sqlite:
    path: ~/.gleitzeit/gleitzeit.db

providers:
  ollama:
    host: localhost
    port: 11434
    models:
      default: llama3.2:latest
      vision: llava:latest

execution:
  max_parallel_tasks: 10
  task_timeout: 300
  retry_attempts: 3

logging:
  level: INFO
  file: ~/.gleitzeit/gleitzeit.log
```

## Output Formats

### Standard Output

Default human-readable format with emojis and colors:

```
📄 Loading workflow: Document Analysis
🚀 Executing workflow: Document Analysis
   Tasks: 3
   ├── extract_text [✓]
   ├── analyze_content [✓]
   └── generate_report [✓]
✅ Workflow completed!
```

### JSON Output

Machine-readable JSON format:

```bash
gleitzeit run workflow.yaml --output json
```

```json
{
  "workflow_id": "wf-abc123",
  "status": "completed",
  "tasks": [
    {
      "id": "task1",
      "status": "completed",
      "result": "..."
    }
  ]
}
```

### Verbose Output

Detailed execution information:

```bash
gleitzeit --verbose run workflow.yaml
```

```
2024-08-15 10:30:00 - INFO - Loading workflow from workflow.yaml
2024-08-15 10:30:00 - INFO - Initializing ExecutionEngine
2024-08-15 10:30:00 - INFO - Registering OllamaProvider
2024-08-15 10:30:01 - INFO - Submitting workflow: wf-abc123
2024-08-15 10:30:01 - INFO - Executing task: task1
2024-08-15 10:30:05 - INFO - Task task1 completed
```

## Error Handling

### Common Errors

1. **Provider Not Available**
   ```
   ❌ Error: No Ollama instances available
   
   Solution: Start Ollama with 'ollama serve'
   ```

2. **Workflow Validation Failed**
   ```
   ❌ Workflow validation failed:
     • Task 'task2' depends on unknown task 'task1'
   
   Solution: Check task IDs and dependencies
   ```

3. **Persistence Connection Failed**
   ```
   ❌ Failed to connect to Redis
   
   Solution: Start Redis or use --backend sqlite
   ```

### Debug Mode

Enable debug mode for detailed error information:

```bash
gleitzeit --debug run workflow.yaml
```

This provides:
- Full stack traces
- Detailed provider logs
- Task execution details
- Performance metrics

## Examples

### Simple LLM Workflow

```bash
# Create workflow file
cat > simple.yaml << EOF
name: "Simple LLM"
tasks:
  - id: generate
    type: llm
    provider: ollama
    params:
      model: llama3.2
      messages:
        - role: user
          content: "Write a haiku about coding"
EOF

# Run workflow
gleitzeit run simple.yaml
```

### Batch Document Processing

```bash
# Process all markdown files
gleitzeit batch ./docs \
  --pattern "*.md" \
  --prompt "Summarize this document in 3 bullet points" \
  --model llama3.2:7b \
  --output summaries.json

# Process images
gleitzeit batch ./screenshots \
  --pattern "*.png" \
  --vision \
  --prompt "What UI elements are visible?" \
  --output ui_analysis.json
```

### Complex Pipeline

```bash
# Create multi-step workflow
cat > pipeline.yaml << EOF
name: "Data Pipeline"
tasks:
  - id: fetch
    type: python
    provider: python
    params:
      code: |
        import requests
        response = requests.get("https://api.example.com/data")
        result = response.json()
  
  - id: process
    type: python
    provider: python
    params:
      code: |
        data = ${fetch.result}
        processed = [x * 2 for x in data['values']]
        result = processed
    depends_on: [fetch]
  
  - id: summarize
    type: llm
    provider: ollama
    params:
      model: llama3.2
      messages:
        - role: user
          content: "Summarize: ${process.result}"
    depends_on: [process]
EOF

# Run with monitoring
gleitzeit run pipeline.yaml --watch
```

## Tips and Tricks

1. **Use watch mode for long-running workflows**
   ```bash
   gleitzeit run complex_workflow.yaml --watch
   ```

2. **Save batch results for later analysis**
   ```bash
   gleitzeit batch ./data --output results.json
   jq '.["file1.txt"]' results.json
   ```

3. **Test workflows with verbose output**
   ```bash
   gleitzeit --verbose run workflow.yaml
   ```

4. **Override backend for testing**
   ```bash
   gleitzeit run workflow.yaml --backend sqlite
   ```

5. **Create aliases for common operations**
   ```bash
   alias glz='gleitzeit'
   alias glz-run='gleitzeit run --watch'
   alias glz-batch='gleitzeit batch --model llama3.2:7b'
   ```

## Performance Considerations

- **Parallel Execution**: Batch commands process files in parallel (default: 5 concurrent)
- **Persistence Backend**: Redis is faster for high-throughput; SQLite better for single-instance
- **Model Selection**: Smaller models (3B, 7B) are faster; larger models (70B) provide better quality
- **Resource Limits**: Configure `GLEITZEIT_MAX_PARALLEL_TASKS` based on system resources

## Troubleshooting

### Check System Status
```bash
gleitzeit status
```

### Enable Debug Logging
```bash
gleitzeit --debug run workflow.yaml
```

### Test Provider Connection
```bash
# Create a simple test workflow
echo 'name: test
tasks:
  - name: test_python
    protocol: python/v1
    method: python/execute
    params:
      file: /path/to/test.py' > test.yaml
gleitzeit run test.yaml
```

### Verify Configuration
```bash
gleitzeit config
```

### Clean Persistence
```bash
# SQLite
rm ~/.gleitzeit/gleitzeit.db

# Redis
redis-cli FLUSHDB
```