"""
Streaming and WebSocket support mixin for Gleitzeit client.
"""

from typing import Any, Dict, Optional, AsyncIterator, Callable, List
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class StreamingMixin:
    """Mixin providing streaming and WebSocket operations."""
    
    async def stream_task_logs(self, 
                              task_id: str,
                              callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream task logs in real-time via WebSocket.
        
        Args:
            task_id: Task ID to stream logs for
            callback: Optional callback for each log entry
            
        Yields:
            Log entries as they arrive
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        # Check if adapter supports WebSocket
        if not hasattr(self._adapter, 'stream_task_logs'):
            raise NotImplementedError("Adapter does not support WebSocket streaming")
        
        async for log_entry in self._adapter.stream_task_logs(task_id):
            if callback:
                callback(log_entry)
            yield log_entry
    
    async def stream_workflow_logs(self,
                                  workflow_id: str,
                                  callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream workflow logs in real-time via WebSocket.
        
        Args:
            workflow_id: Workflow ID to stream logs for
            callback: Optional callback for each log entry
            
        Yields:
            Log entries as they arrive
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        if not hasattr(self._adapter, 'stream_workflow_logs'):
            raise NotImplementedError("Adapter does not support WebSocket streaming")
        
        async for log_entry in self._adapter.stream_workflow_logs(workflow_id):
            if callback:
                callback(log_entry)
            yield log_entry
    
    async def stream_all_logs(self,
                            level: Optional[str] = None,
                            callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream all system logs in real-time via WebSocket.
        
        Args:
            level: Optional log level filter
            callback: Optional callback for each log entry
            
        Yields:
            Log entries as they arrive
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        if not hasattr(self._adapter, 'stream_all_logs'):
            raise NotImplementedError("Adapter does not support WebSocket streaming")
        
        async for log_entry in self._adapter.stream_all_logs(level):
            if callback:
                callback(log_entry)
            yield log_entry
    
    async def stream_events(self,
                          filter: Optional[str] = None,
                          callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream system events in real-time.
        
        Args:
            filter: Optional event type filter
            callback: Optional callback for each event
            
        Yields:
            Events as they occur
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        if not hasattr(self._adapter, 'stream_events'):
            # Fall back to polling if streaming not available
            while True:
                events = await self._adapter.get_event_stream(filter, follow=True)
                for event in events.get('events', []):
                    if callback:
                        callback(event)
                    yield event
                await asyncio.sleep(1)
        else:
            async for event in self._adapter.stream_events(filter):
                if callback:
                    callback(event)
                yield event
    
    async def stream_workflow_events(self,
                                   workflow_id: str,
                                   callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream events for a specific workflow in real-time.
        
        Args:
            workflow_id: Workflow ID to stream events for
            callback: Optional callback for each event
            
        Yields:
            Workflow events as they occur
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        if not hasattr(self._adapter, 'stream_workflow_events'):
            raise NotImplementedError("Adapter does not support workflow event streaming")
        
        async for event in self._adapter.stream_workflow_events(workflow_id):
            if callback:
                callback(event)
            yield event
    
    async def upload_workflow_file(self,
                                  file_path: str,
                                  auto_submit: bool = True) -> Dict[str, Any]:
        """
        Upload a workflow definition file.
        
        Args:
            file_path: Path to workflow file (YAML/JSON)
            auto_submit: Whether to automatically submit after upload
            
        Returns:
            Upload result with workflow details
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        import os
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Workflow file not found: {file_path}")
        
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        return await self._adapter.upload_workflow_file(file_content, file_path, auto_submit)
    
    async def bulk_process_directory(self,
                                    directory_path: str,
                                    pattern: str = "*",
                                    method: str = "process",
                                    recursive: bool = True) -> Dict[str, Any]:
        """
        Bulk process an entire directory of files via API.
        
        Args:
            directory_path: Path to directory
            pattern: File pattern to match
            method: Processing method to use
            recursive: Whether to process subdirectories
            
        Returns:
            Processing results for all files
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        return await self._adapter.bulk_process_directory(
            directory_path,
            pattern,
            method,
            recursive
        )
    
    async def refresh_auth_token(self) -> Dict[str, Any]:
        """
        Refresh authentication token.
        
        Returns:
            New token information
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        return await self._adapter.refresh_auth_token()
    
    async def change_password(self,
                            current_password: str,
                            new_password: str) -> Dict[str, Any]:
        """
        Change the current user's password.
        
        Args:
            current_password: Current password
            new_password: New password
            
        Returns:
            Password change confirmation
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        return await self._adapter.change_password(current_password, new_password)
    
    async def search_logs(self,
                        query: str,
                        advanced_filters: Optional[Dict[str, Any]] = None,
                        limit: int = 100) -> List[Dict[str, Any]]:
        """
        Advanced log search with complex filters.
        
        Args:
            query: Search query
            advanced_filters: Additional search filters
            limit: Maximum results
            
        Returns:
            Matching log entries
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        return await self._adapter.search_logs(query, advanced_filters, limit)
    
    async def set_log_retention(self,
                              days: int,
                              log_level: Optional[str] = None) -> Dict[str, Any]:
        """
        Configure log retention policy.
        
        Args:
            days: Number of days to retain logs
            log_level: Optional level-specific retention
            
        Returns:
            Updated retention policy
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        return await self._adapter.set_log_retention(days, log_level)
    
    async def cleanup_system(self,
                           older_than_days: int = 30,
                           include_logs: bool = True,
                           include_results: bool = True) -> Dict[str, Any]:
        """
        Clean up old system data.
        
        Args:
            older_than_days: Clean data older than this many days
            include_logs: Whether to clean logs
            include_results: Whether to clean task results
            
        Returns:
            Cleanup statistics
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        return await self._adapter.cleanup_system(
            older_than_days,
            include_logs,
            include_results
        )
    
    async def get_api_info(self) -> Dict[str, Any]:
        """
        Get API information and version.
        
        Returns:
            API information including version, endpoints, etc.
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        return await self._adapter.get_api_info()
    
    async def monitor_task(self,
                         task_id: str,
                         include_logs: bool = True,
                         include_events: bool = True) -> AsyncIterator[Dict[str, Any]]:
        """
        Monitor a task with combined logs and events.
        
        Args:
            task_id: Task ID to monitor
            include_logs: Include log entries
            include_events: Include events
            
        Yields:
            Combined stream of logs and events
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        tasks = []
        
        if include_logs:
            tasks.append(self.stream_task_logs(task_id))
        
        if include_events:
            # Assuming events can be filtered by task
            tasks.append(self.stream_events(filter=f"task:{task_id}"))
        
        # Merge streams
        async def merge_streams():
            queues = [asyncio.Queue() for _ in tasks]
            
            async def stream_to_queue(stream, queue):
                async for item in stream:
                    await queue.put(item)
                await queue.put(None)  # Sentinel
            
            # Start all stream tasks
            stream_tasks = [
                asyncio.create_task(stream_to_queue(stream, queue))
                for stream, queue in zip(tasks, queues)
            ]
            
            # Yield from all queues
            active_queues = list(queues)
            while active_queues:
                for queue in list(active_queues):
                    try:
                        item = queue.get_nowait()
                        if item is None:
                            active_queues.remove(queue)
                        else:
                            yield item
                    except asyncio.QueueEmpty:
                        pass
                
                if active_queues:
                    await asyncio.sleep(0.1)
            
            # Wait for all tasks to complete
            await asyncio.gather(*stream_tasks)
        
        async for item in merge_streams():
            yield item