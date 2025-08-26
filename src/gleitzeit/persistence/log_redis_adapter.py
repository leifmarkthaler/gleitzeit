"""
Redis Adapter for Log Persistence

Provides high-performance log storage using Redis data structures.
Uses Redis Streams for ordered log storage with automatic expiration.
"""

import json
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
import asyncio

from gleitzeit.core.logs import LogEntry, LogLevel, LogSource, LogStats
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter

logger = logging.getLogger(__name__)


class LogRedisAdapter:
    """
    Redis adapter specifically for log persistence.
    
    Features:
    - Uses Redis Streams for ordered, time-series log storage
    - Automatic log expiration with TTL
    - Efficient batch writes and reads
    - Task and workflow log correlation
    """
    
    def __init__(
        self,
        redis_adapter: UnifiedRedisAdapter,
        log_ttl_days: int = 7,
        max_stream_length: int = 10000
    ):
        """
        Initialize log Redis adapter.
        
        Args:
            redis_adapter: Existing Redis adapter to use
            log_ttl_days: Days to retain logs before expiration
            max_stream_length: Maximum entries per stream (FIFO eviction)
        """
        self.redis = redis_adapter.redis
        self._key = redis_adapter._key
        self.log_ttl_days = log_ttl_days
        self.max_stream_length = max_stream_length
        self._initialized = redis_adapter._initialized
        
    async def save_log(self, entry: LogEntry) -> str:
        """
        Save a single log entry to Redis.
        
        Args:
            entry: Log entry to save
            
        Returns:
            Log entry ID
        """
        if not self._initialized:
            logger.warning("Redis not initialized, cannot save log")
            return ""
            
        try:
            # Convert log entry to dict for storage
            log_data = self._serialize_log(entry)
            
            # Create stream keys for different access patterns
            streams = []
            
            # Global log stream
            streams.append(self._key("logs", "global"))
            
            # Task-specific stream
            if entry.task_id:
                streams.append(self._key("logs", "task", entry.task_id))
            
            # Workflow-specific stream
            if entry.workflow_id:
                streams.append(self._key("logs", "workflow", entry.workflow_id))
            
            # Add to all relevant streams
            log_id = None
            for stream_key in streams:
                # XADD with automatic ID generation and max length
                result = await self.redis.xadd(
                    stream_key,
                    log_data,
                    maxlen=self.max_stream_length,
                    approximate=True  # Allow approximate trimming for performance
                )
                if not log_id:
                    log_id = result
            
            # Set TTL on task/workflow streams (not global)
            if entry.task_id:
                ttl_seconds = self.log_ttl_days * 86400
                await self.redis.expire(
                    self._key("logs", "task", entry.task_id),
                    ttl_seconds
                )
            
            if entry.workflow_id:
                ttl_seconds = self.log_ttl_days * 86400
                await self.redis.expire(
                    self._key("logs", "workflow", entry.workflow_id),
                    ttl_seconds
                )
            
            return log_id
            
        except Exception as e:
            logger.error(f"Failed to save log to Redis: {e}")
            return ""
    
    async def save_logs_batch(self, entries: List[LogEntry]) -> List[str]:
        """
        Save multiple log entries efficiently.
        
        Args:
            entries: List of log entries to save
            
        Returns:
            List of log entry IDs
        """
        if not entries:
            return []
        
        # Use pipeline for batch operations
        ids = []
        for entry in entries:
            log_id = await self.save_log(entry)
            if log_id:
                ids.append(log_id)
        
        return ids
    
    async def get_logs(
        self,
        task_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        level: Optional[LogLevel] = None,
        limit: int = 100,
        since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve logs with filtering.
        
        Args:
            task_id: Filter by task ID
            workflow_id: Filter by workflow ID
            level: Minimum log level
            limit: Maximum number of logs to return
            since: Return logs after this timestamp
            
        Returns:
            List of log entries as dictionaries
        """
        if not self._initialized:
            return []
        
        try:
            # Determine which stream to read from
            if task_id:
                stream_key = self._key("logs", "task", task_id)
            elif workflow_id:
                stream_key = self._key("logs", "workflow", workflow_id)
            else:
                stream_key = self._key("logs", "global")
            
            # Build range query
            if since:
                # Convert datetime to Redis stream ID format (milliseconds-sequence)
                start_id = f"{int(since.timestamp() * 1000)}-0"
            else:
                start_id = "-"  # From beginning
            
            # Read from stream
            entries = await self.redis.xrange(
                stream_key,
                min=start_id,
                max="+",  # To end
                count=limit
            )
            
            # Parse and filter results
            logs = []
            for entry_id, data in entries:
                log = self._deserialize_log(data)
                
                # Apply level filter if specified
                if level and self._get_level_value(log.get('level')) < self._get_level_value(level):
                    continue
                
                logs.append(log)
            
            return logs
            
        except Exception as e:
            logger.error(f"Failed to get logs from Redis: {e}")
            return []
    
    async def get_log_stats(
        self,
        task_id: Optional[str] = None,
        workflow_id: Optional[str] = None
    ) -> LogStats:
        """
        Get log statistics.
        
        Args:
            task_id: Task to get stats for
            workflow_id: Workflow to get stats for
            
        Returns:
            Log statistics
        """
        if not self._initialized:
            return LogStats()
        
        try:
            # Determine stream to analyze
            if task_id:
                stream_key = self._key("logs", "task", task_id)
            elif workflow_id:
                stream_key = self._key("logs", "workflow", workflow_id)
            else:
                stream_key = self._key("logs", "global")
            
            # Get stream info
            info = await self.redis.xinfo_stream(stream_key)
            
            # Count by level (would need to iterate through entries for accurate counts)
            # For now, return basic stats
            return LogStats(
                total_count=info.get('length', 0),
                debug_count=0,  # Would need to iterate
                info_count=0,
                warning_count=0,
                error_count=0,
                critical_count=0,
                first_timestamp=None,  # Could parse from first-entry
                last_timestamp=None    # Could parse from last-entry
            )
            
        except Exception as e:
            logger.error(f"Failed to get log stats from Redis: {e}")
            return LogStats()
    
    async def delete_logs(
        self,
        task_id: Optional[str] = None,
        workflow_id: Optional[str] = None
    ) -> bool:
        """
        Delete logs for a task or workflow.
        
        Args:
            task_id: Task whose logs to delete
            workflow_id: Workflow whose logs to delete
            
        Returns:
            Success status
        """
        if not self._initialized:
            return False
        
        try:
            keys_to_delete = []
            
            if task_id:
                keys_to_delete.append(self._key("logs", "task", task_id))
            
            if workflow_id:
                keys_to_delete.append(self._key("logs", "workflow", workflow_id))
            
            if keys_to_delete:
                await self.redis.delete(*keys_to_delete)
                logger.info(f"Deleted logs for task={task_id}, workflow={workflow_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete logs from Redis: {e}")
            return False
    
    async def cleanup_old_logs(self, older_than_days: Optional[int] = None) -> int:
        """
        Clean up old logs based on age.
        
        Args:
            older_than_days: Delete logs older than this many days
                           (uses log_ttl_days if not specified)
            
        Returns:
            Number of log streams cleaned up
        """
        if not self._initialized:
            return 0
        
        # Redis Streams with TTL will auto-expire
        # This method is for manual cleanup if needed
        
        days = older_than_days or self.log_ttl_days
        cutoff_time = datetime.utcnow() - timedelta(days=days)
        cutoff_id = f"{int(cutoff_time.timestamp() * 1000)}-0"
        
        cleaned = 0
        
        try:
            # Find all log streams
            pattern = self._key("logs", "*")
            cursor = 0
            
            while True:
                cursor, keys = await self.redis.scan(
                    cursor,
                    match=pattern,
                    count=100
                )
                
                for key in keys:
                    # Trim stream to remove old entries
                    try:
                        await self.redis.xtrim(
                            key,
                            minid=cutoff_id,
                            approximate=True
                        )
                        cleaned += 1
                    except:
                        pass
                
                if cursor == 0:
                    break
            
            logger.info(f"Cleaned up {cleaned} log streams")
            return cleaned
            
        except Exception as e:
            logger.error(f"Failed to cleanup old logs: {e}")
            return 0
    
    def _serialize_log(self, entry: LogEntry) -> Dict[str, str]:
        """Convert LogEntry to Redis-storable format (strings only)."""
        data = {
            'timestamp': entry.timestamp.isoformat(),
            'level': entry.level.value if hasattr(entry.level, 'value') else str(entry.level),
            'message': entry.message,
            'source': entry.source.value if hasattr(entry.source, 'value') else str(entry.source)
        }
        
        # Add optional fields
        if entry.task_id:
            data['task_id'] = entry.task_id
        if entry.workflow_id:
            data['workflow_id'] = entry.workflow_id
        if entry.provider_id:
            data['provider_id'] = entry.provider_id
        if entry.stream_type:
            data['stream_type'] = entry.stream_type
        if entry.line_number is not None:
            data['line_number'] = str(entry.line_number)
        if entry.metadata:
            data['metadata'] = json.dumps(entry.metadata)
        
        return data
    
    def _deserialize_log(self, data: Dict[bytes, bytes]) -> Dict[str, Any]:
        """Convert Redis data back to log entry format."""
        # Decode bytes to strings
        log = {}
        for key, value in data.items():
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            val_str = value.decode('utf-8') if isinstance(value, bytes) else value
            
            if key_str == 'metadata' and val_str:
                try:
                    log[key_str] = json.loads(val_str)
                except:
                    log[key_str] = val_str
            elif key_str == 'line_number':
                log[key_str] = int(val_str)
            else:
                log[key_str] = val_str
        
        return log
    
    def _get_level_value(self, level: Any) -> int:
        """Convert log level to numeric value for comparison."""
        level_values = {
            LogLevel.DEBUG: 10,
            LogLevel.INFO: 20,
            LogLevel.WARNING: 30,
            LogLevel.ERROR: 40,
            LogLevel.CRITICAL: 50,
            "debug": 10,
            "info": 20,
            "warning": 30,
            "error": 40,
            "critical": 50
        }
        return level_values.get(level, 0)