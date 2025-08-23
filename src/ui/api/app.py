"""
FastAPI application for Gleitzeit Web UI
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import os

# Import gleitzeit - with fallback to mock if not available
GLEITZEIT_AVAILABLE = False
GleitzeitClient = None

try:
    from gleitzeit.client import GleitzeitClient
    GLEITZEIT_AVAILABLE = True
    print("✅ Gleitzeit package detected - full functionality enabled")
    # Try to import additional modules if available
    try:
        from gleitzeit.core.execution import ExecutionEngine
        from gleitzeit.core.registry import Registry
    except ImportError:
        # These might not be available in all versions
        ExecutionEngine = None
        Registry = None
except ImportError as e:
    print(f"⚠️  Could not import gleitzeit: {e}")
    print("   Running in standalone mode with limited features")
    
    # Create mock classes for standalone mode
    class GleitzeitClient:
        def __init__(self, **kwargs):
            self._engine = None
            self.mode = kwargs.get('mode', 'mock')
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get_status(self):
            return {"ollama": {"available": False}, "resources": {"total": 0, "available": 0}}
        async def run_workflow(self, workflow):
            return {"error": "Gleitzeit not available - please install gleitzeit package"}
        async def list_models(self):
            return []
    
    class ExecutionEngine:
        pass
    
    class Registry:
        pass

# Import routers
from .routes import workflows, tasks, system, websocket
try:
    from .routes import templates as templates_router
    TEMPLATES_AVAILABLE = True
except ImportError:
    TEMPLATES_AVAILABLE = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle - initialize and cleanup resources
    """
    # The UI is now a thin client that proxies to the Gleitzeit API
    # We don't need to create or manage an engine here anymore
    
    # Initialize WebSocket manager
    from .routes.websocket import manager
    app.state.ws_manager = manager
    
    # Store API URL for reference
    app.state.api_url = os.getenv('GLEITZEIT_API_URL', 'http://localhost:8000')
    
    print(f"✅ Gleitzeit UI started - connected to API at {app.state.api_url}")
    
    yield
    
    print("👋 Gleitzeit UI shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Gleitzeit UI",
    description="Web UI for monitoring and managing Gleitzeit workflows",
    version="0.1.0",
    lifespan=lifespan
)

# Setup static files and templates
ui_dir = Path(__file__).parent.parent
app.mount("/static", StaticFiles(directory=str(ui_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(ui_dir / "templates"))

# Include API routers
app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
if TEMPLATES_AVAILABLE:
    app.include_router(templates_router.router, prefix="/api/templates", tags=["templates"])
app.include_router(websocket.router, tags=["websocket"])

# Root route - Dashboard
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard"""
    # Dashboard now gets data from API via AJAX calls
    # We just render the template with minimal initial data
    
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "api_url": request.app.state.api_url,
            "workflows": [],
            "tasks": [],
            "status": {"status": "loading"},
            "active_workflows": 0,
            "running_tasks": 0,
            "resource_utilization": 0
        }
    )

# Workflow pages
@app.get("/workflows", response_class=HTMLResponse)
async def workflows_page(request: Request):
    """Render workflows list page"""
    return templates.TemplateResponse(
        "workflows/list.html",
        {"request": request}
    )

@app.get("/workflows/{workflow_id}", response_class=HTMLResponse)
async def workflow_detail_page(request: Request, workflow_id: str):
    """Render workflow detail page"""
    return templates.TemplateResponse(
        "workflows/detail.html",
        {"request": request, "workflow_id": workflow_id}
    )

# Task pages
@app.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    """Render tasks list page"""
    return templates.TemplateResponse(
        "tasks/list.html",
        {"request": request}
    )

@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail_page(request: Request, task_id: str):
    """Render task detail page"""
    return templates.TemplateResponse(
        "tasks/detail.html",
        {"request": request, "task_id": task_id}
    )

# Health check
@app.get("/health")
async def health_check():
    """Simple health check endpoint"""
    return {"status": "healthy", "service": "gleitzeit-ui"}

# Add a generic proxy for all /api/* routes not handled by specific routers
# This allows the UI to proxy any API endpoint transparently
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_api(request: Request, path: str):
    """
    Generic proxy for all /api/* requests to the Gleitzeit API
    This catches any /api/* routes not handled by specific routers above
    """
    import aiohttp
    import json
    
    api_url = request.app.state.api_url
    
    # Build the target URL
    target_url = f"{api_url}/{path}"
    
    # Get query parameters
    query_params = dict(request.query_params)
    
    # Prepare headers (remove host header)
    headers = dict(request.headers)
    headers.pop('host', None)
    
    # Get request body if present
    body = None
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            body = await request.body()
        except:
            body = None
    
    async with aiohttp.ClientSession() as session:
        try:
            # Make the request to the API
            async with session.request(
                method=request.method,
                url=target_url,
                params=query_params,
                headers=headers,
                data=body
            ) as resp:
                # Get response content
                content = await resp.read()
                
                # Try to parse as JSON
                try:
                    response_data = json.loads(content) if content else {}
                except:
                    # If not JSON, return as text
                    from fastapi.responses import Response
                    return Response(
                        content=content,
                        status_code=resp.status,
                        headers=dict(resp.headers)
                    )
                
                # Return JSON response
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    content=response_data,
                    status_code=resp.status
                )
                
        except aiohttp.ClientError as e:
            # API not reachable
            from fastapi.responses import JSONResponse
            return JSONResponse(
                content={"error": f"Cannot connect to Gleitzeit API: {str(e)}"},
                status_code=503
            )