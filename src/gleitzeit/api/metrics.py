"""
Prometheus metrics collection and reporting.

Provides metrics in Prometheus format for monitoring.
"""

import time
import psutil
from typing import Dict, Any, List
from dataclasses import dataclass, field
from collections import defaultdict
import asyncio
import logging

logger = logging.getLogger(__name__)


@dataclass
class MetricValue:
    """Single metric value with labels."""
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """Collects and formats metrics in Prometheus format."""
    
    def __init__(self):
        self.counters: Dict[str, List[MetricValue]] = defaultdict(list)
        self.gauges: Dict[str, List[MetricValue]] = defaultdict(list)
        self.histograms: Dict[str, List[MetricValue]] = defaultdict(list)
        self.summaries: Dict[str, List[MetricValue]] = defaultdict(list)
        
        # Start time for uptime calculation
        self.start_time = time.time()
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
    
    async def increment_counter(self, name: str, value: float = 1.0, labels: Dict[str, str] = None):
        """Increment a counter metric."""
        async with self._lock:
            metric = MetricValue(value=value, labels=labels or {})
            self.counters[name].append(metric)
    
    async def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """Set a gauge metric."""
        async with self._lock:
            metric = MetricValue(value=value, labels=labels or {})
            # Gauges replace existing values with same labels
            self.gauges[name] = [m for m in self.gauges[name] 
                                 if m.labels != (labels or {})]
            self.gauges[name].append(metric)
    
    async def observe_histogram(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record a histogram observation."""
        async with self._lock:
            metric = MetricValue(value=value, labels=labels or {})
            self.histograms[name].append(metric)
    
    async def collect_system_metrics(self):
        """Collect system-level metrics."""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=0.1)
            await self.set_gauge("process_cpu_usage_percent", cpu_percent)
            
            # Memory usage
            memory = psutil.virtual_memory()
            await self.set_gauge("process_memory_usage_bytes", memory.used)
            await self.set_gauge("process_memory_available_bytes", memory.available)
            await self.set_gauge("process_memory_percent", memory.percent)
            
            # Uptime
            uptime = time.time() - self.start_time
            await self.set_gauge("process_uptime_seconds", uptime)
            
            # Process info
            process = psutil.Process()
            await self.set_gauge("process_threads", process.num_threads())
            await self.set_gauge("process_open_files", len(process.open_files()))
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
    
    async def format_prometheus(self) -> str:
        """Format metrics in Prometheus text format."""
        lines = []
        
        # Collect current system metrics
        await self.collect_system_metrics()
        
        async with self._lock:
            # Format counters
            for name, values in self.counters.items():
                lines.append(f"# HELP {name} Counter metric")
                lines.append(f"# TYPE {name} counter")
                
                # Aggregate by labels
                aggregated = defaultdict(float)
                for metric in values:
                    label_str = self._format_labels(metric.labels)
                    aggregated[label_str] += metric.value
                
                for label_str, value in aggregated.items():
                    lines.append(f"{name}{label_str} {value}")
            
            # Format gauges
            for name, values in self.gauges.items():
                lines.append(f"# HELP {name} Gauge metric")
                lines.append(f"# TYPE {name} gauge")
                
                for metric in values:
                    label_str = self._format_labels(metric.labels)
                    lines.append(f"{name}{label_str} {metric.value}")
            
            # Format histograms (simplified - just count and sum)
            for name, values in self.histograms.items():
                if values:
                    lines.append(f"# HELP {name} Histogram metric")
                    lines.append(f"# TYPE {name} histogram")
                    
                    # Group by labels
                    by_labels = defaultdict(list)
                    for metric in values:
                        label_str = self._format_labels(metric.labels)
                        by_labels[label_str].append(metric.value)
                    
                    for label_str, vals in by_labels.items():
                        count = len(vals)
                        total = sum(vals)
                        lines.append(f"{name}_count{label_str} {count}")
                        lines.append(f"{name}_sum{label_str} {total}")
        
        return "\n".join(lines) + "\n"
    
    def _format_labels(self, labels: Dict[str, str]) -> str:
        """Format labels for Prometheus format."""
        if not labels:
            return ""
        
        label_parts = [f'{k}="{v}"' for k, v in labels.items()]
        return "{" + ",".join(label_parts) + "}"
    
    async def collect_gleitzeit_metrics(self, client):
        """Collect Gleitzeit-specific metrics from the client."""
        try:
            # Get system metrics
            metrics = await client.get_system_metrics()
            
            # Task metrics
            if "tasks" in metrics:
                task_metrics = metrics["tasks"]
                await self.set_gauge("gleitzeit_tasks_pending", 
                                    task_metrics.get("pending", 0))
                await self.set_gauge("gleitzeit_tasks_running", 
                                    task_metrics.get("running", 0))
                await self.set_gauge("gleitzeit_tasks_completed", 
                                    task_metrics.get("completed", 0))
                await self.set_gauge("gleitzeit_tasks_failed", 
                                    task_metrics.get("failed", 0))
            
            # Workflow metrics
            if "workflows" in metrics:
                workflow_metrics = metrics["workflows"]
                await self.set_gauge("gleitzeit_workflows_active", 
                                    workflow_metrics.get("active", 0))
                await self.set_gauge("gleitzeit_workflows_completed", 
                                    workflow_metrics.get("completed", 0))
                await self.set_gauge("gleitzeit_workflows_failed", 
                                    workflow_metrics.get("failed", 0))
            
            # Queue metrics
            if "queues" in metrics:
                queue_metrics = metrics["queues"]
                for queue_name, depth in queue_metrics.items():
                    await self.set_gauge("gleitzeit_queue_depth", depth, 
                                       labels={"queue": queue_name})
            
            # Timer metrics
            if "timers" in metrics:
                timer_metrics = metrics["timers"]
                await self.set_gauge("gleitzeit_timers_pending", 
                                    timer_metrics.get("pending", 0))
                await self.set_gauge("gleitzeit_timers_expired", 
                                    timer_metrics.get("expired", 0))
            
            # Redis metrics
            if "redis" in metrics:
                redis_metrics = metrics["redis"]
                await self.set_gauge("gleitzeit_redis_connected", 
                                    1 if redis_metrics.get("connected") else 0)
                await self.set_gauge("gleitzeit_redis_memory_bytes", 
                                    redis_metrics.get("memory_usage", 0))
                
        except Exception as e:
            logger.error(f"Error collecting Gleitzeit metrics: {e}")


# Global metrics collector instance
metrics_collector = MetricsCollector()