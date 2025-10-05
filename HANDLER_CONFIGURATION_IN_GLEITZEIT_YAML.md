# Handler Configuration in gleitzeit.yaml

## Executive Summary

This document demonstrates how to extend `gleitzeit.yaml` to include handler-specific configurations, execution modes, and provider settings. The existing architecture already supports handler configuration through the worker's `handler_configs` parameter, making it straightforward to add comprehensive handler settings to the YAML configuration.

## Current Configuration Support

### Existing Handler Configuration Path

The task execution worker already looks for handler configurations:

```python
# src/gleitzeit/workers/task_execution_worker.py:76-77
handler_config = self.config.__dict__.get('handler_configs', {}).get(protocol, {})
handler_instance = handler_class(config=handler_config)
```

This means we can pass handler-specific configurations through the worker configuration in `gleitzeit.yaml`.

## Proposed Handler Configuration Schema

### Complete gleitzeit.yaml with Handler Support

```yaml
# Gleitzeit Configuration with Handler Support
# Version: 0.0.7+

# Redis configuration (existing)
redis:
  mode: single
  single_node:
    host: localhost
    port: 6379

# Handler Configuration Section (NEW)
handlers:
  # Global handler settings
  global:
    # Default execution mode for all handlers
    default_execution_mode: native
    # Enable handler metrics collection
    metrics_enabled: true
    # Default timeout for handler operations
    default_timeout: 300
    # Circuit breaker defaults
    circuit_breaker:
      enabled: true
      failure_threshold: 5
      success_threshold: 2
      reset_timeout: 60

  # Python Handler Configuration
  python:
    # Execution mode configuration
    execution:
      mode: ${PYTHON_HANDLER_MODE:-subprocess}  # native, subprocess, container, remote
      fallback_mode: native
      isolation_level: process

    # Handler-specific settings
    config:
      # Subprocess pool configuration
      subprocess_pool_enabled: true
      subprocess_pool_min_size: 2
      subprocess_pool_max_size: 10
      default_timeout: 300

      # Resource limits for subprocess execution
      resource_limits:
        cpu: 1.0
        memory: "512M"
        max_execution_time: 300

    # Container execution settings
    container:
      enabled: ${ENABLE_PYTHON_CONTAINER:-false}
      image: gleitzeit/python-handler:${PYTHON_HANDLER_VERSION:-latest}
      network: gleitzeit
      volumes:
        - source: /data
          target: /data
          mode: rw
      environment:
        PYTHONPATH: /app/src
        PYTHON_HANDLER_MODE: container
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          memory: 128M

    # Remote execution settings
    remote:
      enabled: ${ENABLE_PYTHON_REMOTE:-false}
      endpoints:
        - ${PYTHON_HANDLER_URL_1:-http://python-handler-1:8080}
        - ${PYTHON_HANDLER_URL_2:-http://python-handler-2:8080}
      load_balancing: round_robin
      health_check_path: /health
      retry_policy:
        max_attempts: 3
        backoff_ms: 100

  # Ollama Handler Configuration
  ollama:
    execution:
      mode: ${OLLAMA_HANDLER_MODE:-remote}
      fallback_mode: container

    config:
      # Ollama service URL
      base_url: ${OLLAMA_URL:-http://localhost:11434}
      timeout: ${OLLAMA_TIMEOUT:-300}
      default_model: ${OLLAMA_DEFAULT_MODEL:-llama2}

      # Default generation options
      default_options:
        temperature: 0.7
        top_k: 40
        top_p: 0.9

      # Circuit breaker for Ollama service
      circuit_breaker:
        enabled: true
        failure_threshold: 3
        success_threshold: 2
        reset_timeout: 60
        half_open_max_calls: 3

    # Container settings for local Ollama
    container:
      enabled: ${ENABLE_OLLAMA_CONTAINER:-false}
      image: ollama/ollama:latest
      network: gleitzeit
      ports:
        - "11434:11434"
      volumes:
        - source: ollama-models
          target: /root/.ollama
          type: volume
      environment:
        OLLAMA_KEEP_ALIVE: 5m
      resources:
        limits:
          memory: 8G
        reservations:
          memory: 4G
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  # HTTP Handler Configuration
  http:
    execution:
      mode: ${HTTP_HANDLER_MODE:-native}

    config:
      timeout: 30
      max_retries: 3
      retry_backoff: 1000

      # Allowed hosts for security
      allowed_hosts:
        - api.example.com
        - webhook.service.com
        - ${ADDITIONAL_ALLOWED_HOSTS:-}

      # Default headers
      default_headers:
        User-Agent: Gleitzeit/0.0.7
        Accept: application/json

      # Connection pooling
      connection_pool:
        max_connections: 100
        max_connections_per_host: 10
        keepalive_timeout: 30

      # Circuit breaker per host
      circuit_breaker:
        enabled: true
        failure_threshold: 5
        success_threshold: 2
        reset_timeout: 30

  # File Handler Configuration
  file:
    execution:
      mode: native  # Files should generally be handled locally

    config:
      # Base directories for file operations
      base_directories:
        input: ${FILE_INPUT_DIR:-/data/input}
        output: ${FILE_OUTPUT_DIR:-/data/output}
        temp: ${FILE_TEMP_DIR:-/tmp/gleitzeit}

      # Security settings
      allowed_operations:
        - read
        - write
        - delete
        - copy
        - move

      # File size limits
      max_file_size_mb: 100
      max_total_size_mb: 1000

      # Cleanup settings
      cleanup:
        enabled: true
        temp_file_ttl: 3600
        orphan_file_ttl: 86400

  # Timer Handler Configuration
  timer:
    execution:
      mode: native  # Timers are lightweight, keep native

    config:
      # Timer precision
      precision_ms: 100

      # Maximum scheduled timers
      max_scheduled_timers: 10000

      # Timer storage backend
      backend: redis  # or: memory, database

      # Cleanup old timers
      cleanup_interval: 3600
      expired_timer_ttl: 86400

  # Signal Handler Configuration
  signal:
    execution:
      mode: native  # Signals are internal, keep native

    config:
      # Signal delivery
      delivery_mode: at_least_once  # or: at_most_once, exactly_once

      # Signal storage
      max_signals_per_workflow: 1000
      signal_ttl: 86400

      # Broadcast settings
      broadcast:
        enabled: true
        max_subscribers: 1000

  # Workflow Handler Configuration
  workflow:
    execution:
      mode: ${WORKFLOW_HANDLER_MODE:-native}

    config:
      # Child workflow limits
      max_child_workflows: 100
      max_recursion_depth: 10

      # Workflow submission
      async_submission: true
      submission_timeout: 10

      # Parent-child relationship tracking
      track_lineage: true
      lineage_ttl: 604800  # 7 days

  # Validation Handler Configuration
  validation:
    execution:
      mode: native  # Validation should be fast and local

    config:
      # Validation rules
      strict_mode: false
      allow_unknown_fields: true

      # Schema validation
      schema_validation:
        enabled: true
        cache_schemas: true
        schema_cache_ttl: 3600

      # Type coercion
      type_coercion:
        enabled: true
        coerce_numbers: true
        coerce_booleans: true

# Workers configuration with handler configs
workers:
  # Task execution worker with handler configurations
  - worker_type: task_execution
    worker_class: gleitzeit.workers.task_execution_worker.TaskExecutionWorker
    count: 2
    max_concurrent: 5
    batch_size: 10
    block_timeout: 5000

    # Handler configurations passed to workers
    handler_configs:
      # Python handler config
      "python/v1":
        subprocess_pool_enabled: true
        subprocess_pool_min_size: 2
        subprocess_pool_max_size: 10
        default_timeout: 300
        instance_url: ${HOSTNAME:-localhost}:${WORKER_PORT:-9000}

      # Ollama handler config
      "ollama/v1":
        base_url: ${OLLAMA_URL:-http://localhost:11434}
        timeout: 300
        default_model: llama2
        circuit_breaker:
          failure_threshold: 3
          reset_timeout: 60

      # HTTP handler config
      "http/v1":
        timeout: 30
        max_retries: 3
        allowed_hosts:
          - api.example.com
          - webhook.service.com

      # File handler config
      "file/v1":
        base_directories:
          input: /data/input
          output: /data/output
          temp: /tmp/gleitzeit
        max_file_size_mb: 100

      # Timer handler config
      "timer/v1":
        precision_ms: 100
        backend: redis

      # Signal handler config
      "signal/v1":
        delivery_mode: at_least_once
        max_signals_per_workflow: 1000

      # Workflow handler config
      "workflow/v1":
        max_child_workflows: 100
        async_submission: true

      # Validation handler config
      "validation/v1":
        strict_mode: false
        allow_unknown_fields: true

  # Specialized workers for specific handler types (optional)
  - worker_type: python_execution
    worker_class: gleitzeit.workers.task_execution_worker.TaskExecutionWorker
    count: 3
    enabled_task_types: [python, script]  # Only handle Python tasks
    handler_configs:
      "python/v1":
        subprocess_pool_enabled: true
        subprocess_pool_min_size: 5
        subprocess_pool_max_size: 20

  - worker_type: llm_execution
    worker_class: gleitzeit.workers.task_execution_worker.TaskExecutionWorker
    count: 1
    enabled_task_types: [ollama, llm]  # Only handle LLM tasks
    handler_configs:
      "ollama/v1":
        base_url: ${OLLAMA_URL:-http://ollama:11434}
        timeout: 600
        default_model: ${LLM_MODEL:-llama2}

# Handler-specific Docker services (for Docker mode)
handler_services:
  # Python handler service
  python_handler:
    enabled: ${ENABLE_PYTHON_SERVICE:-false}
    image: gleitzeit/python-handler:latest
    replicas: 3
    ports:
      - "9100-9102:8080"
    environment:
      HANDLER_MODE: service
      REDIS_URL: redis://redis:6379
    networks:
      - gleitzeit
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 3s
      retries: 3

  # Ollama service
  ollama:
    enabled: ${ENABLE_OLLAMA_SERVICE:-false}
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama-models:/root/.ollama
    networks:
      - gleitzeit
    environment:
      OLLAMA_KEEP_ALIVE: 5m
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

# Handler execution profiles (for different environments)
profiles:
  # Development profile - mostly native execution
  development:
    handlers:
      python:
        execution:
          mode: subprocess
      ollama:
        execution:
          mode: remote
      http:
        execution:
          mode: native
      file:
        execution:
          mode: native

  # Production profile - containerized execution
  production:
    handlers:
      python:
        execution:
          mode: container
          fallback_mode: remote
      ollama:
        execution:
          mode: remote
      http:
        execution:
          mode: container
      file:
        execution:
          mode: container
    handler_services:
      python_handler:
        enabled: true
        replicas: 10
      ollama:
        enabled: true

  # Testing profile - mixed modes for testing
  testing:
    handlers:
      python:
        execution:
          mode: subprocess
      ollama:
        execution:
          mode: remote
      http:
        execution:
          mode: native
      file:
        execution:
          mode: native

# Select active profile
active_profile: ${GLEITZEIT_PROFILE:-development}

# Monitoring for handlers
monitoring:
  handlers:
    # Metrics collection for handlers
    metrics:
      enabled: true
      export_interval: 60
      retention: 86400

    # Handler-specific health checks
    health_checks:
      enabled: true
      interval: 30
      timeout: 5

    # Performance tracking
    performance:
      track_execution_time: true
      track_memory_usage: true
      track_error_rates: true

    # Alerting thresholds
    alerts:
      error_rate_threshold: 0.1  # 10% error rate
      latency_p99_threshold: 5000  # 5 seconds
      memory_threshold_mb: 1000

# Security settings for handlers
security:
  handlers:
    # Sandbox settings for code execution
    sandbox:
      enabled: ${ENABLE_SANDBOX:-false}
      type: docker  # or: firejail, gvisor

    # Network policies
    network:
      restrict_external: false
      allowed_domains:
        - api.example.com
        - "*.amazonaws.com"

    # Resource quotas
    quotas:
      max_cpu_per_task: 1.0
      max_memory_per_task_mb: 512
      max_execution_time_seconds: 300
      max_concurrent_executions: 100

# Handler registry configuration
handler_registry:
  # Auto-discovery of handlers
  auto_discovery:
    enabled: true
    scan_packages:
      - gleitzeit.handlers
      - custom.handlers  # For user-defined handlers

  # Handler loading
  lazy_loading: true
  preload_handlers:
    - python/v1
    - timer/v1
    - signal/v1

  # Handler validation
  validate_on_load: true
  strict_validation: false
```

