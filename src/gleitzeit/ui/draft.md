# Gleitzeit Web UI - Architecture Draft

## Overview

A FastAPI-based web UI for monitoring and managing Gleitzeit workflows, tasks, and results. The UI focuses on real-time monitoring, result viewing, and workflow visualization.

## Architecture

### Tech Stack

- **Backend**: FastAPI (async Python web framework)
- **Frontend**: HTML/CSS/JavaScript with HTMX for dynamic updates
- **WebSocket**: Real-time task/workflow status updates
- **CSS Framework**: Tailwind CSS or minimal custom CSS
- **Charts**: Chart.js for metrics visualization

### Why This Stack?

- FastAPI integrates naturally with Gleitzeit's async architecture
- HTMX provides reactivity without heavy JavaScript frameworks
- WebSockets enable real-time monitoring without polling
- Server-side rendering keeps the UI lightweight and fast

## Core Features (Phase 1)

### 1. Dashboard
- Active workflows count
- Running tasks count
- Resource utilization (Ollama instances, Python processes)
- Recent workflow history
- System health indicators

### 2. Workflow Monitoring
- List of all workflows (running, completed, failed)
- Workflow details view with:
  - Task dependency graph visualization
  - Task status indicators
  - Execution timeline
  - Parameter values
  - Results/outputs

### 3. Task Monitoring
- Real-time task status updates
- Task queue visualization
- Task details:
  - Method/provider
  - Parameters
  - Execution time
  - Result/error output
  - Retry attempts

### 4. Results Viewer
- Formatted display of task results
- JSON/text/markdown rendering
- Export capabilities (JSON, CSV)
- Search and filter results

## API Endpoints

### Monitoring Endpoints

```python
# Workflows
GET /api/workflows                 # List all workflows
GET /api/workflows/{id}           # Get workflow details
GET /api/workflows/{id}/tasks     # Get workflow tasks
GET /api/workflows/{id}/results   # Get workflow results
DELETE /api/workflows/{id}        # Cancel workflow

# Tasks
GET /api/tasks                    # List all tasks
GET /api/tasks/{id}              # Get task details
GET /api/tasks/{id}/result       # Get task result
GET /api/tasks/{id}/logs         # Get task logs

# System
GET /api/status                   # System status
GET /api/metrics                  # Performance metrics
GET /api/resources               # Resource availability

# WebSocket
WS /ws/updates                   # Real-time updates stream
```

### Monitoring WebSocket Protocol

```json
// Client subscribes to updates
{
  "type": "subscribe",
  "channels": ["workflows", "tasks", "metrics"]
}

// Server sends updates
{
  "type": "workflow_update",
  "data": {
    "id": "workflow-123",
    "status": "running",
    "progress": 0.6,
    "current_task": "analyze"
  }
}

{
  "type": "task_update", 
  "data": {
    "id": "task-456",
    "status": "completed",
    "result": {...}
  }
}
```

## Directory Structure

```
src/ui/
├── draft.md                  # This file
├── api/
│   ├── __init__.py
│   ├── app.py               # FastAPI app initialization
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── workflows.py     # Workflow endpoints
│   │   ├── tasks.py         # Task endpoints
│   │   ├── system.py        # System/metrics endpoints
│   │   └── websocket.py     # WebSocket handler
│   ├── models/
│   │   ├── __init__.py
│   │   └── responses.py     # Pydantic response models
│   └── services/
│       ├── __init__.py
│       ├── monitoring.py    # Monitoring service
│       └── formatter.py     # Result formatting
├── static/
│   ├── css/
│   │   └── main.css         # Custom styles
│   ├── js/
│   │   ├── htmx.min.js      # HTMX library
│   │   ├── app.js           # Main application JS
│   │   └── websocket.js     # WebSocket client
│   └── img/
│       └── logo.svg         # Gleitzeit logo
└── templates/
    ├── base.html            # Base template
    ├── index.html           # Dashboard
    ├── workflows/
    │   ├── list.html        # Workflow list
    │   ├── detail.html      # Workflow detail
    │   └── _task_card.html  # Task card partial
    ├── tasks/
    │   ├── list.html        # Task list
    │   └── detail.html      # Task detail
    └── components/
        ├── _navbar.html     # Navigation
        ├── _status.html     # Status indicators
        └── _result.html     # Result viewer

```

