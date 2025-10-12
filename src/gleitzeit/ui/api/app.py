"""
Gleitzeit UI2 - Clean UI with WebSocket support
"""
import os
import uuid
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional, Set

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
    """Disable caching for all HTML and API responses"""
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")

    # Add no-cache headers to HTML and API JSON responses
    if "text/html" in content_type or (request.url.path.startswith("/api/") and "application/json" in content_type):
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


@app.get("/")
async def index(request: Request):
    """Home page - redirect to submit"""
    return RedirectResponse(url="/submit", status_code=302)


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


@app.get("/metrics")
async def metrics_redirect(request: Request):
    """Redirect to system page (handlers)"""
    return RedirectResponse(url="/handlers", status_code=302)


@app.get("/processes")
async def processes_redirect(request: Request):
    """Redirect to system page (handlers)"""
    return RedirectResponse(url="/handlers", status_code=302)


@app.get("/handlers", response_class=HTMLResponse)
async def handlers_list(request: Request):
    """System health page (handlers + processes)"""
    context = await get_base_context(request)

    # Get running Gleitzeit processes
    import psutil
    import os

    processes = []
    current_pid = os.getpid()

    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_info', 'create_time']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if not cmdline:
                continue

            cmdline_str = ' '.join(cmdline)

            # Check if this is a Gleitzeit process
            if 'gleitzeit' in cmdline_str.lower():
                process_type = "unknown"
                process_name = "Gleitzeit Process"
                port = None

                # Determine process type
                if 'uvicorn' in cmdline_str and 'ui.api.app' in cmdline_str:
                    process_type = "ui_server"
                    process_name = "UI Server"
                    port = 8004
                elif 'uvicorn' in cmdline_str and 'api.main' in cmdline_str:
                    process_type = "api_server"
                    process_name = "API Server"
                    port = 8000
                elif 'workers.runner' in cmdline_str:
                    # Extract worker type from config key
                    for part in cmdline:
                        if 'worker:config:' in part:
                            worker_type = part.split(':')[2].split('-')[0]
                            process_type = f"worker_{worker_type}"
                            process_name = f"{worker_type.replace('_', ' ').title()} Worker"
                            break

                # Calculate uptime
                import time
                uptime_seconds = int(time.time() - proc.info['create_time'])

                # Get memory in MB
                memory_mb = proc.info['memory_info'].rss / 1024 / 1024

                processes.append({
                    'pid': proc.info['pid'],
                    'type': process_type,
                    'name': process_name,
                    'cpu_percent': proc.info.get('cpu_percent', 0),
                    'memory_mb': memory_mb,
                    'uptime_seconds': uptime_seconds,
                    'port': port,
                    'is_current': proc.info['pid'] == current_pid
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    # Sort by process type and name
    processes.sort(key=lambda p: (p['type'], p['name']))

    context['processes'] = processes
    context['total_memory'] = sum(p['memory_mb'] for p in processes)
    context['process_count'] = len(processes)

    # Fetch metrics and system status from API
    try:
        # Get metrics (workflow/task counts)
        metrics_response = await client.get("/system/metrics")
        context["metrics"] = metrics_response.json()
    except Exception as e:
        logger.warning(f"Failed to fetch metrics: {e}")
        context["metrics"] = None

    try:
        # Get system status (workers and queues)
        status_response = await client.get("/system/status")
        status_data = status_response.json()

        # Get worker registry for additional info
        workers_response = await client.get("/system/workers")
        workers_data = workers_response.json()

        # Merge worker metrics with registry data
        workers_enriched = {}
        for worker in workers_data.get("workers", []):
            worker_id = worker.get("worker_id")
            if worker_id:
                # Start with registry data
                workers_enriched[worker_id] = worker.copy()

                # Merge in metrics from status
                if worker_id in status_data.get("workers", {}):
                    metrics = status_data["workers"][worker_id]
                    workers_enriched[worker_id].update({
                        "tasks_processed": int(metrics.get("processed", "0")),
                        "errors": int(metrics.get("failed", "0")),
                        "last_heartbeat": metrics.get("last_heartbeat"),
                        "memory_mb": float(metrics.get("memory_mb", "0")),
                        "cpu_percent": float(metrics.get("cpu_percent", "0"))
                    })

                # Determine health status based on last heartbeat
                last_hb = workers_enriched[worker_id].get("last_heartbeat")
                if last_hb:
                    from datetime import datetime, timezone
                    try:
                        # Parse the ISO timestamp
                        if last_hb.endswith('Z'):
                            hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
                        else:
                            hb_time = datetime.fromisoformat(last_hb)

                        # Make timezone-aware if needed
                        if hb_time.tzinfo is None:
                            hb_time = hb_time.replace(tzinfo=timezone.utc)

                        # Calculate age
                        now = datetime.now(timezone.utc)
                        age = (now - hb_time).total_seconds()

                        if age < 30:
                            workers_enriched[worker_id]["status"] = "healthy"
                        elif age < 60:
                            workers_enriched[worker_id]["status"] = "degraded"
                        else:
                            workers_enriched[worker_id]["status"] = "unhealthy"
                    except Exception as e:
                        logger.warning(f"Failed to parse heartbeat time for {worker_id}: {e}")
                        workers_enriched[worker_id]["status"] = "unknown"

        context["workers"] = workers_enriched
        context["queues"] = status_data.get("queues", {})
        context["orchestrator"] = status_data.get("orchestrator", {})

    except Exception as e:
        logger.error(f"Failed to fetch system status: {e}")
        context["workers"] = {}
        context["queues"] = {}

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

    # Extract tasks if available and enrich with execution state
    tasks = []
    logger.info(f"Workflow data keys: {workflow_data.keys()}")
    if "data" in workflow_data:
        logger.info(f"Data keys: {workflow_data['data'].keys()}")
        if "workflow" in workflow_data["data"]:
            logger.info(f"Workflow keys: {workflow_data['data']['workflow'].keys()}")
            if "tasks" in workflow_data["data"]["workflow"]:
                task_definitions = workflow_data["data"]["workflow"]["tasks"]
                logger.info(f"Found {len(task_definitions)} task definitions")

                # Fetch execution state for each task
                for task_def in task_definitions:
                    task_id = task_def.get("id")
                    try:
                        # Fetch task execution state from API
                        task_response = await client.get(f"/tasks/{task_id}")
                        task_data = task_response.json()

                        # Merge definition with execution state
                        enriched_task = {**task_def}
                        if "state" in task_data:
                            enriched_task["status"] = task_data["state"].get("status", "pending")
                        else:
                            enriched_task["status"] = "pending"

                        tasks.append(enriched_task)
                    except Exception as task_error:
                        # If we can't fetch state, just use the definition with pending status
                        logger.warning(f"Failed to fetch state for task {task_id}: {task_error}")
                        enriched_task = {**task_def, "status": "pending"}
                        tasks.append(enriched_task)

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

        # Enrich task data with workflow information
        workflow_id = task_data.get("workflow_id")
        if workflow_id:
            try:
                wf_response = await client.get(f"/workflows/{workflow_id}")
                wf_data = wf_response.json()

                # Find task definition in workflow
                workflow_def = wf_data.get("data", {}).get("workflow", {})
                for task_def in workflow_def.get("tasks", []):
                    if task_def.get("id") == task_id:
                        # Add protocol/type and created_at from workflow
                        task_data["task_type"] = task_def.get("protocol", "unknown").split("/")[0]
                        task_data["created_at"] = workflow_def.get("created_at")
                        task_data["protocol"] = task_def.get("protocol")
                        break
            except Exception as e:
                logger.warning(f"Failed to enrich task with workflow data: {e}")

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
        api_response = await client.get(f"/tasks/list?limit={limit}")
        data = api_response.json()
        task_ids = data.get("task_ids", [])

        # Fetch full details for each task
        tasks = []
        workflows_cache = {}  # Cache workflow data to reduce API calls

        for task_id in task_ids[:limit]:  # Limit to requested number
            try:
                task_response = await client.get(f"/tasks/{task_id}")
                task_data = task_response.json()
                if task_data and "error" not in task_data and "detail" not in task_data:
                    # Enrich with task type from workflow
                    workflow_id = task_data.get("workflow_id")
                    if workflow_id:
                        # Check cache first
                        if workflow_id not in workflows_cache:
                            try:
                                wf_response = await client.get(f"/workflows/{workflow_id}")
                                workflows_cache[workflow_id] = wf_response.json()
                            except Exception:
                                workflows_cache[workflow_id] = None

                        # Extract task type from workflow
                        wf_data = workflows_cache.get(workflow_id)
                        if wf_data:
                            workflow_def = wf_data.get("data", {}).get("workflow", {})
                            for task_def in workflow_def.get("tasks", []):
                                if task_def.get("id") == task_id:
                                    protocol = task_def.get("protocol", "unknown")
                                    task_data["task_type"] = protocol.split("/")[0]
                                    break

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


@app.get("/api/tasks/{task_id}/logs")
async def api_task_logs(task_id: str):
    """Proxy to task logs API"""
    try:
        response = await client.get(f"/tasks/{task_id}/logs")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch task logs: {e}")
        return {"task_id": task_id, "logs": []}


@app.get("/api/tasks/{task_id}/events")
async def api_task_events(task_id: str):
    """Proxy to task events API"""
    try:
        response = await client.get(f"/tasks/{task_id}/events")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch task events: {e}")
        return {"task_id": task_id, "events": []}


@app.get("/api/workflows/{workflow_id}/events")
async def api_workflow_events(workflow_id: str):
    """Proxy to workflow events API"""
    try:
        response = await client.get(f"/workflows/{workflow_id}/events")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch workflow events: {e}")
        return {"workflow_id": workflow_id, "events": []}


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


@app.post("/api/workflows/{workflow_id}/cancel")
async def api_cancel_workflow(workflow_id: str):
    """Proxy to workflow cancellation API"""
    try:
        response = await client.post(f"/workflows/{workflow_id}/cancel")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to cancel workflow: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.delete("/api/workflows/{workflow_id}")
async def api_delete_workflow(workflow_id: str):
    """Proxy to workflow deletion API"""
    try:
        response = await client.delete(f"/workflows/{workflow_id}")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to delete workflow: {e}")
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