## Implementation Guide

### 1. Extending ConfigLoader

Update the ConfigLoader to handle handler configurations:

```python
# src/gleitzeit/core/config_loader.py

class ConfigLoader:
    def load_handler_config(self) -> Dict[str, Any]:
        """Load handler-specific configurations from gleitzeit.yaml"""
        handlers_config = self.get('handlers', {})

        # Apply active profile if specified
        active_profile = self.get('active_profile')
        if active_profile:
            profile = self.get(f'profiles.{active_profile}')
            if profile and 'handlers' in profile:
                handlers_config = self._deep_merge(handlers_config, profile['handlers'])

        return handlers_config

    def get_handler_config(self, protocol: str) -> Dict[str, Any]:
        """Get configuration for a specific handler protocol"""
        # Map protocol to handler name
        handler_name = protocol.split('/')[0]  # e.g., "python/v1" -> "python"

        # Get handler-specific config
        handler_config = self.get(f'handlers.{handler_name}.config', {})

        # Merge with global handler settings
        global_config = self.get('handlers.global', {})
        return self._deep_merge(global_config, handler_config)

    def get_handler_execution_mode(self, protocol: str) -> str:
        """Get execution mode for a handler"""
        handler_name = protocol.split('/')[0]
        return self.get(f'handlers.{handler_name}.execution.mode', 'native')
```

