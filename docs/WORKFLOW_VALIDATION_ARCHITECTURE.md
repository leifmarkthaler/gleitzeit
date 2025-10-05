# Workflow Validation Architecture

## Overview

Gleitzeit's validation system ensures workflows are valid **before** submission by using the same transformation and validation logic that the actual workflow execution uses. This eliminates false positives where validation passes but execution fails.

## Key Principle

**Validation uses the actual WorkflowLoaderWorkerV2, not a separate validator.**

This ensures validation sees exactly what execution will see.

## Validation Flow

```
User submits workflow (YAML/JSON)
   ↓
UI → POST /api/workflows/validate
   ↓
API creates temporary WorkflowLoaderWorkerV2 instance
   ↓
WorkflowLoaderWorkerV2.transform_workflow()
   ├─ Maps simplified schema → protocol-based schema
   ├─ Resolves task types → protocols + methods
   └─ Transforms task parameters
   ↓
WorkflowLoaderWorkerV2.validate_workflow()
   ├─ Checks workflow structure
   ├─ Validates task IDs and dependencies
   └─ Validates protocols exist in handler registry
   ↓
Returns validation result to user
```

## Example Transformation

### User Input (Simplified Schema)
```yaml
name: Simple Python Task
tasks:
  - id: hello
    type: python
    code: |
      print("Hello from Gleitzeit!")
      return {"message": "Success"}
```

### After Transform (Protocol-Based Schema)
```yaml
name: Simple Python Task
tasks:
  - id: a1b2c3d4  # Generated UUID
    workflow_id: validation_xyz789
    protocol: python/v1
    method: python/execute
    params:
      code: |
        print("Hello from Gleitzeit!")
        return {"message": "Success"}
    dependencies: []
    timeout: 300
```

## Handler Registry Architecture

### Why In-Memory Registry?

Handler capabilities are **static code metadata**, not runtime state. They are:
- Defined in handler class code
- Same across all instances
- Never change during execution
- Accessed thousands of times per second

### How It Works

```python
# 1. Handler defines capabilities (static metadata)
@HandlerRegistry.register
class PythonHandler(BaseHandler):
    @classmethod
    def get_capabilities(cls):
        return {
            'protocol': 'python/v1',
            'methods': {
                'python/execute': {
                    'required': ['code'],
                    'optional': ['timeout']
                },
                'python/eval': {
                    'required': ['expression'],
                    'optional': []
                }
            },
            'task_types': ['python']  # For backward compatibility
        }

# 2. Auto-discovery imports all handlers
# When you import: from gleitzeit.handlers import handler_loader
# It automatically discovers and imports all .py files in handlers/
def _auto_import_handlers():
    for module in pkgutil.walk_packages(handlers_path):
        importlib.import_module(module)  # Triggers @register decorator

# 3. Decorator stores in class-level dict (in-memory)
class HandlerRegistry:
    _handlers: Dict[str, Type[BaseHandler]] = {}  # In-memory storage

    @classmethod
    def register(cls, handler_class):
        caps = handler_class.get_capabilities()
        cls._handlers[caps['protocol']] = handler_class
        return handler_class

# 4. Fast lookups (no Redis, no network)
handler = HandlerRegistry.get_handler('python/v1')  # Instant hash lookup
```

### Registry Lifecycle

```
Application Startup
   ↓
Import gleitzeit.handlers
   ↓
LazyHandlerLoader created
   ↓
[Handlers not loaded yet - lazy]
   ↓
First API call needs capabilities
   ↓
handler_loader.get_all_capabilities()
   ↓
_auto_import_handlers() discovers all .py files
   ↓
Each handler module imported
   ↓
@HandlerRegistry.register decorator runs
   ↓
Handler stored in HandlerRegistry._handlers dict
   ↓
Capabilities available for entire application lifetime
```

## What Goes Where

### In-Memory Registry (Static Code Metadata)
✅ Handler capabilities (protocols, methods, parameters)
✅ Task type → protocol mappings
✅ Method → handler mappings
✅ Required/optional parameter definitions

**Rationale**: These are defined in code, ship with the application, and never change at runtime.

### Redis (Runtime State)
✅ Workflow execution state (status, progress)
✅ Task execution state (status, results, errors)
✅ Workflow definitions (submitted workflows)
✅ Task queues (pending, ready, completed)
✅ Event streams (task:completed, workflow:submitted)

**Rationale**: These change during execution and need to be shared across distributed workers.

## Validation Implementation

### API Endpoint (`src/gleitzeit/api/routes/workflows.py`)

