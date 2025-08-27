"""
Queue management mixin for Gleitzeit client.
"""

from typing import Any, Dict, Optional


class QueueMixin:
    """Mixin providing queue management operations."""
    
    async def get_queues(self) -> Dict[str, Any]:
        """
        Get all available queues.
        
        Returns:
            Dictionary with queue information
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_queues()
    
    async def get_queue_details(self, queue_name: str) -> Dict[str, Any]:
        """
        Get detailed information for a specific queue.
        
        Args:
            queue_name: Name of the queue
            
        Returns:
            Queue details including size, status, configuration
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_queue_details(queue_name)
    
    async def pause_queue(self, queue_name: str) -> Dict[str, Any]:
        """
        Pause processing for a queue.
        
        Args:
            queue_name: Name of the queue to pause
            
        Returns:
            Pause operation result
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.pause_queue(queue_name)
    
    async def resume_queue(self, queue_name: str) -> Dict[str, Any]:
        """
        Resume processing for a paused queue.
        
        Args:
            queue_name: Name of the queue to resume
            
        Returns:
            Resume operation result
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.resume_queue(queue_name)
    
    async def clear_queue(self, queue_name: str) -> Dict[str, Any]:
        """
        Clear all items from a queue.
        
        Args:
            queue_name: Name of the queue to clear
            
        Returns:
            Clear operation result with number of items removed
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.clear_queue(queue_name)
    
    async def configure_queue(self, queue_name: str, 
                            config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Configure queue settings.
        
        Args:
            queue_name: Name of the queue to configure
            config: Configuration dictionary with settings like:
                   - max_size: Maximum queue size
                   - priority: Queue priority
                   - workers: Number of workers
                   - retry_policy: Retry configuration
                   
        Returns:
            Configuration result
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        # Validate config if method exists
        if hasattr(self._adapter, 'configure_queue'):
            return await self._adapter.configure_queue(queue_name, config)
        else:
            return {"error": "Queue configuration not supported in this mode"}
    
    async def get_queue_statistics(self) -> Dict[str, Any]:
        """
        Get statistics for all queues.
        
        Returns:
            Dictionary with queue statistics including:
            - Total items across all queues
            - Queue sizes
            - Processing rates
            - Error rates
        """
        queues = await self.get_queues()
        
        stats = {
            'total_queues': 0,
            'total_items': 0,
            'total_processing': 0,
            'queues': {}
        }
        
        for queue_name, queue_info in queues.items():
            stats['total_queues'] += 1
            size = queue_info.get('size', 0)
            processing = queue_info.get('processing', 0)
            
            stats['total_items'] += size
            stats['total_processing'] += processing
            
            stats['queues'][queue_name] = {
                'size': size,
                'processing': processing,
                'status': queue_info.get('status', 'unknown')
            }
        
        return stats
    
    async def rebalance_queues(self) -> Dict[str, Any]:
        """
        Rebalance work across queues for optimal performance.
        
        Returns:
            Rebalancing result
        """
        # Get current queue states
        stats = await self.get_queue_statistics()
        
        # Simple rebalancing logic - could be extended
        rebalanced = []
        for queue_name, queue_stats in stats['queues'].items():
            if queue_stats['size'] > 100:  # Arbitrary threshold
                # Queue might need more workers
                rebalanced.append({
                    'queue': queue_name,
                    'action': 'scale_up',
                    'reason': f"High queue size: {queue_stats['size']}"
                })
            elif queue_stats['size'] == 0 and queue_stats['processing'] == 0:
                # Queue might be idle
                rebalanced.append({
                    'queue': queue_name,
                    'action': 'scale_down',
                    'reason': 'Queue idle'
                })
        
        return {
            'analyzed': stats['total_queues'],
            'recommendations': rebalanced
        }
    
    async def move_task_to_queue(self, task_id: str, 
                                target_queue: str) -> Dict[str, Any]:
        """
        Move a task to a different queue.
        
        Args:
            task_id: Task ID to move
            target_queue: Target queue name
            
        Returns:
            Move operation result
        """
        # This would need backend support
        # For now, return a placeholder
        return {
            'task_id': task_id,
            'target_queue': target_queue,
            'status': 'operation_not_implemented',
            'message': 'Task queue movement requires backend support'
        }
    
    async def get_queue_health(self) -> Dict[str, Any]:
        """
        Get health status of all queues.
        
        Returns:
            Health information for each queue
        """
        queues = await self.get_queues()
        health = {}
        
        for queue_name, queue_info in queues.items():
            size = queue_info.get('size', 0)
            status = queue_info.get('status', 'unknown')
            
            # Determine health based on queue metrics
            if status == 'paused':
                health_status = 'warning'
                health_message = 'Queue is paused'
            elif size > 1000:
                health_status = 'critical'
                health_message = f'Queue overloaded: {size} items'
            elif size > 500:
                health_status = 'warning'
                health_message = f'Queue size high: {size} items'
            else:
                health_status = 'healthy'
                health_message = 'Queue operating normally'
            
            health[queue_name] = {
                'status': health_status,
                'message': health_message,
                'metrics': {
                    'size': size,
                    'status': status
                }
            }
        
        return health