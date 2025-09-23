"""
Gleitzeit UI Application - Thin Client

Serves as a web interface to the Gleitzeit API server.
Uses HTMX for dynamic updates and server-side rendering.
"""

import os
import logging
from pathlib import Path
from typing import Optional
import httpx
import json

from fastapi import FastAPI, Request, HTTPException, Depends, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

logger = logging.getLogger(__name__)

# Configuration
API_BASE_URL = os.getenv("GLEITZEIT_API_URL", "http://localhost:8000")
UI_PORT = int(os.getenv("GLEITZEIT_UI_PORT", "8004"))

# FastAPI app
app = FastAPI(
    title="Gleitzeit UI",
    description="Web interface for Gleitzeit workflow orchestration",
    version="0.0.7"
)

# Setup static files and templates
ui_dir = Path(__file__).parent.parent
app.mount("/static", StaticFiles(directory=str(ui_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(ui_dir / "templates"))

# HTTP client for API calls
client = httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0)


# Session management
def get_session_id(request: Request) -> Optional[str]:
    """Get session ID from cookie or create new one"""
    return request.cookies.get("session_id")


async def ensure_session(request: Request) -> str:
    """Ensure user has a valid session"""
    session_id = get_session_id(request)

    if not session_id:
        # Create new session via API
        response = await client.post(
            "/auth/session/create",
            json={"username": "ui_user"}
        )
        if response.status_code == 200:
            data = response.json()
            session_id = data["session_id"]

    return session_id


# Template context
async def get_base_context(request: Request) -> dict:
    """Get base context for templates"""
    session_id = await ensure_session(request)

    return {
        "request": request,
        "api_url": API_BASE_URL,
        "session_id": session_id,
        "version": "0.0.7"
    }


# Routes
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Dashboard page"""
    context = await get_base_context(request)

    # Get system status
    session_id = context["session_id"]
    headers = {"X-Session-ID": session_id} if session_id else {}

    try:
        # Get metrics
        metrics_response = await client.get("/system/metrics", headers=headers)
        if metrics_response.status_code == 200:
            context["metrics"] = metrics_response.json()

        # Get system status
        status_response = await client.get("/system/status", headers=headers)
        if status_response.status_code == 200:
            context["status"] = status_response.json()
    except Exception as e:
        logger.error(f"Failed to get system info: {e}")
        context["metrics"] = None
        context["status"] = None

    return templates.TemplateResponse("index.html", context)


@app.get("/workflows", response_class=HTMLResponse)
async def workflows_list(request: Request):
    """Workflows list page"""
    context = await get_base_context(request)

    # TODO: Get workflows from API
    context["workflows"] = []

    return templates.TemplateResponse("workflows/list.html", context)


@app.get("/workflows/{workflow_id}", response_class=HTMLResponse)
async def workflow_detail(request: Request, workflow_id: str):
    """Workflow detail page"""
    context = await get_base_context(request)

    session_id = context["session_id"]
    headers = {"X-Session-ID": session_id} if session_id else {}

    try:
        # Get workflow details
        response = await client.get(f"/workflows/{workflow_id}", headers=headers)
        if response.status_code == 200:
            context["workflow"] = response.json()
        else:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Get workflow tasks
        tasks_response = await client.get(f"/workflows/{workflow_id}/tasks", headers=headers)
        if tasks_response.status_code == 200:
            context["tasks"] = tasks_response.json().get("tasks", [])
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return templates.TemplateResponse("workflows/detail.html", context)


@app.get("/tasks", response_class=HTMLResponse)
async def tasks_list(request: Request):
    """Tasks list page"""
    context = await get_base_context(request)

    # TODO: Get tasks from API
    context["tasks"] = []

    return templates.TemplateResponse("tasks/list.html", context)


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    """Task detail page"""
    context = await get_base_context(request)

    session_id = context["session_id"]
    headers = {"X-Session-ID": session_id} if session_id else {}

    try:
        response = await client.get(f"/tasks/{task_id}", headers=headers)
        if response.status_code == 200:
            context["task"] = response.json()
        else:
            raise HTTPException(status_code=404, detail="Task not found")
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=404, detail="Task not found")

    return templates.TemplateResponse("tasks/detail.html", context)


# API Proxy - forwards requests to the main API
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_api(request: Request, path: str):
    """Proxy API requests to the Gleitzeit API server"""

    session_id = get_session_id(request)
    headers = dict(request.headers)

    # Add session ID if available
    if session_id:
        headers["X-Session-ID"] = session_id

    # Remove host header to avoid conflicts
    headers.pop("host", None)

    # Forward the request
    try:
        if request.method == "GET":
            response = await client.get(f"/{path}", headers=headers, params=request.query_params)
        else:
            body = await request.body()
            response = await client.request(
                method=request.method,
                url=f"/{path}",
                headers=headers,
                content=body,
                params=request.query_params
            )

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers)
        )
    except Exception as e:
        logger.error(f"API proxy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# WebSocket proxy for real-time updates
@app.websocket("/ws/updates")
async def websocket_proxy(websocket):
    """WebSocket connection for real-time updates"""
    await websocket.accept()

    try:
        # TODO: Connect to API WebSocket and relay messages
        while True:
            data = await websocket.receive_text()
            # Echo for now
            await websocket.send_text(data)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()


# HTMX specific endpoints
@app.get("/htmx/metrics", response_class=HTMLResponse)
async def htmx_metrics(request: Request):
    """Get metrics fragment for HTMX updates"""
    context = await get_base_context(request)

    session_id = context["session_id"]
    headers = {"X-Session-ID": session_id} if session_id else {}

    try:
        response = await client.get("/system/metrics", headers=headers)
        if response.status_code == 200:
            context["metrics"] = response.json()
    except:
        context["metrics"] = None

    return templates.TemplateResponse("components/metrics.html", context)


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    await client.aclose()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=UI_PORT)