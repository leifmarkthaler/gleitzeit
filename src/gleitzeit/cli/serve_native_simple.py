"""
Simplified native serve implementation for Gleitzeit

This implementation:
- Uses the same workers and handlers as Docker mode
- Fixes the subprocess PIPE deadlock by using files for output
- Simplifies process management for single-machine deployment
- No complex orchestration, just direct process spawning
"""

import asyncio
import subprocess
import sys
import os
import signal
import logging
from pathlib import Path
from typing import Dict, List, Optional
import click
import yaml
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class SimpleNativeServer:
    """Simple native server without complex orchestration"""

    def __init__(
        self,
        config_file: str = "gleitzeit.yaml",
        api_host: str = "0.0.0.0",
        api_port: int = 8000,
        ui_host: str = "0.0.0.0",
        ui_port: int = 8004,
        no_ui: bool = False,
        dev_mode: bool = False
    ):
        self.config_file = config_file
        self.api_host = api_host
        self.api_port = api_port
        self.ui_host = ui_host
        self.ui_port = ui_port
        self.no_ui = no_ui
        self.dev_mode = dev_mode
        self.processes: Dict[str, subprocess.Popen] = {}
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)

        # Load configuration
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load configuration from file"""
        config_path = Path(self.config_file)
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
        return {}

    def _get_python_path(self) -> str:
        """Get the Python executable path"""
        # Use the current Python interpreter
        return sys.executable

    def _create_log_files(self, name: str) -> tuple:
        """Create log files for a process"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stdout_path = self.log_dir / f"{name}_{timestamp}.out"
        stderr_path = self.log_dir / f"{name}_{timestamp}.err"

        stdout_file = open(stdout_path, 'w')
        stderr_file = open(stderr_path, 'w')

        return stdout_file, stderr_file, stdout_path, stderr_path

    def start_redis_check(self) -> bool:
        """Check if Redis is running"""
        try:
            import redis
            r = redis.Redis(host='localhost', port=6379)
            r.ping()
            return True
        except:
            return False

    def start_api(self) -> bool:
        """Start the API server"""
        if 'api' in self.processes:
            logger.info("API already running")
            return True

        click.echo("🚀 Starting API server...")

        # Create log files
        stdout_file, stderr_file, stdout_path, stderr_path = self._create_log_files("api")

        # Build command
        python_path = self._get_python_path()
        cmd = [
            python_path, "-m", "uvicorn",
            "gleitzeit.api.main:app",
            "--host", self.api_host,
            "--port", str(self.api_port),
            "--log-level", "info"
        ]

        if self.dev_mode:
            cmd.append("--reload")

        # Set environment
        env = os.environ.copy()
        env['REDIS_URL'] = 'redis://localhost:6379'
        env['REDIS_CLUSTER_NODES'] = 'localhost:6379'
        env['GLEITZEIT_AUTO_LOGIN'] = 'true'

        # Start process with output to files (no PIPE!)
        try:
            process = subprocess.Popen(
                cmd,
                stdout=stdout_file,
                stderr=stderr_file,
                env=env,
                start_new_session=True  # Create new process group
            )

            self.processes['api'] = process
            click.echo(f"✅ API started (PID: {process.pid})")
            click.echo(f"   Logs: {stdout_path}")
            return True

        except Exception as e:
            click.echo(f"❌ Failed to start API: {e}")
            stdout_file.close()
            stderr_file.close()
            return False

    def start_ui(self) -> bool:
        """Start the UI server"""
        if self.no_ui:
            return True

        if 'ui' in self.processes:
            logger.info("UI already running")
            return True

        click.echo("🚀 Starting UI server...")

        # Create log files
        stdout_file, stderr_file, stdout_path, stderr_path = self._create_log_files("ui")

        # Build command
        python_path = self._get_python_path()
        cmd = [
            python_path, "-m", "uvicorn",
            "gleitzeit.ui.api.app:app",
            "--host", self.ui_host,
            "--port", str(self.ui_port),
            "--log-level", "warning"
        ]

        if self.dev_mode:
            cmd.append("--reload")

        # Set environment
        env = os.environ.copy()
        env['REDIS_URL'] = 'redis://localhost:6379'
        env['REDIS_CLUSTER_NODES'] = 'localhost:6379'
        env['API_URL'] = f'http://localhost:{self.api_port}'

        # Start process with output to files
        try:
            process = subprocess.Popen(
                cmd,
                stdout=stdout_file,
                stderr=stderr_file,
                env=env,
                start_new_session=True
            )

            self.processes['ui'] = process
            click.echo(f"✅ UI started (PID: {process.pid})")
            click.echo(f"   Logs: {stdout_path}")
            return True

        except Exception as e:
            click.echo(f"❌ Failed to start UI: {e}")
            stdout_file.close()
            stderr_file.close()
            return False

    def start_workers(self) -> bool:
        """Start essential workers from configuration"""
        workers = self.config.get('workers', [])

        # For native mode, only start essential workers with count=1
        essential_workers = [
            'workflow_loader',
            'dependency',
            'task_execution',
            'workflow_submission'
        ]

        click.echo("🚀 Starting workers...")

        for worker_config in workers:
            worker_type = worker_config.get('worker_type')

            # Skip non-essential workers in native mode
            if worker_type not in essential_workers:
                continue

            worker_class = worker_config.get('worker_class')
            worker_id = f"{worker_type}-native"

            # Create log files
            stdout_file, stderr_file, stdout_path, stderr_path = self._create_log_files(f"worker_{worker_type}")

            # Build command
            python_path = self._get_python_path()
            cmd = [
                python_path, "-m", "gleitzeit.workers.runner",
                "--worker-class", worker_class,
                "--worker-id", worker_id,
                "--worker-type", worker_type,
                "--redis-url", "redis://localhost:6379",
                "--shards", "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15",
                "--max-concurrent", str(worker_config.get('max_concurrent', 5)),
                "--batch-size", str(worker_config.get('batch_size', 10)),
                "--block-timeout", str(worker_config.get('block_timeout', 5000))
            ]

            # Set environment
            env = os.environ.copy()
            env['REDIS_URL'] = 'redis://localhost:6379'
            env['REDIS_CLUSTER_NODES'] = 'localhost:6379'  # Critical!
            env['LOG_LEVEL'] = 'INFO'

            # Start process
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    env=env,
                    start_new_session=True
                )

                self.processes[f'worker_{worker_type}'] = process
                click.echo(f"  ✅ Worker {worker_type} started (PID: {process.pid})")

            except Exception as e:
                click.echo(f"  ❌ Failed to start worker {worker_type}: {e}")
                stdout_file.close()
                stderr_file.close()

        return True

    async def start(self):
        """Start all services"""
        click.echo("\n🎯 Starting Gleitzeit in native mode (simplified)")
        click.echo("=" * 60)

        # Check Redis
        if not self.start_redis_check():
            click.echo("❌ Redis is not running!")
            click.echo("Please start Redis first:")
            click.echo("  brew services start redis  # macOS")
            click.echo("  sudo systemctl start redis  # Linux")
            click.echo("  redis-server                # Manual")
            sys.exit(1)
        else:
            click.echo("✅ Redis is running")

        # Start services
        if not self.start_api():
            self.stop()
            sys.exit(1)

        # Wait a bit for API to start
        await asyncio.sleep(2)

        if not self.start_ui():
            self.stop()
            sys.exit(1)

        # Wait a bit for UI to start
        await asyncio.sleep(1)

        if not self.start_workers():
            self.stop()
            sys.exit(1)

        click.echo("\n" + "=" * 60)
        click.echo("✨ Gleitzeit is running!")
        click.echo(f"   API: http://{self.api_host}:{self.api_port}")
        if not self.no_ui:
            click.echo(f"   UI:  http://{self.ui_host}:{self.ui_port}")
        click.echo(f"   Logs: {self.log_dir}/")
        click.echo("\nPress Ctrl+C to stop all services")
        click.echo("=" * 60)

        # Wait for interrupt
        try:
            while True:
                # Check if processes are still running
                for name, process in list(self.processes.items()):
                    if process.poll() is not None:
                        click.echo(f"\n⚠️  Process {name} died (exit code: {process.returncode})")
                        # Don't restart in simple mode, just note it

                await asyncio.sleep(5)

        except KeyboardInterrupt:
            click.echo("\n🛑 Stopping services...")
            self.stop()

    def stop(self):
        """Stop all services"""
        for name, process in self.processes.items():
            if process.poll() is None:  # Still running
                click.echo(f"Stopping {name} (PID: {process.pid})")
                try:
                    # Try graceful shutdown first
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force kill if needed
                    process.kill()
                    process.wait()
                except Exception as e:
                    click.echo(f"Error stopping {name}: {e}")

        self.processes.clear()
        click.echo("✅ All services stopped")


async def serve_native_simple(
    config_file: str = "gleitzeit.yaml",
    api_host: str = "0.0.0.0",
    api_port: int = 8000,
    ui_host: str = "0.0.0.0",
    ui_port: int = 8004,
    no_ui: bool = False,
    dev_mode: bool = False
):
    """Simple native serve implementation without subprocess deadlock"""

    server = SimpleNativeServer(
        config_file=config_file,
        api_host=api_host,
        api_port=api_port,
        ui_host=ui_host,
        ui_port=ui_port,
        no_ui=no_ui,
        dev_mode=dev_mode
    )

    await server.start()


# Export for use in serve_unified.py
__all__ = ['serve_native_simple', 'SimpleNativeServer']