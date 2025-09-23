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

        # Kill by port if still in use
        for port in [self.api_port, self.ui_port]:
            try:
                for proc in psutil.process_iter(['pid', 'connections']):
                    connections = proc.info.get('connections', [])
                    if connections:
                        for conn in connections:
                            if hasattr(conn, 'laddr') and conn.laddr.port == port:
                                try:
                                    psutil.Process(proc.pid).terminate()
                                except:
                                    pass
            except:
                pass

        time.sleep(3)  # Give processes time to stop
        print("Existing processes stopped")

    def start(self):
        """Start all components"""
        # Check for existing processes
        existing = self.check_existing_processes()

        if any(existing.values()):
            if self.restart:
                print("\n⚠️  Existing Gleitzeit processes detected")
                self.kill_existing_processes()
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
                        # Try to restart
                        if name == "orchestrator" and not self.no_orchestrator:
                            self.start_orchestrator()
                        elif name == "api":
                            self.start_api()
                        elif name == "ui" and not self.no_ui:
                            self.start_ui()

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

    def start_api(self):
        """Start the API server"""
        print(f"Starting API Server on port {self.api_port}...")

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

    def start_ui(self):
        """Start the UI server"""
        print(f"Starting UI Server on port {self.ui_port}...")

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