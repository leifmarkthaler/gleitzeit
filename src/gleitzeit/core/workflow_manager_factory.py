"""
Factory for creating WorkflowManager instances.

This factory ensures WorkflowManager instances are properly configured
for stateless operation with shared persistence and event bus.
"""

import logging
from typing import Optional
from pathlib import Path

from .workflow_manager import WorkflowManager
from .stateless_dependency_manager import StatelessDependencyManager
from .execution_engine_v2 import ExecutionEngineV2
from ..events import StatelessEventBus
from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from .errors import SystemError

logger = logging.getLogger(__name__)


class WorkflowManagerFactory:
    """Factory for creating WorkflowManager instances."""
    
    @staticmethod
    async def create(
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[StatelessEventBus] = None,
        execution_engine: Optional[ExecutionEngineV2] = None,
        dependency_resolver: Optional[StatelessDependencyManager] = None,
        template_directory: Optional[Path] = None
    ) -> WorkflowManager:
        """
        Create a WorkflowManager instance with injected dependencies.
        
        Args:
            persistence: Shared persistence backend
            event_bus: Optional event bus for workflow events
            execution_engine: Optional execution engine (will create if not provided)
            dependency_resolver: Optional stateless dependency resolver
            template_directory: Optional directory for workflow templates
            
        Returns:
            Configured WorkflowManager instance
        """
        # Get Redis client for atomic operations if available
        redis_client = None
        if hasattr(persistence, 'redis') or hasattr(persistence, '_redis'):
            redis_client = getattr(persistence, 'redis', None) or getattr(persistence, '_redis', None)
        
        # Create stateless dependency resolver if not provided
        if not dependency_resolver:
            dependency_resolver = StatelessDependencyManager(persistence, redis_client)
            logger.info("Created StatelessDependencyManager for WorkflowManager")
        
        # Create execution engine if not provided
        if not execution_engine:
            from ..task_queue import QueueManager
            from ..providers.pooling_adapter import PoolingAdapter
            from ..providers.python_provider import PythonProvider
            
            queue_manager = QueueManager(persistence=persistence, event_bus=event_bus)
            
            # Create a minimal pooling adapter for standalone operation
            pooling_adapter = PoolingAdapter(
                persistence=persistence,
                min_pool_size=1,
                max_pool_size=3
            )
            await pooling_adapter.initialize()
            
            # Register Python provider by default
            await pooling_adapter.register_provider(
                provider_id="python_provider",
                protocol_id="python/v1",
                provider_instance=PythonProvider
            )
            logger.info("Created PoolingAdapter with Python provider for standalone WorkflowManager")
            
            execution_engine = ExecutionEngineV2(
                pooling_adapter=pooling_adapter,
                queue_manager=queue_manager,
                dependency_resolver=dependency_resolver,
                persistence=persistence,
                event_bus=event_bus
            )
            await execution_engine.start()
            logger.info("Created ExecutionEngine for WorkflowManager")
        
        # Create WorkflowManager
        workflow_manager = WorkflowManager(
            execution_engine=execution_engine,
            dependency_manager=dependency_resolver,
            persistence=persistence,
            event_bus=event_bus,
            template_directory=template_directory
        )
        
        logger.info("Created WorkflowManager instance")
        return workflow_manager
    
    @staticmethod
    async def create_from_system_manager(system_manager) -> WorkflowManager:
        """
        Create WorkflowManager using SystemManager's components.
        
        Args:
            system_manager: SystemManager instance with initialized components
            
        Returns:
            Configured WorkflowManager instance
        """
        if not system_manager._initialized:
            raise SystemError("SystemManager must be initialized first")
        
        return await WorkflowManagerFactory.create(
            persistence=system_manager.persistence,
            event_bus=system_manager.event_bus,
            execution_engine=system_manager.execution_engine,
            dependency_resolver=getattr(system_manager, 'dependency_resolver', None)
        )