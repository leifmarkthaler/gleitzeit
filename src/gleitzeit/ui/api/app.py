"""
Gleitzeit UI2 - Clean UI with WebSocket support
"""
import os
import uuid
import asyncio
import logging
from pathlib import Path
from typing import Optional, Set

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        if not self.active_connections:
            return

        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to WebSocket: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

# Configuration
API_BASE_URL = os.getenv("GLEITZEIT_API_URL", "http://localhost:8000")
API_KEY = os.getenv("GLEITZEIT_API_KEY", "dev-key-12345")  # Default dev key

app = FastAPI(title="Gleitzeit UI2")

# Setup static files and templates
ui_dir = Path(__file__).parent.parent
app.mount("/static", StaticFiles(directory=str(ui_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(ui_dir / "templates"))

# Disable all caching
templates.env.auto_reload = True
templates.env.cache = None

# HTTP client for API calls with authentication
client = httpx.AsyncClient(
    base_url=API_BASE_URL,
    timeout=30.0,
    headers={"X-API-Key": API_KEY}
)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    """Disable caching for all HTML responses"""
    response = await call_next(request)
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


async def get_base_context(request: Request) -> dict:
    """Get base template context"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())

    return {
        "request": request,
        "session_id": session_id,
        "version": "0.0.7"
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Home page - redirect to workflows"""
    context = await get_base_context(request)
    return templates.TemplateResponse("index.html", context)


@app.get("/workflows", response_class=HTMLResponse)
async def workflows_list(request: Request):
    """Workflows list page"""
    context = await get_base_context(request)
    return templates.TemplateResponse("workflows.html", context)


@app.get("/tasks", response_class=HTMLResponse)
async def tasks_list(request: Request):
    """Tasks list page"""
    context = await get_base_context(request)
    return templates.TemplateResponse("tasks.html", context)


@app.get("/logs", response_class=HTMLResponse)
async def logs_list(request: Request):
    """Logs list page"""
    context = await get_base_context(request)
    return templates.TemplateResponse("logs/list.html", context)


@app.get("/metrics", response_class=HTMLResponse)
async def metrics_detail(request: Request):
    """Metrics detail page"""
    context = await get_base_context(request)
    return templates.TemplateResponse("metrics/detail.html", context)


@app.get("/processes", response_class=HTMLResponse)
async def processes_list(request: Request):
    """Processes list page"""
    context = await get_base_context(request)
    return templates.TemplateResponse("processes/list.html", context)


@app.get("/handlers", response_class=HTMLResponse)
async def handlers_list(request: Request):
    """Handlers list page"""
    context = await get_base_context(request)
    return templates.TemplateResponse("handlers/list.html", context)


@app.get("/workflows/{workflow_id}", response_class=HTMLResponse)
async def workflow_detail(request: Request, workflow_id: str):
    """Workflow detail page"""
    context = await get_base_context(request)

    # Fetch workflow data from API
    try:
        response = await client.get(f"/workflows/{workflow_id}")
        workflow_data = response.json()
    except Exception as e:
        logger.error(f"Failed to fetch workflow {workflow_id}: {e}")
        workflow_data = {"workflow_id": workflow_id, "error": str(e)}

    # Extract tasks if available
    tasks = []
    if "data" in workflow_data and "tasks" in workflow_data["data"]:
        tasks = workflow_data["data"]["tasks"]

    context["workflow"] = workflow_data
    context["tasks"] = tasks
    return templates.TemplateResponse("workflows/detail.html", context)


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    """Task detail page"""
    context = await get_base_context(request)

    # Fetch task data from API
    try:
        response = await client.get(f"/tasks/{task_id}")
        task_data = response.json()
    except Exception as e:
        logger.error(f"Failed to fetch task {task_id}: {e}")
        task_data = {"task_id": task_id, "error": str(e)}

    context["task"] = task_data
    return templates.TemplateResponse("tasks/detail.html", context)


@app.get("/submit", response_class=HTMLResponse)
async def submit_workflow_page(request: Request):
    """Workflow submission page"""
    context = await get_base_context(request)
    return templates.TemplateResponse("submit.html", context)


# API proxy endpoints
@app.get("/api/workflows/list")
async def api_workflows_list(limit: int = 100):
    """Proxy to workflows API"""
    try:
        response = await client.get(f"/workflows/list?limit={limit}")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch workflows: {e}")
        return {"workflows": []}


@app.get("/api/tasks/list")
async def api_tasks_list(limit: int = 100):
    """Proxy to tasks API - fetches task IDs then gets full details"""
    try:
        # First get the task IDs
        response = await client.get(f"/tasks/list?limit={limit}")
        data = response.json()
        task_ids = data.get("task_ids", [])

        # Fetch full details for each task
        tasks = []
        for task_id in task_ids[:limit]:  # Limit to requested number
            try:
                task_response = await client.get(f"/tasks/{task_id}")
                task_data = task_response.json()
                if task_data and "error" not in task_data:
                    tasks.append(task_data)
            except Exception as task_error:
                logger.warning(f"Failed to fetch task {task_id}: {task_error}")
                continue

        return {
            "tasks": tasks,
            "total": data.get("total", len(tasks))
        }
    except Exception as e:
        logger.error(f"Failed to fetch tasks: {e}")
        return {"tasks": [], "total": 0}


@app.get("/api/workflows/{workflow_id}")
async def api_workflow_detail(workflow_id: str):
    """Proxy to workflow detail API"""
    try:
        response = await client.get(f"/workflows/{workflow_id}")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch workflow: {e}")
        return {"error": str(e)}


@app.get("/api/tasks/{task_id}")
async def api_task_detail(task_id: str):
    """Proxy to task detail API"""
    try:
        response = await client.get(f"/tasks/{task_id}")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch task: {e}")
        return {"error": str(e)}


@app.get("/api/health")
async def health_check():
    """Health check endpoint - returns detailed health"""
    try:
        response = await client.get("/health/detailed")
        return response.json()
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )


# System logs endpoints
@app.get("/api/system/logs/errors")
async def api_system_logs_errors(
    limit: int = 50,
    offset: int = 0,
    workflow_id: Optional[str] = None,
    component: Optional[str] = None
):
    """Proxy to system error logs API"""
    try:
        params = {"limit": limit, "offset": offset}
        if workflow_id:
            params["workflow_id"] = workflow_id
        if component:
            params["component"] = component

        response = await client.get("/system/logs/errors", params=params)
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch error logs: {e}")
        return {"errors": [], "total": 0}


@app.get("/api/system/logs")
async def api_system_logs(
    level: str = "INFO",
    limit: int = 50,
    offset: int = 0,
    workflow_id: Optional[str] = None,
    component: Optional[str] = None
):
    """Proxy to system logs API"""
    try:
        params = {"level": level, "limit": limit, "offset": offset}
        if workflow_id:
            params["workflow_id"] = workflow_id
        if component:
            params["component"] = component

        response = await client.get("/system/logs", params=params)
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch logs: {e}")
        return {"logs": [], "total": 0}


@app.get("/api/system/logs/stats")
async def api_system_logs_stats(
    workflow_id: Optional[str] = None,
    component: Optional[str] = None
):
    """Proxy to system logs statistics API"""
    try:
        params = {}
        if workflow_id:
            params["workflow_id"] = workflow_id
        if component:
            params["component"] = component

        response = await client.get("/system/logs/stats", params=params)
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch log stats: {e}")
        return {"stats": {}, "total": 0}


# System metrics endpoints
@app.get("/api/system/metrics")
async def api_system_metrics():
    """Proxy to system metrics API"""
    try:
        response = await client.get("/system/metrics")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch system metrics: {e}")
        return {"workflows": {}, "tasks": {}}


@app.get("/api/system/metrics/workflows")
async def api_system_metrics_workflows(time_range: str = "24h"):
    """Proxy to workflow metrics API"""
    try:
        response = await client.get(f"/system/metrics/workflows?time_range={time_range}")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch workflow metrics: {e}")
        return {"time_range": time_range, "total_workflows": 0, "by_status": {}}


@app.get("/api/system/metrics/tasks")
async def api_system_metrics_tasks(time_range: str = "24h"):
    """Proxy to task metrics API"""
    try:
        response = await client.get(f"/system/metrics/tasks?time_range={time_range}")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch task metrics: {e}")
        return {"time_range": time_range, "total_tasks": 0, "by_status": {}, "by_protocol": {}}


@app.get("/api/system/queues")
async def api_system_queues():
    """Proxy to system queues API"""
    try:
        response = await client.get("/system/queues")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch queue data: {e}")
        return {"queues": {}}


@app.get("/api/system/resources")
async def api_system_resources():
    """Proxy to system resources API"""
    try:
        response = await client.get("/system/resources")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch resource data: {e}")
        return {}


@app.post("/api/workflows/validate")
async def api_validate_workflow(request: Request):
    """Proxy to workflow validation API"""
    try:
        content_type = request.headers.get("content-type", "")
        body = await request.body()

        # Parse the body based on content type
        import yaml
        if "yaml" in content_type:
            workflow_def = yaml.safe_load(body.decode())
        else:
            workflow_def = json.loads(body.decode())

        # Forward to API as JSON
        response = await client.post(
            "/workflows/validate",
            json={"workflow": workflow_def}
        )

        return response.json()
    except Exception as e:
        logger.error(f"Failed to validate workflow: {e}")
        return JSONResponse(
            status_code=500,
            content={"valid": False, "errors": [str(e)]}
        )


@app.post("/api/workflows/submit")
async def api_submit_workflow(request: Request):
    """Proxy to workflow submission API"""
    try:
        content_type = request.headers.get("content-type", "")
        body = await request.body()

        # Parse the body based on content type
        import yaml
        import json as json_lib
        if "yaml" in content_type:
            workflow_def = yaml.safe_load(body.decode())
        else:
            workflow_def = json_lib.loads(body.decode())

        # Wrap in the expected format for the API
        payload = {
            "workflow": workflow_def
        }

        # Forward to API as JSON
        response = await client.post(
            "/workflows/submit",
            json=payload
        )

        return response.json()
    except Exception as e:
        logger.error(f"Failed to submit workflow: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.websocket("/ws/updates")
async def websocket_updates(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await manager.connect(websocket)

    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket connected successfully"
        })

        # Keep connection alive and listen for client messages
        while True:
            try:
                # Wait for messages from client (with timeout)
                data = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)

                # Handle ping/pong to keep connection alive
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

            except asyncio.TimeoutError:
                # Send periodic ping to keep connection alive
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


# WebSocket polling removed - UI now connects directly to API WebSocket at port 8000
