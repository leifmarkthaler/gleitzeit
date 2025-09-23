"""
Enhanced sharding module with Redis Cluster support for Gleitzeit 0.0.7

Extends the existing sharding strategy to support Redis Cluster while
maintaining backward compatibility.
"""

import os
import hashlib
from typing import Optional, Dict, List, Any
from enum import Enum


class ShardingMode(str, Enum):
    """Sharding modes"""
    SINGLE = "single"  # Traditional single Redis with numeric shards
    CLUSTER = "cluster"  # Redis Cluster with hash tags


class EnhancedShardingStrategy:
    """
    Workflow-based sharding strategy with Redis Cluster support.

    This strategy maintains the same logical sharding (workflows to shards)
    but adapts the key format based on the deployment mode:
    - Single Redis: Keys use suffix format (e.g., "task:ready:5")
    - Redis Cluster: Keys use hash tag format (e.g., "{shard:5}:task:ready")
    """

    def __init__(
        self,
        num_shards: int = 16,
        mode: ShardingMode = None
    ):
        """
        Initialize enhanced sharding strategy.

        Args:
            num_shards: Number of logical shards (default 16)
            mode: Sharding mode (auto-detected if not specified)
        """
        self.num_shards = num_shards
        self.mode = mode or self._detect_mode()
        self.shard_assignments: Dict[str, int] = {}  # Cache workflow->shard mappings

    def _detect_mode(self) -> ShardingMode:
        """Auto-detect sharding mode from environment"""
        if os.getenv("REDIS_CLUSTER_ENABLED", "").lower() == "true":
            return ShardingMode.CLUSTER
        if os.getenv("REDIS_CLUSTER_NODES"):
            return ShardingMode.CLUSTER
        return ShardingMode.SINGLE

    def get_shard(self, workflow_id: str) -> int:
        """
        Get shard number for a workflow ID.

        Uses consistent hashing to ensure all tasks from the same workflow
        go to the same shard. This is unchanged from the original implementation.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Shard number (0 to num_shards-1)
        """
        if workflow_id not in self.shard_assignments:
            hash_value = int(hashlib.md5(workflow_id.encode()).hexdigest(), 16)
            self.shard_assignments[workflow_id] = hash_value % self.num_shards

        return self.shard_assignments[workflow_id]

    def get_shard_key(self, workflow_id: str = None, shard: int = None) -> str:
        """
        Get shard key in the appropriate format for the mode.

        Args:
            workflow_id: Workflow ID (to calculate shard)
            shard: Direct shard number (if known)

        Returns:
            In SINGLE mode: "5"
            In CLUSTER mode: "{shard:5}"
        """
        if shard is None:
            if workflow_id is None:
                raise ValueError("Either workflow_id or shard must be provided")
            shard = self.get_shard(workflow_id)

        if self.mode == ShardingMode.CLUSTER:
            return f"{{shard:{shard}}}"
        else:
            return str(shard)

    def get_stream_key(self, base_stream: str, workflow_id: str = None, shard: int = None) -> str:
        """
        Get sharded stream key for a workflow.

        Args:
            base_stream: Base stream name (e.g., "task:ready")
            workflow_id: Workflow identifier
            shard: Direct shard number (if known)

        Returns:
            In SINGLE mode: "task:ready:5"
            In CLUSTER mode: "{shard:5}:task:ready"
        """
        shard_key = self.get_shard_key(workflow_id, shard)

        if self.mode == ShardingMode.CLUSTER:
            # Cluster format: hash tag prefix
            return f"{shard_key}:{base_stream}"
        else:
            # Single format: shard suffix
            return f"{base_stream}:{shard_key}"

    def get_workflow_key(self, key_type: str, workflow_id: str) -> str:
        """
        Get workflow-specific key with proper sharding.

        Args:
            key_type: Type of key (data, status, signals, etc.)
            workflow_id: Workflow identifier

        Returns:
            In SINGLE mode: "workflow:data:workflow123"
            In CLUSTER mode: "{shard:5}:workflow:data:workflow123"
        """
        if self.mode == ShardingMode.CLUSTER:
            shard_key = self.get_shard_key(workflow_id=workflow_id)
            return f"{shard_key}:workflow:{key_type}:{workflow_id}"
        else:
            return f"workflow:{key_type}:{workflow_id}"

    def get_task_key(self, task_id: str, workflow_id: str) -> str:
        """
        Get task-specific key ensuring workflow locality.

        Args:
            task_id: Task identifier
            workflow_id: Workflow identifier (for sharding)

        Returns:
            In SINGLE mode: "task:status:task123"
            In CLUSTER mode: "{shard:5}:task:status:task123"
        """
        if self.mode == ShardingMode.CLUSTER:
            shard_key = self.get_shard_key(workflow_id=workflow_id)
            return f"{shard_key}:task:status:{task_id}"
        else:
            return f"task:status:{task_id}"

    def get_signal_key(self, signal_type: str, workflow_id: str, signal_name: str = None) -> str:
        """
        Get signal-related key with proper sharding.

        Args:
            signal_type: Type of signal key (waiters, metadata, etc.)
            workflow_id: Workflow identifier
            signal_name: Optional signal name

        Returns:
            Properly formatted signal key
        """
        if self.mode == ShardingMode.CLUSTER:
            shard_key = self.get_shard_key(workflow_id=workflow_id)
            base_key = f"{shard_key}:signal:{signal_type}:{workflow_id}"
        else:
            base_key = f"signal:{signal_type}:{workflow_id}"

        if signal_name:
            return f"{base_key}:{signal_name}"
        return base_key

    def get_timer_key(self, timer_type: str, workflow_id: str = None) -> str:
        """
        Get timer-related key with proper sharding.

        Args:
            timer_type: Type of timer key (pending, active, etc.)
            workflow_id: Optional workflow ID for workflow-specific timers

        Returns:
            Properly formatted timer key
        """
        if workflow_id:
            if self.mode == ShardingMode.CLUSTER:
                shard_key = self.get_shard_key(workflow_id=workflow_id)
                return f"{shard_key}:timer:{timer_type}:{workflow_id}"
            else:
                return f"timer:{timer_type}:{workflow_id}"
        else:
            # Global timer keys (for timer worker)
            if self.mode == ShardingMode.CLUSTER:
                # Global timers go to shard 0 for consistency
                return f"{{shard:0}}:timer:{timer_type}"
            else:
                return f"timer:{timer_type}"

    def get_shards_for_worker(self, worker_index: int, total_workers: int) -> List[int]:
        """
        Get shards assigned to a worker based on round-robin distribution.

        This is unchanged from the original implementation.

        Args:
            worker_index: Zero-based worker index
            total_workers: Total number of workers

        Returns:
            List of shard numbers assigned to this worker
        """
        shards = []
        for shard in range(self.num_shards):
            if shard % total_workers == worker_index:
                shards.append(shard)
        return shards

    def get_worker_for_workflow(self, workflow_id: str, total_workers: int) -> int:
        """
        Determine which worker should handle a workflow.

        This is unchanged from the original implementation.

        Args:
            workflow_id: Workflow identifier
            total_workers: Total number of workers

        Returns:
            Worker index (0 to total_workers-1)
        """
        shard = self.get_shard(workflow_id)
        return shard % total_workers

    def can_pipeline(self, workflow_ids: List[str]) -> Dict[str, List[str]]:
        """
        Group workflows that can be pipelined together.

        In cluster mode, only workflows mapping to the same shard can be
        pipelined together since they'll be on the same Redis node.

        Args:
            workflow_ids: List of workflow IDs

        Returns:
            Dictionary mapping shard key to list of workflow IDs
        """
        groups = {}
        for wf_id in workflow_ids:
            shard_key = self.get_shard_key(workflow_id=wf_id)
            if shard_key not in groups:
                groups[shard_key] = []
            groups[shard_key].append(wf_id)
        return groups

    def migrate_key(self, old_key: str, workflow_id: str = None) -> str:
        """
        Migrate a key from single Redis format to cluster format.

        Args:
            old_key: Key in single Redis format
            workflow_id: Workflow ID if known (for proper sharding)

        Returns:
            Key in the appropriate format for current mode

        Examples:
            Single to Cluster:
                task:ready:5 -> {shard:5}:task:ready
                workflow:data:abc123 -> {shard:7}:workflow:data:abc123
        """
        if self.mode == ShardingMode.SINGLE:
            return old_key  # No migration needed

        # Parse the old key
        parts = old_key.split(":")

        # Handle sharded stream keys (e.g., task:ready:5)
        if len(parts) >= 3 and parts[-1].isdigit():
            shard = int(parts[-1])
            base_stream = ":".join(parts[:-1])
            return self.get_stream_key(base_stream, shard=shard)

        # Handle workflow keys (e.g., workflow:data:abc123)
        if parts[0] == "workflow" and len(parts) >= 3:
            key_type = parts[1]
            wf_id = parts[2] if not workflow_id else workflow_id
            return self.get_workflow_key(key_type, wf_id)

        # Handle task keys (e.g., task:status:task123)
        if parts[0] == "task" and len(parts) >= 3 and workflow_id:
            return self.get_task_key(parts[2], workflow_id)

        # Handle signal keys (e.g., signal:waiters:workflow123:signal-name)
        if parts[0] == "signal" and len(parts) >= 3:
            signal_type = parts[1]
            wf_id = parts[2] if not workflow_id else workflow_id
            signal_name = parts[3] if len(parts) > 3 else None
            return self.get_signal_key(signal_type, wf_id, signal_name)

        # Return unchanged if pattern not recognized
        return old_key

    def clear_cache(self):
        """Clear cached shard assignments"""
        self.shard_assignments.clear()


# Create global instance that can be imported
default_sharding = EnhancedShardingStrategy()

# For backward compatibility, expose original class name
ShardingStrategy = EnhancedShardingStrategy