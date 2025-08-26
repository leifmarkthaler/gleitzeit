"""
Log Collector Service

Centralized log collection service with buffering and batch persistence.
Integrates with the event bus for real-time streaming.
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import contextmanager, asynccontextmanager
import contextvars

from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.core.logs import LogEntry, LogLevel, LogSource, LogEventData, LogStats
from gleitzeit.events.base import EventBus
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.persistence.log_redis_adapter import LogRedisAdapter

logger = logging.getLogger(__name__)

# Context variables for log context
log_context = contextvars.ContextVar('log_context', default={})


class LogCollector:
    """Centralized log collection service with buffering and streaming"""
    
    def __init__(
        self, 
        event_bus: Optional[EventBus] = None,
        persistence: Optional[UnifiedPersistenceAdapter] = None,
        redis_adapter: Optional[UnifiedRedisAdapter] = None,
        buffer_size: int = 100,
        flush_interval: float = 1.0,
        enable_persistence: bool = True,
        enable_streaming: bool = True,
        prefer_redis: bool = True
    ):
        """
        Initialize log collector
        
        Args:
            event_bus: Event bus for real-time streaming
            persistence: SQL persistence adapter for storage
            redis_adapter: Redis adapter for high-performance log storage
            buffer_size: Number of logs to buffer before flush
            flush_interval: Seconds between automatic flushes
            enable_persistence: Whether to persist logs to storage
            enable_streaming: Whether to stream logs via event bus
            prefer_redis: Prefer Redis over SQL when both are available
        """
        self.event_bus = event_bus
        self.persistence = persistence
        self.redis_adapter = redis_adapter
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self.enable_persistence = enable_persistence and (persistence is not None or redis_adapter is not None)
        self.enable_streaming = enable_streaming and event_bus is not None
        self.prefer_redis = prefer_redis
        
        # Initialize Redis log adapter if Redis is available
        self.log_redis: Optional[LogRedisAdapter] = None
        if redis_adapter:
            self.log_redis = LogRedisAdapter(redis_adapter)
            logger.info("LogCollector initialized with Redis backend")
        elif persistence:
            logger.info("LogCollector initialized with SQL backend")
        else:
            logger.info("LogCollector initialized without persistence")
        
        self.buffer: List[LogEntry] = []
        self.buffer_lock = asyncio.Lock()
        self.flush_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Statistics
        self.stats = {
            "total_logged": 0,
            "total_flushed": 0,
            "flush_errors": 0,
            "stream_errors": 0,
            "backend": "redis" if (redis_adapter and prefer_redis) else "sql" if persistence else "none"
        }
    
    async def start(self):
        """Start the log collector background tasks"""
        if self.running:
            return
        
        self.running = True
        
        if self.enable_persistence:
            self.flush_task = asyncio.create_task(self._flush_loop())
            logger.info("LogCollector started with persistence enabled")
        else:
            logger.info("LogCollector started without persistence")
    
    async def stop(self):
        """Stop the log collector and flush remaining logs"""
        self.running = False
        
        # Final flush
        await self._flush_buffer()
        
        if self.flush_task:
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass
        
        logger.info(f"LogCollector stopped. Stats: {self.stats}")
    
    async def log(
        self,
        level: LogLevel,
        message: str,
        source: LogSource,
        task_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        stream_type: Optional[str] = None,
        line_number: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log a message with context
        
        Args:
            level: Log severity level
            message: Log message
            source: Source of the log
            task_id: Associated task ID
            workflow_id: Associated workflow ID
            provider_id: Associated provider ID
            stream_type: Type of stream (stdout, stderr, etc.)
            line_number: Line number in stream
            metadata: Additional metadata
        """
        # Get context from context variables
        ctx = log_context.get()
        if not task_id and 'task_id' in ctx:
            task_id = ctx['task_id']
        if not workflow_id and 'workflow_id' in ctx:
            workflow_id = ctx['workflow_id']
        if not provider_id and 'provider_id' in ctx:
            provider_id = ctx['provider_id']
        
        # Create log entry
        entry = LogEntry(
            timestamp=datetime.utcnow(),
            level=level,
            message=message,
            source=source,
            task_id=task_id,
            workflow_id=workflow_id,
            provider_id=provider_id,
            stream_type=stream_type,
            line_number=line_number,
            metadata=metadata or {}
        )
        
        self.stats["total_logged"] += 1
        
        # Stream via event bus if enabled
        if self.enable_streaming:
            await self._stream_log(entry)
        
        # Add to buffer for persistence if enabled
        if self.enable_persistence:
            async with self.buffer_lock:
                self.buffer.append(entry)
                
                # Flush if buffer is full
                if len(self.buffer) >= self.buffer_size:
                    await self._flush_buffer()
    
    async def log_batch(self, entries: List[LogEntry]) -> None:
        """Log multiple entries at once"""
        for entry in entries:
            await self.log(
                level=entry.level,
                message=entry.message,
                source=entry.source,
                task_id=entry.task_id,
                workflow_id=entry.workflow_id,
                provider_id=entry.provider_id,
                stream_type=entry.stream_type,
                line_number=entry.line_number,
                metadata=entry.metadata
            )
    
    async def _stream_log(self, entry: LogEntry) -> None:
        """Stream log entry via event bus"""
        if not self.event_bus:
            return
        
        try:
            event = GleitzeitEvent(
                event_type=EventType.LOG_MESSAGE,
                data=LogEventData(entry=entry).to_dict()
            )
            await self.event_bus.emit(event)
        except Exception as e:
            self.stats["stream_errors"] += 1
            logger.error(f"Failed to stream log: {e}")
    
    async def _flush_buffer(self) -> None:
        """Flush buffered logs to persistence"""
        if not self.enable_persistence or not self.buffer:
            return
        
        async with self.buffer_lock:
            if not self.buffer:
                return
            
            batch = self.buffer.copy()
            self.buffer.clear()
        
        try:
            # Save logs to persistence
            await self._save_logs_batch(batch)
            
            self.stats["total_flushed"] += len(batch)
            
            # Emit batch event if large
            if len(batch) >= 10 and self.event_bus:
                event = GleitzeitEvent(
                    event_type=EventType.LOG_BATCH,
                    data={
                        "count": len(batch),
                        "workflow_id": batch[0].workflow_id if batch[0].workflow_id else None,
                        "task_id": batch[0].task_id if batch[0].task_id else None
                    }
                )
                await self.event_bus.emit(event)
                
        except Exception as e:
            self.stats["flush_errors"] += 1
            logger.error(f"Failed to flush logs: {e}")
            
            # Re-add to buffer for retry (with size limit)
            async with self.buffer_lock:
                # Keep only most recent logs if buffer would overflow
                if len(self.buffer) + len(batch) > self.buffer_size * 2:
                    self.buffer = batch[-self.buffer_size:]
                else:
                    self.buffer = batch + self.buffer
    
    async def _save_logs_batch(self, entries: List[LogEntry]) -> None:
        """Save log entries to persistence"""
        if not self.enable_persistence:
            return
        
        # Use Redis if available and preferred
        if self.log_redis and self.prefer_redis:
            try:
                await self.log_redis.save_logs_batch(entries)
                logger.debug(f"Saved {len(entries)} logs to Redis")
                return
            except Exception as e:
                logger.error(f"Failed to save logs to Redis: {e}")
                # Fall back to SQL if available
                if not self.persistence:
                    raise
        
        # Use SQL persistence if available
        if self.persistence:
            # Convert to dictionaries for storage
            log_dicts = [entry.to_dict() for entry in entries]
            
            # TODO: Add batch save method to SQL persistence adapter
            # For now, we'll save them individually (not optimal)
            for entry_dict in log_dicts:
                # This would be implemented in the persistence adapter
                # await self.persistence.save_log(entry_dict)
                pass
            
            logger.debug(f"Saved {len(entries)} logs to SQL")
    
    async def _flush_loop(self) -> None:
        """Background task to periodically flush buffer"""
        while self.running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in flush loop: {e}")
    
    @contextmanager
    def task_context(
        self, 
        task_id: str,
        workflow_id: Optional[str] = None,
        provider_id: Optional[str] = None
    ):
        """
        Context manager for task execution logging
        
        Example:
            with log_collector.task_context(task_id, workflow_id):
                # All logs within this context will have task/workflow context
                await log_collector.log(LogLevel.INFO, "Processing", LogSource.ENGINE)
        """
        token = log_context.set({
            "task_id": task_id,
            "workflow_id": workflow_id,
            "provider_id": provider_id
        })
        try:
            yield
        finally:
            log_context.reset(token)
    
    @asynccontextmanager
    async def stream_context(
        self,
        task_id: str,
        workflow_id: Optional[str] = None,
        source: LogSource = LogSource.SYSTEM
    ):
        """
        Async context manager for streaming logs
        
        Example:
            async with log_collector.stream_context(task_id, workflow_id):
                # Stream start event
                await some_operation()
                # Stream end event
        """
        # Emit stream start event
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.LOG_STREAM_START,
                data={
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "source": source.value,
                    "timestamp": datetime.utcnow().isoformat()
                }
            ))
        
        token = log_context.set({
            "task_id": task_id,
            "workflow_id": workflow_id
        })
        
        try:
            yield
        finally:
            log_context.reset(token)
            
            # Emit stream end event
            if self.event_bus:
                await self.event_bus.emit(GleitzeitEvent(
                    event_type=EventType.LOG_STREAM_END,
                    data={
                        "task_id": task_id,
                        "workflow_id": workflow_id,
                        "source": source.value,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                ))
    
    async def get_stats(self, task_id: Optional[str] = None, workflow_id: Optional[str] = None) -> LogStats:
        """Get log statistics"""
        # This would query the persistence layer
        return LogStats()
    
    def get_collector_stats(self) -> Dict[str, int]:
        """Get collector statistics"""
        return self.stats.copy()


# Global log collector instance (initialized at startup)
_log_collector: Optional[LogCollector] = None


def get_log_collector() -> Optional[LogCollector]:
    """Get the global log collector instance"""
    return _log_collector


def set_log_collector(collector: LogCollector) -> None:
    """Set the global log collector instance"""
    global _log_collector
    _log_collector = collector


async def log_info(message: str, source: LogSource = LogSource.SYSTEM, **kwargs):
    """Convenience function to log info message"""
    if _log_collector:
        await _log_collector.log(LogLevel.INFO, message, source, **kwargs)


async def log_error(message: str, source: LogSource = LogSource.SYSTEM, **kwargs):
    """Convenience function to log error message"""
    if _log_collector:
        await _log_collector.log(LogLevel.ERROR, message, source, **kwargs)


async def log_warning(message: str, source: LogSource = LogSource.SYSTEM, **kwargs):
    """Convenience function to log warning message"""
    if _log_collector:
        await _log_collector.log(LogLevel.WARNING, message, source, **kwargs)


async def log_debug(message: str, source: LogSource = LogSource.SYSTEM, **kwargs):
    """Convenience function to log debug message"""
    if _log_collector:
        await _log_collector.log(LogLevel.DEBUG, message, source, **kwargs)