# Gleitzeit Web UI - Implementation Documentation

## Overview

The Gleitzeit Web UI is a FastAPI-based monitoring and management interface for Gleitzeit workflows. It provides real-time monitoring, workflow submission, and result viewing capabilities.

## Current Implementation Status

### ✅ Completed Features

#### 1. **Core Infrastructure**
- **FastAPI Application** (`api/app.py`)
  - Lifespan management with automatic Gleitzeit client initialization
  - Auto-detection of installed Gleitzeit package vs standalone mode
  - Integration with Gleitzeit execution engine
  - Static file serving and template rendering
  - Health check endpoint

#### 2. **Workflow Management** (`api/routes/workflows.py`)
- **Endpoints Implemented:**
  - `GET /api/workflows` - List all workflows with pagination and status filtering
  - `GET /api/workflows/{id}` - Get detailed workflow information
  - `POST /api/workflows` - Submit new workflows (converts dict to YAML file)
  - `DELETE /api/workflows/{id}` - Cancel running workflows
  - `GET /api/workflows/{id}/tasks` - Get tasks for a workflow
  - `GET /api/workflows/{id}/results` - Get workflow execution results
  - `GET /api/workflows/{id}/timeline` - Get execution timeline

- **Features:**
  - Automatic workflow status detection from results
  - In-memory workflow storage with result tracking
  - WebSocket notifications on workflow updates
  - Support for multi-task workflows with dependencies

#### 3. **Task Monitoring** (`api/routes/tasks.py`)
- **Endpoints Implemented:**
  - `GET /api/tasks` - List all tasks with filters
  - `GET /api/tasks/{id}` - Get task details
  - `GET /api/tasks/{id}/result` - Get task execution result
  - `GET /api/tasks/{id}/logs` - Get task logs (with tail support)
  - `POST /api/tasks/{id}/retry` - Retry failed tasks
  - `DELETE /api/tasks/{id}` - Cancel running/pending tasks
  - `GET /api/tasks/queue/status` - Get queue statistics

- **Features:**
  - Automatic task status extraction from workflow results
  - Task result storage and retrieval
  - Dynamic task discovery from workflows
  - Support for task retry and cancellation

#### 4. **System Monitoring** (`api/routes/system.py`)
- **Endpoints Implemented:**
  - `GET /api/system/status` - Overall system health and status
  - `GET /api/system/metrics` - Performance metrics
  - `GET /api/system/resources` - Resource availability (Ollama, Python, MCP)
  - `GET /api/system/providers` - List registered providers
  - `GET /api/system/logs` - System logs with filtering
  - `POST /api/system/config` - Update configuration
  - `GET /api/system/info` - System information

- **Features:**
  - CPU, memory, and disk usage monitoring (when psutil is available)
  - Ollama instance detection and status
  - Provider registration tracking
  - Persistence backend detection (Redis/SQLite/Memory)

#### 5. **WebSocket Support** (`api/routes/websocket.py`)
- **Features Implemented:**
  - Real-time connection management
  - Channel-based subscriptions (workflows, tasks, metrics, system)
  - Broadcast capabilities for updates
  - Connection status tracking
  - Automatic reconnection handling in client

- **Message Types:**
  - `workflow_update` - Workflow status changes
  - `task_update` - Task status changes
  - `metrics_update` - System metrics updates
  - `system_event` - System-level events
  - `status_update` - Overall status updates

#### 6. **Frontend Templates**
- **Base Template** (`templates/base.html`)
  - Navigation bar with active page highlighting
  - WebSocket connection status indicator
  - HTMX integration for dynamic updates
  - Chart.js for visualizations

- **Dashboard** (`templates/index.html`)
  - Metric cards (active workflows, running tasks, resource utilization)
  - System status grid with health indicators
  - Recent workflows list with auto-refresh
  - Task queue visualization
  - Performance metrics chart

- **Workflows Pages** (`templates/workflows/`)
  - `list.html` - Workflow listing with filters and search
  - `detail.html` - Detailed workflow view with task graph and timeline
  - Submit workflow modal with YAML input
  - Progress bars and status indicators

- **Tasks Pages** (`templates/tasks/`)
  - `list.html` - Task listing with queue status
  - `detail.html` - Task details with result viewer and logs
  - Support for multiple result formats (JSON, text, markdown)
  - Download and copy functionality for results

#### 7. **Static Assets**
- **CSS** (`static/css/main.css`)
  - Complete responsive design system
  - Status color coding
  - Card and grid layouts
  - Modal and form styles
  - Dark code blocks for results

- **JavaScript** (`static/js/`)
  - `app.js` - Main application logic, HTMX handlers, formatting utilities
  - `websocket.js` - WebSocket client with auto-reconnection and channel management

## Integration with Gleitzeit

### How It Works

