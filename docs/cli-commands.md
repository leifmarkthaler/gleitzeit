# Gleitzeit CLI Commands Reference

## Overview

The Gleitzeit CLI provides comprehensive access to all system functionality through command-line interface. Most commands interact with the API server, which must be running unless using local execution mode.

## Installation Requirements

```bash
# Core dependencies (included in standard install)
pip install click httpx tabulate pyyaml

# Optional dependencies for full functionality
pip install redis  # For Redis persistence
```

## Global Options

All commands support these global options:
- `--host HOST` - API server host (default: localhost)
- `--port PORT` - API server port (default: 8000)
- `--verbose / -v` - Enable verbose output

## Core Commands

### Server Management

#### Start API Server
```bash
gleitzeit serve [OPTIONS]

Options:
  -h, --host TEXT      Host to bind [default: 0.0.0.0]
  -p, --port INT       Port to bind [default: 8000]
  --reload            Enable auto-reload for development
  -w, --workers INT   Number of worker processes [default: 1]
  --headless          Run without Web UI
  --ui-port INT       Port for Web UI [default: 8004]
```

#### Start Web UI
```bash
gleitzeit ui [OPTIONS]

Options:
  --port INT          UI server port [default: 8004]
  --host TEXT         UI server host [default: 127.0.0.1]
  --browser          Open browser automatically
```

### Workflow Execution

#### Run Workflow
```bash
gleitzeit run WORKFLOW_FILE [OPTIONS]

Options:
  -w, --watch         Watch execution progress
  --host TEXT         API server host [default: localhost]
  --port INT          API server port [default: 8000]
  --local            Run locally without API server
  --no-auto-start    Don't auto-start API if not running
```

Example:
```bash
# Run via API (recommended)
gleitzeit run workflow.yaml --watch

# Run locally without API
gleitzeit run workflow.yaml --local
```

## Task Management Commands

### List Tasks
```bash
gleitzeit task list [OPTIONS]

Options:
  --status [PENDING|EXECUTING|COMPLETED|FAILED|CANCELLED]
  --workflow-id TEXT   Filter by workflow ID
  --limit INT         Maximum tasks to return [default: 50]
```

### Get Task Details
```bash
gleitzeit task get TASK_ID
```

### Cancel Task
```bash
gleitzeit task cancel TASK_ID
```

### Retry Failed Task
```bash
gleitzeit task retry TASK_ID
```

### View Task Logs
```bash
gleitzeit task logs TASK_ID [OPTIONS]

Options:
  --tail INT          Number of lines [default: 50]
  --level [DEBUG|INFO|WARNING|ERROR]
```

### Get Task Result
```bash
gleitzeit task result TASK_ID [OPTIONS]

Options:
  -o, --output FILE   Save result to file
```

Examples:
```bash
# List all failed tasks
gleitzeit task list --status FAILED

# View last 100 lines of task logs
gleitzeit task logs abc-123-def --tail 100

# Save task result to file
gleitzeit task result abc-123-def -o result.json
```

## Workflow Management Commands

### List Workflows
```bash
gleitzeit workflow list [OPTIONS]

Options:
  --status [PENDING|RUNNING|COMPLETED|FAILED|CANCELLED]
  --limit INT         Maximum workflows [default: 50]
```

### Get Workflow Details
```bash
gleitzeit workflow get WORKFLOW_ID
```

### Workflow Control
```bash
# Pause running workflow
gleitzeit workflow pause WORKFLOW_ID

# Resume paused workflow
gleitzeit workflow resume WORKFLOW_ID

# Retry failed tasks in workflow
gleitzeit workflow retry WORKFLOW_ID

# Delete workflow
gleitzeit workflow delete WORKFLOW_ID [--force]
```

### Export Workflow
```bash
gleitzeit workflow export WORKFLOW_ID [OPTIONS]

Options:
  -o, --output FILE   Output file
  --format [json|yaml]  Export format [default: yaml]
```

Examples:
```bash
# List running workflows
gleitzeit workflow list --status RUNNING

# Export workflow as YAML
gleitzeit workflow export wf-123 -o exported.yaml

# Force delete workflow
gleitzeit workflow delete wf-123 --force
```

