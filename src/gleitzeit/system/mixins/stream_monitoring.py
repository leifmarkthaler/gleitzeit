"""
Stream monitoring mixin providing health monitoring and observability.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class StreamMonitoringMixin:
    """
    Mixin providing monitoring and observability for stream-based system.

    This mixin handles:
    - System health monitoring
    - Log collection and streaming
    - Metrics collection
    - Performance monitoring
    """

    def __init__(self, **kwargs):
        """Initialize monitoring components."""
        self.log_collector = None
        self.websocket_manager = None
        super().__init__(**kwargs)

    async def initialize_stream_monitoring(self):
        """Initialize monitoring infrastructure."""
        try:
            logger.info("Initializing stream monitoring infrastructure")

            # Initialize telemetry
            await self._initialize_telemetry()

            # Initialize log collector
            await self._initialize_log_collector()

            # Initialize WebSocket manager
            await self._initialize_websocket_manager()

            logger.info("Stream monitoring infrastructure initialized")

        except Exception as e:
            logger.error(f"Failed to initialize stream monitoring: {e}")
            # Don't raise - monitoring is optional

    async def _initialize_telemetry(self):
        """Initialize OpenTelemetry for distributed tracing."""
        try:
            from ...core.telemetry_simple import initialize_telemetry, TelemetryConfig

            # Get telemetry configuration
            telemetry_config = self._get_telemetry_config()

            if telemetry_config:
                logger.info(f"Initializing OpenTelemetry with {telemetry_config.exporter_type} exporter")
                success = initialize_telemetry(telemetry_config)

                if success:
                    logger.info("OpenTelemetry initialized successfully")
                else:
                    logger.warning("OpenTelemetry initialization failed")
            else:
                logger.debug("No telemetry configuration found, OpenTelemetry disabled")

        except ImportError:
            logger.debug("OpenTelemetry not available, telemetry disabled")
        except Exception as e:
            logger.error(f"Failed to initialize telemetry: {e}")

    def _get_telemetry_config(self) -> Optional['TelemetryConfig']:
        """Get telemetry configuration from environment."""
        import os
        try:
            from ...core.telemetry_simple import TelemetryConfig

            # Check environment variables for telemetry configuration
            exporter_type = os.getenv("GLEITZEIT_TELEMETRY_EXPORTER", "").lower()
            if not exporter_type:
                return None

            config = TelemetryConfig(
                service_name=os.getenv("GLEITZEIT_SERVICE_NAME", "gleitzeit"),
                service_version=os.getenv("GLEITZEIT_SERVICE_VERSION", "0.0.6"),
                exporter_type=exporter_type,
                exporter_endpoint=os.getenv("GLEITZEIT_TELEMETRY_ENDPOINT"),
                enable_logging_instrumentation=os.getenv("GLEITZEIT_TELEMETRY_LOGGING", "true").lower() == "true",
                sample_rate=float(os.getenv("GLEITZEIT_TELEMETRY_SAMPLE_RATE", "1.0"))
            )

            return config
        except Exception:
            return None

    async def _initialize_log_collector(self):
        """Initialize LogCollector for centralized logging."""
        try:
            from ...core.log_collector import LogCollector, set_log_collector

            self.log_collector = LogCollector(
                event_bus=self.event_bus,
                persistence=self.persistence,
                buffer_size=100,
                flush_interval=1.0,
                enable_persistence=True,
                enable_streaming=True,
                scheduler=getattr(self, 'event_scheduler', None)
            )

            # Start the LogCollector
            await self.log_collector.start()

            # Set as global log collector
            set_log_collector(self.log_collector)

            # Register event handler for log_collector.flush events
            if hasattr(self, 'register_stream_handler'):
                self.register_stream_handler(
                    'log_collector.flush',
                    self._handle_log_collector_flush,
                    'log_collector'
                )

            logger.info("LogCollector initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize LogCollector: {e}")
            self.log_collector = None

    async def _initialize_websocket_manager(self):
        """Initialize WebSocket manager for real-time connections."""
        redis_client = getattr(self.persistence, 'redis', None)
        if not redis_client:
            logger.info("Redis not available - WebSocket manager disabled")
            return

        try:
            from ...api.websocket_manager import ScalableWebSocketManager

            self.websocket_manager = ScalableWebSocketManager()
            await self.websocket_manager.initialize_redis()

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="websocket_manager",
                    component_type="service",
                    metadata={
                        "instance_id": self.websocket_manager.instance_id,
                        "max_connections": self.websocket_manager.max_connections,
                        "max_per_ip": self.websocket_manager.max_connections_per_ip,
                        "heartbeat_interval": self.websocket_manager.heartbeat_interval
                    }
                )

            logger.info("WebSocket Manager initialized")

        except Exception as e:
            logger.warning(f"Failed to initialize WebSocket Manager: {e}")
            self.websocket_manager = None

    async def shutdown_stream_monitoring(self):
        """Shutdown monitoring infrastructure."""
        logger.info("Shutting down monitoring infrastructure")

        try:
            # Shutdown log collector
            if self.log_collector:
                await self.log_collector.stop()
                from ...core.log_collector import set_log_collector
                set_log_collector(None)

            # Shutdown WebSocket manager
            if self.websocket_manager:
                await self.websocket_manager.shutdown()

        except Exception as e:
            logger.error(f"Error shutting down monitoring: {e}")

        logger.info("Monitoring infrastructure shutdown complete")

    async def _handle_log_collector_flush(self, event):
        """Handle log collector flush events."""
        if self.log_collector and hasattr(self.log_collector, 'flush'):
            try:
                await self.log_collector.flush()
                logger.debug("Log collector flushed via event")
            except Exception as e:
                logger.error(f"Error flushing log collector: {e}")

    # Monitoring interface
    async def get_system_health(self) -> Dict[str, Any]:
        """Get comprehensive system health."""
        # Get base health from health monitor
        base_health = {}
        if hasattr(self, 'health_monitor') and self.health_monitor:
            try:
                base_health = await self.health_monitor.get_system_health()
            except Exception as e:
                logger.error(f"Error getting base health: {e}")
                base_health = {"status": "unknown", "error": str(e)}

        # Add stream-specific health
        stream_health = {}
        if hasattr(self, 'stream_monitor') and self.stream_monitor:
            try:
                stream_health_data = await self.stream_monitor.get_system_health()
                stream_health = {
                    "stream_processing": {
                        "enabled": True,
                        "status": stream_health_data.status.value,
                        "total_streams": stream_health_data.total_streams,
                        "healthy_streams": stream_health_data.healthy_streams,
                        "warning_streams": stream_health_data.warning_streams,
                        "critical_streams": stream_health_data.critical_streams,
                        "total_pending_messages": stream_health_data.total_pending_messages,
                        "redis_memory_usage": stream_health_data.redis_memory_usage,
                        "issues": stream_health_data.issues
                    }
                }
            except Exception as e:
                logger.error(f"Error getting stream health: {e}")
                stream_health = {
                    "stream_processing": {
                        "enabled": True,
                        "error": str(e)
                    }
                }

        # Combine health information
        return {**base_health, **stream_health}

    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status."""
        from datetime import datetime

        status = {
            "status": "running" if getattr(self, '_running', False) else "stopped",
            "instance_id": self.instance_id,
            "stream_based": True,
            "modular": True,
            "uptime_seconds": (
                (datetime.utcnow() - self._start_time).total_seconds()
                if getattr(self, '_start_time', None) else 0
            ),
        }

        # Add deployment info if available
        if hasattr(self, 'config'):
            status.update({
                "deployment_mode": (
                    self.config.deployment_mode
                    if isinstance(self.config.deployment_mode, str)
                    else self.config.deployment_mode.value
                ),
                "environment": self.config.environment,
            })

        # Add component status
        try:
            components = {}
            if hasattr(self, 'service_registry') and self.service_registry:
                services = await self.service_registry.discover_services()
                components["services"] = len(services)

            if hasattr(self, 'component_registry') and self.component_registry:
                all_components = await self.component_registry.list_components()
                components["total_components"] = len(all_components)
                components["providers"] = len([c for c in all_components if c.component_type == "provider"])
                components["services"] = len([c for c in all_components if c.component_type == "service"])

            status["components"] = components

        except Exception as e:
            logger.error(f"Error getting component status: {e}")
            status["components"] = {"error": str(e)}

        # Add stream statistics if available
        if hasattr(self, 'get_stream_statistics'):
            try:
                status["streams"] = self.get_stream_statistics()
            except Exception as e:
                logger.error(f"Error getting stream statistics: {e}")

        return status

    def get_monitoring_statistics(self) -> Dict[str, Any]:
        """Get monitoring statistics."""
        stats = {
            "log_collector_active": self.log_collector is not None,
            "websocket_manager_active": self.websocket_manager is not None,
        }

        # Add log collector stats
        if self.log_collector:
            try:
                if hasattr(self.log_collector, 'get_statistics'):
                    stats["log_collector"] = self.log_collector.get_statistics()
            except Exception as e:
                stats["log_collector"] = {"error": str(e)}

        # Add WebSocket manager stats
        if self.websocket_manager:
            try:
                if hasattr(self.websocket_manager, 'get_statistics'):
                    stats["websocket_manager"] = self.websocket_manager.get_statistics()
            except Exception as e:
                stats["websocket_manager"] = {"error": str(e)}

        return stats