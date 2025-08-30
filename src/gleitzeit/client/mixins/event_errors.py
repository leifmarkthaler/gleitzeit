"""
Event error management mixin for Gleitzeit client.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime


class EventErrorMixin:
    """Mixin providing event error management operations."""
    
    async def get_event_errors(self,
                              status: Optional[str] = None,
                              severity: Optional[str] = None,
                              start_time: Optional[datetime] = None,
                              end_time: Optional[datetime] = None,
                              limit: int = 100,
                              offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get event errors with optional filtering.
        
        Args:
            status: Error status filter (new, acknowledged, resolved, ignored)
            severity: Severity filter (low, medium, high, critical)
            start_time: Start time for error range
            end_time: End time for error range
            limit: Maximum number of errors to return
            offset: Offset for pagination
            
        Returns:
            List of event errors
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_event_errors(
            status=status,
            severity=severity,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset
        )
    
    async def get_event_error(self, error_id: str) -> Dict[str, Any]:
        """
        Get details of a specific event error.
        
        Args:
            error_id: Event error ID
            
        Returns:
            Event error details
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_event_error(error_id)
    
    async def retry_event_error(self, error_id: str) -> Dict[str, Any]:
        """
        Retry processing of a failed event.
        
        Args:
            error_id: Event error ID to retry
            
        Returns:
            Result of retry attempt
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.retry_event_error(error_id)
    
    async def acknowledge_event_error(self, 
                                     error_id: str,
                                     notes: Optional[str] = None) -> Dict[str, Any]:
        """
        Acknowledge an event error.
        
        Args:
            error_id: Event error ID to acknowledge
            notes: Optional notes about the acknowledgment
            
        Returns:
            Updated error status
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.acknowledge_event_error(error_id, notes)
    
    async def resolve_event_error(self,
                                 error_id: str,
                                 resolution: str,
                                 notes: Optional[str] = None) -> Dict[str, Any]:
        """
        Mark an event error as resolved.
        
        Args:
            error_id: Event error ID to resolve
            resolution: Description of how the error was resolved
            notes: Optional additional notes
            
        Returns:
            Updated error status
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.resolve_event_error(error_id, resolution, notes)
    
    async def ignore_event_error(self,
                                error_id: str,
                                reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Mark an event error as ignored.
        
        Args:
            error_id: Event error ID to ignore
            reason: Optional reason for ignoring
            
        Returns:
            Updated error status
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.ignore_event_error(error_id, reason)
    
    async def delete_event_error(self, error_id: str) -> Dict[str, Any]:
        """
        Delete an event error record.
        
        Args:
            error_id: Event error ID to delete
            
        Returns:
            Deletion confirmation
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.delete_event_error(error_id)
    
    async def get_event_error_statistics(self,
                                        start_time: Optional[datetime] = None,
                                        end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get event error statistics.
        
        Args:
            start_time: Start time for statistics
            end_time: End time for statistics
            
        Returns:
            Dictionary with error statistics
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_event_error_statistics(start_time, end_time)
    
    async def bulk_acknowledge_errors(self, 
                                     error_ids: List[str],
                                     notes: Optional[str] = None) -> Dict[str, Any]:
        """
        Acknowledge multiple event errors at once.
        
        Args:
            error_ids: List of error IDs to acknowledge
            notes: Optional notes for all acknowledgments
            
        Returns:
            Results of bulk operation
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.bulk_acknowledge_errors(error_ids, notes)
    
    async def bulk_retry_errors(self, error_ids: List[str]) -> Dict[str, Any]:
        """
        Retry multiple event errors at once.
        
        Args:
            error_ids: List of error IDs to retry
            
        Returns:
            Results of bulk retry operation
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.bulk_retry_errors(error_ids)