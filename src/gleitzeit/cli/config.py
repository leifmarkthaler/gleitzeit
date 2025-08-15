"""
CLI Configuration Management

Handles configuration profiles, cluster connections, and environment settings.
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from pydantic import BaseModel, Field
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ClusterConfig:
    """Cluster connection configuration"""
    endpoint: str = "localhost:8000"
    auth_method: str = "none"
    token: Optional[str] = None
    tls: bool = False
    timeout: int = 30


@dataclass  
class LocalConfig:
    """Local development configuration"""
    persistence: str = "sqlite"  # sqlite or redis
    db_path: str = "gleitzeit_dev.db"
    redis_host: str = "localhost"
    redis_port: int = 6379
    log_level: str = "info"
    auto_start: bool = True


@dataclass
class WorkflowConfig:
    """Workflow execution configuration"""
    default_priority: str = "normal"
    default_timeout: int = 3600
    retry_attempts: int = 3
    templates_dir: str = "~/.gleitzeit/templates"


class CLIConfig(BaseModel):
    """Main CLI configuration"""
    mode: str = Field(default="auto", pattern="^(local|cluster|auto)$")
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    local: LocalConfig = Field(default_factory=LocalConfig) 
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    profiles: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    
    class Config:
        arbitrary_types_allowed = True


def get_config_path(config_file: Optional[str] = None) -> Path:
    """Get configuration file path"""
    if config_file:
        return Path(config_file)
    
    # Check environment variable
    if env_config := os.getenv('GLEITZEIT_CONFIG'):
        return Path(env_config)
    
    # Default locations
    config_dir = Path.home() / '.gleitzeit'
    config_dir.mkdir(exist_ok=True)
    
    return config_dir / 'config.yaml'


def load_config(config_file: Optional[str] = None, profile: str = "default") -> CLIConfig:
    """Load CLI configuration from file"""
    config_path = get_config_path(config_file)
    
    if not config_path.exists():
        logger.info(f"Creating default configuration at {config_path}")
        config = create_default_config()
        save_config(config, config_path)
        return config
    
    try:
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f) or {}
        
        # Apply profile-specific overrides
        if profile != "default" and profile in config_data.get('profiles', {}):
            profile_data = config_data['profiles'][profile]
            
            # Deep merge profile data
            for section, values in profile_data.items():
                if section in config_data and isinstance(values, dict):
                    config_data[section].update(values)
                else:
                    config_data[section] = values
        
        # Convert dataclass fields
        if 'cluster' in config_data:
            config_data['cluster'] = ClusterConfig(**config_data['cluster'])
        if 'local' in config_data:
            config_data['local'] = LocalConfig(**config_data['local'])  
        if 'workflow' in config_data:
            config_data['workflow'] = WorkflowConfig(**config_data['workflow'])
            
        config = CLIConfig(**config_data)
        logger.debug(f"Loaded configuration from {config_path} with profile {profile}")
        
        return config
        
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        raise


def save_config(config: CLIConfig, config_path: Optional[Path] = None) -> None:
    """Save configuration to file"""
    if config_path is None:
        config_path = get_config_path()
    
    config_path.parent.mkdir(exist_ok=True)
    
    # Convert to serializable dict
    config_dict = {
        'mode': config.mode,
        'cluster': {
            'endpoint': config.cluster.endpoint,
            'auth_method': config.cluster.auth_method,
            'token': config.cluster.token,
            'tls': config.cluster.tls,
            'timeout': config.cluster.timeout
        },
        'local': {
            'persistence': config.local.persistence,
            'db_path': config.local.db_path,
            'redis_host': config.local.redis_host,
            'redis_port': config.local.redis_port,
            'log_level': config.local.log_level,
            'auto_start': config.local.auto_start
        },
        'workflow': {
            'default_priority': config.workflow.default_priority,
            'default_timeout': config.workflow.default_timeout,
            'retry_attempts': config.workflow.retry_attempts,
            'templates_dir': config.workflow.templates_dir
        },
        'profiles': config.profiles
    }
    
    try:
        with open(config_path, 'w') as f:
            yaml.dump(config_dict, f, default_flow_style=False, indent=2)
        
        logger.debug(f"Saved configuration to {config_path}")
        
    except Exception as e:
        logger.error(f"Failed to save configuration: {e}")
        raise


def create_default_config() -> CLIConfig:
    """Create default configuration"""
    return CLIConfig(
        mode="auto",
        cluster=ClusterConfig(),
        local=LocalConfig(),
        workflow=WorkflowConfig(),
        profiles={
            'dev': {
                'mode': 'local',
                'local': {
                    'persistence': 'sqlite',
                    'log_level': 'debug'
                }
            },
            'staging': {
                'mode': 'cluster',
                'cluster': {
                    'endpoint': 'staging.gleitzeit.io',
                    'tls': True
                }
            },
            'prod': {
                'mode': 'cluster', 
                'cluster': {
                    'endpoint': 'prod.gleitzeit.io',
                    'auth_method': 'token',
                    'tls': True
                }
            }
        }
    )


def get_templates_dir(config: CLIConfig) -> Path:
    """Get workflow templates directory"""
    templates_dir = Path(config.workflow.templates_dir).expanduser()
    templates_dir.mkdir(exist_ok=True)
    return templates_dir


def create_default_templates(templates_dir: Path) -> None:
    """Create default workflow templates"""
    
    # Data pipeline template
    data_pipeline = {
        'name': 'data-pipeline',
        'version': '1.0',
        'description': 'Simple data processing pipeline',
        'providers': ['mcp://filesystem'],
        'tasks': [
            {
                'id': 'fetch-data',
                'protocol': 'mcp/filesystem', 
                'method': 'file.read',
                'params': {'path': '/path/to/input.json'}
            },
            {
                'id': 'process-data',
                'protocol': 'custom/processor',
                'method': 'transform',
                'params': {'input': '${fetch-data.result}'},
                'depends_on': ['fetch-data']
            }
        ]
    }
    
    # API workflow template  
    api_workflow = {
        'name': 'api-workflow',
        'version': '1.0',
        'description': 'HTTP API call workflow',
        'providers': ['http://api-client'],
        'tasks': [
            {
                'id': 'api-call',
                'protocol': 'http/client',
                'method': 'get',
                'params': {'url': 'https://api.example.com/data'},
                'retry': {'max_attempts': 3, 'backoff': 'exponential'}
            }
        ]
    }
    
    # MCP integration template
    mcp_workflow = {
        'name': 'mcp-integration', 
        'version': '1.0',
        'description': 'MCP server integration example',
        'providers': [
            'mcp://filesystem'
        ],
        'tasks': [
            {
                'id': 'echo-test',
                'protocol': 'mcp/v1',
                'method': 'mcp/tool.echo',
                'params': {'message': 'Advanced MCP workflow'}
            },
            {
                'id': 'process-result',
                'protocol': 'python/v1',
                'method': 'python/execute',
                'params': {
                    'code': 'result = f"Processed: ${echo-test.response}"'
                },
                'depends_on': ['echo-test']
            }
        ]
    }
    
    # Save templates
    templates = {
        'data-pipeline.yaml': data_pipeline,
        'api-workflow.yaml': api_workflow,
        'mcp-integration.yaml': mcp_workflow
    }
    
    for filename, template in templates.items():
        template_path = templates_dir / filename
        if not template_path.exists():
            with open(template_path, 'w') as f:
                yaml.dump(template, f, default_flow_style=False, indent=2)
            logger.info(f"Created template: {template_path}")


def update_config_value(config: CLIConfig, key: str, value: Any, profile: Optional[str] = None) -> CLIConfig:
    """Update configuration value"""
    if profile:
        # Update profile-specific value
        if profile not in config.profiles:
            config.profiles[profile] = {}
        
        # Parse key path (e.g., "cluster.endpoint")
        keys = key.split('.')
        target = config.profiles[profile]
        
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        
        target[keys[-1]] = value
        
    else:
        # Update main configuration
        keys = key.split('.')
        
        if keys[0] == 'cluster':
            setattr(config.cluster, keys[1], value)
        elif keys[0] == 'local':
            setattr(config.local, keys[1], value)
        elif keys[0] == 'workflow':
            setattr(config.workflow, keys[1], value)
        else:
            setattr(config, keys[0], value)
    
    return config


def get_config_value(config: CLIConfig, key: str, profile: Optional[str] = None) -> Any:
    """Get configuration value"""
    if profile and profile in config.profiles:
        # Get from profile
        keys = key.split('.')
        target = config.profiles[profile]
        
        for k in keys:
            if k in target:
                target = target[k]
            else:
                break
        else:
            return target
    
    # Get from main configuration
    keys = key.split('.')
    
    if keys[0] == 'cluster':
        return getattr(config.cluster, keys[1])
    elif keys[0] == 'local':
        return getattr(config.local, keys[1])
    elif keys[0] == 'workflow':
        return getattr(config.workflow, keys[1])
    else:
        return getattr(config, keys[0])