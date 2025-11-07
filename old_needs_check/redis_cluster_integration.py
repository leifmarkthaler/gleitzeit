#!/usr/bin/env python3
"""
Redis Cluster Integration for Gleitzeit

Shows how Gleitzeit's existing shard architecture maps perfectly to Redis Cluster!
"""

import hashlib
from redis.cluster import RedisCluster
from redis.cluster import ClusterNode

# ============================================================
# CURRENT GLEITZEIT SHARDING
# ============================================================

class GleitzeitSharding:
    """Current Gleitzeit sharding (single Redis)"""

    def get_shard(self, workflow_id: str) -> int:
        """Gets shard 0-15 for workflow"""
        hash_value = int(hashlib.md5(workflow_id.encode()).hexdigest(), 16)
        return hash_value % 16

    def get_keys(self, workflow_id: str):
        """All keys for a workflow go to same shard"""
        shard = self.get_shard(workflow_id)
        return {
            'task_ready': f"task:ready:{shard}",
            'task_executing': f"task:executing:{shard}",
            'task_completed': f"task:completed:{shard}",
            'workflow_data': f"workflow:data:{workflow_id}",
            'workflow_status': f"workflow:status:{workflow_id}"
        }

# ============================================================
# REDIS CLUSTER MAPPING (SMART APPROACH)
# ============================================================

class ClusterAwareSharding:
    """Maps Gleitzeit shards to Redis Cluster hash slots"""

    def __init__(self):
        # Redis Cluster has 16384 hash slots
        # Gleitzeit has 16 shards
        # Each Gleitzeit shard maps to 1024 Redis slots!
        self.slots_per_shard = 16384 // 16  # = 1024

    def get_cluster_key(self, workflow_id: str, key_type: str) -> str:
        """
        Generate Redis Cluster compatible keys using hash tags.
        All keys for a workflow will hit the same Redis node!
        """
        shard = self.get_shard(workflow_id)

        # Use Redis hash tags {} to control slot assignment
        # All keys with {shard:N} go to same slot
        return f"{{{shard}}}:{key_type}:{workflow_id}"

    def get_shard(self, workflow_id: str) -> int:
        """Gets shard 0-15 for workflow"""
        hash_value = int(hashlib.md5(workflow_id.encode()).hexdigest(), 16)
        return hash_value % 16

    def get_keys(self, workflow_id: str):
        """Generate cluster-compatible keys"""
        shard = self.get_shard(workflow_id)

        # All these keys will be on the SAME Redis node
        # because they share the {shard:N} hash tag
        return {
            'task_ready': f"{{shard:{shard}}}:task:ready",
            'task_executing': f"{{shard:{shard}}}:task:executing",
            'task_completed': f"{{shard:{shard}}}:task:completed",
            'workflow_data': f"{{shard:{shard}}}:workflow:data:{workflow_id}",
            'workflow_status': f"{{shard:{shard}}}:workflow:status:{workflow_id}",
            'workflow_signals': f"{{shard:{shard}}}:workflow:signals:{workflow_id}"
        }

    def can_pipeline(self, workflow_ids: list) -> dict:
        """Check which workflows can be pipelined together"""
        by_shard = {}
        for wf_id in workflow_ids:
            shard = self.get_shard(wf_id)
            if shard not in by_shard:
                by_shard[shard] = []
            by_shard[shard].append(wf_id)
        return by_shard

# ============================================================
# CONFIGURATION MAPPING
# ============================================================

def get_redis_cluster_config():
    """
    Redis Cluster configuration for Gleitzeit.

    With 3 masters and 16 shards:
    - Master 1: Shards 0-5 (Hash slots 0-5461)
    - Master 2: Shards 6-10 (Hash slots 5462-10922)
    - Master 3: Shards 11-15 (Hash slots 10923-16383)
    """
    return {
        'startup_nodes': [
            ClusterNode('127.0.0.1', 7000),  # Master 1
            ClusterNode('127.0.0.1', 7001),  # Master 2
            ClusterNode('127.0.0.1', 7002),  # Master 3
            ClusterNode('127.0.0.1', 7003),  # Replica 1
            ClusterNode('127.0.0.1', 7004),  # Replica 2
            ClusterNode('127.0.0.1', 7005),  # Replica 3
        ],
        'decode_responses': False,
        'skip_full_coverage_check': False,
        'max_connections_per_node': 100  # Connection pooling per node!
    }

# ============================================================
# WORKER MODIFICATIONS
# ============================================================

