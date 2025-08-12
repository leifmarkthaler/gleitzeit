"""
Workflow Orchestration Server for Gleitzeit V2

This server handles workflow logic and connects to the central Socket.IO server.
Manages task queuing, provider assignment, and workflow completion.
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional, Any
from datetime import datetime

import socketio

from ..core.models import Workflow, Task, WorkflowStatus, TaskStatus, TaskType, Provider
from ..core.provider_manager import ProviderManager
from ..core.task_queue import TaskQueue
from ..core.workflow_engine import WorkflowEngine
from ..storage.redis_client import RedisClient

logger = logging.getLogger(__name__)


class WorkflowOrchestrationServer:
    """
    Workflow orchestration server that connects to central Socket.IO server
    
    Responsibilities:
    - Workflow and task management
    - Provider coordination  
    - Task scheduling and assignment
    - Workflow completion tracking
    """
    
    def __init__(
        self,
        socketio_url: str = "http://localhost:8000",
        redis_url: str = "redis://localhost:6379",
        server_id: str = "workflow_server_1"
    ):
        self.socketio_url = socketio_url
        self.redis_url = redis_url
        self.server_id = server_id
        
        # Socket.IO client to connect to central server
        self.sio = socketio.AsyncClient()
        
        # Core components
        self.redis_client = RedisClient(redis_url=redis_url)
        self.provider_manager = ProviderManager()
        self.task_queue = TaskQueue(self.redis_client)
        self.workflow_engine = WorkflowEngine(
            redis_client=self.redis_client,
            task_queue=self.task_queue,
            provider_manager=self.provider_manager
        )
        
        # Connection state
        self.connected = False
        self.registered = False
        
        # Setup event handlers
        self._setup_handlers()
        
        logger.info(f"Workflow Orchestration Server initialized: {server_id}")
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect():
            self.connected = True
            logger.info("✅ Connected to central Socket.IO server")
            
            # Register as server component
            await self.sio.emit('component:register', {
                'type': 'server',
                'id': self.server_id
            })
        
        @self.sio.event
        async def disconnect():
            self.connected = False
            self.registered = False
            logger.info("🔌 Disconnected from central Socket.IO server")
        
        @self.sio.on('component:registered')
        async def component_registered(data):
            """Server registration confirmed"""
            self.registered = True
            logger.info(f"✅ Registered as server component: {data}")
        
        # Provider events from central server
        @self.sio.on('provider:register')
        async def provider_register(data):
            """New provider registered"""
            provider_data = data.get('provider', {})
            socket_id = provider_data.get('socket_id')
            
            if socket_id:
                # Register provider with our provider manager
                provider_id = await self.provider_manager.register_provider(socket_id, provider_data)
                logger.info(f"Provider registered: {provider_id}")
                
                # Trigger task scheduling
                await self.workflow_engine.on_provider_available(provider_id)
        
        @self.sio.on('provider:disconnected')
        async def provider_disconnected(data):
            """Provider disconnected"""
            provider_id = data.get('provider_id')
            if provider_id:
                # Remove from provider manager
                await self.provider_manager.unregister_provider_by_id(provider_id)
                logger.info(f"Provider unregistered: {provider_id}")
        
        @self.sio.on('provider:heartbeat')
        async def provider_heartbeat(data):
            """Provider heartbeat"""
            provider_id = data.get('provider_id')
            if provider_id:
                await self.provider_manager.update_heartbeat(provider_id)
        
        # Task execution events from providers
        @self.sio.on('task:accepted')
        async def task_accepted(data):
            """Task accepted by provider"""
            task_id = data.get('task_id')
            provider_socket_id = data.get('provider_socket_id')
            
            if task_id and provider_socket_id:
                # Find provider by socket ID
                provider = self.provider_manager.get_provider_by_socket(provider_socket_id)
                if provider:
                    await self.workflow_engine.on_task_accepted(task_id, provider.id)
        
        @self.sio.on('task:completed')
        async def task_completed(data):
            """Task completed by provider"""
            task_id = data.get('task_id')
            workflow_id = data.get('workflow_id')
            result = data.get('result')
            
            logger.info(f"Workflow server received task:completed event - task_id: {task_id}, workflow_id: {workflow_id}")
            
            if task_id and workflow_id:
                logger.info(f"Calling workflow engine on_task_completed for {task_id}")
                await self.workflow_engine.on_task_completed(task_id, workflow_id, result)
            else:
                logger.warning(f"Missing task_id or workflow_id in task:completed event: {data}")
        
        @self.sio.on('task:failed')
        async def task_failed(data):
            """Task failed"""
            task_id = data.get('task_id')
            workflow_id = data.get('workflow_id')
            error = data.get('error', 'Unknown error')
            
            logger.warning(f"Task failed: {task_id} - {error}")
            
            if task_id and workflow_id:
                await self.workflow_engine.on_task_failed(task_id, workflow_id, error)
        
        # Client workflow events
        @self.sio.on('workflow:submit')
        async def workflow_submit(data):
            """Workflow submission from client"""
            try:
                workflow_data = data.get('workflow', {})
                client_socket_id = data.get('client_socket_id')
                
                # Create workflow from data
                workflow = Workflow.from_dict(workflow_data)
                
                logger.info(f"Received workflow submission: {workflow.name} ({workflow.id})")
                
                # Submit workflow
                workflow_id = await self.workflow_engine.submit_workflow(workflow)
                
                # Notify client
                if client_socket_id:
                    await self.sio.emit('workflow:submitted', {
                        'workflow_id': workflow_id,
                        'status': 'submitted',
                        'timestamp': datetime.utcnow().isoformat()
                    })
                
            except Exception as e:
                logger.error(f"Failed to submit workflow: {e}")
                if data.get('client_socket_id'):
                    await self.sio.emit('workflow:failed', {
                        'error': str(e),
                        'timestamp': datetime.utcnow().isoformat()
                    })
        
        @self.sio.on('workflow:status')
        async def workflow_status(data):
            """Workflow status request"""
            workflow_id = data.get('workflow_id')
            client_socket_id = data.get('client_socket_id')
            
            if workflow_id and client_socket_id:
                status = await self.workflow_engine.get_workflow_status(workflow_id)
                await self.sio.emit('workflow:status_response', {
                    'workflow_id': workflow_id,
                    'status': status,
                    'timestamp': datetime.utcnow().isoformat()
                })
        
        @self.sio.on('workflow:cancel')
        async def workflow_cancel(data):
            """Workflow cancellation request"""
            workflow_id = data.get('workflow_id')
            client_socket_id = data.get('client_socket_id')
            
            if workflow_id:
                success = await self.workflow_engine.cancel_workflow(workflow_id)
                if client_socket_id:
                    await self.sio.emit('workflow:cancelled', {
                        'workflow_id': workflow_id,
                        'success': success,
                        'timestamp': datetime.utcnow().isoformat()
                    })
    
    async def start(self):
        """Start the workflow orchestration server"""
        try:
            # Connect to Redis
            await self.redis_client.connect()
            logger.info("✅ Redis connected")
            
            # Set server reference in workflow engine
            self.workflow_engine.set_server(self)
            
            # Start workflow engine
            await self.workflow_engine.start()
            logger.info("✅ Workflow engine started")
            
            # Connect to central Socket.IO server
            await self.sio.connect(self.socketio_url)
            logger.info(f"✅ Connected to central Socket.IO server: {self.socketio_url}")
            
            # Wait for registration
            max_wait = 10
            wait_time = 0
            while not self.registered and wait_time < max_wait:
                await asyncio.sleep(0.5)
                wait_time += 0.5
            
            if not self.registered:
                raise Exception("Failed to register with central server")
            
            logger.info("🚀 Workflow Orchestration Server ready")
            
        except Exception as e:
            logger.error(f"Failed to start workflow server: {e}")
            raise
    
    async def stop(self):
        """Stop the workflow orchestration server"""
        try:
            # Stop workflow engine
            if self.workflow_engine:
                await self.workflow_engine.stop()
            
            # Disconnect from Socket.IO
            if self.connected:
                await self.sio.disconnect()
            
            # Close Redis
            if self.redis_client:
                await self.redis_client.close()
            
            logger.info("🛑 Workflow Orchestration Server stopped")
            
        except Exception as e:
            logger.error(f"Error stopping workflow server: {e}")
    
    async def assign_task_to_provider(self, task: Task, provider: Provider):
        """Assign task to provider via central Socket.IO server"""
        try:
            logger.info(f"Assigning task {task.id} to provider {provider.name}")
            
            # Substitute task parameters with results from completed dependent tasks
            await self._substitute_task_parameters(task)
            
            # Send task assignment via central server
            await self.sio.emit('task:assign', {
                'task_id': task.id,
                'workflow_id': task.workflow_id,
                'task_type': task.task_type.value,
                'parameters': task.parameters.to_dict(),
                'timeout': task.timeout,
                'max_retries': task.max_retries,
                'provider_id': provider.id,
                'provider_socket_id': provider.socket_id,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            logger.info(f"Task assignment sent: {task.id} -> {provider.name}")
            
        except Exception as e:
            logger.error(f"Failed to assign task {task.id} to provider {provider.name}: {e}")
            raise
    
    async def _substitute_task_parameters(self, task: Task):
        """Substitute task parameters with results from completed dependent tasks"""
        logger.info(f"Starting parameter substitution for task {task.id}")
        logger.info(f"Task workflow_id: {task.workflow_id}")
        
        if not task.workflow_id or task.workflow_id not in self.workflow_engine.workflows:
            logger.warning(f"No workflow found for task {task.id} with workflow_id {task.workflow_id}")
            return
        
        workflow = self.workflow_engine.workflows[task.workflow_id]
        logger.info(f"Found workflow with {len(workflow.task_results)} task results: {list(workflow.task_results.keys())}")
        
        # Get task parameters as dict
        params_dict = task.parameters.to_dict()
        logger.info(f"Original parameters: {params_dict}")
        
        # Look for substitution patterns in string values
        def substitute_string(text: str) -> str:
            if not isinstance(text, str):
                return text
            
            logger.info(f"Checking string for substitution patterns: {text}")
            
            # Pattern: ${task_TASKID_result}
            pattern = r'\$\{task_([a-f0-9\-]+)_result\}'
            matches = re.findall(pattern, text)
            logger.info(f"Found {len(matches)} substitution patterns: {matches}")
            
            def replace_match(match):
                task_id = match.group(1)
                logger.info(f"Looking for result for task_id: {task_id}")
                if task_id in workflow.task_results:
                    result = workflow.task_results[task_id]
                    logger.info(f"Found result for {task_id}: {result}")
                    # Convert result to string if it's not already
                    return str(result) if result is not None else ''
                else:
                    logger.warning(f"Task result not found for substitution: {task_id}")
                    logger.warning(f"Available task results: {list(workflow.task_results.keys())}")
                    return match.group(0)  # Return original if not found
            
            substituted = re.sub(pattern, replace_match, text)
            logger.info(f"String after substitution: {substituted}")
            return substituted
        
        # Recursively substitute in all string values
        def substitute_recursive(obj):
            if isinstance(obj, dict):
                return {k: substitute_recursive(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [substitute_recursive(item) for item in obj]
            elif isinstance(obj, str):
                return substitute_string(obj)
            else:
                return obj
        
        # Apply substitutions
        substituted_params = substitute_recursive(params_dict)
        logger.info(f"Parameters after substitution: {substituted_params}")
        
        # Update task parameters
        # We need to create new TaskParameters object with substituted values
        from ..core.models import TaskParameters
        
        # Create new parameters object with substituted values
        task.parameters = TaskParameters(**substituted_params)
        
        logger.info(f"Parameter substitution completed for task {task.id}. Final parameters: {task.parameters.to_dict()}")
    
    async def broadcast_workflow_completed(self, workflow_id: str, status: str, results: Dict[str, Any]):
        """Broadcast workflow completion"""
        logger.info(f"Broadcasting workflow:completed event for {workflow_id}")
        await self.sio.emit('workflow:completed', {
            'workflow_id': workflow_id,
            'status': status,
            'results': results,
            'timestamp': datetime.utcnow().isoformat()
        })
        logger.info(f"Workflow:completed event sent for {workflow_id}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics"""
        return {
            'connected': self.connected,
            'registered': self.registered,
            'providers': len(self.provider_manager.providers),
            'active_workflows': len(self.workflow_engine.workflows),
            'queued_tasks': self.task_queue.get_queue_size()
        }


async def main():
    """Run the workflow orchestration server"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Workflow Orchestration Server")
    parser.add_argument('--socketio-url', default='http://localhost:8000', help='Central Socket.IO server URL')
    parser.add_argument('--redis-url', default='redis://localhost:6379', help='Redis URL')
    parser.add_argument('--server-id', default='workflow_server_1', help='Server ID')
    parser.add_argument('--log-level', default='INFO', help='Log level')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and start server
    workflow_server = WorkflowOrchestrationServer(
        socketio_url=args.socketio_url,
        redis_url=args.redis_url,
        server_id=args.server_id
    )
    
    try:
        await workflow_server.start()
        
        # Keep running
        while True:
            await asyncio.sleep(60)
            logger.debug(f"Server stats: {workflow_server.get_stats()}")
    
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down workflow server...")
    finally:
        await workflow_server.stop()


if __name__ == '__main__':
    asyncio.run(main())