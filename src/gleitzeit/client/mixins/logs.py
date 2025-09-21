"""
Log management mixin for Gleitzeit client.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime

from gleitzeit.core.errors import SystemError


class LogMixin:
    """Mixin providing log management operations."""
    
    async def get_logs(self, 
                      level: Optional[str] = None,
                      source: Optional[str] = None,
                      start_time: Optional[datetime] = None,
                      end_time: Optional[datetime] = None,
                      limit: int = 100,
                      offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get logs with optional filtering.
        
        Args:
            level: Log level filter (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            source: Source/component filter
            start_time: Start time for log range
            end_time: End time for log range
            limit: Maximum number of logs to return
            offset: Offset for pagination
            
        Returns:
            List of log entries
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.get_logs(
            level=level,
            source=source, 
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset
        )
    
    async def get_log_levels(self) -> List[str]:
        """
        Get available log levels.
        
        Returns:
            List of available log levels
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.get_log_levels()
    
    async def query_logs(self, 
                        query: str,
                        limit: int = 100,
                        offset: int = 0) -> List[Dict[str, Any]]:
        """
        Query logs using a search string.
        
        Args:
            query: Search query string
            limit: Maximum number of results
            offset: Offset for pagination
            
        Returns:
            List of matching log entries
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.query_logs(query, limit, offset)
    
    async def tail_logs(self,
                       lines: int = 100,
                       follow: bool = False,
                       source: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Tail logs (get most recent logs).
        
        Args:
            lines: Number of lines to return
            follow: Whether to follow logs in real-time
            source: Optional source filter
            
        Returns:
            List of recent log entries
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.tail_logs(lines, follow, source)
    
    async def download_logs(self,
                          format: str = "json",
                          start_time: Optional[datetime] = None,
                          end_time: Optional[datetime] = None) -> bytes:
        """
        Download logs in specified format.
        
        Args:
            format: Output format (json, csv, txt)
            start_time: Start time for log range
            end_time: End time for log range
            
        Returns:
            Log data as bytes
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.download_logs(format, start_time, end_time)
    
    async def clear_logs(self,
                        before: Optional[datetime] = None,
                        level: Optional[str] = None) -> Dict[str, Any]:
        """
        Clear logs with optional filtering.
        
        Args:
            before: Clear logs before this time
            level: Only clear logs of this level
            
        Returns:
            Result with number of logs cleared
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.clear_logs(before, level)
    
    async def get_log_size(self) -> Dict[str, Any]:
        """
        Get log storage size information.
        
        Returns:
            Dictionary with size information (bytes, human_readable, etc.)
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.get_log_size()
    
    async def get_task_logs(self, 
                          task_id: str,
                          level: Optional[str] = None,
                          limit: int = 100,
                          offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get logs for a specific task.
        
        Args:
            task_id: Task ID to get logs for
            level: Optional log level filter
            limit: Maximum number of logs to return
            offset: Offset for pagination
            
        Returns:
            List of log entries for the task
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.get_task_logs(
            task_id,
            level=level,
            limit=limit,
            offset=offset
        )
    
    async def get_workflow_logs(self, workflow_id: str) -> List[Dict[str, Any]]:
        """
        Get logs for a specific workflow.
        
        Args:
            workflow_id: Workflow ID to get logs for
            
        Returns:
            List of log entries for the workflow
        """
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.get_workflow_logs(workflow_id)