"""
Refactored Pool Manager using centralized event system
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Type, Callable
from datetime import datetime
import uuid

from gleitzeit.pooling.pool import ProviderPool
from gleitzeit.pooling.circuit_breaker import CircuitBreaker
from gleitzeit.pooling.backpressure import BackpressureManager
from gleitzeit.core.events import EventType, GleitzeitEvent
from gleitzeit.core.errors import ErrorCode, SystemError, ProviderError, ConfigurationError

logger = logging.getLogger(__name__)


class PoolManager:
    """
    Pool manager using centralized event system
    
    This replaces PoolManager to properly integrate with the centralized
    GleitzeitEvent system instead of creating a separate event bus.
    """
    
    def __init__(self, event_emitter: Optional[Callable] = None):
        self.event_emitter = event_emitter  # Function to emit centralized events
        
        # Pool management
        self.pools: Dict[str, CentralizedProviderPool] = {}  # protocol_id -> pool
        self.pool_configs: Dict[str, Dict[str, Any]] = {}
        
        # System components - these still need their own event handling
        # but we'll integrate them with centralized events
        self.circuit_breaker = None  # Will initialize when needed
        self.backpressure_manager = None  # Will initialize when needed
        
        # State
        self.running = False
        self._cleanup_task: Optional[asyncio.Task] = None
        
        # Metrics
        self.system_metrics = {
            "pools_created": 0,
            "pools_destroyed": 0,
            "total_tasks_routed": 0,
            "routing_failures": 0
        }
        
        # Event routing - map event types to handlers
        self._event_handlers = {
            EventType.TASK_AVAILABLE: self._handle_task_available,
            EventType.WORKER_IDLE: self._handle_worker_idle,
            EventType.WORKER_BUSY: self._handle_worker_busy,
            EventType.WORKER_FAILED: self._handle_worker_failed,
            EventType.TASK_COMPLETED: self._handle_task_completed,
            EventType.TASK_FAILED: self._handle_task_failed,
            EventType.TASK_TIMEOUT: self._handle_task_timeout,
        }
    
    async def start(self) -> None:
        """Start the pool manager"""
        if self.running:
            return
        
        self.running = True
        
        # Initialize system components
        if not self.circuit_breaker:
            self.circuit_breaker = CircuitBreaker()
        if not self.backpressure_manager:
            self.backpressure_manager = BackpressureManager()
        
        # Event-driven monitoring - no background polling
        # Health monitoring now happens via events: worker failures, task timeouts, etc.
        logger.info("PoolManager started in event-driven mode")
        
        # Schedule periodic cleanup (only for stale data, not monitoring)
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        
        logger.info("PoolManager started")
    
    async def stop(self) -> None:
        """Stop the pool manager"""
        if not self.running:
            return
        
        self.running = False
        
        # Stop cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Stop all pools
        stop_tasks = []
        for pool in self.pools.values():
            stop_tasks.append(pool.stop())
        
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        
        logger.info("PoolManager stopped")
    
    async def handle_centralized_event(self, event: GleitzeitEvent) -> None:
        """Handle event from centralized event system"""
        handler = self._event_handlers.get(event.event_type)
        if handler:
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Error handling event {event.event_type}: {e}")
    
    async def create_pool(
        self,
        protocol_id: str,
        provider_class: Type,
        min_workers: int = 2,
        max_workers: int = 10,
        provider_config: Optional[Dict[str, Any]] = None,
        **pool_config
    ) -> str:
        """Create a new provider pool"""
        if protocol_id in self.pools:
            raise ConfigurationError(
                f"Pool for protocol {protocol_id} already exists",
                data={"protocol_id": protocol_id, "existing_pools": list(self.pools.keys())}
            )
        
        pool_id = f"pool-{protocol_id}-{uuid.uuid4().hex[:8]}"
        
        # Create pool with centralized event emitter
        pool = ProviderPool(
            pool_id=pool_id,
            protocol_id=protocol_id,
            provider_class=provider_class,
            min_workers=min_workers,
            max_workers=max_workers,
            event_emitter=self.event_emitter,  # Pass centralized event emitter
            provider_config=provider_config,  # Pass provider configuration
            **pool_config
        )
        
        # Store pool and config
        self.pools[protocol_id] = pool
        self.pool_configs[protocol_id] = {
            "provider_class": provider_class,
            "min_workers": min_workers,
            "max_workers": max_workers,
            **pool_config
        }
        
        # Start pool
        await pool.start()
        
        self.system_metrics["pools_created"] += 1
        
        logger.info(f"Created pool {pool_id} for protocol {protocol_id}")
        return pool_id
    
    async def destroy_pool(self, protocol_id: str) -> None:
        """Destroy a provider pool"""
        if protocol_id not in self.pools:
            raise ProviderError(
                f"Pool for protocol {protocol_id} not found",
                code=ErrorCode.PROVIDER_NOT_FOUND,
                data={"protocol_id": protocol_id, "available_protocols": list(self.pools.keys())}
            )
        
        pool = self.pools[protocol_id]
        await pool.stop()
        
        del self.pools[protocol_id]
        del self.pool_configs[protocol_id]
        
        self.system_metrics["pools_destroyed"] += 1
        
        logger.info(f"Destroyed pool for protocol {protocol_id}")
    
    async def route_task(
        self,
        task_id: str,
        protocol_id: str,
        method: str,
        params: Dict[str, Any],
        priority: int = 0,
        timeout: Optional[int] = None
    ) -> None:
        """Route a task by emitting TASK_AVAILABLE event"""
        
        # Check if pool exists
        if protocol_id not in self.pools:
            logger.error(f"No pool found for protocol {protocol_id}")
            self.system_metrics["routing_failures"] += 1
            
            raise ProviderError(
                f"No pool available for protocol {protocol_id}",
                code=ErrorCode.PROVIDER_NOT_FOUND,
                data={"protocol_id": protocol_id, "available_protocols": list(self.pools.keys())}
            )
        
        # Check backpressure (if we have backpressure manager)
        if self.backpressure_manager and self.backpressure_manager.should_block_worker(protocol_id):
            logger.warning(f"Blocking task {task_id} due to critical backpressure on {protocol_id}")
            self.system_metrics["routing_failures"] += 1
            return
        
        # Emit TASK_AVAILABLE event using centralized system
        await self._emit_event(EventType.TASK_AVAILABLE, {
            "task_id": task_id,
            "protocol": protocol_id,
            "method": method,
            "params": params,
            "priority": priority,
            "timeout": timeout,
            "routed_by": "centralized_pool_manager"
        }, correlation_id=task_id)
        
        self.system_metrics["total_tasks_routed"] += 1
        
        logger.debug(f"Routed task {task_id} to protocol {protocol_id}")
    
    # Event handlers for centralized events
    
    async def _handle_task_available(self, event: GleitzeitEvent) -> None:
        """Handle TASK_AVAILABLE event - route to appropriate pool"""
        protocol_id = event.data.get("protocol")
        if protocol_id and protocol_id in self.pools:
            pool = self.pools[protocol_id]
            await pool.handle_task_available(event)
    
    async def _handle_worker_idle(self, event: GleitzeitEvent) -> None:
        """Handle worker idle event"""
        # Forward to pools for state tracking
        for pool in self.pools.values():
            await pool.handle_worker_idle(event)
    
    async def _handle_worker_busy(self, event: GleitzeitEvent) -> None:
        """Handle worker busy event"""
        # Forward to pools for state tracking
        for pool in self.pools.values():
            await pool.handle_worker_busy(event)
    
    async def _handle_worker_failed(self, event: GleitzeitEvent) -> None:
        """Handle worker failure event"""
        worker_id = event.data.get("worker_id")
        protocol_id = event.data.get("protocol_id")
        
        # Update system health metrics based on worker failure
        logger.warning(f"Worker {worker_id} failed for protocol {protocol_id}")
        
        # Forward to pools for replacement
        for pool in self.pools.values():
            await pool.handle_worker_failed(event)
        
        # Event-driven health assessment - no polling needed
        await self._assess_system_health_on_failure(protocol_id)
    
    async def _handle_task_completed(self, event: GleitzeitEvent) -> None:
        """Handle task completion event"""
        # Update metrics and forward to pools
        for pool in self.pools.values():
            await pool.handle_task_completed(event)
    
    async def _handle_task_failed(self, event: GleitzeitEvent) -> None:
        """Handle task failure event"""
        # Update metrics and forward to pools
        for pool in self.pools.values():
            await pool.handle_task_failed(event)
    
    async def _handle_task_timeout(self, event: GleitzeitEvent) -> None:
        """Handle task timeout event"""
        # Update metrics and forward to pools
        for pool in self.pools.values():
            await pool.handle_task_timeout(event)
    
    async def _periodic_cleanup(self) -> None:
        """Periodic cleanup of stale data only - not monitoring"""
        while self.running:
            try:
                await asyncio.sleep(300)  # Cleanup every 5 minutes instead of monitoring
                
                # Only cleanup stale data, no monitoring
                if self.backpressure_manager:
                    self.backpressure_manager.cleanup_stale_workers()
                
                logger.debug("PoolManager performed periodic cleanup")
                
            except Exception as e:
                logger.error(f"Cleanup task error: {e}")
    
    async def _assess_system_health_on_failure(self, protocol_id: str) -> None:
        """Assess system health when failures occur - event-driven alternative to polling"""
        try:
            if protocol_id in self.pools:
                pool = self.pools[protocol_id]
                stats = pool.get_stats()
                
                # React to health issues immediately
                if stats["total_workers"] == 0:
                    logger.error(f"Pool {protocol_id} has no workers - critical failure")
                    await self._emit_event(EventType.POOL_HEALTH_CRITICAL, {
                        "protocol_id": protocol_id,
                        "issue": "no_workers",
                        "pool_stats": stats
                    })
                elif stats["utilization"] == 0 and stats["total_workers"] > 0:
                    logger.warning(f"Pool {protocol_id} has idle workers after failure")
                    await self._emit_event(EventType.POOL_HEALTH_WARNING, {
                        "protocol_id": protocol_id,
                        "issue": "all_idle_after_failure",
                        "pool_stats": stats
                    })
        except Exception as e:
            logger.error(f"Health assessment error for {protocol_id}: {e}")
    
    async def _emit_event(self, event_type: EventType, data: Dict[str, Any], correlation_id: Optional[str] = None) -> None:
        """Emit event using centralized system"""
        if self.event_emitter:
            event = GleitzeitEvent(
                event_type=event_type,
                data=data,
                source="centralized_pool_manager",
                timestamp=datetime.utcnow(),
                correlation_id=correlation_id
            )
            await self.event_emitter(event)
    
    # Utility methods for getting information
    
    def get_pool_stats(self, protocol_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific pool"""
        if protocol_id not in self.pools:
            return None
        return self.pools[protocol_id].get_stats()
    
    def get_all_pool_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all pools"""
        return {
            protocol_id: pool.get_stats()
            for protocol_id, pool in self.pools.items()
        }
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Get overall system statistics"""
        total_workers = sum(len(pool.workers) for pool in self.pools.values())
        total_busy = sum(
            len([w for w in pool.worker_states.values() if str(w) == "busy"])
            for pool in self.pools.values()
        )
        
        return {
            "pools": len(self.pools),
            "total_workers": total_workers,
            "busy_workers": total_busy,
            "idle_workers": total_workers - total_busy,
            "system_utilization": total_busy / total_workers if total_workers > 0 else 0,
            "circuit_breaker_stats": self.circuit_breaker.get_all_stats() if self.circuit_breaker else {},
            "backpressure_stats": self.backpressure_manager.get_pool_pressure_stats() if self.backpressure_manager else {},
            **self.system_metrics
        }
    
    def get_available_protocols(self) -> List[str]:
        """Get list of protocols with available pools"""
        return list(self.pools.keys())
    
    def is_protocol_available(self, protocol_id: str) -> bool:
        """Check if a protocol has an available pool"""
        return protocol_id in self.pools
    
    async def scale_pool(self, protocol_id: str, target_size: int) -> bool:
        """Manually scale a pool to target size"""
        if protocol_id not in self.pools:
            return False
        
        # Emit scale request event
        await self._emit_event(EventType.POOL_SCALE_REQUESTED, {
            "pool_id": self.pools[protocol_id].pool_id,
            "target_size": target_size,
            "reason": "manual_scaling"
        })
        
        return True