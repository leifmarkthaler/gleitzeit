"""
Distributed Reconciliation Manager with leader election.

This module provides a distributed coordination layer for the ReconciliationService,
ensuring that only one instance performs reconciliation at a time in a multi-instance
deployment. Uses the TimerManager for scheduling reconciliation runs.
"""

import asyncio
import json
import logging
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from enum import Enum

# Redis imports removed - using persistence layer instead

from .reconciliation_service import ReconciliationService, ReconciliationMode
from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..core.events import GleitzeitEvent as Event, EventType
from ..events import StatelessEventBus

logger = logging.getLogger(__name__)


class ReconciliationRole(Enum):
    """Role of this instance in distributed reconciliation."""
    LEADER = "leader"
    FOLLOWER = "follower"
    CANDIDATE = "candidate"


class ReconciliationManager:
    """
    Manages distributed reconciliation with leader election.
    
    Features:
    - Leader election using Redis distributed locks
    - Automatic failover if leader fails
    - Heartbeat monitoring for leader health
    - Event-driven reconciliation triggers
    - Graceful leadership handoff
    - Uses TimerManager for scheduling via timer/v1 protocol
    """
    
    def __init__(
        self,
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[StatelessEventBus] = None,
        instance_id: Optional[str] = None,
        reconciliation_interval: int = 60,
        leader_ttl: int = 30,
        heartbeat_interval: int = 10,
    ):
        """
        Initialize the ReconciliationManager with distributed coordination.
        
        Args:
            persistence: Persistence adapter
            event_bus: Event bus for reconciliation events
            instance_id: Unique identifier for this instance
            reconciliation_interval: Seconds between reconciliation runs
            leader_ttl: TTL for leader lock in seconds
            heartbeat_interval: Seconds between leader heartbeats
        """
        self.persistence = persistence
        self.event_bus = event_bus
        self.instance_id = instance_id or f"reconciliation_{uuid.uuid4().hex[:8]}"
        self.reconciliation_interval = reconciliation_interval
        self.leader_ttl = leader_ttl
        self.heartbeat_interval = heartbeat_interval
        
        # Create the underlying reconciliation service
        self.reconciliation_service = ReconciliationService(
            persistence=persistence,
            event_bus=event_bus,
            mode=ReconciliationMode.MANUAL,  # We'll control when it runs
        )
        
        # State management
        self.role = ReconciliationRole.FOLLOWER
        self.is_running = False
        self.leader_lock_id: Optional[str] = None  # Lock ID instead of Lock object
        self.last_reconciliation = datetime.min
        
        # Background tasks
        self._election_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._timer_listener_task: Optional[asyncio.Task] = None
        self._timer_id: Optional[str] = None  # Timer ID for scheduled reconciliation
        
        logger.info(
            f"ReconciliationManager initialized: instance={self.instance_id}"
        )
        
    async def start(self):
        """Start the reconciliation manager."""
        if self.is_running:
            logger.warning("ReconciliationManager already running")
            return
            
        logger.info(f"Starting ReconciliationManager: {self.instance_id}")
        self.is_running = True
        
        # Initialize the reconciliation service
        await self.reconciliation_service.start()
        
        # Start leader election process
        self._election_task = asyncio.create_task(self._election_loop())
        
        # Start timer event listener  
        self._timer_listener_task = asyncio.create_task(self._timer_event_listener())
            
        # Register event handlers
        if self.event_bus:
            await self._register_event_handlers()
            
        logger.info(f"ReconciliationManager started: {self.instance_id}")
        
    async def stop(self):
        """Stop the reconciliation manager."""
        if not self.is_running:
            return
            
        logger.info(f"Stopping ReconciliationManager: {self.instance_id}")
        self.is_running = False
        
        # Step down if we're the leader
        if self.role == ReconciliationRole.LEADER:
            await self._step_down()
            
        # Cancel background tasks
        tasks = [
            self._election_task,
            self._heartbeat_task,
            self._timer_listener_task,
        ]
        
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        # Shutdown the reconciliation service
        await self.reconciliation_service.stop()
        
        logger.info(f"ReconciliationManager stopped: {self.instance_id}")
        
    async def trigger_reconciliation(self, reason: str = "manual"):
        """
        Manually trigger reconciliation if we're the leader.
        
        Args:
            reason: Reason for triggering reconciliation
        """
        if self.role != ReconciliationRole.LEADER:
            logger.debug(
                f"Reconciliation trigger ignored - not leader: {self.instance_id}"
            )
            return
            
        logger.info(f"Triggering reconciliation: reason={reason}")
        await self._run_reconciliation()
        
    async def get_status(self) -> Dict[str, Any]:
        """
        Get current status of the reconciliation manager.
        
        Returns:
            Status information
        """
        leader_id = await self._get_current_leader()
            
        return {
            "instance_id": self.instance_id,
            "role": self.role.value,
            "is_running": self.is_running,
            "current_leader": leader_id,
            "is_leader": self.role == ReconciliationRole.LEADER,
            "last_reconciliation": self.last_reconciliation.isoformat(),
            "reconciliation_interval": self.reconciliation_interval,
        }
        
    # Private methods
    
    async def _election_loop(self):
        """Main election loop for distributed coordination."""
        while self.is_running:
            try:
                if self.role != ReconciliationRole.LEADER:
                    # Try to become leader
                    await self._try_acquire_leadership()
                else:
                    # Maintain leadership
                    await self._maintain_leadership()
                    
                # Wait before next iteration
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in election loop: {e}")
                await asyncio.sleep(5)
                
    async def _try_acquire_leadership(self):
        """Try to acquire leadership through persistence layer lock."""
        lock_key = "gleitzeit:reconciliation:leader"
        
        try:
            # Generate a unique lock ID for this instance
            self.leader_lock_id = f"{self.instance_id}_{uuid.uuid4().hex[:8]}"
            
            # Try to acquire the lock via persistence layer
            acquired = await self.persistence.acquire_lock(
                lock_key,
                self.leader_lock_id,
                timeout=self.leader_ttl
            )
            
            if acquired:
                logger.info(f"Leadership acquired: {self.instance_id}")
                await self._become_leader()
            else:
                # Check if we need to update our role
                if self.role != ReconciliationRole.FOLLOWER:
                    self.role = ReconciliationRole.FOLLOWER
                    logger.debug(f"Remaining as follower: {self.instance_id}")
                    
        except Exception as e:
            logger.error(f"Error acquiring leadership: {e}")
            
    async def _maintain_leadership(self):
        """Maintain leadership by extending the lock."""
        if not self.leader_lock_id:
            # Lost our lock somehow
            await self._step_down()
            return
            
        try:
            # Extend the lock via persistence layer
            extended = await self.persistence.extend_lock(
                "gleitzeit:reconciliation:leader",
                self.leader_lock_id,
                timeout=self.leader_ttl
            )
            
            if not extended:
                # Failed to extend, step down
                logger.warning(f"Failed to extend leadership: {self.instance_id}")
                await self._step_down()
                
            # Update leader info in Redis
            await self._update_leader_info()
            
        except Exception as e:
            logger.error(f"Error maintaining leadership: {e}")
            await self._step_down()
            
    async def _become_leader(self):
        """Transition to leader role."""
        logger.info(f"Becoming leader: {self.instance_id}")
        self.role = ReconciliationRole.LEADER
        
        # Update leader info
        await self._update_leader_info()
        
        # Schedule periodic reconciliation using timer
        await self._schedule_next_reconciliation()
        
        # Emit leadership event
        if self.event_bus:
            await self.event_bus.emit(Event(
                event_type=EventType.RECONCILIATION_LEADER_ELECTED,
                data={
                    "instance_id": self.instance_id,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ))
            
    async def _step_down(self):
        """Step down from leader role."""
        logger.info(f"Stepping down from leadership: {self.instance_id}")
        self.role = ReconciliationRole.FOLLOWER
        
        # Cancel scheduled timer
        if self._timer_id:
            await self._cancel_reconciliation_timer()
            
        # Release the lock via persistence layer
        if self.leader_lock_id:
            try:
                await self.persistence.release_lock(
                    "gleitzeit:reconciliation:leader",
                    self.leader_lock_id
                )
            except:
                pass
            self.leader_lock_id = None
            
        # Clear leader info
        await self._clear_leader_info()
        
        # Emit event
        if self.event_bus:
            await self.event_bus.emit(Event(
                event_type=EventType.RECONCILIATION_LEADER_STEPPED_DOWN,
                data={
                    "instance_id": self.instance_id,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ))
            
    async def _schedule_next_reconciliation(self):
        """Schedule the next reconciliation run using timer."""
        try:
            # Create a unique timer ID for this reconciliation
            self._timer_id = f"reconciliation:{self.instance_id}:{uuid.uuid4().hex[:8]}"
            
            # Calculate wake time
            wake_at = time.time() + self.reconciliation_interval
            
            # Store timer in Redis (same format as TimerTaskHandler)
            await self.persistence.zadd("timers:pending", {self._timer_id: wake_at})
            
            # Store timer metadata as hash (compatible with TimerMonitorService)
            timer_data = {
                "timer_type": "reconciliation",
                "instance_id": self.instance_id,
                "created_at": datetime.utcnow().isoformat(),
                "wake_at": str(wake_at),
                # Add dummy workflow/task IDs for reconciliation timers
                "workflow_id": f"system:reconciliation:{self.instance_id}",
                "task_id": "reconciliation_timer"
            }
            await self.persistence.hset(
                f"timer:{self._timer_id}",
                mapping=timer_data
            )
            await self.persistence.expire(f"timer:{self._timer_id}", self.reconciliation_interval + 60)
            
            logger.info(f"Scheduled reconciliation timer: {self._timer_id} at {datetime.fromtimestamp(wake_at).isoformat()}")
            
        except Exception as e:
            logger.error(f"Failed to schedule reconciliation: {e}")
    
    async def _cancel_reconciliation_timer(self):
        """Cancel the scheduled reconciliation timer."""
        if not self._timer_id:
            return
            
        try:
            # Remove from pending timers
            await self.persistence.zrem("timers:pending", self._timer_id)
            
            # Delete timer metadata
            await self.persistence.delete(f"timer:{self._timer_id}")
            
            logger.info(f"Cancelled reconciliation timer: {self._timer_id}")
            self._timer_id = None
            
        except Exception as e:
            logger.error(f"Failed to cancel reconciliation timer: {e}")
    
    async def _handle_timer_expiry(self):
        """Handle when our reconciliation timer expires."""
        # Only run if we're still the leader
        if self.role != ReconciliationRole.LEADER:
            logger.debug("Timer expired but no longer leader, ignoring")
            return
            
        # Run reconciliation
        await self._run_reconciliation()
        
        # Schedule the next run
        await self._schedule_next_reconciliation()
                
    async def _run_reconciliation(self):
        """Run the actual reconciliation process."""
        try:
            logger.info(f"Starting reconciliation run: {self.instance_id}")
            start_time = datetime.utcnow()
            
            # Emit start event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.RECONCILIATION_STARTED,
                    data={
                        "instance_id": self.instance_id,
                        "start_time": start_time.isoformat(),
                    }
                ))
                
            # Run reconciliation
            result = await self.reconciliation_service.reconcile()
            
            # Update last reconciliation time
            self.last_reconciliation = datetime.utcnow()
            duration = (self.last_reconciliation - start_time).total_seconds()
            
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
            
        except Exception as e:
            logger.error(f"Error running reconciliation: {e}")
            
            # Emit error event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.RECONCILIATION_FAILED,
                    data={
                        "instance_id": self.instance_id,
                        "error": str(e),
                    }
                ))
                
    async def _update_leader_info(self):
        """Update leader information in Redis."""
        info = {
            "instance_id": self.instance_id,
            "role": self.role.value,
            "last_heartbeat": datetime.utcnow().isoformat(),
            "last_reconciliation": self.last_reconciliation.isoformat(),
        }
        
        await self.persistence.set(
            "gleitzeit:reconciliation:leader_info",
            json.dumps(info),
            ex=self.leader_ttl
        )
        
    async def _clear_leader_info(self):
        """Clear leader information from Redis."""
        await self.persistence.delete("gleitzeit:reconciliation:leader_info")
        
    async def _get_current_leader(self) -> Optional[str]:
        """Get the current leader's instance ID."""
        try:
            info = await self.persistence.get("gleitzeit:reconciliation:leader_info")
            if info:
                data = json.loads(info)
                return data.get("instance_id")
        except:
            pass
        return None
        
    async def _store_reconciliation_history(self, result: Dict[str, Any], duration: float):
        """Store reconciliation run history."""
        history_entry = {
            "instance_id": self.instance_id,
            "timestamp": datetime.utcnow().isoformat(),
            "duration_seconds": duration,
            "result": result,
        }
        
        # Store in a list with a limit
        # Store history entry with timestamp key (lpush/ltrim not available)
        history_key = f"gleitzeit:reconciliation:history:{int(time.time() * 1000)}"
        await self.persistence.set(
            history_key,
            json.dumps(history_entry),
            ex=86400  # Keep history for 24 hours
        )
        
    async def _register_event_handlers(self):
        """Register event handlers for reconciliation triggers."""
        
        async def handle_workflow_stuck(event: Event):
            """Handle workflow stuck events."""
            if self.role == ReconciliationRole.LEADER:
                logger.info(f"Workflow stuck event received, triggering reconciliation")
                await self.trigger_reconciliation("workflow_stuck")
                
        async def handle_task_timeout(event: Event):
            """Handle task timeout events."""
            if self.role == ReconciliationRole.LEADER:
                logger.info(f"Task timeout event received, triggering reconciliation")
                await self.trigger_reconciliation("task_timeout")
                
        # Register handlers
        if self.event_bus:
            self.event_bus.register(
                EventType.WORKFLOW_STUCK,
                handle_workflow_stuck
            )
            self.event_bus.register(
                EventType.TASK_TIMEOUT,
                handle_task_timeout
            )
    
    async def _timer_event_listener(self):
        """
        Monitor for scheduled reconciliation timer expiry.
        
        Since we can't use xread directly through persistence layer,
        we use a periodic check approach instead.
        """
        logger.info(f"Starting timer monitor for scheduled reconciliation")
        
        while self.is_running:
            try:
                # Check every 5 seconds if we have a scheduled timer
                await asyncio.sleep(5)
                
                # Only check if we're the leader and have a timer scheduled
                if self.role == ReconciliationRole.LEADER and self._timer_id:
                    # Check if the timer has expired by looking at the timer metadata
                    timer_key = f"timer:{self._timer_id}"
                    timer_data = await self.persistence.hgetall(timer_key)
                    
                    if timer_data:
                        # Check if wake_at time has passed
                        wake_at = float(timer_data.get(b"wake_at", 0))
                        current_time = time.time()
                        
                        if current_time >= wake_at:
                            logger.info(f"Scheduled reconciliation timer expired")
                            await self._handle_timer_expiry()
                                
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in timer monitor: {e}")
                await asyncio.sleep(5)