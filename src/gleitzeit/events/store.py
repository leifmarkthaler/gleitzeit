"""Minimal event persistence layer for Gleitzeit."""

import logging
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import asdict
from ..core.events import GleitzeitEvent

logger = logging.getLogger(__name__)


class EventStore:
    """Minimal event persistence layer that works with any backend."""
    
    def __init__(self, persistence):
        """
        Initialize event store with a persistence backend.
        
        Args:
            persistence: Any persistence adapter (Redis, InMemory, SQL, etc.)
        """
        self.persistence = persistence
        
    async def save_event(self, event: GleitzeitEvent) -> str:
        """
        Persist an event to storage.
        
        Args:
            event: The event to persist
            
        Returns:
            Event ID for reference
        """
        try:
            event_id = f"evt_{uuid.uuid4().hex[:12]}"
            
            # Build event data
            event_data = {
                'event_id': event_id,
                'event_type': event.event_type,
                'timestamp': datetime.utcnow().isoformat(),
                'severity': event.severity.value if hasattr(event.severity, 'value') else str(event.severity),
                'source': event.source or 'unknown',
                'correlation_id': event.correlation_id,
                'tags': event.tags or {}
            }
            
            # Add event data if present
            if event.data:
                if hasattr(event.data, 'to_dict'):
                    event_data['data'] = event.data.to_dict()
                elif hasattr(event.data, '__dict__'):
                    try:
                        event_data['data'] = asdict(event.data)
                    except:
                        event_data['data'] = str(event.data)
                else:
                    event_data['data'] = event.data
            else:
                event_data['data'] = {}
            
            # Extract workflow/task context if available
            if event.data:
                if isinstance(event.data, dict):
                    if 'workflow_id' in event.data:
                        event_data['workflow_id'] = event.data['workflow_id']
                    if 'task_id' in event.data:
                        event_data['task_id'] = event.data['task_id']
                elif hasattr(event.data, 'workflow_id'):
                    event_data['workflow_id'] = event.data.workflow_id
                    if hasattr(event.data, 'task_id'):
                        event_data['task_id'] = event.data.task_id
            
            # Save to persistence backend
            if hasattr(self.persistence, 'save_event'):
                await self.persistence.save_event(event_data)
            else:
                logger.debug(f"Persistence backend {type(self.persistence).__name__} doesn't support event storage")
            
            return event_id
            
        except Exception as e:
            logger.warning(f"Failed to persist event {event.event_type}: {e}")
            return None
    
    async def get_events(self, 
                         workflow_id: Optional[str] = None,
                         task_id: Optional[str] = None,
                         event_type: Optional[str] = None,
                         since: Optional[datetime] = None,
                         until: Optional[datetime] = None,
                         limit: int = 1000) -> List[Dict[str, Any]]:
        """
        Retrieve events with filters.
        
        Args:
            workflow_id: Filter by workflow ID
            task_id: Filter by task ID
            event_type: Filter by event type
            since: Events after this time
            until: Events before this time
            limit: Maximum number of events to return
            
        Returns:
            List of event dictionaries
        """
        try:
            if hasattr(self.persistence, 'get_events'):
                return await self.persistence.get_events(
                    workflow_id=workflow_id,
                    task_id=task_id,
                    event_type=event_type,
                    since=since,
                    until=until,
                    limit=limit
                )
            else:
                logger.debug(f"Persistence backend {type(self.persistence).__name__} doesn't support event retrieval")
                return []
        except Exception as e:
            logger.warning(f"Failed to retrieve events: {e}")
            return []
    
    async def delete_old_events(self, days: int = 30) -> int:
        """
        Delete events older than specified days.
        
        Args:
            days: Number of days to retain
            
        Returns:
            Number of events deleted
        """
        try:
            if hasattr(self.persistence, 'delete_old_events'):
                return await self.persistence.delete_old_events(days)
            else:
                logger.debug(f"Persistence backend {type(self.persistence).__name__} doesn't support event deletion")
                return 0
        except Exception as e:
            logger.warning(f"Failed to delete old events: {e}")
            return 0