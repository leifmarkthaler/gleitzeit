"""
Main scaling manager that coordinates all horizontal scaling components.

Integrates node registry, consistent hashing, and workflow routing
to provide a complete scaling solution.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set
from datetime import datetime
from enum import Enum

from redis.asyncio import Redis

from .node_registry import NodeRegistry, NodeInfo, NodeStatus
from .consistent_hash import ConsistentHashRing
from .workflow_router import WorkflowRouter, RoutingStrategy
from ..core.events import GleitzeitEvent, EventType
from ..scheduler import StatelessScheduler

logger = logging.getLogger(__name__)


class ScalingMode(str, Enum):
    """Scaling operation modes."""
    SINGLE_NODE = "single_node"  # No scaling (backward compatible)
    MULTI_NODE = "multi_node"    # Full horizontal scaling
    AUTO_SCALE = "auto_scale"    # Dynamic scaling based on load


class ScalingManager:
    """
    Manages horizontal scaling for Gleitzeit.
    
    Coordinates:
    - Node registration and health monitoring
    - Workflow routing and affinity
    - Load balancing and rebalancing
    - Failure detection and recovery
    """
    
    def __init__(
        self,
        redis: Redis,
        scheduler: Optional[StatelessScheduler] = None,
        node_id: Optional[str] = None,
        mode: ScalingMode = ScalingMode.SINGLE_NODE,
        routing_strategy: RoutingStrategy = RoutingStrategy.CONSISTENT_HASH,
        capacity: int = 100,
        heartbeat_interval: int = 5,
        node_timeout: int = 30,
        enable_monitoring: bool = True
    ):
        """
        Initialize the scaling manager.
        
        Args:
            redis: Redis connection
            node_id: Unique node identifier
            mode: Scaling mode
            routing_strategy: Workflow routing strategy
            capacity: Max concurrent workflows for this node
            heartbeat_interval: Seconds between heartbeats
            node_timeout: Seconds before marking node as unhealthy
            enable_monitoring: Whether to monitor cluster health
        """
        self.redis = redis
        self.scheduler = scheduler
        self.mode = mode
        self.enable_monitoring = enable_monitoring

        # Components
        self.node_registry = NodeRegistry(
            redis=redis,
            node_id=node_id,
            heartbeat_interval=heartbeat_interval,
            node_timeout=node_timeout,
            capacity=capacity
        )

        self.workflow_router = WorkflowRouter(
            redis=redis,
            node_registry=self.node_registry,
            strategy=routing_strategy,
            enable_affinity=True
        )

        # State
        self._initialized = False

        # Statistics (no more background tasks)
        self._cluster_checks = 0
        self._rebalance_operations = 0
        self._nodes_recovered = 0

        # Event bus reference (set by system manager)
        self.event_bus = None
        
    async def initialize(
        self,
        capabilities: List[str] = None,
        region: str = None,
        zone: str = None,
        metadata: Dict = None
    ):
        """
        Initialize the scaling manager and register this node.
        
        Args:
            capabilities: Node capabilities (e.g., ["python", "gpu"])
            region: Geographic region
            zone: Availability zone
            metadata: Additional metadata
        """
        if self._initialized:
            return
        
        if self.mode == ScalingMode.SINGLE_NODE:
            # Single node mode - minimal setup
            logger.info("Running in single-node mode (no scaling)")
            self._initialized = True
            return
        
        # Register this node
        node_info = await self.node_registry.register_node(
            capabilities=capabilities,
            region=region,
            zone=zone,
            metadata=metadata
        )
        
        logger.info(f"Node {node_info.node_id} registered with capacity {node_info.capacity}")
        
        # Initialize router
        await self.workflow_router.initialize()
        
        # Register event handlers with scheduler if available
        if self.scheduler:
            await self.scheduler.register_handler("cluster_monitor", self._handle_cluster_monitor_event)
            await self.scheduler.register_handler("auto_rebalance", self._handle_auto_rebalance_event)

            # Start monitoring if enabled
            if self.enable_monitoring:
                await self.scheduler.schedule_event("cluster_monitor", 10)

            # Start rebalancing if in auto-scale mode
            if self.mode == ScalingMode.AUTO_SCALE:
                await self.scheduler.schedule_event("auto_rebalance", 60)
        
        self._initialized = True
        logger.info(f"Scaling manager initialized in {self.mode.value} mode")
    
    async def shutdown(self, graceful: bool = True):
        """
        Shutdown the scaling manager.
        
        Args:
            graceful: Whether to perform graceful shutdown
        """
        if not self._initialized:
            return
        
        if self.mode == ScalingMode.SINGLE_NODE:
            return
        
        # Cancel any pending events in scheduler
        if self.scheduler:
            # The scheduler will handle cleanup of pending events
            pass
        
        # Unregister node
        await self.node_registry.unregister_node(graceful=graceful)
        
        logger.info("Scaling manager shutdown complete")
    
    async def route_workflow(self, workflow_id: str, hints: Optional[Dict] = None) -> Optional[str]:
        """
        Route a workflow to a node.
        
        Args:
            workflow_id: Workflow to route
            hints: Routing hints
            
        Returns:
            Node ID or None if routing failed
        """
        if self.mode == ScalingMode.SINGLE_NODE:
            # Always route to self in single-node mode
            return self.node_registry.node_id
        
        return await self.workflow_router.route_workflow(workflow_id, hints)
    
    async def get_workflow_node(self, workflow_id: str) -> Optional[str]:
        """
        Get the node assigned to a workflow.
        
        Args:
            workflow_id: Workflow to query
            
        Returns:
            Node ID or None
        """
        if self.mode == ScalingMode.SINGLE_NODE:
            return self.node_registry.node_id
        
        return await self.workflow_router.get_workflow_node(workflow_id)
    
    async def should_process_workflow(self, workflow_id: str) -> bool:
        """
        Check if this node should process a workflow.
        
        Args:
            workflow_id: Workflow to check
            
        Returns:
            True if this node should process it
        """
        if self.mode == ScalingMode.SINGLE_NODE:
            return True
        
        assigned_node = await self.get_workflow_node(workflow_id)
        return assigned_node == self.node_registry.node_id
    
    async def should_process_task(self, task_id: str, workflow_id: str) -> bool:
        """
        Check if this node should process a task.
        
        Tasks always follow their workflow's node assignment.
        
        Args:
            task_id: Task to check
            workflow_id: Parent workflow
            
        Returns:
            True if this node should process it
        """
        return await self.should_process_workflow(workflow_id)
    
    def get_consumer_group(self) -> str:
        """
        Get the consumer group name for this node.
        
        Returns:
            Consumer group name
        """
        if self.mode == ScalingMode.SINGLE_NODE:
            return "gleitzeit-workers"
        
        return f"node-{self.node_registry.node_id}"
    
    async def get_stream_partitions(self) -> List[str]:
        """
        Get the stream partitions this node should consume from.
        
        Returns:
            List of stream keys
        """
        if self.mode == ScalingMode.SINGLE_NODE:
            # Consume from all streams
            return ["gleitzeit:events:stream:*"]
        
        # In multi-node mode, could partition streams
        # For now, all nodes consume all streams but filter by workflow assignment
        return ["gleitzeit:events:stream:*"]
    
    async def _handle_cluster_monitor_event(self, event_data: Dict) -> Dict[str, int]:
        """Handle cluster monitoring event from scheduler."""
        try:
            logger.debug("Processing cluster monitor event")

            # Get cluster status
            nodes = await self.node_registry.discover_nodes()

            unhealthy_count = 0
            recovered_count = 0

            for node in nodes:
                if node.status == NodeStatus.OFFLINE:
                    await self._handle_node_failure(node.node_id)
                    recovered_count += 1
                elif node.status == NodeStatus.UNHEALTHY:
                    logger.warning(f"Node {node.node_id} is unhealthy")
                    unhealthy_count += 1

            # Emit cluster health event
            if self.event_bus:
                stats = await self.get_cluster_stats()
                await self.event_bus.emit(GleitzeitEvent(
                    event_type=EventType.METRICS_COLLECTED,
                    data={"cluster_stats": stats},
                    source=f"scaling_manager:{self.node_registry.node_id}"
                ))

            self._cluster_checks += 1
            self._nodes_recovered += recovered_count

            # Schedule next cluster monitoring
            if self.scheduler:
                await self.scheduler.schedule_event("cluster_monitor", 10)

            return {
                "nodes_checked": len(nodes),
                "unhealthy_nodes": unhealthy_count,
                "nodes_recovered": recovered_count
            }

        except Exception as e:
            logger.error(f"Error in cluster monitor: {e}")
            # Still schedule next check
            if self.scheduler:
                await self.scheduler.schedule_event("cluster_monitor", 10)
            return {"error": str(e)}
    
    async def _handle_node_failure(self, failed_node_id: str):
        """
        Handle a node failure.
        
        Args:
            failed_node_id: Node that failed
        """
        logger.warning(f"Handling failure of node {failed_node_id}")
        
        # Remove from router
        await self.workflow_router.handle_node_removed(failed_node_id)
        
        # Emit failure event
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.COMPONENT_FAILURE,
                data={
                    "component": "node",
                    "node_id": failed_node_id,
                    "action": "reassigning_workflows"
                },
                source=f"scaling_manager:{self.node_registry.node_id}"
            ))
    
    async def _handle_auto_rebalance_event(self, event_data: Dict) -> Dict[str, int]:
        """Handle auto-rebalance event from scheduler."""
        try:
            logger.debug("Processing auto-rebalance event")

            if self.mode != ScalingMode.AUTO_SCALE:
                # Still schedule next check even if not in auto-scale mode
                if self.scheduler:
                    await self.scheduler.schedule_event("auto_rebalance", 60)
                return {"skipped": 1, "reason": "not_in_auto_scale_mode"}

            # Get load distribution
            nodes = await self.node_registry.get_healthy_nodes()

            if len(nodes) < 2:
                # Schedule next check
                if self.scheduler:
                    await self.scheduler.schedule_event("auto_rebalance", 60)
                return {"skipped": 1, "reason": "insufficient_nodes", "node_count": len(nodes)}

            # Calculate average load
            total_load = sum(n.current_load for n in nodes)
            avg_load = total_load / len(nodes)

            # Find overloaded and underloaded nodes
            overloaded = [n for n in nodes if n.current_load > avg_load * 1.2]
            underloaded = [n for n in nodes if n.current_load < avg_load * 0.8]

            rebalanced_count = 0
            if overloaded and underloaded:
                logger.info("Rebalancing workflows across nodes")
                # TODO: Implement actual workflow migration
                rebalanced_count = len(overloaded)

                # Emit rebalancing event
                if self.event_bus:
                    await self.event_bus.emit(GleitzeitEvent(
                        event_type=EventType.POOL_REBALANCED,
                        data={
                            "overloaded_nodes": len(overloaded),
                            "underloaded_nodes": len(underloaded),
                            "avg_load": avg_load
                        },
                        source=f"scaling_manager:{self.node_registry.node_id}"
                    ))

            self._rebalance_operations += 1

            # Schedule next auto-rebalance
            if self.scheduler:
                await self.scheduler.schedule_event("auto_rebalance", 60)

            return {
                "nodes_checked": len(nodes),
                "overloaded_nodes": len(overloaded),
                "underloaded_nodes": len(underloaded),
                "rebalanced_count": rebalanced_count
            }

        except Exception as e:
            logger.error(f"Error in auto-rebalance: {e}")
            # Still schedule next check
            if self.scheduler:
                await self.scheduler.schedule_event("auto_rebalance", 60)
            return {"error": str(e)}
    
    async def get_cluster_stats(self) -> Dict:
        """Get comprehensive cluster statistics."""
        if self.mode == ScalingMode.SINGLE_NODE:
            return {
                "mode": "single_node",
                "nodes": 1,
                "capacity": self.node_registry.capacity,
                "current_load": 0  # TODO: Get actual load
            }
        
        cluster_stats = await self.node_registry.get_cluster_stats()
        routing_stats = await self.workflow_router.get_routing_stats()
        
        return {
            "mode": self.mode.value,
            "cluster": cluster_stats,
            "routing": routing_stats,
            "node_id": self.node_registry.node_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def scale_out(self, count: int = 1) -> List[str]:
        """
        Scale out by adding nodes (for auto-scaling).
        
        Args:
            count: Number of nodes to add
            
        Returns:
            List of new node IDs
        """
        if self.mode != ScalingMode.AUTO_SCALE:
            logger.warning("Scale out only available in auto-scale mode")
            return []
        
        # In practice, this would trigger node provisioning
        # For now, just log the request
        logger.info(f"Scale out requested: {count} nodes")
        
        # Emit scaling event
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.POOL_SCALED_UP,
                data={"requested_nodes": count},
                source=f"scaling_manager:{self.node_registry.node_id}"
            ))
        
        return []
    
    async def scale_in(self, count: int = 1) -> List[str]:
        """
        Scale in by removing nodes (for auto-scaling).
        
        Args:
            count: Number of nodes to remove
            
        Returns:
            List of removed node IDs
        """
        if self.mode != ScalingMode.AUTO_SCALE:
            logger.warning("Scale in only available in auto-scale mode")
            return []
        
        logger.info(f"Scale in requested: {count} nodes")
        
        # Emit scaling event
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.POOL_SCALED_DOWN,
                data={"requested_nodes": count},
                source=f"scaling_manager:{self.node_registry.node_id}"
            ))
        
        return []