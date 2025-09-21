"""
Stream signals mixin providing signal management via Redis Streams.
"""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class StreamSignalsMixin:
    """
    Mixin providing stream-based signal management.

    This mixin handles:
    - Stream-based signal manager
    - Signal provider registration
    - Signal event processing
    """

    def __init__(self, **kwargs):
        """Initialize signal components."""
        self.signal_manager = None
        super().__init__(**kwargs)

    async def initialize_stream_signals(self):
        """Initialize stream-based signal manager."""
        redis_client = getattr(self.persistence, 'redis', None)
        if not redis_client:
            logger.warning("Redis not available - signal manager disabled")
            return

        try:
            from ...signals.stream_signal_manager import StreamSignalManager

            # Get stream configuration
            total_shards = getattr(self, 'total_shards', 64)
            consumer_group = getattr(self, 'consumer_group', 'gleitzeit-processors')

            self.signal_manager = StreamSignalManager(
                persistence=self.persistence,
                event_bus=self.event_bus,
                instance_id=f"{self.instance_id}-signals",
                total_shards=total_shards,
                consumer_group=f"{consumer_group}-signals"
            )
            await self.signal_manager.initialize()
            await self.signal_manager.start_processing()

            # Register signal/v1 protocol if registry is available
            if hasattr(self, 'registry') and self.registry:
                await self.registry.register_provider_in_persistence(
                    "signal/v1",
                    {
                        "provider_id": "stream_signal_manager",
                        "instance_id": self.instance_id,
                        "capabilities": ["signal/wait", "signal/wait_any", "signal/wait_all", "signal/send", "signal/broadcast"],
                        "stream_based": True
                    }
                )
                logger.info("Registered signal/v1 protocol in StatelessProtocolRegistry")

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="signal_manager",
                    component_type="service",
                    metadata={
                        "instance_id": self.instance_id,
                        "stream_based": True,
                        "total_shards": total_shards,
                        "consumer_group": f"{consumer_group}-signals"
                    }
                )

            # Register event handlers with stream manager if possible
            if hasattr(self, 'register_stream_handler'):
                # Signal manager can register its own handlers here
                pass

            logger.info("StreamSignalManager initialized and started")

        except Exception as e:
            logger.error(f"Failed to initialize signal manager: {e}")
            self.signal_manager = None

    async def shutdown_stream_signals(self):
        """Shutdown stream-based signal manager."""
        if self.signal_manager:
            try:
                await self.signal_manager.shutdown()
                logger.info("StreamSignalManager shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down signal manager: {e}")

    def get_signal_statistics(self) -> Optional[Dict[str, Any]]:
        """Get signal processing statistics."""
        if not self.signal_manager:
            return None

        try:
            if hasattr(self.signal_manager, 'get_statistics'):
                return self.signal_manager.get_statistics()
            elif hasattr(self.signal_manager, 'get_stream_info'):
                return self.signal_manager.get_stream_info()
        except Exception as e:
            logger.error(f"Error getting signal statistics: {e}")

        return {"error": "Statistics not available"}

    # Signal management interface
    async def send_signal(self, signal_name: str, data: Optional[Dict] = None,
                         workflow_id: Optional[str] = None, task_id: Optional[str] = None) -> bool:
        """Send a signal."""
        if not self.signal_manager:
            logger.warning("Signal manager not available")
            return False

        try:
            if hasattr(self.signal_manager, 'send_signal'):
                return await self.signal_manager.send_signal(signal_name, data, workflow_id, task_id)
            else:
                logger.warning("Signal manager does not support sending signals")
                return False
        except Exception as e:
            logger.error(f"Error sending signal {signal_name}: {e}")
            return False

    async def broadcast_signal(self, signal_name: str, data: Optional[Dict] = None) -> bool:
        """Broadcast a signal to all listeners."""
        if not self.signal_manager:
            logger.warning("Signal manager not available")
            return False

        try:
            if hasattr(self.signal_manager, 'broadcast_signal'):
                return await self.signal_manager.broadcast_signal(signal_name, data)
            else:
                logger.warning("Signal manager does not support broadcasting signals")
                return False
        except Exception as e:
            logger.error(f"Error broadcasting signal {signal_name}: {e}")
            return False

    async def wait_for_signal(self, signal_name: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Wait for a specific signal."""
        if not self.signal_manager:
            logger.warning("Signal manager not available")
            return None

        try:
            if hasattr(self.signal_manager, 'wait_for_signal'):
                return await self.signal_manager.wait_for_signal(signal_name, timeout)
            else:
                logger.warning("Signal manager does not support waiting for signals")
                return None
        except Exception as e:
            logger.error(f"Error waiting for signal {signal_name}: {e}")
            return None

    async def wait_for_any_signal(self, signal_names: List[str], timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Wait for any of the specified signals."""
        if not self.signal_manager:
            logger.warning("Signal manager not available")
            return None

        try:
            if hasattr(self.signal_manager, 'wait_for_any_signal'):
                return await self.signal_manager.wait_for_any_signal(signal_names, timeout)
            else:
                logger.warning("Signal manager does not support waiting for multiple signals")
                return None
        except Exception as e:
            logger.error(f"Error waiting for any signal {signal_names}: {e}")
            return None

    async def wait_for_all_signals(self, signal_names: List[str], timeout: Optional[float] = None) -> Optional[List[Dict[str, Any]]]:
        """Wait for all of the specified signals."""
        if not self.signal_manager:
            logger.warning("Signal manager not available")
            return None

        try:
            if hasattr(self.signal_manager, 'wait_for_all_signals'):
                return await self.signal_manager.wait_for_all_signals(signal_names, timeout)
            else:
                logger.warning("Signal manager does not support waiting for all signals")
                return None
        except Exception as e:
            logger.error(f"Error waiting for all signals {signal_names}: {e}")
            return None

    async def get_signal_status(self, signal_name: str) -> Optional[Dict[str, Any]]:
        """Get signal status."""
        if not self.signal_manager:
            return None

        try:
            if hasattr(self.signal_manager, 'get_signal_status'):
                return await self.signal_manager.get_signal_status(signal_name)
            else:
                # Check persistence directly
                return await self.persistence.get_signal(signal_name)
        except Exception as e:
            logger.error(f"Error getting signal status {signal_name}: {e}")
            return None