"""
Central Event Hub for Gleitzeit V5

A pure Socket.IO event router that coordinates distributed components.
Contains no business logic - only routes events and manages component registry.
"""

import asyncio
import logging
import signal
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
import uuid

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from ..base.events import EventRouter, CorrelationTracker
from ..base.config import ComponentConfig, setup_logging

logger = logging.getLogger(__name__)


class CentralHub:
    """
    Central Event Hub for distributed Gleitzeit V5 system
    
    Responsibilities:
    - Route events between components
    - Manage component registry and discovery
    - Track event correlations for observability
    - Handle component health monitoring
    - Provide system-wide observability
    
    Does NOT:
    - Execute business logic
    - Store application state
    - Make routing decisions based on business rules
    """
    
    def __init__(
        self, 
        host: str = "0.0.0.0", 
        port: int = 8000,
        config: Optional[ComponentConfig] = None
    ):
        self.host = host
        self.port = port
        self.config = config or ComponentConfig()
        
        # Socket.IO server
        self.sio = socketio.AsyncServer(
            async_mode='asgi',
            cors_allowed_origins="*",
            logger=logger.getChild('socketio'),
            engineio_logger=logger.getChild('engineio')
        )
        
        # FastAPI app for HTTP endpoints (health, metrics)
        self.app = FastAPI(
            title="Gleitzeit V5 Central Hub",
            description="Central event router for distributed task execution",
            version="5.0.0-alpha"
        )
        
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Event routing and tracking
        self.event_router = EventRouter()
        self.correlation_tracker = CorrelationTracker()
        
        # System state
        self.running = False
        self.started_at: Optional[datetime] = None
        self.shutdown_event = asyncio.Event()
        
        # Statistics
        self.stats = {
            'events_routed': 0,
            'components_connected': 0,
            'components_registered': 0,
            'correlations_tracked': 0,
            'errors': 0
        }
        
        # Setup event handlers
        self._setup_socket_events()
        self._setup_http_endpoints()
        
        # Mount Socket.IO app
        socket_app = socketio.ASGIApp(self.sio, self.app)
        self.app.mount("/", socket_app)
        
        logger.info(f"Initialized Central Hub for {host}:{port}")
    
    def _setup_socket_events(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect(sid, environ):
            """Handle component connection"""
            self.stats['components_connected'] += 1
            
            client_info = {
                'connected_at': datetime.utcnow(),
                'address': environ.get('REMOTE_ADDR', 'unknown')
            }
            
            logger.info(f"Component connected: {sid} from {client_info['address']}")
            
            # Send welcome message
            await self.sio.emit('connected', {
                'message': 'Connected to Gleitzeit V5 Central Hub',
                'hub_version': '5.0.0-alpha',
                'server_time': datetime.utcnow().isoformat()
            }, room=sid)
        
        @self.sio.event
        async def disconnect(sid):
            """Handle component disconnection"""
            component_info = self.event_router.get_component_info(sid)
            if component_info:
                logger.info(f"Component disconnected: {component_info['id']} ({component_info['type']})")
            else:
                logger.info(f"Unknown component disconnected: {sid}")
            
            # Unregister component
            self.event_router.unregister_component(sid)
            self.stats['components_connected'] -= 1
            
            # Notify other components about disconnection
            if component_info:
                await self.sio.emit('component_disconnected', {
                    'component_id': component_info['id'],
                    'component_type': component_info['type'],
                    'disconnected_at': datetime.utcnow().isoformat()
                })
        
        @self.sio.on('register_component')
        async def handle_component_registration(sid, data):
            """Handle component registration"""
            try:
                component_type = data.get('component_type')
                component_id = data.get('component_id')
                capabilities = data.get('capabilities', [])
                
                if not component_type or not component_id:
                    await self.sio.emit('registration_error', {
                        'error': 'component_type and component_id are required'
                    }, room=sid)
                    return
                
                # Register component
                self.event_router.register_component(
                    sid=sid,
                    component_type=component_type,
                    component_id=component_id,
                    capabilities=capabilities
                )
                
                self.stats['components_registered'] += 1
                
                # Confirm registration
                await self.sio.emit('component_registered', {
                    'component_id': component_id,
                    'component_type': component_type,
                    'capabilities': capabilities,
                    'registered_at': datetime.utcnow().isoformat()
                }, room=sid)
                
                # Notify other components about new component
                await self.sio.emit('component_connected', {
                    'component_id': component_id,
                    'component_type': component_type,
                    'capabilities': capabilities
                })
                
                logger.info(f"Registered {component_type} component: {component_id} with capabilities: {capabilities}")
                
            except Exception as e:
                logger.error(f"Component registration error: {e}")
                await self.sio.emit('registration_error', {
                    'error': str(e)
                }, room=sid)
                self.stats['errors'] += 1
        
        @self.sio.on('heartbeat_response')
        async def handle_heartbeat_response(sid, data):
            """Handle heartbeat response from component"""
            try:
                component_id = data.get('component_id')
                metrics = data.get('metrics', {})
                
                # Update component health
                self.event_router.update_component_health(sid, metrics)
                
                logger.debug(f"Heartbeat received from {component_id}")
                
            except Exception as e:
                logger.error(f"Heartbeat processing error: {e}")
                self.stats['errors'] += 1
        
        @self.sio.on('route_event')
        async def handle_event_routing(sid, data):
            """Handle generic event routing request"""
            try:
                target_component_type = data.get('target_component_type')
                target_capability = data.get('target_capability')
                event_name = data.get('event_name')
                event_data = data.get('event_data', {})
                correlation_id = data.get('_correlation_id')
                
                if not event_name:
                    await self.sio.emit('routing_error', {
                        'error': 'event_name is required'
                    }, room=sid)
                    return
                
                # Find target component
                target_sid = None
                if target_component_type:
                    target_sid = self.event_router.find_component_by_type(target_component_type)
                elif target_capability:
                    target_sid = self.event_router.find_component_for_capability(target_capability)
                
                if not target_sid:
                    await self.sio.emit('routing_error', {
                        'error': f'No component found for type={target_component_type} capability={target_capability}',
                        'correlation_id': correlation_id
                    }, room=sid)
                    return
                
                # Route the event
                await self.sio.emit(event_name, event_data, room=target_sid)
                self.stats['events_routed'] += 1
                
                # Track correlation if provided
                if correlation_id:
                    self.correlation_tracker.track_outgoing(
                        correlation_id=correlation_id,
                        event_name=event_name,
                        data=event_data,
                        source_component=data.get('_source_component', 'unknown')
                    )
                    self.stats['correlations_tracked'] += 1
                
                logger.debug(f"Routed {event_name} from {sid} to {target_sid}")
                
            except Exception as e:
                logger.error(f"Event routing error: {e}")
                await self.sio.emit('routing_error', {
                    'error': str(e),
                    'correlation_id': data.get('_correlation_id')
                }, room=sid)
                self.stats['errors'] += 1
        
        # Catch-all event handler for observability
        @self.sio.event
        async def catch_all_events(event_name, data):
            """Log all events for observability"""
            if event_name not in ['connect', 'disconnect', 'heartbeat_response']:
                correlation_id = None
                if isinstance(data, dict):
                    correlation_id = data.get('_correlation_id')
                
                logger.debug(f"Event: {event_name} (correlation: {correlation_id})")
    
    def _setup_http_endpoints(self):
        """Setup HTTP endpoints for monitoring and management"""
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint"""
            return {
                "status": "healthy" if self.running else "stopped",
                "uptime": (datetime.utcnow() - self.started_at).total_seconds() if self.started_at else 0,
                "components_connected": self.stats['components_connected'],
                "version": "5.0.0-alpha"
            }
        
        @self.app.get("/stats")
        async def get_statistics():
            """Get hub statistics"""
            routing_stats = self.event_router.get_routing_statistics()
            correlation_stats = self.correlation_tracker.get_statistics()
            
            return {
                "hub_stats": self.stats,
                "routing_stats": routing_stats,
                "correlation_stats": correlation_stats,
                "uptime": (datetime.utcnow() - self.started_at).total_seconds() if self.started_at else 0
            }
        
        @self.app.get("/components")
        async def list_components():
            """List all connected components"""
            components = []
            
            for component_type, type_components in self.event_router.components.items():
                for sid, info in type_components.items():
                    components.append({
                        "id": info['id'],
                        "type": info['type'],
                        "capabilities": list(info['capabilities']),
                        "registered_at": info['registered_at'].isoformat(),
                        "last_seen": info['last_seen'].isoformat(),
                        "event_count": info['event_count']
                    })
            
            return {"components": components}
        
        @self.app.get("/correlations/{correlation_id}")
        async def get_correlation(correlation_id: str):
            """Get correlation details"""
            correlation = self.correlation_tracker.get_correlation(correlation_id)
            if not correlation:
                return {"error": "Correlation not found"}, 404
            
            return {
                "correlation_id": correlation.correlation_id,
                "root_event": correlation.root_event,
                "started_at": correlation.started_at.isoformat(),
                "completed": correlation.completed,
                "error": correlation.error,
                "events": [
                    {
                        "event_name": trace.event_name,
                        "timestamp": trace.timestamp.isoformat(),
                        "source_component": trace.source_component,
                        "target_component": trace.target_component,
                        "processing_time_ms": trace.processing_time_ms
                    }
                    for trace in correlation.events
                ]
            }
    
    async def _start_background_tasks(self):
        """Start background maintenance tasks"""
        
        async def send_heartbeats():
            """Send periodic heartbeats to all components"""
            while self.running:
                try:
                    await self.sio.emit('heartbeat', {
                        'timestamp': datetime.utcnow().isoformat(),
                        'hub_id': 'central-hub'
                    })
                    logger.debug("Sent heartbeat to all components")
                except Exception as e:
                    logger.error(f"Error sending heartbeats: {e}")
                
                await asyncio.sleep(self.config.heartbeat_interval)
        
        # Start background tasks
        asyncio.create_task(send_heartbeats())
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}")
            asyncio.create_task(self.shutdown())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def start(self):
        """Start the Central Hub"""
        if self.running:
            logger.warning("Central Hub already running")
            return
        
        self.running = True
        self.started_at = datetime.utcnow()
        
        logger.info(f"Starting Gleitzeit V5 Central Hub on {self.host}:{self.port}")
        
        # Setup signal handlers
        self._setup_signal_handlers()
        
        # Start background tasks
        await self._start_background_tasks()
        
        try:
            # Start uvicorn server
            config = uvicorn.Config(
                app=self.app,
                host=self.host,
                port=self.port,
                log_level=self.config.log_level.lower(),
                access_log=True
            )
            server = uvicorn.Server(config)
            
            # Run until shutdown
            await server.serve()
            
        except Exception as e:
            logger.error(f"Central Hub error: {e}")
            raise
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Shutdown the Central Hub gracefully"""
        if not self.running:
            return
        
        logger.info("Shutting down Central Hub")
        self.running = False
        
        # Notify all components about shutdown
        try:
            await self.sio.emit('hub_shutting_down', {
                'message': 'Central Hub is shutting down',
                'timestamp': datetime.utcnow().isoformat()
            })
            
            # Give components time to disconnect gracefully
            await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"Error during shutdown notification: {e}")
        
        self.shutdown_event.set()
        logger.info("Central Hub shutdown complete")


# Convenience function to run the hub
async def run_central_hub(
    host: str = "0.0.0.0",
    port: int = 8000,
    config: Optional[ComponentConfig] = None
):
    """Run the Central Hub"""
    if not config:
        config = ComponentConfig()
    
    # Setup logging
    setup_logging(config)
    
    # Create and start hub
    hub = CentralHub(host=host, port=port, config=config)
    
    try:
        await hub.start()
    except KeyboardInterrupt:
        logger.info("Shutting down due to keyboard interrupt")
    except Exception as e:
        logger.error(f"Hub failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(run_central_hub())