### 2. Updating Task Execution Worker

Modify the worker to use handler configurations from gleitzeit.yaml:

```python
# src/gleitzeit/workers/task_execution_worker.py

class TaskExecutionWorker(BaseWorker):
    def _init_handlers(self):
        """Initialize handlers with configurations from gleitzeit.yaml"""

        # Load handler configurations from gleitzeit.yaml
        from ..core.config_loader import get_config
        config = get_config()

        # Get handler configs from both sources
        # 1. Direct handler_configs in worker config (backward compatibility)
        worker_handler_configs = self.config.__dict__.get('handler_configs', {})

        # 2. Handler configurations from gleitzeit.yaml
        yaml_handler_configs = {}
        if 'handlers' in config:
            for protocol, handler_class in self.protocol_to_handler.items():
                handler_name = protocol.split('/')[0]
                if handler_name in config['handlers']:
                    yaml_handler_configs[protocol] = config['handlers'][handler_name].get('config', {})

        # Merge configurations (worker config takes precedence)
        merged_configs = {**yaml_handler_configs, **worker_handler_configs}

        # Initialize handlers with merged configurations
        for protocol, handler_class in self.protocol_to_handler.items():
            handler_config = merged_configs.get(protocol, {})

            # Add execution mode from config
            handler_name = protocol.split('/')[0]
            execution_mode = config.get(f'handlers.{handler_name}.execution.mode', 'native')
            handler_config['execution_mode'] = execution_mode

            # Create handler instance
            handler_instance = handler_class(config=handler_config)
            self.handlers[protocol] = handler_instance

            logger.info(
                f"Initialized {protocol} handler with mode: {execution_mode}, "
                f"config: {list(handler_config.keys())}"
            )
```