```python
@router.post("/validate")
async def validate_workflow(
    request: WorkflowValidateRequest,
    user: User = Depends(get_current_user_auto)
):
    """
    Validate workflow using WorkflowLoaderWorkerV2.
    Uses same transform + validate logic as actual submission.
    """
    from ...workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
    from ...workers.base import WorkerConfig
    import uuid

    # Create minimal worker config
    config = WorkerConfig(
        name="validation_worker",
        streams=[],
        redis_url="redis://localhost:6379",  # Not used - validation doesn't touch Redis
        batch_size=1
    )

    # Create worker instance (loads handler registry)
    worker = WorkflowLoaderWorkerV2(config)

    # Generate temporary ID for validation
    workflow_id = f"validation_{uuid.uuid4().hex[:12]}"

    # Transform: simplified → protocol-based
    transformed_workflow = await worker.transform_workflow(
        request.workflow,
        workflow_id
    )

    # Validate: check structure, protocols, dependencies
    validation_errors = worker.validate_workflow(transformed_workflow)

    if validation_errors:
        return {
            "valid": False,
            "errors": validation_errors
        }

    # Return summary
    return {
        "valid": True,
        "message": "Workflow validation passed",
        "summary": {
            'name': transformed_workflow.get('name'),
            'task_count': len(transformed_workflow.get('tasks', [])),
            'has_dependencies': any(t.get('dependencies') for t in transformed_workflow.get('tasks', []))
        }
    }
```

### Why This Approach Works

1. **No Code Duplication**: Validation uses the exact same code as submission
2. **No False Positives**: If validation passes, submission will succeed
3. **No Redis Dependency**: Validation is synchronous and uses in-memory registry
4. **Accurate Error Messages**: Users see the same errors they'd get on submission

## Performance Characteristics

### In-Memory Registry
- **Lookup time**: O(1) hash lookup (~100 nanoseconds)
- **Memory overhead**: ~10KB per handler class
- **Typical load time**: ~50ms for 10 handlers on first access
- **Subsequent access**: Instant (already loaded)

### Redis Lookup (for comparison)
- **Network roundtrip**: 0.5-2ms (local)
- **Serialization**: 0.1-0.5ms
- **Total**: ~1-3ms per lookup

For validation that happens on every workflow submission and every task execution, in-memory is 10,000x faster.

## Common Patterns

### Plugin Systems Using In-Memory Registries

- **Django**: `INSTALLED_APPS` registry
- **Flask**: Blueprint registry
- **Celery**: Task registry
- **SQLAlchemy**: Mapper registry
- **Python**: Entry points system

The pattern is universal: **Static code metadata lives in memory, runtime state lives in storage.**

## Deployment Considerations

### Single Instance
```
API Server (port 8000)
├── In-memory handler registry (python, http, timer, signal, ollama)
├── Validates workflows
└── Submits to Redis streams
```

### Multiple Instances
```
API Server 1                API Server 2
├── Handler registry       ├── Handler registry (same handlers)
├── Validates workflows    ├── Validates workflows
└── Submits to Redis      └── Submits to Redis

Worker 1                    Worker 2
├── Handler registry       ├── Handler registry (same handlers)
├── Executes tasks         ├── Executes tasks
└── Reads from Redis      └── Reads from Redis
```

Each instance has its own in-memory registry with the **same handlers** because they all run the **same code**.

## Troubleshooting

### "Handler not found for protocol 'xxx'"

**Cause**: Handler class wasn't imported/registered

**Solutions**:
1. Verify handler file exists in `src/gleitzeit/handlers/`
2. Check handler has `@HandlerRegistry.register` decorator
3. Ensure handler's `get_capabilities()` returns correct protocol
4. Check for import errors in handler module

### "Validation passes but submission fails"

**Before this architecture**: This was the problem - separate validators got out of sync

**After this architecture**: Should never happen - validation uses WorkflowLoaderWorkerV2

**If it happens**: File a bug - this violates the core design principle

### "Slow validation performance"

**Check**:
1. Handler registry lazy loads - first validation may be slow (~50ms)
2. Subsequent validations should be <1ms
3. If consistently slow, profile the transform/validate methods

## Future Enhancements

### Possible Improvements

1. **Deep Parameter Validation**: Currently validates structure and protocols, could validate parameter types/formats
2. **Dependency Cycle Detection**: Could detect circular dependencies during validation
3. **Resource Estimation**: Could estimate memory/CPU requirements before submission
4. **Capability Caching**: Could cache transformed workflows for repeated validations

### Planned: External Handler Plugin System

**Current State**: Handlers must be in `src/gleitzeit/handlers/` directory and shipped with Gleitzeit source.

**Planned**: Support for external/third-party handlers via two mechanisms:

#### 1. Python Entry Points (Production Plugins)

External packages can register handlers via entry points:

```toml
# External plugin: pyproject.toml
[project.entry-points."gleitzeit.handlers"]
slack = "gleitzeit_slack_handler:SlackHandler"
discord = "gleitzeit_discord_handler:DiscordHandler"
aws_lambda = "gleitzeit_aws_handler:LambdaHandler"
```

Installation:
```bash
pip install gleitzeit-slack-handler
# Handler auto-discovered on next startup
```

