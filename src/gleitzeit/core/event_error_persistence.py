"""
Event Error Persistence for Nachvollziehbarkeit (Traceability)

Saves event handler errors to unified persistence for debugging and audit trails.
"""

import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter

logger = logging.getLogger(__name__)


@dataclass
class PersistedEventError:
    """Event error record for persistence."""
    id: str
    handler_name: str
    event_type: str
    event_id: Optional[str]
    error_type: str
    error_message: str
    error_traceback: Optional[str]
    timestamp: datetime
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        data = asdict(self)
        # Convert datetime to ISO format
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PersistedEventError':
        """Create from stored dictionary."""
        # Convert ISO string back to datetime
        if isinstance(data['timestamp'], str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


class EventErrorPersistence:
    """
    Manages persistence of event handler errors.
    
    Uses the unified persistence adapter to store errors in Redis, SQL, or memory
    depending on the system configuration.
    """
    
    def __init__(
        self,
        persistence: Optional[UnifiedPersistenceAdapter] = None,
        retention_days: int = 30,
        key_prefix: str = "event_errors"
    ):
        """
        Initialize event error persistence.
        
        Args:
            persistence: Unified persistence adapter (Redis/SQL/Memory)
            retention_days: How many days to keep errors
            key_prefix: Prefix for storage keys
        """
        self.persistence = persistence
        self.retention_days = retention_days
        self.key_prefix = key_prefix
        self._initialized = False
        
        # In-memory fallback if no persistence available
        self._memory_store: List[PersistedEventError] = []
        self._max_memory_errors = 1000
    
    async def initialize(self) -> None:
        """Initialize the error persistence."""
        if self.persistence:
            try:
                await self.persistence.initialize()
                self._initialized = True
                logger.info("Event error persistence initialized with unified backend")
            except Exception as e:
                logger.warning(f"Failed to initialize persistence, using memory fallback: {e}")
                self._initialized = False
        else:
            logger.info("Event error persistence using in-memory storage")
            self._initialized = False
    
    async def save_error(
        self,
        handler_name: str,
        event_type: str,
        error: Exception,
        event_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Save an event handler error to persistence.
        
        Args:
            handler_name: Name of the handler that failed
            event_type: Type of event being handled
            error: The exception that occurred
            event_id: Optional event ID
            metadata: Additional context
            
        Returns:
            Error ID for reference
        """
        import uuid
        import traceback
        
        error_id = str(uuid.uuid4())
        
        # Capture full traceback if available
        error_traceback = None
        try:
            if hasattr(error, '__traceback__'):
                error_traceback = ''.join(traceback.format_tb(error.__traceback__))
        except Exception:
            pass
        
        # Create error record
        error_record = PersistedEventError(
            id=error_id,
            handler_name=handler_name,
            event_type=event_type,
            event_id=event_id,
            error_type=type(error).__name__,
            error_message=str(error),
            error_traceback=error_traceback,
            timestamp=datetime.utcnow(),
            metadata=metadata
        )
        
        # Try to save to persistence
        if self._initialized and self.persistence:
            try:
                # Store as a task-like record in persistence
                # We'll use the queue_state storage which accepts arbitrary dicts
                storage_key = f"{self.key_prefix}:{error_id}"
                await self.persistence.save_queue_state(
                    storage_key,
                    error_record.to_dict()
                )
                
                # Also maintain an index of error IDs for querying
                index_key = f"{self.key_prefix}:index"
                existing_index = await self.persistence.get_queue_state(index_key)
                
                if existing_index:
                    error_ids = existing_index.get('error_ids', [])
                else:
                    error_ids = []
                
                # Add new error and trim old ones
                error_ids.append({
                    'id': error_id,
                    'timestamp': error_record.timestamp.isoformat(),
                    'event_type': event_type
                })
                
                # Keep only errors within retention period
                cutoff = (datetime.utcnow() - timedelta(days=self.retention_days)).isoformat()
                error_ids = [e for e in error_ids if e['timestamp'] > cutoff]
                
                # Save updated index
                await self.persistence.save_queue_state(
                    index_key,
                    {'error_ids': error_ids, 'updated_at': datetime.utcnow().isoformat()}
                )
                
                logger.debug(f"Saved event error {error_id} to persistence")
                
            except Exception as e:
                logger.error(f"Failed to persist event error: {e}")
                # Fall through to memory storage
        
        # Always save to memory as well (for immediate access)
        self._memory_store.append(error_record)
        
        # Trim memory storage
        if len(self._memory_store) > self._max_memory_errors:
            self._memory_store = self._memory_store[-self._max_memory_errors:]
        
        return error_id
    
    async def get_error(self, error_id: str) -> Optional[PersistedEventError]:
        """
        Retrieve a specific error by ID.
        
        Args:
            error_id: The error ID to retrieve
            
        Returns:
            The error record or None if not found
        """
        # Check memory first
        for error in self._memory_store:
            if error.id == error_id:
                return error
        
        # Try persistence
        if self._initialized and self.persistence:
            try:
                storage_key = f"{self.key_prefix}:{error_id}"
                data = await self.persistence.get_queue_state(storage_key)
                if data:
                    return PersistedEventError.from_dict(data)
            except Exception as e:
                logger.error(f"Failed to retrieve error from persistence: {e}")
        
        return None
    
    async def get_recent_errors(
        self,
        limit: int = 100,
        event_type: Optional[str] = None
    ) -> List[PersistedEventError]:
        """
        Get recent errors.
        
        Args:
            limit: Maximum number of errors to return
            event_type: Filter by event type (optional)
            
        Returns:
            List of error records (most recent first)
        """
        errors = []
        
        # Get from memory
        memory_errors = list(reversed(self._memory_store))
        if event_type:
            memory_errors = [e for e in memory_errors if e.event_type == event_type]
        errors.extend(memory_errors[:limit])
        
        # If we need more and have persistence
        if len(errors) < limit and self._initialized and self.persistence:
            try:
                # Get error index
                index_key = f"{self.key_prefix}:index"
                index_data = await self.persistence.get_queue_state(index_key)
                
                if index_data and 'error_ids' in index_data:
                    error_ids = index_data['error_ids']
                    
                    # Filter by event type if specified
                    if event_type:
                        error_ids = [e for e in error_ids if e.get('event_type') == event_type]
                    
                    # Get most recent errors
                    recent_ids = list(reversed(error_ids))[:limit]
                    
                    # Load each error
                    for error_info in recent_ids:
                        if len(errors) >= limit:
                            break
                        
                        error_id = error_info['id']
                        # Skip if already in memory results
                        if any(e.id == error_id for e in errors):
                            continue
                        
                        storage_key = f"{self.key_prefix}:{error_id}"
                        data = await self.persistence.get_queue_state(storage_key)
                        if data:
                            errors.append(PersistedEventError.from_dict(data))
                            
            except Exception as e:
                logger.error(f"Failed to retrieve errors from persistence: {e}")
        
        return errors[:limit]
    
    async def cleanup_old_errors(self) -> int:
        """
        Remove errors older than retention period.
        
        Returns:
            Number of errors removed
        """
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)
        removed = 0
        
        # Clean memory store
        before = len(self._memory_store)
        self._memory_store = [e for e in self._memory_store if e.timestamp > cutoff]
        removed += before - len(self._memory_store)
        
        # Clean persistence if available
        if self._initialized and self.persistence:
            try:
                index_key = f"{self.key_prefix}:index"
                index_data = await self.persistence.get_queue_state(index_key)
                
                if index_data and 'error_ids' in index_data:
                    error_ids = index_data['error_ids']
                    cutoff_iso = cutoff.isoformat()
                    
                    # Find errors to remove
                    to_remove = [e for e in error_ids if e['timestamp'] <= cutoff_iso]
                    
                    # Delete each old error
                    for error_info in to_remove:
                        storage_key = f"{self.key_prefix}:{error_info['id']}"
                        await self.persistence.delete_queue_state(storage_key)
                        removed += 1
                    
                    # Update index
                    error_ids = [e for e in error_ids if e['timestamp'] > cutoff_iso]
                    await self.persistence.save_queue_state(
                        index_key,
                        {'error_ids': error_ids, 'updated_at': datetime.utcnow().isoformat()}
                    )
                    
            except Exception as e:
                logger.error(f"Failed to cleanup old errors from persistence: {e}")
        
        if removed > 0:
            logger.info(f"Cleaned up {removed} old event errors")
        
        return removed


# Global instance
_error_persistence: Optional[EventErrorPersistence] = None


def get_event_error_persistence() -> Optional[EventErrorPersistence]:
    """Get the global event error persistence instance."""
    return _error_persistence


def set_event_error_persistence(persistence: EventErrorPersistence) -> None:
    """Set the global event error persistence instance."""
    global _error_persistence
    _error_persistence = persistence