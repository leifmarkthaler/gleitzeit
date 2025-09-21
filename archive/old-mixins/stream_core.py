"""
Stream core mixin providing Redis Streams infrastructure - DEPRECATED.

THIS MIXIN IS DEPRECATED. Use stateless_stream_core.py instead.
This old mixin uses MultiplexedStreamConsumer which has loops.
The new stateless_stream_core uses StreamlinedEventBus with NO loops.
"""

import logging
from typing import Optional, Dict, Any

from ...core.errors import SystemManagerError

logger = logging.getLogger(__name__)


class StreamCoreMixin:
    """
    Mixin providing core Redis Streams infrastructure.

    This mixin handles:
    - Stream-based event scheduler
    - Stream consumer management
    - Consumer group coordination
    - Stream monitoring setup
    """

    def __init__(self, stream_config: Optional[Dict[str, Any]] = None, **kwargs):
        """Initialize stream core components."""
        # Stream configuration
        self.stream_config = stream_config or {}
        self.total_shards = self.stream_config.get("total_shards", 64)
        self.consumer_group = self.stream_config.get("consumer_group", "gleitzeit-processors")
        self.monitoring_interval = self.stream_config.get("monitoring_interval", 30)

        # Stream components
        self.event_scheduler = None
        self.stream_monitor = None
        self.consumer_group_manager = None
        self.stream_consumer = None

        # Event handling
        self.event_handlers = {}
        self.handler_registry = None
        self.consumer_started = False

        # Pass along kwargs to next mixin in chain
        super().__init__(**kwargs)

    async def initialize_stream_core(self):
        """Initialize core stream infrastructure."""
        redis_client = getattr(self.persistence, 'redis', None)
        if not redis_client:
            raise SystemManagerError("Redis is required for stream-based system manager")

        try:
            logger.info(f"Initializing stream core with {self.total_shards} shards")

            # Initialize stream-based event scheduler
            await self._initialize_stream_scheduler()

            # Initialize stream monitor
            await self._initialize_stream_monitor()

            # Initialize consumer group manager
            await self._initialize_consumer_group_manager()

            # Initialize multiplexed stream consumer
            await self._initialize_stream_consumer()

            logger.info("Stream core infrastructure initialized")

        except Exception as e:
            logger.error(f"Failed to initialize stream core: {e}")
            raise SystemManagerError("Stream core initialization failed", cause=e)

    async def _initialize_stream_scheduler(self):
        """Initialize stream-based event scheduler."""
        try:
            from ...scheduler.stream_event_scheduler import StreamEventScheduler

            self.event_scheduler = StreamEventScheduler(
                persistence=self.persistence,
                event_bus=self.event_bus,
                instance_id=f"{self.instance_id}-scheduler",
                total_shards=self.total_shards,
                consumer_group=f"{self.consumer_group}-events"
            )
            await self.event_scheduler.initialize()
            await self.event_scheduler.start_processing()

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="stream_scheduler",
                    component_type="service",
                    metadata={
                        "instance_id": self.instance_id,
                        "total_shards": self.total_shards,
                        "consumer_group": f"{self.consumer_group}-events"
                    }
                )

            logger.info("StreamEventScheduler initialized")

        except Exception as e:
            logger.error(f"Failed to initialize stream scheduler: {e}")
            raise

    async def _initialize_stream_monitor(self):
        """Initialize stream monitoring."""
        try:
            from ...scheduler.stream_monitor import StreamMonitor

            self.stream_monitor = StreamMonitor(
                persistence=self.persistence,
                event_bus=self.event_bus,
                monitoring_interval=self.monitoring_interval,
                alert_thresholds=self.stream_config.get("alert_thresholds")
            )
            await self.stream_monitor.start_monitoring()

            logger.info("StreamMonitor initialized")

        except Exception as e:
            logger.error(f"Failed to initialize stream monitor: {e}")
            # Non-critical, continue without monitoring
            self.stream_monitor = None

    async def _initialize_consumer_group_manager(self):
        """Initialize consumer group manager."""
        try:
            from ...scheduler.consumer_group_manager import ConsumerGroupManager

            self.consumer_group_manager = ConsumerGroupManager(
                persistence=self.persistence,
                consumer_group=self.consumer_group,
                consumer_timeout_seconds=self.stream_config.get("consumer_timeout", 300),
                cleanup_interval_seconds=self.stream_config.get("cleanup_interval", 60)
            )
            await self.consumer_group_manager.start_monitoring()

            logger.info("ConsumerGroupManager initialized")

        except Exception as e:
            logger.error(f"Failed to initialize consumer group manager: {e}")
            # Non-critical, continue without consumer group management
            self.consumer_group_manager = None

    async def _initialize_stream_consumer(self):
        """Initialize multiplexed stream consumer."""
        try:
            from ...events.multiplexed_stream_consumer import MultiplexedStreamConsumer
            from ...events.event_contracts import EventContracts, HandlerRegistry

            # Create handler registry with contracts
            contracts = EventContracts.get_all_contracts()
            self.handler_registry = HandlerRegistry(contracts)

            # Initialize consumer but DON'T start it yet
            self.stream_consumer = MultiplexedStreamConsumer(
                redis=self.persistence.redis,
                handlers_registry=self.event_handlers,
                consumer_group=f"{self.consumer_group}-events",
                consumer_id=f"{self.instance_id}-consumer"
            )

            logger.info("MultiplexedStreamConsumer initialized (not started)")

        except Exception as e:
            logger.error(f"Failed to initialize stream consumer: {e}")
            raise

    def register_stream_handler(self, event_type: str, handler, component_name: str = None):
        """
        Register a stream event handler.

        Args:
            event_type: Event type to handle
            handler: Handler function
            component_name: Name of component registering the handler
        """
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []

        # Avoid duplicate handler registration
        if handler not in self.event_handlers[event_type]:
            self.event_handlers[event_type].append(handler)
        else:
            logger.debug(f"Handler already registered for {event_type} from {component_name or 'unknown'}")

        # Register with contract registry if available
        if self.handler_registry and component_name:
            self.handler_registry.register_handler(event_type, handler, component_name)

        # Also register with stream consumer if it exists AND is started
        if self.stream_consumer and self.consumer_started:
            self.stream_consumer.register_handler(event_type, handler)

        logger.info(f"Registered stream handler for {event_type} from {component_name or 'unknown'}")

    def register_event_handler(self, event_type: str, handler, component_name: str = None):
        """Alias for register_stream_handler for compatibility."""
        return self.register_stream_handler(event_type, handler, component_name)

    async def start_stream_consumer(self):
        """Start the stream consumer after all handlers are registered."""
        if not self.stream_consumer:
            logger.warning("No stream consumer to start")
            return

        try:
            # Register all collected handlers with the consumer
            if self.event_handlers:
                for event_type, handlers in self.event_handlers.items():
                    for handler in handlers:
                        self.stream_consumer.register_handler(event_type, handler)
                logger.info(f"Registered {len(self.event_handlers)} event types with consumer")

            # Validate contracts if configured
            validate_contracts = self.stream_config.get("validate_contracts", True)
            if validate_contracts and self.handler_registry:
                violations = self.handler_registry.validate_contracts()
                if violations:
                    logger.warning(f"Contract violations found: {violations}")
                else:
                    logger.info("All event contracts validated successfully")

            # Start the consumer
            await self.stream_consumer.start()
            self.consumer_started = True
            logger.info("MultiplexedStreamConsumer started")

        except Exception as e:
            logger.error(f"Failed to start stream consumer: {e}")
            raise

    async def shutdown_stream_core(self):
        """Shutdown stream core infrastructure."""
        logger.info("Shutting down stream core infrastructure")

        try:
            # Stop stream consumer
            if self.stream_consumer and self.consumer_started:
                await self.stream_consumer.shutdown()
                self.consumer_started = False

            # Stop consumer group manager
            if self.consumer_group_manager:
                await self.consumer_group_manager.stop_monitoring()

            # Stop stream monitor
            if self.stream_monitor:
                await self.stream_monitor.stop_monitoring()

            # Stop event scheduler
            if self.event_scheduler:
                await self.event_scheduler.shutdown()

        except Exception as e:
            logger.error(f"Error shutting down stream core: {e}")

        logger.info("Stream core infrastructure shutdown complete")

    def get_stream_statistics(self) -> Dict[str, Any]:
        """Get stream processing statistics."""
        stats = {
            "stream_processing": True,
            "configuration": {
                "total_shards": self.total_shards,
                "consumer_group": self.consumer_group,
                "monitoring_interval": self.monitoring_interval
            },
            "consumer_started": self.consumer_started,
            "handlers_registered": len(self.event_handlers),
        }

        try:
            # Add component statistics if available
            if self.event_scheduler and hasattr(self.event_scheduler, 'get_statistics'):
                stats["scheduler"] = self.event_scheduler.get_statistics()

            if self.consumer_group_manager and hasattr(self.consumer_group_manager, 'get_statistics'):
                stats["consumer_group_manager"] = self.consumer_group_manager.get_statistics()

            if self.stream_monitor:
                stats["monitor"] = self.stream_monitor.get_status()
                stats["metrics_summary"] = self.stream_monitor.get_metrics_summary(hours=1)

        except Exception as e:
            logger.error(f"Error getting stream statistics: {e}")
            stats["error"] = str(e)

        return stats