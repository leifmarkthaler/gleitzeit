# Fix Handler Configuration Flow in CLI

## Problem Statement

The current CLI implementation cannot pass handler configurations from `gleitzeit.yaml` to workers because:

1. **ComponentOrchestrator** starts workers as subprocesses with basic CLI arguments
2. **WorkerRunner** doesn't accept handler configurations via CLI
3. **Complex nested configurations** (like handler configs) can't be passed via command-line arguments

This means handler-specific settings in `gleitzeit.yaml` are ignored when workers start.

## Current Flow (Broken)

```
gleitzeit.yaml
    ↓
ComponentOrchestrator.load_worker_specs()  [Only loads worker specs, not handler configs]
    ↓
ComponentOrchestrator.start_worker()       [Passes basic args via CLI]
    ↓
WorkerRunner (subprocess)                  [Creates WorkerConfig without handler_configs]
    ↓
TaskExecutionWorker.__init__()            [Expects handler_configs but doesn't get them]
    ↓
Handlers initialized with default configs only ❌
```

## Proposed Solution

### Option 1: Pass Configuration via Redis (Recommended)

Store configuration in Redis and pass a reference key to workers:

```python
# src/gleitzeit/orchestrator/component_orchestrator.py

async def start_worker(self, worker_id: str, worker_type: str, ...):
    """Start a worker with full configuration"""

    # Load handler configs from gleitzeit.yaml
    handler_configs = self.config.get('handlers', {})
    worker_handler_configs = {}

    # Convert handler configs to protocol-based format
    for handler_name, handler_config in handler_configs.items():
        if handler_name != 'global':
            protocol = f"{handler_name}/v1"
            worker_handler_configs[protocol] = handler_config.get('config', {})

    # Also get worker-specific handler configs if defined
    worker_spec = self.worker_specs.get(worker_type)
    if hasattr(worker_spec, 'handler_configs'):
        worker_handler_configs.update(worker_spec.handler_configs)

    # Store configuration in Redis
    config_key = f"worker:config:{worker_id}"
    config_data = {
        'worker_type': worker_type,
        'worker_id': worker_id,
        'handler_configs': worker_handler_configs,
        'max_concurrent': max_concurrent,
        'batch_size': batch_size,
        'block_timeout': block_timeout,
        'assigned_shards': assigned_shards
    }

    await self.redis.set(
        config_key.encode(),
        json.dumps(config_data).encode(),
        ex=3600  # Expire after 1 hour
    )

    # Start worker with config key reference
    cmd = [
        "python", "-m", "gleitzeit.workers.runner",
        "--worker-class", worker_class,
        "--config-key", config_key,  # Pass Redis key instead of all args
        "--redis-url", self.redis_url
    ]

    process = await asyncio.create_subprocess_exec(*cmd, ...)
```

```python
# src/gleitzeit/workers/runner.py

async def run_worker(args):
    """Run a worker instance with configuration from Redis"""

    if args.config_key:
        # Load configuration from Redis
        redis = await aioredis.from_url(args.redis_url)
        config_data = await redis.get(args.config_key.encode())

        if config_data:
            config_dict = json.loads(config_data)

            # Create WorkerConfig with handler configs
            config = WorkerConfig(
                worker_type=config_dict['worker_type'],
                worker_id=config_dict['worker_id'],
                redis_url=args.redis_url,
                assigned_shards=config_dict.get('assigned_shards', []),
                max_concurrent=config_dict.get('max_concurrent', 10),
                batch_size=config_dict.get('batch_size', 10),
                block_timeout=config_dict.get('block_timeout', 5000)
            )

            # Add handler_configs as a custom attribute
            config.handler_configs = config_dict.get('handler_configs', {})

        await redis.aclose()
    else:
        # Fallback to CLI arguments (existing code)
        config = WorkerConfig(...)

    # Create and run worker
    worker_class = import_worker_class(args.worker_class)
    worker = worker_class(config)
    await worker.initialize()
    await worker.run()
```

### Option 2: Pass Configuration via File

Write configuration to a temporary file and pass the path:

