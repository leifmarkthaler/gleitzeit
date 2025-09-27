"""
Async Process Manager for Gleitzeit - Fixes subprocess deadlock issue

This implementation uses asyncio.create_subprocess_exec instead of subprocess.Popen
to properly handle process I/O without deadlocking.
"""

import asyncio
import os
import sys
import signal
import logging
from typing import Dict, Optional, List, Any
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import json

logger = logging.getLogger(__name__)


@dataclass
class ProcessInfo:
    """Information about a running process"""
    pid: int
    name: str
    command: List[str]
    process: asyncio.subprocess.Process
    stdout_task: Optional[asyncio.Task] = None
    stderr_task: Optional[asyncio.Task] = None
    log_file: Optional[Path] = None
    started_at: datetime = None
    port: Optional[int] = None


class AsyncProcessManager:
    """
    Async process manager that fixes the subprocess deadlock issue.

    Key improvements:
    - Uses asyncio.create_subprocess_exec instead of subprocess.Popen
    - Streams output asynchronously to avoid buffer deadlock
    - Proper process lifecycle management
    - Health monitoring without blocking
    """

    def __init__(self, log_dir: Path = None):
        self.processes: Dict[str, ProcessInfo] = {}
        self.log_dir = log_dir or Path("logs")
        self.log_dir.mkdir(exist_ok=True, parents=True)
        self._running = True

    async def _stream_output(self, stream, name: str, log_file: Path, prefix: str = ""):
        """Stream output from a process to a log file"""
        try:
            with open(log_file, 'a') as f:
                while True:
                    line = await stream.readline()
                    if not line:
                        break

                    decoded_line = line.decode('utf-8', errors='replace')
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log_line = f"[{timestamp}] {prefix}{decoded_line}"

                    # Write to file
                    f.write(log_line)
                    f.flush()

                    # Also log important lines
                    if any(keyword in decoded_line.lower() for keyword in ['error', 'failed', 'exception']):
                        logger.error(f"{name}: {decoded_line.strip()}")
                    elif 'warning' in decoded_line.lower():
                        logger.warning(f"{name}: {decoded_line.strip()}")

        except Exception as e:
            logger.error(f"Error streaming output for {name}: {e}")

    async def start_process(
        self,
        name: str,
        command: List[str],
        env: Optional[Dict[str, str]] = None,
        port: Optional[int] = None,
        cwd: Optional[Path] = None,
        restart_on_failure: bool = True
    ) -> ProcessInfo:
        """
        Start a process asynchronously with proper I/O handling.

        This fixes the subprocess deadlock by:
        1. Using asyncio.create_subprocess_exec
        2. Streaming output to files asynchronously
        3. Never blocking on pipe reads
        """

        # Check if already running
        if name in self.processes:
            existing = self.processes[name]
            if existing.process.returncode is None:  # Still running
                logger.info(f"Process {name} already running (PID: {existing.pid})")
                return existing
            else:
                # Clean up dead process
                del self.processes[name]

        # Create log file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"{name}_{timestamp}.log"

        logger.info(f"Starting {name}: {' '.join(command)}")

        # Prepare environment
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        # CRITICAL: Set REDIS_CLUSTER_NODES for workers
        if 'REDIS_CLUSTER_NODES' not in process_env:
            process_env['REDIS_CLUSTER_NODES'] = 'localhost:6379'

        # Create process with asyncio (no PIPE deadlock!)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
                cwd=cwd,
                start_new_session=True  # Create new process group
            )

            # Create process info
            info = ProcessInfo(
                pid=process.pid,
                name=name,
                command=command,
                process=process,
                log_file=log_file,
                started_at=datetime.now(),
                port=port
            )

            # Start streaming output (this prevents deadlock!)
            info.stdout_task = asyncio.create_task(
                self._stream_output(process.stdout, name, log_file, "[STDOUT] ")
            )
            info.stderr_task = asyncio.create_task(
                self._stream_output(process.stderr, name, log_file, "[STDERR] ")
            )

            self.processes[name] = info

            # Wait a moment to check if it started successfully
            await asyncio.sleep(0.5)

            if process.returncode is not None:
                # Process died immediately
                logger.error(f"Process {name} died immediately with code {process.returncode}")
                del self.processes[name]
                raise RuntimeError(f"Process {name} failed to start")

            logger.info(f"✅ Started {name} (PID: {process.pid}, Log: {log_file})")
            return info

        except Exception as e:
            logger.error(f"Failed to start {name}: {e}")
            raise

    async def stop_process(self, name: str, timeout: float = 5.0) -> bool:
        """Stop a process gracefully with timeout"""
        if name not in self.processes:
            return True

        info = self.processes[name]
        if info.process.returncode is not None:
            # Already dead
            del self.processes[name]
            return True

        logger.info(f"Stopping {name} (PID: {info.pid})")

        try:
            # Try graceful termination
            info.process.terminate()

            # Wait for termination with timeout
            try:
                await asyncio.wait_for(info.process.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                # Force kill if needed
                logger.warning(f"Process {name} didn't terminate, killing...")
                info.process.kill()
                await info.process.wait()

            # Cancel output streaming tasks
            if info.stdout_task:
                info.stdout_task.cancel()
            if info.stderr_task:
                info.stderr_task.cancel()

            del self.processes[name]
            logger.info(f"Stopped {name}")
            return True

        except Exception as e:
            logger.error(f"Error stopping {name}: {e}")
            return False

    async def stop_all(self):
        """Stop all processes"""
        tasks = []
        for name in list(self.processes.keys()):
            tasks.append(self.stop_process(name))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def monitor_processes(self) -> Dict[str, Any]:
        """Monitor process health"""
        status = {}

        for name, info in list(self.processes.items()):
            returncode = info.process.returncode

            if returncode is None:
                # Still running
                status[name] = {
                    'status': 'running',
                    'pid': info.pid,
                    'uptime': (datetime.now() - info.started_at).total_seconds(),
                    'port': info.port
                }
            else:
                # Process died
                status[name] = {
                    'status': 'dead',
                    'exit_code': returncode,
                    'died_at': datetime.now().isoformat()
                }

                logger.error(f"Process {name} died with code {returncode}")

                # Clean up
                del self.processes[name]

        return status

    async def restart_process(self, name: str) -> bool:
        """Restart a process"""
        if name not in self.processes:
            logger.error(f"Process {name} not found")
            return False

        info = self.processes[name]
        command = info.command
        port = info.port

        # Stop it first
        await self.stop_process(name)

        # Start it again
        try:
            await self.start_process(name, command, port=port)
            return True
        except Exception as e:
            logger.error(f"Failed to restart {name}: {e}")
            return False

    def get_process_info(self, name: str) -> Optional[ProcessInfo]:
        """Get information about a process"""
        return self.processes.get(name)

    def list_processes(self) -> List[str]:
        """List all managed processes"""
        return list(self.processes.keys())


class AsyncServiceManager:
    """High-level service management using AsyncProcessManager"""

    def __init__(self, config: dict = None, log_dir: Path = None):
        self.config = config or {}
        self.process_manager = AsyncProcessManager(log_dir)
        self.python_path = sys.executable

    async def start_api(self, host: str = "0.0.0.0", port: int = 8000, dev_mode: bool = False):
        """Start API service"""
        command = [
            self.python_path, "-m", "uvicorn",
            "gleitzeit.api.main:app",
            "--host", host,
            "--port", str(port),
            "--log-level", "info"
        ]

        if dev_mode:
            command.append("--reload")

        env = {
            'REDIS_URL': 'redis://localhost:6379',
            'REDIS_CLUSTER_NODES': 'localhost:6379',
            'GLEITZEIT_AUTO_LOGIN': 'true'
        }

        return await self.process_manager.start_process(
            "api", command, env=env, port=port
        )

    async def start_ui(self, host: str = "0.0.0.0", port: int = 8004, api_port: int = 8000, dev_mode: bool = False):
        """Start UI service"""
        command = [
            self.python_path, "-m", "uvicorn",
            "gleitzeit.ui.api.app:app",
            "--host", host,
            "--port", str(port),
            "--log-level", "warning"
        ]

        if dev_mode:
            command.append("--reload")

        env = {
            'REDIS_URL': 'redis://localhost:6379',
            'REDIS_CLUSTER_NODES': 'localhost:6379',
            'API_URL': f'http://localhost:{api_port}'
        }

        return await self.process_manager.start_process(
            "ui", command, env=env, port=port
        )

    async def start_worker(self, worker_config: dict):
        """Start a worker from configuration"""
        worker_type = worker_config.get('worker_type')
        worker_class = worker_config.get('worker_class')
        worker_id = f"{worker_type}-async"

        command = [
            self.python_path, "-m", "gleitzeit.workers.runner",
            "--worker-class", worker_class,
            "--worker-id", worker_id,
            "--worker-type", worker_type,
            "--redis-url", "redis://localhost:6379",
            "--shards", "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15",
            "--max-concurrent", str(worker_config.get('max_concurrent', 10)),
            "--batch-size", str(worker_config.get('batch_size', 10)),
            "--block-timeout", str(worker_config.get('block_timeout', 5000))
        ]

        env = {
            'REDIS_URL': 'redis://localhost:6379',
            'REDIS_CLUSTER_NODES': 'localhost:6379',
            'LOG_LEVEL': 'INFO'
        }

        return await self.process_manager.start_process(
            f"worker_{worker_type}", command, env=env
        )

    async def start_essential_workers(self):
        """Start only essential workers for native mode"""
        workers = self.config.get('workers', [])

        essential_types = [
            'workflow_loader',
            'dependency',
            'task_execution',
            'workflow_submission'
        ]

        for worker_config in workers:
            if worker_config.get('worker_type') in essential_types:
                await self.start_worker(worker_config)

    async def start_all(self, api_port: int = 8000, ui_port: int = 8004, no_ui: bool = False, dev_mode: bool = False):
        """Start all services"""
        # Start API
        await self.start_api(port=api_port, dev_mode=dev_mode)

        # Wait for API to be ready
        await asyncio.sleep(2)

        # Start UI if enabled
        if not no_ui:
            await self.start_ui(port=ui_port, api_port=api_port, dev_mode=dev_mode)

        # Start essential workers
        await self.start_essential_workers()

        return await self.process_manager.monitor_processes()

    async def stop_all(self):
        """Stop all services"""
        await self.process_manager.stop_all()

    async def monitor_loop(self, auto_restart=True):
        """Monitor services and restart if needed"""
        restart_attempts = {}
        max_restart_attempts = 3

        while True:
            status = await self.process_manager.monitor_processes()

            # Check for dead processes and restart if needed
            for name, info in status.items():
                if info.get('status') == 'dead':
                    logger.error(f"Service {name} died with exit code {info.get('exit_code')}")

                    if auto_restart:
                        # Track restart attempts
                        if name not in restart_attempts:
                            restart_attempts[name] = 0

                        if restart_attempts[name] < max_restart_attempts:
                            restart_attempts[name] += 1
                            logger.info(f"Attempting to restart {name} (attempt {restart_attempts[name]}/{max_restart_attempts})")

                            # Try to restart the service
                            if name == 'api':
                                await self.start_api(port=self.config.get('api_port', 8000))
                            elif name == 'ui':
                                await self.start_ui(port=self.config.get('ui_port', 8004))
                            elif name.startswith('worker_'):
                                worker_type = name.replace('worker_', '')
                                for worker_config in self.config.get('workers', []):
                                    if worker_config.get('worker_type') == worker_type:
                                        await self.start_worker(worker_config)
                                        break
                        else:
                            logger.error(f"Max restart attempts reached for {name}, giving up")
                elif info.get('status') == 'running':
                    # Reset restart counter for running processes
                    if name in restart_attempts:
                        restart_attempts[name] = 0

            await asyncio.sleep(5)


# Export for use in CLI
__all__ = ['AsyncProcessManager', 'AsyncServiceManager']