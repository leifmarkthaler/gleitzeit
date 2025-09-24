"""
Unified serve command for Gleitzeit

Manages orchestrator, API, and UI as a single service.
"""

import signal
import subprocess
import sys
import os
import time
import logging
import psutil
import socket
from typing import Dict, Optional, List
from pathlib import Path
import click
import yaml

logger = logging.getLogger(__name__)


class GleitzeitServer:
    """Manages all Gleitzeit components"""

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
        restart: bool = False
    ):
        self.config_file = config_file or "gleitzeit.yaml"

        # Load configuration from YAML
        self.config = self._load_config()
        serve_config = self.config.get('serve', {})

        # Use command line args if provided, otherwise use config, otherwise use defaults
        self.api_port = api_port if api_port is not None else serve_config.get('api', {}).get('port', 8000)
        self.ui_port = ui_port if ui_port is not None else serve_config.get('ui', {}).get('port', 8004)
        self.api_host = api_host if api_host is not None else serve_config.get('api', {}).get('host', '0.0.0.0')
        self.ui_host = ui_host if ui_host is not None else serve_config.get('ui', {}).get('host', '0.0.0.0')
        self.dev_mode = dev_mode if dev_mode is not None else serve_config.get('dev_mode', False)

        # Handle enable/disable flags
        ui_enabled = serve_config.get('ui', {}).get('enabled', True)
        orchestrator_enabled = serve_config.get('orchestrator', {}).get('enabled', True)

        self.no_ui = no_ui if no_ui is not None else not ui_enabled
        self.no_orchestrator = no_orchestrator if no_orchestrator is not None else not orchestrator_enabled
        self.restart = restart

        # Process management
        self.processes: Dict[str, subprocess.Popen] = {}
        self.running = False

        # Setup Python path
        src_path = Path(__file__).parent.parent.parent.absolute()
        self.env = os.environ.copy()
        self.env['PYTHONPATH'] = f"{src_path}:{self.env.get('PYTHONPATH', '')}"

        # Add auth and security environment variables from config
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
        """Setup environment variables from YAML configuration"""
        # Get auth config
        auth_config = self.config.get('auth', {})
        security_config = self.config.get('security', {})
        redis_config = self.config.get('redis', {})

        # Set authentication variables
        if 'auto_login' in auth_config:
            self.env['GLEITZEIT_AUTO_LOGIN'] = str(auth_config['auto_login']).lower()

        # Set JWT configuration
        jwt_config = auth_config.get('jwt', {})
        if 'secret' in jwt_config:
            # Expand environment variable if present
            jwt_secret = str(jwt_config['secret'])
            if jwt_secret.startswith('${') and jwt_secret.endswith('}'):
                # Extract variable name and default
                var_content = jwt_secret[2:-1]
                if ':-' in var_content:
                    var_name, default = var_content.split(':-', 1)
                    jwt_secret = os.environ.get(var_name, default)
            self.env['JWT_SECRET'] = jwt_secret

        # Compute CORS origins dynamically from serve configuration
        cors_origins = []

        # Add API URL
        api_host = self.api_host if self.api_host != '0.0.0.0' else 'localhost'
        api_url = f"http://{api_host}:{self.api_port}"
        cors_origins.append(api_url)

        # Add UI URL if enabled
        if not self.no_ui:
            ui_host = self.ui_host if self.ui_host != '0.0.0.0' else 'localhost'
            ui_url = f"http://{ui_host}:{self.ui_port}"
            cors_origins.append(ui_url)

        # Add localhost variants if using 0.0.0.0
        if self.api_host == '0.0.0.0':
            cors_origins.append(f"http://localhost:{self.api_port}")
            cors_origins.append(f"http://127.0.0.1:{self.api_port}")

        if not self.no_ui and self.ui_host == '0.0.0.0':
            cors_origins.append(f"http://localhost:{self.ui_port}")
            cors_origins.append(f"http://127.0.0.1:{self.ui_port}")

        # Add additional origins from config
        cors_config = security_config.get('cors', {})
        if 'additional_origins' in cors_config:
            additional = cors_config['additional_origins']
            if isinstance(additional, str) and additional:
                cors_origins.extend(additional.split(','))

        # Also check environment for additional origins
        env_origins = os.environ.get('CORS_ORIGINS', '')
        if env_origins:
            cors_origins.extend(env_origins.split(','))

        # Remove duplicates and empty values
        cors_origins = list(filter(None, set(cors_origins)))
        self.env['CORS_ORIGINS'] = ','.join(cors_origins)

        # Compute Redis URL from config
        if redis_config.get('mode') == 'single':
            single_node = redis_config.get('single_node', {})
            redis_host = single_node.get('host', 'localhost')
            redis_port = single_node.get('port', 6379)
            redis_db = single_node.get('db', 0)
            self.env['REDIS_URL'] = f"redis://{redis_host}:{redis_port}/{redis_db}"
        elif redis_config.get('mode') == 'cluster':
            # For cluster mode, use first node as seed
            cluster_nodes = redis_config.get('cluster_nodes', [])
            if cluster_nodes:
                first_node = cluster_nodes[0]
                self.env['REDIS_URL'] = f"redis://{first_node['host']}:{first_node['port']}"

        # If not set from config, use environment or default
        if 'REDIS_URL' not in self.env:
            self.env['REDIS_URL'] = os.environ.get('REDIS_URL', 'redis://localhost:6379')

        logger.info(f"Environment configured:")
        logger.info(f"  - Auto-login: {self.env.get('GLEITZEIT_AUTO_LOGIN', 'not set')}")
        logger.info(f"  - CORS origins: {self.env.get('CORS_ORIGINS', 'not set')}")
        logger.info(f"  - Redis URL: {self.env.get('REDIS_URL', 'not set')}")

    def check_existing_processes(self) -> Dict[str, bool]:
        """Check if Gleitzeit processes are already running"""
        existing = {
            "api": self._is_port_in_use(self.api_port),
            "ui": self._is_port_in_use(self.ui_port) if not self.no_ui else False,
            "orchestrator": self._check_orchestrator_running()
        }
        return existing

    def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is in use"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return False
            except socket.error:
                return True

    def _check_orchestrator_running(self) -> bool:
        """Check if orchestrator is running"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                cmdline = proc.info.get('cmdline', [])
                if cmdline and 'gleitzeit.orchestrator.component_orchestrator' in ' '.join(cmdline):
                    return True
        except:
            pass
        return False

    def kill_existing_processes(self):
        """Kill existing Gleitzeit processes"""
        print("Stopping existing Gleitzeit processes...")

        # Kill orchestrator and workers
        subprocess.run(["pkill", "-f", "gleitzeit.orchestrator"], capture_output=True)
        subprocess.run(["pkill", "-f", "gleitzeit.workers"], capture_output=True)

        # Kill API servers (more comprehensive patterns)
        subprocess.run(["pkill", "-f", "uvicorn.*gleitzeit.api"], capture_output=True)
        subprocess.run(["pkill", "-f", "gleitzeit.api.main"], capture_output=True)

        # Kill UI servers
        subprocess.run(["pkill", "-f", "uvicorn.*gleitzeit.ui"], capture_output=True)
        subprocess.run(["pkill", "-f", "gleitzeit.ui.api"], capture_output=True)
        subprocess.run(["pkill", "-f", "gleitzeit/ui/run_ui"], capture_output=True)

        # Kill by port if still in use - be more aggressive
        for port in [self.api_port, self.ui_port]:
            try:
                for proc in psutil.process_iter(['pid', 'connections']):
                    connections = proc.info.get('connections', [])
                    if connections:
                        for conn in connections:
                            if hasattr(conn, 'laddr') and conn.laddr.port == port:
                                try:
                                    p = psutil.Process(proc.pid)
                                    print(f"  Terminating process {proc.pid} on port {port}")
                                    p.terminate()
                                    # Wait briefly, then force kill if needed
                                    try:
                                        p.wait(timeout=1)
                                    except psutil.TimeoutExpired:
                                        print(f"  Force killing process {proc.pid}")
                                        p.kill()
                                except Exception as e:
                                    print(f"  Could not kill process {proc.pid}: {e}")
            except Exception as e:
                logger.debug(f"Error checking port {port}: {e}")

        time.sleep(2)  # Give processes and OS time to release ports
        print("  Existing processes stopped")

    def start(self):
        """Start all components"""
        # Check for existing processes
        existing = self.check_existing_processes()

        if any(existing.values()):
            if self.restart:
                print("\n⚠️  Existing Gleitzeit processes detected")
                self.kill_existing_processes()
                time.sleep(2)  # Give processes time to fully terminate
            else:
                print("\n⚠️  Existing Gleitzeit processes detected:")
                if existing["orchestrator"]:
                    print("   • Orchestrator is already running")
                if existing["api"]:
                    print(f"   • API port {self.api_port} is already in use")
                if existing["ui"]:
                    print(f"   • UI port {self.ui_port} is already in use")
                print("\nUse --restart flag to stop existing processes and restart")
                print("Example: gleitzeit serve --restart")
                sys.exit(1)

        print("=" * 60)
        print("🚀 Starting Gleitzeit 0.0.7")
        print("=" * 60)

        try:
            # 1. Start Orchestrator (manages workers)
            if not self.no_orchestrator:
                self.start_orchestrator()
                time.sleep(2)  # Give orchestrator time to start

            # 2. Start API Server
            self.start_api()
            time.sleep(2)  # Give API time to start

            # 3. Start UI Server
            if not self.no_ui:
                self.start_ui()
                time.sleep(1)

            self.running = True
            self.print_status()

            # Setup signal handlers
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)

            # Keep running
            while self.running:
                # Check process health
                for name, proc in list(self.processes.items()):
                    if proc.poll() is not None:
                        logger.warning(f"{name} process died (exit code: {proc.returncode})")
                        # Try to restart - don't kill existing processes to avoid loops
                        if name == "orchestrator" and not self.no_orchestrator:
                            self.start_orchestrator()
                        elif name == "api":
                            self.start_api(kill_existing=False)
                        elif name == "ui" and not self.no_ui:
                            self.start_ui(kill_existing=False)

                time.sleep(5)

        except Exception as e:
            logger.error(f"Failed to start: {e}")
            self.stop()
            sys.exit(1)

    def start_orchestrator(self):
        """Start the orchestrator (manages workers)"""
        print("Starting Orchestrator...")

        cmd = [
            sys.executable, "-m",
            "gleitzeit.orchestrator.component_orchestrator",
            self.config_file
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1  # Line buffered
            )

            self.processes["orchestrator"] = proc

            print("✓ Orchestrator started")

        except Exception as e:
            logger.error(f"Failed to start orchestrator: {e}")
            raise

    def start_api(self, kill_existing=True):
        """Start the API server"""
        print(f"Starting API Server on port {self.api_port}...")

        # Only kill existing processes if explicitly requested (e.g., on initial start)
        # Don't kill when restarting from monitor loop to avoid killing newly started instances
        if kill_existing:
            try:
                result = subprocess.run(
                    ["lsof", "-ti", f":{self.api_port}"],
                    capture_output=True,
                    text=True
                )
                if result.stdout:
                    for pid in result.stdout.strip().split('\n'):
                        if pid:
                            logger.info(f"Killing existing process on port {self.api_port} (PID: {pid})")
                            os.kill(int(pid), signal.SIGKILL)
                            time.sleep(0.5)
            except:
                pass

        cmd = [
            sys.executable, "-m", "uvicorn",
            "gleitzeit.api.main:app",
            "--host", self.api_host,
            "--port", str(self.api_port),
            "--log-level", "info"
        ]

        # Check if reload is enabled in config
        reload_on_dev = self.config.get('serve', {}).get('api', {}).get('reload_on_dev', True)
        if self.dev_mode and reload_on_dev:
            cmd.append("--reload")

        try:
            proc = subprocess.Popen(
                cmd,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            self.processes["api"] = proc

            print(f"✓ API Server started on http://{self.api_host}:{self.api_port}")

        except Exception as e:
            logger.error(f"Failed to start API: {e}")
            raise

    def start_ui(self, kill_existing=True):
        """Start the UI server"""
        print(f"Starting UI Server on port {self.ui_port}...")

        # Only kill existing processes if explicitly requested (e.g., on initial start)
        # Don't kill when restarting from monitor loop to avoid killing newly started instances
        if kill_existing:
            try:
                # Find and kill any process using the UI port
                import psutil
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        for conn in proc.connections(kind='inet'):
                            if conn.laddr.port == self.ui_port and conn.status == 'LISTEN':
                                logger.info(f"Killing existing process on port {self.ui_port} (PID: {proc.pid})")
                                proc.kill()
                                time.sleep(0.5)  # Give it time to release the port
                                break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except ImportError:
                # If psutil not available, try using lsof
                try:
                    result = subprocess.run(
                        ["lsof", "-ti", f":{self.ui_port}"],
                        capture_output=True,
                        text=True
                    )
                    if result.stdout:
                        for pid in result.stdout.strip().split('\n'):
                            if pid:
                                logger.info(f"Killing existing process on port {self.ui_port} (PID: {pid})")
                                os.kill(int(pid), signal.SIGKILL)
                                time.sleep(0.5)
                except:
                    pass

        # Set API URL for UI
        self.env["GLEITZEIT_API_URL"] = f"http://localhost:{self.api_port}"
        self.env["GLEITZEIT_UI_PORT"] = str(self.ui_port)
        self.env["GLEITZEIT_UI_HOST"] = self.ui_host

        cmd = [
            sys.executable, "-m", "uvicorn",
            "gleitzeit.ui.api.app:app",
            "--host", self.ui_host,
            "--port", str(self.ui_port),
            "--log-level", "warning"  # Less verbose for UI
        ]

        # Check if reload is enabled in config
        reload_on_dev = self.config.get('serve', {}).get('ui', {}).get('reload_on_dev', True)
        if self.dev_mode and reload_on_dev:
            cmd.append("--reload")

        try:
            proc = subprocess.Popen(
                cmd,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            self.processes["ui"] = proc

            print(f"✓ UI Server started on http://{self.ui_host}:{self.ui_port}")

        except Exception as e:
            logger.error(f"Failed to start UI: {e}")
            raise

    def print_status(self):
        """Print status summary"""
        print("\n" + "=" * 60)
        print("✨ Gleitzeit is running!")
        print("=" * 60)
        print("\n📍 Service URLs:")
        print(f"   API Server:  http://localhost:{self.api_port}")
        if not self.no_ui:
            print(f"   Web UI:      http://localhost:{self.ui_port}")
        print(f"   API Docs:    http://localhost:{self.api_port}/docs")
        print("\n📊 Components:")
        for name, proc in self.processes.items():
            status = "✓ Running" if proc.poll() is None else "✗ Stopped"
            print(f"   {name.capitalize()}: {status}")
        print("\nPress Ctrl+C to stop all services")
        print("=" * 60 + "\n")

    def _handle_signal(self, signum, frame):
        """Handle shutdown signals"""
        print("\n\nShutting down Gleitzeit...")
        self.running = False
        self.stop()
        sys.exit(0)

    def stop(self):
        """Stop all components"""
        for name, proc in self.processes.items():
            if proc.poll() is None:
                print(f"Stopping {name}...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

        self.processes.clear()
        print("All services stopped")

    def get_process_stats(self) -> Dict:
        """Get process statistics"""
        stats = {}

        for name, proc in self.processes.items():
            if proc.poll() is None:
                try:
                    process = psutil.Process(proc.pid)
                    stats[name] = {
                        "pid": proc.pid,
                        "status": "running",
                        "cpu_percent": process.cpu_percent(),
                        "memory_mb": process.memory_info().rss / 1024 / 1024
                    }
                except:
                    stats[name] = {"status": "unknown"}
            else:
                stats[name] = {"status": "stopped", "exit_code": proc.returncode}

        return stats


# CLI Command
@click.command('serve')
@click.option('--config', '-c', type=click.Path(exists=True), help='Configuration file')
@click.option('--api-port', type=int, help='Override API server port from config')
@click.option('--ui-port', type=int, help='Override UI server port from config')
@click.option('--api-host', help='Override API host from config')
@click.option('--ui-host', help='Override UI host from config')
@click.option('--dev', is_flag=True, default=None, help='Development mode with auto-reload')
@click.option('--no-ui', is_flag=True, default=None, help='Start without UI server')
@click.option('--no-orchestrator', is_flag=True, default=None, help='Start without orchestrator (API and UI only)')
@click.option('--restart', is_flag=True, help='Stop existing Gleitzeit processes before starting')
def serve(config, api_port, ui_port, api_host, ui_host, dev, no_ui, no_orchestrator, restart):
    """
    Start all Gleitzeit components (orchestrator, API, and UI).

    Configuration is read from gleitzeit.yaml. Command-line options override
    the configuration file settings.

    Examples:
        gleitzeit serve                  # Use settings from gleitzeit.yaml
        gleitzeit serve --dev             # Override dev_mode
        gleitzeit serve --api-port 8080   # Override API port
        gleitzeit serve --no-ui           # Disable UI regardless of config
        gleitzeit serve --restart         # Stop existing processes and restart
    """

    # Check if config file exists, create default if not
    if config is None:
        default_config = Path("gleitzeit.yaml")
        if not default_config.exists():
            print("Creating default configuration...")
            create_default_config(default_config)
            config = str(default_config)

    server = GleitzeitServer(
        config_file=config,
        api_port=api_port,
        ui_port=ui_port,
        api_host=api_host,
        ui_host=ui_host,
        dev_mode=dev,
        no_ui=no_ui,
        no_orchestrator=no_orchestrator,
        restart=restart
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
        "sharding": {
            "num_shards": 16
        },
        "serve": {
            "api": {
                "host": "0.0.0.0",
                "port": 8000,
                "reload_on_dev": True
            },
            "ui": {
                "host": "0.0.0.0",
                "port": 8004,
                "enabled": True,
                "reload_on_dev": True
            },
            "orchestrator": {
                "enabled": True
            },
            "dev_mode": False
        },
        "workers": [
            {
                "worker_type": "task_execution",
                "worker_class": "gleitzeit.workers.task_execution_worker.TaskExecutionWorker",
                "count": 3,
                "auto_scale": True,
                "max_replicas": 10
            },
            {
                "worker_type": "workflow_loader",
                "worker_class": "gleitzeit.workers.workflow_loader_worker_v2.WorkflowLoaderWorkerV2",
                "count": 1,
                "auto_scale": False
            },
            {
                "worker_type": "dependency",
                "worker_class": "gleitzeit.workers.dependency_worker.DependencyWorker",
                "count": 2,
                "auto_scale": True,
                "max_replicas": 5
            }
        ]
    }

    with open(path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    print(f"Created default configuration at {path}")


if __name__ == "__main__":
    serve()