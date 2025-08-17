# Configuration Guide

## Overview

Gleitzeit v0.0.5 can be configured through multiple methods with a clear precedence order:
1. Command-line arguments (highest priority)
2. Environment variables
3. Configuration files
4. Default values (lowest priority)

## Configuration Methods

### 1. Configuration Files

#### Default Configuration File Location
```bash
# Linux/macOS
~/.config/gleitzeit/config.yaml

# Windows
%APPDATA%\gleitzeit\config.yaml

# Custom location
gleitzeit --config /path/to/config.yaml
```

#### Configuration File Format
```yaml
# config.yaml
persistence:
  type: redis  # redis, sqlite, memory, auto
  redis:
    url: redis://localhost:6379
    password: ${REDIS_PASSWORD}  # Environment variable substitution
    db: 0
    max_connections: 50
  sqlite:
    path: ./gleitzeit.db
    timeout: 30
    check_same_thread: false

execution:
  max_parallel_tasks: 20
  task_timeout: 300
  retry_enabled: true
  retry_max_attempts: 3
  retry_backoff_factor: 2.0

resources:
  ollama:
    default_host: localhost
    default_port: 11434
    health_check_interval: 30
    auto_recovery: true
    max_instances: 10
  docker:
    socket: unix:///var/run/docker.sock
    default_image: python:3.11-slim
    max_containers: 20
    cleanup_interval: 300
    enable_reuse: true

api:
  host: 0.0.0.0
  port: 8000
  cors_enabled: true
  cors_origins: ["*"]
  rate_limit_enabled: true
  rate_limit_requests: 100
  rate_limit_window: 60

logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: ./logs/gleitzeit.log
  max_size: 10485760  # 10MB
  backup_count: 5
  console: true

security:
  api_key_required: false
  api_key: ${GLEITZEIT_API_KEY}
  jwt_enabled: false
  jwt_secret: ${JWT_SECRET}
  jwt_expiration: 3600
```

### 2. Environment Variables

All configuration options can be set via environment variables with the prefix `GLEITZEIT_`:

```bash
# Persistence Configuration
export GLEITZEIT_PERSISTENCE_TYPE=redis
export GLEITZEIT_REDIS_URL=redis://localhost:6379
export GLEITZEIT_REDIS_PASSWORD=secret
export GLEITZEIT_REDIS_DB=0
export GLEITZEIT_SQLITE_PATH=./gleitzeit.db
export GLEITZEIT_SQLITE_TIMEOUT=30

# Execution Configuration
export GLEITZEIT_MAX_PARALLEL_TASKS=20
export GLEITZEIT_TASK_TIMEOUT=300
export GLEITZEIT_RETRY_ENABLED=true
export GLEITZEIT_RETRY_MAX_ATTEMPTS=3

# Resource Configuration
export GLEITZEIT_OLLAMA_HOST=localhost
export GLEITZEIT_OLLAMA_PORT=11434
export GLEITZEIT_OLLAMA_HEALTH_CHECK_INTERVAL=30
export GLEITZEIT_DOCKER_SOCKET=unix:///var/run/docker.sock
export GLEITZEIT_DOCKER_DEFAULT_IMAGE=python:3.11-slim

# API Configuration
export GLEITZEIT_API_HOST=0.0.0.0
export GLEITZEIT_API_PORT=8000
export GLEITZEIT_API_KEY=your-secret-key

# Logging Configuration
export GLEITZEIT_LOG_LEVEL=INFO
export GLEITZEIT_LOG_FILE=./gleitzeit.log
export GLEITZEIT_LOG_FORMAT="%(asctime)s - %(levelname)s - %(message)s"
```

### 3. Command-Line Arguments

Override any configuration at runtime:

```bash
# Override persistence type
gleitzeit --persistence redis --redis-url redis://prod-server:6379

# Override execution settings
gleitzeit --max-parallel 50 --task-timeout 600

# Override logging
gleitzeit --log-level DEBUG --log-file debug.log

# Use custom config file
gleitzeit --config production.yaml
```

### 4. Python API Configuration

```python
from gleitzeit import GleitzeitClient

# Direct configuration
client = GleitzeitClient(
    persistence="redis",
    redis_url="redis://localhost:6379",
    max_parallel_tasks=30,
    task_timeout=600,
    log_level="DEBUG"
)

# Using configuration dict
config = {
    "persistence": {
        "type": "redis",
        "redis": {
            "url": "redis://localhost:6379"
        }
    },
    "execution": {
        "max_parallel_tasks": 30
    }
}
client = GleitzeitClient.from_config(config)

# Load from file
client = GleitzeitClient.from_config_file("config.yaml")
```

