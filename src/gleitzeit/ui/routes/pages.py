"""
Page routes for new UI features
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import os
from pathlib import Path

# Get templates directory
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

router = APIRouter()

@router.get("/dashboard")
async def dashboard_redirect():
    """Redirect /dashboard to root / (main dashboard)"""
    return RedirectResponse(url="/", status_code=302)

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("auth/login.html", {
        "request": request
    })

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Registration page (placeholder)"""
    # For now, redirect to login
    return templates.TemplateResponse("auth/login.html", {
        "request": request
    })

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    """Forgot password page (placeholder)"""
    # For now, redirect to login
    return templates.TemplateResponse("auth/login.html", {
        "request": request
    })

@router.get("/queues", response_class=HTMLResponse)
async def queues_page(request: Request):
    """Queue management page"""
    return templates.TemplateResponse("queues/management.html", {
        "request": request
    })

@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """Log viewer page"""
    return templates.TemplateResponse("logs/viewer.html", {
        "request": request
    })

@router.get("/errors", response_class=HTMLResponse)
async def errors_page(request: Request):
    """Error dashboard page"""
    return templates.TemplateResponse("errors/dashboard.html", {
        "request": request
    })

@router.get("/bulk", response_class=HTMLResponse)
async def bulk_operations_page(request: Request):
    """Bulk operations page"""
    return templates.TemplateResponse("bulk/operations.html", {
        "request": request
    })