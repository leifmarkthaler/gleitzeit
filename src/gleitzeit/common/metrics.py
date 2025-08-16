"""
Unified metrics collection for resources
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
import statistics


@dataclass
class ResourceMetrics:
    """
    Unified metrics for any resource (Ollama instance, Docker container, etc.)
    """
    # Request metrics
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    active_requests: int = 0
    
    # Performance metrics
    response_times: deque = field(default_factory=lambda: deque(maxlen=100))
    
    # Error tracking
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    consecutive_errors: int = 0
    
    # Success tracking
    last_success_time: Optional[datetime] = None
    consecutive_successes: int = 0
    
    # Resource-specific metrics
    custom_metrics: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def avg_response_time(self) -> float:
        """Calculate average response time (ms)"""
        if not self.response_times:
            return 0.0
        return statistics.mean(self.response_times)
    
    @property
    def median_response_time(self) -> float:
        """Calculate median response time (ms)"""
        if not self.response_times:
            return 0.0
        return statistics.median(self.response_times)
    
    @property
    def p95_response_time(self) -> float:
        """Calculate 95th percentile response time (ms)"""
        if not self.response_times:
            return 0.0
        sorted_times = sorted(self.response_times)
        index = int(len(sorted_times) * 0.95)
        return sorted_times[min(index, len(sorted_times) - 1)]
    
    @property
    def p99_response_time(self) -> float:
        """Calculate 99th percentile response time (ms)"""
        if not self.response_times:
            return 0.0
        sorted_times = sorted(self.response_times)
        index = int(len(sorted_times) * 0.99)
        return sorted_times[min(index, len(sorted_times) - 1)]
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_requests == 0:
            return 100.0
        return (self.successful_requests / self.total_requests) * 100
    
    @property
    def error_rate(self) -> float:
        """Calculate error rate percentage"""
        if self.total_requests == 0:
            return 0.0
        return (self.failed_requests / self.total_requests) * 100
    
    @property
    def availability(self) -> float:
        """Calculate availability percentage"""
        return self.success_rate
    
    def record_request_start(self):
        """Record start of a request"""
        self.total_requests += 1
        self.active_requests += 1
    
    def record_request_end(
        self,
        success: bool,
        response_time_ms: Optional[float] = None,
        error: Optional[str] = None
    ):
        """Record end of a request"""
        self.active_requests = max(0, self.active_requests - 1)
        
        if success:
            self.successful_requests += 1
            self.consecutive_successes += 1
            self.consecutive_errors = 0
            self.last_success_time = datetime.now()
            
            if response_time_ms is not None:
                self.response_times.append(response_time_ms)
        else:
            self.failed_requests += 1
            self.consecutive_errors += 1
            self.consecutive_successes = 0
            self.last_error = error
            self.last_error_time = datetime.now()
    
    def add_custom_metric(self, name: str, value: Any):
        """Add custom metric"""
        self.custom_metrics[name] = value
    
    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary"""
        return {
            'total_requests': self.total_requests,
            'successful_requests': self.successful_requests,
            'failed_requests': self.failed_requests,
            'active_requests': self.active_requests,
            'success_rate': round(self.success_rate, 2),
            'error_rate': round(self.error_rate, 2),
            'avg_response_time_ms': round(self.avg_response_time, 2),
            'median_response_time_ms': round(self.median_response_time, 2),
            'p95_response_time_ms': round(self.p95_response_time, 2),
            'p99_response_time_ms': round(self.p99_response_time, 2),
            'consecutive_errors': self.consecutive_errors,
            'consecutive_successes': self.consecutive_successes,
            'last_error': self.last_error,
            'last_error_time': self.last_error_time.isoformat() if self.last_error_time else None,
            'last_success_time': self.last_success_time.isoformat() if self.last_success_time else None,
            'custom_metrics': self.custom_metrics
        }
    
    def reset(self):
        """Reset all metrics"""
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.active_requests = 0
        self.response_times.clear()
        self.last_error = None
        self.last_error_time = None
        self.consecutive_errors = 0
        self.last_success_time = None
        self.consecutive_successes = 0
        self.custom_metrics.clear()


class MetricsCollector:
    """
    Collects and aggregates metrics from multiple resources
    """
    
    def __init__(self):
        self.resource_metrics: Dict[str, ResourceMetrics] = {}
    
    def get_or_create(self, resource_id: str) -> ResourceMetrics:
        """Get or create metrics for resource"""
        if resource_id not in self.resource_metrics:
            self.resource_metrics[resource_id] = ResourceMetrics()
        return self.resource_metrics[resource_id]
    
    def record_request_start(self, resource_id: str):
        """Record start of request for resource"""
        metrics = self.get_or_create(resource_id)
        metrics.record_request_start()
    
    def record_request_end(
        self,
        resource_id: str,
        success: bool,
        response_time_ms: Optional[float] = None,
        error: Optional[str] = None
    ):
        """Record end of request for resource"""
        metrics = self.get_or_create(resource_id)
        metrics.record_request_end(success, response_time_ms, error)
    
    def get_summary(self, resource_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get metrics summary
        
        Args:
            resource_id: Specific resource or None for all
            
        Returns:
            Metrics summary
        """
        if resource_id:
            metrics = self.resource_metrics.get(resource_id)
            return metrics.get_summary() if metrics else {}
        
        # Aggregate metrics for all resources
        total_metrics = {
            'resources': {},
            'aggregate': {
                'total_requests': 0,
                'successful_requests': 0,
                'failed_requests': 0,
                'active_requests': 0,
                'avg_success_rate': 0.0,
                'avg_response_time_ms': 0.0
            }
        }
        
        response_times = []
        success_rates = []
        
        for res_id, metrics in self.resource_metrics.items():
            summary = metrics.get_summary()
            total_metrics['resources'][res_id] = summary
            
            # Aggregate
            total_metrics['aggregate']['total_requests'] += summary['total_requests']
            total_metrics['aggregate']['successful_requests'] += summary['successful_requests']
            total_metrics['aggregate']['failed_requests'] += summary['failed_requests']
            total_metrics['aggregate']['active_requests'] += summary['active_requests']
            
            if summary['total_requests'] > 0:
                success_rates.append(summary['success_rate'])
                response_times.extend(list(metrics.response_times))
        
        # Calculate averages
        if success_rates:
            total_metrics['aggregate']['avg_success_rate'] = round(
                statistics.mean(success_rates), 2
            )
        
        if response_times:
            total_metrics['aggregate']['avg_response_time_ms'] = round(
                statistics.mean(response_times), 2
            )
        
        return total_metrics
    
    def reset(self, resource_id: Optional[str] = None):
        """
        Reset metrics
        
        Args:
            resource_id: Specific resource or None for all
        """
        if resource_id:
            if resource_id in self.resource_metrics:
                self.resource_metrics[resource_id].reset()
        else:
            for metrics in self.resource_metrics.values():
                metrics.reset()
    
    def remove_resource(self, resource_id: str):
        """Remove metrics for resource"""
        if resource_id in self.resource_metrics:
            del self.resource_metrics[resource_id]