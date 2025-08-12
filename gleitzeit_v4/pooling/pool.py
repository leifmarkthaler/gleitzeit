"""
Refactored Event-Driven Provider Pool using centralized event system
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Type, Callable
from datetime import datetime
import uuid

from .worker import ProviderWorker, WorkerState
from ..core.events import EventType, GleitzeitEvent
from ..core.errors import ResourceExhaustedError, ErrorCode

logger = logging.getLogger(__name__)


class ProviderPool:
    """
    Pool of provider workers using the centralized event system
    
    This replaces EventDrivenProviderPool to properly integrate with
    the centralized GleitzeitEvent system instead of creating a separate
    pool event bus.
    """
    
    def __init__(
        self,
        pool_id: str,
        protocol_id: str,
        provider_class: Type,
        min_workers: int = 2,
        max_workers: int = 10,
        scale_up_threshold: float = 0.8,
        scale_down_threshold: float = 0.2,
        event_emitter: Optional[Callable] = None,
        worker_config: Optional[Dict[str, Any]] = None,
        provider_config: Optional[Dict[str, Any]] = None
    ):
        self.pool_id = pool_id
        self.protocol_id = protocol_id
        self.provider_class = provider_class
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.scale_up_threshold = scale_up_threshold
        self.scale_down_threshold = scale_down_threshold
        self.event_emitter = event_emitter  # Function to emit centralized events
        self.worker_config = worker_config or {}
        self.provider_config = provider_config or {}  # Configuration for provider instances
        
        # Workers
        self.workers: Dict[str, ProviderWorker] = {}
        self.worker_states: Dict[str, WorkerState] = {}
        
        # State
        self.running = False
        self._scaling_lock = asyncio.Lock()
        self._last_scale_time = None
        self._scale_cooldown = 30
        
        # Metrics
        self.metrics = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_timeout": 0,
            "total_workers_created": 0,
            "scale_up_count": 0,
            "scale_down_count": 0
        }
        
        # Event subscriptions - we'll register with the centralized system
        self._event_handlers: Dict[str, Callable] = {}
        self._task_queue_depth = 0  # Track queue depth for scaling decisions
    
    async def start(self) -> None:
        """Start the provider pool"""
        if self.running:
            return
            
        self.running = True
        
        # Register for centralized events if we have an event system
        self._register_for_centralized_events()
        
        # Start initial workers
        await self._scale_to(self.min_workers)
        
        # Event-driven scaling - no background polling
        # Scaling decisions triggered by worker state events and task queue events
        
        logger.info(f"ProviderPool {self.pool_id} started with {self.min_workers} workers")
    
    async def stop(self) -> None:
        """Stop the provider pool"""
        if not self.running:
            return
            
        self.running = False
        
        # No monitoring task to stop - using event-driven scaling
        
        # Stop all workers
        stop_tasks = []
        for worker in self.workers.values():
            stop_tasks.append(worker.stop())
        
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        
        # Unregister event handlers
        self._unregister_centralized_events()
        
        logger.info(f"ProviderPool {self.pool_id} stopped")
    
    def _register_for_centralized_events(self) -> None:
        """Register for centralized events"""
        # Note: In a real implementation, this would register with the 
        # centralized event bus. For now, we'll handle events directly
        # when they're sent to the pool methods.
        pass
    
    def _unregister_centralized_events(self) -> None:
        """Unregister from centralized events"""
        pass
    
    async def handle_task_available(self, event: GleitzeitEvent) -> None:
        """Handle TASK_AVAILABLE event from centralized system"""
        task_data = event.data
        protocol = task_data.get("protocol")
        
        # Only handle tasks for our protocol
        if protocol != self.protocol_id:
            return
        
        print(f"🌊 Pool {self.pool_id} handling task {task_data.get('task_id')} for protocol {protocol}")
        
        # Update queue depth for scaling decisions
        self._task_queue_depth += 1
        
        # Find available workers
        available_workers = [
            worker for worker_id, worker in self.workers.items()
            if self.worker_states.get(worker_id) == WorkerState.IDLE
        ]
        
        print(f"   Available workers: {len(available_workers)} of {len(self.workers)}")
        
        if available_workers:
            # Let the first available worker handle it
            worker = available_workers[0]
            print(f"   Routing to worker {worker.worker_id}")
            await worker.handle_task_available(event)
            self._task_queue_depth = max(0, self._task_queue_depth - 1)
        else:
            print(f"   No available workers for task {task_data.get('task_id')}")
            # Event-driven scaling decision: scale up if no workers available
            await self._consider_scaling_up()
    
    async def _consider_scaling_up(self) -> None:
        """Consider scaling up based on current load - event-driven"""
        if not self._can_scale():
            return
            
        current_size = len(self.workers)
        busy_workers = sum(1 for state in self.worker_states.values() if state == WorkerState.BUSY)
        utilization = busy_workers / current_size if current_size > 0 else 1.0
        
        # Scale up if high utilization or queue building up
        if utilization >= self.scale_up_threshold or self._task_queue_depth > current_size:
            new_size = min(current_size + 2, self.max_workers)
            logger.info(f"Event-driven scale up triggered: utilization={utilization:.2f}, queue_depth={self._task_queue_depth}")
            await self._scale_to(new_size)
    
    async def _consider_scaling_down(self) -> None:
        """Consider scaling down based on current load - event-driven"""
        if not self._can_scale():
            return
            
        current_size = len(self.workers)
        busy_workers = sum(1 for state in self.worker_states.values() if state == WorkerState.BUSY)
        utilization = busy_workers / current_size if current_size > 0 else 0.0
        
        # Scale down if low utilization and no queue
        if utilization <= self.scale_down_threshold and self._task_queue_depth == 0:
            new_size = max(current_size - 1, self.min_workers)
            logger.info(f"Event-driven scale down triggered: utilization={utilization:.2f}")
            await self._scale_to(new_size)
    
    async def _create_worker(self) -> ProviderWorker:
        """Create a new worker instance"""
        worker_id = f"{self.pool_id}-worker-{uuid.uuid4().hex[:8]}"
        
        # Create provider instance with configuration
        provider_instance = self.provider_class(**self.provider_config)
        
        # Initialize provider if it has an initialize method
        if hasattr(provider_instance, 'initialize'):
            await provider_instance.initialize()
        
        # Create worker that uses centralized events
        worker = ProviderWorker(
            worker_id=worker_id,
            protocol_id=self.protocol_id,
            provider_instance=provider_instance,
            event_emitter=self.event_emitter,  # Pass centralized event emitter
            **self.worker_config
        )
        
        # Start worker
        await worker.start()
        
        # Track worker
        self.workers[worker_id] = worker
        self.worker_states[worker_id] = WorkerState.IDLE
        self.metrics["total_workers_created"] += 1
        
        # Emit worker started event
        await self._emit_event(EventType.WORKER_STARTED, {
            "worker_id": worker_id,
            "pool_id": self.pool_id,
            "protocol_id": self.protocol_id
        })
        
        logger.info(f"Created worker {worker_id} in pool {self.pool_id}")
        
        return worker
    
    async def _remove_worker(self, worker_id: str) -> None:
        """Remove a worker from the pool"""
        if worker_id not in self.workers:
            return
            
        worker = self.workers[worker_id]
        
        # Stop worker
        await worker.stop()
        
        # Clean up provider if needed
        if hasattr(worker.provider, 'cleanup'):
            await worker.provider.cleanup()
        
        # Remove from tracking
        del self.workers[worker_id]
        del self.worker_states[worker_id]
        
        # Emit worker stopped event
        await self._emit_event(EventType.WORKER_STOPPED, {
            "worker_id": worker_id,
            "pool_id": self.pool_id
        })
        
        logger.info(f"Removed worker {worker_id} from pool {self.pool_id}")
    
    async def _scale_to(self, target_size: int) -> None:
        """Scale pool to target size"""
        async with self._scaling_lock:
            current_size = len(self.workers)
            
            if target_size == current_size:
                return
                
            # Enforce limits
            target_size = max(self.min_workers, min(target_size, self.max_workers))
            
            if target_size > current_size:
                # Scale up
                workers_to_add = target_size - current_size
                logger.info(f"Scaling up pool {self.pool_id}: adding {workers_to_add} workers")
                
                for _ in range(workers_to_add):
                    await self._create_worker()
                
                self.metrics["scale_up_count"] += 1
                
                await self._emit_event(EventType.POOL_SCALED_UP, {
                    "pool_id": self.pool_id,
                    "protocol_id": self.protocol_id,
                    "previous_size": current_size,
                    "new_size": len(self.workers)
                })
                
            elif target_size < current_size:
                # Scale down
                workers_to_remove = current_size - target_size
                logger.info(f"Scaling down pool {self.pool_id}: removing {workers_to_remove} workers")
                
                # Find idle workers to remove
                idle_workers = [
                    worker_id for worker_id, state in self.worker_states.items()
                    if state == WorkerState.IDLE
                ]
                
                # Remove workers
                for i, worker_id in enumerate(idle_workers):
                    if i >= workers_to_remove:
                        break
                    await self._remove_worker(worker_id)
                
                self.metrics["scale_down_count"] += 1
                
                await self._emit_event(EventType.POOL_SCALED_DOWN, {
                    "pool_id": self.pool_id,
                    "protocol_id": self.protocol_id,
                    "previous_size": current_size,
                    "new_size": len(self.workers)
                })
            
            self._last_scale_time = datetime.utcnow()
    
    async def _emit_pool_metrics(self) -> None:
        """Emit pool metrics when events occur - no polling needed"""
        try:
            total_workers = len(self.workers)
            busy_workers = sum(1 for state in self.worker_states.values() if state == WorkerState.BUSY)
            utilization = busy_workers / total_workers if total_workers > 0 else 0
            
            await self._emit_event(EventType.POOL_METRICS, {
                "pool_id": self.pool_id,
                "protocol_id": self.protocol_id,
                "total_workers": total_workers,
                "busy_workers": busy_workers,
                "idle_workers": total_workers - busy_workers,
                "utilization": utilization,
                "queue_depth": self._task_queue_depth,
                "tasks_completed": self.metrics["tasks_completed"],
                "tasks_failed": self.metrics["tasks_failed"]
            })
        except Exception as e:
            logger.error(f"Pool {self.pool_id} metrics error: {e}")
    
    def _can_scale(self) -> bool:
        """Check if scaling is allowed (cooldown period)"""
        if self._last_scale_time is None:
            return True
            
        elapsed = (datetime.utcnow() - self._last_scale_time).total_seconds()
        return elapsed >= self._scale_cooldown
    
    async def _emit_event(self, event_type: EventType, data: Dict[str, Any]) -> None:
        """Emit event using centralized system"""
        if self.event_emitter:
            event = GleitzeitEvent(
                event_type=event_type,
                data=data,
                source=f"pool:{self.pool_id}",
                timestamp=datetime.utcnow()
            )
            await self.event_emitter(event)
    
    # Event handlers for centralized events
    
    async def handle_worker_idle(self, event: GleitzeitEvent) -> None:
        """Handle worker idle event"""
        worker_id = event.data.get("worker_id")
        if worker_id in self.worker_states:
            self.worker_states[worker_id] = WorkerState.IDLE
            # Event-driven scaling decision: consider scaling down when workers go idle
            await self._consider_scaling_down()
    
    async def handle_worker_busy(self, event: GleitzeitEvent) -> None:
        """Handle worker busy event"""  
        worker_id = event.data.get("worker_id")
        if worker_id in self.worker_states:
            self.worker_states[worker_id] = WorkerState.BUSY
    
    async def handle_worker_failed(self, event: GleitzeitEvent) -> None:
        """Handle worker failure"""
        worker_id = event.data.get("worker_id")
        
        if worker_id in self.workers:
            logger.error(f"Worker {worker_id} failed, replacing...")
            
            # Remove failed worker
            await self._remove_worker(worker_id)
            
            # Create replacement if below minimum
            if len(self.workers) < self.min_workers:
                await self._create_worker()
    
    async def handle_task_completed(self, event: GleitzeitEvent) -> None:
        """Handle task completion"""
        worker_id = event.data.get("worker_id")
        if worker_id and worker_id in self.workers:
            self.metrics["tasks_completed"] += 1
            print(f"📈 Pool {self.pool_id} updated: tasks_completed = {self.metrics['tasks_completed']}")
            # Emit metrics on task completion instead of polling
            await self._emit_pool_metrics()
    
    async def handle_task_failed(self, event: GleitzeitEvent) -> None:
        """Handle task failure"""
        if event.data.get("worker_id") in self.workers:
            self.metrics["tasks_failed"] += 1
    
    async def handle_task_timeout(self, event: GleitzeitEvent) -> None:
        """Handle task timeout"""
        if event.data.get("worker_id") in self.workers:
            self.metrics["tasks_timeout"] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics"""
        total_workers = len(self.workers)
        busy_workers = sum(1 for state in self.worker_states.values() if state == WorkerState.BUSY)
        
        return {
            "pool_id": self.pool_id,
            "protocol_id": self.protocol_id,
            "total_workers": total_workers,
            "busy_workers": busy_workers,
            "idle_workers": total_workers - busy_workers,
            "utilization": busy_workers / total_workers if total_workers > 0 else 0,
            "min_workers": self.min_workers,
            "max_workers": self.max_workers,
            **self.metrics
        }