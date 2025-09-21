"""
Stream Integration for Providers

Provides stream-based event emission and monitoring capabilities
for providers in the Gleitzeit stream architecture.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime
import json

if TYPE_CHECKING:
    from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager as StreamSystemManager

logger = logging.getLogger(__name__)


class StreamIntegrationMixin:
    """
    Mixin to add stream integration capabilities to providers.

    This mixin provides:
    - Event emission to Redis streams
    - Stream-based health reporting
    - Integration with StreamSystemManager
    - Provider lifecycle events
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stream_manager: Optional['StreamSystemManager'] = None
        self._stream_enabled = False
        self._event_prefix = "provider"

        # Stream configuration
        self._health_report_interval = 60  # seconds
        self._health_task: Optional[asyncio.Task] = None

    async def initialize_stream_integration(
        self,
        stream_manager: 'StreamSystemManager',
        enable_health_reporting: bool = True
    ):
        """
        Initialize stream integration with a StreamSystemManager.

        Args:
            stream_manager: StreamSystemManager instance
            enable_health_reporting: Whether to enable periodic health reporting
        """
        self._stream_manager = stream_manager
        self._stream_enabled = True

        # Register provider with stream manager
        await self._register_with_stream_manager()

        # Start health reporting if enabled
        if enable_health_reporting:
            await self._start_health_reporting()

        logger.info(f"Provider {self.provider_id} initialized stream integration")

    async def _register_with_stream_manager(self):
        """Register this provider with the stream manager"""
        if not self._stream_manager:
            return

        try:
            registration_data = {
                "provider_id": self.provider_id,
                "provider_type": self.__class__.__name__,
                "protocol_id": self.protocol_id,
                "capabilities": self.get_supported_methods(),
                "registered_at": datetime.utcnow().isoformat(),
                "instance_info": {
                    "version": getattr(self, 'version', '1.0.0'),
                    "description": getattr(self, 'description', ''),
                    "name": getattr(self, 'name', self.provider_id)
                }
            }

            # Emit provider registration event
            await self._emit_provider_event("PROVIDER_REGISTERED", registration_data)

        except Exception as e:
            logger.warning(f"Failed to register provider {self.provider_id} with stream manager: {e}")

    async def _start_health_reporting(self):
        """Health reporting setup (stateless - no loops)"""
        # Health reporting will be triggered externally
        logger.debug(f"Health reporting ready for provider {self.provider_id} (trigger-based)")

    async def _report_health(self):
        """Report provider health to streams"""
        if not self._stream_enabled:
            return

        try:
            # Get health status
            is_healthy = await self.health_check() if hasattr(self, 'health_check') else True

            # Get enhanced metrics if available
            metrics = {}
            if hasattr(self, 'get_enhanced_metrics'):
                metrics = self.get_enhanced_metrics()
            elif hasattr(self, 'get_info'):
                metrics = self.get_info()

            health_data = {
                "provider_id": self.provider_id,
                "healthy": is_healthy,
                "timestamp": datetime.utcnow().isoformat(),
                "metrics": metrics,
                "status": "healthy" if is_healthy else "unhealthy"
            }

            # Emit health report event
            await self._emit_provider_event("PROVIDER_HEALTH_REPORT", health_data)

        except Exception as e:
            logger.error(f"Failed to report health for provider {self.provider_id}: {e}")

    async def _emit_provider_event(self, event_type: str, data: Dict[str, Any]):
        """
        Emit a provider event to Redis streams.

        Args:
            event_type: Type of event (e.g., PROVIDER_REGISTERED, PROVIDER_HEALTH_REPORT)
            data: Event data
        """
        if not self._stream_enabled or not self._stream_manager:
            return

        try:
            event_data = {
                "event_type": event_type,
                "provider_id": self.provider_id,
                "timestamp": datetime.utcnow().isoformat(),
                "data": data
            }

            # Use the stream manager's event bus to emit events
            if hasattr(self._stream_manager, 'event_bus'):
                await self._stream_manager.event_bus.emit(
                    f"{self._event_prefix}:{event_type}",
                    event_data
                )

        except Exception as e:
            logger.warning(f"Failed to emit provider event {event_type}: {e}")

    async def _emit_task_start_event(self, method: str, params: Dict[str, Any], task_id: Optional[str] = None):
        """Emit event when a task starts execution"""
        event_data = {
            "provider_id": self.provider_id,
            "method": method,
            "task_id": task_id,
            "params_count": len(params),
            "started_at": datetime.utcnow().isoformat()
        }

        await self._emit_provider_event("PROVIDER_TASK_STARTED", event_data)

    async def _emit_task_complete_event(
        self,
        method: str,
        success: bool,
        duration_ms: float,
        task_id: Optional[str] = None,
        error: Optional[str] = None
    ):
        """Emit event when a task completes"""
        event_data = {
            "provider_id": self.provider_id,
            "method": method,
            "task_id": task_id,
            "success": success,
            "duration_ms": duration_ms,
            "completed_at": datetime.utcnow().isoformat()
        }

        if error:
            event_data["error"] = error

        event_type = "PROVIDER_TASK_COMPLETED" if success else "PROVIDER_TASK_FAILED"
        await self._emit_provider_event(event_type, event_data)

    async def stream_aware_handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Stream-aware version of handle_request that emits events.

        This method wraps the original handle_request with stream event emission.
        """
        if not self._stream_enabled:
            # Fall back to original handle_request if streams not enabled
            return await super().handle_request(method, params)

        task_id = params.get('task_id') if isinstance(params, dict) else None
        start_time = asyncio.get_event_loop().time()

        # Emit task start event
        await self._emit_task_start_event(method, params, task_id)

        try:
            # Call original handle_request
            result = await super().handle_request(method, params)

            # Calculate duration
            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            # Emit success event
            await self._emit_task_complete_event(method, True, duration_ms, task_id)

            return result

        except Exception as e:
            # Calculate duration
            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            # Emit failure event
            await self._emit_task_complete_event(
                method, False, duration_ms, task_id, str(e)
            )

            raise

    async def shutdown_stream_integration(self):
        """Shutdown stream integration"""
        self._stream_enabled = False

        # Emit shutdown event
        try:
            await self._emit_provider_event("PROVIDER_SHUTDOWN", {
                "provider_id": self.provider_id,
                "shutdown_at": datetime.utcnow().isoformat()
            })
        except Exception as e:
            logger.debug(f"Failed to emit shutdown event for {self.provider_id}: {e}")

        self._stream_manager = None
        logger.info(f"Provider {self.provider_id} stream integration shutdown")


class StreamAwareProtocolProvider:
    """
    Base class that combines ProtocolProvider with stream integration.

    This provides a convenient base class for new providers that want
    stream integration by default.
    """

    def __init__(self, *args, **kwargs):
        # Extract stream-specific kwargs
        self._auto_enable_streams = kwargs.pop('enable_stream_integration', True)
        self._health_reporting = kwargs.pop('enable_health_reporting', True)

        super().__init__(*args, **kwargs)

    async def initialize(self):
        """Initialize provider and optionally set up stream integration"""
        # Call parent initialize
        await super().initialize()

        # Try to auto-discover StreamSystemManager and set up integration
        if self._auto_enable_streams:
            await self._auto_setup_stream_integration()

    async def _auto_setup_stream_integration(self):
        """Automatically set up stream integration if available"""
        try:
            # Try to get StreamSystemManager from system
            from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager as StreamSystemManager

            # Look for active stream manager
            # This could be passed via dependency injection or discovered
            stream_manager = getattr(self, '_stream_manager', None)

            if not stream_manager:
                # Try to discover from system manager registry
                # This is a simplified discovery - in practice you might
                # get this from a service registry or dependency container
                logger.debug(f"No stream manager provided to {self.provider_id}, skipping stream integration")
                return

            # Initialize stream integration
            await self.initialize_stream_integration(
                stream_manager,
                self._health_reporting
            )

        except Exception as e:
            logger.warning(f"Failed to auto-setup stream integration for {self.provider_id}: {e}")

    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Use stream-aware request handling if streams are enabled"""
        if hasattr(self, '_stream_enabled') and self._stream_enabled:
            return await self.stream_aware_handle_request(method, params)
        else:
            return await super().handle_request(method, params)

    async def shutdown(self):
        """Shutdown provider and stream integration"""
        # Shutdown stream integration first
        if hasattr(self, 'shutdown_stream_integration'):
            await self.shutdown_stream_integration()

        # Call parent shutdown
        await super().shutdown()


