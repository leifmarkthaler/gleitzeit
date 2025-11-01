"""
Configuration Manager for Gleitzeit

Provides unified configuration with clear precedence order.
"""

import os
import os.path
import logging
from typing import Dict, Any, Optional, List
import yaml
import importlib.resources as pkg_resources

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
        # Check if config file exists and is a file (not a directory)
        if os.path.isfile(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = yaml.safe_load(f) or {}
                    logger.info(f"Loaded configuration from {self.config_file}")
                    return config
            except Exception as e:
                logger.error(f"Failed to load config from {self.config_file}: {e}")
                # Fall through to load packaged default

        # Config file doesn't exist or is not a file, try packaged default
        try:
            from .. import config as config_pkg

            try:
                # Python 3.9+
                default_config = pkg_resources.files(config_pkg).joinpath('gleitzeit.yaml.default')
                with default_config.open('r') as f:
                    config = yaml.safe_load(f) or {}
                    logger.info(f"Using packaged default configuration")
                    return config
            except AttributeError:
                # Python 3.7-3.8 fallback
                with pkg_resources.open_text(config_pkg, 'gleitzeit.yaml.default') as f:
                    config = yaml.safe_load(f) or {}
                    logger.info(f"Using packaged default configuration")
                    return config
        except Exception as e:
            logger.warning(f"Could not load packaged config: {e}, using minimal defaults")
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

    def get_redis_url(self) -> str:
        """
        Get Redis URL from configuration

        Returns:
            Redis URL string

        Raises:
            ValueError: If Redis configuration is missing or invalid
        """
        redis_config = self.get_redis_config()

        # If URL is directly specified (e.g., from environment)
        if redis_config.get('url'):
            return redis_config['url']

        # Build URL from config
        if redis_config.get('mode') == 'single':
            single_node = redis_config.get('single_node', {})
            redis_host = single_node.get('host')
            redis_port = single_node.get('port')
            redis_db = single_node.get('db', 0)

            if not redis_host or redis_port is None:
                raise ValueError("Redis host and port must be specified in gleitzeit.yaml")

            return f"redis://{redis_host}:{redis_port}/{redis_db}"

        raise ValueError(f"Unsupported Redis mode: {redis_config.get('mode')}. Only 'single' mode is supported.")

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

    def get_redis_health_config(self) -> Dict[str, Any]:
        """
        Get Redis health monitoring configuration.

        Returns:
            Dict with health monitoring settings:
            - enabled: bool
            - check_interval: int (seconds)
            - warning_threshold: int (consecutive failures)
            - critical_timeout: int (seconds)
            - shutdown_timeout: int (seconds)
        """
        redis_config = self.yaml_config.get('redis', {})
        health_config = redis_config.get('health', {})

        return {
            'enabled': health_config.get('enabled', True),
            'check_interval': health_config.get('check_interval', 10),
            'warning_threshold': health_config.get('warning_threshold', 3),
            'critical_timeout': health_config.get('critical_timeout', 120),
            'shutdown_timeout': health_config.get('shutdown_timeout', 300)
        }

    def get_redis_shutdown_config(self) -> Dict[str, Any]:
        """
        Get Redis shutdown configuration.

        Returns:
            Dict with shutdown settings:
            - mode: str ('graceful' or 'immediate')
            - grace_period: int (seconds)
            - force_after: int (seconds)
        """
        redis_config = self.yaml_config.get('redis', {})
        shutdown_config = redis_config.get('shutdown', {})

        return {
            'mode': shutdown_config.get('mode', 'graceful'),
            'grace_period': shutdown_config.get('grace_period', 30),
            'force_after': shutdown_config.get('force_after', 60)
        }

    def get_worker_monitoring_config(self) -> Dict[str, Any]:
        """
        Get worker monitoring configuration.

        Returns:
            Dict with worker monitoring settings
        """
        monitoring_config = self.yaml_config.get('monitoring', {})
        worker_config = monitoring_config.get('worker', {})

        return {
            'heartbeat_interval': worker_config.get('heartbeat_interval', 30),
            'heartbeat_timeout': worker_config.get('heartbeat_timeout', 60),
            'max_health_failures': worker_config.get('max_health_failures', 3),
            'include_metrics': worker_config.get('include_metrics', True),
            'include_system_stats': worker_config.get('include_system_stats', True),
            'health_thresholds': worker_config.get('health_thresholds', {
                'max_memory_mb': 2048,
                'min_processing_rate': 0.1,
                'max_error_rate': 0.5,
                'max_avg_processing_ms': 30000
            })
        }

    def get_service_monitoring_config(self) -> Dict[str, Any]:
        """
        Get service monitoring configuration.

        Returns:
            Dict with service monitoring settings
        """
        monitoring_config = self.yaml_config.get('monitoring', {})
        service_config = monitoring_config.get('service', {})

        return {
            'heartbeat_interval': service_config.get('heartbeat_interval', 30),
            'registration_ttl': service_config.get('registration_ttl', 90),
            'circuit_breaker': service_config.get('circuit_breaker', {
                'enabled': True,
                'failure_threshold': 10,
                'reset_timeout': 300
            })
        }

    def get_component_monitoring_config(self) -> Dict[str, Any]:
        """
        Get component monitoring configuration.

        Returns:
            Dict with component monitoring settings
        """
        monitoring_config = self.yaml_config.get('monitoring', {})
        component_config = monitoring_config.get('component', {})

        return {
            'health_check_interval': component_config.get('health_check_interval', 10),
            'enable_system_metrics': component_config.get('enable_system_metrics', True),
            'enable_queue_metrics': component_config.get('enable_queue_metrics', True)
        }

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

        # Logging configuration (from yaml_config)
        if 'logging' in self.yaml_config:
            config['logging'] = self.yaml_config['logging']

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