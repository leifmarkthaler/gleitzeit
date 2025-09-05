"""
Client adapter for orchestration MVP

Bridges the new orchestration components with the existing client infrastructure.
"""

import asyncio
import logging
from typing import Dict, Optional, Any

from gleitzeit.client.adapters.native import NativeAdapter
from gleitzeit.orchestration.coordinator_mvp import WorkflowCoordinatorMVP
from gleitzeit.orchestration.provider_pull import ProviderPullAdapter, ProviderPoolManager
from gleitzeit.core.models import Workflow, WorkflowExecution, WorkflowStatus
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType

logger = logging.getLogger(__name__)


class OrchestrationAdapter(NativeAdapter):
    """
    Adapter that uses orchestration components instead of direct execution.
    Minimal changes to existing client interface for MVP testing.
    """
    
    def __init__(self, *args, **kwargs):
        # Extract orchestration-specific kwargs
        use_orchestration = kwargs.pop('use_orchestration', True)
        provider_pool_size = kwargs.pop('provider_pool_size', 1)
        
        # Initialize parent
        super().__init__(*args, **kwargs)
        
        self.use_orchestration = use_orchestration
        self.provider_pool_size = provider_pool_size
        
        if self.use_orchestration:
            # Initialize orchestration components
            self._init_orchestration()
        
    def _init_orchestration(self):
        """Initialize orchestration components"""
        logger.info("Initializing orchestration adapter")
        
        # Create event bus if not exists
        if not hasattr(self, 'event_bus'):
            self.event_bus = EventBus()
        
        # Create coordinator
        self.coordinator = WorkflowCoordinatorMVP(
            persistence=self.persistence,
            event_bus=self.event_bus,
            node_id=f"client-{self.client_id}"
        )
        
        # Create provider pool manager
        self.provider_pool = ProviderPoolManager(
            event_bus=self.event_bus,
            redis_client=self.persistence.redis if hasattr(self.persistence, 'redis') else None
        )
        
        # Start provider adapters for registered providers
        asyncio.create_task(self._start_provider_adapters())
        
        logger.info("Orchestration adapter initialized")
    
    async def _start_provider_adapters(self):
        """Start pull adapters for each registered provider"""
        await asyncio.sleep(0.1)  # Let initialization complete
        
        # Check if providers are registered
        if hasattr(self, 'providers') and self.providers:
            for protocol, provider in self.providers.items():
                logger.info(f"Starting pull adapter for protocol: {protocol}")
                
                # Add provider to pool
                await self.provider_pool.add_provider(
                    provider=provider,
                    instances=self.provider_pool_size,
                    poll_interval=0.5
                )
            
            # Start the pool
            asyncio.create_task(self.provider_pool.start())
            logger.info(f"Started provider pool with {len(self.providers)} protocols")
        else:
            logger.warning("No providers registered, provider adapters not started")
    
    async def execute_workflow(self, workflow: Workflow) -> WorkflowExecution:
        """
        Execute workflow using orchestration components
        
        Overrides the parent method to use coordinator instead of execution engine.
        """
        if not self.use_orchestration:
            # Fall back to parent implementation
            return await super().execute_workflow(workflow)
        
        logger.info(f"Executing workflow {workflow.id} via orchestration")
        
        # Submit to coordinator
        workflow_id = await self.coordinator.submit_workflow(workflow)
        
        # Create execution object for compatibility
        execution = WorkflowExecution(
            workflow_id=workflow_id,
            workflow=workflow,
            status=WorkflowStatus.RUNNING,
            created_at=workflow.created_at
        )
        
        # Track execution for get_workflow_status compatibility
        if not hasattr(self, '_workflow_executions'):
            self._workflow_executions = {}
        self._workflow_executions[workflow_id] = execution
        
        # Set up event handlers for execution updates
        self._setup_execution_tracking(workflow_id, execution)
        
        return execution
    
    def _setup_execution_tracking(self, workflow_id: str, execution: WorkflowExecution):
        """Set up event handlers to track execution state"""
        
        async def update_on_completion(event: GleitzeitEvent):
            if event.data.get("workflow_id") == workflow_id:
                execution.status = WorkflowStatus.COMPLETED
                execution.completed_at = event.data.get("timestamp")
                logger.info(f"Workflow {workflow_id} completed")
        
        async def update_on_failure(event: GleitzeitEvent):
            if event.data.get("workflow_id") == workflow_id:
                execution.status = WorkflowStatus.FAILED
                execution.error = event.data.get("reason", "Unknown error")
                logger.error(f"Workflow {workflow_id} failed: {execution.error}")
        
        self.event_bus.register(EventType.WORKFLOW_COMPLETED, update_on_completion)
        self.event_bus.register(EventType.WORKFLOW_FAILED, update_on_failure)
    
    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """
        Get workflow status from coordinator
        
        Overrides parent to use coordinator's status tracking.
        """
        if not self.use_orchestration:
            return await super().get_workflow_status(workflow_id)
        
        # Get status from coordinator
        return self.coordinator.get_workflow_status(workflow_id)
    
    async def shutdown(self):
        """Shutdown orchestration components"""
        if self.use_orchestration and hasattr(self, 'provider_pool'):
            logger.info("Shutting down orchestration adapter")
            await self.provider_pool.stop()
        
        # Call parent shutdown
        await super().shutdown()


class OrchestrationClient:
    """
    Simplified client for testing orchestration MVP
    
    This is a minimal client that bypasses the full client stack
    for easier testing of orchestration components.
    """
    
    def __init__(
        self,
        persistence_backend,
        providers: Optional[Dict[str, Any]] = None
    ):
        self.persistence = persistence_backend
        self.providers = providers or {}
        self.event_bus = EventBus()
        
        # Create coordinator
        self.coordinator = WorkflowCoordinatorMVP(
            persistence=self.persistence,
            event_bus=self.event_bus,
            node_id="test-client"
        )
        
        # Create and start provider adapters
        self.adapters = []
        self._running = False
        
    async def start(self):
        """Start the client and provider adapters"""
        if self._running:
            return
        
        self._running = True
        
        # Start adapter for each provider
        for protocol, provider in self.providers.items():
            adapter = ProviderPullAdapter(
                provider=provider,
                event_bus=self.event_bus,
                redis_client=self.persistence.redis if hasattr(self.persistence, 'redis') else None,
                poll_interval=0.1
            )
            
            # Start adapter in background
            adapter_task = asyncio.create_task(adapter.start())
            self.adapters.append((adapter, adapter_task))
            
            logger.info(f"Started adapter for protocol: {protocol}")
    
    async def stop(self):
        """Stop all adapters"""
        if not self._running:
            return
        
        self._running = False
        
        # Stop all adapters
        for adapter, task in self.adapters:
            await adapter.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        logger.info("Stopped all adapters")
    
    async def execute_workflow(self, workflow: Workflow) -> str:
        """Execute a workflow"""
        return await self.coordinator.submit_workflow(workflow)
    
    def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow status"""
        return self.coordinator.get_workflow_status(workflow_id)
    
    async def wait_for_workflow(
        self, 
        workflow_id: str, 
        timeout: float = 30.0
    ) -> WorkflowStatus:
        """Wait for workflow to complete"""
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.get_workflow_status(workflow_id)
            if status:
                workflow_status = WorkflowStatus(status["status"])
                if workflow_status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]:
                    return workflow_status
            
            await asyncio.sleep(0.1)
        
        raise TimeoutError(f"Workflow {workflow_id} did not complete within {timeout} seconds")