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