# Gleitzeit Web UI

A modern web interface for monitoring and managing Gleitzeit workflows and tasks.

## Architecture

The Gleitzeit UI is a **thin client** that connects to the Gleitzeit REST API. It does NOT create its own execution engine or manage workflows directly.

```
[Gleitzeit API Server (port 8000)]
    ├── ExecutionEngine (manages workflow execution)
    ├── Providers (Python, Ollama, MCP)
    ├── Persistence (Redis/SQLite/Memory)
    └── REST API endpoints

[Gleitzeit Web UI (port 8004)]
    ├── FastAPI web server
    ├── HTMX-powered frontend
    ├── Proxies all requests to API
    └── Real-time updates via WebSocket
```

## Prerequisites

1. **Gleitzeit API Server must be running**:
   ```bash
   gleitzeit serve --port 8000
   ```
   
   The API server will:
   - Initialize persistence (Redis → SQLite → Memory fallback)
   - Start resource management with OllamaHub
   - Register and start all providers (Python, Ollama, MCP)
   - Make providers available for workflow execution

2. **Python dependencies**:
   ```bash
   pip install fastapi uvicorn aiohttp jinja2 python-multipart websockets psutil
   ```

## Quick Start

### Step 1: Start the API Server
```bash
# Start the Gleitzeit API (required!)
gleitzeit serve --port 8000
```

### Step 2: Start the UI

#### Via CLI (Recommended)
```bash
# Start the UI (will check API connectivity)
gleitzeit ui --port 8004

# Custom host/port
gleitzeit ui --host 0.0.0.0 --port 8080

# With auto-reload for development
gleitzeit ui --reload
```

#### Standalone
```bash
cd src/ui
uvicorn api.app:app --port 8004
```

The UI will be available at: http://localhost:8004

### Configuration

Set the API endpoint via environment variable:
```bash
export GLEITZEIT_API_URL=http://localhost:8000
gleitzeit ui
```

## Features

### Dashboard
- System status overview
- Active workflows count
- Running tasks count
- Resource utilization metrics
- Provider health status (Python, Ollama, MCP)

### Workflows
- List all workflows with status
- Submit new workflows (YAML/JSON)
- View workflow details and task graph
- Cancel running workflows
- Download workflow results

### Tasks
- List all tasks with filtering
- View task details and results
- Execute individual tasks
- Monitor task queue status
- Cancel running tasks

### System Monitoring
- Provider status and capabilities
- Resource manager metrics
- Ollama hub instances
- System resource usage (CPU/Memory/Disk)

## How It Works

1. **No Engine Creation**: The UI does NOT create its own GleitzeitClient or ExecutionEngine
2. **API Proxy**: All workflow/task operations are proxied to the Gleitzeit API
3. **Session Tracking**: The UI tracks workflows/tasks submitted in the current session
4. **Real-time Updates**: WebSocket connection for live status updates
5. **Auto-refresh**: HTMX polls endpoints for updated data

## API Endpoints

The UI exposes these endpoints that proxy to the Gleitzeit API:

### Workflows
- `GET /api/workflows` - List workflows
- `GET /api/workflows/{id}` - Get workflow details
- `POST /api/workflows/submit` - Submit workflow
- `DELETE /api/workflows/{id}` - Cancel workflow

### Tasks
- `GET /api/tasks` - List tasks
- `GET /api/tasks/{id}` - Get task details
- `POST /api/tasks/execute` - Execute task
- `DELETE /api/tasks/{id}` - Cancel task
- `GET /api/tasks/queue/status` - Queue statistics

### System
- `GET /api/system/status` - System status
- `GET /api/system/resources` - Resource manager status
- `GET /api/system/providers` - List providers
- `GET /api/system/health` - Health check
- `GET /api/system/metrics` - System metrics

### WebSocket
- `WS /ws/updates` - Real-time workflow/task updates

## Project Structure

```
src/ui/
├── api/
│   ├── app.py              # FastAPI application (thin client)
│   └── routes/             # API route handlers (proxy to Gleitzeit API)
│       ├── workflows.py    # Workflow endpoints
│       ├── tasks.py        # Task endpoints
│       ├── system.py       # System monitoring
│       └── websocket.py    # WebSocket handler
├── static/
│   ├── css/               # Stylesheets (Tailwind CSS)
│   └── js/                # JavaScript (HTMX)
└── templates/             # Jinja2 HTML templates
    ├── base.html          # Base template
    ├── index.html         # Dashboard
    ├── workflows/         # Workflow pages
    │   ├── list.html     # Workflow list
    │   └── detail.html   # Workflow details
    └── tasks/            # Task pages
        ├── list.html     # Task list
        └── detail.html   # Task details
```

