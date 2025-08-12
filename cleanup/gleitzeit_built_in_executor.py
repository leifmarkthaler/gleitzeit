#!/usr/bin/env python3
"""
Built-in Executor for Central Service

A simple executor that registers with the central Socket.IO service and handles task execution.
This ensures there's always at least one executor available for the TaskDispatcher.
"""

import asyncio
import uuid
import logging
from datetime import datetime
from typing import Dict, Any

import socketio

logger = logging.getLogger(__name__)

class BuiltInExecutor:
    """
    Built-in executor that registers with the central Socket.IO service
    
    This provides a reliable executor node that's always available when the
    central service starts, ensuring tasks can be processed immediately.
    """
    
    def __init__(self, socketio_url: str, task_executor):
        """Initialize built-in executor"""
        self.socketio_url = socketio_url
        self.task_executor = task_executor
        self.node_id = f"builtin_executor_{str(uuid.uuid4())[:8]}"
        self.name = "Built-in Executor"
        
        # Create Socket.IO client
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=5,
            reconnection_delay=1,
            logger=False,
            engineio_logger=False
        )
        
        # State
        self.connected = False
        self.current_tasks = 0
        self.total_completed = 0
        self.total_failed = 0
        self.start_time = datetime.utcnow()
        
        self._setup_events()
        
        logger.info(f"BuiltInExecutor initialized: {self.node_id}")
    
    def _setup_events(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect():
            logger.info("✅ Built-in executor connected to Socket.IO")
            self.connected = True
            await self._register_node()
            asyncio.create_task(self._heartbeat_loop())
        
        @self.sio.event
        async def disconnect():
            logger.info("❌ Built-in executor disconnected")
            self.connected = False
        
        @self.sio.on('task:assign')
        async def handle_task_assign(data):
            """Handle task assignment"""
            await self._handle_task_assignment(data)
    
    async def start(self):
        """Start the built-in executor"""
        logger.info("🚀 Starting Built-in Executor")
        
        try:
            # Connect without namespace first, then join namespace
            await self.sio.connect(self.socketio_url)
            logger.info("✅ Built-in executor connected to Socket.IO")
            
            # Wait a bit for connection to stabilize
            await asyncio.sleep(0.5)
            
            logger.info("✅ Built-in executor started")
            
        except Exception as e:
            logger.error(f"Failed to start built-in executor: {e}")
            raise
    
    async def stop(self):
        """Stop the built-in executor"""
        logger.info("🛑 Stopping Built-in Executor")
        
        if self.connected:
            try:
                await self.sio.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
        
        logger.info("✅ Built-in executor stopped")
    
    async def _register_node(self):
        """Register as an executor node"""
        registration_data = {
            'node_id': self.node_id,
            'name': self.name,
            'node_type': 'executor',
            'capabilities': {
                'task_types': [
                    'external_custom',
                    'external_ml',
                    'external_api', 
                    'external_processing',
                    'external_database',
                    'external_webhook'
                ],
                'max_concurrent_tasks': 4,
                'has_gpu': False,
                'ollama_available': True
            },
            'metadata': {
                'version': '1.0.0',
                'builtin': True,
                'started_at': self.start_time.isoformat()
            }
        }
        
        await self.sio.emit('node:register', registration_data)
        logger.info(f"📋 Registered as executor: {self.name} ({self.node_id})")
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats"""
        while self.connected:
            try:
                uptime = (datetime.utcnow() - self.start_time).total_seconds()
                
                heartbeat_data = {
                    'node_id': self.node_id,
                    'node_type': 'executor',
                    'status': 'ready' if self.current_tasks == 0 else 'busy',
                    'active_tasks': self.current_tasks,
                    'tasks_completed': self.total_completed,
                    'tasks_failed': self.total_failed,
                    'uptime_seconds': uptime,
                    'timestamp': datetime.utcnow().isoformat()
                }
                
                await self.sio.emit('node:heartbeat', heartbeat_data)
                await asyncio.sleep(30)  # Heartbeat every 30 seconds
                
            except Exception as e:
                if self.connected:  # Only log if we should be connected
                    logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(30)
    
    async def _handle_task_assignment(self, data):
        """Handle task assignment from TaskDispatcher"""
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        task_type = data.get('task_type')
        parameters = data.get('parameters', {})
        
        logger.info(f"📋 Received task: {task_id[:8]}... ({task_type})")
        
        try:
            # Acknowledge task acceptance
            await self.sio.emit('task:accepted', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'node_id': self.node_id,
                'accepted_at': datetime.utcnow().isoformat()
            })
            
            self.current_tasks += 1
            
            # Import Task class here to avoid circular imports
            from gleitzeit_cluster.core.task import Task, TaskType
            
            # Map task type string to enum
            task_type_enum = TaskType.EXTERNAL_CUSTOM  # Default
            try:
                if task_type == 'external_custom':
                    task_type_enum = TaskType.EXTERNAL_CUSTOM
                elif task_type == 'external_ml':
                    task_type_enum = TaskType.EXTERNAL_ML
                # Add other mappings as needed
            except:
                pass
            
            # Create task object
            task = Task(
                id=task_id,
                workflow_id=workflow_id,
                name=parameters.get('name', f'Task_{task_id[:8]}'),
                task_type=task_type_enum,
                parameters=parameters
            )
            
            # Execute task using the cluster's TaskExecutor
            logger.info(f"⚙️  Executing task: {task.name}")
            result = await self.task_executor.execute_task(task)
            
            # Report completion
            await self.sio.emit('task:completed', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'node_id': self.node_id,
                'result': result,
                'completed_at': datetime.utcnow().isoformat()
            })
            
            self.total_completed += 1
            logger.info(f"✅ Task completed: {task.name}")
            
        except Exception as e:
            # Report failure
            await self.sio.emit('task:failed', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'node_id': self.node_id,
                'error': str(e),
                'failed_at': datetime.utcnow().isoformat()
            })
            
            self.total_failed += 1
            logger.error(f"❌ Task failed: {task_id[:8]}... - {e}")
        
        finally:
            self.current_tasks -= 1