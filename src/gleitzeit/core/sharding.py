"""
Sharding utilities for Gleitzeit 0.0.7 - Redis Cluster Edition

All keys use hash tags for Redis Cluster routing to ensure workflow locality.
"""

from typing import Dict, List
import hashlib


class ClusterShardingStrategy:
    """
    Workflow-based sharding strategy for Redis Cluster.

    All tasks from the same workflow go to the same Redis node using
    hash tags, ensuring:
    - Atomic operations work (all keys on same node)
    - Pipeline operations work
    - Lua scripts work
    - No cross-slot errors
    """

    def __init__(self, num_shards: int = 16):
        """
        Initialize sharding strategy.

        Args:
            num_shards: Number of logical shards (16 maps well to Redis Cluster's 16384 slots)
        """
        self.num_shards = num_shards

    def get_shard(self, workflow_id: str) -> int:
        """
        Get shard number for a workflow ID.

        Uses consistent hashing to ensure all tasks from the same workflow
        go to the same shard (and thus the same Redis node).

        Args:
            workflow_id: Workflow identifier

        Returns:
            Shard number (0 to num_shards-1)
        """
        hash_value = int(hashlib.md5(workflow_id.encode()).hexdigest(), 16)
        return hash_value % self.num_shards

    def get_stream_key(self, base_stream: str, workflow_id: str = None, shard: int = None) -> str:
        """
        Get sharded stream key with Redis Cluster hash tag.

        Args:
            base_stream: Base stream name (e.g., "task:ready")
            workflow_id: Workflow identifier (to calculate shard)
            shard: Direct shard number (if known)

        Returns:
            Cluster-compatible key like "{shard:5}:task:ready"
        """
        if shard is None:
            if workflow_id is None:
                raise ValueError("Either workflow_id or shard must be provided")
            shard = self.get_shard(workflow_id)

        return f"{{shard:{shard}}}:{base_stream}"

    def get_workflow_key(self, key_type: str, workflow_id: str) -> str:
        """
        Get workflow-specific key with hash tag for cluster routing.

        Args:
            key_type: Type of key (data, status, signals, etc.)
            workflow_id: Workflow identifier

        Returns:
            Cluster key like "{shard:5}:workflow:data:workflow123"
        """
        shard = self.get_shard(workflow_id)
        return f"{{shard:{shard}}}:workflow:{key_type}:{workflow_id}"

    def get_task_key(self, task_id: str, workflow_id: str) -> str:
        """
        Get task-specific key ensuring workflow locality.

        Args:
            task_id: Task identifier
            workflow_id: Workflow identifier (for sharding)

        Returns:
            Cluster key like "{shard:5}:task:status:task123"
        """
        shard = self.get_shard(workflow_id)
        return f"{{shard:{shard}}}:task:status:{task_id}"

    def get_signal_key(self, signal_type: str, workflow_id: str, signal_name: str = None) -> str:
        """
        Get signal-related key with cluster routing.

        Args:
            signal_type: Type of signal key (waiters, metadata, etc.)
            workflow_id: Workflow identifier
            signal_name: Optional signal name

        Returns:
            Cluster key like "{shard:5}:signal:waiters:workflow123:signal-name"
        """
        shard = self.get_shard(workflow_id)
        base_key = f"{{shard:{shard}}}:signal:{signal_type}:{workflow_id}"

        if signal_name:
            return f"{base_key}:{signal_name}"
        return base_key

    def get_timer_key(self, timer_type: str, workflow_id: str = None) -> str:
        """
        Get timer-related key with cluster routing.

        Args:
            timer_type: Type of timer key (pending, active, etc.)
            workflow_id: Optional workflow ID for workflow-specific timers

        Returns:
            Cluster key with appropriate hash tag
        """
        if workflow_id:
            shard = self.get_shard(workflow_id)
            return f"{{shard:{shard}}}:timer:{timer_type}:{workflow_id}"
        else:
            # Global timer keys go to shard 0 for consistency
            return f"{{shard:0}}:timer:{timer_type}"

    def get_global_key(self, key_type: str) -> str:
        """
        Get global key that's not workflow-specific.

        Global keys all go to shard 0 for consistency.

        Args:
            key_type: Type of global key

        Returns:
            Cluster key like "{shard:0}:global:key_type"
        """
        return f"{{shard:0}}:global:{key_type}"

    def get_worker_key(self, worker_type: str, worker_id: str) -> str:
        """
        Get worker-specific key.

        All worker keys go to shard 0 for centralized management.

        Args:
            worker_type: Type of worker
            worker_id: Worker identifier

        Returns:
            Cluster key like "{shard:0}:worker:registry:type:id"
        """
        return f"{{shard:0}}:worker:registry:{worker_type}:{worker_id}"

    def get_metrics_key(self, metric_type: str, identifier: str = None) -> str:
        """
        Get metrics key.

        All metrics go to shard 0 for easy aggregation.

        Args:
            metric_type: Type of metric
            identifier: Optional identifier (worker_id, workflow_id, etc.)

        Returns:
            Cluster key like "{shard:0}:metrics:type:id"
        """
        if identifier:
            return f"{{shard:0}}:metrics:{metric_type}:{identifier}"
        return f"{{shard:0}}:metrics:{metric_type}"

    def get_shards_for_worker(self, worker_index: int, total_workers: int) -> List[int]:
        """
        Get shards assigned to a worker based on round-robin distribution.

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

        Args:
            workflow_id: Workflow identifier
            total_workers: Total number of workers

        Returns:
            Worker index (0 to total_workers-1)
        """
        shard = self.get_shard(workflow_id)
        return shard % total_workers

    def can_pipeline(self, workflow_ids: List[str]) -> Dict[int, List[str]]:
        """
        Group workflows that can be pipelined together.

        In Redis Cluster, only operations on keys with the same hash tag
        can be pipelined together.

        Args:
            workflow_ids: List of workflow IDs

        Returns:
            Dictionary mapping shard number to list of workflow IDs
        """
        groups = {}
        for wf_id in workflow_ids:
            shard = self.get_shard(wf_id)
            if shard not in groups:
                groups[shard] = []
            groups[shard].append(wf_id)
        return groups

    def get_all_keys_for_workflow(self, workflow_id: str) -> Dict[str, str]:
        """
        Get all standard keys for a workflow.

        Useful for debugging and cleanup operations.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Dictionary of key types to actual Redis keys
        """
        shard = self.get_shard(workflow_id)
        prefix = f"{{shard:{shard}}}"

        return {
            "workflow_data": f"{prefix}:workflow:data:{workflow_id}",
            "workflow_status": f"{prefix}:workflow:status:{workflow_id}",
            "workflow_signals": f"{prefix}:workflow:signals:{workflow_id}",
            "task_ready_stream": f"{prefix}:task:ready",
            "task_executing_stream": f"{prefix}:task:executing",
            "task_completed_stream": f"{prefix}:task:completed",
            "task_failed_stream": f"{prefix}:task:failed",
            "dependency_resolved": f"{prefix}:dependency:resolved:{workflow_id}",
            "dependency_pending": f"{prefix}:dependency:pending:{workflow_id}"
        }


# Global instance for convenience
default_sharding = ClusterShardingStrategy(num_shards=16)

# For backward compatibility (if needed temporarily)
ShardingStrategy = ClusterShardingStrategy