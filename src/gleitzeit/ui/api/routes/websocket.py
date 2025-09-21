"""
WebSocket endpoint for real-time updates
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from typing import List, Dict, Any, Set, Optional
import asyncio
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter()

class ConnectionManager:
    """
    Manages WebSocket connections and broadcasts updates
    """
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
    
    async def connect(self, websocket: WebSocket):
        """Accept and track a new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()
        
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connection",
            "status": "connected",
            "timestamp": datetime.now().isoformat()
        })
    
    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]
    
    async def subscribe(self, websocket: WebSocket, channels: List[str]):
        """Subscribe a connection to specific channels"""
        if websocket in self.subscriptions:
            self.subscriptions[websocket].update(channels)
            
            await websocket.send_json({
                "type": "subscription",
                "channels": list(self.subscriptions[websocket]),
                "status": "subscribed"
            })
    
    async def unsubscribe(self, websocket: WebSocket, channels: List[str]):
        """Unsubscribe a connection from specific channels"""
        if websocket in self.subscriptions:
            for channel in channels:
                self.subscriptions[websocket].discard(channel)
            
            await websocket.send_json({
                "type": "subscription",
                "channels": list(self.subscriptions[websocket]),
                "status": "unsubscribed"
            })
    
    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket):
        """Send a message to a specific connection"""
        try:
            await websocket.send_json(message)
        except:
            # Connection might be closed
            self.disconnect(websocket)
    
    async def broadcast(self, message: Dict[str, Any], channel: str = None):
        """
        Broadcast a message to all connected clients
        
        Args:
            message: Message to broadcast
            channel: Optional channel to filter subscribers
        """
        # Add timestamp if not present
        if "timestamp" not in message:
            message["timestamp"] = datetime.now().isoformat()
        
        disconnected = []
        
        for connection in self.active_connections:
            # Check if connection is subscribed to the channel
            if channel:
                if channel not in self.subscriptions.get(connection, set()):
                    continue
            
            try:
                await connection.send_json(message)
            except:
                # Mark for disconnection
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

# Create a singleton manager
manager = ConnectionManager()

@router.websocket("/ws/updates")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None)  # Optional auth token for WebSocket
):
    """
    WebSocket endpoint for real-time updates
    
    Protocol:
    - Client sends: {"type": "subscribe", "channels": ["workflows", "tasks"]}
    - Server sends: {"type": "workflow_update", "data": {...}}
    
    Query Parameters:
        token: Optional authentication token (uses basic user if not provided)
    """
    # Authenticate before accepting connection
    user = None
    auth_error = None
    
    # Get SystemManager using the same dependency as REST endpoints
    from gleitzeit.api.dependencies import get_system_manager
    try:
        system_manager = await get_system_manager()
        
        if token and system_manager and system_manager.auth_manager:
            # Validate provided token
            try:
                user = await system_manager.auth_manager.validate_session(token)
                logger.info(f"UI WebSocket authenticated as {user.get('username')}")
            except Exception as e:
                auth_error = f"Invalid token: {str(e)}"
                logger.warning(f"UI WebSocket token validation failed: {e}")
        
        # If no token or validation failed, try auto-login as basic user
        if not user and system_manager and system_manager.auth_manager:
            try:
                _, user = await system_manager.auth_manager.get_or_create_basic_session()
                logger.info(f"UI WebSocket auto-logged in as basic user")
            except Exception as e:
                auth_error = f"Authentication required: {str(e)}"
                logger.error(f"UI WebSocket basic session creation failed: {e}")
                
    except Exception as e:
        auth_error = f"Authentication service unavailable: {str(e)}"
        logger.error(f"UI WebSocket auth setup failed: {e}")
    
    # If authentication failed completely, reject connection
    if not user:
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "message": auth_error or "Authentication required",
            "code": 1008
        })
        await websocket.close(code=1008, reason="Authentication required")
        return
    
    await manager.connect(websocket)
    
    # Send user info if authenticated
    if user:
        await websocket.send_json({
            "type": "auth",
            "user": {
                "id": user.get('id'),
                "username": user.get('username'),
                "role": user.get('role')
            }
        })
    
    try:
        # Handle incoming messages from client
        # NOTE: Changed from while loop to event-driven message handling
        async for message_data in websocket.iter_text():
            try:
                message = json.loads(message_data)
                await handle_client_message(websocket, message)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON"
                })
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                break

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        manager.disconnect(websocket)
        logger.error(f"WebSocket error: {e}")

