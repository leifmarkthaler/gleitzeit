"""
CLI Configuration Management - Simplified for SystemManager
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SystemConfig:
    """SystemManager connection configuration"""
    host: str = "localhost"
    port: int = 8000
    timeout: int = 60
    

@dataclass
class CLIConfig:
    """CLI configuration"""
    system: SystemConfig
    log_level: str = "info"
    
    @classmethod
    def default(cls) -> 'CLIConfig':
        """Create default configuration"""
        return cls(
            system=SystemConfig(),
            log_level="info"
        )
    
    @classmethod
    def from_env(cls) -> 'CLIConfig':
        """Create configuration from environment variables"""
        return cls(
            system=SystemConfig(
                host=os.getenv('GLEITZEIT_HOST', 'localhost'),
                port=int(os.getenv('GLEITZEIT_PORT', '8000')),
                timeout=int(os.getenv('GLEITZEIT_TIMEOUT', '60'))
            ),
            log_level=os.getenv('GLEITZEIT_LOG_LEVEL', 'info')
        )
    
    def save(self, path: Path) -> None:
        """Save configuration to YAML file"""
        config_dict = {
            'system': {
                'host': self.system.host,
                'port': self.system.port,
                'timeout': self.system.timeout
            },
            'log_level': self.log_level
        }
        
        path.parent.mkdir(exist_ok=True)
        with open(path, 'w') as f:
            yaml.dump(config_dict, f, default_flow_style=False, indent=2)
    
    @classmethod
    def load(cls, path: Path) -> 'CLIConfig':
        """Load configuration from YAML file"""
        if not path.exists():
            config = cls.default()
            config.save(path)
            return config
        
        with open(path, 'r') as f:
            data = yaml.safe_load(f) or {}
        
        return cls(
            system=SystemConfig(
                host=data.get('system', {}).get('host', 'localhost'),
                port=data.get('system', {}).get('port', 8000),
                timeout=data.get('system', {}).get('timeout', 60)
            ),
            log_level=data.get('log_level', 'info')
        )


def get_config_path() -> Path:
    """Get default configuration file path"""
    if env_config := os.getenv('GLEITZEIT_CONFIG'):
        return Path(env_config)
    
    config_dir = Path.home() / '.gleitzeit'
    config_dir.mkdir(exist_ok=True)
    return config_dir / 'config.yaml'