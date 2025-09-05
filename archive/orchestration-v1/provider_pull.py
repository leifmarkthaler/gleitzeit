"""
Provider Pull Adapter for task execution

Allows providers to pull tasks from Redis queues instead of 
being directly invoked, enabling better load distribution.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.core.models import TaskStatus

logger = logging.getLogger(__name__)


class ProviderPullAdapter:
    """
    Adapter for providers to pull tasks from queue
    Replaces push-based task execution with pull model
    """
    
    def __init__(
        self,
        provider: ProtocolProvider,
        event_bus: EventBus,
        redis_client,
        poll_interval: float = 1.0,
        batch_size: int = 1
    ):
        """
        Initialize provider pull adapter
        
        Args:
            provider: ProtocolProvider instance to execute tasks
            event_bus: Event bus for coordination
            redis_client: Redis client for queue operations
            poll_interval: Seconds between polls when queue is empty
            batch_size: Number of tasks to pull at once
        """
        self.provider = provider
        self.event_bus = event_bus
        self.redis = redis_client
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self.running = False
        
        # Get protocol from provider
        self.protocol = getattr(provider, 'protocol_name', None) or \
                       getattr(provider, 'protocol', None) or \
                       provider.__class__.__name__.lower().replace('provider', '')
        
        # Queue configuration
        self.queue_key = f"provider:queue:{self.protocol}"
        self.processing_key = f"provider:processing:{self.protocol}"
        
        # Statistics
        self.tasks_processed = 0
        self.tasks_failed = 0
        self.started_at = None
        
        logger.info(f"Initialized ProviderPullAdapter for protocol '{self.protocol}'")
        
    async def start(self):
        """Start pulling and executing tasks"""
        if self.running:
            logger.warning(f"Pull adapter for {self.protocol} already running")
            return
            
        self.running = True
        self.started_at = datetime.utcnow()
        logger.info(f"Starting pull adapter for {self.protocol} (queue: {self.queue_key})")
        
        # Main pull loop
        while self.running:
            try:
                # Pull task from queue
                task_data = await self._pull_task()
                
                if task_data:
                    # Execute task
                    await self._execute_task(task_data)
                else:
                    # No tasks available, wait before polling again
                    await asyncio.sleep(self.poll_interval)
                    
            except asyncio.CancelledError:
                logger.info(f"Pull adapter for {self.protocol} cancelled")
                break
            except Exception as e:
                logger.error(f"Error in pull adapter for {self.protocol}: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)
        
        logger.info(f"Pull adapter for {self.protocol} stopped")
    
    async def stop(self):
        """Stop pulling tasks"""
        logger.info(f"Stopping pull adapter for {self.protocol}")
        self.running = False
    
    async def _pull_task(self) -> Optional[Dict[str, Any]]:
        """Pull next task from queue"""
        try:
            # Use blocking pop with timeout to reduce polling overhead
            # BRPOP blocks until an item is available or timeout expires
            result = await self.redis.brpop(self.queue_key, timeout=1)
            
            if result:
                # result is (queue_name, value)
                _, task_json = result
                task_data = json.loads(task_json)
                
                # Move to processing queue for reliability
                # This allows recovery if provider crashes during execution
                await self.redis.lpush(self.processing_key, task_json)
                
                logger.debug(f"Pulled task {task_data.get('task_id')} from {self.queue_key}")
                return task_data
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in task queue: {e}")
        except Exception as e:
            logger.error(f"Error pulling task from queue: {e}")
            
        return None
    
    async def _execute_task(self, task_data: Dict[str, Any]):
        """Execute pulled task using provider"""
        task_id = task_data.get("task_id", "unknown")
        workflow_id = task_data.get("workflow_id")
        method = task_data.get("method")
        params = task_data.get("params", {})
        metadata = task_data.get("metadata", {})
        
        logger.info(f"Executing task {task_id} (workflow: {workflow_id}, method: {method})")
        
        # Emit task started event
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            data={
                "task_id": task_id,
                "workflow_id": workflow_id,
                "provider": self.protocol,
                "method": method,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        start_time = datetime.utcnow()
        
        try:
            # Execute via provider
            # Check if provider has async execute method
            if hasattr(self.provider, 'execute'):
                if asyncio.iscoroutinefunction(self.provider.execute):
                    result = await self.provider.execute(method=method, params=params)
                else:
                    # Run sync method in executor
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, 
                        self.provider.execute,
                        method,
                        params
                    )
            elif hasattr(self.provider, 'run'):
                # Some providers might use 'run' instead of 'execute'
                if asyncio.iscoroutinefunction(self.provider.run):
                    result = await self.provider.run(**params)
                else:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None,
                        self.provider.run,
                        **params
                    )
            else:
                raise AttributeError(f"Provider {self.protocol} has no execute or run method")
            
            # Calculate execution time
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Remove from processing queue
            await self._remove_from_processing(task_data)
            
            # Update statistics
            self.tasks_processed += 1
            
            # Emit task completed event
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_COMPLETED,
                data={
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "result": result if isinstance(result, (dict, list, str, int, float, bool, type(None))) else str(result),
                    "execution_time": execution_time,
                    "provider": self.protocol,
                    "timestamp": datetime.utcnow().isoformat()
                }
            ))
            
            logger.info(f"Task {task_id} completed successfully in {execution_time:.2f}s")
            
        except asyncio.TimeoutError:
            # Handle timeout
            await self._handle_task_failure(
                task_data,
                "Task execution timed out",
                is_timeout=True
            )
            
        except Exception as e:
            # Handle execution failure
            await self._handle_task_failure(
                task_data,
                str(e),
                is_timeout=False
            )
    
    async def _handle_task_failure(
        self, 
        task_data: Dict[str, Any], 
        error: str,
        is_timeout: bool = False
    ):
        """Handle task execution failure"""
        task_id = task_data.get("task_id", "unknown")
        workflow_id = task_data.get("workflow_id")
        
        logger.error(f"Task {task_id} failed: {error}")
        
        # Remove from processing queue
        await self._remove_from_processing(task_data)
        
        # Update statistics
        self.tasks_failed += 1
        
        # Determine event type
        event_type = EventType.TASK_TIMEOUT if is_timeout else EventType.TASK_FAILED
        
        # Emit failure event
        await self.event_bus.emit(GleitzeitEvent(
            event_type=event_type,
            data={
                "task_id": task_id,
                "workflow_id": workflow_id,
                "error": error,
                "provider": self.protocol,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
    
    async def _remove_from_processing(self, task_data: Dict[str, Any]):
        """Remove task from processing queue after completion"""
        try:
            # Remove specific task from processing queue
            task_json = json.dumps(task_data)
            await self.redis.lrem(self.processing_key, 1, task_json)
        except Exception as e:
            logger.warning(f"Failed to remove task from processing queue: {e}")
    
    async def recover_processing_tasks(self):
        """
        Recover tasks from processing queue (e.g., after crash)
        Moves them back to main queue for reprocessing
        """
        try:
            # Get all tasks from processing queue
            processing_tasks = await self.redis.lrange(self.processing_key, 0, -1)
            
            if processing_tasks:
                logger.info(f"Recovering {len(processing_tasks)} tasks from processing queue")
                
                # Move each task back to main queue
                for task_json in processing_tasks:
                    await self.redis.lpush(self.queue_key, task_json)
                
                # Clear processing queue
                await self.redis.delete(self.processing_key)
                
                logger.info(f"Recovered {len(processing_tasks)} tasks")
                
        except Exception as e:
            logger.error(f"Error recovering processing tasks: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get adapter statistics"""
        uptime = None
        if self.started_at:
            uptime = (datetime.utcnow() - self.started_at).total_seconds()
            
        return {
            "protocol": self.protocol,
            "running": self.running,
            "tasks_processed": self.tasks_processed,
            "tasks_failed": self.tasks_failed,
            "success_rate": self.tasks_processed / (self.tasks_processed + self.tasks_failed) 
                           if (self.tasks_processed + self.tasks_failed) > 0 else 0,
            "uptime_seconds": uptime,
            "queue_key": self.queue_key
        }


