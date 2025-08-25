# UI to API Endpoint Alignment Check

## API Endpoints Available (from Gleitzeit API server)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/` | Root endpoint |
| GET    | `/health` | Health check |
| GET    | `/status` | System status |
| GET    | `/resources` | Resource manager status |
| GET    | `/providers` | List providers |
| GET    | `/protocols` | List protocols |
| GET    | `/workflows/{workflow_id}` | Get workflow details |
| POST   | `/workflows` | Submit workflow |
| POST   | `/workflows/upload` | Upload workflow file |
| DELETE | `/workflows/{workflow_id}` | Cancel workflow |
| GET    | `/tasks/{task_id}` | Get task details |
| POST   | `/tasks` | Execute task |
| DELETE | `/tasks/{task_id}` | Cancel task |
| POST   | `/batch` | Batch process files |
| POST   | `/chat` | Chat with LLM |
| POST   | `/templates/{template_type}` | Execute template |

## UI Calls to API (from UI routes)

| UI Route | API Call | Status |
|----------|----------|--------|
| **workflows.py** | | |
| GET workflow list | `GET /workflows/{wf_id}` | ❌ MISSING - API has no list endpoint |
| GET workflow detail | `GET /workflows/{workflow_id}` | ✅ OK |
| POST submit workflow | `POST /workflows` | ✅ OK |
| DELETE cancel workflow | `DELETE /workflows/{workflow_id}` | ✅ OK |
| **tasks.py** | | |
| GET task list | `GET /tasks/{task_id}` | ❌ MISSING - API has no list endpoint |
| GET task detail | `GET /tasks/{task_id}` | ✅ OK |
| POST execute task | `POST /tasks` | ✅ OK |
| DELETE cancel task | `DELETE /tasks/{task_id}` | ✅ OK |
| **system.py** | | |
| GET system status | `GET /status` | ✅ OK |
| GET resources | `GET /resources` | ✅ OK |
| GET providers | `GET /providers` | ✅ OK |
| GET protocols | `GET /protocols` | ✅ OK |
| GET health | `GET /health` | ✅ OK |
| GET metrics | `GET /status` | ✅ OK (reuses status) |

## Issues Found

### 1. Missing List Endpoints in API

The API is missing these critical endpoints:
- `GET /workflows` - List all workflows
- `GET /tasks` - List all tasks

The UI tries to work around this by:
- Tracking workflows/tasks submitted in the current session
- Fetching individual items by ID

### 2. Missing Query/Filter Support

The API doesn't support:
- Filtering workflows/tasks by status
- Pagination (limit/offset)
- Sorting

### 3. Missing Batch Query Endpoints

The UI can't efficiently:
- Get all workflows at once
- Get all tasks for a workflow
- Get queue status

## Recommendations

### Add to API (main.py):

```python
@app.get("/workflows")
async def list_workflows(
    status: Optional[str] = None,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0)
):
    """List all workflows with optional filtering"""
    # Query from persistence
    pass

@app.get("/tasks")  
async def list_tasks(
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0)
):
    """List all tasks with optional filtering"""
    # Query from persistence
    pass

@app.get("/workflows/{workflow_id}/tasks")
async def get_workflow_tasks(workflow_id: str):
    """Get all tasks for a workflow"""
    # Query tasks by workflow_id
    pass

@app.get("/tasks/queue/status")
async def get_queue_status():
    """Get task queue statistics"""
    # Return queue metrics
    pass
```

### Current Workaround in UI

The UI maintains its own tracking:
```python
# In workflows.py
_ui_workflows = {}  # Tracks submitted workflows

# In tasks.py  
_ui_tasks = {}  # Tracks submitted tasks
```

This is not ideal because:
- Only shows items from current UI session
- Doesn't show workflows/tasks from other sources
- State is lost on UI restart
- Can't see historical data

## Alignment Status Summary

- ✅ **Individual item operations work** (get/update/delete by ID)
- ❌ **List/query operations missing** (can't browse all items)
- ⚠️ **UI uses workarounds** (session-based tracking)
- 🔧 **API needs list endpoints** to properly support UI

The UI is correctly designed to proxy to the API, but the API is missing essential list/query endpoints that any monitoring UI would need.