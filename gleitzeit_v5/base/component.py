"""
Base SocketIOComponent class for all Gleitzeit components

Provides common functionality like connection management, event correlation,
health checks, and graceful shutdown.
"""

import asyncio
import logging
import uuid
import signal
import socket
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from abc import ABC, abstractmethod

import socketio

from .config import ComponentConfig
from .events import CorrelationTracker, get_event_registry

logger = logging.getLogger(__name__)


class SocketIOComponent(ABC):
    """
    Base class for all Gleitzeit Socket.IO components
    
    Provides:
    - Connection management to central hub
    - Event correlation tracking
    - Health monitoring
    - Graceful shutdown
    - Component registration
    """
    
    def __init__(
        self,
        component_type: str,
        component_id: Optional[str] = None,
        config: Optional[ComponentConfig] = None
    ):
        self.component_type = component_type
        self.component_id = component_id or self._generate_component_id()
        self.config = config or ComponentConfig()
        
        # Socket.IO client
        self.sio = socketio.AsyncClient(
            logger=logger.getChild('socketio'),
            engineio_logger=logger.getChild('engineio')
        )
        
        # Component state
        self.connected = False
        self.registered = False
        self.running = False
        self.shutdown_event = asyncio.Event()
        
        # Event correlation
        self.correlation_tracker = CorrelationTracker()
        
        # Event registry
        self.event_registry = get_event_registry()
        
        # Health monitoring
        self.health_metrics = {
            'started_at': datetime.utcnow(),
            'events_processed': 0,
            'events_emitted': 0,
            'last_heartbeat': None,
            'status': 'initializing'
        }
        
        # Setup base event handlers
        self._setup_base_events()
        
        # Setup component-specific event handlers
        self.setup_events()
        
        logger.info(f"Initialized {component_type} component: {self.component_id}")
    
    def _generate_component_id(self) -> str:
        """Generate unique component ID"""
        hostname = socket.gethostname()
        short_uuid = uuid.uuid4().hex[:8]
        return f"{self.component_type}-{hostname}-{short_uuid}"
    
    def _setup_base_events(self):
        """Setup base Socket.IO event handlers common to all components"""
        
        @self.sio.event
        async def connect():
            """Handle connection to central hub"""
            self.connected = True
            self.health_metrics['status'] = 'connected'
            logger.info(f"Connected to central hub: {self.config.hub_url}")
            
            # Register component with central hub
            await self._register_component()
        
        @self.sio.event
        async def disconnect():
            """Handle disconnection from central hub"""
            self.connected = False
            self.registered = False
            self.health_metrics['status'] = 'disconnected'
            logger.warning("Disconnected from central hub")
            
            # Attempt reconnection if still running
            if self.running:
                logger.info("Attempting to reconnect...")
                await asyncio.sleep(5)
                if self.running:
                    await self._connect()
        
        @self.sio.on('component_registered')
        async def handle_registration_confirmation(data):
            """Handle component registration confirmation"""
            if data.get('component_id') == self.component_id:
                self.registered = True
                self.health_metrics['status'] = 'registered'
                logger.info(f"Component registered successfully: {self.component_id}")
                
                # Component is now ready
                await self.on_ready()
        
        @self.sio.on('heartbeat')
        async def handle_heartbeat(data):
            """Handle heartbeat from central hub"""
            self.health_metrics['last_heartbeat'] = datetime.utcnow()
            
            # Respond with health status
            await self.emit_with_correlation('heartbeat_response', {
                'component_id': self.component_id,
                'status': 'healthy',
                'metrics': self._get_health_metrics()
            })
        
        @self.sio.on('shutdown_request')
        async def handle_shutdown_request(data):
            """Handle shutdown request from central hub"""
            logger.info(f"Shutdown requested by central hub: {data.get('reason', 'unknown')}")
            await self.shutdown()
    
    async def _register_component(self):
        """Register this component with the central hub"""
        registration_data = {
            'component_type': self.component_type,
            'component_id': self.component_id,
            'capabilities': self.get_capabilities(),
            'version': '0.0.1',
            'hostname': socket.gethostname(),
            'process_id': asyncio.current_task().get_name() if asyncio.current_task() else 'unknown'
        }
        
        await self.emit_with_correlation('register_component', registration_data)
        logger.info(f"Sent registration request for {self.component_id}")
    
    async def emit_with_correlation(
        self, 
        event_name: str, 
        data: Dict[str, Any], 
        correlation_id: Optional[str] = None,
        validate_schema: bool = True
    ):
        """Emit event with correlation tracking and optional schema validation"""
        # Simple event validation if enabled
        if validate_schema:
            if not self.event_registry.is_valid_event(event_name):
                logger.warning(f"Unknown event being emitted: {event_name}")
                # Log but still emit - allows for dynamic events
        
        # Generate correlation ID if not provided
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        
        # Add correlation metadata
        enhanced_data = {
            **data,
            '_correlation_id': correlation_id,
            '_source_component': self.component_id,
            '_timestamp': datetime.utcnow().isoformat(),
            '_event_sequence': self.health_metrics['events_emitted']
        }
        
        # Track correlation
        self.correlation_tracker.track_outgoing(correlation_id, event_name, data)
        
        # Emit event
        await self.sio.emit(event_name, enhanced_data)
        
        # Update metrics
        self.health_metrics['events_emitted'] += 1
        
        logger.debug(f"Emitted event {event_name} with correlation {correlation_id}")
    
    def _get_health_metrics(self) -> Dict[str, Any]:
        """Get current health metrics"""
        uptime = (datetime.utcnow() - self.health_metrics['started_at']).total_seconds()
        
        return {
            **self.health_metrics,
            'uptime_seconds': uptime,
            'started_at': self.health_metrics['started_at'].isoformat(),
            'last_heartbeat': self.health_metrics['last_heartbeat'].isoformat() if self.health_metrics['last_heartbeat'] else None,
            'connected': self.connected,
            'registered': self.registered,
            'running': self.running
        }
    
    async def _connect(self):
        """Connect to central hub"""
        try:
            await self.sio.connect(self.config.hub_url)
        except Exception as e:
            logger.error(f"Failed to connect to central hub {self.config.hub_url}: {e}")
            raise
    
    async def start(self):
        """Start the component"""
        if self.running:
            logger.warning(f"Component {self.component_id} already running")
            return
        
        self.running = True
        self.health_metrics['status'] = 'starting'
        
        logger.info(f"Starting {self.component_type} component: {self.component_id}")
        
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()
        
        try:
            # Connect to central hub
            await self._connect()
            
            # Wait until shutdown is requested
            await self.shutdown_event.wait()
            
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.error(f"Component error: {e}")
            raise
        finally:
            await self._cleanup()
    
    async def shutdown(self):
        """Shutdown the component gracefully"""
        if not self.running:
            return
        
        logger.info(f"Shutting down {self.component_type} component: {self.component_id}")
        
        self.running = False
        self.health_metrics['status'] = 'shutting_down'
        
        # Component-specific cleanup
        try:
            await self.on_shutdown()
        except Exception as e:
            logger.error(f"Error during component shutdown: {e}")
        
        # Signal shutdown
        self.shutdown_event.set()
    
    async def _cleanup(self):
        """Final cleanup"""
        if self.connected:
            # Send goodbye message
            try:
                await self.emit_with_correlation('component_disconnecting', {
                    'component_id': self.component_id,
                    'reason': 'graceful_shutdown'
                })
                await asyncio.sleep(0.1)  # Give time for message to send
            except:
                pass
            
            # Disconnect from hub
            await self.sio.disconnect()
        
        self.health_metrics['status'] = 'stopped'
        logger.info(f"Component {self.component_id} stopped")
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}")
            asyncio.create_task(self.shutdown())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    # Abstract methods that subclasses must implement
    
    @abstractmethod
    def setup_events(self):
        """Setup component-specific Socket.IO event handlers"""
        pass
    
    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """Return list of capabilities this component provides"""
        pass
    
    @abstractmethod
    async def on_ready(self):
        """Called when component is registered and ready"""
        pass
    
    @abstractmethod
    async def on_shutdown(self):
        """Called during graceful shutdown for component-specific cleanup"""
        pass


# Convenience function to run a component
async def run_component(component: SocketIOComponent):
    """Run a component until shutdown"""
    try:
        await component.start()
    except KeyboardInterrupt:
        logger.info("Shutting down due to keyboard interrupt")
    except Exception as e:
        logger.error(f"Component failed: {e}")
        raise
    finally:
        await component.shutdown()