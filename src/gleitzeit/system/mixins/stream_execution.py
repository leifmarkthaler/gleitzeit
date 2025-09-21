"""
Stream execution mixin providing workflow and task execution via streams.
"""

import logging
from typing import Optional, Dict, Any

from ...core.errors import SystemManagerError

logger = logging.getLogger(__name__)


class StreamExecutionMixin:
    """
    Mixin providing stream-based execution engine and workflow management.

    This mixin handles:
    - Stream-based execution engine
    - Workflow manager with stream integration
    - Queue manager for task distribution
    - Provider pooling and registry
    - Dependency management
    """

    def __init__(self, **kwargs):
        """Initialize execution components."""
        # Execution components
        self.execution_engine = None
        self.workflow_manager = None
        self.workflow_loader = None
        self.queue_manager = None
        self.pooling_adapter = None
        self.dependency_manager = None
        self.registry = None

        super().__init__(**kwargs)

    async def initialize_stream_execution(self):
        """Initialize stream-based execution infrastructure."""
        try:
            logger.info("Initializing stream-based execution infrastructure")

            # Initialize stateless registry
            await self._initialize_stateless_registry()

            # Initialize dependency manager
            await self._initialize_dependency_manager()

            # Initialize pooling adapter
            await self._initialize_pooling_adapter()

            # Initialize queue manager
            await self._initialize_queue_manager()

            # Register basic providers early for workflow loader validation
            await self._register_basic_providers_early()

            # Initialize execution engine
            await self._initialize_execution_engine()

            # Initialize workflow manager
            await self._initialize_workflow_manager()

            # Initialize workflow loader (needs providers for validation)
            await self._initialize_workflow_loader()

            logger.info("Stream-based execution infrastructure initialized")

        except Exception as e:
            logger.error(f"Failed to initialize stream execution: {e}")
            raise SystemManagerError("Stream execution initialization failed", cause=e)

    async def _initialize_stateless_registry(self):
        """Initialize stateless protocol registry."""
        try:
            from ...registry_stateless import StatelessProtocolRegistry

            self.registry = StatelessProtocolRegistry(persistence=self.persistence)
            # StatelessProtocolRegistry doesn't need initialization - it's stateless
            logger.info("StatelessProtocolRegistry created")

        except Exception as e:
            logger.error(f"Failed to initialize stateless registry: {e}")
            raise

    async def _initialize_dependency_manager(self):
        """Initialize dependency manager."""
        try:
            from ...core.stateless_dependency_manager import StatelessDependencyManager

            # Get Redis client for atomic operations if available
            redis_client = getattr(self.persistence, 'redis', None)
            self.dependency_manager = StatelessDependencyManager(self.persistence, redis_client)

            if redis_client:
                logger.info("StatelessDependencyManager initialized with atomic operations")
            else:
                logger.info("StatelessDependencyManager initialized (limited atomic operations)")

        except Exception as e:
            logger.error(f"Failed to initialize dependency manager: {e}")
            raise

    async def _initialize_pooling_adapter(self):
        """Initialize provider pooling adapter."""
        try:
            from ...providers.pooling_adapter import PoolingAdapter

            self.pooling_adapter = PoolingAdapter(
                persistence=self.persistence,
                min_pool_size=1,
                max_pool_size=5,
                provider_hub=None,  # Will be set by provider mixin
                stateless_registry=self.registry
            )
            await self.pooling_adapter.initialize()

            # Connect registry to pooling adapter
            if self.registry:
                self.registry.set_pooling_adapter(self.pooling_adapter)

            logger.info("PoolingAdapter initialized")

        except Exception as e:
            logger.error(f"Failed to initialize pooling adapter: {e}")
            raise

    async def _register_basic_providers_early(self):
        """Register basic providers early for workflow loader validation."""
        if not self.pooling_adapter:
            logger.warning("PoolingAdapter not available for early provider registration")
            return

        try:
            from ...providers.python_provider import PythonProvider

            # Register Python provider early (most common, needed for workflow validation)
            await self.pooling_adapter.register_provider(
                provider_id="python_provider",
                protocol_id="python/v1",
                provider_instance=PythonProvider
            )
            logger.info("Registered Python provider early for workflow validation")

        except Exception as e:
            logger.warning(f"Could not register providers early: {e}")
            # Non-critical, providers will be registered later

    async def _initialize_queue_manager(self):
        """Initialize task queue manager."""
        try:
            from ...task_queue import QueueManager

            self.queue_manager = QueueManager(
                persistence=self.persistence,
                event_bus=self.event_bus,
                transport=None  # Stream transport handled through event bus
            )

            logger.info("QueueManager initialized")

        except Exception as e:
            logger.error(f"Failed to initialize queue manager: {e}")
            raise

    async def _initialize_execution_engine(self):
        """Initialize stream-based execution engine."""
        try:
            # Try to use stream execution engine if available
            try:
                from ...core.stream_execution_engine import StreamExecutionEngine

                self.execution_engine = StreamExecutionEngine(
                    pooling_adapter=self.pooling_adapter,
                    queue_manager=self.queue_manager,
                    stream_scheduler=getattr(self, 'event_scheduler', None),
                    dependency_resolver=self.dependency_manager,
                    persistence=self.persistence,
                    event_bus=self.event_bus,
                    instance_id=f"{self.instance_id}-execution"
                )

                await self.execution_engine.initialize()
                await self.execution_engine.start()

                logger.info("StreamExecutionEngine initialized")

            except ImportError:
                # Fall back to regular execution engine
                from ...core.execution_engine_v2 import ExecutionEngineV2

                self.execution_engine = ExecutionEngineV2(
                    pooling_adapter=self.pooling_adapter,
                    queue_manager=self.queue_manager,
                    dependency_resolver=self.dependency_manager,
                    persistence=self.persistence,
                    event_bus=self.event_bus
                )
                await self.execution_engine.start()

                logger.info("ExecutionEngineV2 initialized (fallback)")

            # Register handlers with stream manager if possible
            if hasattr(self.execution_engine, 'register_with_stream_manager'):
                self.execution_engine.register_with_stream_manager(self)

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="execution_engine",
                    component_type="service",
                    metadata={
                        "instance_id": self.instance_id,
                        "stream_based": True,
                        "type": self.execution_engine.__class__.__name__
                    }
                )

        except Exception as e:
            logger.error(f"Failed to initialize execution engine: {e}")
            raise

    async def _initialize_workflow_manager(self):
        """Initialize workflow manager."""
        try:
            from ...core.workflow_manager import WorkflowManager

            self.workflow_manager = WorkflowManager(
                execution_engine=self.execution_engine,
                dependency_manager=self.dependency_manager,
                persistence=self.persistence,
                event_bus=self.event_bus
            )

            # Register handlers with stream manager if possible
            if hasattr(self.workflow_manager, 'register_with_stream_manager'):
                self.workflow_manager.register_with_stream_manager(self)

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="workflow_manager",
                    component_type="service",
                    metadata={
                        "instance_id": self.instance_id,
                        "stream_based": True,
                        "features": ["templates", "scheduling", "policies"]
                    }
                )

            logger.info("WorkflowManager initialized")

        except Exception as e:
            logger.error(f"Failed to initialize workflow manager: {e}")
            raise

    async def _initialize_workflow_loader(self):
        """Initialize workflow loader."""
        try:
            from ...core.workflow_loader_v2 import WorkflowLoaderV2, WorkflowLoaderConfig

            # Configure loader based on deployment mode
            loader_config = WorkflowLoaderConfig()

            # Set resource limits based on deployment mode
            if hasattr(self, 'config'):
                from ...system.models import DeploymentMode
                deployment_mode = self.config.deployment_mode
                if isinstance(deployment_mode, str):
                    deployment_mode_str = deployment_mode
                else:
                    deployment_mode_str = deployment_mode.value

                if deployment_mode_str == "development":
                    loader_config.MAX_TASKS_PER_WORKFLOW = 1000
                    loader_config.MAX_WORKFLOW_SIZE_MB = 10
                elif deployment_mode_str == "staging":
                    loader_config.MAX_TASKS_PER_WORKFLOW = 5000
                    loader_config.MAX_WORKFLOW_SIZE_MB = 50
                else:  # Production/Kubernetes
                    loader_config.MAX_TASKS_PER_WORKFLOW = 10000
                    loader_config.MAX_WORKFLOW_SIZE_MB = 100

            # Enable caching
            loader_config.ENABLE_CACHING = True
            loader_config.CACHE_TTL_SECONDS = 300

            self.workflow_loader = WorkflowLoaderV2(
                config=loader_config,
                registry=self.registry
            )

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="workflow_loader",
                    component_type="service",
                    metadata={
                        "max_tasks": loader_config.MAX_TASKS_PER_WORKFLOW,
                        "max_size_mb": loader_config.MAX_WORKFLOW_SIZE_MB,
                        "caching_enabled": loader_config.ENABLE_CACHING
                    }
                )

            logger.info("WorkflowLoaderV2 initialized")

        except Exception as e:
            logger.error(f"Failed to initialize workflow loader: {e}")
            # Non-critical, continue without loader
            self.workflow_loader = None

    async def shutdown_stream_execution(self):
        """Shutdown stream execution infrastructure."""
        logger.info("Shutting down stream execution infrastructure")

        try:
            # Shutdown in reverse order
            if self.workflow_manager:
                if hasattr(self.workflow_manager, 'stop_scheduler'):
                    await self.workflow_manager.stop_scheduler()

            if self.execution_engine:
                await self.execution_engine.stop()

            if self.queue_manager:
                await self.queue_manager.shutdown()

            if self.pooling_adapter:
                await self.pooling_adapter.shutdown()

        except Exception as e:
            logger.error(f"Error shutting down stream execution: {e}")

        logger.info("Stream execution infrastructure shutdown complete")

    # Workflow management interface
    async def submit_workflow(self, workflow) -> str:
        """Submit a workflow for execution."""
        if not self.workflow_manager:
            raise SystemManagerError("WorkflowManager not initialized")

        # If workflow_loader is available, process workflow through it for validation
        if self.workflow_loader:
            from ...core.models import Workflow

            # If it's already a Workflow object, assume it's been validated
            if isinstance(workflow, Workflow):
                return await self.workflow_manager.submit_workflow(workflow)

            # Otherwise it's a dict that needs validation
            workflow_dict = workflow

            # Process through workflow_loader for validation and ID generation
            try:
                validated_workflow = self.workflow_loader.load_workflow_from_dict(workflow_dict)
                return await self.workflow_manager.submit_workflow(validated_workflow)
            except Exception as e:
                from ...core.errors import WorkflowValidationError
                raise WorkflowValidationError(
                    workflow_id=workflow_dict.get('id', 'unknown'),
                    validation_errors=[str(e)]
                )

        # Direct submission if no loader
        return await self.workflow_manager.submit_workflow(workflow)

    async def get_workflow(self, workflow_id: str):
        """Get workflow by ID."""
        if not self.workflow_manager:
            raise SystemManagerError("WorkflowManager not initialized")
        # Use persistence directly for now
        return await self.persistence.get_workflow(workflow_id)

    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel a workflow."""
        if not self.workflow_manager:
            raise SystemManagerError("WorkflowManager not initialized")
        return await self.workflow_manager.cancel_workflow(workflow_id)

    # Task management interface
    async def submit_task(self, task) -> str:
        """Submit a task for execution."""
        if not self.execution_engine:
            raise SystemManagerError("ExecutionEngine not initialized")
        return await self.execution_engine.submit_task(task)

    async def get_task_result(self, task_id: str):
        """Get task result by ID."""
        if not self.execution_engine:
            raise SystemManagerError("ExecutionEngine not initialized")
        return await self.persistence.get_task_result(task_id)

    def get_workflow_loader(self):
        """Get workflow loader instance."""
        return self.workflow_loader