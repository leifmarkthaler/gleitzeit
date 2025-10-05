# Configuration Flow Fix Required for Native Mode

## Problem Summary

When running Gleitzeit in native mode (`gleitzeit serve --force-native`), handler configurations from `gleitzeit.yaml` are NOT loaded. This prevents features like container execution mode from working.

## Root Cause

Two parallel code paths exist:

### Path 1: Docker/Orchestrator Mode (✅ WORKS)
```
gleitzeit serve (without --force-native)
├── ComponentOrchestrator
│   ├── Loads gleitzeit.yaml
│   ├── Processes handler configs
│   ├── Stores in Redis with key
│   └── Starts workers with --config-key
└── Workers receive full configuration including handler_configs
```

### Path 2: Native Mode (❌ BROKEN)
```
gleitzeit serve --force-native
├── AsyncServiceManager
│   ├── Does NOT load handler configs
│   ├── Uses hardcoded CLI arguments
│   └── Starts workers WITHOUT --config-key
└── Workers get NO handler configurations
```

## The Evidence

In worker logs when running native mode:
```
2025-09-28 20:52:39,668 - gleitzeit.workers.task_execution_worker - INFO - No handler configurations found, using defaults
2025-09-28 20:52:39,670 - gleitzeit.handlers.python - INFO - Python handler using subprocess pool (min=2, max=10)
```

The Python handler ignores `execution_mode: container` because it never receives the configuration.

## Solution Approach

### Option 1: Quick Fix (Minimal Changes)
Modify `AsyncServiceManager` to load and pass handler configs:

```python
# src/gleitzeit/core/async_process_manager.py

class AsyncServiceManager:
    def __init__(self, config_file='gleitzeit.yaml'):
        # Load config
        with open(config_file) as f:
            self.config = yaml.safe_load(f)

        # Extract handler configs like ComponentOrchestrator does
        self.handler_configs = self._load_handler_configs()

    def _load_handler_configs(self):
        """Load handler configurations from gleitzeit.yaml"""
        handler_configs = {}
        handlers_section = self.config.get('handlers', {})

        for handler_name, handler_config in handlers_section.items():
            protocol = f"{handler_name}/v1"
            handler_configs[protocol] = handler_config.get('config', {})

            # Add execution mode
            if 'execution' in handler_config:
                handler_configs[protocol]['execution_mode'] = handler_config['execution']['mode']

                # Add container config if present
                if 'container' in handler_config['execution']:
                    handler_configs[protocol]['container'] = handler_config['execution']['container']

        return handler_configs

    async def start_worker(self, worker_config):
        # Build complete config with handler configs
        full_config = {
            **worker_config,
            'handler_configs': self.handler_configs
        }

        # Store in Redis
        config_key = f"worker:config:{worker_id}:{uuid.uuid4().hex[:8]}"
        await redis_client.set(config_key, json.dumps(full_config), ex=3600)

        # Use --config-key instead of individual args
        command = [
            self.python_path, "-m", "gleitzeit.workers.runner",
            "--config-key", config_key,
            "--redis-url", "redis://localhost:6379"
        ]
```

### Option 2: Unified Approach (Better Long-term)
Use ComponentOrchestrator for BOTH Docker and Native modes:

```python
# Always use ComponentOrchestrator for configuration
if force_native:
    orchestrator = ComponentOrchestrator(config, deploy_mode='native')
else:
    orchestrator = ComponentOrchestrator(config, deploy_mode='docker')

await orchestrator.start()
```

## Files to Modify

### For Quick Fix:
1. `/src/gleitzeit/core/async_process_manager.py`
   - Add handler config loading in `__init__`
   - Modify `start_worker` to use Redis config

2. `/src/gleitzeit/cli/serve_unified.py`
   - Pass config file path to AsyncServiceManager

### For Unified Approach:
1. `/src/gleitzeit/orchestrator/component_orchestrator.py`
   - Add native mode support
   - Use AsyncProcessManager instead of subprocess.Popen

2. `/src/gleitzeit/cli/serve_unified.py`
   - Always use ComponentOrchestrator

## Implementation Priority

1. **Immediate**: Document this limitation in README
2. **Short-term**: Implement Quick Fix to get container execution working
3. **Long-term**: Unify configuration flow for all deployment modes

## Testing

After fix, verify:
```bash
# Start in native mode
gleitzeit serve --force-native

# Check worker logs - should show:
# "Python handler using container execution with image: python:3.11-slim"

# Submit test workflow
gleitzeit submit test_container_execution.yaml

# Verify Docker container is spawned
docker ps  # Should show python:3.11-slim container
```

## Current Workaround

None available. Native mode cannot use handler configurations from gleitzeit.yaml.

## Impact

This blocks:
- Container execution mode for handlers
- Custom handler configurations per worker
- Mixed execution modes (native/container/remote)

## Conclusion

The configuration system works perfectly in ComponentOrchestrator but is completely bypassed in native mode. This is a critical gap that prevents handler-level Docker execution from working when Gleitzeit runs natively.