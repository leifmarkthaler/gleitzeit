"""
Socket.IO server for real-time cluster coordination
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from contextlib import asynccontextmanager

import socketio
from aiohttp import web

from ..core.workflow import WorkflowStatus
from ..core.task import TaskStatus
from ..storage.redis_client import RedisClient


logger = logging.getLogger(__name__)


class SocketIOServer:
    """
    Socket.IO server for Gleitzeit cluster coordination
    
    Provides real-time event broadcasting and coordination between
    cluster components including executors, dashboards, and cluster managers.
    """
    
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        redis_url: str = "redis://localhost:6379",
        cors_allowed_origins: str = "*",
        auth_enabled: bool = False
    ):
        """
        Initialize Socket.IO server
        
        Args:
            host: Server host address
            port: Server port
            redis_url: Redis URL for pub/sub and persistence
            cors_allowed_origins: CORS origins (comma-separated or *)
            auth_enabled: Enable authentication
        """
        self.host = host
        self.port = port
        self.auth_enabled = auth_enabled
        
        # Initialize Socket.IO server with async mode
        self.sio = socketio.AsyncServer(
            async_mode='aiohttp',
            cors_allowed_origins=cors_allowed_origins,
            logger=logger,
            engineio_logger=False
        )
        
        # Initialize aiohttp app
        self.app = web.Application()
        self.sio.attach(self.app)
        
        # Redis client for persistence
        self.redis_client = RedisClient(redis_url=redis_url)
        
        # Connection tracking
        self.connected_clients: Dict[str, Dict[str, Any]] = {}
        self.executor_nodes: Dict[str, Dict[str, Any]] = {}
        self.external_service_nodes: Dict[str, Dict[str, Any]] = {}
        self.workflow_rooms: Dict[str, Set[str]] = {}
        
        # Monitoring tracking
        self.monitoring_clients: Dict[str, Dict[str, Any]] = {}
        self.metrics_history: Dict[str, List[Dict[str, Any]]] = {
            'cluster_metrics': [],
            'node_metrics': [],
            'task_metrics': [],
            'workflow_metrics': []
        }
        
        # Real-time monitoring state
        self._metrics_broadcast_task: Optional[asyncio.Task] = None
        self._metrics_interval = 2.0  # seconds
        
        # Setup event handlers
        self._setup_handlers()
        
        # Setup HTTP routes
        self._setup_routes()
        
        self.runner = None
        self.site = None
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        # Connection events
        self.sio.on('connect', namespace='/cluster')(self.handle_connect)
        self.sio.on('disconnect', namespace='/cluster')(self.handle_disconnect)
        self.sio.on('authenticate', namespace='/cluster')(self.handle_authenticate)
        
        # Workflow events
        self.sio.on('workflow:submit', namespace='/cluster')(self.handle_workflow_submit)
        self.sio.on('workflow:cancel', namespace='/cluster')(self.handle_workflow_cancel)
        self.sio.on('workflow:status', namespace='/cluster')(self.handle_workflow_status)
        
        # Task events
        self.sio.on('task:completed', namespace='/cluster')(self.handle_task_completed)
        self.sio.on('task:failed', namespace='/cluster')(self.handle_task_failed)
        self.sio.on('task:progress', namespace='/cluster')(self.handle_task_progress)
        self.sio.on('task:accepted', namespace='/cluster')(self.handle_task_accepted)
        
        # Node events
        self.sio.on('node:register', namespace='/cluster')(self.handle_node_register)
        self.sio.on('node:heartbeat', namespace='/cluster')(self.handle_node_heartbeat)
        self.sio.on('node:status', namespace='/cluster')(self.handle_node_status)
        
        # Cluster events
        self.sio.on('cluster:stats', namespace='/cluster')(self.handle_cluster_stats)
        
        # Monitoring events
        self.sio.on('monitor:subscribe', namespace='/cluster')(self.handle_monitor_subscribe)
        self.sio.on('monitor:unsubscribe', namespace='/cluster')(self.handle_monitor_unsubscribe)
        self.sio.on('monitor:get_metrics', namespace='/cluster')(self.handle_monitor_get_metrics)
    
    def _setup_routes(self):
        """Setup HTTP routes for health checks and monitoring"""
        from pathlib import Path
        
        async def health_check(request):
            """Health check endpoint"""
            return web.json_response({
                'status': 'healthy',
                'connected_clients': len(self.connected_clients),
                'executor_nodes': len(self.executor_nodes),
                'timestamp': datetime.utcnow().isoformat()
            })
        
        async def metrics(request):
            """Metrics endpoint"""
            stats = await self.get_server_stats()
            return web.json_response(stats)
        
        async def dashboard(request):
            """Serve dashboard HTML"""
            dashboard_path = Path(__file__).parent.parent.parent / "dashboard" / "index.html"
            if dashboard_path.exists():
                return web.FileResponse(dashboard_path)
            else:
                return web.Response(text="Dashboard not found", status=404)
        
        # API routes
        self.app.router.add_get('/health', health_check)
        self.app.router.add_get('/metrics', metrics)
        
        # Dashboard routes
        self.app.router.add_get('/', dashboard)
        self.app.router.add_get('/dashboard', dashboard)
        
        # Static files
        dashboard_static = Path(__file__).parent.parent.parent / "dashboard" / "static"
        if dashboard_static.exists():
            self.app.router.add_static('/static/', dashboard_static)
    
    async def start(self):
        """Start Socket.IO server"""
        try:
            # Connect to Redis
            await self.redis_client.connect()
            logger.info(f"Connected to Redis")
            
            # Setup aiohttp runner
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            
            # Start site
            self.site = web.TCPSite(self.runner, self.host, self.port)
            await self.site.start()
            
            logger.info(f"🚀 Socket.IO server started on http://{self.host}:{self.port}")
            print(f"🚀 Socket.IO server started on http://{self.host}:{self.port}")
            
            # Start metrics broadcasting
            self._metrics_broadcast_task = asyncio.create_task(self._metrics_broadcast_loop())
            
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            raise
    
    async def stop(self):
        """Stop Socket.IO server"""
        # Stop metrics broadcasting
        if self._metrics_broadcast_task:
            self._metrics_broadcast_task.cancel()
            try:
                await self._metrics_broadcast_task
            except asyncio.CancelledError:
                pass
        
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        
        await self.redis_client.disconnect()
        
        logger.info("Socket.IO server stopped")
        print("🛑 Socket.IO server stopped")
    
    # ========================
    # Connection Handlers
    # ========================
    
    async def handle_connect(self, sid, environ):
        """Handle client connection"""
        logger.info(f"Client connected: {sid}")
        
        # Store client info
        self.connected_clients[sid] = {
            'sid': sid,
            'connected_at': datetime.utcnow(),
            'authenticated': not self.auth_enabled,  # Auto-auth if disabled
            'client_type': None,
            'metadata': {}
        }
        
        # Send welcome message
        await self.sio.emit(
            'connected',
            {'message': 'Connected to Gleitzeit cluster', 'sid': sid},
            room=sid,
            namespace='/cluster'
        )
        
        return True
    
    async def handle_disconnect(self, sid):
        """Handle client disconnection"""
        logger.info(f"Client disconnected: {sid}")
        
        # Check if it's an executor node
        if sid in self.executor_nodes:
            node_info = self.executor_nodes[sid]
            del self.executor_nodes[sid]
            
            # Notify about node disconnection
            await self.broadcast_event('node:disconnected', {
                'node_id': node_info['node_id'],
                'name': node_info['name'],
                'node_type': 'executor',
                'timestamp': datetime.utcnow().isoformat()
            })
        
        # Check if it's an external service node
        if sid in self.external_service_nodes:
            service_info = self.external_service_nodes[sid]
            del self.external_service_nodes[sid]
            
            # Notify about external service disconnection
            await self.broadcast_event('external_service:disconnected', {
                'service_id': service_info['service_id'],
                'service_name': service_info['service_name'],
                'node_type': 'external_service',
                'capabilities': service_info.get('capabilities', []),
                'timestamp': datetime.utcnow().isoformat()
            })
        
        # Remove from connected clients
        if sid in self.connected_clients:
            del self.connected_clients[sid]
        
        # Remove from all rooms
        for room_id, members in self.workflow_rooms.items():
            if sid in members:
                members.remove(sid)
    
    async def handle_authenticate(self, sid, data):
        """Handle client authentication"""
        if not self.auth_enabled:
            # Authentication disabled, auto-approve
            self.connected_clients[sid]['authenticated'] = True
            self.connected_clients[sid]['client_type'] = data.get('client_type', 'unknown')
            
            await self.sio.emit(
                'authenticated',
                {'success': True},
                room=sid,
                namespace='/cluster'
            )
            return
        
        # TODO: Implement proper authentication
        token = data.get('token')
        if self._validate_token(token):
            self.connected_clients[sid]['authenticated'] = True
            self.connected_clients[sid]['client_type'] = data.get('client_type', 'unknown')
            
            await self.sio.emit(
                'authenticated',
                {'success': True},
                room=sid,
                namespace='/cluster'
            )
        else:
            await self.sio.emit(
                'authentication_failed',
                {'error': 'Invalid token'},
                room=sid,
                namespace='/cluster'
            )
    
    def _validate_token(self, token: str) -> bool:
        """Validate authentication token"""
        # TODO: Implement proper token validation
        return token == "demo_token"
    
    # ========================
    # Workflow Handlers
    # ========================
    
    async def handle_workflow_submit(self, sid, data):
        """Handle workflow submission"""
        workflow_id = data.get('workflow_id')
        
        logger.info(f"Workflow submitted: {workflow_id}")
        
        # Create workflow room
        room_id = f"workflow:{workflow_id}"
        await self.sio.enter_room(sid, room_id, namespace='/cluster')
        
        if room_id not in self.workflow_rooms:
            self.workflow_rooms[room_id] = set()
        self.workflow_rooms[room_id].add(sid)
        
        # Broadcast workflow started event
        await self.broadcast_event('workflow:started', {
            'workflow_id': workflow_id,
            'name': data.get('name'),
            'total_tasks': len(data.get('tasks', [])),
            'timestamp': datetime.utcnow().isoformat()
        }, room=room_id)
        
        # Assign tasks to executors
        await self._assign_workflow_tasks(workflow_id, data.get('tasks', []))
    
    async def handle_workflow_cancel(self, sid, data):
        """Handle workflow cancellation"""
        workflow_id = data.get('workflow_id')
        
        logger.info(f"Workflow cancelled: {workflow_id}")
        
        # Update Redis
        if self.redis_client:
            await self.redis_client.update_workflow_status(
                workflow_id,
                WorkflowStatus.CANCELLED
            )
        
        # Broadcast cancellation
        room_id = f"workflow:{workflow_id}"
        await self.broadcast_event('workflow:cancelled', {
            'workflow_id': workflow_id,
            'timestamp': datetime.utcnow().isoformat()
        }, room=room_id)
    
    async def handle_workflow_status(self, sid, data):
        """Handle workflow status request"""
        workflow_id = data.get('workflow_id')
        
        # Get status from Redis
        if self.redis_client:
            workflow_data = await self.redis_client.get_workflow(workflow_id)
            
            await self.sio.emit(
                'workflow:status_response',
                {
                    'workflow_id': workflow_id,
                    'status': workflow_data
                },
                room=sid,
                namespace='/cluster'
            )
    
    async def _assign_workflow_tasks(self, workflow_id: str, tasks: List[Dict[str, Any]]):
        """Assign workflow tasks to available executors"""
        for task in tasks:
            # Find suitable executor
            executor_sid = await self._find_executor_for_task(task)
            
            if executor_sid:
                # Assign task to executor
                await self.sio.emit(
                    'task:assign',
                    {
                        'task_id': task['task_id'],
                        'workflow_id': workflow_id,
                        'task_type': task['task_type'],
                        'parameters': task.get('parameters', {}),
                        'timeout': task.get('timeout', 300)
                    },
                    room=executor_sid,
                    namespace='/cluster'
                )
                
                logger.info(f"Task {task['task_id']} assigned to executor {executor_sid}")
            else:
                logger.warning(f"No executor available for task {task['task_id']}")
    
    async def _find_executor_for_task(self, task: Dict[str, Any]) -> Optional[str]:
        """Find suitable executor for task"""
        task_type = task.get('task_type')
        
        # Find executor with matching capabilities
        for sid, node_info in self.executor_nodes.items():
            capabilities = node_info.get('capabilities', {})
            supported_types = capabilities.get('task_types', [])
            
            if task_type in supported_types:
                # Check if node is not overloaded
                current_tasks = node_info.get('current_tasks', 0)
                max_tasks = capabilities.get('max_concurrent_tasks', 1)
                
                if current_tasks < max_tasks:
                    return sid
        
        return None
    
    # ========================
    # Task Handlers
    # ========================
    
    async def handle_task_accepted(self, sid, data):
        """Handle task acceptance by executor"""
        task_id = data.get('task_id')
        node_id = data.get('node_id')
        
        logger.info(f"Task {task_id} accepted by node {node_id}")
        
        # Update executor's current tasks
        if sid in self.executor_nodes:
            self.executor_nodes[sid]['current_tasks'] = \
                self.executor_nodes[sid].get('current_tasks', 0) + 1
    
    async def handle_task_progress(self, sid, data):
        """Handle task progress update"""
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        progress = data.get('progress', 0)
        
        # Broadcast progress to workflow room
        room_id = f"workflow:{workflow_id}"
        await self.broadcast_event('task:progress', {
            'task_id': task_id,
            'workflow_id': workflow_id,
            'progress': progress,
            'message': data.get('message', ''),
            'timestamp': datetime.utcnow().isoformat()
        }, room=room_id)
    
    async def handle_task_completed(self, sid, data):
        """Handle task completion"""
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        result = data.get('result')
        
        logger.info(f"Task {task_id} completed")
        
        # Update executor's current tasks
        if sid in self.executor_nodes:
            self.executor_nodes[sid]['current_tasks'] = max(
                0, self.executor_nodes[sid].get('current_tasks', 1) - 1
            )
        
        # Store result in Redis
        if self.redis_client:
            await self.redis_client.complete_task(task_id, result=result)
        
        # Broadcast completion
        room_id = f"workflow:{workflow_id}"
        await self.broadcast_event('task:completed', {
            'task_id': task_id,
            'workflow_id': workflow_id,
            'result': result,
            'timestamp': datetime.utcnow().isoformat()
        }, room=room_id)
        
        # Check if workflow is complete
        await self._check_workflow_completion(workflow_id)
    
    async def handle_task_failed(self, sid, data):
        """Handle task failure"""
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        error = data.get('error')
        
        logger.error(f"Task {task_id} failed: {error}")
        
        # Update executor's current tasks
        if sid in self.executor_nodes:
            self.executor_nodes[sid]['current_tasks'] = max(
                0, self.executor_nodes[sid].get('current_tasks', 1) - 1
            )
        
        # Store error in Redis
        if self.redis_client:
            await self.redis_client.complete_task(task_id, error=error)
        
        # Broadcast failure
        room_id = f"workflow:{workflow_id}"
        await self.broadcast_event('task:failed', {
            'task_id': task_id,
            'workflow_id': workflow_id,
            'error': error,
            'timestamp': datetime.utcnow().isoformat()
        }, room=room_id)
    
    async def _check_workflow_completion(self, workflow_id: str):
        """Check if workflow is complete and broadcast if so"""
        if self.redis_client:
            workflow_data = await self.redis_client.get_workflow(workflow_id)
            
            if workflow_data:
                total_tasks = int(workflow_data.get('total_tasks', 0))
                completed_tasks = int(workflow_data.get('completed_tasks', 0))
                failed_tasks = int(workflow_data.get('failed_tasks', 0))
                
                if completed_tasks + failed_tasks >= total_tasks:
                    # Workflow complete
                    status = 'completed' if failed_tasks == 0 else 'failed'
                    
                    room_id = f"workflow:{workflow_id}"
                    await self.broadcast_event('workflow:completed', {
                        'workflow_id': workflow_id,
                        'status': status,
                        'completed_tasks': completed_tasks,
                        'failed_tasks': failed_tasks,
                        'timestamp': datetime.utcnow().isoformat()
                    }, room=room_id)
    
    # ========================
    # Node Handlers
    # ========================
    
    async def handle_node_register(self, sid, data):
        """Handle node registration (executor nodes and external services)"""
        node_id = data.get('node_id')
        name = data.get('name')
        capabilities = data.get('capabilities', {})
        node_type = data.get('node_type', 'executor')
        
        logger.info(f"{node_type.title()} registered: {name} ({node_id})")
        
        if node_type == 'external_service':
            # Store external service info
            self.external_service_nodes[sid] = {
                'sid': sid,
                'service_id': node_id,
                'service_name': name,
                'node_type': 'external_service',
                'capabilities': capabilities.get('service_capabilities', []),
                'task_types': capabilities.get('task_types', []),
                'status': 'ready',
                'current_tasks': 0,
                'max_tasks': capabilities.get('max_concurrent_tasks', 10),
                'registered_at': datetime.utcnow(),
                'last_heartbeat': datetime.utcnow()
            }
            
            # Broadcast external service registration
            await self.broadcast_event('external_service:registered', {
                'service_id': node_id,
                'service_name': name,
                'node_type': 'external_service',
                'capabilities': capabilities.get('service_capabilities', []),
                'task_types': capabilities.get('task_types', []),
                'max_concurrent_tasks': capabilities.get('max_concurrent_tasks', 10),
                'timestamp': datetime.utcnow().isoformat()
            })
        else:
            # Store regular executor node info
            self.executor_nodes[sid] = {
                'sid': sid,
                'node_id': node_id,
                'name': name,
                'node_type': 'executor',
                'capabilities': capabilities,
                'status': 'ready',
                'current_tasks': 0,
                'registered_at': datetime.utcnow(),
                'last_heartbeat': datetime.utcnow()
            }
            
            # Broadcast node registration
            await self.broadcast_event('node:registered', {
                'node_id': node_id,
                'name': name,
                'node_type': 'executor',
                'capabilities': capabilities,
                'timestamp': datetime.utcnow().isoformat()
            })
    
    async def handle_node_heartbeat(self, sid, data):
        """Handle node heartbeat (executor nodes and external services)"""
        node_type = data.get('node_type', 'executor')
        
        if sid in self.executor_nodes and node_type == 'executor':
            # Handle executor node heartbeat
            self.executor_nodes[sid]['last_heartbeat'] = datetime.utcnow()
            self.executor_nodes[sid]['status'] = data.get('status', 'ready')
            self.executor_nodes[sid]['cpu_usage'] = data.get('cpu_usage')
            self.executor_nodes[sid]['memory_usage'] = data.get('memory_usage')
            self.executor_nodes[sid]['current_tasks'] = data.get('active_tasks', 0)
            
        elif sid in self.external_service_nodes and node_type == 'external_service':
            # Handle external service heartbeat
            self.external_service_nodes[sid]['last_heartbeat'] = datetime.utcnow()
            self.external_service_nodes[sid]['status'] = data.get('status', 'ready')
            self.external_service_nodes[sid]['current_tasks'] = data.get('active_tasks', 0)
            self.external_service_nodes[sid]['tasks_completed'] = data.get('tasks_completed', 0)
            self.external_service_nodes[sid]['tasks_failed'] = data.get('tasks_failed', 0)
            self.external_service_nodes[sid]['uptime_seconds'] = data.get('uptime_seconds', 0)
    
    async def handle_node_status(self, sid, data):
        """Handle node status update"""
        if sid in self.executor_nodes:
            old_status = self.executor_nodes[sid].get('status')
            new_status = data.get('status')
            
            self.executor_nodes[sid]['status'] = new_status
            
            # Broadcast status change
            await self.broadcast_event('node:status_change', {
                'node_id': self.executor_nodes[sid]['node_id'],
                'old_status': old_status,
                'new_status': new_status,
                'timestamp': datetime.utcnow().isoformat()
            })
    
    # ========================
    # Cluster Handlers
    # ========================
    
    async def handle_cluster_stats(self, sid, data=None):
        """Handle cluster statistics request"""
        stats = await self.get_server_stats()
        
        await self.sio.emit(
            'cluster:stats_response',
            stats,
            room=sid,
            namespace='/cluster'
        )
    
    async def get_server_stats(self) -> Dict[str, Any]:
        """Get server statistics"""
        redis_stats = {}
        if self.redis_client:
            try:
                redis_stats = await self.redis_client.get_cluster_stats()
            except Exception as e:
                logger.error(f"Failed to get Redis stats: {e}")
        
        return {
            'connected_clients': len(self.connected_clients),
            'authenticated_clients': sum(
                1 for c in self.connected_clients.values() 
                if c.get('authenticated')
            ),
            'executor_nodes': len(self.executor_nodes),
            'active_workflows': len(self.workflow_rooms),
            'redis_stats': redis_stats,
            'timestamp': datetime.utcnow().isoformat()
        }
    
    # ========================
    # Utility Methods
    # ========================
    
    async def broadcast_event(self, event: str, data: Dict[str, Any], room: Optional[str] = None):
        """Broadcast event to room or all clients"""
        if room:
            await self.sio.emit(event, data, room=room, namespace='/cluster')
        else:
            await self.sio.emit(event, data, namespace='/cluster')
    
    async def send_to_node(self, node_id: str, event: str, data: Dict[str, Any]):
        """Send event to specific node"""
        for sid, node_info in self.executor_nodes.items():
            if node_info['node_id'] == node_id:
                await self.sio.emit(event, data, room=sid, namespace='/cluster')
                break
    
    # ========================
    # Monitoring Handlers
    # ========================
    
    async def handle_monitor_subscribe(self, sid, data):
        """Handle monitoring subscription"""
        subscription_types = data.get('types', ['all'])  # ['node_metrics', 'task_metrics', 'workflow_metrics', 'cluster_metrics']
        
        self.monitoring_clients[sid] = {
            'sid': sid,
            'subscribed_at': datetime.utcnow(),
            'subscription_types': subscription_types,
            'last_ping': datetime.utcnow()
        }
        
        logger.info(f"Client {sid} subscribed to monitoring: {subscription_types}")
        
        # Send initial metrics
        await self._send_initial_metrics(sid, subscription_types)
        
        await self.sio.emit(
            'monitor:subscribed',
            {'message': 'Successfully subscribed to real-time monitoring', 'types': subscription_types},
            room=sid,
            namespace='/cluster'
        )
    
    async def handle_monitor_unsubscribe(self, sid, data):
        """Handle monitoring unsubscription"""
        if sid in self.monitoring_clients:
            del self.monitoring_clients[sid]
            
        await self.sio.emit(
            'monitor:unsubscribed',
            {'message': 'Unsubscribed from monitoring'},
            room=sid,
            namespace='/cluster'
        )
    
    async def handle_monitor_get_metrics(self, sid, data):
        """Handle one-time metrics request"""
        metrics_type = data.get('type', 'all')
        history_minutes = data.get('history_minutes', 5)
        
        metrics = await self._collect_metrics()
        
        # Get historical metrics
        historical_data = self._get_historical_metrics(metrics_type, history_minutes)
        
        response = {
            'current_metrics': metrics,
            'historical_metrics': historical_data,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        await self.sio.emit(
            'monitor:metrics_response',
            response,
            room=sid,
            namespace='/cluster'
        )
    
    async def _metrics_broadcast_loop(self):
        """Continuously broadcast metrics to monitoring clients"""
        try:
            while True:
                if self.monitoring_clients:
                    metrics = await self._collect_metrics()
                    
                    # Store metrics history (keep last 30 minutes)
                    timestamp = datetime.utcnow()
                    self._store_metrics_history(metrics, timestamp)
                    
                    # Broadcast to monitoring clients
                    await self._broadcast_metrics(metrics)
                
                await asyncio.sleep(self._metrics_interval)
                
        except asyncio.CancelledError:
            logger.info("Metrics broadcast loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in metrics broadcast loop: {e}")
    
    async def _collect_metrics(self) -> Dict[str, Any]:
        """Collect comprehensive system metrics"""
        import psutil
        
        # Cluster-wide metrics
        cluster_metrics = {
            'connected_clients': len(self.connected_clients),
            'executor_nodes': len(self.executor_nodes),
            'active_workflows': len(self.workflow_rooms),
            'monitoring_clients': len(self.monitoring_clients)
        }
        
        # Node metrics
        node_metrics = []
        total_cpu = 0
        total_memory = 0
        total_active_tasks = 0
        
        for sid, node_info in self.executor_nodes.items():
            node_data = {
                'node_id': node_info['node_id'],
                'name': node_info['name'],
                'status': node_info.get('status', 'unknown'),
                'cpu_usage': node_info.get('cpu_usage', 0),
                'memory_usage': node_info.get('memory_usage', 0),
                'active_tasks': node_info.get('current_tasks', 0),
                'max_tasks': node_info.get('capabilities', {}).get('max_concurrent_tasks', 1),
                'last_heartbeat': node_info.get('last_heartbeat'),
                'has_gpu': node_info.get('capabilities', {}).get('has_gpu', False),
                'uptime_seconds': (datetime.utcnow() - node_info.get('registered_at', datetime.utcnow())).total_seconds()
            }
            node_metrics.append(node_data)
            
            total_cpu += node_info.get('cpu_usage', 0)
            total_memory += node_info.get('memory_usage', 0) 
            total_active_tasks += node_info.get('current_tasks', 0)
        
        # System metrics (server host)
        try:
            system_cpu = psutil.cpu_percent(interval=0.1)
            system_memory = psutil.virtual_memory().percent
            system_disk = psutil.disk_usage('/').percent
        except:
            system_cpu = system_memory = system_disk = 0
        
        # Task queue metrics (from Redis)
        queue_metrics = {}
        if self.redis_client:
            try:
                queue_metrics = {
                    'urgent_queue': await self.redis_client.redis.llen('task_queue:urgent'),
                    'high_queue': await self.redis_client.redis.llen('task_queue:high'),
                    'normal_queue': await self.redis_client.redis.llen('task_queue:normal'),
                    'low_queue': await self.redis_client.redis.llen('task_queue:low')
                }
                queue_metrics['total_queued'] = sum(queue_metrics.values())
            except Exception as e:
                logger.warning(f"Failed to get queue metrics: {e}")
                queue_metrics = {'total_queued': 0}
        
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'cluster_metrics': cluster_metrics,
            'node_metrics': node_metrics,
            'queue_metrics': queue_metrics,
            'system_metrics': {
                'server_cpu': system_cpu,
                'server_memory': system_memory,
                'server_disk': system_disk
            },
            'aggregate_metrics': {
                'avg_node_cpu': total_cpu / max(len(node_metrics), 1),
                'avg_node_memory': total_memory / max(len(node_metrics), 1),
                'total_active_tasks': total_active_tasks,
                'cluster_utilization': total_active_tasks / max(sum(n.get('max_tasks', 1) for n in node_metrics), 1) * 100
            }
        }
    
    def _store_metrics_history(self, metrics: Dict[str, Any], timestamp: datetime):
        """Store metrics in history (keep last 30 minutes)"""
        history_limit = int(30 * 60 / self._metrics_interval)  # 30 minutes of data
        
        # Store with timestamp
        timestamped_metrics = {
            'timestamp': timestamp.isoformat(),
            **metrics
        }
        
        # Add to each category
        for category in self.metrics_history.keys():
            self.metrics_history[category].append(timestamped_metrics)
            
            # Trim to limit
            if len(self.metrics_history[category]) > history_limit:
                self.metrics_history[category] = self.metrics_history[category][-history_limit:]
    
    def _get_historical_metrics(self, metrics_type: str, minutes: int) -> List[Dict[str, Any]]:
        """Get historical metrics for specified time range"""
        if metrics_type == 'all':
            return self.metrics_history.get('cluster_metrics', [])[-int(minutes * 60 / self._metrics_interval):]
        else:
            return self.metrics_history.get(metrics_type, [])[-int(minutes * 60 / self._metrics_interval):]
    
    async def _send_initial_metrics(self, sid: str, subscription_types: List[str]):
        """Send initial metrics to newly subscribed client"""
        metrics = await self._collect_metrics()
        
        await self.sio.emit(
            'monitor:initial_metrics',
            {
                'metrics': metrics,
                'subscription_types': subscription_types,
                'update_interval_seconds': self._metrics_interval
            },
            room=sid,
            namespace='/cluster'
        )
    
    async def _broadcast_metrics(self, metrics: Dict[str, Any]):
        """Broadcast metrics to all monitoring clients"""
        if not self.monitoring_clients:
            return
        
        for sid, client_info in self.monitoring_clients.items():
            subscription_types = client_info.get('subscription_types', ['all'])
            
            # Filter metrics based on subscription
            if 'all' not in subscription_types:
                filtered_metrics = {}
                for sub_type in subscription_types:
                    if sub_type in metrics:
                        filtered_metrics[sub_type] = metrics[sub_type]
                filtered_metrics['timestamp'] = metrics['timestamp']
            else:
                filtered_metrics = metrics
            
            try:
                await self.sio.emit(
                    'monitor:metrics_update',
                    filtered_metrics,
                    room=sid,
                    namespace='/cluster'
                )
            except Exception as e:
                logger.error(f"Failed to send metrics to client {sid}: {e}")
    
    # Enhanced node heartbeat handling with detailed metrics
    async def handle_node_heartbeat(self, sid, data):
        """Handle enhanced node heartbeat with detailed metrics"""
        if sid in self.executor_nodes:
            # Update basic info
            self.executor_nodes[sid]['last_heartbeat'] = datetime.utcnow()
            self.executor_nodes[sid]['status'] = data.get('status', 'ready')
            
            # Update detailed metrics
            self.executor_nodes[sid]['cpu_usage'] = data.get('cpu_usage', 0)
            self.executor_nodes[sid]['memory_usage'] = data.get('memory_usage', 0)
            self.executor_nodes[sid]['gpu_usage'] = data.get('gpu_usage')
            self.executor_nodes[sid]['disk_usage'] = data.get('disk_usage')
            self.executor_nodes[sid]['network_io'] = data.get('network_io', {})
            self.executor_nodes[sid]['current_tasks'] = data.get('active_tasks', 0)
            
            # Store task execution metrics
            if 'task_metrics' in data:
                task_metrics = data['task_metrics']
                self.executor_nodes[sid]['task_metrics'] = task_metrics
                
                # Broadcast task metrics to monitoring clients
                await self.broadcast_event('monitor:task_metrics', {
                    'node_id': self.executor_nodes[sid]['node_id'],
                    'task_metrics': task_metrics,
                    'timestamp': datetime.utcnow().isoformat()
                })
    
    def __str__(self) -> str:
        return f"SocketIOServer(http://{self.host}:{self.port})"