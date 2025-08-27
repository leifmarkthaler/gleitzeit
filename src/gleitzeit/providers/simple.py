"""
Simple Provider Base Class

Simplified provider that handles all boilerplate automatically.
Users only need to implement the execute() method.
"""

import asyncio
import time
import uuid
from abc import abstractmethod
from typing import Dict, Any, Optional, List, Union
from datetime import datetime

from .base import ProtocolProvider
from gleitzeit.core.errors import is_retryable_error, ProviderError, ErrorCode


class SimpleProvider(ProtocolProvider):
    """
    Simplified provider base class that handles boilerplate automatically.
    
    Users only need to implement the execute() method. All other methods
    (initialize, shutdown, health_check) have sensible defaults.
    
    Features included automatically:
    - Smart retry logic with exponential backoff
    - Enhanced structured logging
    - Basic metrics collection
    - Error classification and handling
    
    Example:
        class WeatherProvider(SimpleProvider):
            async def execute(self, method: str, **params):
                if method == "get_weather":
                    return {"temp": 20, "city": params.get("city", "London")}
    """
    
    def __init__(
        self,
        provider_id: Optional[str] = None,
        protocol_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        version: str = "1.0.0",
        max_retries: int = 3,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        **kwargs
    ):
        # Auto-generate IDs if not provided
        if not provider_id:
            provider_id = self.__class__.__name__.lower()
            if provider_id.endswith('provider'):
                provider_id = provider_id[:-8]  # Remove 'provider' suffix
        
        if not protocol_id:
            protocol_id = f"{provider_id}/v1"
        
        if not name:
            name = f"{provider_id.title()} Provider"
        
        if not description:
            description = f"Simplified provider for {protocol_id}"
        
        super().__init__(
            provider_id=provider_id,
            protocol_id=protocol_id,
            name=name,
            description=description,
            version=version,
            **kwargs
        )
        
        # Retry configuration
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_backoff = retry_backoff
        
        # Enhanced metrics
        self.latencies = []
        self.method_counts = {}
        self.last_request_time = None
        
    async def initialize(self) -> None:
        """
        Default initialization - override only if needed.
        
        The default implementation does nothing, making initialization optional.
        """
        pass
    
    async def shutdown(self) -> None:
        """
        Default shutdown - override only if needed.
        
        The default implementation does nothing, making cleanup optional.
        """
        pass
    
    async def health_check(self) -> bool:
        """
        Default health check - override only if needed.
        
        The default implementation always returns True.
        Override to implement custom health checking logic.
        """
        return True
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Enhanced request handler with automatic retry, logging, and metrics.
        
        This method wraps the user's execute() method with:
        - Automatic retry logic using exponential backoff
        - Error classification (retryable vs non-retryable)
        - Request timing and metrics collection
        - Enhanced structured logging
        
        Args:
            method: The method name to execute
            params: Method parameters
            
        Returns:
            The result from the user's execute() method
            
        Raises:
            Exception: Re-raises the last exception if all retries fail
        """
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        # Enhanced logging - start
        self.logger.info(
            f"[{request_id}] Starting {method}",
            extra={
                'request_id': request_id,
                'method': method,
                'provider_id': self.provider_id,
                'params_count': len(params),
                'timestamp': datetime.utcnow().isoformat()
            }
        )
        
        # Update method counts
        self.method_counts[method] = self.method_counts.get(method, 0) + 1
        
        # Retry logic with exponential backoff
        last_error = None
        for attempt in range(self.max_retries):
            try:
                # Call user's execute method
                result = await self.execute(method, **params)
                
                # Success metrics
                duration = time.time() - start_time
                self.latencies.append(duration)
                self.last_request_time = datetime.utcnow()
                
                # Enhanced logging - success
                self.logger.info(
                    f"[{request_id}] Success {method} in {duration:.3f}s",
                    extra={
                        'request_id': request_id,
                        'method': method,
                        'duration_ms': duration * 1000,
                        'attempt': attempt + 1,
                        'success': True,
                        'result_size': len(str(result)) if result else 0
                    }
                )
                
                return result
                
            except Exception as e:
                last_error = e
                duration = time.time() - start_time
                
                # Check if error is retryable
                is_retryable = is_retryable_error(e)
                is_final_attempt = (attempt == self.max_retries - 1)
                
                # Enhanced logging - error
                log_level = 'error' if is_final_attempt else 'warning'
                getattr(self.logger, log_level)(
                    f"[{request_id}] {'Final ' if is_final_attempt else ''}Attempt {attempt + 1} failed: {e}",
                    extra={
                        'request_id': request_id,
                        'method': method,
                        'duration_ms': duration * 1000,
                        'attempt': attempt + 1,
                        'success': False,
                        'error_type': e.__class__.__name__,
                        'error_message': str(e),
                        'retryable': is_retryable,
                        'final_attempt': is_final_attempt
                    }
                )
                
                # Don't retry if not retryable or final attempt
                if not is_retryable or is_final_attempt:
                    self.error_count += 1
                    raise
                
                # Calculate delay with exponential backoff
                delay = self.retry_delay * (self.retry_backoff ** attempt)
                
                self.logger.info(
                    f"[{request_id}] Retrying in {delay:.1f}s...",
                    extra={
                        'request_id': request_id,
                        'retry_delay': delay,
                        'next_attempt': attempt + 2
                    }
                )
                
                await asyncio.sleep(delay)
        
        # Should never reach here due to the logic above, but just in case
        self.error_count += 1
        raise last_error
    
    @abstractmethod
    async def execute(self, method: str, **params) -> Any:
        """
        Simplified method that users implement.
        
        This is the only method users need to implement. All the complexity
        of provider lifecycle, error handling, retries, and logging is
        handled automatically by the base class.
        
        Args:
            method: The method name being called
            **params: Method parameters as keyword arguments
            
        Returns:
            The result of the method execution (must be JSON serializable)
            
        Example:
            async def execute(self, method: str, **params):
                if method == "get_weather":
                    city = params.get("city", "London")
                    return {"temperature": 20, "city": city}
                elif method == "get_forecast":
                    return {"forecast": "sunny", "days": 7}
                else:
                    raise ValueError(f"Unknown method: {method}")
        """
        pass
    
    def get_enhanced_metrics(self) -> Dict[str, Any]:
        """
        Get enhanced metrics including latency percentiles and method breakdown.
        
        Returns:
            Dictionary with comprehensive provider metrics
        """
        import statistics
        
        base_metrics = self.get_provider_info()
        
        # Calculate latency statistics
        latency_stats = {}
        if self.latencies:
            latency_stats = {
                "mean_ms": statistics.mean(self.latencies) * 1000,
                "median_ms": statistics.median(self.latencies) * 1000,
                "min_ms": min(self.latencies) * 1000,
                "max_ms": max(self.latencies) * 1000,
            }
            
            # Calculate percentiles if we have enough data
            if len(self.latencies) >= 10:
                sorted_latencies = sorted(self.latencies)
                latency_stats.update({
                    "p95_ms": sorted_latencies[int(len(sorted_latencies) * 0.95)] * 1000,
                    "p99_ms": sorted_latencies[int(len(sorted_latencies) * 0.99)] * 1000,
                })
        
        # Enhanced metrics
        enhanced_metrics = {
            **base_metrics,
            "latency": latency_stats,
            "method_breakdown": dict(self.method_counts),
            "last_request": self.last_request_time.isoformat() if self.last_request_time else None,
            "total_latency_samples": len(self.latencies),
            "provider_type": "SimpleProvider",
            "features": [
                "automatic_retry",
                "enhanced_logging", 
                "metrics_collection",
                "error_classification"
            ]
        }
        
        return enhanced_metrics
    
    def get_supported_methods(self) -> List[str]:
        """
        Default implementation returns empty list.
        Override to specify supported methods for better documentation.
        
        Example:
            def get_supported_methods(self):
                return ["get_weather", "get_forecast"]
        """
        return []