# Create combined classes using multiple inheritance
class StreamAwareProtocolProviderImpl(StreamIntegrationMixin, StreamAwareProtocolProvider):
    """
    Complete implementation combining ProtocolProvider with stream integration.

    Use this as a base class for providers that want full stream integration.
    """
    pass


# Convenience function to add stream integration to existing providers
async def enable_stream_integration_for_provider(
    provider,
    stream_manager: 'StreamSystemManager',
    enable_health_reporting: bool = True
):
    """
    Add stream integration to an existing provider instance.

    Args:
        provider: Existing provider instance
        stream_manager: StreamSystemManager instance
        enable_health_reporting: Whether to enable health reporting
    """
    # Dynamically add stream integration methods
    mixin = StreamIntegrationMixin()

    # Copy stream integration methods to the provider
    for method_name in dir(mixin):
        if method_name.startswith('_') and not method_name.startswith('__'):
            if hasattr(mixin, method_name):
                setattr(provider, method_name, getattr(mixin, method_name).__get__(provider))

    # Initialize stream integration
    await provider.initialize_stream_integration(stream_manager, enable_health_reporting)

    # Wrap handle_request method for stream awareness
    original_handle_request = provider.handle_request

    async def stream_aware_wrapper(method: str, params: Dict[str, Any]) -> Any:
        if hasattr(provider, '_stream_enabled') and provider._stream_enabled:
            return await provider.stream_aware_handle_request(method, params)
        else:
            return await original_handle_request(method, params)

    provider.handle_request = stream_aware_wrapper

    logger.info(f"Enabled stream integration for existing provider {provider.provider_id}")