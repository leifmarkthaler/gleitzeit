"""
Stateless Event Bus Implementation

A truly stateless event bus that stores all state in Redis or other backends,
allowing for horizontal scaling and crash recovery.
"""

import json
import logging
import asyncio
import uuid
import pickle
import base64
from typing import Dict, List, Any, Optional, Callable, Set, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

from ..core.events import GleitzeitEvent, EventType, EventSeverity
from ..core.errors import GleitzeitError, InvalidEventTypeError, EventError

logger = logging.getLogger(__name__)


@dataclass
class HandlerConfig:
    """Configuration for a registered handler."""
    handler_id: str
    event_type: str
    module_path: str
    function_name: str
    priority: int = 2  # 0=critical, 1=high, 2=normal, 3=low
    filter_expr: Optional[str] = None  # Python expression for filtering
    once: bool = False
    active: bool = True
    created_at: str = ""
    metadata: Dict[str, Any] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for Redis storage."""
        result = {}
        for k, v in asdict(self).items():
            if v is not None:
                # Convert booleans to strings for Redis storage
                if isinstance(v, bool):
                    result[k] = str(v)
                else:
                    result[k] = v
        return result


class StatelessEventBus:
    """
    Stateless event bus with all state stored in Redis.
    
    Features:
    - Handler registry stored in Redis
    - Error tracking persisted to Redis
    - Metrics stored as Redis counters
    - Fully recoverable after restart
    - Horizontally scalable
    """
    
    def __init__(self, persistence=None, prefix: str = "eventbus", event_store=None):
        """
        Initialize stateless event bus.
        
        Args:
            persistence: Backend persistence (Redis or InMemory)
            prefix: Redis key prefix for namespacing
            event_store: Optional EventStore for persisting events
        """
        self.persistence = persistence
        self.prefix = prefix
        self.event_store = event_store
        self._local_handler_cache: Dict[str, Callable] = {}  # Local cache only
        self._subscription_task = None
        self._running = False
        
    def _key(self, *parts) -> str:
        """Build Redis key with prefix."""
        return f"{self.prefix}:{':'.join(parts)}"
    
    def _validate_event_type(self, event_type: Union[str, EventType]) -> str:
        """
        Validate and normalize event type to use centralized EventType enum.
        
        Args:
            event_type: Event type to validate
            
        Returns:
            Validated event type string
            
        Raises:
            ValueError: If event type is not valid
        """
        if isinstance(event_type, EventType):
            return event_type.value
        elif isinstance(event_type, str):
            # Check if string matches any EventType value
            valid_event_types = [e.value for e in EventType]
            if event_type in valid_event_types:
                return event_type
            else:
                raise InvalidEventTypeError(
                    f"Invalid event type '{event_type}'. Must be one of the defined EventType values."
                )
        else:
            raise InvalidEventTypeError(
                f"Event type must be EventType enum or valid string, got {type(event_type)}"
            )
    
    # =========================================================================
    # Handler Registration (Stateless)
    # =========================================================================
    
    async def register_handler(self,
                              event_type: Union[str, EventType],
                              handler: Callable,
                              priority: int = 2,
                              filter_expr: Optional[str] = None,
                              once: bool = False,
                              handler_id: Optional[str] = None) -> str:
        """
        Register an event handler in Redis.
        
        Args:
            event_type: Event type to handle (must be valid EventType)
            handler: Handler function (must be importable)
            priority: Handler priority (0=critical, 3=low)
            filter_expr: Optional Python filter expression
            once: If True, handler runs only once
            handler_id: Optional handler ID (generated if not provided)
            
        Returns:
            Handler ID for reference
        """
        # Validate and normalize event type
        event_type_str = self._validate_event_type(event_type)
        if not self.persistence:
            logger.warning("No persistence backend, falling back to in-memory")
            return await self._register_local(event_type, handler)
        
        # Generate handler ID if not provided
        if not handler_id:
            handler_id = f"handler_{uuid.uuid4().hex[:12]}"
        
        # Get handler module and function name for storage
        module_path = handler.__module__
        function_name = handler.__name__
        
        # Create handler configuration
        config = HandlerConfig(
            handler_id=handler_id,
            event_type=event_type_str,
            module_path=module_path,
            function_name=function_name,
            priority=priority,
            filter_expr=filter_expr,
            once=once,
            active=True,  # Explicitly set active to True
            created_at=datetime.utcnow().isoformat(),
            metadata={
                'registered_by': 'stateless_bus',
                'node_id': self._get_node_id()
            }
        )
        
        # Store handler configuration in persistence
        handler_key = self._key("handler", handler_id)
        
        # Store handler config using persistence adapter's hset if available
        if hasattr(self.persistence, 'hset'):
            # Store handler config (serialize values)
            config_dict = config.to_dict()
            serialized_config = {}
            for k, v in config_dict.items():
                if isinstance(v, (dict, list)):
                    serialized_config[k] = json.dumps(v)
                elif v is None:
                    serialized_config[k] = ""
                else:
                    serialized_config[k] = str(v)
            await self.persistence.hset(handler_key, mapping=serialized_config)
            
            # Add to event type's handler set (sorted by priority)
            handlers_key = self._key("handlers", event_type_str)
            await self.persistence.zadd(handlers_key, {handler_id: priority})
            
            # Track handler for this node (for cleanup)
            node_handlers_key = self._key("node_handlers", self._get_node_id())
            await self.persistence.sadd(node_handlers_key, handler_id)
            
            # Set expiry for one-time handlers
            if once:
                await self.persistence.expire(handler_key, 86400)  # 24 hour expiry
        else:
            # Fallback to generic persistence
            await self._store_handler_generic(config)
        
        # Cache handler locally for performance
        self._local_handler_cache[handler_id] = handler
        
        logger.info(f"Registered handler {handler_id} for {event_type} (priority={priority})")
        return handler_id
    
    def _register_local_sync(self, event_type: Union[str, EventType], handler: Callable) -> str:
        """Fallback local registration when no persistence available (sync version)."""
        # Validate and normalize event type
        event_type_str = self._validate_event_type(event_type)
        handler_id = f"local_{uuid.uuid4().hex[:12]}"
        if event_type_str not in self._local_handler_cache:
            self._local_handler_cache[event_type_str] = []
        self._local_handler_cache[event_type_str].append(handler)
        logger.info(f"Registered local handler {handler_id} for {event_type_str}")
        return handler_id
    
    async def _register_local(self, event_type: Union[str, EventType], handler: Callable) -> str:
        """Fallback local registration when no persistence available (async wrapper)."""
        return self._register_local_sync(event_type, handler)
    
    async def _store_handler_generic(self, config: HandlerConfig):
        """Store handler using generic persistence interface."""
        # Store as event for retrieval
        event_data = {
            'event_type': 'HANDLER_REGISTERED',
            'handler_config': config.to_dict(),
            'timestamp': datetime.utcnow().isoformat()
        }
        if hasattr(self.persistence, 'save_event'):
            await self.persistence.save_event(event_data)
    
    async def unregister_handler(self, handler_id: str) -> bool:
        """
        Remove a handler from persistence.
        
        Args:
            handler_id: Handler ID to remove
            
        Returns:
            True if removed, False if not found
        """
        if not self.persistence:
            return False
        
        # Get handler config to find event type
        handler_key = self._key("handler", handler_id)
        config = await self.persistence.hgetall(handler_key) if hasattr(self.persistence, 'hgetall') else None
        
        if not config:
            return False
            
        event_type = config.get(b'event_type', b'').decode()
        
        # Remove from handler set
        if event_type:
            handlers_key = self._key("handlers", event_type)
            if hasattr(self.persistence, 'zrem'):
                await self.persistence.zrem(handlers_key, handler_id)
        
        # Remove handler config
        await self.persistence.delete(handler_key)
        
        # Remove from node handlers
        node_handlers_key = self._key("node_handlers", self._get_node_id())
        if hasattr(self.persistence, 'srem'):
            await self.persistence.srem(node_handlers_key, handler_id)
        
        # Remove from local cache
        self._local_handler_cache.pop(handler_id, None)
        
        logger.info(f"Unregistered handler {handler_id}")
        return True
    
    # =========================================================================
    # Handler Retrieval (Stateless)
    # =========================================================================
    
    async def get_handlers(self, event_type: str) -> List[HandlerConfig]:
        """
        Get all handlers for an event type from persistence.
        
        Args:
            event_type: Event type to get handlers for
            
        Returns:
            List of handler configurations sorted by priority
        """
        if not self.persistence:
            return []
        
        # Get handler IDs sorted by priority
        handlers_key = self._key("handlers", event_type)
        handler_ids = await self.persistence.zrange(handlers_key, 0, -1) if hasattr(self.persistence, 'zrange') else []
        
        if not handler_ids:
            return []
        
        # Get handler configurations
        handlers = []
        for handler_id in handler_ids:
            handler_id = handler_id.decode() if isinstance(handler_id, bytes) else handler_id
            handler_key = self._key("handler", handler_id)
            config_data = await self.persistence.hgetall(handler_key) if hasattr(self.persistence, 'hgetall') else None
            
            if config_data:
                # Convert bytes to strings
                config_dict = {
                    k.decode() if isinstance(k, bytes) else k: 
                    v.decode() if isinstance(v, bytes) else v
                    for k, v in config_data.items()
                }
                
                # Convert string booleans with defaults
                config_dict['once'] = config_dict.get('once', 'False') == 'True'
                config_dict['active'] = config_dict.get('active', 'True') == 'True'
                if 'priority' in config_dict:
                    config_dict['priority'] = int(config_dict['priority'])
                    
                handlers.append(HandlerConfig(**config_dict))
        
        return handlers
    
    async def _load_handler_function(self, config: HandlerConfig) -> Optional[Callable]:
        """
        Load handler function from configuration.
        
        Args:
            config: Handler configuration
            
        Returns:
            Handler function or None if not loadable
        """
        # Check local cache first
        if config.handler_id in self._local_handler_cache:
            return self._local_handler_cache[config.handler_id]
        
        try:
            # Import module and get function
            import importlib
            module = importlib.import_module(config.module_path)
            handler = getattr(module, config.function_name)
            
            # Cache locally
            self._local_handler_cache[config.handler_id] = handler
            return handler
            
        except Exception as e:
            logger.error(f"Failed to load handler {config.handler_id}: {e}")
            return None
    
    # =========================================================================
    # Event Emission (Stateless)
    # =========================================================================
    
    async def emit(self, event: GleitzeitEvent) -> None:
        """
        Emit an event to all registered handlers.
        
        Args:
            event: Event to emit (must use valid EventType)
        """
        # Persist event if store is configured
        if self.event_store:
            try:
                await self.event_store.save_event(event)
            except Exception as e:
                logger.warning(f"Failed to persist event {event.event_type}: {e}")
                # Don't fail emission if persistence fails
        
        # Validate event type
        event_type = self._validate_event_type(event.event_type)
        
        # Check for local handlers first (fallback mode)
        if event_type in self._local_handler_cache:
            logger.debug(f"Using local handlers for {event_type}")
            handlers = self._local_handler_cache[event_type]
            for handler in handlers:
                try:
                    await handler(event)
                except Exception as e:
                    logger.error(f"Error in local handler: {e}")
            return
        
        # Get handlers from Redis
        handler_configs = await self.get_handlers(event_type)
        
        if not handler_configs:
            logger.debug(f"No handlers registered for {event_type}")
            return
        
        logger.debug(f"Emitting {event_type} to {len(handler_configs)} handlers")
        
        # Execute handlers
        tasks = []
        for config in handler_configs:
            if not config.active:
                continue
                
            # Load handler function
            handler = await self._load_handler_function(config)
            if not handler:
                continue
            
            # Apply filter if specified
            if config.filter_expr:
                try:
                    # Safe evaluation of filter expression
                    if not self._evaluate_filter(config.filter_expr, event):
                        continue
                except Exception as e:
                    logger.error(f"Filter evaluation failed for {config.handler_id}: {e}")
                    continue
            
            # Create execution task
            task = asyncio.create_task(
                self._execute_handler(handler, event, config)
            )
            tasks.append(task)
        
        # Wait for all handlers to complete
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Track results
            successes = sum(1 for r in results if not isinstance(r, Exception))
            failures = len(results) - successes
            
            if failures > 0:
                logger.warning(f"Event {event_type}: {successes} succeeded, {failures} failed")
            else:
                logger.debug(f"Event {event_type} processed successfully by {successes} handlers")
    
    async def _execute_handler(self, 
                              handler: Callable,
                              event: GleitzeitEvent,
                              config: HandlerConfig) -> Any:
        """
        Execute a single handler with error tracking.
        
        Args:
            handler: Handler function to execute
            event: Event to pass to handler
            config: Handler configuration
            
        Returns:
            Handler result or exception
        """
        try:
            # Increment call count
            await self._increment_metrics(config.handler_id, 'call_count')
            
            # Execute handler
            result = handler(event)
            if asyncio.iscoroutine(result):
                result = await result
            
            # Mark success
            await self._increment_metrics(config.handler_id, 'success_count')
            
            # Handle one-time handlers
            if config.once:
                await self.unregister_handler(config.handler_id)
                logger.debug(f"Removed one-time handler {config.handler_id}")
            
            return result
            
        except Exception as e:
            # Track error
            await self._track_error(config.handler_id, event_type=str(event.event_type), error=e)
            await self._increment_metrics(config.handler_id, 'error_count')
            
            logger.error(f"Handler {config.handler_id} failed: {e}")
            raise
    
    def _evaluate_filter(self, filter_expr: str, event: GleitzeitEvent) -> bool:
        """
        Safely evaluate a filter expression.
        
        Args:
            filter_expr: Python expression to evaluate
            event: Event to filter
            
        Returns:
            True if filter passes, False otherwise
        """
        # Create safe evaluation context
        context = {
            'event': event,
            'event_type': str(event.event_type),
            'data': event.data,
            'tags': event.tags or {},
            'source': event.source
        }
        
        try:
            # Use compile for safety
            code = compile(filter_expr, '<filter>', 'eval')
            return eval(code, {"__builtins__": {}}, context)
        except Exception:
            return False
    
    # =========================================================================
    # Error Tracking (Stateless)
    # =========================================================================
    
    async def _track_error(self,
                          handler_id: str,
                          event_type: str,
                          error: Exception) -> None:
        """
        Track handler error in persistence.
        
        Args:
            handler_id: Handler that failed
            event_type: Event type being processed
            error: Exception that occurred
        """
        if not self.persistence:
            return
        
        # Create error record
        error_data = {
            'handler_id': handler_id,
            'event_type': event_type,
            'error_type': type(error).__name__,
            'error_message': str(error),
            'timestamp': datetime.utcnow().isoformat(),
            'node_id': self._get_node_id()
        }
        
        # Store in error list (keep last 1000)
        errors_key = self._key("errors")
        if hasattr(self.persistence, 'lpush'):
            await self.persistence.lpush(errors_key, json.dumps(error_data))
            if hasattr(self.persistence, 'ltrim'):
                await self.persistence.ltrim(errors_key, 0, 999)
        
        # Store handler-specific error
        handler_errors_key = self._key("errors", handler_id)
        if hasattr(self.persistence, 'lpush'):
            await self.persistence.lpush(handler_errors_key, json.dumps(error_data))
            if hasattr(self.persistence, 'ltrim'):
                await self.persistence.ltrim(handler_errors_key, 0, 99)  # Keep last 100 per handler
        
        # Set TTL on error records (7 days)
        if hasattr(self.persistence, 'expire'):
            await self.persistence.expire(errors_key, 604800)
            await self.persistence.expire(handler_errors_key, 604800)
    
    async def get_error_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get error history from persistence.
        
        Args:
            limit: Maximum number of errors to return
            
        Returns:
            List of error records (newest first)
        """
        if not self.persistence:
            return []
        
        errors_key = self._key("errors")
        
        # Get recent errors
        error_jsons = await self.persistence.lrange(errors_key, 0, limit - 1) if hasattr(self.persistence, 'lrange') else []
        
        errors = []
        for error_json in error_jsons:
            try:
                error_data = json.loads(error_json)
                errors.append(error_data)
            except json.JSONDecodeError:
                continue
                
        return errors
    
    # =========================================================================
    # Metrics (Stateless)
    # =========================================================================
    
    async def _increment_metrics(self, handler_id: str, metric: str, amount: int = 1) -> None:
        """
        Increment handler metrics in persistence.
        
        Args:
            handler_id: Handler to track
            metric: Metric name (call_count, error_count, etc.)
            amount: Amount to increment
        """
        if not self.persistence:
            return
        
        # Increment counter
        metrics_key = self._key("metrics", handler_id)
        if hasattr(self.persistence, 'hincrby'):
            await self.persistence.hincrby(metrics_key, metric, amount)
        
        # Update last activity time
        if hasattr(self.persistence, 'hset'):
            await self.persistence.hset(metrics_key, "last_activity", datetime.utcnow().isoformat())
        
        # Set TTL (30 days)
        if hasattr(self.persistence, 'expire'):
            await self.persistence.expire(metrics_key, 2592000)
    
    async def get_metrics(self, handler_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get metrics from persistence.
        
        Args:
            handler_id: Specific handler or None for all
            
        Returns:
            Metrics dictionary
        """
        if not self.persistence:
            return {}
        
        if handler_id:
            # Get specific handler metrics
            metrics_key = self._key("metrics", handler_id)
            metrics = await self.persistence.hgetall(metrics_key) if hasattr(self.persistence, 'hgetall') else {}
            
            return {
                k.decode() if isinstance(k, bytes) else k:
                int(v) if v.isdigit() else v.decode() if isinstance(v, bytes) else v
                for k, v in metrics.items()
            }
        else:
            # Get aggregate metrics
            pattern = self._key("metrics", "*")
            all_metrics = {}
            
            # Use SCAN to find all metric keys
            cursor = 0
            while True:
                if hasattr(self.persistence, 'scan'):
                    cursor, keys = await self.persistence.scan(cursor, match=pattern, count=100)
                else:
                    break
                
                for key in keys:
                    handler_id = key.decode().split(':')[-1]
                    metrics = await self.persistence.hgetall(key) if hasattr(self.persistence, 'hgetall') else {}
                    all_metrics[handler_id] = {
                        k.decode() if isinstance(k, bytes) else k:
                        int(v) if v.isdigit() else v.decode() if isinstance(v, bytes) else v
                        for k, v in metrics.items()
                    }
                
                if cursor == 0:
                    break
                    
            return all_metrics
    
    # =========================================================================
    # Lifecycle Management
    # =========================================================================
    
    async def start(self) -> None:
        """Start the event bus (initialize Redis subscriptions)."""
        self._running = True
        logger.info("Stateless event bus started")
    
    async def stop(self) -> None:
        """Stop the event bus and cleanup."""
        self._running = False
        
        # Clean up node-specific handlers
        if self.persistence:
            node_handlers_key = self._key("node_handlers", self._get_node_id())
            
            # Get all handlers for this node
            handler_ids = await self.persistence.smembers(node_handlers_key) if hasattr(self.persistence, 'smembers') else set()
            
            # Remove handlers registered by this node
            for handler_id in handler_ids:
                await self.unregister_handler(handler_id.decode() if isinstance(handler_id, bytes) else handler_id)
            
            # Remove node handlers set
            await self.persistence.delete(node_handlers_key)
        
        logger.info("Stateless event bus stopped")
    
    def _get_node_id(self) -> str:
        """Get unique node identifier."""
        import socket
        import os
        return f"{socket.gethostname()}_{os.getpid()}"
    
    # =========================================================================
    # Compatibility Methods
    # =========================================================================
    
    def register(self, event_type: Union[str, EventType], handler: Callable) -> None:
        """
        Synchronous registration for compatibility.
        
        Note: Uses local cache for immediate registration.
        """
        # Always use local cache for sync registration
        # This ensures handlers are immediately available
        self._register_local_sync(event_type, handler)
    
    def unregister(self, event_type: str, handler: Callable) -> bool:
        """Compatibility method - not fully supported in stateless mode."""
        logger.warning("Unregister by handler reference not supported in stateless mode")
        return False
    
    def get_handler_count(self, event_type: str) -> int:
        """Get handler count synchronously."""
        # This would need to be async to query Redis
        # Return 0 for compatibility
        return 0
    
    def list_event_types(self) -> List[str]:
        """List event types synchronously."""
        # This would need to be async to query Redis
        # Return empty for compatibility
        return []