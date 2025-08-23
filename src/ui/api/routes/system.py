"""
System monitoring and status endpoints - proxies to Gleitzeit API
"""

from fastapi import APIRouter, Request, HTTPException
from typing import Dict, Any, List
import os
import aiohttp

# Try to import psutil, but make it optional
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    print("⚠️  psutil not installed - system metrics will be limited")
    PSUTIL_AVAILABLE = False

router = APIRouter()

# Get Gleitzeit API URL from environment or use default
GLEITZEIT_API_URL = os.getenv('GLEITZEIT_API_URL', 'http://localhost:8000')

@router.get("/status")
async def get_system_status(request: Request) -> Dict[str, Any]:
    """
    Get system status from Gleitzeit API
    
    Returns:
        System status including providers, resources, and metrics
    """
    async with aiohttp.ClientSession() as session:
        try:
            # Get status from API
            async with session.get(f"{GLEITZEIT_API_URL}/status") as resp:
                if resp.status == 200:
                    api_status = await resp.json()
                    
                    # Add local system metrics if psutil is available
                    local_metrics = {}
                    if PSUTIL_AVAILABLE:
                        try:
                            local_metrics = {
                                "cpu_percent": psutil.cpu_percent(interval=0.1),
                                "memory_percent": psutil.virtual_memory().percent,
                                "disk_percent": psutil.disk_usage('/').percent
                            }
                        except:
                            pass
                    
                    return {
                        **api_status,
                        "local_metrics": local_metrics
                    }
                else:
                    # API not available, return basic status
                    return {
                        "status": "degraded",
                        "message": "Gleitzeit API not available",
                        "providers": {},
                        "task_statistics": {}
                    }
        except aiohttp.ClientError as e:
            # API not reachable
            return {
                "status": "offline",
                "message": f"Cannot connect to Gleitzeit API: {e}",
                "providers": {},
                "task_statistics": {}
            }

@router.get("/resources")
async def get_resources_status(request: Request) -> Dict[str, Any]:
    """
    Get resource manager and hub status from API
    
    Returns:
        Resource manager status and hub information
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/resources") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {
                        "message": "Resource information not available",
                        "resource_manager": None,
                        "hubs": {}
                    }
        except aiohttp.ClientError as e:
            return {
                "message": f"Cannot get resource status: {e}",
                "resource_manager": None,
                "hubs": {}
            }

@router.get("/providers")
async def list_providers(request: Request) -> Dict[str, Any]:
    """
    List all registered providers from API
    
    Returns:
        List of providers with their capabilities
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/providers") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {"providers": []}
        except aiohttp.ClientError as e:
            return {"providers": [], "error": str(e)}

@router.get("/protocols")
async def list_protocols(request: Request) -> Dict[str, Any]:
    """
    List all registered protocols from API
    
    Returns:
        List of available protocols
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/protocols") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {"protocols": []}
        except aiohttp.ClientError as e:
            return {"protocols": [], "error": str(e)}

@router.get("/health")
async def health_check(request: Request) -> Dict[str, Any]:
    """
    Health check for UI and API connectivity
    
    Returns:
        Health status of UI and API
    """
    ui_healthy = True
    api_healthy = False
    api_message = ""
    
    # Check API health
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/health", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status == 200:
                    api_healthy = True
                    api_message = "API is healthy"
                else:
                    api_message = f"API returned status {resp.status}"
        except aiohttp.ClientError as e:
            api_message = f"Cannot connect to API: {e}"
        except Exception as e:
            api_message = f"API check failed: {e}"
    
    return {
        "ui_status": "healthy" if ui_healthy else "unhealthy",
        "api_status": "healthy" if api_healthy else "unhealthy",
        "api_message": api_message,
        "overall_status": "healthy" if (ui_healthy and api_healthy) else "degraded"
    }

@router.get("/metrics")
async def get_metrics(request: Request) -> Dict[str, Any]:
    """
    Get system metrics
    
    Returns:
        System resource utilization metrics
    """
    metrics = {
        "system": {},
        "gleitzeit": {}
    }
    
    # Get local system metrics if psutil is available
    if PSUTIL_AVAILABLE:
        try:
            cpu_freq = psutil.cpu_freq()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            metrics["system"] = {
                "cpu": {
                    "percent": psutil.cpu_percent(interval=0.1),
                    "count": psutil.cpu_count(),
                    "frequency": cpu_freq.current if cpu_freq else None
                },
                "memory": {
                    "percent": memory.percent,
                    "used_gb": memory.used / (1024**3),
                    "total_gb": memory.total / (1024**3)
                },
                "disk": {
                    "percent": disk.percent,
                    "used_gb": disk.used / (1024**3),
                    "total_gb": disk.total / (1024**3)
                }
            }
        except:
            pass
    
    # Try to get Gleitzeit metrics from API
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/status") as resp:
                if resp.status == 200:
                    status = await resp.json()
                    metrics["gleitzeit"] = {
                        "uptime_seconds": status.get("uptime_seconds", 0),
                        "task_statistics": status.get("task_statistics", {})
                    }
        except:
            pass
    
    return metrics