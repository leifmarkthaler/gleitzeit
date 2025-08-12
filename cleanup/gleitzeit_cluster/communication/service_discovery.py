"""
Service Discovery for Gleitzeit Components

Helps components find the central Socket.IO service automatically
"""

import os
import socket
import logging
from typing import Optional, Dict, Any
from pathlib import Path
import json
import time

logger = logging.getLogger(__name__)

class ServiceDiscovery:
    """
    Service discovery helper for finding Gleitzeit services
    
    Uses multiple methods to locate services:
    1. Environment variables  
    2. Local service file
    3. Default locations
    4. Network scanning (last resort)
    """
    
    def __init__(self):
        self.service_file = Path.home() / '.gleitzeit' / 'services.json'
    
    def get_socketio_url(self) -> str:
        """
        Get the Socket.IO service URL using discovery methods
        
        Returns:
            Socket.IO service URL
        """
        
        # Method 1: Environment variable (highest priority)
        if 'GLEITZEIT_SOCKETIO_URL' in os.environ:
            url = os.environ['GLEITZEIT_SOCKETIO_URL']
            logger.debug(f"Found Socket.IO URL from environment: {url}")
            return url
        
        # Method 2: Environment variables for host/port
        host = os.getenv('GLEITZEIT_SOCKETIO_HOST', 'localhost')
        port = int(os.getenv('GLEITZEIT_SOCKETIO_PORT', '8000'))
        url = f"http://{host}:{port}"
        
        # Method 3: Check if service is actually running at that location
        if self._check_service_availability(host, port):
            logger.debug(f"Found running Socket.IO service at: {url}")
            return url
        
        # Method 4: Check service registry file
        registry_url = self._get_url_from_registry()
        if registry_url and self._check_service_availability_url(registry_url):
            logger.debug(f"Found Socket.IO URL from registry: {registry_url}")
            return registry_url
        
        # Method 5: Scan common ports on localhost (last resort)
        discovered_url = self._scan_localhost()
        if discovered_url:
            logger.debug(f"Discovered Socket.IO service at: {discovered_url}")
            return discovered_url
        
        # Method 6: Return default and hope for the best
        logger.warning(f"Could not discover Socket.IO service, using default: {url}")
        return url
    
    def register_service(self, service_type: str, url: str, metadata: Dict[str, Any] = None):
        """
        Register a service in the local registry
        
        Args:
            service_type: Type of service (e.g., 'socketio')
            url: Service URL
            metadata: Additional service metadata
        """
        try:
            # Ensure directory exists
            self.service_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Load existing registry
            services = {}
            if self.service_file.exists():
                try:
                    with open(self.service_file, 'r') as f:
                        services = json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Could not read service registry: {e}")
                    services = {}
            
            # Update registry
            services[service_type] = {
                'url': url,
                'registered_at': time.time(),
                'metadata': metadata or {}
            }
            
            # Save registry
            with open(self.service_file, 'w') as f:
                json.dump(services, f, indent=2)
            
            logger.debug(f"Registered {service_type} service at {url}")
            
        except Exception as e:
            logger.warning(f"Failed to register service: {e}")
    
    def _get_url_from_registry(self) -> Optional[str]:
        """Get Socket.IO URL from service registry"""
        try:
            if not self.service_file.exists():
                return None
            
            with open(self.service_file, 'r') as f:
                services = json.load(f)
            
            socketio_info = services.get('socketio')
            if socketio_info:
                # Check if registration is recent (within 1 hour)
                age = time.time() - socketio_info.get('registered_at', 0)
                if age < 3600:  # 1 hour
                    return socketio_info.get('url')
                else:
                    logger.debug("Service registry entry is stale")
            
        except Exception as e:
            logger.debug(f"Could not read service registry: {e}")
        
        return None
    
    def _check_service_availability(self, host: str, port: int) -> bool:
        """Check if a service is running at host:port"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    def _check_service_availability_url(self, url: str) -> bool:
        """Check if a service is available at URL"""
        try:
            # Extract host and port from URL
            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = parsed.hostname or 'localhost'
            port = parsed.port or 80
            return self._check_service_availability(host, port)
        except Exception:
            return False
    
    def _scan_localhost(self) -> Optional[str]:
        """Scan common ports on localhost for Socket.IO service"""
        common_ports = [8000, 8001, 8002, 8003, 3000, 5000]
        
        for port in common_ports:
            if self._check_service_availability('localhost', port):
                url = f"http://localhost:{port}"
                # TODO: Could add HTTP check to verify it's actually Socket.IO
                logger.debug(f"Found service on port {port}")
                return url
        
        return None

# Global service discovery instance
_service_discovery = ServiceDiscovery()

def get_socketio_url() -> str:
    """Get Socket.IO service URL (global convenience function)"""
    return _service_discovery.get_socketio_url()

def register_socketio_service(url: str, metadata: Dict[str, Any] = None):
    """Register Socket.IO service (global convenience function)"""
    _service_discovery.register_service('socketio', url, metadata)