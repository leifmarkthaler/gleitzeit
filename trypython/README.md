# Gleitzeit Python Client Examples

This directory contains examples of how to use the Gleitzeit Python client to submit and monitor workflows.

## Files

- `run_workflow.py` - Main script using the GleitzeitClient
- `run_workflow_simple.py` - Simplified script using direct HTTP calls
- `tasks.py` - Python functions that workflows can execute
- `example_workflow.yaml` - Example workflow with Python tasks
- `simple_shell.yaml` - Example workflow with shell commands
- `simple_test.py` - Test script for debugging

## Usage

### Using the GleitzeitClient:
```bash
python run_workflow.py example_workflow.yaml
python run_workflow.py example_workflow.yaml --stream
```

### Using direct HTTP API:
```bash
python run_workflow_simple.py example_workflow.yaml
```

## Requirements

The Gleitzeit server must be running:
```bash
gleitzeit serve
```

## Workflow Format

Workflows must use the correct protocol and method format:

```yaml
name: workflow_name
description: Workflow description
tasks:
  - name: task_name
    protocol: python/v1      # Protocol with version
    method: python/execute   # Full method name
    params:
      file: path/to/file.py
      function: function_name
    dependencies: [other_task]  # Optional task dependencies
```

## Known Issues

1. **Protocol Registry Error**: The server currently has an issue with the protocol registry that prevents workflow execution. The error "argument of type 'ProtocolRegistry' is not iterable" indicates a server-side validation problem.

2. **Task Execution**: Even when workflows are accepted, tasks remain in "pending" status and don't execute, suggesting the task queue or executor may not be running properly.

## API Endpoints

The Gleitzeit API provides these endpoints:

- `POST /workflows/` - Submit a new workflow
- `GET /workflows/` - List workflows
- `GET /workflows/{id}` - Get workflow details
- `GET /health` - Check server health