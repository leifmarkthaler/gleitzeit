"""
Stateless stream signals mixin providing signal management without loops.
"""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class StatelessStreamSignalsMixin:
    """
    Mixin providing stateless signal management.

    This mixin handles:
    - Stateless signal processing
    - No loops, pure trigger-based
    - Signal operations via Redis
    """

    def __init__(self, **kwargs):
        """Initialize stateless signal components."""
        self.max_signals_per_tick = 100
        super().__init__(**kwargs)

    async def initialize_stateless_stream_signals(self):
        """Initialize stateless signal support."""
        redis_client = getattr(self.persistence, 'redis', None)
        if not redis_client:
            logger.warning("Redis not available - signal support disabled")
            return

        try:
            # Store Redis reference for stateless signal operations
            self.redis_client = redis_client

            # Register signal/v1 protocol if registry is available
            if hasattr(self, 'registry') and self.registry:
                await self.registry.register_provider_in_persistence(
                    "signal/v1",
                    {
                        "provider_id": "stateless_signal_manager",
                        "instance_id": self.instance_id,
                        "capabilities": ["signal/wait", "signal/wait_any", "signal/wait_all", "signal/send", "signal/broadcast"],
                        "stateless": True,
                        "has_loops": False
                    }
                )
                logger.info("Registered signal/v1 protocol (stateless)")

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="stateless_signal_manager",
                    component_type="stateless_service",
                    metadata={
                        "instance_id": self.instance_id,
                        "stateless": True,
                        "has_loops": False,
                        "max_signals_per_tick": self.max_signals_per_tick
                    }
                )

            logger.info("Stateless signal support initialized (NO LOOPS!)")

        except Exception as e:
            logger.error(f"Failed to initialize stateless signal support: {e}")

    async def process_signals_once(self) -> Dict[str, Any]:
        """
        Process signals once - NO LOOPS!
        This is called by external triggers.

        Returns:
            Processing statistics
        """
        try:
            from ...signals.stateless_signal_manager import StatelessSignalManager

            result = await StatelessSignalManager.process_all_once(
                self.redis_client,
                max_signals=self.max_signals_per_tick
            )

            logger.debug(f"Processed {result['processed']} signals")
            return result

        except Exception as e:
            logger.error(f"Error processing signals: {e}")
            return {"error": str(e), "processed": 0}

    async def send_signal(
        self,
        signal_name: str,
        workflow_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        target: Optional[str] = None
    ) -> str:
        """
        Send a signal (stateless operation).

        Args:
            signal_name: Signal name
            workflow_id: Optional workflow ID
            payload: Signal payload
            target: Optional target

        Returns:
            Signal ID
        """
        try:
            from ...signals.stateless_signal_manager import StatelessSignalManager

            signal_id = await StatelessSignalManager.send_signal(
                self.redis_client,
                signal_name=signal_name,
                workflow_id=workflow_id,
                payload=payload,
                target=target
            )

            logger.info(f"Sent signal {signal_id} ({signal_name})")
            return signal_id

        except Exception as e:
            logger.error(f"Failed to send signal: {e}")
            raise

    async def register_signal_handler(
        self,
        signal_name: str,
        handler_id: str,
        handler_type: str = "workflow",
        handler_config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Register a signal handler (stateless operation).

        Args:
            signal_name: Signal to handle
            handler_id: Handler ID
            handler_type: Handler type
            handler_config: Handler configuration

        Returns:
            True if registered
        """
        try:
            from ...signals.stateless_signal_manager import StatelessSignalManager

            result = await StatelessSignalManager.register_handler(
                self.redis_client,
                signal_name=signal_name,
                handler_id=handler_id,
                handler_type=handler_type,
                handler_config=handler_config
            )

            if result:
                logger.info(f"Registered handler {handler_id} for signal {signal_name}")

            return result

        except Exception as e:
            logger.error(f"Failed to register signal handler: {e}")
            return False

    async def unregister_signal_handler(
        self,
        signal_name: str,
        handler_id: str
    ) -> bool:
        """
        Unregister a signal handler (stateless operation).

        Args:
            signal_name: Signal name
            handler_id: Handler ID

        Returns:
            True if unregistered
        """
        try:
            from ...signals.stateless_signal_manager import StatelessSignalManager

            result = await StatelessSignalManager.unregister_handler(
                self.redis_client,
                signal_name=signal_name,
                handler_id=handler_id
            )

            if result:
                logger.info(f"Unregistered handler {handler_id} for signal {signal_name}")

            return result

        except Exception as e:
            logger.error(f"Failed to unregister signal handler: {e}")
            return False

    async def get_workflow_signals(
        self,
        workflow_id: str,
        count: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get signals for a workflow (stateless query).

        Args:
            workflow_id: Workflow ID
            count: Maximum signals to retrieve

        Returns:
            List of signal data
        """
        try:
            from ...signals.stateless_signal_manager import StatelessSignalManager

            signals = await StatelessSignalManager.get_workflow_signals(
                self.redis_client,
                workflow_id=workflow_id,
                count=count
            )

            return signals

        except Exception as e:
            logger.error(f"Failed to get workflow signals: {e}")
            return []

    async def get_signal_statistics(self) -> Optional[Dict[str, Any]]:
        """Get signal statistics (stateless query)."""
        try:
            from ...signals.stateless_signal_manager import StatelessSignalManager

            stats = await StatelessSignalManager.get_signal_stats(self.redis_client)
            stats["stateless"] = True
            stats["has_loops"] = False

            return stats

        except Exception as e:
            logger.error(f"Failed to get signal statistics: {e}")
            return None

    async def shutdown_stateless_stream_signals(self):
        """Shutdown stateless signal support (no loops to stop!)."""
        logger.info("Stateless signal support shutdown (no loops to stop)")