async def handle_client_message(websocket: WebSocket, message: Dict[str, Any]):
    """
    Handle incoming messages from WebSocket clients
    
    Args:
        websocket: The WebSocket connection
        message: Parsed message from client
    """
    msg_type = message.get("type")
    
    if msg_type == "subscribe":
        channels = message.get("channels", [])
        await manager.subscribe(websocket, channels)
    
    elif msg_type == "unsubscribe":
        channels = message.get("channels", [])
        await manager.unsubscribe(websocket, channels)
    
    elif msg_type == "ping":
        await websocket.send_json({
            "type": "pong",
            "timestamp": datetime.now().isoformat()
        })
    
    elif msg_type == "get_status":
        # Send current status
        await send_status_update(websocket)
    
    else:
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown message type: {msg_type}"
        })

async def send_status_update(websocket: WebSocket):
    """Send current status to a specific client"""
    from .tasks import _ui_tasks
    from .workflows import _ui_workflows
    
    status = {
        "type": "status_update",
        "data": {
            "workflows": {
                "total": len(_ui_workflows),
                "running": len([w for w in _ui_workflows.values() if w.get("status") == "running"]),
                "completed": len([w for w in _ui_workflows.values() if w.get("status") == "completed"]),
                "failed": len([w for w in _ui_workflows.values() if w.get("status") == "failed"])
            },
            "tasks": {
                "total": len(_ui_tasks),
                "running": len([t for t in _ui_tasks.values() if t.get("status") == "running"]),
                "pending": len([t for t in _ui_tasks.values() if t.get("status") == "pending"]),
                "completed": len([t for t in _ui_tasks.values() if t.get("status") == "completed"]),
                "failed": len([t for t in _ui_tasks.values() if t.get("status") == "failed"])
            }
        }
    }
    
    await manager.send_personal_message(status, websocket)

# NOTE: Periodic updates now handled by Redis event scheduler
# No more background tasks with while loops - event-driven only

async def send_metrics_update():
    """Send metrics update to all connected clients (called by scheduler)"""
    # Get current stats
    from .tasks import _ui_tasks
    from .workflows import _ui_workflows

    # Send metrics update
    metrics_update = {
        "type": "metrics_update",
        "data": {
            "active_workflows": len([w for w in _ui_workflows.values() if w.get("status") == "running"]),
            "running_tasks": len([t for t in _ui_tasks.values() if t.get("status") == "running"]),
            "queue_size": len([t for t in _ui_tasks.values() if t.get("status") == "pending"])
        }
    }

    await manager.broadcast(metrics_update, "metrics")

# Helper functions for other routes to send updates
async def notify_workflow_update(workflow_id: str, status: str, data: Dict[str, Any] = None):
    """Send workflow update notification"""
    update = {
        "type": "workflow_update",
        "data": {
            "id": workflow_id,
            "status": status,
            **(data or {})
        }
    }
    await manager.broadcast(update, "workflows")

async def notify_task_update(task_id: str, status: str, data: Dict[str, Any] = None):
    """Send task update notification"""
    update = {
        "type": "task_update",
        "data": {
            "id": task_id,
            "status": status,
            **(data or {})
        }
    }
    await manager.broadcast(update, "tasks")

async def notify_system_event(event_type: str, data: Dict[str, Any]):
    """Send system event notification"""
    update = {
        "type": "system_event",
        "event": event_type,
        "data": data
    }
    await manager.broadcast(update, "system")

async def notify_log_event(log_entry: Dict[str, Any]):
    """Send log event notification"""
    update = {
        "type": "log_event", 
        "data": log_entry
    }
    await manager.broadcast(update, "logs")

async def notify_real_time_log(log_data: Dict[str, Any]):
    """Send real-time log update"""
    update = {
        "type": "real_time_log",
        "data": {
            "timestamp": log_data.get("timestamp", datetime.now().isoformat()),
            "level": log_data.get("level", "INFO"),
            "source": log_data.get("source", "system"),
            "message": log_data.get("message", ""),
            "context": log_data.get("context", {})
        }
    }
    await manager.broadcast(update, "logs")