## Queue Management Commands

### List Queues
```bash
gleitzeit queue list
```

### Queue Status
```bash
gleitzeit queue status QUEUE_NAME
```

### Queue Control
```bash
# Pause queue processing
gleitzeit queue pause QUEUE_NAME

# Resume queue processing
gleitzeit queue resume QUEUE_NAME

# Clear all tasks from queue
gleitzeit queue clear QUEUE_NAME [--force]
```

Examples:
```bash
# View default queue status
gleitzeit queue status default

# Clear queue with confirmation
gleitzeit queue clear high_priority
```

## Log Management Commands

### Query Logs
```bash
gleitzeit logs query [OPTIONS]

Options:
  --level [DEBUG|INFO|WARNING|ERROR]
  --source [TASK|WORKFLOW|SYSTEM|API]
  --task-id TEXT
  --workflow-id TEXT
  --since TIMESTAMP
  --limit INT         [default: 100]
```

### Search Logs
```bash
gleitzeit logs search QUERY [OPTIONS]

Options:
  --task-id TEXT
  --workflow-id TEXT
  --limit INT         [default: 50]
```

### Log Statistics
```bash
gleitzeit logs stats [OPTIONS]

Options:
  --since TIMESTAMP
  --until TIMESTAMP
```

### Cleanup Logs
```bash
gleitzeit logs cleanup [OPTIONS]

Options:
  --days INT          Delete logs older than N days [default: 30]
  --level TEXT        Only delete this level and lower
  --force            Skip confirmation
```

### Tail Logs
```bash
gleitzeit logs tail TASK_ID [OPTIONS]

Options:
  --lines INT         Number of lines [default: 50]
  -f, --follow       Follow output (not yet implemented)
```

Examples:
```bash
# Query ERROR logs from last hour
gleitzeit logs query --level ERROR --since "2024-01-15T09:00:00"

# Search for timeout errors
gleitzeit logs search "timeout" --limit 20

# Cleanup DEBUG logs older than 7 days
gleitzeit logs cleanup --days 7 --level DEBUG --force
```

## System Management Commands

### System Statistics
```bash
gleitzeit system stats
```

### System Health Check
```bash
gleitzeit system health
```

### System Cleanup
```bash
gleitzeit system cleanup [OPTIONS]

Options:
  --days INT          Delete data older than N days [default: 30]
  --force            Skip confirmation
```

Examples:
```bash
# Check system health
gleitzeit system health

# View system statistics
gleitzeit system stats

# Cleanup old data
gleitzeit system cleanup --days 90 --force
```

## Provider Management Commands

### List Providers
```bash
gleitzeit provider list
```

### Check Provider Health
```bash
gleitzeit provider health PROVIDER_ID
```

Examples:
```bash
# List all providers
gleitzeit provider list

# Check Ollama provider health
gleitzeit provider health ollama_provider
```

## Event Error Commands

### List Event Errors
```bash
gleitzeit errors list [OPTIONS]

Options:
  --event-type TEXT   Filter by event type
  --handler TEXT      Filter by handler name
  --limit INT         Maximum errors [default: 100]
```

### Error Statistics
```bash
gleitzeit errors stats
```

Examples:
```bash
# List recent errors
gleitzeit errors list --limit 50

# View error statistics
gleitzeit errors stats
```

## Authentication Commands

### Login/Logout
```bash
# Interactive login
gleitzeit auth login

# Login with credentials
gleitzeit auth login --email user@example.com

# Logout
gleitzeit auth logout
```

### User Registration
```bash
gleitzeit auth register
```

### API Key Management
```bash
# Create new API key
gleitzeit auth api-key create --name "CI/CD Key"

# List API keys
gleitzeit auth api-key list

# Revoke API key
gleitzeit auth api-key revoke --key-id abc-123
```

### Audit Logs
```bash
gleitzeit auth audit-logs [OPTIONS]

Options:
  --user-id TEXT      Filter by user
  --action TEXT       Filter by action
  --limit INT         Maximum logs [default: 50]
```

