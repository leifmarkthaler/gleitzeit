"""
Node registration and discovery system for horizontal scaling.

Manages node lifecycle, health monitoring, and service discovery
using Redis as the coordination backend.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict
import socket
import uuid

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class NodeStatus(str, Enum):
    """Node health status."""
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DRAINING = "draining"  # Preparing to shutdown
    OFFLINE = "offline"


@dataclass
class NodeInfo:
    """Information about a node in the cluster."""
    node_id: str
    hostname: str
    ip_address: str
    port: int
    status: NodeStatus
    capacity: int  # Max concurrent workflows
    current_load: int  # Current workflow count
    capabilities: List[str]  # e.g., ["python", "gpu", "docker"]
    region: Optional[str] = None
    zone: Optional[str] = None
    started_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    metadata: Dict[str, any] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for Redis storage."""
        data = asdict(self)
        # Convert datetime objects to ISO format
        if self.started_at:
            data['started_at'] = self.started_at.isoformat()
        if self.last_heartbeat:
            data['last_heartbeat'] = self.last_heartbeat.isoformat()
        data['status'] = self.status.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'NodeInfo':
        """Create from dictionary retrieved from Redis."""
        # Convert ISO strings back to datetime
        if data.get('started_at'):
            data['started_at'] = datetime.fromisoformat(data['started_at'])
        if data.get('last_heartbeat'):
            data['last_heartbeat'] = datetime.fromisoformat(data['last_heartbeat'])
        # Convert status string to enum
        if isinstance(data.get('status'), str):
            data['status'] = NodeStatus(data['status'])
        return cls(**data)


