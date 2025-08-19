# Configuration

Gleitzeit can be configured through configuration files, environment variables, and command-line options.

## Configuration Priority

Configuration is applied in this order (highest priority first):

1. Command-line options
2. Environment variables
3. Configuration file
4. Default values

## Configuration File

Default location: `~/.gleitzeit/config.yaml`

### Complete Configuration Example

```yaml
# Gleitzeit Configuration

# General settings
general:
  log_level: INFO           # DEBUG, INFO, WARNING, ERROR
  log_file: ~/.gleitzeit/gleitzeit.log
  working_directory: ~/workflows

# Ollama settings
ollama:
  url: http://localhost:11434
  default_model: llama3.2
  timeout: 30
  max_retries: 3
  discovery:
    enabled: true
    ports: [11434, 11435, 11436, 11437, 11438, 11439]
    interval: 60  # seconds
  models:
    chat: llama3.2
    vision: llava
    code: codellama
    small: phi

# Persistence configuration
persistence:
  type: auto  # auto, redis, sqlite, memory
  
  redis:
    url: redis://localhost:6379/0
    password: null
    key_prefix: gleitzeit
    ttl: 86400  # 24 hours
    max_connections: 10
  
  sqlite:
    db_path: ~/.gleitzeit/workflows.db
    journal_mode: WAL
    timeout: 5.0
  
  memory:
    max_size: 1000  # Maximum entries

# Execution settings
execution:
  max_parallel_tasks: 5
  default_timeout: 30
  continue_on_error: false
  retry:
    enabled: true
    max_attempts: 3
    initial_delay: 1
    exponential_backoff: true
    max_delay: 30

# Python provider settings
python:
  timeout: 60
  sandbox: true
  max_memory: 512M
  allowed_modules:
    - json
    - csv
    - math
    - datetime
    - os
    - sys
    - pathlib
  scripts_directory: ./scripts

# Template provider settings
template:
  default_depth: "medium"  # shallow, medium, deep
  max_research_steps: 5
  code_languages:
    - python
    - javascript
    - java
  enable_testing: true  # Enable code testing for supported languages

# Batch processing
batch:
  max_concurrent: 5
  max_file_size: 1048576  # 1MB
  recursive: false
  ignore_patterns:
    - "*.pyc"
    - "__pycache__"
    - ".git"

# API server settings
api:
  host: 0.0.0.0
  port: 8000
  auto_start: true
  keep_running: true
  cors:
    enabled: true
    origins: ["*"]
  authentication:
    enabled: false
    token: null

# Resource management
resources:
  enabled: false
  ollama_hub:
    min_instances: 1
    max_instances: 5
    scale_up_threshold: 0.8
    scale_down_threshold: 0.2
  docker_hub:
    enabled: false
    max_containers: 10
    image: gleitzeit/python:latest

# Development settings
development:
  debug: false
  reload: false
  profile: false
  trace_tasks: false
```

### Minimal Configuration

```yaml
# Minimal config - uses defaults for everything else
ollama:
  default_model: mistral

persistence:
  type: redis
  redis:
    url: redis://localhost:6379
```

## Environment Variables

All configuration options can be set via environment variables.

### General Variables

```bash
export GLEITZEIT_LOG_LEVEL=DEBUG
export GLEITZEIT_LOG_FILE=/var/log/gleitzeit.log
export GLEITZEIT_WORKING_DIR=/workspace
```

### Ollama Configuration

```bash
export GLEITZEIT_OLLAMA_URL=http://localhost:11434
export GLEITZEIT_DEFAULT_MODEL=llama3.2
export GLEITZEIT_OLLAMA_TIMEOUT=30
export GLEITZEIT_OLLAMA_MAX_RETRIES=3
```

### Persistence Configuration

```bash
# Persistence type
export GLEITZEIT_PERSISTENCE_TYPE=redis  # auto, redis, sqlite, memory

# Redis
export GLEITZEIT_REDIS_URL=redis://localhost:6379/0
export GLEITZEIT_REDIS_PASSWORD=secret
export GLEITZEIT_REDIS_KEY_PREFIX=gleitzeit
export GLEITZEIT_REDIS_TTL=86400

# SQLite
export GLEITZEIT_SQL_DB_PATH=~/.gleitzeit/workflows.db
export GLEITZEIT_SQL_JOURNAL_MODE=WAL
```

### Execution Configuration

```bash
export GLEITZEIT_MAX_PARALLEL_TASKS=10
export GLEITZEIT_DEFAULT_TIMEOUT=60
export GLEITZEIT_CONTINUE_ON_ERROR=true
export GLEITZEIT_RETRY_ENABLED=true
export GLEITZEIT_RETRY_MAX_ATTEMPTS=3
```

### API Server Configuration

```bash
export GLEITZEIT_API_HOST=0.0.0.0
export GLEITZEIT_API_PORT=8000
export GLEITZEIT_API_AUTO_START=true
export GLEITZEIT_API_CORS_ENABLED=true
```

## Command-Line Options

Override configuration at runtime:

```bash
# Override model
gleitzeit run workflow.yaml --model mistral

# Override API settings
gleitzeit run workflow.yaml --host localhost --port 9000

# Force local execution
gleitzeit run workflow.yaml --local

# Set log level
gleitzeit --verbose run workflow.yaml
gleitzeit --debug run workflow.yaml
```

## Client Configuration

### Python Client