### 3. Handler Base Class Enhancement

Update BaseHandler to support execution modes:

```python
# src/gleitzeit/handlers/base.py

class BaseHandler(ABC):
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)

        # Get execution mode from config
        self.execution_mode = self.config.get('execution_mode', 'native')

        # Get container config if applicable
        self.container_config = self.config.get('container', {})

        # Get remote config if applicable
        self.remote_config = self.config.get('remote', {})

        logger.info(
            f"{self.__class__.__name__} initialized with execution mode: {self.execution_mode}"
        )
```

### 4. CLI Integration

Update the CLI to load handler configurations:

```python
# src/gleitzeit/cli/serve.py

def load_gleitzeit_config(config_path: str = None) -> Dict[str, Any]:
    """Load gleitzeit.yaml configuration including handlers"""

    if config_path is None:
        # Look for gleitzeit.yaml in standard locations
        search_paths = [
            Path.cwd() / "gleitzeit.yaml",
            Path.cwd() / "config" / "gleitzeit.yaml",
            Path.home() / ".gleitzeit" / "config.yaml",
        ]

        for path in search_paths:
            if path.exists():
                config_path = path
                break

    if config_path and Path(config_path).exists():
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Process environment variables
        config = process_env_vars(config)

        # Apply active profile if specified
        if 'active_profile' in config and 'profiles' in config:
            profile = config['profiles'].get(config['active_profile'])
            if profile:
                config = deep_merge(config, profile)

        return config

    return {}

def create_worker_configs(config: Dict[str, Any]) -> List[WorkerConfig]:
    """Create worker configurations with handler settings"""

    worker_configs = []

    for worker_def in config.get('workers', []):
        worker_config = WorkerConfig()

        # Set basic worker properties
        worker_config.worker_type = worker_def['worker_type']
        worker_config.worker_class = worker_def['worker_class']

        # Add handler configurations
        if 'handler_configs' in worker_def:
            worker_config.handler_configs = worker_def['handler_configs']
        elif 'handlers' in config:
            # Use global handler configurations
            worker_config.handler_configs = {}
            for handler_name, handler_config in config['handlers'].items():
                if handler_name != 'global':
                    protocol = f"{handler_name}/v1"  # Assuming v1 protocol
                    worker_config.handler_configs[protocol] = handler_config.get('config', {})

        worker_configs.append(worker_config)

    return worker_configs
```