class NodeRegistry:
    """
    Manages node registration, discovery, and health monitoring.
    
    Uses Redis for coordination with the following key structure:
    - nodes:registry -> Hash of node_id -> NodeInfo (JSON)
    - nodes:heartbeat:{node_id} -> Timestamp of last heartbeat
    - nodes:status:{node_id} -> Current status
    - nodes:workflows:{node_id} -> Set of assigned workflow IDs
    """
    
    def __init__(
        self,
        redis: Redis,
        node_id: Optional[str] = None,
        heartbeat_interval: int = 5,
        node_timeout: int = 30,
        capacity: int = 100
    ):
        """
        Initialize the node registry.
        
        Args:
            redis: Redis connection
            node_id: Unique node identifier (auto-generated if None)
            heartbeat_interval: Seconds between heartbeats
            node_timeout: Seconds before marking node as unhealthy
            capacity: Max concurrent workflows for this node
        """
        self.redis = redis
        self.node_id = node_id or self._generate_node_id()
        self.heartbeat_interval = heartbeat_interval
        self.node_timeout = node_timeout
        self.capacity = capacity
        
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Node information
        self.node_info: Optional[NodeInfo] = None
        
    def _generate_node_id(self) -> str:
        """Generate unique node ID."""
        hostname = socket.gethostname()
        unique_id = uuid.uuid4().hex[:8]
        return f"{hostname}-{unique_id}"
    
    async def register_node(
        self,
        capabilities: List[str] = None,
        region: str = None,
        zone: str = None,
        metadata: Dict = None
    ) -> NodeInfo:
        """
        Register this node with the cluster.
        
        Args:
            capabilities: List of node capabilities (e.g., ["python", "gpu"])
            region: Geographic region
            zone: Availability zone
            metadata: Additional metadata
            
        Returns:
            NodeInfo object for this node
        """
        # Get network info
        hostname = socket.gethostname()
        try:
            ip_address = socket.gethostbyname(hostname)
        except:
            ip_address = "127.0.0.1"
        
        # Create node info
        self.node_info = NodeInfo(
            node_id=self.node_id,
            hostname=hostname,
            ip_address=ip_address,
            port=8080,  # TODO: Make configurable
            status=NodeStatus.STARTING,
            capacity=self.capacity,
            current_load=0,
            capabilities=capabilities or ["python"],
            region=region,
            zone=zone,
            started_at=datetime.utcnow(),
            last_heartbeat=datetime.utcnow(),
            metadata=metadata or {}
        )
        
        # Store in Redis
        await self._save_node_info(self.node_info)
        
        # Start heartbeat
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        # Mark as healthy after registration
        self.node_info.status = NodeStatus.HEALTHY
        await self._save_node_info(self.node_info)
        
        logger.info(f"Node {self.node_id} registered successfully")
        return self.node_info
    
    async def _save_node_info(self, node_info: NodeInfo):
        """Save node information to Redis."""
        # Save to main registry
        await self.redis.hset(
            "nodes:registry",
            node_info.node_id,
            json.dumps(node_info.to_dict())
        )
        
        # Update status key
        await self.redis.set(
            f"nodes:status:{node_info.node_id}",
            node_info.status.value,
            ex=self.node_timeout * 2  # Auto-expire if no updates
        )
        
        # Update heartbeat
        await self.redis.set(
            f"nodes:heartbeat:{node_info.node_id}",
            datetime.utcnow().isoformat(),
            ex=self.node_timeout * 2
        )
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats."""
        while self._running:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                
                if self.node_info:
                    # Update heartbeat
                    self.node_info.last_heartbeat = datetime.utcnow()
                    
                    # Update load information
                    workflow_count = await self.redis.scard(f"nodes:workflows:{self.node_id}")
                    self.node_info.current_load = workflow_count
                    
                    # Save to Redis
                    await self._save_node_info(self.node_info)
                    
                    logger.debug(f"Heartbeat sent for node {self.node_id}")
                    
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
    
    async def unregister_node(self, graceful: bool = True):
        """
        Unregister this node from the cluster.
        
        Args:
            graceful: If True, mark as draining first
        """
        self._running = False
        
        if graceful and self.node_info:
            # Mark as draining
            self.node_info.status = NodeStatus.DRAINING
            await self._save_node_info(self.node_info)
            
            # Wait for workflows to complete
            logger.info(f"Node {self.node_id} draining...")
            await asyncio.sleep(5)  # TODO: Actually wait for workflows
        
        # Cancel heartbeat
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Remove from registry
        await self.redis.hdel("nodes:registry", self.node_id)
        await self.redis.delete(f"nodes:status:{self.node_id}")
        await self.redis.delete(f"nodes:heartbeat:{self.node_id}")
        
        logger.info(f"Node {self.node_id} unregistered")
    
    async def discover_nodes(self, include_self: bool = True) -> List[NodeInfo]:
        """
        Discover all active nodes in the cluster.
        
        Args:
            include_self: Whether to include this node
            
        Returns:
            List of NodeInfo objects for active nodes
        """
        nodes = []
        
        # Get all nodes from registry
        registry = await self.redis.hgetall("nodes:registry")
        
        for node_id_bytes, node_data_bytes in registry.items():
            node_id = node_id_bytes.decode() if isinstance(node_id_bytes, bytes) else node_id_bytes
            
            # Skip self if requested
            if not include_self and node_id == self.node_id:
                continue
            
            try:
                # Parse node data
                node_data = json.loads(node_data_bytes)
                node_info = NodeInfo.from_dict(node_data)
                
                # Check if node is still alive
                if await self._is_node_alive(node_id):
                    nodes.append(node_info)
                else:
                    # Mark as offline
                    node_info.status = NodeStatus.OFFLINE
                    nodes.append(node_info)
                    
            except Exception as e:
                logger.error(f"Error parsing node {node_id}: {e}")
        
        return nodes
    
    async def _is_node_alive(self, node_id: str) -> bool:
        """Check if a node is still alive based on heartbeat."""
        heartbeat_key = f"nodes:heartbeat:{node_id}"
        heartbeat = await self.redis.get(heartbeat_key)
        
        if not heartbeat:
            return False
        
        try:
            last_heartbeat = datetime.fromisoformat(heartbeat.decode() if isinstance(heartbeat, bytes) else heartbeat)
            time_since = (datetime.utcnow() - last_heartbeat).total_seconds()
            return time_since < self.node_timeout
        except:
            return False
    
    async def get_node_info(self, node_id: str) -> Optional[NodeInfo]:
        """Get information about a specific node."""
        node_data = await self.redis.hget("nodes:registry", node_id)
        
        if not node_data:
            return None
        
        try:
            data = json.loads(node_data)
            return NodeInfo.from_dict(data)
        except Exception as e:
            logger.error(f"Error parsing node info for {node_id}: {e}")
            return None
    
    async def get_healthy_nodes(self) -> List[NodeInfo]:
        """Get list of healthy nodes."""
        all_nodes = await self.discover_nodes()
        return [n for n in all_nodes if n.status == NodeStatus.HEALTHY]
    
    async def update_node_load(self, node_id: str, load_delta: int):
        """
        Update the load for a node.
        
        Args:
            node_id: Node to update
            load_delta: Change in load (positive or negative)
        """
        node_info = await self.get_node_info(node_id)
        
        if node_info:
            node_info.current_load += load_delta
            node_info.current_load = max(0, node_info.current_load)  # Don't go negative
            await self._save_node_info(node_info)
    
    async def assign_workflow_to_node(self, workflow_id: str, node_id: str):
        """Track workflow assignment to a node."""
        await self.redis.sadd(f"nodes:workflows:{node_id}", workflow_id)
        await self.update_node_load(node_id, 1)
    
    async def remove_workflow_from_node(self, workflow_id: str, node_id: str):
        """Remove workflow assignment from a node."""
        await self.redis.srem(f"nodes:workflows:{node_id}", workflow_id)
        await self.update_node_load(node_id, -1)
    
    async def get_node_workflows(self, node_id: str) -> Set[str]:
        """Get all workflows assigned to a node."""
        workflows = await self.redis.smembers(f"nodes:workflows:{node_id}")
        return {w.decode() if isinstance(w, bytes) else w for w in workflows}
    
    async def monitor_cluster_health(self):
        """
        Monitor health of all nodes in the cluster.
        
        This should be run by a designated leader node.
        """
        self._monitor_task = asyncio.create_task(self._monitor_loop())
    
    async def _monitor_loop(self):
        """Monitor cluster health and handle failures."""
        while self._running:
            try:
                await asyncio.sleep(self.heartbeat_interval * 2)
                
                nodes = await self.discover_nodes(include_self=False)
                
                for node in nodes:
                    if node.status == NodeStatus.OFFLINE:
                        logger.warning(f"Node {node.node_id} is offline")
                        # TODO: Trigger workflow reassignment
                    elif node.status == NodeStatus.UNHEALTHY:
                        logger.warning(f"Node {node.node_id} is unhealthy")
                        
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
    
    async def get_cluster_stats(self) -> Dict:
        """Get statistics about the cluster."""
        nodes = await self.discover_nodes()
        
        healthy = sum(1 for n in nodes if n.status == NodeStatus.HEALTHY)
        total_capacity = sum(n.capacity for n in nodes)
        total_load = sum(n.current_load for n in nodes)
        
        return {
            "total_nodes": len(nodes),
            "healthy_nodes": healthy,
            "total_capacity": total_capacity,
            "total_load": total_load,
            "utilization": total_load / total_capacity if total_capacity > 0 else 0,
            "nodes": [n.to_dict() for n in nodes]
        }