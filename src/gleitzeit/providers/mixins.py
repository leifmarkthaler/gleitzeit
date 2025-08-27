"""
Provider Mixins

Reusable mixins that add automatic features to providers.
Can be combined with any provider class.
"""

import time
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from gleitzeit.core.errors import ProviderNotAvailableError, ProviderError


class CircuitBreakerMixin:
    """
    Circuit breaker mixin that prevents cascading failures.
    
    Automatically opens circuit after too many failures and gives
    the downstream service time to recover.
    
    States:
    - CLOSED: Normal operation
    - OPEN: Circuit is open, requests fail fast
    - HALF_OPEN: Testing if service recovered
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Circuit breaker configuration
        self.circuit_threshold = kwargs.get('circuit_threshold', 5)
        self.circuit_timeout = kwargs.get('circuit_timeout', 60)  # seconds
        self.circuit_half_open_max_calls = kwargs.get('circuit_half_open_max_calls', 3)
        
        # Circuit breaker state
        self.circuit_failure_count = 0
        self.circuit_last_failure_time = None
        self.circuit_state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.circuit_half_open_calls = 0
        
        # Add circuit breaker info to logger
        if hasattr(self, 'logger'):
            self.logger.info(f"Circuit breaker enabled: threshold={self.circuit_threshold}, timeout={self.circuit_timeout}s")
    
    async def handle_request_with_circuit_breaker(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Wrap request handling with circuit breaker logic.
        
        This should be called instead of handle_request() when using the circuit breaker.
        """
        # Check circuit state before proceeding
        await self._check_circuit_state()
        
        try:
            # Execute the actual request
            result = await super().handle_request(method, params)
            
            # Success - reset failure count and close circuit if half-open
            self._record_success()
            
            return result
            
        except Exception as e:
            # Failure - record and potentially open circuit
            self._record_failure()
            raise
    
    async def _check_circuit_state(self):
        """Check and update circuit breaker state before request"""
        current_time = time.time()
        
        if self.circuit_state == "OPEN":
            # Check if we should transition to half-open
            if (self.circuit_last_failure_time and 
                current_time - self.circuit_last_failure_time > self.circuit_timeout):
                
                self.circuit_state = "HALF_OPEN"
                self.circuit_half_open_calls = 0
                
                if hasattr(self, 'logger'):
                    self.logger.info("Circuit breaker: OPEN -> HALF_OPEN (testing recovery)")
            else:
                # Circuit is still open - fail fast
                raise ProviderNotAvailableError(
                    f"Circuit breaker is OPEN for {self.provider_id}. "
                    f"Will retry in {self.circuit_timeout - (current_time - self.circuit_last_failure_time):.0f}s"
                )
        
        elif self.circuit_state == "HALF_OPEN":
            # Check if we've exceeded half-open call limit
            if self.circuit_half_open_calls >= self.circuit_half_open_max_calls:
                self.circuit_state = "OPEN"
                self.circuit_last_failure_time = current_time
                
                if hasattr(self, 'logger'):
                    self.logger.warning("Circuit breaker: HALF_OPEN -> OPEN (too many test calls)")
                
                raise ProviderNotAvailableError(
                    f"Circuit breaker is OPEN for {self.provider_id} (half-open limit exceeded)"
                )
            
            self.circuit_half_open_calls += 1
    
    def _record_success(self):
        """Record successful request"""
        if self.circuit_state == "HALF_OPEN":
            # Transition back to closed on success
            self.circuit_state = "CLOSED"
            self.circuit_failure_count = 0
            self.circuit_half_open_calls = 0
            
            if hasattr(self, 'logger'):
                self.logger.info("Circuit breaker: HALF_OPEN -> CLOSED (service recovered)")
        
        elif self.circuit_state == "CLOSED":
            # Reset failure count on success
            self.circuit_failure_count = 0
    
    def _record_failure(self):
        """Record failed request and potentially open circuit"""
        self.circuit_failure_count += 1
        self.circuit_last_failure_time = time.time()
        
        if (self.circuit_state == "CLOSED" and 
            self.circuit_failure_count >= self.circuit_threshold):
            
            # Open the circuit
            self.circuit_state = "OPEN"
            
            if hasattr(self, 'logger'):
                self.logger.warning(
                    f"Circuit breaker: CLOSED -> OPEN "
                    f"({self.circuit_failure_count} failures >= {self.circuit_threshold} threshold)"
                )
        
        elif self.circuit_state == "HALF_OPEN":
            # Failed during half-open - back to open
            self.circuit_state = "OPEN"
            
            if hasattr(self, 'logger'):
                self.logger.warning("Circuit breaker: HALF_OPEN -> OPEN (test call failed)")
    
    def get_circuit_breaker_info(self) -> Dict[str, Any]:
        """Get current circuit breaker status"""
        current_time = time.time()
        
        info = {
            "state": self.circuit_state,
            "failure_count": self.circuit_failure_count,
            "threshold": self.circuit_threshold,
            "timeout_seconds": self.circuit_timeout,
        }
        
        if self.circuit_last_failure_time:
            info.update({
                "last_failure": datetime.fromtimestamp(self.circuit_last_failure_time).isoformat(),
                "seconds_since_failure": current_time - self.circuit_last_failure_time
            })
            
            if self.circuit_state == "OPEN":
                remaining = self.circuit_timeout - (current_time - self.circuit_last_failure_time)
                info["retry_in_seconds"] = max(0, remaining)
        
        if self.circuit_state == "HALF_OPEN":
            info.update({
                "half_open_calls": self.circuit_half_open_calls,
                "half_open_max_calls": self.circuit_half_open_max_calls
            })
        
        return info