1. **On Startup:**
   - Attempts to import Gleitzeit package
   - Falls back to mock classes if not available
   - Initializes GleitzeitClient in native mode
   - Registers all providers (Ollama, Python, MCP)
   - Connects to persistence backend (Redis/SQLite/Memory)

2. **Workflow Submission:**
   - Receives workflow as JSON via API
   - Converts to YAML and saves to temporary file
   - Submits to Gleitzeit engine via `client.run_workflow()`
   - Tracks workflow in memory with results
   - Updates status based on completion

3. **Task Tracking:**
   - Extracts tasks from workflow definitions
   - Maps task results from workflow execution results
   - Provides real-time status updates
   - Stores results for viewing

4. **Resource Management:**
   - Auto-discovers Ollama instances (ports 11434-11436)
   - Tracks provider availability
   - Monitors system resources

## Data Flow

```
User → UI (Browser) → FastAPI → GleitzeitClient → ExecutionEngine
                ↑                                        ↓
           WebSocket ← Updates ← Task Results ← Providers (Ollama/Python/MCP)
```

## Current Limitations & TODOs

### Limitations
- Workflow and task data stored in memory (lost on restart)
- No authentication or user management
- Limited error handling for edge cases
- No workflow validation before submission
- Task logs are mock data (not connected to actual execution logs)

### TODOs
- [ ] Persist workflows and tasks to database
- [ ] Add workflow validation before submission
- [ ] Implement actual log streaming from task execution
- [ ] Add workflow templates and examples
- [ ] Implement workflow editing/modification
- [ ] Add export functionality for workflows and results
- [ ] Implement batch workflow submission
- [ ] Add metrics history and trending
- [ ] Implement workflow scheduling
- [ ] Add notification system for workflow completion

## API Usage Examples

### Submit a Workflow
```bash
curl -X POST http://localhost:8004/api/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Example Workflow",
    "tasks": [
      {
        "id": "task1",
        "method": "llm/chat",
        "parameters": {
          "model": "llama3.2",
          "messages": [{"role": "user", "content": "Hello"}]
        }
      }
    ]
  }'
```

### Get Workflow Status
```bash
curl http://localhost:8004/api/workflows/{workflow_id}
```

### List Tasks
```bash
curl http://localhost:8004/api/tasks?status=completed
```

### Get System Status
```bash
curl http://localhost:8004/api/system/status
```

### WebSocket Connection
```javascript
const ws = new WebSocket('ws://localhost:8004/ws/updates');
ws.send(JSON.stringify({
  type: 'subscribe',
  channels: ['workflows', 'tasks']
}));
```

## Configuration

### Environment Variables
- `GLEITZEIT_API_URL` - Gleitzeit API endpoint (if using API mode)
- `GLEITZEIT_DEFAULT_MODEL` - Default LLM model
- `GLEITZEIT_PERSISTENCE_TYPE` - Persistence backend (auto/redis/sql/memory)

### Running the UI

```bash
# Development
cd src/ui
python -m uvicorn api.app:app --reload --port 8004

# Production
uvicorn api.app:app --host 0.0.0.0 --port 8004 --workers 4
```

## Testing

Tests are located in `/tests/ui/`:
- `test_api_endpoints.py` - API endpoint tests
- `test_websocket.py` - WebSocket functionality tests

Run tests:
```bash
pytest tests/ui/
```

## Architecture Decisions

1. **HTMX over Heavy JS Framework**: Chosen for simplicity and server-side rendering benefits
2. **WebSocket for Real-time Updates**: Provides instant feedback without polling overhead
3. **In-Memory Storage**: Simple for initial implementation, easily replaceable with persistence
4. **Standalone Mode**: Allows UI to run without Gleitzeit for development/testing
5. **Native Mode Integration**: Direct engine access for better performance vs API mode

## Browser Compatibility

- Modern browsers with WebSocket support
- Tested on Chrome, Firefox, Safari, Edge
- Requires JavaScript enabled for full functionality

## Performance Considerations

- Auto-refresh intervals: 2-5 seconds depending on component
- WebSocket reconnection: 5 second intervals with exponential backoff
- Pagination: Default 50 items per page
- Result size limits: Truncated if exceeding reasonable limits

## Security Notes

- No authentication implemented (add for production)
- Input validation on workflow submission
- XSS protection via template escaping
- CORS configuration needed for cross-origin access

## Maintenance

### Adding New Endpoints
1. Add route handler in appropriate file under `api/routes/`
2. Update OpenAPI documentation
3. Add tests in `tests/ui/`
4. Update this documentation

### Modifying Templates
1. Edit templates in `templates/`
2. Ensure HTMX attributes are properly set
3. Test auto-refresh functionality
4. Update CSS if needed

### Updating WebSocket Protocol
1. Modify message handlers in `websocket.py`
2. Update client-side handler in `websocket.js`
3. Document new message types
4. Test reconnection scenarios