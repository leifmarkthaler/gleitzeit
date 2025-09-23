"""
Base worker framework for Gleitzeit 0.0.7 - Redis Cluster Edition

All workers use Redis Cluster with hash-tag based sharding for workflow locality.
"""

import asyncio
import logging
import signal
import json
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass
from datetime import datetime
import uuid

from ..core.redis_cluster import GleitzeitRedisCluster, RedisConfig
from .pending_recovery import PendingRecoveryMixin

logger = logging.getLogger(__name__)


@dataclass
class WorkerConfig:
    """Configuration for a worker instance"""
    worker_type: str
    worker_id: str
    consumer_group: str
    redis_url: str = None  # Not used with cluster
    assigned_shards: List[int] = None
    max_concurrent: int = 10
    batch_size: int = 10
    block_timeout: int = 5000  # milliseconds
    heartbeat_interval: int = 30  # seconds


class BaseWorker(ABC, PendingRecoveryMixin):
    """
    Base class for all Gleitzeit workers - Redis Cluster optimized.

    Features:
    - Redis Cluster with connection pooling per node
    - Hash-tag based sharding for workflow locality
    - Concurrent processing with semaphore
    - Health monitoring and heartbeat
    - Graceful shutdown
    """

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.logger = logging.getLogger(f"{config.worker_type}.{config.worker_id}")
        self.redis: Optional[GleitzeitRedisCluster] = None

        # Worker state
        self._running = False
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._tasks: Dict[str, asyncio.Task] = {}
        self.messages_processed = 0
        self.messages_failed = 0
        self.started_at = datetime.utcnow()

        # Consumer groups tracking
        self._consumer_groups_created = set()

        # Sharding - default to all 16 shards
        self.assigned_shards = config.assigned_shards or list(range(16))

    async def initialize(self):
        """Initialize worker with Redis Cluster"""
        # Initialize Redis Cluster connection with pooling
        self.redis = GleitzeitRedisCluster()
        await self.redis.initialize()

        # Custom initialization for specific worker types
        await self.on_initialize()

        # Register worker in service discovery
        await self._register_worker()

        self.logger.info(f"Worker {self.config.worker_id} initialized with Redis Cluster, shards {self.assigned_shards}")

    @abstractmethod
    async def on_initialize(self):
        """Override for custom initialization"""
        pass

    @abstractmethod
    def get_base_streams(self) -> List[str]:
        """
        Return base stream names (without shard suffix).
        Example: ["task:ready", "task:retry"]
        """
        pass

    @abstractmethod
    async def process_message(self, stream: str, message_id: str, data: Dict) -> bool:
        """
        Process a single message from the stream.

        Args:
            stream: Stream key the message came from
            message_id: Redis stream message ID
            data: Message data

        Returns:
            True if message was processed successfully and should be ACK'd
            False if message failed and should not be ACK'd
        """
        pass

    def get_stream_patterns(self) -> Dict[bytes, bytes]:
        """Get cluster-compatible stream patterns with hash tags"""
        patterns = {}
        for base_stream in self.get_base_streams():
            for shard in self.assigned_shards:
                # Use hash tag format for cluster routing
                # Use ">" to read new messages (including those from before group creation)
                # The pending recovery mixin handles stuck messages separately
                stream_key = f"{{shard:{shard}}}:{base_stream}".encode()
                patterns[stream_key] = b">"
        return patterns

    async def run(self):
        """Main worker loop"""
        self._running = True

        # Setup graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown)

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start pending recovery task (claims stuck messages)
        await self.start_recovery_task()

        try:
            while self._running:
                try:
                    # Read from sharded streams
                    streams = self.get_stream_patterns()

                    # Ensure consumer groups exist
                    await self._ensure_consumer_groups(streams)

                    # Blocking read from streams
                    messages = await self.redis.xreadgroup(
                        self.config.consumer_group.encode(),
                        self.config.worker_id.encode(),
                        streams,
                        count=self.config.batch_size,
                        block=self.config.block_timeout
                    )

                    if messages:
                        # Process messages concurrently with semaphore
                        tasks = []
                        for stream_key, stream_messages in messages:
                            for msg_id, data in stream_messages:
                                task = asyncio.create_task(
                                    self._process_with_semaphore(
                                        stream_key.decode(),
                                        msg_id.decode(),
                                        data
                                    )
                                )
                                tasks.append(task)

                        # Wait for batch to complete
                        await asyncio.gather(*tasks, return_exceptions=True)

                except Exception as e:
                    self.logger.error(f"Error in worker loop: {e}", exc_info=True)
                    await asyncio.sleep(1)

        finally:
            self._running = False
            heartbeat_task.cancel()
            await self.stop_recovery_task()  # Stop recovery task
            await self._cleanup()

    async def _ensure_consumer_groups(self, streams: Dict[bytes, bytes]):
        """Create consumer groups if they don't exist"""
        for stream_key in streams.keys():
            if stream_key not in self._consumer_groups_created:
                try:
                    await self.redis.xgroup_create(
                        stream_key,
                        self.config.consumer_group.encode(),
                        id=b"0",
                        mkstream=True
                    )
                    self._consumer_groups_created.add(stream_key)
                    self.logger.debug(f"Created consumer group for {stream_key.decode()}")
                except Exception as e:
                    # Group might already exist
                    if "BUSYGROUP" not in str(e):
                        self.logger.warning(f"Could not create consumer group: {e}")

    async def _process_with_semaphore(self, stream: str, msg_id: str, raw_data: Dict):
        """Process message with concurrency control and proper ACK/NACK handling"""
        async with self._semaphore:
            try:
                # Decode data
                data = {}
                for k, v in raw_data.items():
                    key = k.decode() if isinstance(k, bytes) else k
                    value = v.decode() if isinstance(v, bytes) else v
                    data[key] = value

                # Process message and get success status
                success = await self.process_message(stream, msg_id, data)

                if success:
                    # Only ACK if processing was successful
                    await self.redis.xack(
                        stream.encode(),
                        self.config.consumer_group.encode(),
                        msg_id.encode()
                    )
                    self.messages_processed += 1
                    self.logger.debug(f"Successfully processed and ACK'd message {msg_id}")
                else:
                    # Don't ACK - leave message in pending state for retry
                    self.messages_failed += 1
                    self.logger.warning(f"Message {msg_id} processing failed, not ACK'd (will retry)")

                    # Emit to dead letter queue immediately (stateless)
                    # Let Redis Streams handle retry via pending entries
                    await self._emit_to_dead_letter_queue(stream, msg_id, data, "Processing returned False")

            except Exception as e:
                self.logger.error(f"Exception processing message {msg_id}: {e}", exc_info=True)
                self.messages_failed += 1

                # Don't ACK on exception - leave for retry
                # Emit to DLQ for tracking
                try:
                    decoded_data = {}
                    for k, v in raw_data.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        value = v.decode() if isinstance(v, bytes) else v
                        decoded_data[key] = value
                    await self._emit_to_dead_letter_queue(stream, msg_id, decoded_data, str(e))
                except:
                    pass  # Don't fail if DLQ emission fails

    async def _register_worker(self):
        """Register worker in Redis Cluster for service discovery"""
        worker_info = {
            "worker_type": self.config.worker_type,
            "worker_id": self.config.worker_id,
            "shards": json.dumps(self.assigned_shards),
            "started_at": self.started_at.isoformat(),
            "status": "running",
            "host": "localhost",  # Could get actual hostname
            "pid": asyncio.get_event_loop()._thread_id if hasattr(asyncio.get_event_loop(), '_thread_id') else 0
        }

        # Worker registry goes to shard 0 for consistency
        key = f"{{shard:0}}:worker:registry:{self.config.worker_type}:{self.config.worker_id}"
        await self.redis.hset(key.encode(), mapping={
            k.encode(): v.encode() if isinstance(v, str) else str(v).encode()
            for k, v in worker_info.items()
        })

        # Set TTL for health monitoring
        await self.redis.expire(key.encode(), 60)

    async def _heartbeat_loop(self):
        """Send periodic heartbeats"""
        while self._running:
            try:
                await self._register_worker()  # Refresh registration

                # Update metrics (also on shard 0)
                metrics_key = f"{{shard:0}}:worker:metrics:{self.config.worker_id}"
                await self.redis.hset(metrics_key.encode(), mapping={
                    b"processed": str(self.messages_processed).encode(),
                    b"failed": str(self.messages_failed).encode(),
                    b"uptime": str((datetime.utcnow() - self.started_at).total_seconds()).encode(),
                    b"last_heartbeat": datetime.utcnow().isoformat().encode()
                })

                await asyncio.sleep(self.config.heartbeat_interval)

            except Exception as e:
                self.logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(5)

    def _handle_shutdown(self):
        """Handle graceful shutdown"""
        self.logger.info(f"Shutdown signal received for {self.config.worker_id}")
        self._running = False

    async def _emit_to_dead_letter_queue(self, stream: str, msg_id: str, data: Any, error: str = None):
        """Emit failed messages to dead letter queue (stateless - no tracking)"""
        try:
            # Extract workflow_id and task_id if available
            if isinstance(data, dict):
                workflow_id = data.get('workflow_id', 'unknown')
                task_id = data.get('task_id', 'unknown')
                data_str = json.dumps(data)
            else:
                workflow_id = 'unknown'
                task_id = 'unknown'
                data_str = str(data)

            # Emit to dead letter queue stream (for monitoring/alerting)
            dlq_stream = "dead_letter:tasks"

            # Prepare the DLQ message
            dlq_data = {
                b"original_stream": stream.encode(),
                b"message_id": msg_id.encode(),
                b"workflow_id": workflow_id.encode() if isinstance(workflow_id, str) else workflow_id,
                b"task_id": task_id.encode() if isinstance(task_id, str) else task_id,
                b"error": (error or "Processing failed").encode(),
                b"failed_at": datetime.utcnow().isoformat().encode(),
                b"worker_id": self.config.worker_id.encode(),
                b"original_data": data_str.encode()
            }

            await self.redis.xadd(dlq_stream.encode(), dlq_data)

            self.logger.info(f"Message {msg_id} from {stream} logged to dead letter queue")

        except Exception as e:
            self.logger.error(f"Failed to emit to dead letter queue: {e}", exc_info=True)

    async def _cleanup(self):
        """Cleanup worker resources"""
        # Cancel any active tasks
        for task in self._tasks.values():
            task.cancel()

        # Unregister worker from cluster
        key = f"{{shard:0}}:worker:registry:{self.config.worker_type}:{self.config.worker_id}"
        await self.redis.delete(key.encode())

        # Close Redis Cluster connections
        if self.redis:
            await self.redis.close()

        self.logger.info(f"Worker {self.config.worker_id} cleaned up")

    # Helper methods for cluster operations

    def get_workflow_key(self, workflow_id: str, key_type: str) -> str:
        """
        Get cluster-compatible workflow key with hash tag.

        All keys for a workflow use the same hash tag to ensure they're
        on the same Redis node, enabling atomic operations.
        """
        import hashlib
        shard = int(hashlib.md5(workflow_id.encode()).hexdigest(), 16) % 16
        return f"{{shard:{shard}}}:workflow:{key_type}:{workflow_id}"

    def get_task_key(self, task_id: str, workflow_id: str) -> str:
        """Get cluster-compatible task key ensuring workflow locality"""
        import hashlib
        shard = int(hashlib.md5(workflow_id.encode()).hexdigest(), 16) % 16
        return f"{{shard:{shard}}}:task:status:{task_id}"

    def get_stream_key(self, base_stream: str, workflow_id: str) -> str:
        """Get cluster-compatible stream key for workflow"""
        import hashlib
        shard = int(hashlib.md5(workflow_id.encode()).hexdigest(), 16) % 16
        return f"{{shard:{shard}}}:{base_stream}"

    async def pipeline_for_workflow(self, workflow_id: str):
        """
        Create a pipeline for a workflow.

        All operations for a workflow go to the same Redis node
        due to hash tags, so pipelining works perfectly!
        """
        return self.redis.pipeline(transaction=False)