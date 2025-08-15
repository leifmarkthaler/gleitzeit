"""
Backpressure Management for Provider Pool
"""

import asyncio
import logging
from typing import Dict, Optional, Callable, Any
from datetime import datetime, timedelta

from ..core.errors import ErrorCode, SystemError, ResourceExhaustedError
from ..core.events import EventType, GleitzeitEvent

logger = logging.getLogger(__name__)


class BackpressureManager:
    """
    Manages backpressure in provider pools
    
    Monitors resource usage and prevents overload by:
    - Tracking worker resource usage (CPU, memory)
    - Signaling high pressure conditions
    - Requesting pool scaling when needed
    - Throttling task distribution
    """
    
    def __init__(
        self,
        memory_threshold: float = 80.0,  # Percentage
        cpu_threshold: float = 80.0,     # Percentage
        queue_threshold: int = 100,      # Tasks in queue
        event_emitter: Optional[Callable] = None
    ):
        self.memory_threshold = memory_threshold
        self.cpu_threshold = cpu_threshold
        self.queue_threshold = queue_threshold
        self.event_emitter = event_emitter
        
        # Worker resource tracking
        self.worker_resources: Dict[str, Dict] = {}
        self.pool_metrics: Dict[str, Dict] = {}
        
        # Backpressure state
        self.high_pressure_workers = set()
        self.critical_pressure_workers = set()
    
    # Event handlers for centralized events
    async def handle_worker_heartbeat(self, event: GleitzeitEvent) -> None:
        """Handle worker heartbeat with resource info"""
        await self._on_worker_heartbeat(event)
    
    async def handle_pool_metrics(self, event: GleitzeitEvent) -> None:
        """Handle pool metrics"""
        await self._on_pool_metrics(event)
    
    async def handle_task_available(self, event: GleitzeitEvent) -> None:
        """Filter task distribution based on backpressure"""
        await self._on_task_available(event)
    
    async def _on_worker_heartbeat(self, event) -> None:
        """Handle worker heartbeat with resource info"""
        worker_id = event.data.get("worker_id")
        if not worker_id:
            return
        
        # Extract resource metrics
        resources = {
            "memory_usage_mb": event.data.get("memory_usage_mb", 0),
            "cpu_percent": event.data.get("cpu_percent", 0),
            "current_tasks": event.data.get("current_tasks", 0),
            "max_tasks": event.data.get("max_tasks", 1),
            "last_update": datetime.utcnow()
        }
        
        self.worker_resources[worker_id] = resources
        
        # Check for backpressure conditions
        await self._check_worker_pressure(worker_id, resources)
    
    async def _on_pool_metrics(self, event) -> None:
        """Handle pool metrics"""
        pool_id = event.data.get("pool_id")
        if not pool_id:
            return
        
        self.pool_metrics[pool_id] = {
            "total_workers": event.data.get("total_workers", 0),
            "busy_workers": event.data.get("busy_workers", 0),
            "utilization": event.data.get("utilization", 0),
            "tasks_completed": event.data.get("tasks_completed", 0),
            "tasks_failed": event.data.get("tasks_failed", 0),
            "last_update": datetime.utcnow()
        }
        
        # Check pool-level backpressure
        await self._check_pool_pressure(pool_id, self.pool_metrics[pool_id])
    
    async def _on_task_available(self, event) -> None:
        """Filter task distribution based on backpressure"""
        # This could be enhanced to prevent task routing to high-pressure workers
        # For now, just log high pressure situations
        
        if self.critical_pressure_workers:
            logger.warning(
                f"Critical backpressure on workers: {list(self.critical_pressure_workers)}"
            )
    
    async def _check_worker_pressure(self, worker_id: str, resources: Dict) -> None:
        """Check if worker is under pressure"""
        memory_mb = resources.get("memory_usage_mb", 0)
        cpu_percent = resources.get("cpu_percent", 0)
        task_load = resources.get("current_tasks", 0) / resources.get("max_tasks", 1)
        
        # Calculate pressure score (0-100)
        pressure_score = max(
            cpu_percent,
            task_load * 100,
            min(memory_mb / 10, 100)  # Rough memory pressure (10MB = 1%)
        )
        
        previous_high = worker_id in self.high_pressure_workers
        previous_critical = worker_id in self.critical_pressure_workers
        
        # Determine pressure level
        if pressure_score >= 95:
            # Critical pressure
            self.critical_pressure_workers.add(worker_id)
            self.high_pressure_workers.add(worker_id)
            
            if not previous_critical:
                await self._emit_event(EventType.BACKPRESSURE_CRITICAL, {
                    "worker_id": worker_id,
                    "pressure_score": pressure_score,
                    "memory_mb": memory_mb,
                    "cpu_percent": cpu_percent,
                    "task_load": task_load
                })
                
                # Request immediate scaling
                await self._emit_event(EventType.POOL_SCALE_REQUESTED, {
                    "reason": "critical_backpressure",
                    "worker_id": worker_id,
                    "scale_factor": 2  # Double the pool size
                })
        
        elif pressure_score >= self.memory_threshold:
            # High pressure
            self.high_pressure_workers.add(worker_id)
            self.critical_pressure_workers.discard(worker_id)
            
            if not previous_high:
                await self._emit_event(EventType.BACKPRESSURE_HIGH, {
                    "worker_id": worker_id,
                    "pressure_score": pressure_score,
                    "memory_mb": memory_mb,
                    "cpu_percent": cpu_percent,
                    "task_load": task_load
                })
        
        else:
            # Normal pressure
            self.high_pressure_workers.discard(worker_id)
            self.critical_pressure_workers.discard(worker_id)
            
            if previous_high:
                await self._emit_event(EventType.BACKPRESSURE_NORMAL, {
                    "worker_id": worker_id,
                    "pressure_score": pressure_score
                })
    
    async def _check_pool_pressure(self, pool_id: str, metrics: Dict) -> None:
        """Check pool-level pressure"""
        utilization = metrics.get("utilization", 0)
        total_workers = metrics.get("total_workers", 0)
        busy_workers = metrics.get("busy_workers", 0)
        
        # High utilization suggests need for scaling
        if utilization > 0.9 and total_workers > 0:
            await self._emit_event(EventType.POOL_SCALE_REQUESTED, {
                "pool_id": pool_id,
                "reason": "high_utilization",
                "utilization": utilization,
                "current_size": total_workers,
                "suggested_size": total_workers + max(1, total_workers // 2)
            })
    
    async def _emit_event(self, event_type: EventType, data: Dict[str, Any]) -> None:
        """Emit event using centralized system"""
        if self.event_emitter:
            event = GleitzeitEvent(
                event_type=event_type,
                data=data,
                source="backpressure_manager",
                timestamp=datetime.utcnow()
            )
            await self.event_emitter(event)
    
    def should_throttle_worker(self, worker_id: str) -> bool:
        """Check if tasks to this worker should be throttled"""
        return worker_id in self.high_pressure_workers
    
    def should_block_worker(self, worker_id: str) -> bool:
        """Check if tasks to this worker should be blocked"""
        return worker_id in self.critical_pressure_workers
    
    def get_worker_pressure_score(self, worker_id: str) -> Optional[float]:
        """Get pressure score for a worker"""
        if worker_id not in self.worker_resources:
            return None
        
        resources = self.worker_resources[worker_id]
        memory_mb = resources.get("memory_usage_mb", 0)
        cpu_percent = resources.get("cpu_percent", 0)
        task_load = resources.get("current_tasks", 0) / resources.get("max_tasks", 1)
        
        return max(
            cpu_percent,
            task_load * 100,
            min(memory_mb / 10, 100)
        )
    
    def get_pool_pressure_stats(self) -> Dict:
        """Get overall pressure statistics"""
        total_workers = len(self.worker_resources)
        
        return {
            "total_workers": total_workers,
            "high_pressure_workers": len(self.high_pressure_workers),
            "critical_pressure_workers": len(self.critical_pressure_workers),
            "high_pressure_ratio": (
                len(self.high_pressure_workers) / total_workers
                if total_workers > 0 else 0
            ),
            "worker_details": {
                worker_id: {
                    "pressure_score": self.get_worker_pressure_score(worker_id),
                    "is_high_pressure": worker_id in self.high_pressure_workers,
                    "is_critical_pressure": worker_id in self.critical_pressure_workers
                }
                for worker_id in self.worker_resources.keys()
            }
        }
    
    def cleanup_stale_workers(self, max_age_seconds: int = 300) -> None:
        """Remove stale worker resource data"""
        now = datetime.utcnow()
        stale_workers = []
        
        for worker_id, resources in self.worker_resources.items():
            last_update = resources.get("last_update", now)
            if (now - last_update).total_seconds() > max_age_seconds:
                stale_workers.append(worker_id)
        
        for worker_id in stale_workers:
            del self.worker_resources[worker_id]
            self.high_pressure_workers.discard(worker_id)
            self.critical_pressure_workers.discard(worker_id)
            
        if stale_workers:
            logger.info(f"Cleaned up {len(stale_workers)} stale worker resources")