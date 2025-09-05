"""
Client-specific event models and types.
"""

from enum import Enum
from typing import Any, Dict, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

from gleitzeit.core.events import GleitzeitEvent, EventType


class ConnectionState(Enum):
    """WebSocket connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    CLOSED = "closed"


class ClientEvent(GleitzeitEvent):
    """
    Extended event model for client-side events.
    
    Adds client-specific fields while maintaining compatibility
    with server GleitzeitEvent.
    """
    
    # Client-specific fields
    client_id: Optional[str] = None
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None
    reply_to: Optional[str] = None
    ttl: Optional[int] = None  # Time to live in seconds
    priority: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)  # Add timestamp field
    
    @classmethod
    def from_server_event(cls, server_event: GleitzeitEvent, **kwargs) -> 'ClientEvent':
        """
        Create a ClientEvent from a server GleitzeitEvent.
        
        Args:
            server_event: Server event to convert
            **kwargs: Additional client-specific fields
            
        Returns:
            ClientEvent instance
        """
        event_dict = server_event.dict() if hasattr(server_event, 'dict') else {
            'event_type': server_event.event_type,
            'data': server_event.data,
            'source': getattr(server_event, 'source', None),
            'metadata': getattr(server_event, 'metadata', {})
        }
        
        return cls(**event_dict, **kwargs)
        
    def to_server_event(self) -> GleitzeitEvent:
        """
        Convert to a server GleitzeitEvent.
        
        Returns:
            GleitzeitEvent instance
        """
        # Store timestamp in data if needed
        data = self.data.copy()
        if 'timestamp' not in data:
            data['timestamp'] = self.timestamp.isoformat()
        
        return GleitzeitEvent(
            event_type=self.event_type,
            data=data,
            source=self.source,
            severity=getattr(self, 'severity', None),
            correlation_id=self.correlation_id,
            tags=getattr(self, 'tags', {})
        )


class WebSocketMessage(BaseModel):
    """WebSocket message format."""
    
    type: str  # 'event', 'subscribe', 'unsubscribe', 'ping', 'pong'
    event: Optional[ClientEvent] = None
    subscription: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    id: Optional[str] = None  # Message ID for request/response correlation
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EventSubscriptionRequest(BaseModel):
    """Request to subscribe to events."""
    
    event_types: List[str]  # Event types to subscribe to
    filters: Optional[Dict[str, Any]] = None  # Server-side filters
    client_id: Optional[str] = None
    session_id: Optional[str] = None


class EventFilter(BaseModel):
    """Client-side event filter configuration."""
    
    event_types: Optional[List[str]] = None  # None means all types
    workflow_id: Optional[str] = None
    task_id: Optional[str] = None
    min_priority: Optional[int] = None
    max_age_seconds: Optional[int] = None  # Ignore events older than this
    
    def matches(self, event: ClientEvent) -> bool:
        """
        Check if an event matches this filter.
        
        Args:
            event: Event to check
            
        Returns:
            True if event matches filter criteria
        """
        # Check event type
        if self.event_types and str(event.event_type) not in self.event_types:
            return False
            
        # Check workflow ID
        if self.workflow_id and event.data.get('workflow_id') != self.workflow_id:
            return False
            
        # Check task ID
        if self.task_id and event.data.get('task_id') != self.task_id:
            return False
            
        # Check priority
        if self.min_priority is not None and event.priority < self.min_priority:
            return False
            
        # Check age
        if self.max_age_seconds is not None:
            age = (datetime.utcnow() - event.timestamp).total_seconds()
            if age > self.max_age_seconds:
                return False
                
        return True


class ConnectionConfig(BaseModel):
    """WebSocket connection configuration."""
    
    url: str
    reconnect: bool = True
    reconnect_interval: float = 1.0
    reconnect_max_interval: float = 30.0
    reconnect_max_attempts: Optional[int] = None  # None = infinite
    ping_interval: float = 30.0
    ping_timeout: float = 10.0
    max_message_size: int = 1024 * 1024  # 1MB
    compression: bool = True
    
    # Authentication
    auth_token: Optional[str] = None
    auth_headers: Dict[str, str] = Field(default_factory=dict)
    
    # Client identification
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    client_version: Optional[str] = None


class EventStatistics(BaseModel):
    """Event statistics for monitoring."""
    
    events_received: int = 0
    events_processed: int = 0
    events_failed: int = 0
    events_filtered: int = 0
    
    handlers_registered: int = 0
    handlers_executed: int = 0
    handlers_failed: int = 0
    
    connection_state: ConnectionState = ConnectionState.DISCONNECTED
    connection_uptime_seconds: float = 0
    reconnection_count: int = 0
    
    last_event_time: Optional[datetime] = None
    last_error_time: Optional[datetime] = None
    last_error_message: Optional[str] = None
    
    avg_latency_ms: float = 0
    max_latency_ms: float = 0
    min_latency_ms: float = float('inf')
    
    queue_size: int = 0
    max_queue_size: int = 0
    
    def update_latency(self, latency_ms: float):
        """Update latency statistics."""
        self.avg_latency_ms = (
            (self.avg_latency_ms * self.events_processed + latency_ms) /
            (self.events_processed + 1)
        )
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)
        self.min_latency_ms = min(self.min_latency_ms, latency_ms)


class EventBatch(BaseModel):
    """Batch of events for efficient transmission."""
    
    events: List[ClientEvent]
    batch_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    compressed: bool = False
    checksum: Optional[str] = None
    
    def add_event(self, event: ClientEvent):
        """Add an event to the batch."""
        self.events.append(event)
        
    def size(self) -> int:
        """Get the number of events in the batch."""
        return len(self.events)
        
    def clear(self):
        """Clear all events from the batch."""
        self.events.clear()