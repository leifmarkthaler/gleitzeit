# Gleitzeit Replay Functionality - Complete User Guide

## 🎯 Overview

Gleitzeit's replay functionality enables you to:
- **Re-execute** workflows with automatic ID management
- **Continue** failed workflows from the last successful point
- **Debug** workflows with breakpoints and step-through execution
- **Template** workflows for reuse with modifications
- **Restore** workflow state at any point in time
- **Audit** workflow execution history

## 🚀 Quick Start (Works immediately after pip install!)

```python
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task

# No setup required - works out of the box!
async with GleitzeitClient() as client:
    # Create a workflow
    workflow = Workflow(
        id="my_workflow",
        name="Example Workflow",
        tasks=[
            Task(id="task1", name="First Task", protocol="python/v1", 
                 method="python/execute", params={"code": "print('Hello World')"})
        ]
    )
    
    # Submit original workflow
    await client.submit_workflow(workflow)
    
    # Replay it - that's it!
    result = await client.replay_workflow("my_workflow")
    print(f"Replayed as: {result['replay_id']}")
```

## 🔒 Security & Authentication

### Always-On Security
- **Basic user** automatically created for seamless pip install experience
- **Multi-user support** with ownership-based access control
- **Permission-based authorization** for all replay operations
- **Audit trails** with user metadata on all replayed workflows

### Configuration Options
```bash
# Default: Basic auth (always enabled)
GLEITZEIT_AUTH_MODE=basic

# Control ownership filtering  
GLEITZEIT_AUTH_OWNERSHIP_FILTER=true   # Default: enabled
GLEITZEIT_AUTH_OWNERSHIP_FILTER=false  # Disable for shared environments
```

### User Context
```python
# Automatic user context detection
result = await client.replay_workflow("workflow_id")

# Or provide explicit user context for multi-user scenarios
user_context = {
    "id": "user123",
    "email": "user@company.com", 
    "permissions": ["workflows:read", "workflows:replay"],
    "is_superuser": False
}

service = ReplayService(client)
result = await service.replay("workflow_id", user_context=user_context)
```

## 📚 Available Replay Methods

### 1. Re-execute Workflow
Create a complete copy and run it again.

```python
# Simple re-execution
result = await client.replay_workflow("workflow_id")
print(f"New workflow: {result['replay_id']}")

# With modifications
result = await client.replay_workflow(
    "workflow_id",
    mode="re_execute",
    modifications={
        "name": "Modified Workflow",
        "tasks": [
            {"id": "task1", "params": {"new_param": "value"}}
        ]
    }
)
```

### 2. Continue Failed Workflow
Resume from the last successful task.

```python
# Continue failed workflow
result = await client.continue_workflow("failed_workflow_id")
print(f"Continuing: {result['replay_id']}")
print(f"Skipping {len(result['tasks_to_skip'])} completed tasks")
print(f"Running {len(result['tasks_to_run'])} remaining tasks")
```

### 3. Debug Workflow
Step-through execution with breakpoints.

```python
# Debug with breakpoints
result = await client.debug_workflow(
    "workflow_id",
    breakpoints=["task2", "task5", "final_task"]
)
print(f"Debug session: {result['replay_id']}")
print(f"Breakpoints set: {result['breakpoints']}")
```

### 4. Use as Template
Create variations of existing workflows.

```python
# Use workflow as template
result = await client.use_workflow_as_template(
    "daily_etl_workflow",
    modifications={
        "name": "Weekly ETL",
        "description": "Weekly batch processing",
        "tasks": [
            {"id": "fetch_data", "params": {"frequency": "weekly"}},
            {"id": "process", "params": {"batch_size": 5000}}
        ]
    }
)
```

### 5. Restore State
View workflow state at any point in time.

```python
from datetime import datetime

# Restore latest state
state = await client.restore_workflow_state("workflow_id")
print(f"Task states: {len(state['task_states'])}")
print(f"Task results: {len(state['task_results'])}")

# Restore state at specific time
historical_state = await client.restore_workflow_state(
    "workflow_id",
    target_time=datetime(2025, 8, 29, 10, 30)
)
```

### 6. List & Discover
Find workflows available for replay.

```python
# List all replayable workflows
workflows = await client.list_replayable_workflows()
for wf in workflows:
    print(f"{wf['id']}: {wf['name']} - {wf['task_count']} tasks")
    print(f"  Status: {wf['status']}")
    print(f"  Modes: {', '.join(wf['replay_modes'])}")

# Filter by status
failed_workflows = await client.list_replayable_workflows(status="failed")

# Filter by time
from datetime import datetime, timedelta
recent = await client.list_replayable_workflows(
    since=datetime.now() - timedelta(days=7)
)
```

### 7. Replay History
Track all replays of a workflow.

```python
# Get replay history
history = await client.get_replay_history("original_workflow_id")
for replay in history:
    print(f"{replay['replay_id']}: {replay['replay_type']}")
    print(f"  Status: {replay['status']}")
    print(f"  Created: {replay['created_at']}")
```

## 🛠 Advanced Usage

### Workflow Modifications
```python
# Complex modifications
modifications = {
    "name": "Production ETL v2.1",
    "description": "Updated production pipeline",
    "metadata": {"version": "2.1", "environment": "prod"},
    "tasks": [
        {
            "id": "extract_data",
            "params": {
                "source": "prod_db",
                "query": "SELECT * FROM updated_table", 
                "timeout": 300
            }
        },
        {
            "id": "transform", 
            "params": {"transformations": ["normalize", "validate", "enrich"]}
        }
    ]
}

result = await client.use_workflow_as_template("etl_v2", modifications=modifications)
```