class RateLimitMixin:
    """
    Rate limiting mixin to prevent overwhelming downstream services.
    
    Implements token bucket algorithm for smooth rate limiting.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Rate limit configuration
        self.rate_limit_requests_per_second = kwargs.get('rate_limit_rps', None)
        self.rate_limit_burst_size = kwargs.get('rate_limit_burst', None)
        
        if self.rate_limit_requests_per_second:
            # Token bucket state
            self.rate_limit_tokens = self.rate_limit_burst_size or self.rate_limit_requests_per_second
            self.rate_limit_last_update = time.time()
            self.rate_limit_max_tokens = self.rate_limit_burst_size or self.rate_limit_requests_per_second
            
            if hasattr(self, 'logger'):
                self.logger.info(
                    f"Rate limiting enabled: {self.rate_limit_requests_per_second} rps, "
                    f"burst={self.rate_limit_max_tokens}"
                )
    
    async def handle_request_with_rate_limit(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Wrap request handling with rate limiting.
        """
        if self.rate_limit_requests_per_second:
            await self._enforce_rate_limit()
        
        return await super().handle_request(method, params)
    
    async def _enforce_rate_limit(self):
        """Enforce rate limiting using token bucket algorithm"""
        current_time = time.time()
        time_passed = current_time - self.rate_limit_last_update
        
        # Add tokens based on time passed
        tokens_to_add = time_passed * self.rate_limit_requests_per_second
        self.rate_limit_tokens = min(
            self.rate_limit_max_tokens,
            self.rate_limit_tokens + tokens_to_add
        )
        self.rate_limit_last_update = current_time
        
        # Check if we have tokens available
        if self.rate_limit_tokens < 1:
            # Calculate wait time
            wait_time = (1 - self.rate_limit_tokens) / self.rate_limit_requests_per_second
            
            if hasattr(self, 'logger'):
                self.logger.warning(f"Rate limit exceeded, waiting {wait_time:.2f}s")
            
            await asyncio.sleep(wait_time)
            
            # Update tokens after waiting
            self.rate_limit_tokens = 1
        
        # Consume one token
        self.rate_limit_tokens -= 1
    
    def get_rate_limit_info(self) -> Dict[str, Any]:
        """Get current rate limiting status"""
        if not self.rate_limit_requests_per_second:
            return {"enabled": False}
        
        return {
            "enabled": True,
            "requests_per_second": self.rate_limit_requests_per_second,
            "burst_size": self.rate_limit_max_tokens,
            "available_tokens": self.rate_limit_tokens,
            "tokens_per_second": self.rate_limit_requests_per_second
        }