```python
# src/gleitzeit/orchestrator/component_orchestrator.py

async def start_worker(self, worker_id: str, ...):
    """Start a worker with configuration file"""

    # Create worker configuration including handler configs
    worker_config = {
        'worker_type': worker_type,
        'worker_id': worker_id,
        'handler_configs': self._get_handler_configs_for_worker(worker_type),
        'max_concurrent': max_concurrent,
        # ... other settings
    }

    # Write to temporary file
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.json',
        prefix=f'worker_{worker_id}_',
        delete=False
    ) as f:
        json.dump(worker_config, f)
        config_file = f.name

    # Start worker with config file
    cmd = [
        "python", "-m", "gleitzeit.workers.runner",
        "--worker-class", worker_class,
        "--config-file", config_file,
        "--redis-url", self.redis_url
    ]
```

### Option 3: Extend WorkerConfig Class

Make WorkerConfig more flexible to accept additional attributes:

```python
# src/gleitzeit/workers/base.py

@dataclass
class WorkerConfig:
    """Configuration for a worker instance"""
    worker_type: str
    worker_id: str
    consumer_group: str
    redis_url: str = None
    assigned_shards: List[int] = None
    max_concurrent: int = 10
    batch_size: int = 10
    block_timeout: int = 5000
    heartbeat_interval: int = 30

    # Add support for handler configurations
    handler_configs: Dict[str, Dict[str, Any]] = None

    # Allow additional config attributes
    extra_config: Dict[str, Any] = None

    def __post_init__(self):
        """Initialize optional fields"""
        if self.handler_configs is None:
            self.handler_configs = {}
        if self.extra_config is None:
            self.extra_config = {}
        if self.assigned_shards is None:
            self.assigned_shards = []
```

## Implementation Plan

### Phase 1: Update WorkerConfig (Immediate)

```python
# src/gleitzeit/workers/base.py

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

@dataclass
class WorkerConfig:
    """Enhanced configuration for a worker instance"""
    # Core configuration
    worker_type: str
    worker_id: str
    consumer_group: str

    # Connection
    redis_url: Optional[str] = None

    # Sharding
    assigned_shards: List[int] = field(default_factory=list)

    # Performance
    max_concurrent: int = 10
    batch_size: int = 10
    block_timeout: int = 5000
    heartbeat_interval: int = 30

    # Handler configuration (NEW)
    handler_configs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    enabled_task_types: List[str] = field(default_factory=lambda: ['all'])

    # Extensibility (NEW)
    extra: Dict[str, Any] = field(default_factory=dict)

    def get_handler_config(self, protocol: str) -> Dict[str, Any]:
        """Get configuration for a specific handler protocol"""
        return self.handler_configs.get(protocol, {})

    def __getattr__(self, name):
        """Allow access to extra config as attributes"""
        if 'extra' in self.__dict__ and name in self.__dict__['extra']:
            return self.__dict__['extra'][name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
```

### Phase 2: Update ComponentOrchestrator

```python
# src/gleitzeit/orchestrator/component_orchestrator.py

class ComponentOrchestrator:

    def load_worker_specs(self):
        """Load worker specifications from config"""
        # Load from gleitzeit.yaml workers section
        worker_configs = self.config.get('workers', [])

        for worker_config in worker_configs:
            spec = WorkerSpec(
                worker_type=worker_config['worker_type'],
                worker_class=worker_config['worker_class'],
                count=worker_config.get('count', 1),
                max_concurrent=worker_config.get('max_concurrent', 10),
                batch_size=worker_config.get('batch_size', 10),
                block_timeout=worker_config.get('block_timeout', 5000),
                # Store handler configs with the spec
                handler_configs=worker_config.get('handler_configs', {}),
                enabled_task_types=worker_config.get('enabled_task_types', ['all'])
            )
            self.worker_specs[spec.worker_type] = spec

    async def start_worker(self, worker_id: str, worker_type: str, ...):
        """Start a worker with full configuration"""

        spec = self.worker_specs[worker_type]

        # Build complete configuration
        config_data = {
            'worker_type': worker_type,
            'worker_id': worker_id,
            'worker_class': spec.worker_class,
            'consumer_group': f"{worker_type}-group",
            'redis_url': self.redis_url,
            'assigned_shards': assigned_shards,
            'max_concurrent': spec.max_concurrent,
            'batch_size': spec.batch_size,
            'block_timeout': spec.block_timeout,
            'handler_configs': spec.handler_configs,
            'enabled_task_types': spec.enabled_task_types
        }

        # Store in Redis with TTL
        config_key = f"worker:config:{worker_id}:{uuid.uuid4().hex[:8]}"
        await self.redis.setex(
            config_key.encode(),
            3600,  # 1 hour TTL
            json.dumps(config_data).encode()
        )

        # Start worker with config reference
        cmd = [
            "python", "-m", "gleitzeit.workers.runner",
            "--config-key", config_key,
            "--redis-url", self.redis_url
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
```

