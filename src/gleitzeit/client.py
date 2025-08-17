"""
Gleitzeit Client with Unified Persistence

This module provides the main client interface for Gleitzeit with:
- Automatic persistence fallback (Redis -> SQL -> Memory)
- Unified task and resource management
- Cross-domain operations linking tasks to resources
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics
from gleitzeit.persistence.factory import PersistenceManager, PersistenceType
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter
from gleitzeit.task_queue.task_queue import TaskQueue, QueueManager

logger = logging.getLogger(__name__)


class GleitzeitClient:
    """
    Main client for Gleitzeit with unified persistence
    
    Features:
    - Automatic persistence fallback (Redis -> SQL -> Memory)
    - Unified task and resource management
    - Queue management with persistence
    - Cross-domain operations
    
    Usage:
        # Create client with automatic persistence selection
        client = GleitzeitClient()
        await client.initialize()
        
        # Submit a task
        task = await client.submit_task(
            name="Process data",
            protocol="python",
            method="process",
            params={"data": "..."}
        )
        
        # Check task status
        status = await client.get_task_status(task.id)
        
        # Get resource utilization
        utilization = await client.get_resource_utilization("ollama-hub")
    """
    
    def __init__(
        self,
        persistence_type: Optional[str] = None,
        redis_url: Optional[str] = None,
        sql_connection: Optional[str] = None,
        sql_db_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the Gleitzeit client
        
        Args:
            persistence_type: Force specific persistence ("redis", "sql", "memory", "auto")
            redis_url: Redis connection URL
            sql_connection: SQL connection string
            sql_db_path: SQLite database path
            config: Additional configuration
        """
        self.persistence_type = persistence_type
        self.redis_url = redis_url
        self.sql_connection = sql_connection
        self.sql_db_path = sql_db_path
        self.config = config or {}
        
        self.adapter: Optional[UnifiedPersistenceAdapter] = None
        self.queue_manager: Optional[QueueManager] = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """
        Initialize the client and persistence layer
        
        This method:
        1. Initializes persistence with automatic fallback
        2. Sets up the queue manager
        3. Recovers any existing state
        """
        if self._initialized:
            logger.warning("Client already initialized")
            return
        
        try:
            # Initialize persistence with fallback chain
            if not PersistenceManager.is_initialized():
                ptype = None
                if self.persistence_type:
                    try:
                        ptype = PersistenceType(self.persistence_type.lower())
                    except ValueError:
                        logger.warning(f"Unknown persistence type '{self.persistence_type}', using AUTO")
                
                self.adapter = await PersistenceManager.initialize(
                    persistence_type=ptype,
                    redis_url=self.redis_url,
                    sql_connection=self.sql_connection,
                    sql_db_path=self.sql_db_path,
                    config=self.config
                )
            else:
                self.adapter = PersistenceManager.get_adapter()
            
            # Log which persistence backend is being used
            adapter_type = type(self.adapter).__name__
            logger.info(f"Gleitzeit client initialized with {adapter_type}")
            
            # Initialize queue manager with persistence
            self.queue_manager = QueueManager()
            
            # Set persistence for default queue
            default_queue = self.queue_manager.get_default_queue()
            default_queue.persistence = self.adapter
            await default_queue.initialize()
            
            self._initialized = True
            logger.info("Gleitzeit client fully initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Gleitzeit client: {e}")
            raise
    
    async def shutdown(self) -> None:
        """Shutdown the client and cleanup resources"""
        if not self._initialized:
            return
        
        try:
            # Shutdown queue manager
            if self.queue_manager:
                await self.queue_manager.shutdown()
            
            # Shutdown persistence
            await PersistenceManager.shutdown()
            
            self._initialized = False
            logger.info("Gleitzeit client shut down")
            
        except Exception as e:
            logger.error(f"Error during client shutdown: {e}")
            raise
    
    # =========================================================================
    # Task Management
    # =========================================================================
    
    async def submit_task(
        self,
        name: str,
        protocol: str,
        method: str,
        params: Dict[str, Any],
        priority: str = "normal",
        dependencies: Optional[List[str]] = None,
        workflow_id: Optional[str] = None,
        queue_name: Optional[str] = None
    ) -> Task:
        """
        Submit a new task for execution
        
        Args:
            name: Task name
            protocol: Protocol identifier (e.g., "llm", "python")
            method: Method to execute
            params: Task parameters
            priority: Task priority ("urgent", "high", "normal", "low")
            dependencies: List of task IDs this task depends on
            workflow_id: Parent workflow ID
            queue_name: Target queue name (uses default if None)
            
        Returns:
            Created task
        """
        self._ensure_initialized()
        
        # Create task
        task = Task(
            name=name,
            protocol=protocol,
            method=method,
            params=params,
            priority=priority,
            dependencies=dependencies,
            workflow_id=workflow_id
        )
        
        # Save to persistence
        await self.adapter.save_task(task)
        
        # Enqueue for execution
        await self.queue_manager.enqueue_task(task, queue_name)
        
        logger.info(f"Submitted task {task.id}: {name}")
        return task
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        self._ensure_initialized()
        return await self.adapter.get_task(task_id)
    
    async def get_task_status(self, task_id: str) -> Optional[str]:
        """Get the status of a task"""
        task = await self.get_task(task_id)
        return task.status if task else None
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get the result of a completed task"""
        self._ensure_initialized()
        return await self.adapter.get_task_result(task_id)
    
    async def wait_for_task(
        self,
        task_id: str,
        timeout: Optional[float] = None,
        poll_interval: float = 1.0
    ) -> Optional[TaskResult]:
        """
        Wait for a task to complete and return its result
        
        Args:
            task_id: Task ID to wait for
            timeout: Maximum time to wait in seconds
            poll_interval: Interval between status checks
            
        Returns:
            Task result if completed, None if timeout
        """
        self._ensure_initialized()
        
        start_time = datetime.utcnow()
        
        while True:
            # Check task status
            task = await self.get_task(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found")
                return None
            
            # Check if completed
            if task.status in ["completed", "failed"]:
                return await self.get_task_result(task_id)
            
            # Check timeout
            if timeout:
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed >= timeout:
                    logger.warning(f"Timeout waiting for task {task_id}")
                    return None
            
            # Wait before next check
            await asyncio.sleep(poll_interval)
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a queued task
        
        Args:
            task_id: Task ID to cancel
            
        Returns:
            True if task was cancelled, False if not found or already executing
        """
        self._ensure_initialized()
        
        task = await self.get_task(task_id)
        if not task:
            return False
        
        if task.status != "queued":
            logger.warning(f"Cannot cancel task {task_id} with status {task.status}")
            return False
        
        # Remove from queue
        for queue in self.queue_manager.queues.values():
            if await queue.remove_task(task_id):
                # Update task status
                task.status = "cancelled"
                await self.adapter.save_task(task)
                logger.info(f"Cancelled task {task_id}")
                return True
        
        return False
    
    # =========================================================================
    # Workflow Management
    # =========================================================================
    
    async def submit_workflow(
        self,
        name: str,
        tasks: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Workflow:
        """
        Submit a workflow for execution
        
        Args:
            name: Workflow name
            tasks: List of task definitions
            metadata: Optional workflow metadata
            
        Returns:
            Created workflow
        """
        self._ensure_initialized()
        
        # Create workflow
        workflow = Workflow(
            name=name,
            tasks=tasks,
            metadata=metadata or {}
        )
        
        # Save to persistence
        await self.adapter.save_workflow(workflow)
        
        # Create workflow execution
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            status="pending",
            progress={"current_task": 0, "total_tasks": len(tasks)}
        )
        await self.adapter.save_workflow_execution(execution)
        
        # Create and enqueue tasks
        for task_def in tasks:
            task = Task(
                name=task_def.get("name", "Workflow Task"),
                protocol=task_def["protocol"],
                method=task_def["method"],
                params=task_def.get("params", {}),
                priority=task_def.get("priority", "normal"),
                dependencies=task_def.get("dependencies", []),
                workflow_id=workflow.id
            )
            await self.adapter.save_task(task)
            await self.queue_manager.enqueue_task(task)
        
        logger.info(f"Submitted workflow {workflow.id}: {name} with {len(tasks)} tasks")
        return workflow
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID"""
        self._ensure_initialized()
        return await self.adapter.get_workflow(workflow_id)
    
    async def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get workflow execution status"""
        self._ensure_initialized()
        return await self.adapter.get_workflow_execution(execution_id)
    
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow"""
        self._ensure_initialized()
        return await self.adapter.get_tasks_by_workflow(workflow_id)
    
    # =========================================================================
    # Resource Management
    # =========================================================================
    
    async def register_resource(
        self,
        hub_id: str,
        instance: ResourceInstance
    ) -> None:
        """Register a resource instance with a hub"""
        self._ensure_initialized()
        await self.adapter.save_instance(hub_id, instance)
        logger.info(f"Registered resource {instance.id} with hub {hub_id}")
    
    async def get_resource(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Get a resource instance by ID"""
        self._ensure_initialized()
        return await self.adapter.load_instance(instance_id)
    
    async def list_resources(self, hub_id: str) -> List[Dict[str, Any]]:
        """List all resources for a hub"""
        self._ensure_initialized()
        return await self.adapter.list_instances(hub_id)
    
    async def save_resource_metrics(
        self,
        instance_id: str,
        metrics: ResourceMetrics
    ) -> None:
        """Save metrics for a resource instance"""
        self._ensure_initialized()
        await self.adapter.save_metrics(instance_id, metrics)
    
    async def get_resource_metrics(
        self,
        instance_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Get historical metrics for a resource"""
        self._ensure_initialized()
        return await self.adapter.get_metrics_history(instance_id, start_time, end_time)
    
    # =========================================================================
    # Cross-Domain Operations
    # =========================================================================
    
    async def get_tasks_for_resource(self, resource_id: str) -> List[Task]:
        """Get all tasks assigned to a specific resource"""
        self._ensure_initialized()
        return await self.adapter.get_tasks_for_resource(resource_id)
    
    async def get_resource_for_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get the resource assigned to a task"""
        self._ensure_initialized()
        return await self.adapter.get_resource_for_task(task_id)
    
    async def get_resource_utilization(self, hub_id: str) -> Dict[str, Any]:
        """Get resource utilization statistics for a hub"""
        self._ensure_initialized()
        return await self.adapter.get_resource_utilization(hub_id)
    
    # =========================================================================
    # Statistics and Monitoring
    # =========================================================================
    
    async def get_task_statistics(self) -> Dict[str, int]:
        """Get task count by status"""
        self._ensure_initialized()
        return await self.adapter.get_task_count_by_status()
    
    async def get_queue_statistics(self) -> Dict[str, Any]:
        """Get queue statistics"""
        self._ensure_initialized()
        return await self.queue_manager.get_global_stats()
    
    async def cleanup_old_data(self, days: int = 30) -> int:
        """
        Clean up old completed tasks and results
        
        Args:
            days: Number of days to keep data
            
        Returns:
            Number of items deleted
        """
        self._ensure_initialized()
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        return await self.adapter.cleanup_old_data(cutoff)
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _ensure_initialized(self) -> None:
        """Ensure the client is initialized"""
        if not self._initialized:
            raise RuntimeError("Client not initialized. Call initialize() first.")
    
    @property
    def persistence_backend(self) -> str:
        """Get the name of the current persistence backend"""
        if self.adapter:
            return type(self.adapter).__name__
        return "Not initialized"
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the client
        
        Returns:
            Health status information
        """
        self._ensure_initialized()
        
        health = {
            "status": "healthy",
            "persistence_backend": self.persistence_backend,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        try:
            # Test persistence with a simple operation
            test_task = Task(
                id="__health_check__",
                name="Health Check",
                protocol="test",
                method="test",
                params={},
                priority="low"
            )
            
            await self.adapter.save_task(test_task)
            retrieved = await self.adapter.get_task("__health_check__")
            await self.adapter.delete_task("__health_check__")
            
            if not retrieved:
                health["status"] = "degraded"
                health["errors"] = ["Persistence test failed"]
            
            # Get statistics
            health["task_stats"] = await self.get_task_statistics()
            health["queue_stats"] = await self.get_queue_statistics()
            
        except Exception as e:
            health["status"] = "unhealthy"
            health["errors"] = [str(e)]
        
        return health


# Convenience function for quick client creation
async def create_client(
    persistence_type: str = "auto",
    **kwargs
) -> GleitzeitClient:
    """
    Create and initialize a Gleitzeit client
    
    Args:
        persistence_type: Persistence type ("redis", "sql", "memory", "auto")
        **kwargs: Additional configuration
        
    Returns:
        Initialized GleitzeitClient
    """
    client = GleitzeitClient(
        persistence_type=persistence_type,
        **kwargs
    )
    await client.initialize()
    return client