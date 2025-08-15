"""
Circuit Breaker for Provider Pool
"""

import asyncio
import logging
from typing import Dict, Optional, Callable, Any
from enum import Enum
from datetime import datetime, timedelta

# Circuit breaker now uses centralized events through the pool manager
from ..core.errors import ErrorCode, SystemError
from ..core.events import EventType, GleitzeitEvent

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """
    Circuit breaker for provider pools
    
    Prevents cascading failures by temporarily blocking requests
    to failing providers and allowing recovery.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 3,
        event_emitter: Optional[Callable] = None
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.event_emitter = event_emitter
        
        # Circuit states per worker/pool
        self.circuits: Dict[str, Dict] = {}
    
    # Event handling methods for centralized events
    async def handle_task_failed(self, event: GleitzeitEvent) -> None:
        """Handle task failure event"""
        worker_id = event.data.get("worker_id")
        if worker_id:
            await self._record_failure(worker_id)
    
    async def handle_task_timeout(self, event: GleitzeitEvent) -> None:
        """Handle task timeout event"""
        worker_id = event.data.get("worker_id")
        if worker_id:
            await self._record_failure(worker_id)
    
    async def handle_task_completed(self, event: GleitzeitEvent) -> None:
        """Handle task completion event"""
        worker_id = event.data.get("worker_id")
        if worker_id:
            await self._record_success(worker_id)
    
    async def handle_worker_failed(self, event: GleitzeitEvent) -> None:
        """Handle worker failure event"""
        worker_id = event.data.get("worker_id")
        if worker_id:
            # Worker failure should open circuit immediately
            await self._open_circuit(worker_id, "worker_failed")
    
    
    async def _record_failure(self, worker_id: str) -> None:
        """Record a failure for a worker"""
        if worker_id not in self.circuits:
            self._init_circuit(worker_id)
        
        circuit = self.circuits[worker_id]
        circuit["consecutive_failures"] += 1
        circuit["total_failures"] += 1
        circuit["last_failure"] = datetime.utcnow()
        
        # Check if we should open the circuit
        if (circuit["state"] == CircuitState.CLOSED and
            circuit["consecutive_failures"] >= self.failure_threshold):
            await self._open_circuit(worker_id, "failure_threshold")
        
        elif circuit["state"] == CircuitState.HALF_OPEN:
            # Failed during recovery test
            await self._open_circuit(worker_id, "recovery_failed")
    
    async def _record_success(self, worker_id: str) -> None:
        """Record a success for a worker"""
        if worker_id not in self.circuits:
            self._init_circuit(worker_id)
        
        circuit = self.circuits[worker_id]
        circuit["consecutive_failures"] = 0  # Reset failure count
        circuit["consecutive_successes"] += 1
        circuit["total_successes"] += 1
        circuit["last_success"] = datetime.utcnow()
        
        # Check if we should close the circuit (from half-open)
        if (circuit["state"] == CircuitState.HALF_OPEN and
            circuit["consecutive_successes"] >= self.success_threshold):
            await self._close_circuit(worker_id)
    
    def _init_circuit(self, worker_id: str) -> None:
        """Initialize circuit state for a worker"""
        self.circuits[worker_id] = {
            "state": CircuitState.CLOSED,
            "consecutive_failures": 0,
            "consecutive_successes": 0,
            "total_failures": 0,
            "total_successes": 0,
            "last_failure": None,
            "last_success": None,
            "opened_at": None,
            "recovery_task": None
        }
    
    async def _open_circuit(self, worker_id: str, reason: str) -> None:
        """Open circuit for a worker"""
        if worker_id not in self.circuits:
            self._init_circuit(worker_id)
        
        circuit = self.circuits[worker_id]
        circuit["state"] = CircuitState.OPEN
        circuit["opened_at"] = datetime.utcnow()
        circuit["consecutive_successes"] = 0
        
        # Cancel existing recovery task
        if circuit["recovery_task"]:
            circuit["recovery_task"].cancel()
        
        # Schedule recovery attempt
        circuit["recovery_task"] = asyncio.create_task(
            self._schedule_recovery(worker_id)
        )
        
        # Emit circuit opened event
        await self._emit_event(EventType.CIRCUIT_OPENED, {
            "worker_id": worker_id,
            "reason": reason,
            "failures": circuit["consecutive_failures"],
            "recovery_timeout": self.recovery_timeout
        })
        
        logger.warning(f"Circuit opened for worker {worker_id}: {reason}")
    
    async def _close_circuit(self, worker_id: str) -> None:
        """Close circuit for a worker (normal operation)"""
        if worker_id not in self.circuits:
            return
        
        circuit = self.circuits[worker_id]
        circuit["state"] = CircuitState.CLOSED
        circuit["consecutive_failures"] = 0
        
        # Cancel recovery task
        if circuit["recovery_task"]:
            circuit["recovery_task"].cancel()
            circuit["recovery_task"] = None
        
        # Emit circuit closed event
        await self._emit_event(EventType.CIRCUIT_CLOSED, {
            "worker_id": worker_id,
            "successes": circuit["consecutive_successes"]
        })
        
        logger.info(f"Circuit closed for worker {worker_id}")
    
    async def _schedule_recovery(self, worker_id: str) -> None:
        """Schedule circuit recovery attempt"""
        try:
            await asyncio.sleep(self.recovery_timeout)
            await self._attempt_recovery(worker_id)
        except asyncio.CancelledError:
            pass
    
    async def _attempt_recovery(self, worker_id: str) -> None:
        """Attempt to recover a circuit"""
        if worker_id not in self.circuits:
            return
        
        circuit = self.circuits[worker_id]
        if circuit["state"] != CircuitState.OPEN:
            return
        
        # Move to half-open state
        circuit["state"] = CircuitState.HALF_OPEN
        circuit["consecutive_successes"] = 0
        
        # Emit half-open event
        await self._emit_event(EventType.CIRCUIT_HALF_OPEN, {
            "worker_id": worker_id
        })
        
        logger.info(f"Circuit half-open for worker {worker_id} - testing recovery")
    
    async def _emit_event(self, event_type: EventType, data: Dict[str, Any]) -> None:
        """Emit event using centralized system"""
        if self.event_emitter:
            event = GleitzeitEvent(
                event_type=event_type,
                data=data,
                source="circuit_breaker",
                timestamp=datetime.utcnow()
            )
            await self.event_emitter(event)
    
    def should_allow_request(self, worker_id: str) -> bool:
        """Check if a request should be allowed through the circuit"""
        if worker_id not in self.circuits:
            return True
        
        circuit = self.circuits[worker_id]
        state = circuit["state"]
        
        if state == CircuitState.CLOSED:
            return True
        elif state == CircuitState.OPEN:
            return False
        elif state == CircuitState.HALF_OPEN:
            # Allow limited requests for testing
            return True
        
        return True
    
    def get_circuit_stats(self, worker_id: str) -> Optional[Dict]:
        """Get circuit breaker stats for a worker"""
        if worker_id not in self.circuits:
            return None
        
        circuit = self.circuits[worker_id]
        return {
            "worker_id": worker_id,
            "state": circuit["state"].value,
            "consecutive_failures": circuit["consecutive_failures"],
            "consecutive_successes": circuit["consecutive_successes"],
            "total_failures": circuit["total_failures"],
            "total_successes": circuit["total_successes"],
            "success_rate": (
                circuit["total_successes"] / 
                (circuit["total_successes"] + circuit["total_failures"])
                if (circuit["total_successes"] + circuit["total_failures"]) > 0
                else 1.0
            ),
            "last_failure": circuit["last_failure"].isoformat() if circuit["last_failure"] else None,
            "last_success": circuit["last_success"].isoformat() if circuit["last_success"] else None,
            "opened_at": circuit["opened_at"].isoformat() if circuit["opened_at"] else None
        }
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Get circuit breaker stats for all workers"""
        return {
            worker_id: self.get_circuit_stats(worker_id)
            for worker_id in self.circuits.keys()
        }