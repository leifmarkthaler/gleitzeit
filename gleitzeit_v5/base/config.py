"""
Configuration management for Gleitzeit components

Provides environment-based configuration with sensible defaults.
"""

import os
import socket
import uuid
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class ComponentConfig:
    """Configuration for Gleitzeit components"""
    
    # Central Hub connection
    hub_url: str = "http://localhost:8000"
    
    # Component identification
    component_id: Optional[str] = None
    hostname: Optional[str] = None
    
    # Redis configuration (for persistence components)
    redis_url: str = "redis://localhost:6379"
    redis_db: int = 0
    
    # SQLite configuration (for single-node persistence)
    sqlite_path: str = "./gleitzeit_v5.db"
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Performance tuning
    max_concurrent_tasks: int = 10
    heartbeat_interval: int = 30
    reconnect_delay: int = 5
    
    # Security (for future use)
    auth_token: Optional[str] = None
    tls_enabled: bool = False
    
    def __post_init__(self):
        """Load configuration from environment variables"""
        
        # Central Hub
        self.hub_url = os.getenv('GLEITZEIT_HUB_URL', self.hub_url)
        
        # Component ID
        if not self.component_id:
            self.component_id = os.getenv('COMPONENT_ID')
        
        # Hostname
        if not self.hostname:
            self.hostname = os.getenv('HOSTNAME', socket.gethostname())
        
        # Redis
        self.redis_url = os.getenv('REDIS_URL', self.redis_url)
        self.redis_db = int(os.getenv('REDIS_DB', str(self.redis_db)))
        
        # SQLite
        self.sqlite_path = os.getenv('SQLITE_PATH', self.sqlite_path)
        
        # Logging
        self.log_level = os.getenv('LOG_LEVEL', self.log_level)
        
        # Performance
        self.max_concurrent_tasks = int(os.getenv('MAX_CONCURRENT_TASKS', str(self.max_concurrent_tasks)))
        self.heartbeat_interval = int(os.getenv('HEARTBEAT_INTERVAL', str(self.heartbeat_interval)))
        self.reconnect_delay = int(os.getenv('RECONNECT_DELAY', str(self.reconnect_delay)))
        
        # Security
        self.auth_token = os.getenv('GLEITZEIT_AUTH_TOKEN')
        self.tls_enabled = os.getenv('TLS_ENABLED', '').lower() in ('true', '1', 'yes')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary"""
        return {
            'hub_url': self.hub_url,
            'component_id': self.component_id,
            'hostname': self.hostname,
            'redis_url': self.redis_url,
            'redis_db': self.redis_db,
            'sqlite_path': self.sqlite_path,
            'log_level': self.log_level,
            'max_concurrent_tasks': self.max_concurrent_tasks,
            'heartbeat_interval': self.heartbeat_interval,
            'reconnect_delay': self.reconnect_delay,
            'tls_enabled': self.tls_enabled
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ComponentConfig':
        """Create configuration from dictionary"""
        return cls(**data)
    
    def validate(self) -> bool:
        """Validate configuration"""
        if not self.hub_url:
            raise ValueError("hub_url is required")
        
        if self.max_concurrent_tasks <= 0:
            raise ValueError("max_concurrent_tasks must be positive")
        
        if self.heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be positive")
        
        if self.reconnect_delay < 0:
            raise ValueError("reconnect_delay must be non-negative")
        
        return True


# Global configuration instance
default_config = ComponentConfig()


def setup_logging(config: ComponentConfig):
    """Setup logging based on configuration"""
    import logging
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper()),
        format=config.log_format
    )
    
    # Set specific loggers to appropriate levels
    logging.getLogger('socketio').setLevel(logging.WARNING)
    logging.getLogger('engineio').setLevel(logging.WARNING)
    
    # Set gleitzeit loggers to debug in development
    if config.log_level.upper() == 'DEBUG':
        logging.getLogger('gleitzeit_v5').setLevel(logging.DEBUG)