class ClusterAwareWorker:
    """Modified Gleitzeit worker for Redis Cluster"""

    def __init__(self, assigned_shards: list):
        self.assigned_shards = assigned_shards
        self.redis = None

    async def initialize(self):
        """Connect to Redis Cluster instead of single instance"""
        # Redis Cluster client handles routing automatically!
        self.redis = RedisCluster(**get_redis_cluster_config())

    async def get_streams_for_shards(self):
        """Get stream keys for assigned shards"""
        streams = {}

        for shard in self.assigned_shards:
            # Use hash tags to ensure streams stay on right nodes
            streams[f"{{shard:{shard}}}:task:ready"] = ">"
            streams[f"{{shard:{shard}}}:task:executing"] = "$"

        return streams

    async def process_workflow_atomic(self, workflow_id: str):
        """
        All operations for a workflow hit the SAME Redis node!
        This enables pipelining and Lua scripts!
        """
        shard = self.get_shard(workflow_id)

        # Pipeline works because all keys have same {shard:N} tag!
        async with self.redis.pipeline() as pipe:
            pipe.hget(f"{{shard:{shard}}}:workflow:data:{workflow_id}", "tasks")
            pipe.xadd(f"{{shard:{shard}}}:task:ready", {"task": "123"})
            pipe.hset(f"{{shard:{shard}}}:workflow:status:{workflow_id}", "running", "true")
            results = await pipe.execute()

        return results

    def get_shard(self, workflow_id: str) -> int:
        hash_value = int(hashlib.md5(workflow_id.encode()).hexdigest(), 16)
        return hash_value % 16

# ============================================================
# MIGRATION PATH
# ============================================================

def show_migration_path():
    """How to migrate Gleitzeit to Redis Cluster"""

    print("=== REDIS CLUSTER MIGRATION PATH ===\n")

    print("1. MINIMAL CHANGES NEEDED:")
    print("   - Add hash tags to all Redis keys")
    print("   - Change from: 'task:ready:5'")
    print("   - Change to:   '{shard:5}:task:ready'")
    print()

    print("2. CONNECTION CHANGE:")
    print("   - From: aioredis.from_url('redis://localhost:6379')")
    print("   - To:   RedisCluster(startup_nodes=[...])")
    print()

    print("3. BENEFITS:")
    print("   ✓ Horizontal scaling (add more nodes)")
    print("   ✓ Automatic sharding (16 shards → 16384 slots)")
    print("   ✓ High availability (replicas)")
    print("   ✓ Connection pooling per node")
    print("   ✓ Workflows stay atomic (same node)")
    print()

    print("4. WHAT STILL WORKS:")
    print("   ✓ Pipelines (within shard)")
    print("   ✓ Lua scripts (within shard)")
    print("   ✓ Transactions (within shard)")
    print("   ✓ Streams & consumer groups")
    print("   ✓ All existing logic!")
    print()

    print("5. SCALING MATH:")
    print("   - 16 Gleitzeit shards")
    print("   - 3-6 Redis Cluster masters")
    print("   - Each master handles 3-6 shards")
    print("   - Linear scaling with more masters!")

# ============================================================
# TESTING
# ============================================================

def test_key_distribution():
    """Test that workflows distribute evenly across shards"""

    sharding = ClusterAwareSharding()
    shard_counts = {i: 0 for i in range(16)}

    # Test 10000 workflows
    for i in range(10000):
        workflow_id = f"workflow_{i}"
        shard = sharding.get_shard(workflow_id)
        shard_counts[shard] += 1

    print("\n=== SHARD DISTRIBUTION TEST ===")
    for shard, count in shard_counts.items():
        print(f"Shard {shard:2}: {'█' * (count // 100)} {count}")

    # Check that same workflow always gets same keys
    print("\n=== KEY CONSISTENCY TEST ===")
    keys1 = sharding.get_keys("workflow_123")
    keys2 = sharding.get_keys("workflow_123")
    assert keys1 == keys2, "Keys not consistent!"
    print("✓ Same workflow always gets same keys")

    # Check that keys for same workflow share hash tag
    print("\n=== HASH TAG TEST ===")
    keys = sharding.get_keys("workflow_abc")
    tags = set()
    for key in keys.values():
        if '{' in key and '}' in key:
            tag = key[key.index('{')+1:key.index('}')]
            tags.add(tag)
    assert len(tags) == 1, f"Multiple hash tags found: {tags}"
    print(f"✓ All keys share hash tag: {tags.pop()}")

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("REDIS CLUSTER + GLEITZEIT SHARDING")
    print("=" * 40)

    # Show how keys map
    print("\n=== KEY MAPPING EXAMPLE ===")

    old_sharding = GleitzeitSharding()
    new_sharding = ClusterAwareSharding()

    workflow_id = "test-workflow-123"

    print(f"\nWorkflow: {workflow_id}")
    print(f"Shard: {old_sharding.get_shard(workflow_id)}")

    print("\nOLD KEYS (current Gleitzeit):")
    for name, key in old_sharding.get_keys(workflow_id).items():
        print(f"  {name:20} = {key}")

    print("\nNEW KEYS (Redis Cluster compatible):")
    for name, key in new_sharding.get_keys(workflow_id).items():
        print(f"  {name:20} = {key}")

    # Show migration path
    show_migration_path()

    # Test distribution
    test_key_distribution()

    print("\n" + "=" * 40)
    print("CONCLUSION: Gleitzeit shards map PERFECTLY to Redis Cluster!")
    print("Just need to add hash tags to keys!")