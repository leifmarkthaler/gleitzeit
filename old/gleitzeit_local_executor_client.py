#!/usr/bin/env python3
"""
Local Task Executor Client

Connects to the central Gleitzeit Socket.IO service and registers as an executor node.
This allows the TaskDispatcher to assign tasks to the local TaskExecutor.
"""

import asyncio
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
import sys

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from gleitzeit_cluster.execution.task_executor import TaskExecutor
from gleitzeit_cluster.core.task import Task, TaskType, TaskStatus
from gleitzeit_cluster.communication.service_discovery import get_socketio_url

import socketio

logger = logging.getLogger(__name__)

class LocalExecutorClient:
    """
    Local executor client that connects to central Socket.IO service
    
    This acts as a bridge between the TaskDispatcher (in the central service)
    and the local TaskExecutor. It receives task assignments and delegates
    execution to the TaskExecutor.
    """
    
    def __init__(
        self,
        node_id: str = None,
        name: str = "LocalTaskExecutor",
        socketio_url: str = None,
        ollama_url: str = "http://localhost:11434"
    ):
        """Initialize executor client"""
        self.node_id = node_id or str(uuid.uuid4())
        self.name = name
        self.socketio_url = socketio_url or get_socketio_url()
        self.ollama_url = ollama_url
        
        # Create Socket.IO client
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=5,
            reconnection_delay=1,
            reconnection_delay_max=30,
            logger=False,
            engineio_logger=False
        )
        
        # Task executor for actual execution
        self.task_executor = TaskExecutor(
            ollama_url=ollama_url
        )
        
        # State
        self.connected = False
        self.current_tasks = 0
        self.total_completed = 0
        self.total_failed = 0
        self.start_time = datetime.utcnow()
        
        # Setup event handlers
        self._setup_events()
        
        logger.info(f"LocalExecutorClient initialized")
        logger.info(f"  Node ID: {self.node_id}")
        logger.info(f"  Name: {self.name}")
        logger.info(f"  Socket.IO URL: {self.socketio_url}")
    
    def _setup_events(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect():
            logger.info("✅ Connected to central Socket.IO service")
            self.connected = True
            await self.register_node()
            await self.start_heartbeat()
        
        @self.sio.event
        async def disconnect():
            logger.info("❌ Disconnected from central Socket.IO service")
            self.connected = False
        
        @self.sio.on('task:assign', namespace='/cluster')
        async def handle_task_assign(data):
            """Handle task assignment from TaskDispatcher"""
            await self._handle_task_assignment(data)
    
    async def start(self):
        """Start the executor client"""
        logger.info("🚀 Starting Local Executor Client")
        
        # Start task executor
        await self.task_executor.start()
        logger.info("✅ TaskExecutor started")
        
        # Connect to Socket.IO service
        try:
            await self.sio.connect(
                self.socketio_url,
                namespaces=['/cluster'],
                auth={'token': 'demo_token'}
            )
            logger.info("✅ Connected to Socket.IO service")
            
        except Exception as e:
            logger.error(f"Failed to connect to Socket.IO service: {e}")
            raise
    
    async def stop(self):
        """Stop the executor client"""
        logger.info("🛑 Stopping Local Executor Client")
        
        if self.connected:
            try:
                await self.sio.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting from Socket.IO: {e}")
        
        if self.task_executor:
            try:
                await self.task_executor.stop()
            except Exception as e:
                logger.error(f"Error stopping TaskExecutor: {e}")
        
        logger.info("✅ Local Executor Client stopped")
    
    async def register_node(self):
        """Register this executor as an available node"""
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
                'has_gpu': False,  # Could be detected
                'ollama_available': True,
                'python_available': True
            },
            'metadata': {
                'version': '1.0.0',
                'ollama_url': self.ollama_url,
                'started_at': self.start_time.isoformat()
            }
        }
        
        await self.sio.emit('node:register', registration_data, namespace='/cluster')
        logger.info(f"📋 Registered as executor node: {self.name} ({self.node_id[:8]}...)")
    
    async def start_heartbeat(self):
        """Start sending periodic heartbeat updates"""
        asyncio.create_task(self._heartbeat_loop())
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeat updates"""
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
                
                await self.sio.emit('node:heartbeat', heartbeat_data, namespace='/cluster')
                await asyncio.sleep(30)  # Heartbeat every 30 seconds
                
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(30)
    
    async def _handle_task_assignment(self, data):
        """Handle task assignment from TaskDispatcher"""
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        task_type = data.get('task_type')
        parameters = data.get('parameters', {})
        
        logger.info(f"📋 Received task assignment: {task_id[:8]}... ({task_type})")
        
        try:
            # Acknowledge task acceptance
            await self.sio.emit('task:accepted', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'node_id': self.node_id,
                'accepted_at': datetime.utcnow().isoformat()
            }, namespace='/cluster')
            
            self.current_tasks += 1
            
            # Convert task data to Task object
            # Map task type string to TaskType enum
            task_type_enum = TaskType.EXTERNAL_CUSTOM  # Default fallback
            try:
                if task_type == 'external_custom':
                    task_type_enum = TaskType.EXTERNAL_CUSTOM
                elif task_type == 'external_ml':
                    task_type_enum = TaskType.EXTERNAL_ML
                elif task_type == 'external_api':
                    task_type_enum = TaskType.EXTERNAL_API
                elif task_type == 'external_processing':
                    task_type_enum = TaskType.EXTERNAL_PROCESSING
                elif task_type == 'external_database':
                    task_type_enum = TaskType.EXTERNAL_DATABASE
                elif task_type == 'external_webhook':
                    task_type_enum = TaskType.EXTERNAL_WEBHOOK
            except:
                pass  # Use default
            
            task = Task(
                id=task_id,
                workflow_id=workflow_id,
                name=parameters.get('name', f'Task_{task_id[:8]}'),
                task_type=task_type_enum,
                parameters=parameters
            )
            
            # Execute task using TaskExecutor
            logger.info(f"⚙️  Executing task: {task.name}")
            result = await self.task_executor.execute_task(task)
            
            # Report successful completion
            await self.sio.emit('task:completed', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'node_id': self.node_id,
                'result': result,
                'completed_at': datetime.utcnow().isoformat()
            }, namespace='/cluster')
            
            self.total_completed += 1
            logger.info(f"✅ Task completed: {task.name}")
            
        except Exception as e:
            # Report task failure
            await self.sio.emit('task:failed', {
                'task_id': task_id,
                'workflow_id': workflow_id, 
                'node_id': self.node_id,
                'error': str(e),
                'failed_at': datetime.utcnow().isoformat()
            }, namespace='/cluster')
            
            self.total_failed += 1
            logger.error(f"❌ Task failed: {task_id[:8]}... - {e}")
        
        finally:
            self.current_tasks -= 1


async def main():
    """Main entry point for standalone execution"""
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("🤖 Gleitzeit Local Executor Client")
    print("=" * 50)
    print("Connects to central service and executes assigned tasks")
    print()
    
    # Create and start executor client
    client = LocalExecutorClient()
    
    try:
        await client.start()
        
        # Keep running until interrupted
        print("✅ Executor client is running - Press Ctrl+C to stop")
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        await client.stop()
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        await client.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())