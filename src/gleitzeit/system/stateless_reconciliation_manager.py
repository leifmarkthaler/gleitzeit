"""
Stateless Reconciliation Manager with distributed coordination.

This module provides a stateless reconciliation system that uses external
triggers instead of persistent loops. Each instance can participate in
reconciliation when triggered, with distributed coordination to prevent
duplicate work.
"""

import asyncio
import json
import logging
import uuid
import time
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum

from .reconciliation_service import ReconciliationService, ReconciliationMode
from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..core.events import GleitzeitEvent as Event, EventType
from ..events import StatelessEventBus

logger = logging.getLogger(__name__)


class StatelessReconciliationManager:
    """
    Manages distributed reconciliation without persistent loops.

    Features:
    - No persistent loops - triggered externally
    - Distributed lock for single reconciliation
    - Event-driven reconciliation triggers
    - Idempotent reconciliation runs
    - TTL-based coordination
    """

    def __init__(
        self,
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[StatelessEventBus] = None,
        instance_id: Optional[str] = None,
        reconciliation_ttl: int = 300,  # 5 minute TTL for reconciliation lock
    ):
        """
        Initialize the StatelessReconciliationManager.

        Args:
            persistence: Persistence adapter
            event_bus: Event bus for reconciliation events
            instance_id: Unique identifier for this instance
            reconciliation_ttl: TTL for reconciliation lock in seconds
        """
        self.persistence = persistence
        self.event_bus = event_bus
        self.instance_id = instance_id or f"reconciliation_{uuid.uuid4().hex[:8]}"
        self.reconciliation_ttl = reconciliation_ttl

        # Create the underlying reconciliation service
        self.reconciliation_service = ReconciliationService(
            persistence=persistence,
            event_bus=event_bus,
            mode=ReconciliationMode.MANUAL,  # Always manual - we control when it runs
        )

        # State (minimal - no persistent state!)
        self._initialized = False

        logger.info(
            f"StatelessReconciliationManager initialized: instance={self.instance_id}"
        )

    async def initialize(self):
        """Initialize the reconciliation manager (no loops started!)."""
        if self._initialized:
            logger.warning("StatelessReconciliationManager already initialized")
            return

        logger.info(f"Initializing StatelessReconciliationManager: {self.instance_id}")

        # Initialize the reconciliation service
        await self.reconciliation_service.start()

        # Register instance in persistence with TTL
        await self._register_instance()

        # Register event handlers if we have an event bus
        if self.event_bus:
            await self._register_event_handlers()

        self._initialized = True
        logger.info(f"StatelessReconciliationManager initialized: {self.instance_id}")

    async def shutdown(self):
        """Shutdown the reconciliation manager."""
        if not self._initialized:
            return

        logger.info(f"Shutting down StatelessReconciliationManager: {self.instance_id}")

        # Unregister instance
        await self._unregister_instance()

        # Shutdown the reconciliation service
        await self.reconciliation_service.stop()

        self._initialized = False
        logger.info(f"StatelessReconciliationManager shutdown: {self.instance_id}")

    async def reconcile_once(self, reason: str = "manual") -> Dict[str, Any]:
        """
        Perform a single reconciliation run.

        This method is idempotent and uses distributed locking to ensure
        only one instance performs reconciliation at a time.

        Args:
            reason: Reason for triggering reconciliation

        Returns:
            Reconciliation result or None if lock couldn't be acquired
        """
        if not self._initialized:
            raise RuntimeError("ReconciliationManager not initialized")

        # Try to acquire reconciliation lock
        lock_key = "gleitzeit:reconciliation:active"
        lock_id = f"{self.instance_id}:{uuid.uuid4().hex[:8]}"

        acquired = await self.persistence.acquire_lock(
            lock_key,
            lock_id,
            timeout=self.reconciliation_ttl
        )

        if not acquired:
            # Another instance is reconciling
            logger.debug(f"Reconciliation already in progress by another instance")
            return {
                "status": "skipped",
                "reason": "another_instance_reconciling",
                "instance_id": self.instance_id
            }

        try:
            logger.info(f"Starting reconciliation: instance={self.instance_id}, reason={reason}")
            start_time = datetime.utcnow()

            # Emit start event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.RECONCILIATION_STARTED,
                    data={
                        "instance_id": self.instance_id,
                        "start_time": start_time.isoformat(),
                        "reason": reason
                    }
                ))

            # Run reconciliation
            result = await self.reconciliation_service.reconcile()

            # Calculate duration
            duration = (datetime.utcnow() - start_time).total_seconds()

            # Add metadata to result
            result.update({
                "status": "completed",
                "instance_id": self.instance_id,
                "duration_seconds": duration,
                "timestamp": datetime.utcnow().isoformat()
            })

            # Store reconciliation history
            await self._store_reconciliation_history(result, duration)

            # Emit completion event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.RECONCILIATION_COMPLETED,
                    data={
                        "instance_id": self.instance_id,
                        "duration_seconds": duration,
                        "workflows_recovered": result.get("workflows_recovered", 0),
                        "tasks_recovered": result.get("tasks_recovered", 0),
                        "errors": result.get("errors", 0),
                    }
                ))

            logger.info(
                f"Reconciliation completed: duration={duration:.2f}s, "
                f"workflows={result.get('workflows_recovered', 0)}, "
                f"tasks={result.get('tasks_recovered', 0)}"
            )

            return result

        except Exception as e:
            logger.error(f"Error during reconciliation: {e}")

            # Emit error event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.RECONCILIATION_FAILED,
                    data={
                        "instance_id": self.instance_id,
                        "error": str(e),
                    }
                ))

            return {
                "status": "failed",
                "error": str(e),
                "instance_id": self.instance_id
            }

        finally:
            # Always release the lock
            try:
                await self.persistence.release_lock(lock_key, lock_id)
            except Exception as e:
                logger.error(f"Error releasing reconciliation lock: {e}")

    async def get_status(self) -> Dict[str, Any]:
        """
        Get current status of the reconciliation system.

        Returns:
            Status information
        """
        # Check if reconciliation is currently running
        is_active = await self.persistence.exists("gleitzeit:reconciliation:active")

        # Get last reconciliation info
        last_run = await self._get_last_reconciliation()

        # Get registered instances
        instances = await self._get_registered_instances()

        return {
            "instance_id": self.instance_id,
            "initialized": self._initialized,
            "reconciliation_active": bool(is_active),
            "last_reconciliation": last_run,
            "registered_instances": instances,
            "reconciliation_ttl": self.reconciliation_ttl,
        }

    async def trigger_if_needed(self) -> Dict[str, Any]:
        """
        Check if reconciliation is needed and trigger if so.

        This method can be called periodically by external schedulers
        to check if reconciliation should run.

        Returns:
            Result of reconciliation or skip reason
        """
        # Check for stuck workflows/tasks
        needs_reconciliation = False
        reason = "periodic_check"

        # Check for stuck workflows
        stuck_workflows = await self.persistence.keys("workflow:*:status")
        for key in stuck_workflows[:10]:  # Check first 10
            status = await self.persistence.get(key)
            if status == "pending" or status == "running":
                # Check if it's been stuck for too long
                workflow_id = key.split(":")[1]
                last_update_key = f"workflow:{workflow_id}:last_update"
                last_update = await self.persistence.get(last_update_key)
                if last_update:
                    try:
                        last_time = datetime.fromisoformat(last_update)
                        if (datetime.utcnow() - last_time).total_seconds() > 300:
                            needs_reconciliation = True
                            reason = "stuck_workflows_detected"
                            break
                    except:
                        pass

        if needs_reconciliation:
            logger.info(f"Reconciliation needed: {reason}")
            return await self.reconcile_once(reason)
        else:
            return {
                "status": "skipped",
                "reason": "not_needed",
                "instance_id": self.instance_id
            }

    # Private helper methods

    async def _register_instance(self):
        """Register this instance with TTL."""
        instance_key = f"gleitzeit:reconciliation:instances:{self.instance_id}"
        instance_data = {
            "instance_id": self.instance_id,
            "registered_at": datetime.utcnow().isoformat(),
            "ttl": self.reconciliation_ttl
        }

        await self.persistence.set(
            instance_key,
            json.dumps(instance_data),
            ex=self.reconciliation_ttl
        )

    async def _unregister_instance(self):
        """Unregister this instance."""
        instance_key = f"gleitzeit:reconciliation:instances:{self.instance_id}"
        await self.persistence.delete(instance_key)

    async def _get_registered_instances(self) -> list:
        """Get list of registered instances."""
        pattern = "gleitzeit:reconciliation:instances:*"
        keys = await self.persistence.keys(pattern)
        instances = []

        for key in keys:
            try:
                data = await self.persistence.get(key)
                if data:
                    instances.append(json.loads(data))
            except:
                pass

        return instances

    async def _store_reconciliation_history(self, result: Dict[str, Any], duration: float):
        """Store reconciliation run history."""
        history_entry = {
            "instance_id": self.instance_id,
            "timestamp": datetime.utcnow().isoformat(),
            "duration_seconds": duration,
            "result": result,
        }

        # Store with timestamp key
        history_key = f"gleitzeit:reconciliation:history:{int(time.time() * 1000)}"
        await self.persistence.set(
            history_key,
            json.dumps(history_entry),
            ex=86400  # Keep history for 24 hours
        )

        # Also store as "last reconciliation" for quick access
        await self.persistence.set(
            "gleitzeit:reconciliation:last",
            json.dumps(history_entry),
            ex=86400
        )

    async def _get_last_reconciliation(self) -> Optional[Dict[str, Any]]:
        """Get information about the last reconciliation run."""
        try:
            data = await self.persistence.get("gleitzeit:reconciliation:last")
            if data:
                return json.loads(data)
        except:
            pass
        return None

    async def _register_event_handlers(self):
        """Register event handlers for reconciliation triggers."""

        async def handle_workflow_stuck(event: Event):
            """Handle workflow stuck events."""
            logger.info(f"Workflow stuck event received, queuing reconciliation")
            # In stateless mode, just log - external trigger will handle reconciliation
            await self.persistence.set(
                "gleitzeit:reconciliation:needed",
                "workflow_stuck",
                ex=300  # 5 minute TTL
            )

        async def handle_task_timeout(event: Event):
            """Handle task timeout events."""
            logger.info(f"Task timeout event received, queuing reconciliation")
            # In stateless mode, just log - external trigger will handle reconciliation
            await self.persistence.set(
                "gleitzeit:reconciliation:needed",
                "task_timeout",
                ex=300  # 5 minute TTL
            )

        # Register handlers
        self.event_bus.register(EventType.WORKFLOW_STUCK, handle_workflow_stuck)
        self.event_bus.register(EventType.TASK_TIMEOUT, handle_task_timeout)