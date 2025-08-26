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
                            mem = psutil.virtual_memory()
                            local_metrics = {
                                "cpu_percent": psutil.cpu_percent(interval=0.1),
                                "memory_percent": mem.percent,
                                "disk_percent": psutil.disk_usage('/').percent
                            }
                        except:
                            pass
                    
                    # Check for ollama availability by looking at providers
                    ollama_available = False
                    providers_status = {}
                    
                    for provider_name, provider_info in api_status.get('providers', {}).items():
                        # Add each provider to the status
                        provider_type = provider_info.get('type', 'Unknown')
                        provider_status = provider_info.get('status', 'unknown')
                        provider_protocol = provider_info.get('protocol', '')
                        
                        providers_status[provider_name] = {
                            "type": provider_type,
                            "status": provider_status,
                            "protocol": provider_protocol,
                            "available": provider_status == 'healthy'
                        }
                        
                        # Check for ollama
                        if 'ollama' in provider_name.lower() or provider_info.get('is_ollama'):
                            ollama_available = provider_status == 'healthy'
                    
                    # Format response to match dashboard expectations
                    return {
                        **api_status,
                        "ollama": {
                            "available": ollama_available
                        },
                        "engine": {
                            "running": api_status.get('status') == 'running'
                        },
                        "providers_status": providers_status,
                        "resources": {
                            "cpu_percent": local_metrics.get('cpu_percent', 0),
                            "memory": {
                                "percent": local_metrics.get('memory_percent', 0)
                            }
                        },
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


# New System Monitoring Endpoints

@router.get("/queues")
async def list_queues(request: Request) -> Dict[str, Any]:
    """
    List all task queues and their statistics
    
    Returns:
        Queue information and statistics
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/queues") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {"total_queues": 0, "queues": {}}
        except aiohttp.ClientError as e:
            return {"total_queues": 0, "queues": {}, "error": str(e)}


@router.get("/queues/{queue_name}")
async def get_queue_details(request: Request, queue_name: str) -> Dict[str, Any]:
    """
    Get detailed statistics for a specific queue
    
    Args:
        queue_name: Name of the queue
    
    Returns:
        Queue details and statistics
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/queues/{queue_name}") as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail=f"Queue '{queue_name}' not found")
                else:
                    raise HTTPException(status_code=resp.status, detail="API error")
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")


@router.post("/queues/{queue_name}/pause")
async def pause_queue(request: Request, queue_name: str) -> Dict[str, Any]:
    """
    Pause a task queue
    
    Args:
        queue_name: Name of the queue to pause
    
    Returns:
        Pause result
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{GLEITZEIT_API_URL}/queues/{queue_name}/pause") as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail=f"Queue '{queue_name}' not found")
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error_text)
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")


@router.post("/queues/{queue_name}/resume")
async def resume_queue(request: Request, queue_name: str) -> Dict[str, Any]:
    """
    Resume a paused queue
    
    Args:
        queue_name: Name of the queue to resume
    
    Returns:
        Resume result
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{GLEITZEIT_API_URL}/queues/{queue_name}/resume") as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail=f"Queue '{queue_name}' not found")
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error_text)
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")


@router.post("/queues/{queue_name}/clear")
async def clear_queue(request: Request, queue_name: str) -> Dict[str, Any]:
    """
    Clear all pending tasks from a queue
    
    Args:
        queue_name: Name of the queue to clear
    
    Returns:
        Clear result
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{GLEITZEIT_API_URL}/queues/{queue_name}/clear") as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 404:
                    raise HTTPException(status_code=404, detail=f"Queue '{queue_name}' not found")
                else:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error_text)
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=503, detail=f"API connection error: {e}")


@router.get("/statistics/tasks")
async def get_task_statistics(request: Request) -> Dict[str, Any]:
    """
    Get task execution statistics
    
    Returns:
        Task statistics
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/statistics/tasks") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {
                        "total": 0,
                        "pending": 0,
                        "running": 0,
                        "completed": 0,
                        "failed": 0,
                        "cancelled": 0
                    }
        except aiohttp.ClientError as e:
            return {
                "total": 0,
                "pending": 0,
                "running": 0,
                "completed": 0,
                "failed": 0,
                "cancelled": 0,
                "error": str(e)
            }


@router.get("/statistics/system")
async def get_system_statistics(request: Request) -> Dict[str, Any]:
    """
    Get overall system statistics
    
    Returns:
        System statistics including uptime and queue info
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/statistics/system") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {"uptime_seconds": 0, "tasks": {}, "queues": {}}
        except aiohttp.ClientError as e:
            return {"uptime_seconds": 0, "tasks": {}, "queues": {}, "error": str(e)}


@router.get("/resources/limits")
async def get_resource_limits(request: Request) -> Dict[str, Any]:
    """
    Get current resource limits
    
    Returns:
        Resource limits configuration
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/resources/limits") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {
                        "max_concurrent_tasks": 5,
                        "max_memory_mb": 512,
                        "max_queue_size": 1000
                    }
        except aiohttp.ClientError as e:
            return {
                "max_concurrent_tasks": 5,
                "max_memory_mb": 512,
                "max_queue_size": 1000,
                "error": str(e)
            }


@router.get("/resources/usage")
async def get_resource_usage(request: Request) -> Dict[str, Any]:
    """
    Get current resource usage
    
    Returns:
        Current resource utilization
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{GLEITZEIT_API_URL}/resources/usage") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {
                        "active_tasks": 0,
                        "queued_tasks": 0,
                        "memory_usage_mb": 0
                    }
        except aiohttp.ClientError as e:
            return {
                "active_tasks": 0,
                "queued_tasks": 0,
                "memory_usage_mb": 0,
                "error": str(e)
            }