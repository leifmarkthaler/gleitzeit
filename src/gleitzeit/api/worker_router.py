"""
Worker Router - Routes workflows to worker services

This module handles routing workflows to external worker services
for distributed execution when configured.
"""

import os
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import aiohttp
import random

from gleitzeit.core.models import Workflow, Task

logger = logging.getLogger(__name__)


class WorkerRouter:
    """
    Routes workflows to worker services for distributed execution.
    
    Can be configured with multiple worker service URLs for load balancing.
    Falls back to local execution if no workers are available.
    """
    
    def __init__(self, worker_urls: Optional[List[str]] = None):
        """
        Initialize worker router.
        
        Args:
            worker_urls: List of worker service URLs
        """
        # Get worker URLs from env or use provided
        if worker_urls:
            self.worker_urls = worker_urls
        else:
            urls_env = os.environ.get('WORKER_SERVICE_URLS', '')
            self.worker_urls = [url.strip() for url in urls_env.split(',') if url.strip()]
        
        self.enabled = bool(self.worker_urls)
        self.health_cache = {}  # URL -> (is_healthy, last_check)
        self.health_check_interval = 30  # seconds
        
        if self.enabled:
            logger.info(f"Worker routing enabled with {len(self.worker_urls)} worker services")
        else:
            logger.info("Worker routing disabled - using local execution")
    
    def should_route_to_worker(self, workflow: Workflow) -> bool:
        """
        Determine if workflow should be routed to worker service.
        
        Args:
            workflow: Workflow to evaluate
            
        Returns:
            True if should route to worker
        """
        if not self.enabled:
            return False
        
        # Route based on workflow characteristics
        # Large workflows go to workers
        if len(workflow.tasks) > 10:
            return True
        
        # Long-running workflows go to workers
        if workflow.metadata and workflow.metadata.get('estimated_duration', 0) > 60:
            return True
        
        # Workflows marked for async execution
        if workflow.metadata and workflow.metadata.get('async', False):
            return True
        
        # Default to local execution for small, quick workflows
        return False
    
    async def get_healthy_worker(self) -> Optional[str]:
        """
        Get a healthy worker service URL.
        
        Returns:
            URL of healthy worker or None
        """
        if not self.worker_urls:
            return None
        
        # Simple round-robin with health check
        healthy_urls = []
        
        for url in self.worker_urls:
            if await self.is_worker_healthy(url):
                healthy_urls.append(url)
        
        if healthy_urls:
            # Random selection for load balancing
            return random.choice(healthy_urls)
        
        return None
    
    async def is_worker_healthy(self, url: str) -> bool:
        """
        Check if worker service is healthy.
        
        Args:
            url: Worker service URL
            
        Returns:
            True if healthy
        """
        # Check cache
        if url in self.health_cache:
            is_healthy, last_check = self.health_cache[url]
            age = (datetime.utcnow() - last_check).total_seconds()
            if age < self.health_check_interval:
                return is_healthy
        
        # Perform health check
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{url}/health",
                    timeout=aiohttp.ClientTimeout(total=2)
                ) as response:
                    is_healthy = response.status == 200
                    self.health_cache[url] = (is_healthy, datetime.utcnow())
                    return is_healthy
        except Exception as e:
            logger.warning(f"Worker health check failed for {url}: {e}")
            self.health_cache[url] = (False, datetime.utcnow())
            return False
    
    async def route_workflow(self, workflow: Workflow) -> Optional[Dict[str, Any]]:
        """
        Route workflow to worker service.
        
        Args:
            workflow: Workflow to execute
            
        Returns:
            Execution result or None if routing failed
        """
        if not self.should_route_to_worker(workflow):
            return None
        
        worker_url = await self.get_healthy_worker()
        if not worker_url:
            logger.warning("No healthy workers available, falling back to local execution")
            return None
        
        try:
            # Send to worker service
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{worker_url}/execute/workflow",
                    json={"workflow": workflow.dict()},
                    timeout=aiohttp.ClientTimeout(total=300)  # 5 minute timeout
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Workflow {workflow.id} routed to worker at {worker_url}")
                        return result
                    else:
                        error = await response.text()
                        logger.error(f"Worker execution failed: {error}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error(f"Worker execution timeout for workflow {workflow.id}")
            return None
        except Exception as e:
            logger.error(f"Failed to route workflow to worker: {e}")
            return None
    
    async def route_task(self, task: Task) -> Optional[Dict[str, Any]]:
        """
        Route individual task to worker service.
        
        Args:
            task: Task to execute
            
        Returns:
            Execution result or None if routing failed
        """
        if not self.enabled:
            return None
        
        worker_url = await self.get_healthy_worker()
        if not worker_url:
            return None
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{worker_url}/execute/task",
                    json={"task": task.dict()},
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Task {task.id} routed to worker at {worker_url}")
                        return result
                    else:
                        return None
                        
        except Exception as e:
            logger.error(f"Failed to route task to worker: {e}")
            return None
    
    async def get_worker_status(self) -> Dict[str, Any]:
        """Get status of all worker services"""
        status = {
            "enabled": self.enabled,
            "worker_count": len(self.worker_urls),
            "workers": []
        }
        
        for url in self.worker_urls:
            is_healthy = await self.is_worker_healthy(url)
            
            worker_info = {
                "url": url,
                "healthy": is_healthy
            }
            
            # Get detailed metrics if healthy
            if is_healthy:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{url}/metrics",
                            timeout=aiohttp.ClientTimeout(total=2)
                        ) as response:
                            if response.status == 200:
                                metrics = await response.json()
                                worker_info["metrics"] = metrics
                except:
                    pass
            
            status["workers"].append(worker_info)
        
        return status


# Global router instance
_worker_router: Optional[WorkerRouter] = None


def get_worker_router() -> WorkerRouter:
    """Get or create global worker router"""
    global _worker_router
    if _worker_router is None:
        _worker_router = WorkerRouter()
    return _worker_router