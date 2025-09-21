"""
Event streaming WebSocket route for real-time event delivery.

This module provides WebSocket endpoints for streaming events from the
core EventBus to connected clients, enabling real-time updates without polling.
Uses dependency injection for stateless operation.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends, HTTPException
from typing import List, Dict, Any, Optional, Set
import asyncio
import json
import logging
from datetime import datetime
from uuid import uuid4

from gleitzeit.core.events import EventType, GleitzeitEvent
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client, get_system_manager
from ..auth_dependencies import get_current_user_auto
from ..websocket_manager import ScalableWebSocketManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.websocket("/test")
async def test_websocket(websocket: WebSocket):
    """Minimal WebSocket endpoint for testing."""
    try:
        await websocket.accept()
        await websocket.send_text("Hello from WebSocket!")
        
        # Echo messages back
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
            if data == "close":
                break
                
    except WebSocketDisconnect:
        logger.info("Test WebSocket disconnected")
    except Exception as e:
        logger.error(f"Test WebSocket error: {e}")
        await websocket.close(code=1011)


# Note: EventConnectionManager class has been removed in favor of ScalableWebSocketManager
# The old class provided basic WebSocket management without security features.
# All WebSocket connections now use the secure ScalableWebSocketManager integrated with SystemManager.


@router.websocket("/stream")
async def event_stream_endpoint(
    websocket: WebSocket,
    client_id: Optional[str] = Query(None),
    auto_subscribe: Optional[str] = Query(None),  # Comma-separated event types
    token: Optional[str] = Query(None)  # Optional auth token for WebSocket
):
    """
    WebSocket endpoint for streaming events.
    
    Protocol:
    - Client connects with optional client_id
    - Server sends connection confirmation
    - Client sends: {"type": "subscribe", "event_types": ["task:*", "workflow:*"]}
    - Server streams matching events
    - Client sends: {"type": "ping"} for keepalive
    - Server sends: {"type": "pong"}
    
    Query Parameters:
        client_id: Optional client identifier
        auto_subscribe: Comma-separated event types to auto-subscribe
        token: Optional authentication token
    
    Note: Uses direct event bus connection for scalability
    """
    # Generate connection ID
    connection_id = client_id or str(uuid4())
    
    # Authenticate before accepting connection
    user = None
    auth_error = None
    
    # Get SystemManager for auth
    from ..dependencies import get_system_manager
    try:
        system_manager = await get_system_manager()
        
        if token and system_manager and system_manager.auth_manager:
            # Validate provided token
            try:
                user = await system_manager.auth_manager.validate_session(token)
                logger.info(f"WebSocket {connection_id} authenticated as {user.get('username')}")
            except Exception as e:
                auth_error = f"Invalid token: {str(e)}"
                logger.warning(f"WebSocket {connection_id} token validation failed: {e}")
        
        # If no token or validation failed, try auto-login as basic user
        if not user and system_manager and system_manager.auth_manager:
            try:
                _, user = await system_manager.auth_manager.get_or_create_basic_session()
                logger.info(f"WebSocket {connection_id} auto-logged in as basic user")
            except Exception as e:
                auth_error = f"Authentication required: {str(e)}"
                logger.error(f"WebSocket {connection_id} basic session creation failed: {e}")
                
    except Exception as e:
        auth_error = f"Authentication service unavailable: {str(e)}"
        logger.error(f"WebSocket {connection_id} auth setup failed: {e}")
    
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
    
    # Get WebSocket manager from SystemManager (required)
    client_ip = websocket.client.host if websocket.client else "unknown"
    
    if not system_manager or not hasattr(system_manager, 'websocket_manager'):
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "message": "WebSocket service unavailable",
            "code": 1011
        })
        await websocket.close(code=1011, reason="Service unavailable")
        return
    
    ws_manager: ScalableWebSocketManager = system_manager.websocket_manager
    
    # Use scalable manager for connection management
    connected = await ws_manager.connect(websocket, connection_id, client_ip, user)
    if not connected:
        return  # Connection rejected by manager
    
    # Track subscriptions for this connection
    subscriptions: Set[str] = set()
    handler_ids: List[str] = []
    
    # Get SystemManager for event bus access from dependency
    from ..dependencies import get_system_manager
    try:
        system_manager = await get_system_manager()
        event_bus = system_manager.event_bus if system_manager else None
    except Exception as e:
        logger.error(f"Failed to get event bus: {e}")
        event_bus = None
    
    # Helper function to subscribe to events
    async def subscribe_to_events(event_types: List[str]):
        """Subscribe this WebSocket to event types."""
        if not event_bus:
            return {"type": "error", "message": "Event system not available"}
        
        # Update subscription set
        subscriptions.update(event_types)
        
        # Create handler for this connection
        async def forward_event(event):
            """Forward event to WebSocket connection."""
            try:
                # Convert event to dict
                event_data = {
                    "event_type": str(getattr(event, 'event_type', 'unknown')),
                    "data": getattr(event, 'data', {}),
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                message = {
                    "type": "event",
                    "event": event_data
                }
                
                # Broadcast via manager (includes Redis PubSub for cross-instance)
                await ws_manager.send_to_connection(connection_id, message)
                # Also broadcast to other instances via Redis
                event_channel = str(getattr(event, 'event_type', 'unknown'))
                await ws_manager.broadcast(message, channel=event_channel)
            except Exception as e:
                logger.error(f"Error forwarding event: {e}")
        
        # Register handlers for each event type
        for event_type_str in event_types:
            try:
                if event_type_str == '*':
                    # Subscribe to all events
                    handler_id = event_bus.register('*', forward_event)
                else:
                    # Subscribe to specific event type
                    handler_id = event_bus.register(event_type_str, forward_event)
                
                handler_ids.append(handler_id)
            except Exception as e:
                logger.error(f"Failed to subscribe to {event_type_str}: {e}")
        
        return {
            "type": "subscription",
            "subscribed": list(subscriptions),
            "status": "subscribed"
        }
    
    # Auto-subscribe if requested
    if auto_subscribe:
        event_types = [et.strip() for et in auto_subscribe.split(',')]
        result = await subscribe_to_events(event_types)
        await websocket.send_json(result)
    
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_text()
            
            # Check rate limit
            if not ws_manager.check_rate_limit(connection_id):
                await websocket.send_json({
                    "type": "error",
                    "message": "Rate limit exceeded. Please slow down.",
                    "code": 1008
                })
                continue
            
            try:
                message = json.loads(data)
                msg_type = message.get("type")
                
                if msg_type == "subscribe":
                    # Subscribe to event types
                    event_types = message.get("event_types", [])
                    result = await subscribe_to_events(event_types)
                    await websocket.send_json(result)
                    
                elif msg_type == "ping":
                    # Update heartbeat
                    ws_manager.update_heartbeat(connection_id)
                    
                    # Respond with pong
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}"
                    })
                    
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON"
                })
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket {connection_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error for {connection_id}: {e}")
    finally:
        # Clean up WebSocket manager connection
        ws_manager.disconnect(connection_id)
        
        # Clean up event handlers
        if event_bus:
            for handler_id in handler_ids:
                try:
                    event_bus.unregister(handler_id)
                except:
                    pass  # Handler might already be gone
        
        # Close WebSocket if still open
        try:
            await websocket.close()
        except:
            pass


@router.get("/types")
async def get_event_types(
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """
    Get list of available event types.
    
    Returns:
        List of event type strings
    """
    # Get all EventType enum values
    event_types = [et.value for et in EventType]
    
    return {
        "event_types": event_types,
        "categories": {
            "task": [et for et in event_types if et.startswith("task:")],
            "workflow": [et for et in event_types if et.startswith("workflow:")],
            "provider": [et for et in event_types if et.startswith("provider:")],
            "engine": [et for et in event_types if et.startswith("engine:")],
            "client": [et for et in event_types if et.startswith("client:")],
            "retry": [et for et in event_types if "retry" in et],
        }
    }


@router.get("/stats")
async def get_event_statistics(
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """
    Get event system statistics.
    
    Returns:
        Event statistics and connection info
    """
    # Get WebSocket manager from SystemManager
    system_manager = await get_system_manager()
    ws_manager = system_manager.websocket_manager if system_manager else None
    
    stats = {
        "websocket_manager": {
            "active_connections": len(ws_manager.active_connections) if ws_manager else 0,
            "connections_per_ip": {ip: len(conns) for ip, conns in ws_manager.ip_connections.items()} if ws_manager else {},
            "max_connections": ws_manager.max_connections if ws_manager else 0,
            "max_connections_per_ip": ws_manager.max_connections_per_ip if ws_manager else 0,
            "heartbeat_interval": ws_manager.heartbeat_interval if ws_manager else 0,
            "redis_connected": ws_manager.redis_client is not None if ws_manager else False
        },
        "subscriptions": {
            conn_id: list(subs) 
            for conn_id, subs in ws_manager.subscriptions.items()
        } if ws_manager else {}
    }
    
    # Add client event statistics if available
    if client:
        client_stats = client.get_event_statistics()
        stats.update(client_stats)
    
    return stats