class ProviderPoolManager:
    """
    Manage multiple provider pull adapters for scaling
    """
    
    def __init__(self, event_bus: EventBus, redis_client):
        self.event_bus = event_bus
        self.redis = redis_client
        self.adapters: Dict[str, List[ProviderPullAdapter]] = {}
        self.running = False
        
    async def add_provider(
        self, 
        provider: ProtocolProvider, 
        instances: int = 1,
        poll_interval: float = 1.0
    ):
        """Add provider with specified number of pull adapter instances"""
        protocol = getattr(provider, 'protocol_name', None) or \
                  getattr(provider, 'protocol', None) or \
                  provider.__class__.__name__.lower().replace('provider', '')
        
        if protocol not in self.adapters:
            self.adapters[protocol] = []
        
        for i in range(instances):
            adapter = ProviderPullAdapter(
                provider=provider,
                event_bus=self.event_bus,
                redis_client=self.redis,
                poll_interval=poll_interval
            )
            self.adapters[protocol].append(adapter)
            
            if self.running:
                # Start immediately if manager is running
                asyncio.create_task(adapter.start())
        
        logger.info(f"Added {instances} pull adapter(s) for protocol {protocol}")
    
    async def start(self):
        """Start all provider adapters"""
        self.running = True
        
        tasks = []
        for protocol, adapter_list in self.adapters.items():
            for adapter in adapter_list:
                # Recover any crashed tasks first
                await adapter.recover_processing_tasks()
                # Start adapter
                tasks.append(asyncio.create_task(adapter.start()))
        
        logger.info(f"Started {len(tasks)} provider pull adapters")
        
        # Wait for all adapters
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def stop(self):
        """Stop all provider adapters"""
        self.running = False
        
        for protocol, adapter_list in self.adapters.items():
            for adapter in adapter_list:
                await adapter.stop()
        
        logger.info("Stopped all provider pull adapters")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all adapters"""
        stats = {}
        for protocol, adapter_list in self.adapters.items():
            stats[protocol] = {
                "instances": len(adapter_list),
                "adapters": [adapter.get_stats() for adapter in adapter_list]
            }
        return stats