"""
Consistent hashing implementation for even workflow distribution.

Uses virtual nodes to ensure better balance and minimal disruption
when nodes are added or removed.
"""

import hashlib
import bisect
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class ConsistentHashRing:
    """
    Consistent hash ring for distributing workflows across nodes.
    
    Features:
    - Virtual nodes for better distribution
    - Minimal redistribution when nodes change
    - Configurable hash function
    - Support for weighted nodes
    """
    
    def __init__(self, virtual_nodes: int = 150, hash_function: str = "md5"):
        """
        Initialize the hash ring.
        
        Args:
            virtual_nodes: Number of virtual nodes per physical node
            hash_function: Hash function to use ("md5", "sha1", "sha256")
        """
        self.virtual_nodes = virtual_nodes
        self.hash_function = hash_function
        
        # Ring structure
        self._ring: Dict[int, str] = {}  # hash -> node_id
        self._sorted_keys: List[int] = []  # sorted hash values
        self._nodes: Dict[str, Dict] = {}  # node_id -> node_info
        
        # Statistics
        self._key_count: Dict[str, int] = {}  # node_id -> assigned key count
        
    def _hash(self, key: str) -> int:
        """Generate hash for a key."""
        if self.hash_function == "md5":
            hasher = hashlib.md5()
        elif self.hash_function == "sha1":
            hasher = hashlib.sha1()
        elif self.hash_function == "sha256":
            hasher = hashlib.sha256()
        else:
            hasher = hashlib.md5()
        
        hasher.update(key.encode('utf-8'))
        return int(hasher.hexdigest(), 16)
    
    def add_node(self, node_id: str, weight: float = 1.0, metadata: Dict = None) -> List[Tuple[int, str]]:
        """
        Add a node to the hash ring.
        
        Args:
            node_id: Unique node identifier
            weight: Node weight (higher = more keys)
            metadata: Optional node metadata
            
        Returns:
            List of (hash, node_id) tuples for virtual nodes added
        """
        if node_id in self._nodes:
            logger.warning(f"Node {node_id} already in ring")
            return []
        
        self._nodes[node_id] = {
            "weight": weight,
            "metadata": metadata or {},
            "virtual_nodes": []
        }
        
        added_vnodes = []
        num_vnodes = int(self.virtual_nodes * weight)
        
        for i in range(num_vnodes):
            # Create virtual node key
            vnode_key = f"{node_id}:{i}"
            vnode_hash = self._hash(vnode_key)
            
            # Add to ring
            self._ring[vnode_hash] = node_id
            bisect.insort(self._sorted_keys, vnode_hash)
            
            # Track virtual node
            self._nodes[node_id]["virtual_nodes"].append(vnode_hash)
            added_vnodes.append((vnode_hash, node_id))
        
        # Reset statistics
        self._key_count[node_id] = 0
        
        logger.info(f"Added node {node_id} with {num_vnodes} virtual nodes")
        return added_vnodes
    
    def remove_node(self, node_id: str) -> List[str]:
        """
        Remove a node from the hash ring.
        
        Args:
            node_id: Node to remove
            
        Returns:
            List of keys that need reassignment
        """
        if node_id not in self._nodes:
            logger.warning(f"Node {node_id} not in ring")
            return []
        
        # Find all keys assigned to this node (for reassignment)
        affected_keys = []
        
        # Remove virtual nodes
        for vnode_hash in self._nodes[node_id]["virtual_nodes"]:
            del self._ring[vnode_hash]
            self._sorted_keys.remove(vnode_hash)
        
        # Remove node tracking
        del self._nodes[node_id]
        if node_id in self._key_count:
            del self._key_count[node_id]
        
        logger.info(f"Removed node {node_id} from ring")
        return affected_keys
    
    def get_node(self, key: str) -> Optional[str]:
        """
        Get the node responsible for a key.
        
        Args:
            key: Key to look up (e.g., workflow_id)
            
        Returns:
            Node ID responsible for this key
        """
        if not self._ring:
            return None
        
        key_hash = self._hash(key)
        
        # Find the first node with hash >= key_hash
        idx = bisect.bisect_right(self._sorted_keys, key_hash)
        
        # Wrap around if necessary
        if idx == len(self._sorted_keys):
            idx = 0
        
        node_hash = self._sorted_keys[idx]
        node_id = self._ring[node_hash]
        
        # Update statistics
        self._key_count[node_id] = self._key_count.get(node_id, 0) + 1
        
        return node_id
    
    def get_nodes(self, key: str, count: int = 3) -> List[str]:
        """
        Get multiple nodes for a key (for replication).
        
        Args:
            key: Key to look up
            count: Number of nodes to return
            
        Returns:
            List of node IDs
        """
        if not self._ring or count <= 0:
            return []
        
        nodes = []
        seen = set()
        key_hash = self._hash(key)
        
        # Start from the primary node
        idx = bisect.bisect_right(self._sorted_keys, key_hash)
        
        # Walk the ring until we have enough unique nodes
        steps = 0
        while len(nodes) < count and steps < len(self._sorted_keys):
            # Wrap around if necessary
            actual_idx = (idx + steps) % len(self._sorted_keys)
            
            node_hash = self._sorted_keys[actual_idx]
            node_id = self._ring[node_hash]
            
            # Only add unique nodes
            if node_id not in seen:
                nodes.append(node_id)
                seen.add(node_id)
            
            steps += 1
        
        return nodes
    
    def get_node_keys(self, node_id: str) -> List[int]:
        """
        Get all hash values assigned to a node.
        
        Args:
            node_id: Node to query
            
        Returns:
            List of hash values
        """
        if node_id not in self._nodes:
            return []
        
        return self._nodes[node_id]["virtual_nodes"]
    
    def rebalance_keys_for_new_node(self, new_node_id: str) -> Dict[str, List[str]]:
        """
        Calculate which keys should move to a new node.
        
        Args:
            new_node_id: The newly added node
            
        Returns:
            Dict mapping old_node -> list of keys to move
        """
        if new_node_id not in self._nodes:
            return {}
        
        moves = {}
        
        # For each virtual node of the new node
        for vnode_hash in self._nodes[new_node_id]["virtual_nodes"]:
            # Find the range of keys that should move to this vnode
            idx = self._sorted_keys.index(vnode_hash)
            
            # Find the previous vnode
            prev_idx = (idx - 1) % len(self._sorted_keys)
            prev_hash = self._sorted_keys[prev_idx]
            
            # Find the next vnode (that's not the new node)
            next_idx = (idx + 1) % len(self._sorted_keys)
            while next_idx != idx and self._ring[self._sorted_keys[next_idx]] == new_node_id:
                next_idx = (next_idx + 1) % len(self._sorted_keys)
            
            if next_idx != idx:
                next_hash = self._sorted_keys[next_idx]
                old_node = self._ring[next_hash]
                
                # Keys in range (prev_hash, vnode_hash] should move from old_node to new_node
                if old_node not in moves:
                    moves[old_node] = []
                
                # In practice, we'd need to track actual keys
                # For now, we just note the range
                moves[old_node].append(f"range({prev_hash}, {vnode_hash}]")
        
        return moves
    
    def get_distribution(self) -> Dict[str, float]:
        """
        Get the current key distribution across nodes.
        
        Returns:
            Dict mapping node_id -> percentage of ring
        """
        if not self._sorted_keys:
            return {}
        
        distribution = {}
        total_range = 2**128  # Assuming MD5 hash space
        
        for node_id in self._nodes:
            vnodes = self._nodes[node_id]["virtual_nodes"]
            node_range = 0
            
            for vnode_hash in vnodes:
                idx = self._sorted_keys.index(vnode_hash)
                prev_idx = (idx - 1) % len(self._sorted_keys)
                
                # Calculate range owned by this vnode
                if prev_idx < idx:
                    range_size = vnode_hash - self._sorted_keys[prev_idx]
                else:
                    # Wrap around
                    range_size = (2**128 - self._sorted_keys[prev_idx]) + vnode_hash
                
                node_range += range_size
            
            distribution[node_id] = (node_range / total_range) * 100
        
        return distribution
    
    def get_stats(self) -> Dict:
        """Get statistics about the hash ring."""
        return {
            "nodes": len(self._nodes),
            "virtual_nodes": len(self._sorted_keys),
            "distribution": self.get_distribution(),
            "key_counts": dict(self._key_count)
        }
    
    def clear(self):
        """Clear the entire hash ring."""
        self._ring.clear()
        self._sorted_keys.clear()
        self._nodes.clear()
        self._key_count.clear()
        logger.info("Hash ring cleared")
    
    def __len__(self) -> int:
        """Get number of physical nodes in the ring."""
        return len(self._nodes)
    
    def __contains__(self, node_id: str) -> bool:
        """Check if a node is in the ring."""
        return node_id in self._nodes