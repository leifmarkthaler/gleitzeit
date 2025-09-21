"""
Stream providers mixin for provider management and registration.
"""

import logging
from typing import Optional, Dict, Any, Type

logger = logging.getLogger(__name__)


class StreamProvidersMixin:
    """
    Mixin providing provider management for stream-based system.

    This mixin handles:
    - Provider hub initialization
    - Provider registration and pooling
    - Protocol discovery and management
    """

    def __init__(self, **kwargs):
        """Initialize provider components."""
        self.provider_hub = None
        self.provider_hub_runner = None
        self.provider_hub_task = None
        super().__init__(**kwargs)

    async def initialize_stream_providers(self):
        """Initialize provider infrastructure."""
        try:
            logger.info("Initializing stream-based provider infrastructure")

            # Initialize provider hub
            await self._initialize_provider_hub()

            # Register default providers
            await self._register_default_providers()

            logger.info("Stream provider infrastructure initialized")

        except Exception as e:
            logger.error(f"Failed to initialize stream providers: {e}")
            # Don't raise - providers are optional for basic functionality

    async def _initialize_provider_hub(self):
        """Initialize provider hub for protocol management."""
        try:
            from ...hub.provider_hub_simple import SimpleProviderHub

            # Only start in non-Kubernetes deployments
            if hasattr(self, 'config'):
                from ...system.models import DeploymentMode
                deployment_mode = self.config.deployment_mode
                if isinstance(deployment_mode, str):
                    deployment_mode_str = deployment_mode
                else:
                    deployment_mode_str = deployment_mode.value

                if deployment_mode_str == "kubernetes":
                    logger.info("Skipping ProviderHub in Kubernetes mode (handled by K8s)")
                    return

            # Create and initialize hub with persistence for timer provider
            self.provider_hub = SimpleProviderHub(persistence=self.persistence)
            await self.provider_hub.initialize()

            # Connect ProviderHub to PoolingAdapter if available
            if hasattr(self, 'pooling_adapter') and self.pooling_adapter:
                self.pooling_adapter.provider_hub = self.provider_hub
                logger.info("Connected ProviderHub to PoolingAdapter")

                # Track discovered protocols in PoolingAdapter
                for protocol_id in self.provider_hub.providers.keys():
                    self.pooling_adapter._registered_protocols.add(protocol_id)

            # Connect ProviderHub to registry if available
            if hasattr(self, 'registry') and self.registry:
                self.registry.set_provider_hub(self.provider_hub)
                logger.info("Connected StatelessProtocolRegistry to ProviderHub")

                # Register hub providers in persistence for distributed discovery
                for protocol_id in self.provider_hub.providers.keys():
                    await self.registry.register_provider_in_persistence(
                        protocol_id,
                        {
                            "provider_id": f"{protocol_id}_provider",
                            "instance_id": self.instance_id,
                            "hub_based": True,
                            "capabilities": (
                                self.provider_hub.providers[protocol_id].get_supported_methods()
                                if hasattr(self.provider_hub.providers[protocol_id], 'get_supported_methods')
                                else []
                            )
                        }
                    )

            # Start HTTP server for the hub
            await self._start_provider_hub_server()

            logger.info("ProviderHub initialized")

        except Exception as e:
            logger.error(f"Failed to initialize provider hub: {e}")
            self.provider_hub = None

    async def _start_provider_hub_server(self):
        """Start the ProviderHub HTTP server."""
        if not self.provider_hub:
            return

        try:
            from aiohttp import web
            import asyncio

            # Define web handlers
            async def handle_execute(request):
                """Handle execution requests"""
                try:
                    data = await request.json()
                    protocol_id = data.get("protocol", "python/v1")
                    from ...core.jsonrpc import JSONRPCRequest
                    jsonrpc_request = JSONRPCRequest(**data.get("request", {}))

                    response = await self.provider_hub.execute_request(protocol_id, jsonrpc_request)
                    return web.json_response(response.dict())
                except Exception as e:
                    logger.error(f"Request handling error: {e}")
                    return web.json_response({"error": str(e)}, status=500)

            async def handle_health(request):
                """Health check"""
                return web.json_response({"status": "healthy"})

            async def handle_stats(request):
                """Get stats"""
                return web.json_response({
                    "protocols": list(self.provider_hub.providers.keys()),
                    "initialized": self.provider_hub._initialized
                })

            # Create web app
            app = web.Application()
            app.router.add_post('/execute', handle_execute)
            app.router.add_get('/health', handle_health)
            app.router.add_get('/stats', handle_stats)

            # Start server
            self.provider_hub_runner = web.AppRunner(app)
            await self.provider_hub_runner.setup()

            port = getattr(self.config, 'provider_hub_port', 9090)
            site = web.TCPSite(self.provider_hub_runner, '0.0.0.0', port)

            # Start in background
            self.provider_hub_task = asyncio.create_task(site.start())

            logger.info(f"ProviderHub HTTP server started on port {port}")

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="provider_hub_http",
                    component_type="hub",
                    metadata={
                        "url": f"http://localhost:{port}",
                        "protocols": list(self.provider_hub.providers.keys())
                    }
                )

        except Exception as e:
            logger.error(f"Failed to start ProviderHub server: {e}")

    async def _register_default_providers(self):
        """Register default providers with pooling adapter."""
        if not hasattr(self, 'pooling_adapter') or not self.pooling_adapter:
            logger.warning("PoolingAdapter not available - skipping provider registration")
            return

        try:
            from ...providers.python_provider import PythonProvider
            from ...providers.shell_provider import ShellProvider
            from ...providers.timer_provider import TimerProvider
            from ...providers.signal_provider import SignalProvider

            # Get default providers from config
            default_providers = getattr(self.config, 'default_providers', ["python"]) if hasattr(self, 'config') else ["python"]

            for provider_type in default_providers:
                if provider_type == "python":
                    await self.pooling_adapter.register_provider(
                        provider_id="python_provider",
                        protocol_id="python/v1",
                        provider_instance=PythonProvider
                    )
                    logger.info("Registered Python provider with pooling adapter")

                    # Register in persistence for distributed discovery
                    if hasattr(self, 'registry') and self.registry:
                        await self.registry.register_provider_in_persistence(
                            "python/v1",
                            {
                                "provider_id": "python_provider",
                                "instance_id": self.instance_id,
                                "capabilities": ["python/execute", "python/validate", "python/info"]
                            }
                        )

                elif provider_type == "shell":
                    await self.pooling_adapter.register_provider(
                        provider_id="shell_provider",
                        protocol_id="shell/v1",
                        provider_instance=ShellProvider
                    )
                    logger.info("Registered Shell provider with pooling adapter")

                    # Register in persistence for distributed discovery
                    if hasattr(self, 'registry') and self.registry:
                        await self.registry.register_provider_in_persistence(
                            "shell/v1",
                            {
                                "provider_id": "shell_provider",
                                "instance_id": self.instance_id,
                                "capabilities": ["shell/execute", "shell/validate", "shell/info"]
                            }
                        )

            # ALWAYS register Timer and Signal providers - they're needed for workflow tasks
            # Timer Provider - for workflow tasks with protocol: timer/v1
            # Note: PoolingAdapter will pass persistence when creating instances
            await self.pooling_adapter.register_provider(
                provider_id="timer_provider",
                protocol_id="timer/v1",
                provider_instance=TimerProvider  # Pass class, pooling adapter creates instances with persistence
            )
            logger.info("Registered Timer provider for workflow tasks")

            # Register in persistence for distributed discovery
            if hasattr(self, 'registry') and self.registry:
                await self.registry.register_provider_in_persistence(
                    "timer/v1",
                    {
                        "provider_id": "timer_provider",
                        "instance_id": self.instance_id,
                        "capabilities": ["timer/sleep", "timer/wait_until", "timer/wait_or_signal"]
                    }
                )

            # Signal Provider - for workflow tasks with protocol: signal/v1
            await self.pooling_adapter.register_provider(
                provider_id="signal_provider",
                protocol_id="signal/v1",
                provider_instance=SignalProvider
            )
            logger.info("Registered Signal provider for workflow tasks")

            # Register in persistence for distributed discovery
            if hasattr(self, 'registry') and self.registry:
                await self.registry.register_provider_in_persistence(
                    "signal/v1",
                    {
                        "provider_id": "signal_provider",
                        "instance_id": self.instance_id,
                        "capabilities": ["signal/wait", "signal/wait_any", "signal/wait_all", "signal/send"]
                    }
                )

            logger.info(f"Registered {len(default_providers) + 2} providers (including timer/signal)")

        except Exception as e:
            logger.error(f"Failed to register default providers: {e}")

    async def shutdown_stream_providers(self):
        """Shutdown provider infrastructure."""
        logger.info("Shutting down provider infrastructure")

        try:
            # Shutdown ProviderHub HTTP server
            if self.provider_hub_runner:
                await self.provider_hub_runner.cleanup()
                self.provider_hub_runner = None

            if self.provider_hub_task:
                self.provider_hub_task.cancel()
                try:
                    await self.provider_hub_task
                except asyncio.CancelledError:
                    pass
                self.provider_hub_task = None

            # Cleanup ProviderHub
            if self.provider_hub:
                if hasattr(self.provider_hub, 'cleanup'):
                    await self.provider_hub.cleanup()
                self.provider_hub = None

            # Deregister providers from persistence
            if hasattr(self, 'registry') and self.registry:
                protocols_to_deregister = []

                # Check pooling adapter for registered protocols
                if hasattr(self, 'pooling_adapter') and self.pooling_adapter:
                    protocols_to_deregister.extend(self.pooling_adapter._registered_protocols)

                # Deregister each protocol
                for protocol_id in set(protocols_to_deregister):
                    try:
                        await self.registry.deregister_provider_from_persistence(
                            protocol_id,
                            instance_id=self.instance_id
                        )
                        logger.info(f"Deregistered provider {protocol_id} from persistence")
                    except Exception as e:
                        logger.error(f"Error deregistering provider {protocol_id}: {e}")

        except Exception as e:
            logger.error(f"Error shutting down providers: {e}")

        logger.info("Provider infrastructure shutdown complete")

    # Provider management interface
    async def register_provider(self, provider_class: Type, provider_id: str, protocol_id: str,
                              config: Optional[Dict[str, Any]] = None) -> bool:
        """Register a provider."""
        if not hasattr(self, 'pooling_adapter') or not self.pooling_adapter:
            logger.warning("PoolingAdapter not available")
            return False

        try:
            await self.pooling_adapter.register_provider(
                provider_id=provider_id,
                protocol_id=protocol_id,
                provider_instance=provider_class
            )

            # Register in persistence for distributed discovery
            if hasattr(self, 'registry') and self.registry:
                capabilities = []
                if hasattr(provider_class, 'get_supported_methods'):
                    capabilities = provider_class.get_supported_methods()

                await self.registry.register_provider_in_persistence(
                    protocol_id,
                    {
                        "provider_id": provider_id,
                        "instance_id": self.instance_id,
                        "capabilities": capabilities
                    }
                )

            logger.info(f"Registered provider {provider_id} for protocol {protocol_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to register provider {provider_id}: {e}")
            return False

    def get_available_protocols(self) -> list:
        """Get list of available protocols."""
        protocols = []

        if hasattr(self, 'pooling_adapter') and self.pooling_adapter:
            protocols.extend(self.pooling_adapter._registered_protocols)

        if self.provider_hub:
            protocols.extend(self.provider_hub.providers.keys())

        return list(set(protocols))

    def get_provider_statistics(self) -> Dict[str, Any]:
        """Get provider statistics."""
        stats = {
            "available_protocols": self.get_available_protocols(),
            "provider_hub_active": self.provider_hub is not None,
            "http_server_active": self.provider_hub_task is not None
        }

        if hasattr(self, 'pooling_adapter') and self.pooling_adapter:
            stats["pooling_adapter"] = {
                "registered_protocols": list(self.pooling_adapter._registered_protocols),
                "active": True
            }

        if self.provider_hub:
            stats["provider_hub"] = {
                "protocols": list(self.provider_hub.providers.keys()),
                "initialized": getattr(self.provider_hub, '_initialized', False)
            }

        return stats