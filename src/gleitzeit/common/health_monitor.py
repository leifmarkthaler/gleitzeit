"""
Generic health monitoring for resources
"""
from typing import Dict, Any, Optional, Callable, List, Protocol
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import asyncio
import logging

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check"""
    status: HealthStatus
    message: Optional[str] = None
    details: Dict[str, Any] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.details is None:
            self.details = {}


class HealthCheck(Protocol):
    """Protocol for health check implementations"""
    
    async def check(self, resource_id: str, **kwargs) -> HealthCheckResult:
        """Perform health check on resource"""
        ...


class HTTPHealthCheck:
    """HTTP-based health check"""
    
    def __init__(self, endpoint: str = "/health", timeout: int = 5):
        self.endpoint = endpoint
        self.timeout = timeout
    
    async def check(self, resource_id: str, base_url: str) -> HealthCheckResult:
        """Check health via HTTP endpoint"""
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{base_url}{self.endpoint}"
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status == 200:
                        return HealthCheckResult(
                            status=HealthStatus.HEALTHY,
                            message="HTTP health check passed",
                            details={"status_code": response.status}
                        )
                    else:
                        return HealthCheckResult(
                            status=HealthStatus.UNHEALTHY,
                            message=f"HTTP health check failed with status {response.status}",
                            details={"status_code": response.status}
                        )
        except asyncio.TimeoutError:
            return HealthCheckResult(
                status=HealthStatus.DEGRADED,
                message="Health check timeout",
                details={"timeout": self.timeout}
            )
        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Health check error: {str(e)}",
                details={"error": str(e)}
            )


class HealthMonitor:
    """
    Monitors health of multiple resources
    """
    
    def __init__(
        self,
        check_interval: int = 30,
        unhealthy_threshold: int = 3,
        degraded_threshold: int = 2
    ):
        """
        Initialize health monitor
        
        Args:
            check_interval: Seconds between health checks
            unhealthy_threshold: Consecutive failures before marking unhealthy
            degraded_threshold: Consecutive issues before marking degraded
        """
        self.check_interval = check_interval
        self.unhealthy_threshold = unhealthy_threshold
        self.degraded_threshold = degraded_threshold
        
        # Resource tracking
        self.resources: Dict[str, Dict[str, Any]] = {}
        self.health_checks: Dict[str, HealthCheck] = {}
        self.health_history: Dict[str, List[HealthCheckResult]] = {}
        
        # Monitoring task
        self.monitor_task: Optional[asyncio.Task] = None
        self.is_running = False
    
    def register_resource(
        self,
        resource_id: str,
        health_check: HealthCheck,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Register a resource for health monitoring"""
        self.resources[resource_id] = {
            'metadata': metadata or {},
            'consecutive_failures': 0,
            'consecutive_degraded': 0,
            'last_check': None,
            'current_status': HealthStatus.UNKNOWN
        }
        self.health_checks[resource_id] = health_check
        self.health_history[resource_id] = []
        
        logger.info(f"Registered resource {resource_id} for health monitoring")
    
    def unregister_resource(self, resource_id: str):
        """Unregister a resource from health monitoring"""
        if resource_id in self.resources:
            del self.resources[resource_id]
            del self.health_checks[resource_id]
            del self.health_history[resource_id]
            logger.info(f"Unregistered resource {resource_id}")
    
    async def check_health(self, resource_id: str) -> HealthCheckResult:
        """
        Perform health check on specific resource
        
        Args:
            resource_id: Resource to check
            
        Returns:
            Health check result
        """
        if resource_id not in self.resources:
            return HealthCheckResult(
                status=HealthStatus.UNKNOWN,
                message="Resource not registered"
            )
        
        resource = self.resources[resource_id]
        health_check = self.health_checks[resource_id]
        
        try:
            # Perform health check
            result = await health_check.check(
                resource_id,
                **resource['metadata']
            )
            
            # Update tracking
            self._update_health_status(resource_id, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Health check failed for {resource_id}: {e}")
            result = HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Health check exception: {str(e)}"
            )
            self._update_health_status(resource_id, result)
            return result
    
    async def check_all(self) -> Dict[str, HealthCheckResult]:
        """
        Check health of all registered resources
        
        Returns:
            Dict of resource_id -> HealthCheckResult
        """
        tasks = [
            self.check_health(resource_id)
            for resource_id in self.resources.keys()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            resource_id: (
                result if isinstance(result, HealthCheckResult)
                else HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed: {str(result)}"
                )
            )
            for resource_id, result in zip(self.resources.keys(), results)
        }
    
    def get_status(self, resource_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get health status
        
        Args:
            resource_id: Specific resource or None for all
            
        Returns:
            Health status information
        """
        if resource_id:
            if resource_id not in self.resources:
                return {"error": "Resource not found"}
            
            resource = self.resources[resource_id]
            history = self.health_history[resource_id]
            
            return {
                'resource_id': resource_id,
                'status': resource['current_status'].value,
                'last_check': resource['last_check'].isoformat() if resource['last_check'] else None,
                'consecutive_failures': resource['consecutive_failures'],
                'consecutive_degraded': resource['consecutive_degraded'],
                'history': [
                    {
                        'status': h.status.value,
                        'message': h.message,
                        'timestamp': h.timestamp.isoformat()
                    }
                    for h in history[-10:]  # Last 10 checks
                ]
            }
        
        # Return status for all resources
        return {
            'total_resources': len(self.resources),
            'healthy': sum(
                1 for r in self.resources.values()
                if r['current_status'] == HealthStatus.HEALTHY
            ),
            'degraded': sum(
                1 for r in self.resources.values()
                if r['current_status'] == HealthStatus.DEGRADED
            ),
            'unhealthy': sum(
                1 for r in self.resources.values()
                if r['current_status'] == HealthStatus.UNHEALTHY
            ),
            'unknown': sum(
                1 for r in self.resources.values()
                if r['current_status'] == HealthStatus.UNKNOWN
            ),
            'resources': {
                res_id: {
                    'status': res['current_status'].value,
                    'last_check': res['last_check'].isoformat() if res['last_check'] else None
                }
                for res_id, res in self.resources.items()
            }
        }
    
    def get_healthy_resources(self) -> List[str]:
        """Get list of healthy resource IDs"""
        return [
            res_id for res_id, res in self.resources.items()
            if res['current_status'] == HealthStatus.HEALTHY
        ]
    
    def get_unhealthy_resources(self) -> List[str]:
        """Get list of unhealthy resource IDs"""
        return [
            res_id for res_id, res in self.resources.items()
            if res['current_status'] == HealthStatus.UNHEALTHY
        ]
    
    async def start_monitoring(self):
        """Start continuous health monitoring"""
        if self.is_running:
            logger.warning("Health monitoring already running")
            return
        
        self.is_running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Started health monitoring")
    
    async def stop_monitoring(self):
        """Stop health monitoring"""
        self.is_running = False
        
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
            self.monitor_task = None
        
        logger.info("Stopped health monitoring")
    
    # Private methods
    
    def _update_health_status(self, resource_id: str, result: HealthCheckResult):
        """Update health status based on check result"""
        resource = self.resources[resource_id]
        
        # Add to history
        history = self.health_history[resource_id]
        history.append(result)
        
        # Keep only last 100 results
        if len(history) > 100:
            self.health_history[resource_id] = history[-100:]
        
        # Update last check time
        resource['last_check'] = result.timestamp
        
        # Update consecutive counters
        if result.status == HealthStatus.HEALTHY:
            resource['consecutive_failures'] = 0
            resource['consecutive_degraded'] = 0
            resource['current_status'] = HealthStatus.HEALTHY
            
        elif result.status == HealthStatus.DEGRADED:
            resource['consecutive_degraded'] += 1
            resource['consecutive_failures'] = 0
            
            # Check if should mark as degraded
            if resource['consecutive_degraded'] >= self.degraded_threshold:
                resource['current_status'] = HealthStatus.DEGRADED
                
        elif result.status == HealthStatus.UNHEALTHY:
            resource['consecutive_failures'] += 1
            resource['consecutive_degraded'] = 0
            
            # Check if should mark as unhealthy
            if resource['consecutive_failures'] >= self.unhealthy_threshold:
                resource['current_status'] = HealthStatus.UNHEALTHY
    
    async def _monitor_loop(self):
        """Continuous monitoring loop"""
        while self.is_running:
            try:
                # Check all resources
                await self.check_all()
                
                # Log summary
                status = self.get_status()
                logger.debug(
                    f"Health check complete: "
                    f"{status['healthy']}/{status['total_resources']} healthy"
                )
                
                # Wait for next check
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}")
                await asyncio.sleep(5)  # Brief pause on error