## UI Components

### 1. Dashboard Layout

```
┌─────────────────────────────────────────────────────────┐
│                    Navigation Bar                       │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Active     │  │   Running    │  │   Resource   │ │
│  │  Workflows   │  │    Tasks     │  │ Utilization  │ │
│  │      5       │  │      12      │  │     45%      │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Recent Workflows                                      │
│  ┌─────────────────────────────────────────────────┐  │
│  │ ▶ Analysis Pipeline      Running    2/5 tasks   │  │
│  │ ✓ Document Processor     Complete   5/5 tasks   │  │
│  │ ✗ Data ETL              Failed     3/4 tasks   │  │
│  └─────────────────────────────────────────────────┘  │
│                                                         │
│  Task Queue                                            │
│  ┌─────────────────────────────────────────────────┐  │
│  │ [■■■■■□□□□□] 5 running, 3 queued                │  │
│  └─────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 2. Workflow Detail View

```
┌─────────────────────────────────────────────────────────┐
│  Workflow: Analysis Pipeline                            │
│  Status: Running | Started: 10:30 AM | Duration: 2m    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Task Graph:                                           │
│    [load_data] ──→ [analyze] ──→ [save_results]       │
│        ✓              ▶              □                 │
│                                                         │
│  Tasks:                                                │
│  ┌─────────────────────────────────────────────────┐  │
│  │ load_data    ✓ Complete   0.5s   View Result   │  │
│  │ analyze      ▶ Running    1.2s   View Logs     │  │
│  │ save_results □ Pending    --     --            │  │
│  └─────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 3. Result Viewer

```
┌─────────────────────────────────────────────────────────┐
│  Task Result: analyze                                   │
│  Format: [JSON] [Text] [Markdown]    [Export] [Copy]   │
├─────────────────────────────────────────────────────────┤
│  {                                                      │
│    "response": "The analysis shows...",                │
│    "confidence": 0.95,                                  │
│    "topics": ["data", "trends", "insights"],           │
│    "execution_time": 1.234                              │
│  }                                                      │
└─────────────────────────────────────────────────────────┘
```

## Implementation Plan

### Phase 1: Core Monitoring (Week 1)
1. FastAPI app setup with basic routes
2. Integration with Gleitzeit ExecutionEngine
3. Workflow and task listing endpoints
4. Basic HTML templates with HTMX
5. Real-time status updates via WebSocket

### Phase 2: Enhanced Visualization (Week 2)
1. Task dependency graph visualization
2. Execution timeline view
3. Resource utilization charts
4. Result formatting and syntax highlighting
5. Search and filtering capabilities

### Phase 3: Management Features (Week 3)
1. Workflow submission interface
2. Task retry/cancel functionality
3. Resource management controls
4. Export and reporting features
5. User preferences and settings

## Code Examples

### FastAPI App Structure

```python
# src/ui/api/app.py
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from gleitzeit import GleitzeitClient

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Gleitzeit client
    app.state.gleitzeit = GleitzeitClient(mode="native")
    await app.state.gleitzeit.__aenter__()
    yield
    # Cleanup
    await app.state.gleitzeit.__aexit__(None, None, None)

app = FastAPI(title="Gleitzeit UI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Include routers
from .routes import workflows, tasks, system, websocket
app.include_router(workflows.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(websocket.router)
```

### Workflow Monitoring Endpoint

