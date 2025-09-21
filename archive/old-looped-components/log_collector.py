"""
Log Collector Service

Centralized log collection service with buffering and batch persistence.
Integrates with the event bus for real-time streaming.
"""

import asyncio
import logging
import time
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import contextmanager, asynccontextmanager
import contextvars

from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.core.logs import LogEntry, LogLevel, LogSource, LogEventData, LogStats
from gleitzeit.events import EventBus
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter

# OpenTelemetry integration - optional
try:
    from opentelemetry import trace
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    trace = None

logger = logging.getLogger(__name__)

# Context variables for log context
log_context = contextvars.ContextVar('log_context', default={})


class LogCollector:
    """Centralized log collection service with buffering and streaming"""
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        persistence: Optional[UnifiedPersistenceAdapter] = None,
        buffer_size: int = 100,
        flush_interval: float = 1.0,
        enable_persistence: bool = True,
        enable_streaming: bool = True,
        scheduler=None  # StatelessScheduler for stateless flush scheduling
    ):
        """
        Initialize log collector
        
        Args:
            event_bus: Event bus for real-time streaming
            persistence: Unified persistence adapter for storage
            buffer_size: Number of logs to buffer before flush
            flush_interval: Seconds between automatic flushes
            enable_persistence: Whether to persist logs to storage
            enable_streaming: Whether to stream logs via event bus
        """
        self.event_bus = event_bus
        self.persistence = persistence
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self.enable_persistence = enable_persistence and persistence is not None
        self.enable_streaming = enable_streaming and event_bus is not None
        self.scheduler = scheduler  # For stateless flush scheduling
        
        # Store Redis client if available from persistence
        self.redis_client = None
        if persistence and hasattr(persistence, 'redis') and persistence.redis:
            from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
            if isinstance(persistence, UnifiedRedisAdapter):
                self.redis_client = persistence.redis
                logger.info("LogCollector initialized with Redis backend via persistence")
        
        if not self.redis_client and persistence:
            logger.info("LogCollector initialized with unified persistence (no Redis)")
        elif not persistence:
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
            "backend": "redis" if self.redis_client else "unified" if persistence else "none"
        }
    
    async def start(self):
        """Start the log collector background tasks - stateless only"""
        if self.running:
            return

        self.running = True

        if self.enable_persistence:
            if self.scheduler:
                # Use stateless scheduler-based flushing
                await self._start_stateless_flush_loop()
                logger.info("LogCollector started with stateless scheduler-based flushing")
            else:
                # No fallback - stateless architecture requires scheduler
                raise RuntimeError(
                    "LogCollector requires a scheduler for stateless operation. "
                    "Cannot start without proper stream-based scheduling infrastructure."
                )
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
        
        # Add to OpenTelemetry span if available
        if OPENTELEMETRY_AVAILABLE and trace:
            try:
                current_span = trace.get_current_span()
                if current_span and current_span.is_recording():
                    # Add log entry as span attributes
                    span_attributes = {
                        "log.level": level.value,
                        "log.source": source.value,
                        "log.message": message[:200],  # Truncate long messages
                    }
                    
                    if task_id:
                        span_attributes["log.task_id"] = task_id
                    if workflow_id:
                        span_attributes["log.workflow_id"] = workflow_id
                    if provider_id:
                        span_attributes["log.provider_id"] = provider_id
                    
                    # Set attributes on current span
                    for key, value in span_attributes.items():
                        current_span.set_attribute(key, value)
                    
                    # Record exception for error logs
                    if level in [LogLevel.ERROR, LogLevel.CRITICAL] and metadata:
                        error_type = metadata.get('error_type')
                        error_message = metadata.get('error_message', message)
                        if error_type:
                            # Create a fake exception for OpenTelemetry
                            try:
                                raise Exception(f"{error_type}: {error_message}")
                            except Exception as fake_exception:
                                current_span.record_exception(fake_exception)
                
            except Exception as e:
                # Don't let telemetry errors break logging
                logger.debug(f"OpenTelemetry integration error: {e}")
        
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
        if not self.enable_persistence or not self.persistence:
            return
        
        # Use Redis directly for Redis Streams
        if self.redis_client:
            try:
                await self._save_logs_to_redis(entries)
                logger.debug(f"Saved {len(entries)} logs via Redis")
                return
            except Exception as e:
                logger.error(f"Failed to save logs to Redis: {e}")
                raise
        
        # For now, if no Redis adapter, we skip persistence
        # In the future, we could add log methods to UnifiedPersistenceAdapter interface
        logger.debug(f"Skipping log persistence - Redis adapter not available")
    
    async def _save_logs_to_redis(self, entries: List[LogEntry]) -> List[str]:
        """Save logs to Redis using streams"""
        if not self.redis_client:
            return []
        
        ids = []
        for entry in entries:
            try:
                # Convert log entry to Redis stream format
                log_data = self._serialize_log(entry)
                
                # Add to global log stream
                global_key = "logs:global"
                log_id = await self.redis_client.xadd(
                    global_key,
                    log_data,
                    maxlen=10000,  # Keep last 10k logs
                    approximate=True
                )
                ids.append(log_id)
                
                # Add to task-specific stream if applicable
                if entry.task_id:
                    task_key = f"logs:task:{entry.task_id}"
                    await self.redis_client.xadd(
                        task_key,
                        log_data,
                        maxlen=1000,  # Keep last 1k logs per task
                        approximate=True
                    )
                    # Set expiration on task logs (7 days)
                    await self.redis_client.expire(task_key, 7 * 86400)
                
                # Add to workflow-specific stream if applicable
                if entry.workflow_id:
                    workflow_key = f"logs:workflow:{entry.workflow_id}"
                    await self.redis_client.xadd(
                        workflow_key,
                        log_data,
                        maxlen=5000,  # Keep last 5k logs per workflow
                        approximate=True
                    )
                    # Set expiration on workflow logs (7 days)
                    await self.redis_client.expire(workflow_key, 7 * 86400)
                    
            except Exception as e:
                logger.error(f"Failed to save individual log: {e}")
                
        return ids
    
    def _serialize_log(self, entry: LogEntry) -> Dict[str, str]:
        """Convert LogEntry to Redis-storable format"""
        import json
        
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
    
    async def _flush_loop(self) -> None:
        """Background task to periodically flush buffer using stream-based approach"""
        if not self.enable_persistence:
            return

        try:
            # Use Redis stream for flush scheduling instead of sleep polling
            stream_name = f"log_collector:flush:{id(self)}"

            # Ensure stream exists and add initial flush event
            await self.persistence.redis.xadd(
                stream_name,
                {"action": "flush", "timestamp": str(time.time())}
            )

            while self.running:
                try:
                    # Use blocking read with timeout instead of sleep
                    messages = await self.persistence.redis.xread(
                        {stream_name: "$"},
                        count=1,
                        block=int(self.flush_interval * 1000)  # Convert to milliseconds
                    )

                    # Flush buffer regardless of whether we got a message (timeout-based)
                    await self._flush_buffer()

                    # Schedule next flush event
                    await self.persistence.redis.xadd(
                        stream_name,
                        {"action": "flush", "timestamp": str(time.time())}
                    )

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in stream-based flush loop: {e}")
                    # Fallback to simple sleep if stream fails
                    await asyncio.sleep(self.flush_interval)
                    await self._flush_buffer()

        except Exception as e:
            logger.error(f"Error setting up stream-based flush loop: {e}")
            # Ultimate fallback to simple sleep-based approach
            while self.running:
                try:
                    await asyncio.sleep(self.flush_interval)
                    await self._flush_buffer()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in fallback flush loop: {e}")

    async def _start_stateless_flush_loop(self):
        """Start stateless flush loop using scheduler events"""
        if not self.scheduler:
            logger.warning("No scheduler available for stateless flush loop")
            return

        # Register event handler first
        await self.scheduler.register_handler(
            event_type="log_collector.flush",
            handler=self._handle_flush_event
        )

        # Schedule first flush event
        await self.scheduler.schedule_event(
            event_type="log_collector.flush",
            delay_seconds=self.flush_interval,
            payload={"instance_id": id(self)}
        )
        logger.debug(f"Registered flush handler and scheduled first flush event in {self.flush_interval}s")

    async def _handle_flush_event(self, event_data: dict):
        """Handle scheduled flush events"""
        try:
            if not self.running:
                logger.debug("LogCollector not running, skipping flush event")
                return

            # Flush the buffer
            await self._flush_buffer()

            # Schedule next flush if still running
            if self.running and self.scheduler:
                await self.scheduler.schedule_event(
                    event_type="log_collector.flush",
                    delay_seconds=self.flush_interval,
                    payload={"instance_id": id(self)}
                )

        except Exception as e:
            logger.error(f"Error in flush event handler: {e}")
            # Reschedule even on error to prevent stopping
            if self.running and self.scheduler:
                await self.scheduler.schedule_event(
                    event_type="log_collector.flush",
                    delay_seconds=self.flush_interval,
                    payload={"instance_id": id(self), "error_recovery": True}
                )
    
    async def get_logs(
        self,
        task_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        limit: int = 100,
        since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve logs from Redis streams
        
        Args:
            task_id: Filter by task ID
            workflow_id: Filter by workflow ID  
            limit: Maximum number of logs to return
            since: Return logs after this timestamp
            
        Returns:
            List of log entries as dictionaries
            
        Raises:
            PersistenceReadError: If Redis read fails
        """
        if not self.redis_client:
            return []
        
        try:
            # Determine which stream to read from
            # Generate keys following UnifiedRedisAdapter key format
            if task_id:
                stream_key = f"logs:task:{task_id}"
            elif workflow_id:
                stream_key = f"logs:workflow:{workflow_id}"
            else:
                stream_key = "logs:global"
            
            # Build range query
            if since:
                start_id = f"{int(since.timestamp() * 1000)}-0"
            else:
                start_id = "-"  # From beginning
            
            # Read from stream
            entries = await self.redis_client.xrange(
                stream_key,
                min=start_id,
                max="+",  # To end
                count=limit
            )
            
            # Parse results
            logs = []
            for entry_id, data in entries:
                log = self._deserialize_log(data)
                logs.append(log)
            
            return logs
            
        except Exception as e:
            logger.error(f"Failed to get logs from Redis: {e}")
            raise PersistenceReadError(
                f"Failed to retrieve logs from Redis",
                code=ErrorCode.PERSISTENCE_READ_FAILED,
                data={"task_id": task_id, "workflow_id": workflow_id},
                cause=e
            )
    
    def _deserialize_log(self, data: Dict[bytes, bytes]) -> Dict[str, Any]:
        """Convert Redis data back to log entry format"""
        import json
        
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
    
    async def delete_logs(
        self,
        task_id: Optional[str] = None,
        workflow_id: Optional[str] = None
    ) -> bool:
        """
        Delete logs for a task or workflow
        
        Args:
            task_id: Task whose logs to delete
            workflow_id: Workflow whose logs to delete
            
        Returns:
            Success status
            
        Raises:
            PersistenceWriteError: If Redis delete fails
        """
        if not self.redis_client:
            return False
        
        try:
            keys_to_delete = []
            
            if task_id:
                keys_to_delete.append(f"logs:task:{task_id}")
            
            if workflow_id:
                keys_to_delete.append(f"logs:workflow:{workflow_id}")
            
            if keys_to_delete:
                await self.redis_client.delete(*keys_to_delete)
                logger.info(f"Deleted logs for task={task_id}, workflow={workflow_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete logs from Redis: {e}")
            raise PersistenceWriteError(
                f"Failed to delete logs from Redis",
                code=ErrorCode.PERSISTENCE_WRITE_FAILED,
                data={"task_id": task_id, "workflow_id": workflow_id},
                cause=e
            )
    
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