"""
Unified serve command for Gleitzeit with Layered Process Management

Uses the new layered architecture:
- SmartProcessManager: Core process lifecycle with distributed locking
- ServiceManager: Service-specific management (API, UI)
- WorkerManager: Worker-specific management with shard assignment
- ProcessOrchestrator: Top-level coordination
"""

import asyncio
import sys
import os
import logging
from pathlib import Path
from typing import Dict, Optional
import click
import yaml

from ..core.errors import (
    SystemError as GleitzeitSystemError,
    ErrorCode,
    ConfigurationError,
    ServiceRegistrationError
)
from ..core.instance import InstanceIdentity, initialize_instance, get_current_instance
from ..core.config_loader import ConfigLoader
from ..core.process_orchestrator import ProcessOrchestrator

logger = logging.getLogger(__name__)


class GleitzeitServerV3:
    """Manages all Gleitzeit components with Layered Process Management"""

    def __init__(
        self,
        config_file: Optional[str] = None,
        api_port: Optional[int] = None,
        ui_port: Optional[int] = None,
        api_host: Optional[str] = None,
        ui_host: Optional[str] = None,
        dev_mode: Optional[bool] = None,
        no_ui: Optional[bool] = None,
        no_orchestrator: Optional[bool] = None,
        restart: bool = False,
        instance_name: Optional[str] = None,
        instance_role: str = "standalone",
        port_offset: int = 0
    ):
        self.config_file = config_file or "gleitzeit.yaml"
        self.restart = restart

        # Initialize instance identity
        self.instance = initialize_instance(
            instance_name=instance_name or os.getenv("GLEITZEIT_INSTANCE_NAME"),
            role=instance_role or os.getenv("GLEITZEIT_ROLE", "standalone"),
            port_offset=port_offset or int(os.getenv("GLEITZEIT_PORT_OFFSET", "0"))
        )

        logger.info(f"Initialized instance: {self.instance}")
        logger.info(f"Instance ID: {self.instance.instance_id}")
        logger.info(f"Machine: {self.instance.machine_id} ({self.instance.machine_ip})")
        logger.info(f"Capabilities: {self.instance.capabilities.cpu_count} CPUs, "
                   f"{self.instance.capabilities.memory_gb:.1f} GB RAM")

        # Load configuration
        self.config = self._load_config()

        # Apply CLI overrides
        self._apply_cli_overrides(
            api_port=api_port,
            ui_port=ui_port,
            api_host=api_host,
            ui_host=ui_host,
            dev_mode=dev_mode,
            no_ui=no_ui,
            no_orchestrator=no_orchestrator
        )

        # Setup environment
        self._setup_environment()

        # Initialize orchestrator
        self.orchestrator = ProcessOrchestrator(
            config=self.config,
            redis_url=self.env.get('REDIS_URL')
        )

    def _load_config(self) -> Dict:
        """Load configuration from YAML file"""
        try:
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning(f"Config file {self.config_file} not found, using defaults")
            return {}
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    def _apply_cli_overrides(
        self,
        api_port: Optional[int],
        ui_port: Optional[int],
        api_host: Optional[str],
        ui_host: Optional[str],
        dev_mode: Optional[bool],
        no_ui: Optional[bool],
        no_orchestrator: Optional[bool]
    ):
        """Apply CLI parameter overrides to config"""
        # Ensure serve config exists
        if 'serve' not in self.config:
            self.config['serve'] = {}

        serve_config = self.config['serve']

        # API overrides
        if 'api' not in serve_config:
            serve_config['api'] = {}
        if api_host is not None:
            serve_config['api']['host'] = api_host
        if api_port is not None:
            serve_config['api']['port'] = api_port

        # UI overrides
        if 'ui' not in serve_config:
            serve_config['ui'] = {}
        if ui_host is not None:
            serve_config['ui']['host'] = ui_host
        if ui_port is not None:
            serve_config['ui']['port'] = ui_port
        if no_ui is not None:
            serve_config['ui']['enabled'] = not no_ui

        # Development mode
        if dev_mode is not None:
            serve_config['dev_mode'] = dev_mode

        # Worker overrides
        if no_orchestrator:
            # Disable all workers if orchestrator is disabled
            if 'workers' not in self.config:
                self.config['workers'] = {}
            elif isinstance(self.config['workers'], list):
                # Convert list to dict format
                self.config['workers'] = {}

            for worker_type in ['task_execution', 'dependency', 'retry', 'workflow_loader']:
                if worker_type not in self.config['workers']:
                    self.config['workers'][worker_type] = {}
                self.config['workers'][worker_type]['enabled'] = False

    def _setup_environment(self):
        """Setup environment variables from configuration"""
        self.env = os.environ.copy()

        # Add instance identity to environment
        self.env['GLEITZEIT_INSTANCE_ID'] = self.instance.instance_id
        self.env['GLEITZEIT_INSTANCE_NAME'] = self.instance.instance_name
        self.env['GLEITZEIT_INSTANCE_ROLE'] = self.instance.role
        self.env['GLEITZEIT_DEPLOYMENT_ID'] = self.instance.deployment_id
        self.env['GLEITZEIT_REDIS_NAMESPACE'] = self.instance.get_redis_namespace()

        # Setup Redis URL
        redis_config = self.config.get('redis', {})
        if redis_config.get('mode') == 'single':
            single_node = redis_config.get('single_node', {})
            redis_host = single_node.get('host', 'localhost')
            redis_port = single_node.get('port', 6379)
            redis_db = single_node.get('db', 0)
            self.env['REDIS_URL'] = f"redis://{redis_host}:{redis_port}/{redis_db}"

        if 'REDIS_URL' not in self.env:
            self.env['REDIS_URL'] = os.environ.get('REDIS_URL', 'redis://localhost:6379')

        # Setup authentication
        auth_config = self.config.get('auth', {})
        if 'auto_login' in auth_config:
            self.env['GLEITZEIT_AUTO_LOGIN'] = str(auth_config['auto_login']).lower()

        # Setup JWT
        jwt_config = auth_config.get('jwt', {})
        if 'secret' in jwt_config:
            jwt_secret = str(jwt_config['secret'])
            if jwt_secret.startswith('${') and jwt_secret.endswith('}'):
                var_content = jwt_secret[2:-1]
                if ':-' in var_content:
                    var_name, default = var_content.split(':-', 1)
                    jwt_secret = os.environ.get(var_name, default)
            self.env['JWT_SECRET'] = jwt_secret

        # Setup PYTHONPATH
        src_path = Path(__file__).parent.parent.parent.absolute()
        self.env['PYTHONPATH'] = f"{src_path}:{self.env.get('PYTHONPATH', '')}"

        logger.info(f"Environment configured:")
        logger.info(f"  - Instance: {self.env.get('GLEITZEIT_INSTANCE_ID')}")
        logger.info(f"  - Redis URL: {self.env.get('REDIS_URL')}")

    def start(self):
        """Start the server (synchronous wrapper)"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(self.start_async())
            if not success:
                sys.exit(1)
        except KeyboardInterrupt:
            print("\nShutdown requested")
        finally:
            if loop:
                loop.close()

    async def start_async(self):
        """Start all components asynchronously"""
        try:
            # Start all processes
            success = await self.orchestrator.start_all(restart=self.restart)
            if not success:
                return False

            # Wait for shutdown signal
            await self.orchestrator.wait_for_shutdown()

            return True

        except Exception as e:
            logger.error(f"Failed to start: {e}")
            return False

        finally:
            # Ensure cleanup
            await self.orchestrator.stop_all()


# CLI Command
@click.command('serve')
@click.option('--config', '-c', type=click.Path(exists=True), help='Configuration file')
@click.option('--api-port', type=int, help='Override API server port')
@click.option('--ui-port', type=int, help='Override UI server port')
@click.option('--api-host', help='Override API host')
@click.option('--ui-host', help='Override UI host')
@click.option('--dev', is_flag=True, default=None, help='Development mode with auto-reload')
@click.option('--no-ui', is_flag=True, default=None, help='Start without UI server')
@click.option('--no-orchestrator', is_flag=True, default=None, help='Start without workers')
@click.option('--restart', is_flag=True, help='Stop existing processes before starting')
@click.option('--instance-name', help='Name for this instance')
@click.option('--instance-role', default='standalone', help='Instance role: standalone, worker, coordinator')
@click.option('--port-offset', type=int, default=0, help='Port offset for all services')
def serve_v3(config, api_port, ui_port, api_host, ui_host, dev, no_ui, no_orchestrator,
             restart, instance_name, instance_role, port_offset):
    """
    Start all Gleitzeit components with Layered Process Management.

    Uses clean separation between services and workers with proper
    instance identity and distributed coordination.
    """

    server = GleitzeitServerV3(
        config_file=config,
        api_port=api_port,
        ui_port=ui_port,
        api_host=api_host,
        ui_host=ui_host,
        dev_mode=dev,
        no_ui=no_ui,
        no_orchestrator=no_orchestrator,
        restart=restart,
        instance_name=instance_name,
        instance_role=instance_role,
        port_offset=port_offset
    )

    server.start()


def create_default_config(path: Path):
    """Create a default configuration file"""
    config = {
        "redis": {
            "mode": "single",
            "single_node": {
                "host": "localhost",
                "port": 6379,
                "db": 0
            }
        },
        "serve": {
            "api": {
                "enabled": True,
                "host": "0.0.0.0",
                "port": 8000
            },
            "ui": {
                "enabled": True,
                "host": "0.0.0.0",
                "port": 8004
            },
            "dev_mode": False
        },
        "workers": {
            "task_execution": {
                "enabled": False,  # Disabled by default for safety
                "count": 2
            },
            "dependency": {
                "enabled": False,
                "count": 1
            },
            "retry": {
                "enabled": False,
                "count": 1
            },
            "workflow_loader": {
                "enabled": False,
                "count": 1
            }
        },
        "auth": {
            "auto_login": True,
            "jwt": {
                "secret": "${JWT_SECRET:-dev-secret-change-me}",
                "algorithm": "HS256"
            }
        },
        "security": {
            "cors": {
                "additional_origins": ""
            }
        }
    }

    with open(path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"✓ Created default configuration at {path}")