### Phase 3: Update Worker Runner

```python
# src/gleitzeit/workers/runner.py

async def run_worker(args):
    """Run a worker instance"""

    redis = None
    try:
        # Connect to Redis
        redis = await aioredis.from_url(
            args.redis_url or 'redis://localhost:6379',
            decode_responses=False
        )

        if args.config_key:
            # Load configuration from Redis
            logger.info(f"Loading configuration from Redis key: {args.config_key}")
            config_data = await redis.get(args.config_key.encode())

            if not config_data:
                logger.error(f"Configuration not found in Redis: {args.config_key}")
                sys.exit(1)

            config_dict = json.loads(config_data)

            # Import worker class
            worker_class = import_worker_class(config_dict['worker_class'])

            # Create WorkerConfig with all settings
            config = WorkerConfig(
                worker_type=config_dict['worker_type'],
                worker_id=config_dict['worker_id'],
                consumer_group=config_dict.get('consumer_group', f"{config_dict['worker_type']}-group"),
                redis_url=config_dict.get('redis_url', args.redis_url),
                assigned_shards=config_dict.get('assigned_shards', []),
                max_concurrent=config_dict.get('max_concurrent', 10),
                batch_size=config_dict.get('batch_size', 10),
                block_timeout=config_dict.get('block_timeout', 5000),
                heartbeat_interval=config_dict.get('heartbeat_interval', 30),
                handler_configs=config_dict.get('handler_configs', {}),
                enabled_task_types=config_dict.get('enabled_task_types', ['all']),
                extra=config_dict.get('extra', {})
            )

            # Clean up config from Redis (optional)
            # await redis.delete(args.config_key.encode())

        else:
            # Fallback to CLI arguments (for backward compatibility)
            worker_class = import_worker_class(args.worker_class)
            config = WorkerConfig(
                worker_type=args.worker_type or worker_class.__name__,
                worker_id=args.worker_id,
                consumer_group=args.consumer_group or f"{args.worker_type}-group",
                redis_url=args.redis_url,
                assigned_shards=[int(s) for s in args.shards.split(',')] if args.shards else [],
                max_concurrent=args.max_concurrent,
                batch_size=args.batch_size,
                block_timeout=args.block_timeout,
                heartbeat_interval=args.heartbeat_interval
            )

        # Create and initialize worker
        worker = worker_class(config)
        await worker.initialize()

        logger.info(f"Worker {config.worker_id} started successfully")
        logger.info(f"Handler configs: {list(config.handler_configs.keys())}")

        # Run worker
        await worker.run()

    finally:
        if redis:
            await redis.aclose()

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Run a Gleitzeit worker')

    # Add config-key option for Redis-based configuration
    parser.add_argument(
        '--config-key',
        help='Redis key containing worker configuration'
    )

    # Keep existing arguments for backward compatibility
    parser.add_argument(
        '--worker-class',
        help='Python path to worker class (required if not using --config-key)'
    )

    # ... rest of existing arguments ...

    args = parser.parse_args()

    # Validate arguments
    if not args.config_key and not args.worker_class:
        parser.error("Either --config-key or --worker-class must be provided")

    asyncio.run(run_worker(args))
```