```python
# src/ui/api/routes/workflows.py
from fastapi import APIRouter, Request, HTTPException
from typing import List, Optional

router = APIRouter()

@router.get("/workflows")
async def list_workflows(
    request: Request,
    status: Optional[str] = None,
    limit: int = 50
):
    """List all workflows with optional status filter"""
    client = request.app.state.gleitzeit
    
    # Get workflows from execution engine
    workflows = await client.get_workflows(status=status, limit=limit)
    
    return {
        "workflows": workflows,
        "total": len(workflows)
    }

@router.get("/workflows/{workflow_id}")
async def get_workflow(request: Request, workflow_id: str):
    """Get detailed workflow information"""
    client = request.app.state.gleitzeit
    
    workflow = await client.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    return workflow

@router.get("/workflows/{workflow_id}/tasks")
async def get_workflow_tasks(request: Request, workflow_id: str):
    """Get all tasks for a workflow"""
    client = request.app.state.gleitzeit
    
    tasks = await client.get_workflow_tasks(workflow_id)
    return {"tasks": tasks}
```

### WebSocket Updates

```python
# src/ui/api/routes/websocket.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import json

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)

manager = ConnectionManager()

@router.websocket("/ws/updates")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_json()
            
            if data["type"] == "subscribe":
                # Handle subscription
                await monitor_updates(websocket, data["channels"])
    
    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def monitor_updates(websocket: WebSocket, channels: List[str]):
    """Send updates for subscribed channels"""
    while True:
        # Get updates from Gleitzeit
        # This would hook into the ExecutionEngine's event system
        updates = await get_engine_updates(channels)
        
        for update in updates:
            await websocket.send_json(update)
        
        await asyncio.sleep(0.5)  # Poll interval
```

### HTMX Dynamic Updates

```html
<!-- templates/workflows/list.html -->
<div id="workflow-list" 
     hx-get="/api/workflows" 
     hx-trigger="every 2s"
     hx-swap="innerHTML">
  
  {% for workflow in workflows %}
  <div class="workflow-card">
    <h3>{{ workflow.name }}</h3>
    <span class="status status-{{ workflow.status }}">
      {{ workflow.status }}
    </span>
    <div class="progress">
      <div class="progress-bar" 
           style="width: {{ workflow.progress * 100 }}%">
      </div>
    </div>
    <a href="/workflows/{{ workflow.id }}" 
       hx-get="/workflows/{{ workflow.id }}"
       hx-target="#main-content">
      View Details
    </a>
  </div>
  {% endfor %}
</div>
```

## Security Considerations

1. **Authentication**: Add auth middleware for production
2. **Rate Limiting**: Implement rate limits on API endpoints
3. **Input Validation**: Validate all user inputs
4. **CORS**: Configure CORS appropriately
5. **WebSocket Security**: Implement token-based WebSocket auth

## Performance Optimizations

1. **Caching**: Cache workflow/task data with TTL
2. **Pagination**: Implement pagination for large result sets
3. **Lazy Loading**: Load task details on demand
4. **Compression**: Enable gzip compression
5. **Connection Pooling**: Use connection pools for database

## Future Enhancements

1. **Workflow Designer**: Visual workflow creation tool
2. **Metrics Dashboard**: Advanced analytics and metrics
3. **Collaborative Features**: Multi-user support with permissions
4. **Notifications**: Email/webhook notifications for events
5. **Mobile Responsive**: Optimize for mobile devices
6. **Dark Mode**: Theme switching support
7. **API Documentation**: Interactive Swagger/ReDoc UI

## Development Setup

```bash
# Install dependencies
pip install fastapi uvicorn jinja2 python-multipart websockets

# Run development server
cd src/ui
uvicorn api.app:app --reload --port 8001

# Access UI
# http://localhost:8001
```

## Testing Strategy

1. **Unit Tests**: Test individual endpoints and services
2. **Integration Tests**: Test with real Gleitzeit engine
3. **WebSocket Tests**: Test real-time updates
4. **UI Tests**: Playwright for end-to-end testing
5. **Load Tests**: Locust for performance testing

## Conclusion

This UI design provides a solid foundation for monitoring and managing Gleitzeit workflows. The focus on real-time updates, clean visualization, and lightweight architecture ensures a responsive and intuitive user experience. The modular design allows for incremental development and easy extension with additional features.