class HealthMonitorMixin:
    """
    Enhanced health monitoring with automatic degraded state detection.
    
    Tracks health check success rate and automatically marks provider
    as degraded if health checks start failing.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Health monitoring configuration
        self.health_check_interval = kwargs.get('health_check_interval', 30)  # seconds
        self.health_failure_threshold = kwargs.get('health_failure_threshold', 3)
        
        # Health monitoring state
        self.health_check_failures = 0
        self.health_last_check = None
        self.health_status = "healthy"  # healthy, degraded, unhealthy
        self.health_check_history = []
        
        # Start background health monitoring
        if hasattr(self, 'logger'):
            self.logger.info(
                f"Health monitoring enabled: interval={self.health_check_interval}s, "
                f"failure_threshold={self.health_failure_threshold}"
            )
    
    async def start_health_monitoring(self):
        """Start background health monitoring task"""
        asyncio.create_task(self._health_monitor_loop())
    
    async def _health_monitor_loop(self):
        """Background task that periodically checks health"""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                
                # Perform health check
                is_healthy = await super().health_check()
                current_time = datetime.utcnow()
                
                # Record result
                self.health_check_history.append({
                    "timestamp": current_time.isoformat(),
                    "healthy": is_healthy
                })
                
                # Keep only recent history (last 100 checks)
                if len(self.health_check_history) > 100:
                    self.health_check_history = self.health_check_history[-100:]
                
                self.health_last_check = current_time
                
                if is_healthy:
                    # Reset failure count on success
                    if self.health_check_failures > 0:
                        self.health_check_failures = 0
                        
                        # Transition back to healthy if we were degraded
                        if self.health_status != "healthy":
                            old_status = self.health_status
                            self.health_status = "healthy"
                            
                            if hasattr(self, 'logger'):
                                self.logger.info(f"Health status: {old_status} -> healthy")
                else:
                    # Increment failure count
                    self.health_check_failures += 1
                    
                    # Update status based on failure count
                    if self.health_check_failures >= self.health_failure_threshold:
                        if self.health_status != "unhealthy":
                            old_status = self.health_status
                            self.health_status = "unhealthy"
                            
                            if hasattr(self, 'logger'):
                                self.logger.error(
                                    f"Health status: {old_status} -> unhealthy "
                                    f"({self.health_check_failures} consecutive failures)"
                                )
                    elif self.health_check_failures >= 1:
                        if self.health_status == "healthy":
                            self.health_status = "degraded"
                            
                            if hasattr(self, 'logger'):
                                self.logger.warning("Health status: healthy -> degraded")
                
            except Exception as e:
                if hasattr(self, 'logger'):
                    self.logger.error(f"Error in health monitoring: {e}")
    
    def get_health_info(self) -> Dict[str, Any]:
        """Get comprehensive health information"""
        # Calculate success rate from recent history
        success_rate = 100.0
        if self.health_check_history:
            successful_checks = sum(1 for check in self.health_check_history if check["healthy"])
            success_rate = (successful_checks / len(self.health_check_history)) * 100
        
        return {
            "status": self.health_status,
            "consecutive_failures": self.health_check_failures,
            "failure_threshold": self.health_failure_threshold,
            "last_check": self.health_last_check.isoformat() if self.health_last_check else None,
            "check_interval_seconds": self.health_check_interval,
            "success_rate_percent": success_rate,
            "total_checks": len(self.health_check_history)
        }


class ComprehensiveProvider:
    """
    Example of how to combine all mixins for a fully-featured provider.
    
    This is not a base class, but an example showing how mixins can be combined.
    """
    pass


# Usage examples:
"""
# Circuit breaker only
class MyProvider(CircuitBreakerMixin, SimpleProvider):
    async def execute(self, method, **params):
        return {"result": "data"}
    
    async def handle_request(self, method, params):
        return await self.handle_request_with_circuit_breaker(method, params)


# All features combined  
class AdvancedProvider(CircuitBreakerMixin, RateLimitMixin, HealthMonitorMixin, SimpleProvider):
    def __init__(self, **kwargs):
        super().__init__(
            circuit_threshold=5,
            rate_limit_rps=10,
            health_check_interval=30,
            **kwargs
        )
    
    async def handle_request(self, method, params):
        # Apply all mixins in order
        return await self.handle_request_with_rate_limit(method, params)
    
    async def initialize(self):
        await super().initialize()
        await self.start_health_monitoring()
"""