## Development

### Key Technologies
- **FastAPI**: Async Python web framework
- **HTMX**: Dynamic HTML without complex JavaScript
- **Jinja2**: Server-side templating
- **Tailwind CSS**: Utility-first CSS framework
- **WebSocket**: Real-time bidirectional communication
- **aiohttp**: Async HTTP client for API calls

### Adding New Features

1. **New API Endpoint** (proxy to Gleitzeit API):
   ```python
   # In api/routes/your_feature.py
   @router.get("/your-endpoint")
   async def your_endpoint(request: Request):
       async with aiohttp.ClientSession() as session:
           async with session.get(f"{GLEITZEIT_API_URL}/your-api-endpoint") as resp:
               return await resp.json()
   ```

2. **New Template**:
   ```html
   <!-- In templates/your_feature.html -->
   {% extends "base.html" %}
   {% block content %}
   <div hx-get="/api/your-endpoint" 
        hx-trigger="load, every 5s"
        hx-swap="innerHTML">
     Loading...
   </div>
   {% endblock %}
   ```

3. **Register Route**:
   ```python
   # In api/app.py
   from .routes import your_feature
   app.include_router(your_feature.router, prefix="/api/your-feature")
   ```

### Environment Variables

- `GLEITZEIT_API_URL` - Gleitzeit API endpoint (default: `http://localhost:8000`)
- `UI_HOST` - UI server host (default: `127.0.0.1`)
- `UI_PORT` - UI server port (default: `8004`)

## Usage Examples

### Submit a Workflow

1. Navigate to the Workflows page
2. Click "New Workflow"
3. Paste your workflow YAML:

```yaml
name: "Example Workflow"
tasks:
  - id: "hello"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Say hello!"
```

4. Click "Submit"

The workflow will be sent to the Gleitzeit API for execution.

### Monitor Task Execution

1. Go to the Tasks page
2. Click on a task to view details
3. View real-time logs and results
4. Retry failed tasks if needed

## Troubleshooting

### UI shows no workflows/tasks
- **Check if API is running**: `curl http://localhost:8000/health`
- **Verify providers are healthy**: `curl http://localhost:8000/providers`
- **Check UI logs** for connection errors
- Remember: UI only tracks workflows/tasks submitted in current session

### "API not available" error
- **Start the API server first**: `gleitzeit serve`
- **Check API URL**: `echo $GLEITZEIT_API_URL`
- **Verify connectivity**: `curl http://localhost:8000/`

### Providers show as "unhealthy"
- The API server needs to properly start providers
- Check API startup logs for errors
- Verify Ollama is running: `ollama list`
- Check Redis if using Redis persistence

### WebSocket disconnections
- Check browser console for WebSocket errors
- Verify firewall/proxy allows WebSocket connections
- Try disabling browser extensions

## Important Notes

1. **The UI is stateless** - doesn't persist any data itself
2. **Requires API server** - won't work without Gleitzeit API running
3. **Session-based tracking** - only tracks workflows/tasks from current UI session
4. **No direct engine access** - all operations go through REST API
5. **Real-time updates** - WebSocket for live status, falls back to polling

## Security Considerations

- UI should only be accessible from trusted networks
- Consider using reverse proxy (nginx/caddy) for production
- Add authentication if exposing to internet
- Use HTTPS in production
- Validate all inputs before sending to API

## API Server Setup

The Gleitzeit API server (`gleitzeit serve`) properly initializes:

1. **Persistence Backend** (Redis → SQLite → Memory)
2. **Resource Manager** with OllamaHub auto-discovery
3. **Providers** (all started and healthy):
   - Python Provider - for executing Python scripts
   - Ollama Provider - for LLM operations
   - MCP Provider - for MCP tool integrations

Without the API server running with healthy providers, the UI cannot execute workflows.

## Contributing

When making changes to the UI:
1. **Do NOT add direct engine or provider access**
2. **All data operations must go through the API**
3. **Follow existing HTMX patterns** for dynamic updates
4. **Test with API both running and not running**
5. **Ensure graceful degradation** when API unavailable
6. **Update this documentation** for new features

## License

Part of the Gleitzeit project - MIT License