### Error Handling
```python
try:
    result = await client.replay_workflow("workflow_id")
except PermissionError as e:
    print(f"Access denied: {e}")
except ValueError as e:
    print(f"Invalid workflow: {e}")
except Exception as e:
    print(f"Replay failed: {e}")
```

### Batch Operations
```python
# Replay multiple workflows
workflow_ids = ["wf1", "wf2", "wf3"]
results = []

for wf_id in workflow_ids:
    try:
        result = await client.replay_workflow(wf_id)
        results.append(result)
        print(f"✓ Replayed {wf_id} → {result['replay_id']}")
    except Exception as e:
        print(f"✗ Failed to replay {wf_id}: {e}")
```

## 🔍 Monitoring & Observability

### Audit Information
Every replayed workflow includes audit metadata:

```python
result = await client.replay_workflow("workflow_id")
workflow = result['workflow']

print(f"Owner: {workflow.metadata['owner_id']}")
print(f"Replayed by: {workflow.metadata['replayed_by']}")  
print(f"Replayed at: {workflow.metadata['replayed_at']}")
```

### Logging
```python
import logging

# Enable replay logging
logging.getLogger('gleitzeit.replay').setLevel(logging.INFO)

# Logs include:
# - Access control decisions
# - Replay operation details  
# - Error diagnostics
```

## 🏗 Architecture

### Core Components
- **ReplayManager**: Core replay logic and security
- **ReplayService**: High-level client integration
- **ReplayMixin**: User-friendly client methods
- **Authentication**: Always-on security with basic user fallback

### Security Model
```python
# Access control flow:
# 1. User context resolution (auto or explicit)
# 2. Workflow ownership verification  
# 3. Permission checking
# 4. Operation execution
# 5. Audit trail creation
```

### Replay Modes
- `re_execute`: Complete re-run with new IDs
- `continue`: Resume from failure point
- `debug`: Step-through with breakpoints  
- `template`: Use as basis for new workflow
- `restore`: Read-only state inspection

## 🚨 Best Practices

### Security
```python
# ✅ Good: Let the system handle user context
result = await client.replay_workflow("workflow_id")

# ✅ Good: Explicit context for multi-user scenarios  
result = await service.replay("workflow_id", user_context=user_context)

# ❌ Avoid: Hardcoding user contexts in production
```

### Performance
```python
# ✅ Good: Use specific filters
workflows = await client.list_replayable_workflows(
    status="failed", 
    limit=50
)

# ❌ Avoid: Loading all workflows unnecessarily
all_workflows = await client.list_replayable_workflows(limit=10000)
```

### Error Recovery
```python
# ✅ Good: Structured error handling
try:
    result = await client.continue_workflow("failed_wf")
    await monitor_replay_progress(result['replay_id'])
except PermissionError:
    # Handle access control
    pass
except ValueError:
    # Handle invalid workflow
    pass
```

## 🔧 Configuration

### Environment Variables
```bash
# Authentication mode (always basic or admin)
GLEITZEIT_AUTH_MODE=basic|admin

# Ownership filtering
GLEITZEIT_AUTH_OWNERSHIP_FILTER=true|false

# Client mode selection
GLEITZEIT_CLIENT_MODE=auto|api|native
```

### Client Configuration
```python
# Native mode for full features
client = GleitzeitClient(mode=ClientMode.NATIVE)

# API mode for scalability  
client = GleitzeitClient(mode=ClientMode.API, api_host="replay.company.com")

# Auto mode for best experience
client = GleitzeitClient(mode=ClientMode.AUTO)  # Default
```

## 📊 Use Cases

### 🚀 Development & Testing
```python
# Test workflow changes
result = await client.use_workflow_as_template(
    "prod_workflow",
    modifications={"name": "Test Version", "metadata": {"env": "test"}}
)
```

### 🛠 Debugging Production Issues
```python
# Debug failed production workflow
result = await client.debug_workflow(
    "prod_failure_123",
    breakpoints=["data_validation", "external_api_call"]
)
```

### 🔄 Disaster Recovery
```python
# Continue from last checkpoint after system recovery
result = await client.continue_workflow("interrupted_workflow")
```

### 📋 Compliance & Auditing
```python
# Restore state for audit
audit_state = await client.restore_workflow_state(
    "compliance_workflow",
    target_time=audit_date
)
```

### 🏭 Production Scaling
```python
# Create variations for different environments
for env in ["staging", "prod", "dr"]:
    result = await client.use_workflow_as_template(
        "base_workflow",
        modifications={
            "name": f"Workflow - {env.upper()}",
            "metadata": {"environment": env},
            "tasks": [{"id": "deploy", "params": {"target": env}}]
        }
    )
```

## ✅ Implementation Status

- ✅ **Core ReplayManager**: Complete with all 5 replay modes
- ✅ **Authentication & Security**: Enterprise-grade with basic user fallback
- ✅ **Client Integration**: ReplayMixin with user-friendly methods  
- ✅ **Field Compatibility**: Defensive programming for varying Task models
- ✅ **Comprehensive Testing**: Functionality and security tests
- 🚧 **API Endpoints**: In development
- 🚧 **CLI Commands**: In development

## 🆘 Support

For issues or questions:
- Check logs: `logging.getLogger('gleitzeit.replay').setLevel(logging.DEBUG)`
- Verify permissions: `await client.get_current_user()` (if available)
- Test basic functionality: `await client.list_replayable_workflows()`

The replay system is production-ready with comprehensive security and seamless user experience!