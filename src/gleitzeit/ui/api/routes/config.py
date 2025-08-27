"""
Configuration and feature detection endpoints
"""

from fastapi import APIRouter, Request
from typing import Dict, Any
import os
import aiohttp

router = APIRouter()

# Get Gleitzeit API URL from environment or use default
GLEITZEIT_API_URL = os.getenv('GLEITZEIT_API_URL', 'http://localhost:8000')

@router.get("/features")
async def get_enabled_features(request: Request) -> Dict[str, Any]:
    """
    Check which features are enabled in the Gleitzeit API
    
    Returns:
        Dictionary of feature flags
    """
    features = {
        "auth": False,
        "queues": True,
        "logs": True,
        "errors": True,
        "providers": True,
        "templates": True,
        "bulk_operations": True
    }
    
    async with aiohttp.ClientSession() as session:
        # Check if auth is enabled by trying to access auth endpoints
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/auth/status") as resp:
                features["auth"] = resp.status != 404
        except:
            features["auth"] = False
        
        # Check for other optional features
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/queues") as resp:
                features["queues"] = resp.status != 404
        except:
            pass
            
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/logs/stats") as resp:
                features["logs"] = resp.status != 404
        except:
            pass
    
    return features

@router.get("/auth/status")
async def check_auth_status(request: Request) -> Dict[str, Any]:
    """
    Check authentication mode and configuration
    
    Returns:
        Auth mode and configuration
    """
    auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
    
    # Auth is always enabled now, but mode determines behavior
    return {
        "enabled": True,  # Always true for data isolation
        "mode": auth_mode,
        "requires_login": auth_mode != "basic",
        "message": "Basic mode - no login required" if auth_mode == "basic" else "Admin mode - login required",
        "config": {
            "mode": auth_mode,
            "basic_user": "basic@localhost" if auth_mode == "basic" else None
        }
    }

@router.get("/config")
async def get_ui_config(request: Request) -> Dict[str, Any]:
    """
    Get UI configuration including feature flags and API settings
    
    Returns:
        UI configuration
    """
    # Check environment variables for configuration
    auth_enabled = os.getenv('GLEITZEIT_AUTH_ENABLED', 'false').lower() == 'true'
    
    # Get features
    features = await get_enabled_features(request)
    
    return {
        "api_url": GLEITZEIT_API_URL,
        "auth_enabled": features.get("auth", False),
        "features": features,
        "ui_version": "0.1.0",
        "environment": {
            "auth_configured": auth_enabled,
            "api_url": GLEITZEIT_API_URL
        }
    }