```python
from gleitzeit import GleitzeitClient

# Use environment variables
client = GleitzeitClient()

# Override with parameters
client = GleitzeitClient(
    mode="api",
    api_host="custom.host",
    api_port=9000,
    native_config={
        "max_parallel_tasks": 10,
        "default_timeout": 60,
        "enable_resource_management": True
    }
)
```

### Client Config Dictionary

```python
config = {
    "mode": "native",
    "native_config": {
        "enable_resource_management": True,
        "max_parallel_tasks": 10,
        "default_timeout": 60,
        "persistence": {
            "type": "redis",
            "redis": {
                "url": "redis://localhost:6379"
            }
        },
        "ollama": {
            "url": "http://localhost:11434",
            "default_model": "llama3.2"
        }
    }
}

client = GleitzeitClient(**config)
```

## Per-Workflow Configuration

Override settings in workflow files:

```yaml
name: "Custom Config Workflow"
config:
  timeout: 120
  max_parallel: 10
  continue_on_error: true
  
tasks:
  - id: "task1"
    method: "llm/chat"
    # Inherits workflow config
```

## Model-Specific Configuration

Configure model parameters:

```yaml
# In config.yaml
models:
  llama3.2:
    temperature: 0.7
    max_tokens: 500
    top_p: 0.9
  
  mistral:
    temperature: 0.5
    max_tokens: 1000
  
  codellama:
    temperature: 0.3
    max_tokens: 2000
```

## Security Configuration

### API Authentication

```yaml
api:
  authentication:
    enabled: true
    type: bearer  # bearer, basic, api_key
    token: "your-secret-token"
    users:
      - username: admin
        password_hash: "$2b$12$..."
```

### Python Sandbox

```yaml
python:
  sandbox: true
  allowed_paths:
    - /workspace
    - /tmp
  blocked_modules:
    - subprocess
    - socket
    - requests
  max_execution_time: 60
  max_memory: 512M
```

## Logging Configuration

### Log Levels

- `DEBUG`: Detailed debugging information
- `INFO`: General information
- `WARNING`: Warning messages
- `ERROR`: Error messages only

### Log Format

```yaml
logging:
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  date_format: "%Y-%m-%d %H:%M:%S"
  file:
    enabled: true
    path: ~/.gleitzeit/gleitzeit.log
    max_size: 10485760  # 10MB
    backup_count: 5
  console:
    enabled: true
    colorize: true
```

## Performance Tuning

### Connection Pooling

```yaml
performance:
  connection_pool:
    max_size: 100
    min_size: 10
    timeout: 30
  
  cache:
    enabled: true
    size: 1000
    ttl: 3600
```

### Resource Limits

```yaml
limits:
  max_workflow_size: 10485760  # 10MB
  max_task_output: 1048576     # 1MB
  max_parallel_workflows: 10
  max_queue_size: 1000
```

## Development Configuration

### Debug Mode

```yaml
development:
  debug: true
  reload: true          # Auto-reload on file changes
  profile: true         # Enable profiling
  trace_tasks: true     # Detailed task tracing
  mock_providers: false # Use mock providers for testing
```

### Testing Configuration

```yaml
testing:
  use_mock_ollama: true
  mock_responses:
    default: "Mock response"
  disable_retries: true
  fast_timeouts: true
```

## Configuration Validation

Validate configuration file:

```bash
gleitzeit config validate

# Or with specific file
gleitzeit config validate --file custom-config.yaml
```

## Default Paths

| Item | Default Path |
|------|-------------|
| Config file | `~/.gleitzeit/config.yaml` |
| Log file | `~/.gleitzeit/gleitzeit.log` |
| SQLite DB | `~/.gleitzeit/workflows.db` |
| Scripts | `./scripts/` |
| Workflows | `./workflows/` |

## Migration from Older Versions

### From v0.0.4 to v0.0.5

Old configuration (v0.0.4):
```yaml
ollama_url: http://localhost:11434
default_model: llama3.2
redis_url: redis://localhost:6379
```

New configuration (v0.0.5):
```yaml
ollama:
  url: http://localhost:11434
  default_model: llama3.2

persistence:
  type: redis
  redis:
    url: redis://localhost:6379
```

## Best Practices

1. **Use configuration files** for static settings
2. **Use environment variables** for deployment-specific settings
3. **Use command-line options** for one-time overrides
4. **Keep secrets in environment variables**, not config files
5. **Version control config templates**, not actual configs
6. **Validate configuration** before deployment
7. **Use appropriate log levels** (INFO for production, DEBUG for development)
8. **Set reasonable timeouts** to prevent hanging
9. **Configure retries** for reliability
10. **Monitor resource limits** in production

## Examples

### Production Configuration

```yaml
general:
  log_level: INFO
  
ollama:
  url: http://ollama.internal:11434
  timeout: 60
  max_retries: 5

persistence:
  type: redis
  redis:
    url: redis://redis.internal:6379
    password: ${REDIS_PASSWORD}  # From environment

execution:
  max_parallel_tasks: 20
  default_timeout: 120

api:
  host: 0.0.0.0
  port: 8000
  authentication:
    enabled: true
    token: ${API_TOKEN}  # From environment
```

### Development Configuration

```yaml
general:
  log_level: DEBUG

ollama:
  url: http://localhost:11434
  default_model: llama3.2

persistence:
  type: memory  # Fast for development

execution:
  max_parallel_tasks: 2
  continue_on_error: true

development:
  debug: true
  reload: true
  trace_tasks: true
```