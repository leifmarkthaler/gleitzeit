"""
Event streaming WebSocket route for real-time event delivery.

This module provides WebSocket endpoints for streaming events from the
core EventBus to connected clients, enabling real-time updates without polling.
Uses dependency injection for stateless operation.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from typing import List, Dict, Any, Optional, Set
import asyncio
import json
import logging
from datetime import datetime
from uuid import uuid4

from gleitzeit.core.events import EventType, GleitzeitEvent
from gleitzeit.client.events import ClientEvent
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


class EventConnectionManager:
    """
    Manages WebSocket connections for event streaming.
    
    This manager bridges the server EventBus to WebSocket clients,
    providing real-time event delivery with subscription management.
    """
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Set[str]] = {}
        self.connection_handlers: Dict[str, List[str]] = {}  # connection_id -> handler_ids
        self.connection_clients: Dict[str, GleitzeitClient] = {}  # connection_id -> client
        
    async def connect(
        self, 
        websocket: WebSocket, 
        connection_id: str,
        client: GleitzeitClient
    ) -> str:
        """
        Accept and track a new WebSocket connection.
        
        Args:
            websocket: WebSocket connection
            connection_id: Unique connection identifier
            client: GleitzeitClient instance for this connection
            
        Returns:
            Connection ID
        """
        await websocket.accept()
        self.active_connections[connection_id] = websocket
        self.subscriptions[connection_id] = set()
        self.connection_handlers[connection_id] = []
        self.connection_clients[connection_id] = client
        
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connection",
            "status": "connected",
            "connection_id": connection_id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        logger.info(f"Event WebSocket connected: {connection_id}")
        return connection_id
        
    def disconnect(self, connection_id: str):
        """
        Remove a WebSocket connection and clean up handlers.
        
        Args:
            connection_id: Connection to remove
        """
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
            
        if connection_id in self.subscriptions:
            del self.subscriptions[connection_id]
            
        # Clean up event handlers
        if connection_id in self.connection_handlers:
            client = self.connection_clients.get(connection_id)
            if client and client.event_bus:
                for handler_id in self.connection_handlers[connection_id]:
                    try:
                        client.event_bus.unregister(handler_id)
                    except:
                        pass  # Handler might already be gone
            del self.connection_handlers[connection_id]
            
        # Remove client reference
        if connection_id in self.connection_clients:
            del self.connection_clients[connection_id]
            
        logger.info(f"Event WebSocket disconnected: {connection_id}")
        
    async def subscribe_to_events(self, 
                                 connection_id: str,
                                 event_types: List[str]) -> Dict[str, Any]:
        """
        Subscribe a connection to specific event types.
        
        Args:
            connection_id: Connection ID
            event_types: List of event type strings or patterns
            
        Returns:
            Subscription confirmation
        """
        if connection_id not in self.active_connections:
            return {"error": "Connection not found"}
            
        websocket = self.active_connections[connection_id]
        client = self.connection_clients.get(connection_id)
        
        if not client or not client.event_bus:
            return {"error": "Event system not available"}
            
        # Update subscription set
        self.subscriptions[connection_id].update(event_types)
        
        # Create handler for this connection
        async def forward_event(event: ClientEvent):
            """Forward event to WebSocket connection."""
            try:
                # Check if this event type matches subscriptions
                event_type_str = str(event.event_type.value if hasattr(event.event_type, 'value') else event.event_type)
                
                # Check for exact match or wildcard
                if '*' in self.subscriptions[connection_id] or \
                   event_type_str in self.subscriptions[connection_id] or \
                   any(event_type_str.startswith(pattern.rstrip('*')) 
                       for pattern in self.subscriptions[connection_id] if pattern.endswith('*')):
                    
                    # Send event to WebSocket
                    await websocket.send_json({
                        "type": "event",
                        "event": {
                            "event_type": event_type_str,
                            "data": event.data,
                            "timestamp": event.timestamp.isoformat() if hasattr(event, 'timestamp') else datetime.utcnow().isoformat(),
                            "source": getattr(event, 'source', None),
                            "correlation_id": getattr(event, 'correlation_id', None)
                        }
                    })
                    
            except Exception as e:
                logger.error(f"Error forwarding event to {connection_id}: {e}")
                
        # Register handlers for each event type
        for event_type_str in event_types:
            if event_type_str == '*':
                # Subscribe to all events
                handler_id = client.event_bus.register('*', forward_event)
            else:
                # Try to convert to EventType enum
                try:
                    event_type = EventType(event_type_str)
                    handler_id = client.event_bus.register(event_type, forward_event)
                except ValueError:
                    # Use as custom event type
                    handler_id = client.event_bus.register(event_type_str, forward_event)
                    
            self.connection_handlers[connection_id].append(handler_id)
            
        return {
            "type": "subscription",
            "subscribed": list(self.subscriptions[connection_id]),
            "status": "subscribed"
        }
        
    async def unsubscribe_from_events(self,
                                     connection_id: str,
                                     event_types: List[str]) -> Dict[str, Any]:
        """
        Unsubscribe a connection from specific event types.
        
        Args:
            connection_id: Connection ID
            event_types: Event types to unsubscribe from
            
        Returns:
            Unsubscription confirmation
        """
        if connection_id not in self.subscriptions:
            return {"error": "Connection not found"}
            
        # Remove from subscriptions
        for event_type in event_types:
            self.subscriptions[connection_id].discard(event_type)
            
        # Note: We don't remove handlers here as it's complex to track
        # which handler corresponds to which event type. They'll be
        # cleaned up on disconnect.
        
        return {
            "type": "subscription",
            "subscribed": list(self.subscriptions[connection_id]),
            "status": "unsubscribed"
        }
        
    async def send_to_connection(self,
                                connection_id: str,
                                message: Dict[str, Any]):
        """
        Send a message to a specific connection.
        
        Args:
            connection_id: Target connection
            message: Message to send
        """
        if connection_id in self.active_connections:
            websocket = self.active_connections[connection_id]
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to {connection_id}: {e}")
                self.disconnect(connection_id)


# Create singleton manager
event_manager = EventConnectionManager()


@router.websocket("/stream")
async def event_stream_endpoint(
    websocket: WebSocket,
    client_id: Optional[str] = Query(None),
    auto_subscribe: Optional[str] = Query(None)  # Comma-separated event types
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
    
    Note: Each WebSocket connection gets its own client from the pool
    """
    # Generate connection ID
    connection_id = client_id or str(uuid4())
    
    # Get a client from the pool for this connection
    client = None
    async for pooled_client in get_client():
        client = pooled_client
        break
    
    if not client:
        await websocket.close(code=1011, reason="No client available")
        return
    
    # Accept connection
    await event_manager.connect(websocket, connection_id, client)
    
    # Auto-subscribe if requested
    if auto_subscribe:
        event_types = [et.strip() for et in auto_subscribe.split(',')]
        result = await event_manager.subscribe_to_events(connection_id, event_types)
        await websocket.send_json(result)
    
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                await handle_event_message(connection_id, websocket, message)
                
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON"
                })
                
    except WebSocketDisconnect:
        event_manager.disconnect(connection_id)
    except Exception as e:
        logger.error(f"WebSocket error for {connection_id}: {e}")
        event_manager.disconnect(connection_id)