## Configuration Options Reference

### Persistence Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `persistence.type` | string | auto | Persistence backend (redis, sqlite, memory, auto) |
| `persistence.redis.url` | string | redis://localhost:6379 | Redis connection URL |
| `persistence.redis.password` | string | - | Redis password |
| `persistence.redis.db` | int | 0 | Redis database number |
| `persistence.redis.max_connections` | int | 50 | Maximum Redis connections |
| `persistence.redis.socket_keepalive` | bool | true | Enable TCP keepalive |
| `persistence.sqlite.path` | string | ./gleitzeit.db | SQLite database path |
| `persistence.sqlite.timeout` | int | 30 | SQLite connection timeout |
| `persistence.sqlite.journal_mode` | string | WAL | SQLite journal mode |
| `persistence.memory.max_size` | int | - | Maximum memory cache size (bytes) |

### Execution Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `execution.max_parallel_tasks` | int | 10 | Maximum parallel task execution |
| `execution.task_timeout` | int | 300 | Default task timeout (seconds) |
| `execution.retry_enabled` | bool | true | Enable automatic retry |
| `execution.retry_max_attempts` | int | 3 | Maximum retry attempts |
| `execution.retry_backoff_factor` | float | 2.0 | Exponential backoff factor |
| `execution.retry_max_backoff` | int | 60 | Maximum backoff time (seconds) |
| `execution.queue_type` | string | memory | Task queue type |
| `execution.checkpoint_enabled` | bool | false | Enable workflow checkpointing |
| `execution.checkpoint_interval` | int | 60 | Checkpoint save interval |

### Resource Options

#### Ollama Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `resources.ollama.default_host` | string | localhost | Default Ollama host |
| `resources.ollama.default_port` | int | 11434 | Default Ollama port |
| `resources.ollama.health_check_interval` | int | 30 | Health check interval (seconds) |
| `resources.ollama.auto_recovery` | bool | true | Enable auto-recovery |
| `resources.ollama.max_instances` | int | 10 | Maximum Ollama instances |
| `resources.ollama.connection_timeout` | int | 30 | Connection timeout |
| `resources.ollama.request_timeout` | int | 300 | Request timeout |
| `resources.ollama.retry_on_failure` | bool | true | Retry failed requests |

#### Docker Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `resources.docker.socket` | string | unix:///var/run/docker.sock | Docker socket path |
| `resources.docker.default_image` | string | python:3.11-slim | Default container image |
| `resources.docker.max_containers` | int | 20 | Maximum containers |
| `resources.docker.memory_limit` | string | 512m | Container memory limit |
| `resources.docker.cpu_limit` | float | 1.0 | Container CPU limit |
| `resources.docker.cleanup_interval` | int | 300 | Cleanup interval (seconds) |
| `resources.docker.enable_reuse` | bool | true | Enable container reuse |
| `resources.docker.network_mode` | string | none | Container network mode |

### API Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `api.host` | string | 0.0.0.0 | API server host |
| `api.port` | int | 8000 | API server port |
| `api.workers` | int | 4 | Number of API workers |
| `api.cors_enabled` | bool | true | Enable CORS |
| `api.cors_origins` | list | ["*"] | Allowed CORS origins |
| `api.rate_limit_enabled` | bool | false | Enable rate limiting |
| `api.rate_limit_requests` | int | 100 | Rate limit requests |
| `api.rate_limit_window` | int | 60 | Rate limit window (seconds) |
| `api.max_request_size` | int | 10485760 | Maximum request size (bytes) |

### Logging Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `logging.level` | string | INFO | Log level |
| `logging.format` | string | %(asctime)s - %(levelname)s - %(message)s | Log format |
| `logging.file` | string | - | Log file path |
| `logging.max_size` | int | 10485760 | Max log file size (bytes) |
| `logging.backup_count` | int | 5 | Number of backup files |
| `logging.console` | bool | true | Enable console output |
| `logging.json` | bool | false | JSON formatted logs |
| `logging.syslog` | bool | false | Send to syslog |

### Security Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `security.api_key_required` | bool | false | Require API key |
| `security.api_key` | string | - | API key value |
| `security.jwt_enabled` | bool | false | Enable JWT auth |
| `security.jwt_secret` | string | - | JWT secret key |
| `security.jwt_algorithm` | string | HS256 | JWT algorithm |
| `security.jwt_expiration` | int | 3600 | Token expiration (seconds) |
| `security.tls_enabled` | bool | false | Enable TLS |
| `security.tls_cert` | string | - | TLS certificate path |
| `security.tls_key` | string | - | TLS key path |

## Configuration Profiles

### Development Profile

