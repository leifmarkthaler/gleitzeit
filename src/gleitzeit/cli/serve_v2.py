"""
Unified serve command for Gleitzeit with Smart Process Management

Manages orchestrator, API, and UI as a single service with proper
process lifecycle, ownership tracking, and conflict resolution.
"""

import signal
import subprocess
import sys
import os
import time
import logging
import asyncio
from typing import Dict, Optional
from pathlib import Path
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
from ..core.process_manager import SmartProcessManager
from ..core.ports import PortManager

logger = logging.getLogger(__name__)


class GleitzeitServerV2:
    """Manages all Gleitzeit components with Smart Process Management"""

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
        serve_config = self.config.get('serve', {})

        # Initialize managers
        self.process_manager = SmartProcessManager()
        self.port_manager = PortManager()

        # Service configuration
        self.api_port = api_port if api_port is not None else self.port_manager.get_service_port('api')
        self.ui_port = ui_port if ui_port is not None else self.port_manager.get_service_port('ui')
        self.api_host = api_host if api_host is not None else serve_config.get('api', {}).get('host', '0.0.0.0')
        self.ui_host = ui_host if ui_host is not None else serve_config.get('ui', {}).get('host', '0.0.0.0')
        self.dev_mode = dev_mode if dev_mode is not None else serve_config.get('dev_mode', False)

        # Service enable/disable flags
        ui_enabled = serve_config.get('ui', {}).get('enabled', True)
        orchestrator_enabled = serve_config.get('orchestrator', {}).get('enabled', True)

        self.no_ui = no_ui if no_ui is not None else not ui_enabled
        self.no_orchestrator = no_orchestrator if no_orchestrator is not None else not orchestrator_enabled
        self.restart = restart

        # State
        self.running = False
        self.loop = None

        # Setup environment
        src_path = Path(__file__).parent.parent.parent.absolute()
        self.env = os.environ.copy()
        self.env['PYTHONPATH'] = f"{src_path}:{self.env.get('PYTHONPATH', '')}"

        # Add instance identity to environment
        self.env['GLEITZEIT_INSTANCE_ID'] = self.instance.instance_id
        self.env['GLEITZEIT_INSTANCE_NAME'] = self.instance.instance_name
        self.env['GLEITZEIT_INSTANCE_ROLE'] = self.instance.role
        self.env['GLEITZEIT_DEPLOYMENT_ID'] = self.instance.deployment_id
        self.env['GLEITZEIT_REDIS_NAMESPACE'] = self.instance.get_redis_namespace()

        # Setup environment from config
        self._setup_environment_from_config()

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

    def _setup_environment_from_config(self):
        """Setup environment variables from configuration"""
        auth_config = self.config.get('auth', {})
        security_config = self.config.get('security', {})
        redis_config = self.config.get('redis', {})

        # Set authentication
        if 'auto_login' in auth_config:
            self.env['GLEITZEIT_AUTO_LOGIN'] = str(auth_config['auto_login']).lower()

        # Set JWT configuration
        jwt_config = auth_config.get('jwt', {})
        if 'secret' in jwt_config:
            jwt_secret = str(jwt_config['secret'])
            if jwt_secret.startswith('${') and jwt_secret.endswith('}'):
                var_content = jwt_secret[2:-1]
                if ':-' in var_content:
                    var_name, default = var_content.split(':-', 1)
                    jwt_secret = os.environ.get(var_name, default)
            self.env['JWT_SECRET'] = jwt_secret

        # Compute CORS origins
        cors_origins = []
        api_host = self.api_host if self.api_host != '0.0.0.0' else 'localhost'
        api_url = f"http://{api_host}:{self.api_port}"
        cors_origins.append(api_url)

        if not self.no_ui:
            ui_host = self.ui_host if self.ui_host != '0.0.0.0' else 'localhost'
            ui_url = f"http://{ui_host}:{self.ui_port}"
            cors_origins.append(ui_url)

        if self.api_host == '0.0.0.0':
            cors_origins.append(f"http://localhost:{self.api_port}")
            cors_origins.append(f"http://127.0.0.1:{self.api_port}")

        if not self.no_ui and self.ui_host == '0.0.0.0':
            cors_origins.append(f"http://localhost:{self.ui_port}")
            cors_origins.append(f"http://127.0.0.1:{self.ui_port}")

        cors_origins = list(filter(None, set(cors_origins)))
        self.env['CORS_ORIGINS'] = ','.join(cors_origins)

        # Redis configuration
        if redis_config.get('mode') == 'single':
            single_node = redis_config.get('single_node', {})
            redis_host = single_node.get('host', 'localhost')
            redis_port = single_node.get('port', 6379)
            redis_db = single_node.get('db', 0)
            self.env['REDIS_URL'] = f"redis://{redis_host}:{redis_port}/{redis_db}"

        if 'REDIS_URL' not in self.env:
            self.env['REDIS_URL'] = os.environ.get('REDIS_URL', 'redis://localhost:6379')

        # Set API URL for UI
        self.env['GLEITZEIT_API_URL'] = f"http://{api_host}:{self.api_port}"

        logger.info(f"Environment configured:")
        logger.info(f"  - Instance: {self.env.get('GLEITZEIT_INSTANCE_ID')}")
        logger.info(f"  - Redis URL: {self.env.get('REDIS_URL')}")
        logger.info(f"  - CORS origins: {self.env.get('CORS_ORIGINS')}")

    async def start_orchestrator(self):
        """Start the orchestrator component"""
        if self.no_orchestrator:
            return

        # Orchestrator needs a config file
        if not os.path.exists(self.config_file):
            # Create a minimal config if it doesn't exist
            create_default_config(Path(self.config_file))

        cmd = [
            sys.executable, "-m",
            "gleitzeit.orchestrator.component_orchestrator",
            self.config_file
        ]

        port = self.port_manager.get_service_port("orchestrator")

        process_info = await self.process_manager.start_service(
            "orchestrator",
            cmd,
            port,
            env=self.env,
            kill_existing=self.restart
        )

        if process_info:
            print(f"✓ Orchestrator started (PID: {process_info.pid})")
        else:
            raise RuntimeError("Failed to start orchestrator")

    async def start_api(self):
        """Start the API server"""
        cmd = [
            sys.executable, "-m", "uvicorn",
            "gleitzeit.api.main:app",
            "--host", self.api_host,
            "--port", str(self.api_port)
        ]

        if self.dev_mode:
            cmd.append("--reload")

        process_info = await self.process_manager.start_service(
            "api",
            cmd,
            self.api_port,
            env=self.env,
            kill_existing=self.restart
        )

        if process_info:
            print(f"✓ API Server started on http://{self.api_host}:{self.api_port} (PID: {process_info.pid})")
        else:
            raise RuntimeError("Failed to start API server")

    async def start_ui(self):
        """Start the UI server"""
        if self.no_ui:
            return

        cmd = [
            sys.executable, "-m", "uvicorn",
            "gleitzeit.ui.api.app:app",
            "--host", self.ui_host,
            "--port", str(self.ui_port)
        ]

        if self.dev_mode:
            cmd.append("--reload")

        process_info = await self.process_manager.start_service(
            "ui",
            cmd,
            self.ui_port,
            env=self.env,
            kill_existing=self.restart
        )

        if process_info:
            print(f"✓ UI Server started on http://{self.ui_host}:{self.ui_port} (PID: {process_info.pid})")
        else:
            raise RuntimeError("Failed to start UI server")

    def print_status(self):
        """Print status summary"""
        print("\n" + "=" * 60)
        print("✨ Gleitzeit is running!")
        print("=" * 60)
        print(f"\n📦 Instance: {self.instance.instance_name} ({self.instance.instance_id[:8]})")
        print(f"   Role: {self.instance.role}")
        if self.instance.port_offset > 0:
            print(f"   Port Offset: +{self.instance.port_offset}")

        print("\n📍 Service URLs:")
        print(f"   API Server:  http://localhost:{self.api_port}")
        if not self.no_ui:
            print(f"   Web UI:      http://localhost:{self.ui_port}")
        print(f"   API Docs:    http://localhost:{self.api_port}/docs")

        print("\n📊 Components:")
        status = self.process_manager.get_service_status()
        for name, info in status["services"].items():
            status_text = "✓ Running" if info["status"] == "running" else "✗ " + info["status"].capitalize()
            print(f"   {name.capitalize()}: {status_text} (PID: {info['pid']})")

        print("\nPress Ctrl+C to stop all services")
        print("=" * 60 + "\n")

    async def monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                # Monitor services
                await self.process_manager.monitor_services()

                # Wait before next check
                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")

    async def start_async(self):
        """Start all components asynchronously"""
        print("=" * 60)
        print("🚀 Starting Gleitzeit 0.0.7 (Smart Process Management)")
        print("=" * 60)

        # Check for port conflicts
        conflicts = self.port_manager.check_port_conflicts()
        if conflicts:
            print("\n⚠️  Port conflicts detected:")
            for conflict, owner in conflicts.items():
                print(f"   • {conflict} used by {owner}")

            if not self.restart:
                print("\nUse --restart flag to override")
                return False

        try:
            # Initialize process manager
            await self.process_manager.initialize()

            # Start services
            await self.start_orchestrator()
            await asyncio.sleep(2)

            await self.start_api()
            await asyncio.sleep(2)

            await self.start_ui()
            await asyncio.sleep(1)

            self.running = True
            self.print_status()

            # Start monitoring
            monitor_task = asyncio.create_task(self.monitor_loop())

            # Wait for signal
            stop_event = asyncio.Event()

            def signal_handler():
                stop_event.set()

            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, signal_handler)

            await stop_event.wait()

            # Shutdown
            print("\n\nShutting down Gleitzeit...")
            self.running = False
            monitor_task.cancel()

            await self.process_manager.stop_all_services()
            await self.process_manager.close()

            print("All services stopped")
            return True

        except Exception as e:
            logger.error(f"Failed to start: {e}")
            self.running = False
            await self.process_manager.stop_all_services()
            await self.process_manager.close()
            return False

    def start(self):
        """Start the server (synchronous wrapper)"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            success = self.loop.run_until_complete(self.start_async())
            if not success:
                sys.exit(1)
        except KeyboardInterrupt:
            print("\nShutdown requested")
        finally:
            if self.loop:
                self.loop.close()


# CLI Command
@click.command('serve')
@click.option('--config', '-c', type=click.Path(exists=True), help='Configuration file')
@click.option('--api-port', type=int, help='Override API server port')
@click.option('--ui-port', type=int, help='Override UI server port')
@click.option('--api-host', help='Override API host')
@click.option('--ui-host', help='Override UI host')
@click.option('--dev', is_flag=True, default=None, help='Development mode with auto-reload')
@click.option('--no-ui', is_flag=True, default=None, help='Start without UI server')
@click.option('--no-orchestrator', is_flag=True, default=None, help='Start without orchestrator')
@click.option('--restart', is_flag=True, help='Stop existing processes before starting')
@click.option('--instance-name', help='Name for this instance')
@click.option('--instance-role', default='standalone', help='Instance role: standalone, worker, coordinator')
@click.option('--port-offset', type=int, default=0, help='Port offset for all services')
@click.option('--v2', is_flag=True, hidden=True, help='Use v2 implementation')
def serve_v2(config, api_port, ui_port, api_host, ui_host, dev, no_ui, no_orchestrator,
             restart, instance_name, instance_role, port_offset, v2):
    """
    Start all Gleitzeit components with Smart Process Management.

    Uses instance identity, distributed locking, and intelligent restart policies
    to prevent startup loops and enable multi-instance deployments.
    """

    server = GleitzeitServerV2(
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
            "orchestrator": {
                "enabled": True
            },
            "dev_mode": False
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