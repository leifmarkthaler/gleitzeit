"""
Configuration Manager for Gleitzeit

Provides unified configuration with clear precedence order.
"""

import os
import logging
from typing import Dict, Any, Optional, List
import yaml

from .instance import get_current_instance
from .ports import PortManager

logger = logging.getLogger(__name__)


class ConfigurationManager:
    """Unified configuration with clear precedence"""

    PRECEDENCE = [
        'cli_args',      # 1. Command line (highest priority)
        'env_vars',      # 2. Environment variables
        'instance',      # 3. Instance configuration
        'config_file',   # 4. YAML config file
        'defaults'       # 5. Hardcoded defaults (lowest priority)
    ]

    def __init__(self, config_file: str, cli_args: Optional[Dict] = None):
        """
        Initialize Configuration Manager

        Args:
            config_file: Path to YAML configuration file
            cli_args: Command line arguments dictionary
        """
        self.config_file = config_file
        self.cli_args = cli_args or {}
        self.yaml_config = self._load_yaml()
        self.instance = get_current_instance()

    def _load_yaml(self) -> Dict:
        """Load configuration from YAML file"""
        try:
            with open(self.config_file, 'r') as f:
                config = yaml.safe_load(f) or {}
                logger.info(f"Loaded configuration from {self.config_file}")
                return config
        except FileNotFoundError:
            logger.warning(f"Config file {self.config_file} not found, using defaults")
            return {}
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    def get_value(self, key: str, service: Optional[str] = None) -> Any:
        """
        Get configuration value with precedence

        Args:
            key: Configuration key (e.g., 'port', 'host')
            service: Optional service name (e.g., 'api', 'ui')

        Returns:
            Configuration value based on precedence
        """
        sources = self._build_sources(key, service)

        for source_name in self.PRECEDENCE:
            value = sources.get(source_name)
            if value is not None:
                logger.debug(f"Config {key}{f' for {service}' if service else ''}: "
                           f"{value} (source: {source_name})")
                return value

        return None

    def _build_sources(self, key: str, service: Optional[str] = None) -> Dict[str, Any]:
        """Build sources dictionary for a configuration key"""
        sources = {}

        # 1. CLI arguments
        if service:
            cli_key = f'{service}_{key}'
            sources['cli_args'] = self.cli_args.get(cli_key)
        else:
            sources['cli_args'] = self.cli_args.get(key)

        # 2. Environment variables
        if service:
            env_key = f'GLEITZEIT_{service.upper()}_{key.upper()}'
        else:
            env_key = f'GLEITZEIT_{key.upper()}'

        env_value = os.getenv(env_key)
        sources['env_vars'] = env_value

        # 3. Instance configuration
        if self.instance:
            if service and key == 'port':
                sources['instance'] = self.instance.get_service_port(service)
            else:
                sources['instance'] = None
        else:
            sources['instance'] = None

        # 4. Config file
        if service:
            # Look in serve.service.key
            config_value = self.yaml_config.get('serve', {}).get(service, {}).get(key)
        else:
            # Look in top-level or serve
            config_value = (self.yaml_config.get(key) or
                          self.yaml_config.get('serve', {}).get(key))
        sources['config_file'] = config_value

        # 5. Defaults
        defaults = {
            'api': {
                'port': 8000,
                'host': '0.0.0.0'
            },
            'ui': {
                'port': 8004,
                'host': '0.0.0.0'
            },
            'orchestrator': {
                'enabled': True
            }
        }

        if service and key in defaults.get(service, {}):
            sources['defaults'] = defaults[service][key]
        else:
            sources['defaults'] = None

        return sources

    def get_port(self, service: str) -> int:
        """
        Get port for a service with clear precedence

        Args:
            service: Service name (e.g., 'api', 'ui')

        Returns:
            Port number for the service
        """
        port = self.get_value('port', service)
        if port is not None:
            return int(port)

        raise ValueError(f"No port configuration found for {service}")

    def get_host(self, service: str) -> str:
        """
        Get host for a service

        Args:
            service: Service name

        Returns:
            Host address for the service
        """
        host = self.get_value('host', service)
        if host is not None:
            return str(host)

        return '0.0.0.0'  # Default host

    def is_enabled(self, service: str) -> bool:
        """
        Check if a service is enabled

        Args:
            service: Service name

        Returns:
            True if service is enabled, False otherwise
        """
        # Check for no_ flags in CLI
        if self.cli_args.get(f'no_{service}'):
            return False

        enabled = self.get_value('enabled', service)
        if enabled is not None:
            return bool(enabled)

        # Default to enabled for most services
        return True

    def get_redis_config(self) -> Dict[str, Any]:
        """Get Redis configuration"""
        redis_config = self.yaml_config.get('redis', {})

        # Override with environment if set
        if os.getenv('REDIS_URL'):
            return {'url': os.getenv('REDIS_URL')}

        return redis_config

    def validate(self) -> List[str]:
        """
        Validate configuration and return errors

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Check port ranges
        for service in ['api', 'ui']:
            try:
                port = self.get_port(service)
                if not (1024 <= port <= 65535):
                    errors.append(f"{service} port {port} out of valid range (1024-65535)")
            except ValueError as e:
                errors.append(str(e))

        # Check for port conflicts in configuration
        ports = {}
        for service in ['api', 'ui']:
            try:
                port = self.get_port(service)
                if port in ports:
                    errors.append(f"Port {port} configured for both {ports[port]} and {service}")
                ports[port] = service
            except:
                pass

        # Check Redis connectivity
        redis_config = self.get_redis_config()
        if not redis_config:
            errors.append("No Redis configuration found")

        return errors

    def get_all_config(self) -> Dict[str, Any]:
        """Get all configuration with precedence applied"""
        config = {}

        # Services configuration
        for service in ['api', 'ui', 'orchestrator']:
            config[service] = {
                'enabled': self.is_enabled(service)
            }

            if service in ['api', 'ui']:
                try:
                    config[service]['port'] = self.get_port(service)
                    config[service]['host'] = self.get_host(service)
                except:
                    pass

        # Redis configuration
        config['redis'] = self.get_redis_config()

        # Development mode
        config['dev_mode'] = self.get_value('dev_mode') or False

        return config

    def log_configuration(self):
        """Log the final configuration with sources"""
        logger.info("=" * 60)
        logger.info("Configuration Summary (with precedence)")
        logger.info("=" * 60)

        config = self.get_all_config()

        for service, settings in config.items():
            if isinstance(settings, dict):
                logger.info(f"\n{service.upper()}:")
                for key, value in settings.items():
                    # Find source
                    sources = self._build_sources(key, service if service in ['api', 'ui'] else None)
                    source = 'unknown'
                    for source_name in self.PRECEDENCE:
                        if sources.get(source_name) is not None:
                            source = source_name
                            break
                    logger.info(f"  {key}: {value} (from {source})")
            else:
                logger.info(f"{service}: {settings}")

        logger.info("=" * 60)