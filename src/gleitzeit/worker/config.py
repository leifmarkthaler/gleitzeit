"""
Worker Service Configuration
"""

import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class WorkerConfig:
    """Configuration for worker service"""
    
    # Pool configuration
    pool_size: int = 50
    initial_size: Optional[int] = None  # Defaults to pool_size // 2
    
    # Service configuration
    host: str = "0.0.0.0"
    port: int = 8091
    service_name: str = "gleitzeit-worker"
    
    # Client configuration
    client_mode: str = "native"
    event_mode: str = "direct"
    use_hub: bool = False  # Whether to connect to external hub
    
    # Resource configuration
    resource_service_url: Optional[str] = None
    enable_resource_client: bool = False
    
    # Persistence configuration
    redis_url: Optional[str] = None
    persistence_type: str = "memory"  # "redis" or "memory"
    
    # Health check configuration
    health_check_interval: int = 30
    enable_metrics: bool = True
    
    @classmethod
    def from_env(cls) -> 'WorkerConfig':
        """Create config from environment variables"""
        return cls(
            pool_size=int(os.environ.get('WORKER_POOL_SIZE', '50')),
            initial_size=int(os.environ.get('WORKER_INITIAL_SIZE', '0')) or None,
            host=os.environ.get('WORKER_HOST', '0.0.0.0'),
            port=int(os.environ.get('WORKER_PORT', '8091')),
            service_name=os.environ.get('WORKER_SERVICE_NAME', 'gleitzeit-worker'),
            client_mode=os.environ.get('CLIENT_MODE', 'native'),
            event_mode=os.environ.get('EVENT_MODE', 'direct'),
            resource_service_url=os.environ.get('RESOURCE_SERVICE_URL'),
            enable_resource_client=os.environ.get('ENABLE_RESOURCE_CLIENT', 'false').lower() == 'true',
            redis_url=os.environ.get('REDIS_URL'),
            persistence_type=os.environ.get('PERSISTENCE_TYPE', 'memory'),
            health_check_interval=int(os.environ.get('HEALTH_CHECK_INTERVAL', '30')),
            enable_metrics=os.environ.get('ENABLE_METRICS', 'true').lower() == 'true'
        )