### Authentication Setup (Admin)
```bash
# Initial setup
gleitzeit auth setup

# Migrate existing data
gleitzeit auth migrate --admin-email admin@example.com

# Check auth status
gleitzeit auth status
```

## Utility Commands

### Show Status
```bash
gleitzeit status [OPTIONS]

Options:
  --backend [sqlite|redis]   Persistence backend
  --resources               Show resource manager status
```

### Initialize New Workflow
```bash
gleitzeit init NAME [OPTIONS]

Options:
  --type [python|llm|mixed]   Workflow type [default: python]
```

### Scan Directory (Batch Processing)
```bash
gleitzeit scan DIRECTORY [OPTIONS]

Options:
  --pattern TEXT      File pattern [default: *]
  --prompt TEXT       Prompt for each file
  --model TEXT        Model to use
  --vision           Use vision model for images
```

### Show Configuration
```bash
gleitzeit config
```

## Common Workflows

### Development Workflow
```bash
# 1. Start API server with auto-reload
gleitzeit serve --reload

# 2. In another terminal, run workflows
gleitzeit run my_workflow.yaml --watch

# 3. Monitor tasks
gleitzeit task list --status EXECUTING

# 4. Check logs if something fails
gleitzeit task logs <task-id>
```

### Production Deployment
```bash
# 1. Start API server with multiple workers
gleitzeit serve --workers 4 --headless

# 2. Setup authentication
gleitzeit auth setup

# 3. Create API key for automation
gleitzeit auth login
gleitzeit auth api-key create --name "Production"

# 4. Monitor system health
gleitzeit system health
gleitzeit system stats
```

### Debugging Failed Tasks
```bash
# 1. List failed tasks
gleitzeit task list --status FAILED

# 2. Get error details
gleitzeit task get <task-id>

# 3. View logs
gleitzeit task logs <task-id> --tail 200

# 4. Search for errors
gleitzeit logs search "error" --task-id <task-id>

# 5. Retry task
gleitzeit task retry <task-id>
```

### Maintenance Operations
```bash
# 1. Check system statistics
gleitzeit system stats

# 2. View log statistics
gleitzeit logs stats

# 3. Cleanup old data
gleitzeit system cleanup --days 30
gleitzeit logs cleanup --days 7 --level DEBUG

# 4. Check event errors
gleitzeit errors stats
```

## Environment Variables

The CLI respects these environment variables:

```bash
# API Connection
GLEITZEIT_API_HOST=localhost
GLEITZEIT_API_PORT=8000

# Persistence
GLEITZEIT_PERSISTENCE_TYPE=redis
GLEITZEIT_REDIS_URL=redis://localhost:6379/0

# Authentication
GLEITZEIT_AUTH_ENABLED=true
GLEITZEIT_JWT_SECRET=your-secret-key

# Logging
GLEITZEIT_LOG_LEVEL=INFO
GLEITZEIT_LOG_RETENTION_DAYS=30
```

## Configuration File

Default location: `~/.gleitzeit/config.yaml`

```yaml
server:
  api:
    host: 0.0.0.0
    port: 8000
  ui:
    host: 127.0.0.1
    port: 8004

persistence:
  backend: redis
  redis:
    host: localhost
    port: 6379

auth:
  enabled: true
  jwt_secret: your-secret-key
```

## Troubleshooting

### API Connection Issues
```bash
# Check if server is running
gleitzeit system health

# Try different port
gleitzeit task list --port 8001
```

### Authentication Issues
```bash
# Check auth status
gleitzeit auth status

# Re-login
gleitzeit auth logout
gleitzeit auth login
```

### Missing Commands
```bash
# Install required dependencies
pip install httpx tabulate

# Check version
gleitzeit --version
```

## Exit Codes

- `0` - Success
- `1` - General error
- `2` - Command line usage error
- `130` - Interrupted (Ctrl+C)

## Getting Help

```bash
# General help
gleitzeit --help

# Command-specific help
gleitzeit task --help
gleitzeit task list --help
```

## See Also

- [API Documentation](api-endpoints.md)
- [Configuration Guide](CONFIGURATION.md)
- [Python Client](pythonclient.md)