### Phase 4: Load Handler Configs from gleitzeit.yaml

```python
# src/gleitzeit/orchestrator/component_orchestrator.py

class ComponentOrchestrator:

    def __init__(self, redis_url: Optional[str] = None, config: Optional[Dict] = None):
        self.config = config or {}
        # ... existing init code ...

        # Load handler configurations
        self.handler_configs = self._load_handler_configs()

    def _load_handler_configs(self) -> Dict[str, Dict[str, Any]]:
        """Load handler configurations from gleitzeit.yaml"""
        handler_configs = {}

        # Load from handlers section
        handlers_section = self.config.get('handlers', {})
        for handler_name, handler_config in handlers_section.items():
            if handler_name == 'global':
                continue  # Skip global config

            protocol = f"{handler_name}/v1"
            handler_configs[protocol] = handler_config.get('config', {})

            # Add execution mode if specified
            if 'execution' in handler_config:
                handler_configs[protocol]['execution_mode'] = handler_config['execution']['mode']

        return handler_configs

    def load_worker_specs(self):
        """Load worker specifications with handler configs"""
        worker_configs = self.config.get('workers', [])

        for worker_config in worker_configs:
            # Merge global handler configs with worker-specific ones
            worker_handler_configs = self.handler_configs.copy()

            # Override with worker-specific handler configs if provided
            if 'handler_configs' in worker_config:
                worker_handler_configs.update(worker_config['handler_configs'])

            spec = WorkerSpec(
                worker_type=worker_config['worker_type'],
                worker_class=worker_config['worker_class'],
                count=worker_config.get('count', 1),
                handler_configs=worker_handler_configs,
                # ... other fields ...
            )

            self.worker_specs[spec.worker_type] = spec
```

## Testing the Fix

### Test Configuration (gleitzeit.yaml)

```yaml
handlers:
  python:
    execution:
      mode: subprocess
    config:
      subprocess_pool_enabled: true
      subprocess_pool_min_size: 2
      subprocess_pool_max_size: 10

  ollama:
    execution:
      mode: remote
    config:
      base_url: http://localhost:11434
      default_model: codellama

workers:
  - worker_type: task_execution
    worker_class: gleitzeit.workers.task_execution_worker.TaskExecutionWorker
    count: 2
    handler_configs:
      "python/v1":
        subprocess_pool_enabled: true
        subprocess_pool_max_size: 20  # Override global setting
```

### Validation Script

```python
#!/usr/bin/env python
"""Validate handler configuration flow"""

import asyncio
import redis.asyncio as aioredis
import json

async def check_handler_configs():
    """Check if handler configs are being passed correctly"""

    redis = await aioredis.from_url('redis://localhost:6379')

    # Check for worker config keys
    keys = await redis.keys(b'worker:config:*')
    print(f"Found {len(keys)} worker config keys")

    for key in keys:
        config_data = await redis.get(key)
        if config_data:
            config = json.loads(config_data)
            print(f"\nWorker: {config.get('worker_id')}")
            print(f"Handler configs: {config.get('handler_configs', {})}")

    await redis.aclose()

if __name__ == '__main__':
    asyncio.run(check_handler_configs())
```

## Benefits

1. **Complete Configuration Flow**: Handler settings from `gleitzeit.yaml` reach the handlers
2. **Backward Compatible**: Existing CLI arguments still work
3. **Flexible**: Supports complex nested configurations
4. **Scalable**: Works with any number of workers
5. **Secure**: Configs stored in Redis with TTL, not exposed in process list

## Migration Path

1. **Phase 1**: Update WorkerConfig to support handler_configs
2. **Phase 2**: Modify ComponentOrchestrator to store configs in Redis
3. **Phase 3**: Update WorkerRunner to load configs from Redis
4. **Phase 4**: Test with handler configurations in gleitzeit.yaml

This approach ensures that handler configurations defined in `gleitzeit.yaml` are properly passed to workers and their handlers, enabling full configuration management through the YAML file.