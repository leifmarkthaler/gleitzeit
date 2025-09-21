"""
Dedicated signal worker with leader election for Gleitzeit.

Processes workflow signals to resume waiting tasks.
Signals are scoped per-workflow for security and isolation.
"""

import asyncio
import json
import logging
import os
import signal
import socket
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


class SignalWorker:
    """
    Dedicated signal worker with leader election.
    Processes signals sent to workflows and resumes waiting tasks.
    """

    def __init__(self, system_manager, worker_id: Optional[str] = None, priority: int = 0):
        """
        Initialize signal worker.

        Args:
            system_manager: The existing ModularStreamSystemManager instance
            worker_id: Optional worker identifier
            priority: Leadership priority (higher = more likely to be leader)
        """
        self.system_manager = system_manager
        self.redis = system_manager.persistence.redis
        self.worker_id = worker_id or f"signal-{uuid.uuid4().hex[:8]}"
        self.priority = min(max(priority, 0), 10)  # Clamp to 0-10

        # Leadership configuration (same as timer)
        self.is_leader = False
        self.leader_key = "signal:leader"
        self.leader_ttl = 10  # seconds
        self.heartbeat_interval = 3  # seconds
        self.check_interval = 0.5  # Check more frequently than timers

        # Runtime state
        self._running = False
        self._leader_task = None
        self._shutdown_event = asyncio.Event()
        self.leadership_token = None

        # Metrics
        self.signals_processed = 0
        self.tasks_resumed = 0
        self.last_check = 0

        # Consumer group for signal streams
        self.consumer_group = "signal-workers"

        # Register shutdown handlers
        signal.signal(signal.SIGTERM, lambda s, f: self._shutdown_event.set())
        signal.signal(signal.SIGINT, lambda s, f: self._shutdown_event.set())

    async def start(self):
        """Start signal worker and participate in election."""
        if self._running:
            return

        self._running = True
        logger.info(f"Starting signal worker {self.worker_id} with priority {self.priority}")

        try:
            # Register as a signal worker
            await self._register_signal_worker()

            # Ensure consumer groups exist for signal streams
            await self._ensure_consumer_groups()

            # Main loop
            await self._run_loop()

        except Exception as e:
            logger.error(f"Signal worker {self.worker_id} error: {e}")
        finally:
            await self._cleanup()
            self._running = False
            logger.info(f"Signal worker {self.worker_id} stopped")

    async def _register_signal_worker(self):
        """Register this worker as a signal worker."""
        await self.redis.hset(
            "signal:workers",
            self.worker_id,
            json.dumps({
                "started": time.time(),
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "priority": self.priority
            })
        )

    async def _ensure_consumer_groups(self):
        """Ensure consumer groups exist for signal processing."""
        # We'll create consumer groups as we find workflow signal streams
        pass

    async def _run_loop(self):
        """Main loop - election and signal processing."""

        while self._running and not self._shutdown_event.is_set():
            try:
                if not self.is_leader:
                    # Try to become leader (with priority-based delay)
                    await asyncio.sleep(0.05 * (10 - self.priority))
                    await self._attempt_leadership()

                if self.is_leader:
                    # Process signals as leader
                    await self._process_signals_as_leader()
                else:
                    # Standby mode - monitor health
                    await self._standby_mode()

                # Brief pause between iterations
                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Signal worker loop error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _attempt_leadership(self):
        """Try to become the signal leader."""

        # Atomic set-if-not-exists with TTL
        success = await self.redis.set(
            self.leader_key,
            self.worker_id,
            nx=True,  # Only if not exists
            ex=self.leader_ttl
        )

        if success:
            logger.info(f"Signal worker {self.worker_id} became leader")
            self.is_leader = True
            self.leadership_token = uuid.uuid4().hex

            # Store leadership token for fencing
            await self.redis.set(
                f"{self.leader_key}:token",
                self.leadership_token,
                ex=self.leader_ttl
            )

            # Start heartbeat task
            if self._leader_task:
                self._leader_task.cancel()
            self._leader_task = asyncio.create_task(self._leader_heartbeat())

            # Emit leadership event
            await self._emit_leadership_change()

    async def _leader_heartbeat(self):
        """Maintain leadership with heartbeats."""

        while self.is_leader and self._running:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                # Atomic check-and-extend with Lua script
                lua_script = """
                if redis.call('get', KEYS[1]) == ARGV[1] then
                    redis.call('expire', KEYS[1], ARGV[2])
                    redis.call('expire', KEYS[2], ARGV[2])
                    return 1
                else
                    return 0
                end
                """

                renewed = await self.redis.eval(
                    lua_script,
                    2,
                    self.leader_key,
                    f"{self.leader_key}:token",
                    self.worker_id,
                    self.leader_ttl
                )

                if not renewed:
                    logger.warning(f"Signal worker {self.worker_id} lost leadership")
                    self.is_leader = False
                    self.leadership_token = None

                    # Cancel heartbeat task
                    if self._leader_task:
                        self._leader_task.cancel()
                        self._leader_task = None

            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                self.is_leader = False

    async def _process_signals_as_leader(self):
        """Process pending signals for all workflows."""

        # Verify leadership with fencing token
        stored_token = await self.redis.get(f"{self.leader_key}:token")
        if not stored_token or stored_token.decode() != self.leadership_token:
            logger.warning(f"Signal worker {self.worker_id} failed fencing check")
            self.is_leader = False
            self.leadership_token = None
            return

        now = time.time()

        # Skip if we checked too recently
        if now - self.last_check < 0.2:  # Check every 200ms minimum
            return
        self.last_check = now

        try:
            # Scan for workflows with signal streams
            workflow_keys = []
            async for key in self.redis.scan_iter("workflow:signals:*"):
                workflow_keys.append(key)

            if not workflow_keys:
                return

            for workflow_key in workflow_keys:
                await self._process_workflow_signals(workflow_key)

            # Also check for signal timeouts
            await self._check_signal_timeouts()

        except Exception as e:
            logger.error(f"Error processing signals: {e}", exc_info=True)

    async def _process_workflow_signals(self, workflow_key):
        """Process signals for a specific workflow."""

        # Extract workflow_id from key
        workflow_id = workflow_key.decode().split(":")[-1]

        # Ensure consumer group exists for this stream
        try:
            await self.redis.xgroup_create(workflow_key, self.consumer_group, id="0")
        except:
            # Group already exists
            pass

        # Read pending signals from workflow stream
        messages = await self.redis.xreadgroup(
            self.consumer_group,
            self.worker_id,
            {workflow_key: ">"},  # Read new messages only
            count=10,
            block=0  # Non-blocking read
        )

        if not messages:
            return

        # Process each signal
        for stream_key, stream_messages in messages.items():
            for msg_id, signal_data in stream_messages:
                try:
                    # Decode signal data
                    signal_name = signal_data.get(b"signal", b"").decode()
                    payload = signal_data.get(b"payload", b"{}").decode()

                    logger.info(f"Processing signal {signal_name} for workflow {workflow_id}")

                    # Find waiting tasks for this signal IN THIS WORKFLOW
                    waiting_key = f"signal:waiters:{workflow_id}:{signal_name}"
                    waiting_tasks = await self.redis.smembers(waiting_key)

                    if waiting_tasks:
                        logger.info(
                            f"Signal {signal_name} matched {len(waiting_tasks)} tasks "
                            f"in workflow {workflow_id}"
                        )

                        # Resume each waiting task
                        for task_id in waiting_tasks:
                            task_id = task_id.decode() if isinstance(task_id, bytes) else task_id

                            # Emit task:ready event
                            await self.redis.xadd(
                                "gleitzeit:events:stream:task:ready",
                                {
                                    "event_type": "task:ready",
                                    "task_id": task_id,
                                    "workflow_id": workflow_id,
                                    "reason": "signal_received",
                                    "signal_name": signal_name,
                                    "signal_data": payload
                                }
                            )

                            self.tasks_resumed += 1

                        # Clean up waiters
                        await self.redis.delete(waiting_key)

                        # Clean up metadata
                        for task_id in waiting_tasks:
                            task_id = task_id.decode() if isinstance(task_id, bytes) else task_id
                            await self.redis.delete(f"signal:metadata:{workflow_id}:{task_id}")

                    # ACK the signal message
                    await self.redis.xack(workflow_key, self.consumer_group, msg_id)
                    self.signals_processed += 1

                    # Update metrics
                    await self._update_leader_metrics()

                except Exception as e:
                    logger.error(f"Error processing signal {msg_id}: {e}")

    async def _check_signal_timeouts(self):
        """Check for signal timeouts."""

        try:
            now = time.time()

            # Get all timeout entries that have expired
            expired = await self.redis.zrangebyscore(
                "signal:timeouts",
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

                    # Resume task with timeout error
                    await self.redis.xadd(
                        "gleitzeit:events:stream:task:ready",
                        {
                            "event_type": "task:ready",
                            "task_id": task_id,
                            "workflow_id": workflow_id,
                            "reason": "signal_timeout",
                            "error": "Signal wait timed out"
                        }
                    )

                    # Clean up metadata
                    await self.redis.delete(f"signal:metadata:{workflow_id}:{task_id}")

                # Remove from timeouts
                await self.redis.zrem("signal:timeouts", entry)

        except Exception as e:
            logger.error(f"Error checking signal timeouts: {e}")

    async def _standby_mode(self):
        """Standby mode - monitor leader health and system state."""

        # Update our heartbeat as standby
        await self.redis.hset(
            "signal:workers:heartbeat",
            self.worker_id,
            time.time()
        )

        # Check if leader exists and is healthy
        leader = await self.redis.get(self.leader_key)

        if not leader:
            logger.debug(f"Signal worker {self.worker_id} detected no leader")
        else:
            # Monitor signal backlog for alerting
            await self._monitor_signal_backlog()

    async def _monitor_signal_backlog(self):
        """Monitor signal queue depth for alerting."""

        try:
            # Count pending signals across workflows
            total_pending = 0
            async for key in self.redis.scan_iter("workflow:signals:*"):
                length = await self.redis.xlen(key)
                total_pending += length

            # Count waiting tasks
            total_waiting = 0
            async for key in self.redis.scan_iter("signal:waiters:*"):
                count = await self.redis.scard(key)
                total_waiting += count

            # Alert if backlog is high
            if total_pending > 100 or total_waiting > 100:
                logger.warning(
                    f"High signal backlog: {total_pending} pending signals, "
                    f"{total_waiting} waiting tasks"
                )

                # Emit alert event
                await self.redis.xadd(
                    "gleitzeit:events:stream:alerts",
                    {
                        "event_type": "signal:backlog:high",
                        "pending_signals": str(total_pending),
                        "waiting_tasks": str(total_waiting),
                        "worker": self.worker_id,
                        "timestamp": str(time.time())
                    },
                    maxlen=1000  # Keep last 1000 alerts
                )

        except Exception as e:
            logger.error(f"Error monitoring backlog: {e}")

    async def _cleanup(self):
        """Clean shutdown."""

        logger.info(f"Signal worker {self.worker_id} shutting down...")

        # Cancel heartbeat task
        if self._leader_task:
            self._leader_task.cancel()
            try:
                await self._leader_task
            except asyncio.CancelledError:
                pass

        # Remove from workers list
        await self.redis.hdel("signal:workers", self.worker_id)
        await self.redis.hdel("signal:workers:heartbeat", self.worker_id)

        # Release leadership gracefully if we have it
        if self.is_leader:
            current = await self.redis.get(self.leader_key)
            if current and current.decode() == self.worker_id:
                await self.redis.delete(self.leader_key)
                await self.redis.delete(f"{self.leader_key}:token")
                logger.info(f"Signal worker {self.worker_id} released leadership")

                # Emit leadership released event
                await self.redis.xadd(
                    "gleitzeit:events:stream:signal:leadership",
                    {
                        "event_type": "signal:leadership:released",
                        "previous_leader": self.worker_id,
                        "timestamp": str(time.time())
                    }
                )

    async def _emit_leadership_change(self):
        """Emit event when leadership changes."""

        await self.redis.xadd(
            "gleitzeit:events:stream:signal:leadership",
            {
                "event_type": "signal:leadership:acquired",
                "new_leader": self.worker_id,
                "priority": str(self.priority),
                "timestamp": str(time.time())
            }
        )

    async def _update_leader_metrics(self):
        """Update processing metrics for monitoring."""

        # Update cumulative counts
        await self.redis.hset(
            "signal:metrics",
            mapping={
                f"{self.worker_id}:signals_processed": str(self.signals_processed),
                f"{self.worker_id}:tasks_resumed": str(self.tasks_resumed),
                f"{self.worker_id}:last_update": str(time.time())
            }
        )

    async def get_status(self) -> dict:
        """Get current worker status."""

        return {
            "worker_id": self.worker_id,
            "is_leader": self.is_leader,
            "priority": self.priority,
            "signals_processed": self.signals_processed,
            "tasks_resumed": self.tasks_resumed,
            "uptime": time.time() - self.last_check if self.last_check else 0,
            "leadership_token": self.leadership_token[:8] if self.leadership_token else None
        }