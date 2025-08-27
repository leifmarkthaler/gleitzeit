# CLI-API Misalignment Report

## Executive Summary
Significant misalignment exists between the REST API endpoints and CLI commands. The API has ~70+ endpoints while the CLI only exposes 10 commands, missing many operational and management capabilities.

## Current CLI Commands

### Main CLI Commands (gleitzeit_cli.py)
1. `run` - Execute workflow (can use API or local)
2. `status` - Show system status
3. `init` - Create workflow template
4. `config` - Show configuration
5. `scan` - Batch process files
6. `serve` - Start API server
7. `ui` - Start Web UI

### Auth Commands (auth/setup.py)
1. `auth setup` - Interactive auth setup
2. `auth migrate` - Migrate data with ownership
3. `auth status` - Check auth status

Total: **10 CLI commands**

## API Endpoints Summary

### Core Endpoints (70+ total)
- **System**: `/`, `/status`, `/health`, `/resources`
- **Workflows**: 15 endpoints (CRUD, control, bulk ops, export/clone)
- **Tasks**: 12 endpoints (CRUD, control, bulk ops, logs)
- **Queues**: 6 endpoints (list, control, config)
- **Statistics**: 2 endpoints (tasks, system)
- **Providers**: 4 endpoints (list, health check)
- **Logs**: 7 endpoints (query, search, stats, cleanup)
- **Event Errors**: 5 endpoints (list, stats, cleanup)
- **Auth**: 11 endpoints (login, register, API keys, audit)
- **WebSocket**: 3 endpoints (log streaming)

## Major Misalignments

### 1. Missing CLI Commands for Core Operations

#### Task Management ❌
**API Endpoints Available:**
- `POST /tasks` - Create task
- `GET /tasks` - List tasks
- `GET /tasks/{id}` - Get task details
- `DELETE /tasks/{id}` - Delete task
- `POST /tasks/{id}/cancel` - Cancel task
- `POST /tasks/{id}/retry` - Retry task
- `GET /tasks/{id}/result` - Get result
- `GET /tasks/{id}/logs` - Get logs

**CLI Commands:** NONE

#### Workflow Management ⚠️
**API Endpoints:**
- `POST /workflows` - Create workflow
- `GET /workflows` - List workflows
- `GET /workflows/{id}` - Get workflow
- `DELETE /workflows/{id}` - Delete workflow
- `POST /workflows/{id}/pause` - Pause workflow
- `POST /workflows/{id}/resume` - Resume workflow
- `POST /workflows/{id}/retry` - Retry workflow
- `GET /workflows/{id}/export` - Export workflow
- `POST /workflows/{id}/clone` - Clone workflow

**CLI Commands:** Only `run` (creates and executes)

#### Queue Management ❌
**API Endpoints:**
- `GET /queues` - List queues
- `GET /queues/{name}` - Queue details
- `POST /queues/{name}/pause` - Pause queue
- `POST /queues/{name}/resume` - Resume queue
- `POST /queues/{name}/clear` - Clear queue
- `PUT /queues/{name}/config` - Configure queue

**CLI Commands:** NONE

#### Log Management ❌
**API Endpoints:**
- `GET /logs` - Query logs
- `GET /logs/search` - Search logs
- `GET /logs/stats` - Log statistics
- `DELETE /logs/cleanup` - Clean up logs
- `GET /logs/retention` - Get retention
- `PUT /logs/retention` - Set retention

**CLI Commands:** NONE

#### Event Error Management ❌
**API Endpoints:**
- `GET /event-errors` - List errors
- `GET /event-errors/stats` - Error stats
- `GET /event-errors/{id}` - Get error
- `DELETE /event-errors/cleanup` - Cleanup

**CLI Commands:** NONE

#### Provider Management ❌
**API Endpoints:**
- `GET /providers` - List providers
- `GET /providers/{id}` - Provider details
- `POST /providers/{id}/health` - Health check

**CLI Commands:** NONE (only indirect via `scan`)

