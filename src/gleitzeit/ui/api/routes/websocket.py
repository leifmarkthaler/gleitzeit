"""
WebSocket endpoint for real-time updates
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any, Set
import asyncio
import json
from datetime import datetime

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
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates
    
    Protocol:
    - Client sends: {"type": "subscribe", "channels": ["workflows", "tasks"]}
    - Server sends: {"type": "workflow_update", "data": {...}}
    """
    await manager.connect(websocket)
    
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                await handle_client_message(websocket, message)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON"
                })
            
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

# Background task to send periodic updates
async def periodic_updates():
    """Send periodic status updates to all connected clients"""
    while True:
        await asyncio.sleep(5)  # Send updates every 5 seconds
        
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