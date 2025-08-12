"""
Gleitzeit V2 Server - Central Coordinator

Clean implementation using provider-executor architecture with Socket.IO.
Manages providers, queues tasks, orchestrates workflows, and emits completion events.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass

import socketio
from socketio import AsyncServer

from .provider_manager import ProviderManager
from .task_queue import TaskQueue  
from .workflow_engine import WorkflowEngine
from .models import Task, Workflow, TaskStatus, WorkflowStatus
from ..storage.redis_client import RedisClient

logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """Server configuration"""
    host: str = "0.0.0.0"
    port: int = 8000
    redis_url: str = "redis://localhost:6379"
    cors_allowed_origins: str = "*"
    log_level: str = "INFO"


class GleitzeitServer:
    """
    Central Gleitzeit server using pure provider-executor architecture
    
    Architecture:
    - Clients submit workflows via Socket.IO
    - Server queues tasks with dependency resolution
    - Providers process tasks and emit completion events
    - Server orchestrates workflow completion
    - All communication via Socket.IO events
    """
    
    def __init__(self, config: ServerConfig = None):
        self.config = config or ServerConfig()
        
        # Core components
        self.redis_client = RedisClient(redis_url=self.config.redis_url)
        self.provider_manager = ProviderManager()
        self.task_queue = TaskQueue(self.redis_client)
        self.workflow_engine = WorkflowEngine(
            redis_client=self.redis_client,
            task_queue=self.task_queue,
            provider_manager=self.provider_manager
        )
        
        # Socket.IO server
        self.sio = AsyncServer(
            cors_allowed_origins=self.config.cors_allowed_origins,
            logger=logger,
            engineio_logger=logger
        )
        
        # Connected clients tracking
        self.clients: Dict[str, Dict] = {}  # sid -> client info
        self.workflow_rooms: Dict[str, List[str]] = {}  # workflow_id -> [sids]
        
        # Setup event handlers
        self._setup_handlers()
        
        # State
        self._running = False
        
        logger.info("GleitzeitServer initialized")
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        # Client lifecycle
        self.sio.on('connect')(self._handle_connect)
        self.sio.on('disconnect')(self._handle_disconnect)
        
        # Workflow operations
        self.sio.on('workflow:submit')(self._handle_workflow_submit)
        self.sio.on('workflow:status')(self._handle_workflow_status)
        self.sio.on('workflow:cancel')(self._handle_workflow_cancel)
        
        # Provider operations
        self.sio.on('provider:register')(self._handle_provider_register)
        self.sio.on('provider:heartbeat')(self._handle_provider_heartbeat)
        self.sio.on('provider:capabilities')(self._handle_provider_capabilities)
        
        # Task events (from providers)
        self.sio.on('task:accepted')(self._handle_task_accepted)
        self.sio.on('task:progress')(self._handle_task_progress)
        self.sio.on('task:completed')(self._handle_task_completed)
        self.sio.on('task:failed')(self._handle_task_failed)
    
    async def start(self):
        """Start the server"""
        if self._running:
            return
        
        logger.info("Starting Gleitzeit Server...")
        
        # Connect to Redis
        await self.redis_client.connect()
        logger.info("✅ Redis connected")
        
        # Start workflow engine
        await self.workflow_engine.start()
        logger.info("✅ Workflow engine started")
        
        self._running = True
        logger.info(f"✅ Gleitzeit Server ready on {self.config.host}:{self.config.port}")
    
    async def stop(self):
        """Stop the server"""
        if not self._running:
            return
        
        logger.info("Stopping Gleitzeit Server...")
        
        # Stop workflow engine
        await self.workflow_engine.stop()
        
        # Disconnect from Redis
        await self.redis_client.disconnect()
        
        self._running = False
        logger.info("✅ Gleitzeit Server stopped")
    
    # =================
    # Client Handlers
    # =================
    
    async def _handle_connect(self, sid, environ, auth):
        """Handle client connection"""
        client_info = {
            'connected_at': datetime.utcnow(),
            'type': 'client',  # Will be updated based on registration
            'workflows': []
        }
        
        self.clients[sid] = client_info
        logger.info(f"Client connected: {sid}")
        
        await self.sio.emit('server:ready', {
            'server_version': '2.0',
            'capabilities': ['workflows', 'batches', 'dependencies', 'providers'],
            'timestamp': datetime.utcnow().isoformat()
        }, room=sid)
    
    async def _handle_disconnect(self, sid):
        """Handle client disconnection"""
        if sid in self.clients:
            client_info = self.clients.pop(sid)
            logger.info(f"Client disconnected: {sid} (type: {client_info.get('type', 'unknown')})")
        
        # Remove from workflow rooms
        for workflow_id, sids in list(self.workflow_rooms.items()):
            if sid in sids:
                sids.remove(sid)
                if not sids:
                    del self.workflow_rooms[workflow_id]
    
    # ===================
    # Workflow Handlers
    # ===================
    
    async def _handle_workflow_submit(self, sid, data):
        """Handle workflow submission"""
        try:
            workflow_data = data.get('workflow')
            if not workflow_data:
                await self._send_error(sid, 'Missing workflow data')
                return
            
            # Create workflow object
            workflow = Workflow.from_dict(workflow_data)
            
            # Join workflow room for progress updates
            workflow_room = f"workflow:{workflow.id}"
            await self.sio.enter_room(sid, workflow_room)
            
            if workflow_room not in self.workflow_rooms:
                self.workflow_rooms[workflow_room] = []
            self.workflow_rooms[workflow_room].append(sid)
            
            # Submit to workflow engine
            await self.workflow_engine.submit_workflow(workflow)
            
            # Track workflow for client
            if sid in self.clients:
                self.clients[sid]['workflows'].append(workflow.id)
            
            # Confirm submission
            await self.sio.emit('workflow:submitted', {
                'workflow_id': workflow.id,
                'status': 'queued',
                'total_tasks': len(workflow.tasks),
                'timestamp': datetime.utcnow().isoformat()
            }, room=sid)
            
            logger.info(f"Workflow submitted: {workflow.id} ({len(workflow.tasks)} tasks)")
            
        except Exception as e:
            logger.error(f"Error submitting workflow: {e}")
            await self._send_error(sid, f"Failed to submit workflow: {e}")
    
    async def _handle_workflow_status(self, sid, data):
        """Handle workflow status request"""
        try:
            workflow_id = data.get('workflow_id')
            if not workflow_id:
                await self._send_error(sid, 'Missing workflow_id')
                return
            
            status = await self.workflow_engine.get_workflow_status(workflow_id)
            
            await self.sio.emit('workflow:status_response', {
                'workflow_id': workflow_id,
                'status': status
            }, room=sid)
            
        except Exception as e:
            logger.error(f"Error getting workflow status: {e}")
            await self._send_error(sid, f"Failed to get workflow status: {e}")
    
    async def _handle_workflow_cancel(self, sid, data):
        """Handle workflow cancellation"""
        try:
            workflow_id = data.get('workflow_id')
            if not workflow_id:
                await self._send_error(sid, 'Missing workflow_id')
                return
            
            await self.workflow_engine.cancel_workflow(workflow_id)
            
            await self.sio.emit('workflow:cancelled', {
                'workflow_id': workflow_id,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f"workflow:{workflow_id}")
            
            logger.info(f"Workflow cancelled: {workflow_id}")
            
        except Exception as e:
            logger.error(f"Error cancelling workflow: {e}")
            await self._send_error(sid, f"Failed to cancel workflow: {e}")
    
    # ===================
    # Provider Handlers
    # ===================
    
    async def _handle_provider_register(self, sid, data):
        """Handle provider registration"""
        try:
            provider_info = data.get('provider')
            if not provider_info:
                await self._send_error(sid, 'Missing provider data')
                return
            
            # Register provider
            provider_id = await self.provider_manager.register_provider(sid, provider_info)
            
            # Update client type
            if sid in self.clients:
                self.clients[sid]['type'] = 'provider'
                self.clients[sid]['provider_id'] = provider_id
            
            # Confirm registration
            await self.sio.emit('provider:registered', {
                'provider_id': provider_id,
                'status': 'active',
                'timestamp': datetime.utcnow().isoformat()
            }, room=sid)
            
            logger.info(f"Provider registered: {provider_info.get('name')} ({provider_id})")
            
            # Notify workflow engine about new provider
            await self.workflow_engine.on_provider_available(provider_id)
            
        except Exception as e:
            logger.error(f"Error registering provider: {e}")
            await self._send_error(sid, f"Failed to register provider: {e}")
    
    async def _handle_provider_heartbeat(self, sid, data):
        """Handle provider heartbeat"""
        provider_id = data.get('provider_id')
        if provider_id:
            await self.provider_manager.update_heartbeat(provider_id)
    
    async def _handle_provider_capabilities(self, sid, data):
        """Handle provider capabilities update"""
        try:
            provider_id = data.get('provider_id')
            capabilities = data.get('capabilities', {})
            
            if provider_id:
                await self.provider_manager.update_capabilities(provider_id, capabilities)
                
        except Exception as e:
            logger.error(f"Error updating provider capabilities: {e}")
    
    # ================
    # Task Handlers
    # ================
    
    async def _handle_task_accepted(self, sid, data):
        """Handle task acceptance by provider"""
        task_id = data.get('task_id')
        provider_id = data.get('provider_id')
        
        if task_id and provider_id:
            await self.workflow_engine.on_task_accepted(task_id, provider_id)
            logger.debug(f"Task accepted: {task_id} by {provider_id}")
    
    async def _handle_task_progress(self, sid, data):
        """Handle task progress update"""
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        progress = data.get('progress', {})
        
        if workflow_id:
            # Broadcast progress to workflow watchers
            await self.sio.emit('task:progress', {
                'task_id': task_id,
                'progress': progress,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f"workflow:{workflow_id}")
    
    async def _handle_task_completed(self, sid, data):
        """Handle task completion"""
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        result = data.get('result')
        
        if task_id and workflow_id:
            # Notify workflow engine
            await self.workflow_engine.on_task_completed(task_id, workflow_id, result)
            
            # Broadcast to workflow watchers
            await self.sio.emit('task:completed', {
                'task_id': task_id,
                'result': result,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f"workflow:{workflow_id}")
            
            logger.debug(f"Task completed: {task_id}")
    
    async def _handle_task_failed(self, sid, data):
        """Handle task failure"""
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        error = data.get('error')
        
        if task_id and workflow_id:
            # Notify workflow engine
            await self.workflow_engine.on_task_failed(task_id, workflow_id, error)
            
            # Broadcast to workflow watchers
            await self.sio.emit('task:failed', {
                'task_id': task_id,
                'error': error,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f"workflow:{workflow_id}")
            
            logger.warning(f"Task failed: {task_id} - {error}")
    
    # =================
    # Helper Methods
    # =================
    
    async def _send_error(self, sid: str, message: str):
        """Send error message to client"""
        await self.sio.emit('error', {
            'message': message,
            'timestamp': datetime.utcnow().isoformat()
        }, room=sid)
    
    async def broadcast_workflow_completed(self, workflow_id: str, status: str, results: Dict):
        """Broadcast workflow completion"""
        await self.sio.emit('workflow:completed', {
            'workflow_id': workflow_id,
            'status': status,
            'results': results,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f"workflow:{workflow_id}")
        
        logger.info(f"Workflow completed: {workflow_id} ({status})")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics"""
        return {
            'running': self._running,
            'connected_clients': len(self.clients),
            'registered_providers': self.provider_manager.get_provider_count(),
            'active_workflows': len(self.workflow_rooms),
            'queued_tasks': self.task_queue.get_queue_size(),
            'uptime': datetime.utcnow().isoformat()
        }