async def handle_event_message(
    connection_id: str,
    websocket: WebSocket,
    message: Dict[str, Any]
):
    """
    Handle incoming messages from event WebSocket clients.
    
    Args:
        connection_id: Connection identifier
        websocket: WebSocket connection
        message: Parsed message from client
    """
    msg_type = message.get("type")
    
    if msg_type == "subscribe":
        # Subscribe to event types
        event_types = message.get("event_types", [])
        result = await event_manager.subscribe_to_events(connection_id, event_types)
        await websocket.send_json(result)
        
    elif msg_type == "unsubscribe":
        # Unsubscribe from event types
        event_types = message.get("event_types", [])
        result = await event_manager.unsubscribe_from_events(connection_id, event_types)
        await websocket.send_json(result)
        
    elif msg_type == "ping":
        # Respond with pong
        await websocket.send_json({
            "type": "pong",
            "timestamp": datetime.utcnow().isoformat()
        })
        
    elif msg_type == "emit":
        # Allow clients to emit events (if authorized)
        event_data = message.get("event", {})
        client = event_manager.connection_clients.get(connection_id)
        
        if client and client.event_bus:
            # Create and emit event
            event = ClientEvent(
                event_type=event_data.get("event_type", "custom"),
                data=event_data.get("data", {}),
                client_id=connection_id
            )
            await client.emit_event(event)
            
            await websocket.send_json({
                "type": "emit_confirmation",
                "status": "emitted"
            })
        else:
            await websocket.send_json({
                "type": "error",
                "message": "Event system not available"
            })
            
    else:
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown message type: {msg_type}"
        })


@router.get("/types")
async def get_event_types():
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
    client: GleitzeitClient = Depends(get_client)
):
    """
    Get event system statistics.
    
    Returns:
        Event statistics and connection info
    """
    stats = {
        "connections": {
            "active": len(event_manager.active_connections),
            "connection_ids": list(event_manager.active_connections.keys())
        },
        "subscriptions": {
            conn_id: list(subs) 
            for conn_id, subs in event_manager.subscriptions.items()
        }
    }
    
    # Add client event statistics if available
    if client:
        client_stats = client.get_event_statistics()
        stats.update(client_stats)
    
    return stats