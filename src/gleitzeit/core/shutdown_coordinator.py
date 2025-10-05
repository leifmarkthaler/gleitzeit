"""
Stateless Shutdown Coordinator for Gleitzeit

Implements distributed shutdown via Redis pub/sub, maintaining stateless architecture.
All workers/services listen for shutdown signals and self-terminate.
"""

import asyncio
import logging
import json
import psutil
import signal
import sys
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class ShutdownCoordinator:
    """
    Coordinates distributed shutdown via Redis pub/sub.

    Architecture:
    - Uses Redis pub/sub for stateless shutdown signaling
    - Each worker/service subscribes to shutdown channel
    - CLI publishes shutdown command to channel
    - Workers self-terminate on receiving signal
    - No central coordinator required (stateless)
    """

    SHUTDOWN_CHANNEL = "gleitzeit:commands:shutdown"
    HEARTBEAT_CHANNEL = "gleitzeit:commands:heartbeat"

    def __init__(self, redis_client, instance_id: str):
        """
        Initialize shutdown coordinator.

        Args:
            redis_client: Redis client (async)
            instance_id: Unique instance identifier
        """
        self.redis = redis_client
        self.instance_id = instance_id
        self.shutdown_callback: Optional[Callable] = None
        self._subscriber_task: Optional[asyncio.Task] = None
        self._running = False

    async def start_listening(self, shutdown_callback: Callable):
        """
        Start listening for shutdown signals.

        Args:
            shutdown_callback: Async function to call on shutdown signal
        """
        self.shutdown_callback = shutdown_callback
        self._running = True

        # Subscribe to shutdown channel
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.SHUTDOWN_CHANNEL)

        self._subscriber_task = asyncio.create_task(
            self._listen_for_shutdown(pubsub)
        )

        logger.info(f"Instance {self.instance_id} listening for shutdown signals")

    async def _listen_for_shutdown(self, pubsub):
        """Listen for shutdown messages on Redis pub/sub"""
        try:
            while self._running:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0
                )

                if message and message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        command = data.get('command')

                        if command == 'shutdown_all':
                            logger.info(f"Received shutdown_all signal")
                            await self._handle_shutdown(data)
                        elif command == 'shutdown_instance':
                            # Check if this is for us
                            target = data.get('instance_id')
                            if target == self.instance_id or target == 'all':
                                logger.info(f"Received shutdown signal for {self.instance_id}")
                                await self._handle_shutdown(data)

                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid shutdown message: {e}")

        except asyncio.CancelledError:
            logger.info("Shutdown listener cancelled")
        except Exception as e:
            logger.error(f"Error in shutdown listener: {e}")
        finally:
            await pubsub.unsubscribe(self.SHUTDOWN_CHANNEL)
            await pubsub.close()

    async def _handle_shutdown(self, data: Dict[str, Any]):
        """
        Handle shutdown signal.

        Args:
            data: Shutdown command data
        """
        grace_period = data.get('grace_period', 10)
        force = data.get('force', False)

        logger.info(f"Initiating shutdown (grace_period={grace_period}s, force={force})")

        if self.shutdown_callback:
            try:
                # Call shutdown callback with timeout
                if force:
                    # Immediate shutdown
                    await asyncio.wait_for(
                        self.shutdown_callback(),
                        timeout=1.0
                    )
                else:
                    # Graceful shutdown
                    await asyncio.wait_for(
                        self.shutdown_callback(),
                        timeout=grace_period
                    )
            except asyncio.TimeoutError:
                logger.warning(f"Shutdown callback timed out after {grace_period}s")
            except Exception as e:
                logger.error(f"Error in shutdown callback: {e}")

        # Stop listening
        self._running = False

    async def stop_listening(self):
        """Stop listening for shutdown signals"""
        self._running = False
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped listening for shutdown signals")

    @classmethod
    async def broadcast_shutdown(
        cls,
        redis_client,
        instance_id: Optional[str] = None,
        grace_period: int = 10,
        force: bool = False,
        wait_for_acks: bool = True,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Broadcast shutdown signal via Redis pub/sub.

        Args:
            redis_client: Redis client (async)
            instance_id: Target instance ID (None for all)
            grace_period: Grace period for shutdown (seconds)
            force: Force immediate shutdown
            wait_for_acks: Wait for acknowledgments
            timeout: Max wait time for acks

        Returns:
            dict with shutdown status
        """
        command = {
            'command': 'shutdown_instance' if instance_id else 'shutdown_all',
            'instance_id': instance_id or 'all',
            'grace_period': grace_period,
            'force': force,
            'timestamp': datetime.utcnow().isoformat(),
            'request_ack': wait_for_acks
        }

        # Publish shutdown command
        receivers = await redis_client.publish(
            cls.SHUTDOWN_CHANNEL,
            json.dumps(command)
        )

        logger.info(f"Broadcast shutdown signal to {receivers} subscribers")

        result = {
            'command': command['command'],
            'receivers': receivers,
            'timestamp': command['timestamp'],
            'acknowledged': []
        }

        # Wait for acknowledgments if requested
        if wait_for_acks and receivers > 0:
            ack_channel = f"{cls.SHUTDOWN_CHANNEL}:acks"
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(ack_channel)

            start_time = asyncio.get_event_loop().time()
            acknowledged = set()

            try:
                while len(acknowledged) < receivers:
                    elapsed = asyncio.get_event_loop().time() - start_time
                    remaining = timeout - elapsed

                    if remaining <= 0:
                        logger.warning(f"Timeout waiting for acks, got {len(acknowledged)}/{receivers}")
                        break

                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=min(remaining, 1.0)
                    )

                    if message and message['type'] == 'message':
                        try:
                            ack_data = json.loads(message['data'])
                            ack_instance = ack_data.get('instance_id')
                            if ack_instance:
                                acknowledged.add(ack_instance)
                                logger.info(f"Received shutdown ack from {ack_instance}")
                        except json.JSONDecodeError:
                            pass

            except asyncio.CancelledError:
                pass
            finally:
                await pubsub.unsubscribe(ack_channel)
                await pubsub.close()

            result['acknowledged'] = list(acknowledged)
            result['ack_count'] = len(acknowledged)

        return result


class RestartCoordinator:
    """
    Coordinates safe restart of services.

    Combines stateless shutdown with process cleanup.
    """

    @staticmethod
    async def restart_all(
        redis_client,
        api_port: int = 8000,
        ui_port: int = 8004,
        force: bool = False,
        grace_period: int = 10
    ) -> Dict[str, Any]:
        """
        Safely restart all Gleitzeit services.

        Steps:
        1. Broadcast shutdown signal (stateless)
        2. Wait for graceful shutdown
        3. Force kill remaining processes
        4. Clean Redis keys
        5. Verify cleanup

        Args:
            redis_client: Redis client
            api_port: API port to check
            ui_port: UI port to check
            force: Force immediate shutdown
            grace_period: Grace period for shutdown

        Returns:
            dict with restart status
        """
        result = {
            'shutdown': {},
            'cleanup': {},
            'validation': {},
            'success': False
        }

        logger.info("=== Starting Restart Sequence ===")

        # Step 1: Broadcast shutdown via Redis (stateless)
        logger.info("Step 1: Broadcasting shutdown signal...")
        shutdown_result = await ShutdownCoordinator.broadcast_shutdown(
            redis_client,
            instance_id=None,  # All instances
            grace_period=grace_period,
            force=force,
            wait_for_acks=True,
            timeout=grace_period + 5
        )
        result['shutdown'] = shutdown_result
        logger.info(f"  Shutdown broadcast to {shutdown_result['receivers']} subscribers")
        logger.info(f"  Acknowledged by {len(shutdown_result['acknowledged'])} instances")

        # Step 2: Wait for graceful shutdown
        if not force:
            logger.info(f"Step 2: Waiting {grace_period}s for graceful shutdown...")
            await asyncio.sleep(grace_period)
        else:
            logger.info("Step 2: Force mode, minimal wait...")
            await asyncio.sleep(2)

        # Step 3: Force kill remaining processes
        logger.info("Step 3: Cleaning up remaining processes...")
        cleanup_stats = await RestartCoordinator._force_cleanup_processes()
        result['cleanup'] = cleanup_stats
        logger.info(f"  Killed {cleanup_stats['processes_killed']} processes")

        # Step 4: Clean Redis keys
        logger.info("Step 4: Cleaning Redis keys...")
        redis_cleanup = await RestartCoordinator._clean_redis_keys(redis_client)
        result['cleanup']['redis'] = redis_cleanup
        logger.info(f"  Deleted {redis_cleanup['keys_deleted']} Redis keys")

        # Step 5: Wait for port release
        logger.info("Step 5: Waiting for ports to be released...")
        await asyncio.sleep(3)

        # Step 6: Validate cleanup
        logger.info("Step 6: Validating cleanup...")
        validation = await RestartCoordinator._validate_cleanup(api_port, ui_port)
        result['validation'] = validation

        if validation['success']:
            logger.info("✅ Restart cleanup complete")
            result['success'] = True
        else:
            logger.warning(f"⚠️  Restart cleanup incomplete: {validation['issues']}")
            result['success'] = False

        return result

    @staticmethod
    async def _force_cleanup_processes() -> Dict[str, Any]:
        """Force kill remaining Gleitzeit processes"""
        stats = {
            'processes_found': 0,
            'processes_killed': 0,
            'errors': []
        }

        killed_pids = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if not cmdline:
                    continue

                cmdline_str = ' '.join(cmdline)

                # Check if it's a Gleitzeit process
                if 'python' in cmdline_str and 'gleitzeit' in cmdline_str:
                    stats['processes_found'] += 1
                    logger.info(f"  Killing process PID {proc.pid}")
                    proc.kill()
                    killed_pids.append(proc.pid)
                    stats['processes_killed'] += 1

            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                stats['errors'].append(f"PID {proc.pid}: {e}")
            except Exception as e:
                stats['errors'].append(f"Unknown error: {e}")

        # Wait for processes to die
        if killed_pids:
            gone, alive = psutil.wait_procs(
                [psutil.Process(pid) for pid in killed_pids if psutil.pid_exists(pid)],
                timeout=5
            )
            stats['processes_alive'] = len(alive)

        return stats

    @staticmethod
    async def _clean_redis_keys(redis_client) -> Dict[str, Any]:
        """Clean Gleitzeit keys from Redis"""
        stats = {
            'keys_deleted': 0,
            'patterns': []
        }

        patterns = [
            "service:registry:*",
            "{shard:0}:worker:metrics:*",
            "{shard:0}:worker:registry:*",
            "handler:registration:*",
            "worker:config:*"
        ]

        for pattern in patterns:
            count = 0
            cursor = b"0"
            keys_batch = []

            while True:
                cursor, keys = await redis_client.scan(
                    cursor,
                    match=pattern,
                    count=100
                )
                keys_batch.extend(keys)

                if cursor == b"0":
                    break

            if keys_batch:
                await redis_client.delete(*keys_batch)
                count = len(keys_batch)
                stats['keys_deleted'] += count
                logger.info(f"  Deleted {count} keys matching {pattern}")

            stats['patterns'].append({
                'pattern': pattern,
                'count': count
            })

        return stats

    @staticmethod
    async def _validate_cleanup(api_port: int, ui_port: int) -> Dict[str, Any]:
        """Validate that cleanup was successful"""
        validation = {
            'success': True,
            'issues': []
        }

        # Check for running processes
        running_procs = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info.get('cmdline', []))
                if 'gleitzeit' in cmdline and 'python' in cmdline:
                    running_procs.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if running_procs:
            validation['success'] = False
            validation['issues'].append(
                f"Found {len(running_procs)} running processes: {running_procs}"
            )

        # Check if ports are free
        for port in [api_port, ui_port]:
            for conn in psutil.net_connections():
                try:
                    if conn.laddr.port == port and conn.status == 'LISTEN':
                        validation['success'] = False
                        validation['issues'].append(
                            f"Port {port} still in use by PID {conn.pid}"
                        )
                except AttributeError:
                    pass

        return validation