### 2. CLI Commands Without Direct API Equivalents

#### `init` Command ⚠️
- Creates workflow templates locally
- No API endpoint for template generation
- Could use API for validation

#### `scan` Command ⚠️
- Batch processes files locally
- Uses `/batch` endpoint indirectly
- Could be better integrated

#### `config` Command ✅
- Shows local config
- Could integrate with API `/status`

### 3. Authentication Misalignment

**API Auth Endpoints:**
- Full REST auth with JWT tokens
- API key management
- Audit logging
- User/role management

**CLI Auth:**
- Only setup and migration
- No user management
- No API key management via CLI
- No audit log viewing

## Recommended CLI Additions

### Priority 1: Task Management
```bash
gleitzeit task list [--status STATUS]
gleitzeit task get TASK_ID
gleitzeit task cancel TASK_ID
gleitzeit task retry TASK_ID
gleitzeit task logs TASK_ID [--tail N]
gleitzeit task result TASK_ID
```

### Priority 2: Workflow Management
```bash
gleitzeit workflow list [--status STATUS]
gleitzeit workflow get WORKFLOW_ID
gleitzeit workflow pause WORKFLOW_ID
gleitzeit workflow resume WORKFLOW_ID
gleitzeit workflow retry WORKFLOW_ID
gleitzeit workflow export WORKFLOW_ID
gleitzeit workflow delete WORKFLOW_ID
```

### Priority 3: Queue Management
```bash
gleitzeit queue list
gleitzeit queue status QUEUE_NAME
gleitzeit queue pause QUEUE_NAME
gleitzeit queue resume QUEUE_NAME
gleitzeit queue clear QUEUE_NAME
```

### Priority 4: Log Management
```bash
gleitzeit logs query [--task-id ID] [--level LEVEL]
gleitzeit logs search QUERY
gleitzeit logs stats
gleitzeit logs cleanup --days N
gleitzeit logs tail TASK_ID
```

### Priority 5: System Management
```bash
gleitzeit system stats
gleitzeit system cleanup --days N
gleitzeit provider list
gleitzeit provider health PROVIDER_ID
```

### Priority 6: Auth Management
```bash
gleitzeit auth login
gleitzeit auth logout
gleitzeit auth api-key create
gleitzeit auth api-key list
gleitzeit auth api-key revoke KEY_ID
gleitzeit auth audit-logs
```

## Implementation Strategy

### Option 1: Direct API Client in CLI
- Add httpx-based API client to CLI
- Each command calls corresponding API endpoint
- Requires API server to be running

### Option 2: Hybrid Approach
- Local operations for simple queries
- API calls for complex operations
- Auto-start API server if needed

### Option 3: Generated CLI from OpenAPI
- Generate CLI commands from OpenAPI spec
- Ensures automatic alignment
- Tools: typer, click-openapi

## Benefits of Alignment

1. **Consistency**: Same operations available via CLI and API
2. **Automation**: CLI commands for scripting and CI/CD
3. **Debugging**: Easy access to logs and errors
4. **Operations**: Queue and system management from terminal
5. **Security**: Auth management without direct API calls

## Current Workarounds

Users must currently:
1. Use `curl` or `httpx` for most operations
2. Start API server and use Web UI
3. Write custom scripts for automation
4. Access database directly for queries

## Recommendations

### Immediate Actions
1. Add task management commands (most used)
2. Add log query commands (debugging)
3. Add workflow list/status commands

### Short Term
1. Implement queue management
2. Add provider health checks
3. Complete auth CLI commands

### Long Term
1. Generate CLI from OpenAPI spec
2. Add interactive mode (REPL)
3. Shell completion for all commands
4. Pipeline composition support

## Conclusion

The current CLI covers only ~15% of API functionality. This severely limits command-line automation and operational capabilities. Implementing the recommended commands would bring CLI-API parity and significantly improve the developer experience.

**Misalignment Score: 8/10** (1 = perfect alignment, 10 = severe misalignment)