# Troubleshooting

Common issues and solutions for Gleitzeit.

## Installation Issues

### pip install fails

**Error:** `error: Microsoft Visual C++ 14.0 or greater is required`

**Solution (Windows):**
```bash
# Install Visual Studio Build Tools
# Or use conda instead of pip
conda install gleitzeit
```

**Error:** `No matching distribution found for gleitzeit`

**Solution:**
```bash
# Upgrade pip
pip install --upgrade pip

# Try again
pip install gleitzeit
```

### Import errors

**Error:** `ModuleNotFoundError: No module named 'gleitzeit'`

**Solution:**
```bash
# Verify installation
pip list | grep gleitzeit

# Reinstall
pip uninstall gleitzeit
pip install gleitzeit

# Check Python path
python -c "import sys; print(sys.path)"
```

## Ollama Issues

### Ollama not available

**Error:** `Ollama not available at http://localhost:11434`

**Solution:**
```bash
# Start Ollama
ollama serve

# Check if running
curl http://localhost:11434/api/tags

# Use different port
export GLEITZEIT_OLLAMA_URL=http://localhost:11435
```

### Model not found

**Error:** `model 'llama3.2' not found`

**Solution:**
```bash
# Pull the model
ollama pull llama3.2

# List available models
ollama list

# Use a different model
gleitzeit run workflow.yaml --model mistral
```

### Ollama timeout

**Error:** `Task timeout after 30 seconds`

**Solution:**
```yaml
# Increase timeout in workflow
tasks:
  - id: "task"
    method: "llm/chat"
    parameters:
      timeout: 120  # 2 minutes
```

Or globally:
```bash
export GLEITZEIT_DEFAULT_TIMEOUT=120
```

### Memory issues with large models

**Error:** `Ollama out of memory`

**Solution:**
```bash
# Use smaller model
ollama pull phi  # Smaller model

# Limit context size
export OLLAMA_NUM_CTX=2048
```

## Persistence Issues

### Redis connection failed

**Error:** `Cannot connect to Redis at localhost:6379`

**Solution:**
```bash
# Start Redis
redis-server

# Check if running
redis-cli ping

# Use SQLite fallback
export GLEITZEIT_PERSISTENCE_TYPE=sqlite

# Or use memory (temporary)
export GLEITZEIT_PERSISTENCE_TYPE=memory
```

### SQLite locked

**Error:** `database is locked`

**Solution:**
```bash
# Remove lock file
rm ~/.gleitzeit/workflows.db-journal

# Or use different database
export GLEITZEIT_SQL_DB_PATH=~/workflows_new.db
```

### Data not persisting

**Issue:** Workflows not saved between runs

**Solution:**
```bash
# Check persistence type
gleitzeit status

# Force persistent backend
export GLEITZEIT_PERSISTENCE_TYPE=sqlite
# or
export GLEITZEIT_PERSISTENCE_TYPE=redis
```

## Workflow Issues

### Workflow validation fails

**Error:** `Invalid workflow format`

**Solution:**
```bash
# Validate workflow
gleitzeit validate workflow.yaml --verbose

# Common issues:
# - Missing 'tasks' key
# - Invalid YAML syntax
# - Duplicate task IDs
```

**Example fix:**
```yaml
# Wrong
tasks:
- id: task1  # Missing quotes

# Correct
tasks:
  - id: "task1"
```

### Task dependencies not working

**Issue:** Tasks run in wrong order

**Solution:**
```yaml
# Ensure dependencies are lists
tasks:
  - id: "task1"
    method: "llm/chat"
  
  - id: "task2"
    dependencies: ["task1"]  # Must be a list
    method: "llm/chat"
```

### Parameter substitution fails

**Error:** `Unknown variable: ${task1.response}`

**Solution:**
```yaml
# Check task ID matches
tasks:
  - id: "generate"  # Note the ID
    method: "llm/chat"
  
  - id: "use"
    dependencies: ["generate"]
    parameters:
      content: "${generate.response}"  # Must match ID
```

## Python Script Issues

### Script not found

**Error:** `Script 'process.py' not found`

**Solution:**
```bash
# Check script path
ls scripts/process.py

# Set scripts directory
export GLEITZEIT_SCRIPTS_DIR=./scripts

# Or use absolute path
```

```yaml
parameters:
  script: "/absolute/path/to/process.py"
```

### Script execution fails

**Error:** `Script returned non-zero exit code`

**Solution:**
```python
# Debug script standalone
python script.py '{"test": "data"}'

# Common issues:
# - Missing imports
# - Syntax errors
# - Not outputting JSON
```

**Correct script format:**
```python
import sys
import json

args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
# Process...
print(json.dumps({"result": "data"}))  # Must output JSON
```

