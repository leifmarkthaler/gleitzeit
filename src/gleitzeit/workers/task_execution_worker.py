"""
Task Execution Worker with Handler Architecture

Simplified task execution using handler system.
Maintains clustering and sharding while enabling type-specific scaling.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

from .base import BaseWorker, WorkerConfig
from ..core.sharding import default_sharding
from ..core.models import Task, TaskResult, TaskStatus
from ..core.cache import get_workflow_cache
from ..core.config_loader import get_config
# Retry is now handled by RetryWorker - no local retry imports needed
from ..core.events import EventType
from ..core.event_store import EventStore, EventLevel
from ..handlers import handler_loader, HandlerRegistry

logger = logging.getLogger(__name__)


class TaskExecutionWorker(BaseWorker):
    """
    Task execution worker using handler architecture.

    Features:
    - Handler-based execution (not providers)
    - Type-specific worker specialization
    - Maintains sharding and clustering
    - Direct execution without abstraction layers
    """

    def __init__(self, config: WorkerConfig):
        super().__init__(config)

        # Get enabled task types from config
        # Use the proper dataclass attribute
        self.enabled_types = config.enabled_task_types if hasattr(config, 'enabled_task_types') else ['all']

        # Load signal registry TTL from global config once (not on every signal emission)
        global_config = get_config()
        self.signal_registry_ttl = global_config.get('handlers', {}).get('signal', {}).get('config', {}).get('signal_registry_ttl', 3600)

        # Initialize handlers
        self.handlers = {}
        self.protocol_to_handler = {}
        self._init_handlers()

        # Workflow cache with LRU eviction
        cache_size = config.__dict__.get('workflow_cache_size', 1000)
        cache_ttl = config.__dict__.get('workflow_cache_ttl', 3600)  # 1 hour default
        self.workflow_cache = get_workflow_cache(max_size=cache_size, ttl=cache_ttl)

    def _init_handlers(self):
        """Initialize handlers based on enabled task types"""
        # Get all handler capabilities
        capabilities = handler_loader.get_all_capabilities()
        registry = handler_loader.get_registry()

        # Build type to handler mapping
        type_to_handler = {}
        for protocol, caps in capabilities.items():
            handler_class = registry.get_handler(protocol)
            if handler_class:
                # Map task types to handler
                for task_type in caps.get('task_types', []):
                    type_to_handler[task_type] = (protocol, handler_class)
                # Map protocol to handler
                self.protocol_to_handler[protocol] = handler_class

        # Get handler configs - with backward compatibility
        handler_configs = {}
        if hasattr(self.config, 'handler_configs'):
            # New WorkerConfig with handler_configs attribute
            handler_configs = self.config.handler_configs
        elif hasattr(self.config, 'get_handler_config'):
            # Has the method but need to extract all configs
            handler_configs = getattr(self.config, 'handler_configs', {})
        elif hasattr(self.config, '__dict__') and 'handler_configs' in self.config.__dict__:
            # Old style - handler_configs in __dict__
            handler_configs = self.config.__dict__.get('handler_configs', {})

        # Log what we found
        if handler_configs:
            logger.info(f"Found handler configurations for: {list(handler_configs.keys())}")
        else:
            logger.info("No handler configurations found, using defaults")

        # Initialize handlers based on enabled types
        if 'all' in self.enabled_types:
            # Load all handlers
            for protocol, handler_class in self.protocol_to_handler.items():
                # Get handler-specific config if available
                handler_config = handler_configs.get(protocol, {})

                # Add worker metadata to handler config
                if hasattr(self.config, 'worker_id'):
                    handler_config['worker_id'] = self.config.worker_id

                handler_instance = handler_class(config=handler_config)
                self.handlers[protocol] = handler_instance
                logger.info(f"Loaded handler for protocol {protocol}: {handler_class.__name__} (ID: {handler_instance.handler_id[:8]})")
                if handler_config:
                    logger.info(f"  Handler config keys: {list(handler_config.keys())}")
        else:
            # Load only specified types
            loaded_protocols = set()
            for task_type in self.enabled_types:
                if task_type in type_to_handler:
                    protocol, handler_class = type_to_handler[task_type]
                    if protocol not in loaded_protocols:
                        handler_config = handler_configs.get(protocol, {})

                        # Add worker metadata to handler config
                        if hasattr(self.config, 'worker_id'):
                            handler_config['worker_id'] = self.config.worker_id

                        handler_instance = handler_class(config=handler_config)
                        self.handlers[protocol] = handler_instance
                        loaded_protocols.add(protocol)
                        logger.info(f"Loaded handler for type {task_type} -> protocol {protocol} (ID: {handler_instance.handler_id[:8]})")
                        if handler_config:
                            logger.info(f"  Handler config keys: {list(handler_config.keys())}")

        logger.info(f"Worker initialized with {len(self.handlers)} handlers: {list(self.handlers.keys())}")

    async def on_initialize(self):
        """Initialize worker resources"""
        # Initialize event store
        self.event_store = EventStore(self.redis, config={
            'max_events_per_workflow': 10000,
            'event_ttl_seconds': 86400 * 30  # 30 days
        })

        logger.info(f"TaskExecutionWorker initialized with enabled types: {self.enabled_types}")
        logger.info(f"Available handlers: {list(self.handlers.keys())}")
        logger.info(f"Workflow cache configured: size={self.workflow_cache.max_size}, ttl={self.workflow_cache.default_ttl}s")

        # Initialize handlers that support async initialization
        for protocol, handler in self.handlers.items():
            if hasattr(handler, 'async_init'):
                try:
                    await handler.async_init()
                    logger.info(f"Async initialization completed for handler {protocol}")
                except Exception as e:
                    logger.warning(f"Failed to async initialize handler {protocol}: {e}")

        # Register handlers in Redis
        await self._register_handlers()

    async def _register_handlers(self):
        """Register handler metadata in Redis"""
        import socket

        for protocol, handler in self.handlers.items():
            handler_info = handler.get_handler_info()
            handler_info['worker_id'] = self.config.worker_id
            handler_info['worker_instance_url'] = socket.gethostname()

            # Add provider URL if available
            if hasattr(handler, 'base_url'):
                handler_info['provider_url'] = handler.base_url

            # Store handler metadata
            handler_key = f"handler:registry:{handler.handler_id}"
            await self.redis.hset(
                handler_key.encode(),
                mapping={k.encode(): json.dumps(v).encode() if isinstance(v, dict) else str(v).encode()
                         for k, v in handler_info.items()}
            )

            # Set expiry to keep registry clean (24 hours)
            await self.redis.expire(handler_key.encode(), 86400)

            logger.info(f"Registered handler {handler.handler_id[:8]} for protocol {protocol}")

    def get_base_streams(self) -> List[str]:
        """Subscribe to sharded task:ready streams"""
        return ["task:ready", "task:retry"]

    async def process_message(self, stream: str, message_id: str, data: Dict) -> bool:
        """Process a task execution request

        Returns:
            True if task was processed successfully
            False if task failed and should be retried
        """
        workflow_id = data.get('workflow_id')
        task_id = data.get('task_id')

        if not workflow_id or not task_id:
            logger.error(f"Missing workflow_id or task_id in message {message_id}")
            # This is a malformed message, don't retry
            return True  # ACK it to remove from stream

        logger.info(f"Processing task {task_id} from workflow {workflow_id}")

        # Log INFO: Task execution started
        await self.log_worker_info(
            "task_execution_started",
            f"Starting execution of task {task_id}",
            workflow_id=workflow_id,
            task_id=task_id,
            stream=stream
        )

        try:
            # Check if task has been cancelled before starting execution
            state_key = default_sharding.get_task_key(task_id, workflow_id)
            task_state = await self.redis.hgetall(state_key.encode())

            if task_state:
                current_status = task_state.get(b"status", b"").decode()
                if current_status == "cancelled":
                    logger.info(f"Task {task_id} was cancelled, skipping execution")
                    # Emit cancellation confirmation event
                    await self.redis.xadd(
                        default_sharding.get_stream_key("task:cancelled", workflow_id).encode(),
                        {
                            b"task_id": task_id.encode(),
                            b"workflow_id": workflow_id.encode(),
                            b"reason": b"cancelled_before_execution",
                            b"timestamp": datetime.utcnow().isoformat().encode()
                        }
                    )
                    return True  # ACK the message, task won't be retried

            # Get task data
            task_data = data.get('task')
            if isinstance(task_data, str):
                task_data = json.loads(task_data)

            # Create Task object from data
            task = Task(**task_data)

            # Check if we handle this protocol
            if task.protocol not in self.handlers:
                # Check if we handle the task type (for backward compatibility)
                task_type = task_data.get('type') or task_data.get('task_type')
                can_handle = False

                # Check if any of our handlers support this task type
                for protocol, handler in self.handlers.items():
                    caps = handler.get_capabilities()
                    if task_type in caps.get('task_types', []):
                        can_handle = True
                        task.protocol = protocol  # Update protocol
                        break

                if not can_handle:
                    # No handler for this protocol - this is a configuration issue
                    logger.error(
                        f"No handler for protocol '{task.protocol}' in task {task_id}. "
                        f"This worker has handlers for: {list(self.handlers.keys())}"
                    )

                    # Mark task as failed due to no handler
                    await self.redis.hset(
                        default_sharding.get_task_key(task_id, workflow_id).encode(),
                        mapping={
                            b"status": b"failed",
                            b"error": f"No handler available for protocol {task.protocol}".encode(),
                            b"failed_at": datetime.utcnow().isoformat().encode(),
                            b"failed_by": self.config.worker_id.encode(),
                            b"workflow_id": workflow_id.encode()
                        }
                    )

                    # Emit to task:failed stream
                    await self.redis.xadd(
                        default_sharding.get_stream_key("task:failed", workflow_id).encode(),
                        {
                            b"workflow_id": workflow_id.encode(),
                            b"task_id": task_id.encode(),
                            b"error": f"No handler for protocol {task.protocol}".encode(),
                            b"worker_id": self.config.worker_id.encode(),
                            b"timestamp": datetime.utcnow().isoformat().encode()
                        }
                    )

                    # Don't retry - this is a permanent failure (unretryable error per CLAUDE.md)
                    return True  # ACK to prevent retry

            # Get handler
            handler = self.handlers[task.protocol]

            # Add resolved inputs if available
            if 'resolved_inputs' in data:
                task.params['inputs'] = data['resolved_inputs']

            # Generate execution ID for tracking
            import uuid
            execution_id = f"exec_{uuid.uuid4().hex[:12]}"

            # Store execution metadata
            await self.redis.hset(
                default_sharding.get_task_key(task_id, workflow_id).encode(),
                mapping={
                    b"execution_id": execution_id.encode(),
                    b"executed_at": datetime.utcnow().isoformat().encode(),
                    b"handler_id": handler.handler_id.encode(),
                    b"worker_id": self.config.worker_id.encode(),
                    b"workflow_id": workflow_id.encode()
                }
            )

            # Emit task started event
            await self.event_store.store_event(
                event_type=EventType.TASK_STARTED,
                workflow_id=workflow_id,
                task_id=task_id,
                level=EventLevel.CRITICAL,
                data={
                    'protocol': task.protocol,
                    'handler_id': handler.handler_id,
                    'worker_id': self.config.worker_id,
                    'execution_id': execution_id,
                    'has_dependencies': bool(task.dependencies)
                }
            )

            # Execute task
            logger.info(f"Executing task {task_id} with handler {handler.__class__.__name__}")

            # Log DEBUG: Handler selected
            await self.log_worker_debug(
                "handler_selected",
                f"Using handler {handler.__class__.__name__}",
                workflow_id=workflow_id,
                task_id=task_id,
                handler_type=handler.__class__.__name__,
                protocol=task.protocol
            )

            start_time = datetime.utcnow()
            result = await handler.execute(task)
            duration = (datetime.utcnow() - start_time).total_seconds()

            # WARNING: Slow execution
            if duration > 30:
                await self.log_worker_warning(
                    "slow_task_execution",
                    f"Task {task_id} took {duration:.2f}s to execute",
                    workflow_id=workflow_id,
                    task_id=task_id,
                    duration=duration,
                    handler_type=handler.__class__.__name__
                )

            # Handle result based on status
            success = await self.handle_execution_result(
                task_id, workflow_id, task.protocol, result
            )

            return success

            # All paths should have returned by now
            return True

        except Exception as e:
            logger.error(f"Task execution failed for {task_id}: {e}", exc_info=True)
            await self.handle_task_failure(task_id, workflow_id, str(e))
            # Let the base worker handle retry logic
            return False  # Don't ACK, allow retry

    async def handle_execution_result(
        self,
        task_id: str,
        workflow_id: str,
        protocol: str,
        result: TaskResult
    ) -> bool:
        """Handle different result statuses from handlers

        Returns:
            True if task processing succeeded (even if task itself failed)
            False if we should retry the task
        """

        if result.status == TaskStatus.COMPLETED:
            # Log INFO: Task completed successfully
            await self.log_worker_info(
                "task_execution_completed",
                f"Task {task_id} completed successfully",
                workflow_id=workflow_id,
                task_id=task_id,
                status=result.status,
                duration=result.duration_seconds if hasattr(result, 'duration_seconds') else None
            )

            # Normal completion - pass protocol for handler tracking
            await self.emit_task_completed(task_id, workflow_id, result, protocol)
            return True

        elif result.status == TaskStatus.FAILED:
            # Task failed - but we successfully processed the failure
            # Pass error_type from metadata if available
            error_type = result.metadata.get('error_type', 'Exception') if result.metadata else 'Exception'
            await self.handle_task_failure(
                task_id, workflow_id,
                result.error or "Task execution failed",
                error_type=error_type
            )
            return True  # We handled the failure, don't retry the message

        elif result.status == TaskStatus.SCHEDULED:
            # Timer task - needs TimerWorker to handle
            await self.emit_task_scheduled(task_id, workflow_id, result)
            return True

        elif result.status == TaskStatus.WAITING:
            # Signal task - needs SignalWorker to handle
            await self.emit_task_waiting(task_id, workflow_id, result)
            return True

        else:
            logger.warning(f"Unknown result status: {result.status} for task {task_id}")
            return False  # Unknown status, retry

    async def emit_task_completed(
        self,
        task_id: str,
        workflow_id: str,
        result: TaskResult,
        protocol: str = None
    ):
        """Emit task completion event with handler tracking"""
        shard = default_sharding.get_shard(workflow_id)

        # Emit event for replay
        await self.event_store.store_event(
            event_type=EventType.TASK_COMPLETED,
            workflow_id=workflow_id,
            task_id=task_id,
            level=EventLevel.CRITICAL,
            data={
                'result': result.result if result.result else {},
                'handler_id': result.handler_id if hasattr(result, 'handler_id') else None,
                'protocol': protocol,
                'worker_id': self.config.worker_id
            }
        )

        # Check for workflow submission (for async workflows that complete immediately)
        if result.metadata and result.metadata.get('submit_workflow'):
            await self._submit_child_workflow(
                task_id=task_id,
                workflow_id=workflow_id,
                metadata=result.metadata
            )

        # Check if this is a signal send/broadcast task
        if result.metadata and result.metadata.get('emit_signal'):
            signal_action = result.metadata.get('signal_action')
            if signal_action == 'send':
                # Send to specific workflows
                target_workflows = result.metadata.get('target_workflows', [workflow_id])
                for target_wf in target_workflows:
                    await self._emit_signal(
                        sender_workflow_id=workflow_id,
                        signal_name=result.metadata.get('signal_name'),
                        payload=result.metadata.get('payload', {}),
                        target_workflow=target_wf
                    )
            elif signal_action == 'broadcast':
                # Broadcast system-wide (no specific workflow)
                await self._emit_signal(
                    sender_workflow_id=workflow_id,
                    signal_name=result.metadata.get('signal_name'),
                    payload=result.metadata.get('payload', {}),
                    target_workflow=None  # None means broadcast
                )

        # Update task status in Redis
        await self.redis.hset(
            default_sharding.get_task_key(task_id, workflow_id).encode(),
            mapping={
                b"status": TaskStatus.COMPLETED.encode(),
                b"result": json.dumps(result.result).encode() if result.result else b"{}",
                b"completed_at": datetime.utcnow().isoformat().encode(),
                b"handler_id": result.handler_id.encode() if hasattr(result, 'handler_id') and result.handler_id else b"",
                b"worker_id": self.config.worker_id.encode(),
                b"workflow_id": workflow_id.encode()
            }
        )

        # Build stream message with handler tracking
        message = {
            b"workflow_id": workflow_id.encode(),
            b"task_id": task_id.encode(),
            b"result": json.dumps(result.result).encode() if result.result else b"{}",
            b"timestamp": datetime.utcnow().isoformat().encode(),
            # Handler tracking (new fields)
            b"worker_id": self.config.worker_id.encode(),
        }

        # Add handler info if available
        if protocol and protocol in self.handlers:
            handler = self.handlers[protocol]
            message[b"handler_id"] = handler.handler_id.encode()
            message[b"handler_protocol"] = protocol.encode()

            # Add provider URL if handler has it (e.g., Ollama endpoint)
            if hasattr(handler, 'base_url'):
                message[b"provider_url"] = handler.base_url.encode()

            # Add worker instance URL (where this worker is running)
            import socket
            hostname = socket.gethostname()
            message[b"worker_instance_url"] = hostname.encode()

        # Store task-to-handler mapping for quick lookup
        if protocol and protocol in self.handlers:
            handler = self.handlers[protocol]
            await self.redis.set(
                f"task:handler:{task_id}".encode(),
                handler.handler_id.encode(),
                ex=86400  # 24 hour TTL
            )

        # Emit to task:completed stream with enriched data
        await self.redis.xadd(
            default_sharding.get_stream_key("task:completed", workflow_id).encode(),
            message
        )

        logger.info(f"Task {task_id} completed successfully by handler {message.get(b'handler_id', b'unknown').decode()}")

    async def emit_task_scheduled(
        self,
        task_id: str,
        workflow_id: str,
        result: TaskResult
    ):
        """Register timer - simple metadata only, no buckets/registry"""
        wake_time = result.metadata.get('wake_time', 0)
        shard = default_sharding.get_shard(workflow_id)
        current_time = time.time()
        duration_seconds = wake_time - current_time

        # Update task status
        await self.redis.hset(
            default_sharding.get_task_key(task_id, workflow_id).encode(),
            mapping={
                b"status": TaskStatus.SCHEDULED.encode(),
                b"wake_time": str(wake_time).encode(),
                b"timer_type": result.metadata.get('timer_type', 'sleep').encode(),
                b"scheduled_at": datetime.utcnow().isoformat().encode()
            }
        )

        # Store timer metadata (NO TTL, NO bucket, NO registry)
        metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
        await self.redis.hset(
            metadata_key.encode(),
            mapping={
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"shard": str(shard).encode(),
                b"wake_time": str(wake_time).encode(),
                b"timer_type": result.metadata.get('timer_type', 'sleep').encode(),
                b"created_at": datetime.utcnow().isoformat().encode()
            }
        )

        # Add to pending set for reconciliation
        pending_key = default_sharding.get_timer_key("pending", workflow_id)
        await self.redis.sadd(pending_key, task_id)

        # Publish timer created event (full audit trail)
        await self.event_store.store_event(
            event_type=EventType.TIMER_CREATED,
            workflow_id=workflow_id,
            task_id=task_id,
            level=EventLevel.INFO,
            data={
                'timer_type': result.metadata.get('timer_type', 'sleep'),
                'wake_time': wake_time,
                'duration_seconds': duration_seconds
            }
        )

        logger.info(
            f"Timer registered for task {task_id}: "
            f"wake_time={wake_time}, duration={duration_seconds:.1f}s"
        )

    async def emit_task_waiting(
        self,
        task_id: str,
        workflow_id: str,
        result: TaskResult
    ):
        """Emit task waiting event for SignalWorker or WorkflowMonitor"""
        # Check for workflow submission (for sync workflows that wait)
        if result.metadata and result.metadata.get('submit_workflow'):
            await self._submit_child_workflow(
                task_id=task_id,
                workflow_id=workflow_id,
                metadata=result.metadata
            )

        shard = default_sharding.get_shard(workflow_id)
        signal_name = result.metadata.get('signal_name', '')

        # Update task status
        await self.redis.hset(
            default_sharding.get_task_key(task_id, workflow_id).encode(),
            mapping={
                b"status": TaskStatus.WAITING.encode(),
                b"signal_type": result.metadata.get('signal_type', 'wait').encode(),
                b"signal_name": signal_name.encode(),
                b"waiting_since": datetime.utcnow().isoformat().encode()
            }
        )

        # Register task in waiters SET for SignalWorker to find
        # This is the key data structure SignalWorker uses to match signals to waiting tasks
        waiting_key = default_sharding.get_signal_key("waiters", workflow_id, signal_name)
        await self.redis.sadd(waiting_key, task_id)

        # Store metadata for SignalWorker (includes shard info)
        metadata_key = default_sharding.get_signal_key("metadata", workflow_id, task_id)
        await self.redis.hset(
            metadata_key.encode(),
            mapping={
                b"shard": str(shard).encode(),
                b"signal_name": signal_name.encode(),
                b"signal_type": result.metadata.get('signal_type', 'wait').encode(),
                b"waiting_since": datetime.utcnow().isoformat().encode(),
                b"timeout": str(result.metadata.get('timeout', 0)).encode()
            }
        )

        # Publish task waiting event
        await self.event_store.store_event(
            event_type=EventType.TASK_WAITING,
            workflow_id=workflow_id,
            task_id=task_id,
            level=EventLevel.INFO,
            data={
                'signal_name': signal_name,
                'signal_type': result.metadata.get('signal_type', 'wait'),
                'timeout': result.metadata.get('timeout')
            }
        )

        # Handle timeout if specified
        timeout = result.metadata.get('timeout')
        if timeout:
            timeout_time = time.time() + timeout
            await self.redis.zadd(
                default_sharding.get_global_key("signal:timeouts").encode(),
                {f"{workflow_id}:{task_id}".encode(): timeout_time}
            )

        # Emit to signal:waiting stream for observability
        await self.redis.xadd(
            default_sharding.get_stream_key("signal:waiting", workflow_id).encode(),
            {
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"signal_name": signal_name.encode(),
                b"signal_type": result.metadata.get('signal_type', 'wait').encode(),
                b"metadata": json.dumps(result.metadata).encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        logger.info(f"Task {task_id} waiting for signal '{signal_name}' in workflow {workflow_id}")

    async def _emit_signal(
        self,
        sender_workflow_id: str,
        signal_name: str,
        payload: Dict[str, Any],
        target_workflow: Optional[str] = None
    ):
        """Emit a signal to the signal processing system"""
        # Write signal directly to the sharded workflow signals stream
        # This matches what SignalWorker expects (replaces StatelessSignalManager)

        # Default to sender workflow if no target specified
        if target_workflow is None:
            target_workflow = sender_workflow_id

        # Get the workflow signals stream key (sharded)
        # SignalWorker scans for {shard:N}:workflow:signals:*
        workflow_signals_key = default_sharding.get_workflow_key("signals", target_workflow)

        # Add signal to the workflow's signal stream
        signal_id = await self.redis.xadd(
            workflow_signals_key.encode(),
            {
                b"signal": signal_name.encode(),
                b"payload": json.dumps(payload).encode(),
                b"sender_workflow": sender_workflow_id.encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        # CRITICAL: Also register in global signal registry for SignalWorker
        # This eliminates race conditions - signals are discoverable immediately
        # Use individual key with TTL for automatic cleanup (prevents memory leak)
        registry_entry_key = f"signal:registry:{target_workflow}:{signal_name}"

        # Use TTL loaded from config during initialization
        await self.redis.setex(registry_entry_key, self.signal_registry_ttl, "1")

        # Publish signal sent event
        await self.event_store.store_event(
            event_type=EventType.SIGNAL_SENT,
            workflow_id=sender_workflow_id,
            level=EventLevel.IMPORTANT,
            data={
                'signal_name': signal_name,
                'target_workflow': target_workflow,
                'payload': payload
            }
        )

        if target_workflow == sender_workflow_id:
            logger.info(
                f"Emitted signal '{signal_name}' (ID: {signal_id.decode()}) "
                f"within workflow {sender_workflow_id}, registered in global registry"
            )
        else:
            logger.info(
                f"Emitted signal '{signal_name}' (ID: {signal_id.decode()}) "
                f"from workflow {sender_workflow_id} to {target_workflow}, registered in global registry"
            )

    async def handle_task_failure(
        self,
        task_id: str,
        workflow_id: str,
        error: str,
        error_type: str = None
    ):
        """Handle task execution failure - emit to retry worker for centralized handling"""
        logger.error(f"Task {task_id} failed: {error}")

        # Use provided error_type or extract from error string if possible
        if not error_type:
            error_type = "Exception"  # Default
            if ":" in error:
                # Try to extract error type from format "ErrorType: message"
                potential_type = error.split(":")[0].strip()
                if len(potential_type) < 50:  # Reasonable length for error type
                    error_type = potential_type

        # Log error to Redis via StatelessLogService
        from ..core.stateless_log_service import StatelessLogService
        try:
            await StatelessLogService.log_error(
                redis=self.redis,
                message=f"Task {task_id} execution failed: {error}",
                workflow_id=workflow_id,
                task_id=task_id,
                component="TaskExecutionWorker",
                error_type=error_type,
                stack_trace=None,  # Would need to pass this from the except block
                metadata={
                    'worker_id': self.config.worker_id,
                    'error': error
                }
            )
        except Exception as log_err:
            logger.warning(f"Failed to log error to Redis: {log_err}")

        # Emit task failed event
        await self.event_store.store_event(
            event_type=EventType.TASK_FAILED,
            workflow_id=workflow_id,
            task_id=task_id,
            level=EventLevel.CRITICAL,
            data={
                'error': error,
                'worker_id': self.config.worker_id
            }
        )

        # Emit to retry worker stream for centralized retry handling
        # RetryWorker is now the ONLY retry mechanism
        retry_stream = default_sharding.get_stream_key("task:failed", workflow_id).encode()
        await self.redis.xadd(
            retry_stream,
            {
                b"task_id": task_id.encode(),
                b"workflow_id": workflow_id.encode(),
                b"error": error.encode(),
                b"error_type": error_type.encode(),
                b"worker_id": self.config.worker_id.encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        logger.info(f"Emitted task failure to RetryWorker for {task_id}")

        # IMPORTANT: If RetryWorker is not running, tasks will fail permanently
        # This is intentional - RetryWorker is now a required component

    async def get_cached_workflow(self, workflow_id: str) -> Optional[Dict]:
        """Get workflow from cache or Redis"""
        if workflow_id in self.workflow_cache:
            return self.workflow_cache[workflow_id]

        # Load from Redis
        workflow_data = await self.redis.hget(
            default_sharding.get_workflow_key("data", workflow_id).encode(),
            b"workflow"
        )

        if workflow_data:
            workflow = json.loads(workflow_data)
            self.workflow_cache[workflow_id] = workflow
            return workflow

        return None

    async def _submit_child_workflow(
        self,
        task_id: str,
        workflow_id: str,
        metadata: Dict[str, Any]
    ):
        """Submit child workflow based on handler metadata."""
        # Get submission details from metadata
        child_workflow_id = metadata.get('child_workflow_id')
        child_shard = metadata.get('child_shard', 0)
        workflow_ref = metadata.get('workflow_ref')
        workflow_inputs = metadata.get('workflow_inputs', {})

        logger.info(
            f"Submitting child workflow {child_workflow_id} to shard {child_shard}"
        )

        # Submit to workflow submission stream
        submission_stream = default_sharding.get_stream_key(
            "workflow:submit",
            workflow_id=workflow_id
        )

        # Build submission data
        submission_data = {
            b'child_workflow_id': child_workflow_id.encode(),
            b'parent_workflow_id': workflow_id.encode(),
            b'parent_task_id': task_id.encode(),
            b'target_shard': str(child_shard).encode(),
            b'workflow_ref': workflow_ref.encode(),  # Always required now
            b'inputs': json.dumps(workflow_inputs).encode(),
            b'timestamp': datetime.utcnow().isoformat().encode()
        }

        # Submit to stream
        await self.redis.xadd(submission_stream, submission_data)

        logger.info(
            f"Submitted child workflow {child_workflow_id} for parent task {task_id}"
        )

    async def cleanup(self):
        """Cleanup handler resources"""
        for handler in self.handlers.values():
            if hasattr(handler, 'cleanup'):
                await handler.cleanup()
        await super().cleanup()