## Usage Examples

### Example 1: Development Setup

```yaml
# gleitzeit.yaml for development
handlers:
  python:
    execution:
      mode: subprocess  # Use subprocess for isolation
    config:
      subprocess_pool_enabled: true
      subprocess_pool_min_size: 2
      subprocess_pool_max_size: 5

  ollama:
    execution:
      mode: remote
    config:
      base_url: http://localhost:11434
      default_model: codellama
```

### Example 2: Production Setup with Docker

```yaml
# gleitzeit.yaml for production
active_profile: production

profiles:
  production:
    handlers:
      python:
        execution:
          mode: container
          fallback_mode: remote
        container:
          enabled: true
          image: gleitzeit/python-handler:1.0.0
          replicas: 10

      ollama:
        execution:
          mode: remote
        config:
          base_url: http://ollama-service.internal:11434
          circuit_breaker:
            enabled: true
            failure_threshold: 3
```

### Example 3: Mixed Mode for Testing

```yaml
# gleitzeit.yaml for testing different execution modes
handlers:
  python:
    execution:
      mode: ${PYTHON_MODE:-subprocess}  # Override via environment

workers:
  # Native Python worker
  - worker_type: python_native
    enabled_task_types: [python]
    handler_configs:
      "python/v1":
        execution_mode: native

  # Container Python worker
  - worker_type: python_container
    enabled_task_types: [python_container]
    handler_configs:
      "python/v1":
        execution_mode: container
        container:
          image: gleitzeit/python-handler:test
```

## Benefits of YAML Configuration

1. **Centralized Configuration**: All handler settings in one place
2. **Environment-Specific Profiles**: Different configurations for dev/staging/prod
3. **Environment Variable Support**: Override settings without changing files
4. **Version Control Friendly**: Track configuration changes in git
5. **Validation**: Schema validation for configuration correctness
6. **Hot Reload**: Potential for configuration updates without restart

## Migration Path

### Phase 1: Add Handler Section to gleitzeit.yaml
- Add `handlers` section with basic configurations
- Maintain backward compatibility with existing worker configs

### Phase 2: Implement ConfigLoader Extensions
- Add handler configuration methods
- Support for profiles and environment variables

### Phase 3: Update Workers to Use YAML Config
- Modify task execution worker to read handler configs
- Add execution mode support

### Phase 4: Advanced Features
- Container orchestration from YAML
- Dynamic handler loading based on config
- Configuration validation and schema

## Conclusion

Extending `gleitzeit.yaml` to include handler configurations provides a unified, maintainable way to manage handler behavior across different environments. The proposed schema supports:

- Multiple execution modes (native, subprocess, container, remote)
- Environment-specific profiles
- Handler-specific settings (timeouts, pools, circuit breakers)
- Security and resource limits
- Monitoring and metrics configuration

This approach maintains backward compatibility while enabling advanced handler orchestration capabilities.