### Script timeout

**Error:** `Python script timeout`

**Solution:**
```yaml
# Increase timeout
parameters:
  script: "long_running.py"
  timeout: 300  # 5 minutes
```

## API Server Issues

### Server won't start

**Error:** `Address already in use`

**Solution:**
```bash
# Find process using port
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# Kill process or use different port
gleitzeit serve --port 9000
```

### Can't connect to API

**Error:** `Connection refused`

**Solution:**
```bash
# Start server
gleitzeit serve

# Check if running
curl http://localhost:8000/health

# Use correct host/port in client
```

```python
client = GleitzeitClient(
    mode="api",
    api_host="localhost",
    api_port=8000
)
```

### CORS errors

**Error:** `CORS policy blocked`

**Solution:**
```yaml
# Enable CORS in config
api:
  cors:
    enabled: true
    origins: ["*"]  # Or specific origins
```

## Performance Issues

### Slow execution

**Issue:** Workflows running slowly

**Solutions:**

1. **Increase parallelism:**
```yaml
execution:
  max_parallel_tasks: 10
```

2. **Use smaller models:**
```yaml
parameters:
  model: "phi"  # Faster than llama3.2
```

3. **Enable caching:**
```yaml
persistence:
  type: redis  # Faster than SQLite
```

4. **Batch operations:**
```python
# Process files in parallel
results = await client.batch_process(
    directory="docs",
    max_concurrent=10
)
```

### Memory leaks

**Issue:** Memory usage increases over time

**Solution:**
```python
# Always use context managers
async with GleitzeitClient() as client:
    # Operations
    pass  # Automatic cleanup

# Don't do this:
client = GleitzeitClient()
# Missing cleanup!
```

### Task hanging

**Issue:** Task never completes

**Solution:**
```yaml
# Set timeout
tasks:
  - id: "task"
    parameters:
      timeout: 30
```

Or kill hanging task:
```bash
# Find and kill process
ps aux | grep gleitzeit
kill -9 <PID>
```

## Debugging

### Enable debug logging

```bash
# Via environment
export GLEITZEIT_LOG_LEVEL=DEBUG

# Via CLI
gleitzeit --debug run workflow.yaml

# In Python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### View logs

```bash
# Follow logs
gleitzeit logs --follow

# View errors only
gleitzeit logs --level error

# Check log file
tail -f ~/.gleitzeit/gleitzeit.log
```

### Test components

```bash
# Test Ollama
curl http://localhost:11434/api/generate \
  -d '{"model": "llama3.2", "prompt": "test"}'

# Test Redis
redis-cli ping

# Test Python scripts
python script.py '{"test": "data"}'
```

### Trace workflow execution

```yaml
# Enable tracing
development:
  trace_tasks: true
```

## Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `Connection refused` | Service not running | Start the service |
| `Model not found` | Model not installed | `ollama pull <model>` |
| `Timeout error` | Operation too slow | Increase timeout |
| `Invalid JSON` | Script output issue | Ensure JSON output |
| `Task not found` | Wrong task ID | Check task ID spelling |
| `Permission denied` | File permissions | Check file permissions |
| `Out of memory` | Resource exhaustion | Use smaller models/data |
| `Database locked` | Concurrent access | Use Redis or wait |

## Getting Help

### Check documentation

```bash
# Built-in help
gleitzeit --help
gleitzeit run --help

# Online docs
https://github.com/leifmarkthaler/gleitzeit
```

### Debug information

```bash
# System information
gleitzeit status --verbose

# Version info
gleitzeit --version

# Configuration
gleitzeit config show
```

### Report issues

1. Check existing issues: https://github.com/leifmarkthaler/gleitzeit/issues
2. Provide:
   - Gleitzeit version
   - Python version
   - Operating system
   - Error messages
   - Minimal reproduction example

### Minimal reproduction

```yaml
# minimal.yaml
name: "Reproduction"
tasks:
  - id: "failing_task"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "This fails"
```

```bash
# Run with debug
gleitzeit --debug run minimal.yaml > debug.log 2>&1
```

## Recovery

### Reset configuration

```bash
# Backup current config
cp ~/.gleitzeit/config.yaml ~/.gleitzeit/config.backup.yaml

# Reset to defaults
gleitzeit config reset --confirm
```

### Clear persistence

```bash
# Clear Redis
redis-cli FLUSHDB

# Remove SQLite
rm ~/.gleitzeit/workflows.db

# Start fresh
gleitzeit run workflow.yaml
```

### Reinstall

```bash
# Complete reinstall
pip uninstall gleitzeit
rm -rf ~/.gleitzeit
pip install gleitzeit
```