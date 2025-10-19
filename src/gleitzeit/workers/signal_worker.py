"""
Signal worker for Gleitzeit 0.0.7

Handles signal-based task waking and workflow coordination using the worker architecture.
"""

import asyncio
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import time

from .base import BaseWorker, WorkerConfig
from ..core.sharding import default_sharding
from ..core.leader_election import LeaderElection, LeaderStatus
from ..core.events import EventType
from ..core.event_store import EventStore, EventLevel

logger = logging.getLogger(__name__)


class SignalWorker(BaseWorker):
    """
    Worker that processes signals and wakes waiting tasks.

    Features:
    - Signal delivery to waiting tasks
    - Signal timeout handling
    - Workflow-scoped signal isolation
    - Leader election for signal processing
    """

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.leader_election: Optional[LeaderElection] = None
        self.leader_key = default_sharding.get_global_key("signal:leader")
        self.leader_ttl = 10  # seconds
        self.last_heartbeat = 0
        self.check_interval = 0.5  # Check more frequently than timers

    async def on_initialize(self):
        """Initialize signal worker resources"""
        # Initialize event store for publishing signal events
        self.event_store = EventStore(self.redis, config={
            'max_events_per_workflow': 10000,
            'event_ttl_seconds': 86400 * 30  # 30 days
        })

        # Initialize atomic leader election
        self.leader_election = LeaderElection(
            self.redis,
            self.leader_key,
            self.config.worker_id,
            self.leader_ttl
        )
        logger.info(f"SignalWorker initialized with atomic leader election and event store")

    def get_base_streams(self) -> List[str]:
        """Return streams this worker consumes from"""
        # Signal worker doesn't consume streams - it processes Redis state
        return []

    async def run(self):
        """Enhanced run method with leader election and signal processing"""
        logger.info(f"Worker {self.config.worker_id} starting with consumer group {self.config.consumer_group}")

        self._running = True  # Important: Set running flag!

        # Start heartbeat task (includes worker registration and command checking)
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start leader election task
        election_task = asyncio.create_task(self._leader_election_loop())

        # Start signal processing (only if leader)
        signal_task = asyncio.create_task(self._signal_processing_loop())

        try:
            # Run all tasks
            await asyncio.gather(heartbeat_task, election_task, signal_task)
        except asyncio.CancelledError:
            logger.info("Worker cancelled")
        finally:
            # Cleanup
            heartbeat_task.cancel()
            if self.leader_election and self.leader_election.is_leader:
                await self.leader_election.release()

    async def _leader_election_loop(self):
        """Participate in atomic leader election for signal processing"""
        logger.info(f"Starting atomic leader election loop for {self.config.worker_id}")
        while self._running:
            try:
                # Atomic leader election
                status = await self.leader_election.try_elect()

                if status == LeaderStatus.BECAME_LEADER:
                    logger.info(f"Worker {self.config.worker_id} became signal leader")
                elif status == LeaderStatus.LOST_LEADERSHIP:
                    logger.info(f"Worker {self.config.worker_id} lost signal leadership")

                await asyncio.sleep(self.leader_ttl // 3)  # Heartbeat interval

            except Exception as e:
                logger.error(f"Leader election error: {e}")
                await asyncio.sleep(1)

    async def _signal_processing_loop(self):
        """Process signals (only when leader)"""
        logger.info(f"Signal processing loop started for {self.config.worker_id}")
        iteration = 0

        while self._running:
            try:
                iteration += 1
                # Log every 20th iteration to avoid spam, but always log first few
                if iteration <= 3 or iteration % 20 == 0:
                    logger.info(f"Signal processing loop iteration {iteration}")

                if self.leader_election and self.leader_election.is_leader:
                    # Process workflow signal streams with timeout to prevent hanging
                    try:
                        await asyncio.wait_for(
                            self._process_workflow_signals(),
                            timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Signal processing timed out after 5s, continuing")

                    # Check for signal timeouts
                    await self._check_signal_timeouts()

                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Signal processing error: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info(f"Signal processing loop ended for {self.config.worker_id}")

    async def _process_workflow_signals(self):
        """Process signals using global registry - eliminates race conditions"""
        try:
            # Scan for registry keys (now using individual keys with TTL instead of set)
            # Pattern: signal:registry:workflow_id:signal_name
            registry_pattern = "signal:registry:*"
            registry_keys = []

            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(cursor, match=registry_pattern, count=100)
                registry_keys.extend(keys)
                if cursor == 0:
                    break

            if not registry_keys:
                return

            logger.info(f"SignalWorker found {len(registry_keys)} signals in global registry")

            # Process each registry key: "signal:registry:workflow_id:signal_name"
            for registry_key in registry_keys:
                try:
                    # Decode key if bytes
                    key_str = registry_key.decode() if isinstance(registry_key, bytes) else registry_key

                    # Extract workflow_id and signal_name from key
                    # Key format: "signal:registry:workflow_id:signal_name"
                    parts = key_str.split(":", 3)  # Split into max 4 parts
                    if len(parts) < 4:
                        logger.warning(f"Invalid registry key format: {key_str}")
                        continue

                    workflow_id = parts[2]
                    signal_name = parts[3]

                    logger.info(f"Processing registry entry: workflow={workflow_id}, signal={signal_name}")

                    # Check if there are any waiters for this signal
                    waiting_key = default_sharding.get_signal_key("waiters", workflow_id, signal_name)
                    waiting_tasks = await self.redis.smembers(waiting_key)

                    if not waiting_tasks:
                        # No waiters yet, keep signal in registry for future processing
                        logger.info(f"No waiters for signal {signal_name} in workflow {workflow_id} - keeping in registry")
                        continue

                    logger.info(f"Found {len(waiting_tasks)} waiting tasks for signal {signal_name}")

                    # Get signal data from workflow stream
                    workflow_stream_key = default_sharding.get_all_keys_for_workflow(workflow_id)["workflow_signals"]

                    # Ensure consumer group exists for this stream
                    try:
                        await self.redis.xgroup_create(workflow_stream_key, "signal-workers", id="0")
                    except Exception:
                        # Group already exists - this is normal
                        pass

                    # Read messages from workflow stream to find this signal
                    messages = await self.redis.xreadgroup(
                        "signal-workers",
                        self.config.worker_id,
                        {workflow_stream_key: b">"},  # Read new messages only
                        count=100,  # Read more to find matching signal
                        block=0  # Non-blocking read
                    )

                    if not messages:
                        logger.info(f"No messages in stream for workflow {workflow_id} - signal may have been processed")
                        # Remove from registry since we have waiters but no signal in stream
                        await self.redis.delete(registry_key)
                        continue

                    # Process each message looking for matching signal name
                    signal_found = False
                    for stream_key, stream_messages in messages:
                        for msg_id, signal_data in stream_messages:
                            msg_signal_name = signal_data.get(b"signal", b"").decode()

                            if msg_signal_name == signal_name:
                                # Found matching signal - process it
                                logger.info(f"Found matching signal {signal_name} in stream (msg_id={msg_id})")
                                await self._handle_signal(workflow_id, msg_id, signal_data)

                                # ACK the signal message
                                await self.redis.xack(workflow_stream_key, "signal-workers", msg_id)

                                # Remove from registry since it's been processed
                                await self.redis.delete(registry_key)
                                signal_found = True
                                break

                        if signal_found:
                            break

                    if not signal_found:
                        logger.info(f"Signal {signal_name} not found in stream messages for workflow {workflow_id}")

                except Exception as e:
                    logger.error(f"Error processing registry entry {entry}: {e}", exc_info=True)
                    continue

        except Exception as e:
            logger.error(f"Error processing signal registry: {e}", exc_info=True)

    async def _handle_signal(self, workflow_id: str, msg_id: str, signal_data: Dict):
        """Handle a single signal"""
        signal_name = signal_data.get(b"signal", b"").decode()
        payload = signal_data.get(b"payload", b"{}").decode()

        logger.info(f"Processing signal {signal_name} for workflow {workflow_id}")

        # Find waiting tasks for this signal IN THIS WORKFLOW
        waiting_key = default_sharding.get_signal_key("waiters", workflow_id, signal_name)
        waiting_tasks = await self.redis.smembers(waiting_key)

        if waiting_tasks:
            logger.info(
                f"Signal {signal_name} matched {len(waiting_tasks)} tasks "
                f"in workflow {workflow_id}"
            )

            # Resume each waiting task
            for task_id in waiting_tasks:
                task_id = task_id.decode() if isinstance(task_id, bytes) else task_id

                # Get task metadata to find shard
                metadata = await self.redis.hgetall(default_sharding.get_signal_key("metadata", workflow_id, task_id).encode())
                shard = int(metadata.get(b"shard", b"0").decode())

                # Publish signal received event
                await self.event_store.store_event(
                    event_type=EventType.SIGNAL_RECEIVED,
                    workflow_id=workflow_id,
                    task_id=task_id,
                    level=EventLevel.IMPORTANT,
                    data={
                        'signal_name': signal_name,
                        'payload': json.loads(payload) if payload else {}
                    }
                )

                # Mark signal task as completed
                await self.redis.hset(
                    default_sharding.get_task_key(task_id, workflow_id).encode(),
                    mapping={
                        b"status": b"completed",
                        b"signal_received_at": datetime.utcnow().isoformat().encode(),
                        b"result": json.dumps({
                            "signal_received": True,
                            "signal_name": signal_name,
                            "payload": json.loads(payload)
                        }).encode()
                    }
                )

                # Emit completion event to dependency worker on the correct shard
                await self.redis.xadd(
                    default_sharding.get_stream_key("task:completed", workflow_id).encode(),
                    {
                        b"workflow_id": workflow_id.encode(),
                        b"task_id": task_id.encode(),
                        b"result": json.dumps({
                            "signal_received": True,
                            "signal_name": signal_name,
                            "payload": json.loads(payload)
                        }).encode(),
                        b"timestamp": datetime.utcnow().isoformat().encode()
                    }
                )

                logger.info(f"Signal task {task_id} marked as completed and event emitted to shard {shard}")

            # Clean up waiters
            await self.redis.delete(waiting_key)

            # Clean up metadata
            for task_id in waiting_tasks:
                task_id = task_id.decode() if isinstance(task_id, bytes) else task_id
                await self.redis.delete(default_sharding.get_signal_key("metadata", workflow_id, task_id).encode())

    async def _check_signal_timeouts(self):
        """Check for signal timeouts"""
        try:
            now = time.time()

            # Get all timeout entries that have expired
            expired = await self.redis.zrangebyscore(
                default_sharding.get_global_key("signal:timeouts").encode(),
                0,
                now,
                start=0,
                num=10  # Process 10 at a time
            )

            if not expired:
                return

            for entry in expired:
                entry = entry.decode() if isinstance(entry, bytes) else entry
                # Format: "signal:task:{workflow_id}:{task_id}"
                parts = entry.split(":")
                if len(parts) >= 4:
                    workflow_id = parts[2]
                    task_id = parts[3]

                    logger.warning(f"Signal timeout for task {task_id} in workflow {workflow_id}")

                    # Get task metadata to find shard
                    metadata = await self.redis.hgetall(default_sharding.get_signal_key("metadata", workflow_id, task_id).encode())
                    shard = int(metadata.get(b"shard", b"0").decode())

                    # Publish signal timeout event
                    await self.event_store.store_event(
                        event_type=EventType.SIGNAL_TIMEOUT,
                        workflow_id=workflow_id,
                        task_id=task_id,
                        level=EventLevel.WARNING,
                        data={
                            'error': 'Signal wait timed out'
                        }
                    )

                    # Mark task as failed due to timeout
                    await self.redis.hset(
                        default_sharding.get_task_key(task_id, workflow_id).encode(),
                        mapping={
                            b"status": b"failed",
                            b"error": b"Signal wait timed out",
                            b"failed_at": datetime.utcnow().isoformat().encode()
                        }
                    )

                    # Emit failure event to dependency worker
                    await self.redis.xadd(
                        default_sharding.get_stream_key("task:failed", workflow_id).encode(),
                        {
                            b"workflow_id": workflow_id.encode(),
                            b"task_id": task_id.encode(),
                            b"error": b"Signal wait timed out",
                            b"timestamp": datetime.utcnow().isoformat().encode()
                        }
                    )

                    # Clean up metadata
                    await self.redis.delete(default_sharding.get_signal_key("metadata", workflow_id, task_id).encode())

                # Remove from timeouts
                await self.redis.zrem(default_sharding.get_global_key("signal:timeouts").encode(), entry)

        except Exception as e:
            logger.error(f"Error checking signal timeouts: {e}")

    async def _release_leadership(self):
        """Release leadership when shutting down"""
        if self.is_leader:
            await self.redis.delete(self.leader_key.encode())
            logger.info(f"Worker {self.config.worker_id} released signal leadership")

    async def process_message(self, stream: str, message_id: str, data: Dict) -> bool:
        """Process signal-related messages

        Returns:
            True if message was processed successfully and should be ACK'd
            False if message failed and should not be ACK'd
        """
        # SignalWorker doesn't process stream messages directly
        # It reads directly from signal streams in its leader loop
        return True  # Always ACK since we don't actually process here