#### 2. Config-Based Loading (Local Development)

For development and custom deployments:

```yaml
# gleitzeit.yaml
handlers:
  external_paths:
    - /opt/company/gleitzeit/handlers    # Company-specific handlers
    - ./plugins/handlers                   # Local development
    - ~/my_handlers                        # User handlers
```

#### Implementation Plan

**Step 1**: Enhance `_auto_import_handlers()` (`src/gleitzeit/handlers/__init__.py`)

```python
def _auto_import_handlers():
    """Import handlers from multiple sources"""
    discovered = []

    # 1. Built-in handlers (existing)
    discovered.extend(_import_builtin_handlers())

    # 2. Entry point plugins (new)
    discovered.extend(_import_entry_point_handlers())

    # 3. Config paths (new)
    discovered.extend(_import_config_path_handlers())

    return discovered

def _import_entry_point_handlers():
    """Load handlers from installed packages"""
    import importlib.metadata

    discovered = []
    entry_points = importlib.metadata.entry_points()

    # Python 3.10+ API
    if hasattr(entry_points, 'select'):
        handlers = entry_points.select(group='gleitzeit.handlers')
    else:
        # Python 3.9 fallback
        handlers = entry_points.get('gleitzeit.handlers', [])

    for entry_point in handlers:
        try:
            handler_class = entry_point.load()
            # Registration happens via decorator
            discovered.append(entry_point.name)
            logger.info(f"Loaded plugin handler: {entry_point.name}")
        except Exception as e:
            logger.error(f"Failed to load {entry_point.name}: {e}")

    return discovered

def _import_config_path_handlers():
    """Load handlers from configured paths"""
    from ..core.config_manager import get_config

    config = get_config()
    external_paths = config.get('handlers', {}).get('external_paths', [])

    discovered = []
    for path in external_paths:
        try:
            # Add to sys.path
            sys.path.insert(0, str(Path(path).resolve()))

            # Import all .py files
            for module_file in Path(path).glob('*.py'):
                if module_file.stem.startswith('_'):
                    continue

                module_name = module_file.stem
                importlib.import_module(module_name)
                discovered.append(module_name)

        except Exception as e:
            logger.error(f"Failed to load handlers from {path}: {e}")

    return discovered
```

**Step 2**: Update `pyproject.toml` to declare entry point group

```toml
# No changes needed to core package
# External packages will declare:
# [project.entry-points."gleitzeit.handlers"]
```

**Step 3**: Handler Plugin Template

Create `docs/HANDLER_PLUGIN_TEMPLATE.md`:

```python
# my_custom_handler.py
from gleitzeit.handlers.base import BaseHandler
from gleitzeit.handlers.registry import HandlerRegistry
from gleitzeit.core.models import Task, TaskResult, TaskStatus

@HandlerRegistry.register
class CustomHandler(BaseHandler):
    """Custom handler for external service"""

    @classmethod
    def get_capabilities(cls):
        return {
            'protocol': 'custom/v1',
            'methods': {
                'custom/send': {
                    'required': ['message'],
                    'optional': ['priority']
                }
            },
            'task_types': ['custom']
        }

    async def execute(self, task: Task) -> TaskResult:
        # Implementation
        pass
```

Package as plugin:

```toml
# pyproject.toml
[project]
name = "gleitzeit-custom-handler"
version = "1.0.0"

[project.entry-points."gleitzeit.handlers"]
custom = "my_custom_handler:CustomHandler"
```

#### Benefits

1. **Ecosystem Growth**: Community can create and share handlers
2. **Enterprise Customization**: Companies can add proprietary integrations without forking
3. **Faster Development**: Test handlers without modifying core codebase
4. **Version Independence**: Plugin versions can evolve separately from Gleitzeit core

#### Security Considerations

1. **Validation**: Entry point handlers go through same `@HandlerRegistry.register` validation
2. **Sandboxing**: Config-path handlers run in same process (trust required)
3. **Code Review**: Production deployments should audit external handlers
4. **Signing** (future): Could require signed handlers for production use

#### Migration Path

**Existing Code**: No changes required - builtin handlers still work
**New Plugins**: Opt-in via entry points or config
**Mixed Mode**: Can use both builtin and external handlers simultaneously

### Non-Goals

❌ **Store capabilities in Redis**: Would add complexity and latency for no benefit
❌ **Separate validator class**: Would risk false positives from logic drift
❌ **Runtime capability changes**: Handlers are code - change code, redeploy
❌ **Dynamic handler loading**: No hot-reload - restart required for new handlers

## Related Documentation

- [Workflow Submission Flow](./WORKFLOW_SUBMISSION.md)
- [Handler Development Guide](./HANDLER_DEVELOPMENT.md)
- [Worker Architecture](./WORKER_ARCHITECTURE.md)
- [Redis Streams Design](./REDIS_STREAMS.md)
