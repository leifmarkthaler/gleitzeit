"""
Monitoring and statistics mixin for Gleitzeit client.
"""

from typing import Any, Dict, Optional
from datetime import datetime


class MonitoringMixin:
    """Mixin providing monitoring and statistics operations."""
    
    async def get_detailed_task_statistics(self, 
                                          start_time: Optional[datetime] = None,
                                          end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get detailed task execution statistics with time range.
        
        Args:
            start_time: Optional start time for statistics
            end_time: Optional end time for statistics
            
        Returns:
            Task statistics including counts, durations, success rates
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_detailed_task_statistics(start_time, end_time)
    
    async def get_detailed_workflow_statistics(self, 
                                              start_time: Optional[datetime] = None,
                                              end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get detailed workflow execution statistics with time range.
        
        Args:
            start_time: Optional start time for statistics
            end_time: Optional end time for statistics
            
        Returns:
            Workflow statistics including counts, durations, success rates
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_detailed_workflow_statistics(start_time, end_time)
    
    async def get_system_statistics(self) -> Dict[str, Any]:
        """
        Get system-wide statistics.
        
        Returns:
            System statistics including uptime, throughput, resource usage
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_system_statistics()
    
    async def get_resource_limits(self) -> Dict[str, Any]:
        """
        Get resource limits configuration.
        
        Returns:
            Dictionary with resource limits (CPU, memory, disk, etc.)
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_resource_limits()
    
    async def get_resource_usage(self) -> Dict[str, Any]:
        """
        Get current resource usage.
        
        Returns:
            Dictionary with current resource usage metrics
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_resource_usage()
    
    async def get_event_stream(self, 
                              filter: Optional[str] = None,
                              follow: bool = False) -> Dict[str, Any]:
        """
        Get event stream for real-time monitoring.
        
        Args:
            filter: Optional event type filter
            follow: Whether to follow the stream in real-time
            
        Returns:
            Event stream data
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_event_stream(filter, follow)
    
    async def get_provider_details(self, provider_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a provider.
        
        Args:
            provider_id: Provider ID
            
        Returns:
            Provider details including capabilities and status
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_provider_details(provider_id)
    
    async def check_provider_health(self, provider_id: str) -> Dict[str, Any]:
        """
        Check health status of a provider.
        
        Args:
            provider_id: Provider ID
            
        Returns:
            Health check results
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.check_provider_health(provider_id)
    
    async def get_performance_metrics(self,
                                     component: Optional[str] = None,
                                     start_time: Optional[datetime] = None,
                                     end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get performance metrics for system components.
        
        Args:
            component: Optional component filter (api, worker, scheduler, etc.)
            start_time: Optional start time
            end_time: Optional end time
            
        Returns:
            Performance metrics including latency, throughput, error rates
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_performance_metrics(component, start_time, end_time)
    
    async def get_queue_metrics(self) -> Dict[str, Any]:
        """
        Get detailed queue metrics.
        
        Returns:
            Queue metrics including sizes, processing rates, wait times
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_queue_metrics()