```yaml
# config-dev.yaml
persistence:
  type: sqlite
  sqlite:
    path: ./dev.db

execution:
  max_parallel_tasks: 5
  task_timeout: 60

logging:
  level: DEBUG
  console: true

api:
  host: localhost
  port: 8000
```

### Production Profile

```yaml
# config-prod.yaml
persistence:
  type: redis
  redis:
    url: redis://redis-cluster:6379
    password: ${REDIS_PASSWORD}
    max_connections: 100

execution:
  max_parallel_tasks: 50
  task_timeout: 600
  retry_enabled: true

logging:
  level: WARNING
  file: /var/log/gleitzeit/app.log
  json: true

security:
  api_key_required: true
  api_key: ${API_KEY}
  tls_enabled: true
```

### Testing Profile

```yaml
# config-test.yaml
persistence:
  type: memory

execution:
  max_parallel_tasks: 2
  task_timeout: 10

logging:
  level: ERROR
  console: false
```

## Dynamic Configuration

### Hot Reload

Configuration can be reloaded without restart:

```python
# Signal handler for config reload
import signal

def reload_config(signum, frame):
    client.reload_config()

signal.signal(signal.SIGHUP, reload_config)
```

### Runtime Updates

```python
# Update configuration at runtime
client.update_config({
    "execution": {
        "max_parallel_tasks": 50
    }
})

# Get current configuration
config = client.get_config()
print(config)
```

## Provider-Specific Configuration

### Ollama Provider

```yaml
providers:
  ollama:
    enabled: true
    default_model: llama3.2
    default_temperature: 0.7
    streaming_enabled: true
    timeout: 300
    retry_attempts: 3
```

### Python Provider

```yaml
providers:
  python:
    enabled: true
    execution_mode: docker  # docker or disabled
    allowed_imports:
      - numpy
      - pandas
      - json
    max_execution_time: 60
    max_memory: 512m
```

### MCP Provider

```yaml
providers:
  mcp:
    enabled: true
    servers:
      - name: calculator
        command: python
        args: [mcp_calculator.py]
        env:
          PYTHONPATH: /app
      - name: database
        command: node
        args: [mcp_database.js]
```

## Validation

### Configuration Validation

```bash
# Validate configuration file
gleitzeit config validate config.yaml

# Test configuration
gleitzeit config test --persistence --resources
```

### Schema Validation

```python
from gleitzeit.config import ConfigSchema

# Validate configuration
schema = ConfigSchema()
errors = schema.validate(config)
if errors:
    print("Configuration errors:", errors)
```

## Best Practices

### 1. Use Environment Variables for Secrets
```yaml
# Never hardcode secrets
security:
  api_key: ${API_KEY}  # Good
  # api_key: "hardcoded-secret"  # Bad
```

### 2. Profile-Based Configuration
```bash
# Use different configs for different environments
gleitzeit --config config-${ENVIRONMENT}.yaml
```

### 3. Configuration Hierarchy
```yaml
# base.yaml - Shared configuration
# dev.yaml - Extends base.yaml
# prod.yaml - Extends base.yaml
```

### 4. Validate Before Deployment
```bash
# Always validate configuration
gleitzeit config validate config.yaml && gleitzeit serve
```

### 5. Use Sensible Defaults
```python
# Provide defaults in code
config = {
    "persistence": {
        "type": os.getenv("GLEITZEIT_PERSISTENCE_TYPE", "auto")
    }
}
```

## Troubleshooting Configuration

### Configuration Not Loading

```bash
# Check configuration file location
gleitzeit config show --sources

# Debug configuration loading
GLEITZEIT_LOG_LEVEL=DEBUG gleitzeit config show
```

### Environment Variables Not Working

```bash
# Check environment variables
env | grep GLEITZEIT

# Debug with explicit values
GLEITZEIT_PERSISTENCE_TYPE=redis gleitzeit --debug
```

### Validation Errors

```bash
# Get detailed validation errors
gleitzeit config validate --verbose config.yaml

# Check schema version
gleitzeit config schema --version
```

## Migration from v0.0.4

### Changed Configuration Keys

```yaml
# v0.0.4
task_queue:
  backend: redis

# v0.0.5
persistence:
  type: redis
```

### New Required Configuration

```yaml
# v0.0.5 requires hub configuration
resources:
  ollama:
    default_host: localhost
  docker:
    socket: unix:///var/run/docker.sock
```

## Summary

Gleitzeit's configuration system provides:
- **Multiple configuration methods** with clear precedence
- **Environment variable substitution** for secrets
- **Profile-based configuration** for different environments
- **Runtime configuration updates** without restart
- **Comprehensive validation** before deployment
- **Sensible defaults** for zero-configuration startup