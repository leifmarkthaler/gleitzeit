"""
Workflow routing system for horizontal scaling.

Routes workflows to appropriate nodes based on consistent hashing,
maintains workflow-to-node affinity, and handles failover.
"""

import logging
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime
import json

from redis.asyncio import Redis

from .consistent_hash import ConsistentHashRing
from .node_registry import NodeRegistry, NodeInfo, NodeStatus

logger = logging.getLogger(__name__)


class RoutingStrategy(str, Enum):
    """Workflow routing strategies."""
    CONSISTENT_HASH = "consistent_hash"
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    NAMESPACE = "namespace"
    CAPABILITY = "capability"
    HYBRID = "hybrid"


class WorkflowRouter:
    """
    Routes workflows to nodes and maintains affinity.
    
    Ensures that:
    - Workflows are evenly distributed
    - All tasks in a workflow run on the same node
    - Failed nodes have their workflows reassigned
    """
    
    def __init__(
        self,
        redis: Redis,
        node_registry: NodeRegistry,
        strategy: RoutingStrategy = RoutingStrategy.CONSISTENT_HASH,
        enable_affinity: bool = True
    ):
        """
        Initialize the workflow router.
        
        Args:
            redis: Redis connection
            node_registry: Node registry instance
            strategy: Routing strategy to use
            enable_affinity: Whether to maintain workflow-node affinity
        """
        self.redis = redis
        self.node_registry = node_registry
        self.strategy = strategy
        self.enable_affinity = enable_affinity
        
        # Consistent hash ring for hash-based routing
        self.hash_ring = ConsistentHashRing(virtual_nodes=150)
        
        # Round-robin counter
        self._round_robin_counter = 0
        
        # Namespace to node mapping for multi-tenant scenarios
        self._namespace_nodes: Dict[str, str] = {}
        
        # Initialize hash ring with current nodes
        self._initialized = False
    
    async def initialize(self):
        """Initialize the router with current cluster state."""
        if self._initialized:
            return
        
        # Discover and add all healthy nodes to hash ring
        nodes = await self.node_registry.get_healthy_nodes()
        
        for node in nodes:
            # Weight based on capacity
            weight = node.capacity / 100.0  # Normalize to 1.0 for standard capacity
            self.hash_ring.add_node(node.node_id, weight=weight, metadata=node.to_dict())
        
        logger.info(f"Router initialized with {len(nodes)} nodes")
        self._initialized = True
    
    async def route_workflow(
        self,
        workflow_id: str,
        hints: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Route a workflow to a node.
        
        Args:
            workflow_id: Unique workflow identifier
            hints: Routing hints (namespace, capabilities, priority, etc.)
            
        Returns:
            Node ID to execute the workflow, or None if no suitable node
        """
        # Ensure we're initialized
        if not self._initialized:
            await self.initialize()
        
        # Check for existing affinity
        if self.enable_affinity:
            existing_node = await self.get_workflow_node(workflow_id)
            if existing_node and await self._is_node_available(existing_node):
                logger.debug(f"Using existing affinity for workflow {workflow_id} -> {existing_node}")
                return existing_node
        
        # Route based on strategy
        hints = hints or {}
        
        if self.strategy == RoutingStrategy.CONSISTENT_HASH:
            node_id = await self._route_consistent_hash(workflow_id, hints)
        elif self.strategy == RoutingStrategy.ROUND_ROBIN:
            node_id = await self._route_round_robin(hints)
        elif self.strategy == RoutingStrategy.LEAST_LOADED:
            node_id = await self._route_least_loaded(hints)
        elif self.strategy == RoutingStrategy.NAMESPACE:
            node_id = await self._route_namespace(workflow_id, hints)
        elif self.strategy == RoutingStrategy.CAPABILITY:
            node_id = await self._route_capability(workflow_id, hints)
        elif self.strategy == RoutingStrategy.HYBRID:
            node_id = await self._route_hybrid(workflow_id, hints)
        else:
            node_id = await self._route_consistent_hash(workflow_id, hints)
        
        # Record affinity if routing succeeded
        if node_id and self.enable_affinity:
            await self.set_workflow_node(workflow_id, node_id)
            await self.node_registry.assign_workflow_to_node(workflow_id, node_id)
        
        return node_id
    
    async def _route_consistent_hash(self, workflow_id: str, hints: Dict) -> Optional[str]:
        """Route using consistent hashing."""
        # Check namespace override
        if "namespace" in hints and hints["namespace"] in self._namespace_nodes:
            return self._namespace_nodes[hints["namespace"]]
        
        # Use consistent hash
        node_id = self.hash_ring.get_node(workflow_id)
        
        # Verify node is healthy
        if node_id and await self._is_node_available(node_id):
            return node_id
        
        # Try backup nodes
        backup_nodes = self.hash_ring.get_nodes(workflow_id, count=3)
        for backup_node in backup_nodes:
            if await self._is_node_available(backup_node):
                return backup_node
        
        return None
    
    async def _route_round_robin(self, hints: Dict) -> Optional[str]:
        """Route using round-robin strategy."""
        nodes = await self.node_registry.get_healthy_nodes()
        
        if not nodes:
            return None
        
        # Filter by capabilities if specified
        if "capabilities" in hints:
            required_caps = set(hints["capabilities"])
            nodes = [n for n in nodes if required_caps.issubset(set(n.capabilities))]
        
        if not nodes:
            return None
        
        # Round-robin selection
        node = nodes[self._round_robin_counter % len(nodes)]
        self._round_robin_counter += 1
        
        return node.node_id
    
    async def _route_least_loaded(self, hints: Dict) -> Optional[str]:
        """Route to the least loaded node."""
        nodes = await self.node_registry.get_healthy_nodes()
        
        if not nodes:
            return None
        
        # Filter by capabilities
        if "capabilities" in hints:
            required_caps = set(hints["capabilities"])
            nodes = [n for n in nodes if required_caps.issubset(set(n.capabilities))]
        
        if not nodes:
            return None
        
        # Find least loaded node
        least_loaded = min(nodes, key=lambda n: n.current_load / n.capacity)
        
        # Check if node has capacity
        if least_loaded.current_load < least_loaded.capacity:
            return least_loaded.node_id
        
        return None
    
    async def _route_namespace(self, workflow_id: str, hints: Dict) -> Optional[str]:
        """Route based on namespace isolation."""
        namespace = hints.get("namespace", "default")
        
        # Check if namespace has assigned node
        if namespace in self._namespace_nodes:
            node_id = self._namespace_nodes[namespace]
            if await self._is_node_available(node_id):
                return node_id
        
        # Assign a node to this namespace
        node_id = await self._route_least_loaded({})
        if node_id:
            self._namespace_nodes[namespace] = node_id
            await self.redis.hset("routing:namespaces", namespace, node_id)
        
        return node_id
    
    async def _route_capability(self, workflow_id: str, hints: Dict) -> Optional[str]:
        """Route based on required capabilities."""
        required_caps = hints.get("capabilities", [])
        
        if not required_caps:
            # No specific requirements, use consistent hash
            return await self._route_consistent_hash(workflow_id, hints)
        
        # Find nodes with required capabilities
        nodes = await self.node_registry.get_healthy_nodes()
        required_set = set(required_caps)
        
        capable_nodes = [
            n for n in nodes
            if required_set.issubset(set(n.capabilities))
        ]
        
        if not capable_nodes:
            logger.warning(f"No nodes found with capabilities: {required_caps}")
            return None
        
        # Among capable nodes, use consistent hash
        node_ids = [n.node_id for n in capable_nodes]
        
        # Create temporary hash ring with only capable nodes
        temp_ring = ConsistentHashRing()
        for node in capable_nodes:
            temp_ring.add_node(node.node_id)
        
        return temp_ring.get_node(workflow_id)
    
    async def _route_hybrid(self, workflow_id: str, hints: Dict) -> Optional[str]:
        """Hybrid routing combining multiple strategies."""
        # Priority order:
        # 1. Namespace isolation
        # 2. Required capabilities
        # 3. Load balancing
        # 4. Consistent hash
        
        if "namespace" in hints:
            node_id = await self._route_namespace(workflow_id, hints)
            if node_id:
                return node_id
        
        if "capabilities" in hints:
            node_id = await self._route_capability(workflow_id, hints)
            if node_id:
                return node_id
        
        if hints.get("prefer_least_loaded"):
            node_id = await self._route_least_loaded(hints)
            if node_id:
                return node_id
        
        return await self._route_consistent_hash(workflow_id, hints)
    
    async def _is_node_available(self, node_id: str) -> bool:
        """Check if a node is available for routing."""
        node_info = await self.node_registry.get_node_info(node_id)
        
        if not node_info:
            return False
        
        # Node must be healthy and not at capacity
        return (
            node_info.status == NodeStatus.HEALTHY and
            node_info.current_load < node_info.capacity
        )
    
    async def get_workflow_node(self, workflow_id: str) -> Optional[str]:
        """
        Get the node assigned to a workflow.
        
        Args:
            workflow_id: Workflow to query
            
        Returns:
            Node ID or None if not assigned
        """
        node_id = await self.redis.get(f"workflow:node:{workflow_id}")
        if node_id:
            return node_id.decode() if isinstance(node_id, bytes) else node_id
        return None
    
    async def set_workflow_node(self, workflow_id: str, node_id: str):
        """
        Set the node assignment for a workflow.
        
        Args:
            workflow_id: Workflow to assign
            node_id: Target node
        """
        # Set with TTL to auto-cleanup old assignments
        await self.redis.set(
            f"workflow:node:{workflow_id}",
            node_id,
            ex=86400  # 24 hour TTL
        )
        
        # Also track reverse mapping
        await self.redis.sadd(f"node:workflows:{node_id}", workflow_id)
    
    async def remove_workflow_node(self, workflow_id: str):
        """Remove workflow-node assignment."""
        # Get current node
        node_id = await self.get_workflow_node(workflow_id)
        
        if node_id:
            # Remove from both mappings
            await self.redis.delete(f"workflow:node:{workflow_id}")
            await self.redis.srem(f"node:workflows:{node_id}", workflow_id)
            await self.node_registry.remove_workflow_from_node(workflow_id, node_id)
    
    async def reassign_node_workflows(self, failed_node_id: str) -> Dict[str, str]:
        """
        Reassign all workflows from a failed node.
        
        Args:
            failed_node_id: Node that failed
            
        Returns:
            Mapping of workflow_id -> new_node_id
        """
        reassignments = {}
        
        # Get all workflows from failed node
        workflows = await self.node_registry.get_node_workflows(failed_node_id)
        
        logger.info(f"Reassigning {len(workflows)} workflows from failed node {failed_node_id}")
        
        for workflow_id in workflows:
            # Remove old assignment
            await self.remove_workflow_node(workflow_id)
            
            # Route to new node
            new_node = await self.route_workflow(workflow_id)
            
            if new_node:
                reassignments[workflow_id] = new_node
                logger.debug(f"Reassigned workflow {workflow_id} to {new_node}")
            else:
                logger.error(f"Could not reassign workflow {workflow_id}")
        
        return reassignments
    
    async def handle_node_added(self, node_id: str):
        """
        Handle a new node being added to the cluster.
        
        Args:
            node_id: New node ID
        """
        node_info = await self.node_registry.get_node_info(node_id)
        
        if node_info:
            # Add to hash ring
            weight = node_info.capacity / 100.0
            self.hash_ring.add_node(node_id, weight=weight, metadata=node_info.to_dict())
            
            logger.info(f"Added node {node_id} to router")
            
            # TODO: Implement rebalancing if needed
    
    async def handle_node_removed(self, node_id: str):
        """
        Handle a node being removed from the cluster.
        
        Args:
            node_id: Node being removed
        """
        # Remove from hash ring
        self.hash_ring.remove_node(node_id)
        
        # Reassign workflows
        await self.reassign_node_workflows(node_id)
        
        logger.info(f"Removed node {node_id} from router")
    
    async def get_routing_stats(self) -> Dict:
        """Get statistics about workflow routing."""
        nodes = await self.node_registry.get_healthy_nodes()
        
        distribution = {}
        for node in nodes:
            workflows = await self.node_registry.get_node_workflows(node.node_id)
            distribution[node.node_id] = {
                "workflows": len(workflows),
                "capacity": node.capacity,
                "utilization": len(workflows) / node.capacity if node.capacity > 0 else 0
            }
        
        return {
            "strategy": self.strategy.value,
            "nodes": len(nodes),
            "hash_ring": self.hash_ring.get_stats(),
            "distribution": distribution,
            "namespace_mappings": dict(self._namespace_nodes)
        }