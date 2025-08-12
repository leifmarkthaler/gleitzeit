"""
Base Provider for Gleitzeit V3

Event-driven provider base class with:
- Automatic health monitoring
- Heartbeat management
- Event-based task execution
- Built-in observability and metrics
"""

import asyncio
import logging
import time
import socketio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from ..events.schemas import EventType, EventEnvelope, create_event, EventSeverity

logger = logging.getLogger(__name__)


class BaseProvider(ABC):
    """
    Base class for all Gleitzeit V3 providers.
    
    Provides:
    - Event-driven architecture
    - Automatic health monitoring
    - Heartbeat management
    - Task execution lifecycle
    - Performance metrics
    """
    
    def __init__(
        self,
        provider_id: str,
        provider_name: str,
        provider_type: str,
        supported_functions: List[str],
        server_url: str = "http://localhost:8000",
        max_concurrent_tasks: int = 5,
        heartbeat_interval: float = 10.0,
        health_check_interval: float = 30.0
    ):
        # Store provider info
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.provider_type = provider_type
        self.supported_functions = supported_functions
        self.max_concurrent_tasks = max_concurrent_tasks
        
        # Server connection
        self.server_url = server_url
        self.sio = socketio.AsyncClient()
        self.heartbeat_interval = heartbeat_interval
        self.health_check_interval = health_check_interval
        
        # Connection state
        self.connected = False
        self.registered = False
        self.current_tasks = 0
        self.status = "registering"
        self.health_score = 1.0
        
        # Task execution tracking
        self.executing_tasks: Dict[str, Dict[str, Any]] = {}
        self.task_history: List[Dict[str, Any]] = []
        
        # Performance metrics
        self.metrics = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_execution_time": 0.0,
            "average_execution_time": 0.0,
            "last_execution_time": None,
            "health_checks_passed": 0,
            "health_checks_failed": 0
        }
        
        # Running state
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        
        # Setup Socket.IO handlers
        self._setup_socket_handlers()
        
        logger.info(f"BaseProvider initialized: {provider_name} ({provider_id})")
    
    def _setup_socket_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect():
            self.connected = True
            logger.info(f"🔗 Provider connected to server: {self.server_url}")
            
            # Register with server
            await self.sio.emit('provider:register', {
                'provider_id': self.provider_id,
                'provider_name': self.provider_name,
                'provider_type': self.provider_type,
                'supported_functions': self.supported_functions,
                'max_concurrent_tasks': self.max_concurrent_tasks,
                'version': '1.0.0'
            })
        
        @self.sio.event
        async def disconnect():
            self.connected = False
            self.registered = False
            logger.warning(f"🔌 Provider disconnected from server")
        
        @self.sio.on('provider:registered')
        async def provider_registered(data):
            self.registered = True
            self.status = "available"
            logger.info(f"✅ Provider registered with server: {data}")
        
        @self.sio.on('task:execute')
        async def task_execute(data):
            """Handle task execution request from server"""
            await self._handle_task_execution(data)
        
        @self.sio.on('error')
        async def error(data):
            logger.error(f"Server error: {data}")
    
    async def start(self):
        """Start the provider"""
        if self._running:
            return
        
        # Connect to central server
        try:
            await self.sio.connect(self.server_url)
            
            # Wait for registration
            max_wait = 10
            wait_time = 0
            while not self.registered and wait_time < max_wait:
                await asyncio.sleep(0.5)
                wait_time += 0.5
            
            if not self.registered:
                raise Exception("Failed to register with server")
            
            # Start background tasks
            self._running = True
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._health_check_task = asyncio.create_task(self._health_check_loop())
            
            logger.info(f"🚀 Provider started: {self.provider_name}")
            
        except Exception as e:
            logger.error(f"Failed to start provider: {e}")
            raise
    
    async def stop(self):
        """Stop the provider"""
        if not self._running:
            return
        
        self._running = False
        
        # Cancel background tasks
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # Disconnect from server
        if self.connected:
            await self.sio.disconnect()
        
        logger.info(f"🛑 Provider stopped: {self.provider_name}")
    
    async def _handle_task_execution(self, data: Dict[str, Any]):
        """Handle task execution request from server"""
        task_id = data.get("task_id")
        task_type = data.get("task_type", "unknown")
        parameters = data.get("parameters", {})
        
        if not task_id:
            logger.warning("Task execution request missing task_id")
            return
        
        logger.info(f"📋 Executing task: {task_id}")
        
        try:
            # Track task start
            execution_start = time.time()
            self.executing_tasks[task_id] = {
                "task_type": task_type,
                "start_time": execution_start,
                "parameters": parameters
            }
            
            # Update current tasks count
            self.current_tasks += 1
            
            # Execute the task
            result = await self.execute_task(task_type, parameters)
            
            # Track completion
            execution_time = time.time() - execution_start
            await self._handle_task_completion(task_id, result, execution_time)
            
        except Exception as e:
            execution_time = time.time() - execution_start if task_id in self.executing_tasks else 0
            await self._handle_task_failure(task_id, str(e), execution_time)
    
    async def _heartbeat_loop(self):
        """Heartbeat loop"""
        while self._running:
            try:
                if self.connected:
                    await self.sio.emit('provider:heartbeat', {
                        'provider_id': self.provider_id,
                        'status': self.status,
                        'current_tasks': self.current_tasks,
                        'health_score': self.health_score,
                        'timestamp': datetime.utcnow().isoformat()
                    })
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(self.heartbeat_interval)
    
    async def _health_check_loop(self):
        """Health check loop"""
        while self._running:
            try:
                await self._perform_health_check()
                await asyncio.sleep(self.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
                await asyncio.sleep(self.health_check_interval)
    
    async def _perform_health_check(self):
        """Perform health check and update status"""
        try:
            # Perform provider-specific health check
            health_result = await self.health_check()
            
            if health_result.get("healthy", True):
                self.health_score = health_result.get("score", 1.0)
                self.metrics["health_checks_passed"] += 1
                
                # Update status based on load
                if self.current_tasks >= self.max_concurrent_tasks:
                    self.status = "busy"
                elif self.current_tasks > self.max_concurrent_tasks * 0.8:
                    self.status = "overloaded"
                else:
                    self.status = "available"
            else:
                self.health_score = health_result.get("score", 0.0)
                self.metrics["health_checks_failed"] += 1
                self.status = "unhealthy"
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self.health_score = 0.0
            self.metrics["health_checks_failed"] += 1
            self.status = "unhealthy"
    
    async def _handle_task_completion(
        self, 
        task_id: str, 
        result: Any, 
        execution_time: float
    ):
        """Handle successful task completion"""
        # Update metrics
        self.metrics["tasks_completed"] += 1
        self.metrics["total_execution_time"] += execution_time
        self.metrics["average_execution_time"] = (
            self.metrics["total_execution_time"] / 
            (self.metrics["tasks_completed"] + self.metrics["tasks_failed"])
        )
        self.metrics["last_execution_time"] = execution_time
        
        # Clean up tracking
        if task_id in self.executing_tasks:
            task_info = self.executing_tasks.pop(task_id)
            
            # Add to history
            self.task_history.append({
                "task_id": task_id,
                "task_type": task_info["task_type"],
                "start_time": task_info["start_time"],
                "execution_time": execution_time,
                "status": "completed",
                "result_size": len(str(result)) if result else 0
            })
        
        # Update current tasks count
        self.current_tasks = max(0, self.current_tasks - 1)
        
        # Send completion to server
        if self.connected:
            await self.sio.emit('provider:task_completed', {
                "task_id": task_id,
                "provider_id": self.provider_id,
                "success": True,
                "result": result,
                "duration_seconds": execution_time
            })
        
        logger.info(f"✅ Task completed: {task_id} ({execution_time:.2f}s)")
    
    async def _handle_task_failure(
        self, 
        task_id: str, 
        error: str, 
        execution_time: float
    ):
        """Handle task failure"""
        # Update metrics
        self.metrics["tasks_failed"] += 1
        self.metrics["total_execution_time"] += execution_time
        
        # Clean up tracking
        if task_id in self.executing_tasks:
            task_info = self.executing_tasks.pop(task_id)
            
            # Add to history
            self.task_history.append({
                "task_id": task_id,
                "task_type": task_info["task_type"],
                "start_time": task_info["start_time"],
                "execution_time": execution_time,
                "status": "failed",
                "error": error
            })
        
        # Update current tasks count
        self.current_tasks = max(0, self.current_tasks - 1)
        
        # Send failure to server
        if self.connected:
            await self.sio.emit('provider:task_completed', {
                "task_id": task_id,
                "provider_id": self.provider_id,
                "success": False,
                "error": error,
                "duration_seconds": execution_time
            })
        
        logger.error(f"❌ Task failed: {task_id} - {error}")
    
    # Abstract methods that providers must implement
    
    @abstractmethod
    async def execute_task(self, task_type: str, parameters: Dict[str, Any]) -> Any:
        """Execute a task and return the result"""
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Perform provider-specific health check"""
        pass
    
    # Utility methods
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get provider metrics"""
        success_rate = (
            self.metrics["tasks_completed"] / 
            (self.metrics["tasks_completed"] + self.metrics["tasks_failed"])
            if (self.metrics["tasks_completed"] + self.metrics["tasks_failed"]) > 0
            else 1.0
        )
        
        return {
            **self.metrics,
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "current_tasks": self.current_tasks,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "health_score": self.health_score,
            "success_rate": success_rate,
            "status": self.status,
            "connected": self.connected,
            "registered": self.registered
        }
    
    def get_task_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent task execution history"""
        return self.task_history[-limit:] if self.task_history else []