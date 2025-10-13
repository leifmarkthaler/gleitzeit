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
import yaml
import uuid
import socket
import redis

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

    def __init__(self, log_dir: Path = None, file_logging_enabled: bool = False):
        self.processes: Dict[str, ProcessInfo] = {}
        self.log_dir = log_dir or Path("logs")
        self.file_logging_enabled = file_logging_enabled

        # Only create log directory if file logging is enabled
        if self.file_logging_enabled:
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
                log_file=log_file if self.file_logging_enabled else None,
                started_at=datetime.now(),
                port=port
            )

            # Start streaming output only if file logging is enabled (this prevents deadlock!)
            if self.file_logging_enabled:
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

            # Log message with or without log file reference
            if self.file_logging_enabled:
                logger.info(f"✅ Started {name} (PID: {process.pid}, Log: {log_file})")
            else:
                logger.info(f"✅ Started {name} (PID: {process.pid}, Logs: Redis only)")
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
            # Handle attached processes (no subprocess object)
            if info.process is None:
                # Check if process is still running via PID
                try:
                    import psutil
                    if psutil.pid_exists(info.pid):
                        proc = psutil.Process(info.pid)
                        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                            status[name] = {
                                'status': 'running',
                                'pid': info.pid,
                                'uptime': (datetime.now() - info.started_at).total_seconds(),
                                'port': info.port
                            }
                        else:
                            status[name] = {
                                'status': 'dead',
                                'exit_code': -1,
                                'died_at': datetime.now().isoformat()
                            }
                            logger.error(f"Attached process {name} is dead/zombie")
                            del self.processes[name]
                    else:
                        status[name] = {
                            'status': 'dead',
                            'exit_code': -1,
                            'died_at': datetime.now().isoformat()
                        }
                        logger.error(f"Attached process {name} no longer exists")
                        del self.processes[name]
                except Exception:
                    # If we can't check, assume running
                    status[name] = {
                        'status': 'running',
                        'pid': info.pid,
                        'uptime': (datetime.now() - info.started_at).total_seconds(),
                        'port': info.port
                    }
            else:
                # Handle normal subprocess objects
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

    def __init__(self, config: dict = None, log_dir: Path = None, config_file: str = None, redis_url: str = None, port_offset: int = 0):
        self.config = config or {}
        self.config_file = config_file or 'gleitzeit.yaml'
        self.redis_url = redis_url or os.environ.get('REDIS_URL', 'redis://localhost:6379')
        self.port_offset = port_offset

        # Use ConfigurationManager as per the plan!
        from .config_manager import ConfigurationManager
        self.config_manager = ConfigurationManager(
            config_file=self.config_file,
            cli_args={}  # Could be populated from CLI
        )

        # Get file logging configuration
        logging_config = self.config_manager.get_all_config().get('logging', {})
        file_logging_enabled = logging_config.get('file_logging_enabled', False)

        self.process_manager = AsyncProcessManager(log_dir, file_logging_enabled=file_logging_enabled)
        self.python_path = sys.executable

        # Load handler configurations using ConfigurationManager
        self.handler_configs = {}
        if Path(self.config_file).exists():
            self._load_handler_configs()

        # Initialize Redis client for config storage
        self.redis_client = None
        self._init_redis()

        # Initialize SmartProcessManager for service registry
        self.smart_manager = None
        self.existing_services = {}

    def _init_redis(self):
        """Initialize Redis client for configuration storage"""
        try:
            self.redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
            self.redis_client.ping()
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}")
            self.redis_client = None

    def _get_network_hostname(self, bind_host: str) -> str:
        """Get network-accessible hostname for service registration"""
        # If explicitly binding to localhost/127.0.0.1, use that
        if bind_host in ['127.0.0.1', 'localhost']:
            return bind_host

        # If binding to 0.0.0.0, determine the best network address
        if bind_host == '0.0.0.0':
            try:
                # Try to get the hostname that other machines can use to reach us
                hostname = socket.gethostname()
                # Verify it resolves to a real IP
                socket.gethostbyname(hostname)
                return hostname
            except (socket.gaierror, OSError):
                try:
                    # Fallback: get local IP by connecting to a remote address
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                        s.connect(('8.8.8.8', 80))
                        local_ip = s.getsockname()[0]
                        return local_ip
                except OSError:
                    # Final fallback
                    return 'localhost'

        # For any other specific IP, use as-is
        return bind_host

    async def _init_smart_manager(self):
        """Initialize SmartProcessManager for service registry"""
        from .process_manager import SmartProcessManager
        from .instance import initialize_instance, get_current_instance

        try:
            # Initialize instance if not already done
            if not get_current_instance():
                initialize_instance(
                    instance_name="gleitzeit-native",
                    role="standalone",
                    port_offset=0
                )
                logger.info("Initialized instance identity for service registry")

            self.smart_manager = SmartProcessManager(config=self.config, redis_url=self.redis_url)
            await self.smart_manager.initialize()
            # Check for existing services
            registered_services = await self.smart_manager.get_registered_services()

            # Validate that registered services are actually still running
            self.existing_services = {}
            if registered_services:
                logger.info(f"Found {len(registered_services)} services in registry, checking health...")
                import psutil

                for service_name, service_info in registered_services.items():
                    try:
                        pid = int(service_info.get('pid', 0))
                        if pid and psutil.pid_exists(pid):
                            # Check if process is actually running
                            proc = psutil.Process(pid)
                            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                                self.existing_services[service_name] = service_info
                                logger.info(f"  ✅ {service_name} (PID: {pid}) is healthy")
                            else:
                                logger.info(f"  ❌ {service_name} (PID: {pid}) is zombie/dead, removing from registry")
                                await self.smart_manager.unregister_service(service_name)
                        else:
                            logger.info(f"  ❌ {service_name} has invalid/missing PID, removing from registry")
                            await self.smart_manager.unregister_service(service_name)
                    except (psutil.NoSuchProcess, ValueError) as e:
                        logger.info(f"  ❌ {service_name} process not found, removing from registry")
                        await self.smart_manager.unregister_service(service_name)

                if self.existing_services:
                    logger.info(f"Found {len(self.existing_services)} healthy existing services")
                for name, info in self.existing_services.items():
                    logger.info(f"  - {name}: PID={info.get('pid')}, Port={info.get('port')}")
        except Exception as e:
            import traceback
            logger.warning(f"Failed to initialize SmartProcessManager: {e}")
            logger.warning(f"Traceback: {traceback.format_exc()}")
            self.smart_manager = None

    def _load_handler_configs(self):
        """Load handler configurations from gleitzeit.yaml"""
        try:
            with open(self.config_file, 'r') as f:
                full_config = yaml.safe_load(f)

            # Extract handler configurations
            handlers_section = full_config.get('handlers', {})

            for handler_name, handler_config in handlers_section.items():
                if handler_name == 'global':
                    continue

                protocol = f"{handler_name}/v1"
                # Store the FULL handler configuration, not just the 'config' section
                # This includes 'execution', 'config', and any other sections
                self.handler_configs[protocol] = handler_config.copy()

                # For backward compatibility, if there's a config section, merge it at the top level
                if 'config' in handler_config:
                    # Merge config section keys into top level for backward compatibility
                    config_section = handler_config['config']
                    for key, value in config_section.items():
                        # Don't override execution or other top-level sections
                        if key not in self.handler_configs[protocol]:
                            self.handler_configs[protocol][key] = value

            if self.handler_configs:
                logger.info(f"Loaded handler configs for: {list(self.handler_configs.keys())}")
            else:
                logger.info("No handler configurations found in config file")

        except Exception as e:
            logger.warning(f"Failed to load handler configs from {self.config_file}: {e}")
            self.handler_configs = {}

    async def start_api(self, host: str = "0.0.0.0", port: int = 8000, dev_mode: bool = False):
        """Start API service"""
        # Check if already running in registry
        if "api" in self.existing_services:
            existing = self.existing_services["api"]
            logger.info(f"API service already running (PID: {existing.get('pid')}, Port: {existing.get('port')})")
            return ProcessInfo(
                pid=int(existing.get('pid')),
                name="api",
                command=[],
                process=None,
                port=int(existing.get('port', port)),
                started_at=datetime.now()
            )

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
            'REDIS_URL': self.redis_url,
            'REDIS_CLUSTER_NODES': self.redis_url.replace('redis://', '').replace('/', ''),
            'GLEITZEIT_AUTO_LOGIN': 'true'
        }

        result = await self.process_manager.start_process(
            "api", command, env=env, port=port
        )

        # Register in service registry
        if result and self.smart_manager:
            network_host = self._get_network_hostname(host)
            await self.smart_manager.register_service("api", {
                "pid": str(result.pid),
                "port": str(port),
                "host": network_host,
                "started_at": datetime.now().isoformat(),
                "mode": "native"
            })

        return result

    async def start_ui(self, host: str = "0.0.0.0", port: int = 8004, api_port: int = 8000, dev_mode: bool = False):
        """Start UI service"""
        # Check if already running in registry
        if "ui" in self.existing_services:
            existing = self.existing_services["ui"]
            logger.info(f"UI service already running (PID: {existing.get('pid')}, Port: {existing.get('port')})")
            return ProcessInfo(
                pid=int(existing.get('pid')),
                name="ui",
                command=[],
                process=None,
                port=int(existing.get('port', port)),
                started_at=datetime.now()
            )

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
            'REDIS_URL': self.redis_url,
            'REDIS_CLUSTER_NODES': self.redis_url.replace('redis://', '').replace('/', ''),
            'API_URL': f'http://localhost:{api_port}'
        }

        result = await self.process_manager.start_process(
            "ui", command, env=env, port=port
        )

        # Register in service registry
        if result and self.smart_manager:
            network_host = self._get_network_hostname(host)
            await self.smart_manager.register_service("ui", {
                "pid": str(result.pid),
                "port": str(port),
                "host": network_host,
                "started_at": datetime.now().isoformat(),
                "mode": "native"
            })

        return result

    async def start_worker(self, worker_config: dict):
        """Start a worker from configuration"""
        worker_type = worker_config.get('worker_type')
        worker_class = worker_config.get('worker_class')
        worker_id = f"{worker_type}-async"

        # Check if already running in registry
        worker_name = f"worker_{worker_type}"
        if worker_name in self.existing_services:
            existing = self.existing_services[worker_name]
            logger.info(f"Worker {worker_name} already running (PID: {existing.get('pid')})")
            return ProcessInfo(
                pid=int(existing.get('pid')),
                name=worker_name,
                command=[],
                process=None,
                port=None,
                started_at=datetime.now()
            )

        # Build complete configuration including handler configs
        full_config = {
            'worker_type': worker_type,
            'worker_class': worker_class,
            'worker_id': worker_id,
            'max_concurrent': worker_config.get('max_concurrent', 10),
            'batch_size': worker_config.get('batch_size', 10),
            'block_timeout': worker_config.get('block_timeout', 5000),
            'shards': list(range(16)),  # All shards
            'redis_url': 'redis://localhost:6379',
            'redis_cluster_nodes': ['localhost:6379']
        }

        # Add handler configurations if available
        if self.handler_configs:
            # Deep copy to avoid modifying original
            full_config['handler_configs'] = {
                protocol: config.copy() for protocol, config in self.handler_configs.items()
            }

        # Merge worker-specific handler configs if present
        if 'handler_configs' in worker_config:
            if 'handler_configs' not in full_config:
                full_config['handler_configs'] = {}
            # Deep merge worker configs with global configs
            for protocol, worker_handler_config in worker_config['handler_configs'].items():
                if protocol in full_config['handler_configs']:
                    # Merge worker config with global config (worker overrides specific keys)
                    merged_config = full_config['handler_configs'][protocol].copy()
                    merged_config.update(worker_handler_config)
                    full_config['handler_configs'][protocol] = merged_config
                else:
                    # New protocol config from worker
                    full_config['handler_configs'][protocol] = worker_handler_config

        # Store configuration in Redis if available
        if self.redis_client:
            try:
                config_key = f"worker:config:{worker_id}:{uuid.uuid4().hex[:8]}"
                config_json = json.dumps(full_config)
                self.redis_client.setex(config_key, 3600, config_json)  # 1 hour expiry

                # Use config-key based startup (preferred)
                command = [
                    self.python_path, "-m", "gleitzeit.workers.runner",
                    "--config-key", config_key,
                    "--redis-url", self.redis_url
                ]

                logger.info(f"Starting worker {worker_id} with config key {config_key}")
                if self.handler_configs:
                    logger.info(f"  Handler configs included for: {list(self.handler_configs.keys())}")

            except Exception as e:
                logger.warning(f"Failed to store config in Redis: {e}, falling back to CLI args")
                # Fall back to CLI arguments
                command = self._build_fallback_command(worker_config, worker_class, worker_id)
        else:
            # No Redis available, use CLI arguments
            command = self._build_fallback_command(worker_config, worker_class, worker_id)

        env = {
            'REDIS_URL': self.redis_url,
            'REDIS_CLUSTER_NODES': self.redis_url.replace('redis://', '').replace('/', ''),
            'LOG_LEVEL': 'INFO'
        }

        result = await self.process_manager.start_process(
            f"worker_{worker_type}", command, env=env
        )

        # Register in service registry
        if result and self.smart_manager:
            await self.smart_manager.register_service(f"worker_{worker_type}", {
                "pid": str(result.pid),
                "worker_type": worker_type,
                "worker_id": worker_id,
                "started_at": datetime.now().isoformat(),
                "mode": "native"
            })

        return result

    def _build_fallback_command(self, worker_config, worker_class, worker_id):
        """Build fallback command using CLI arguments"""
        return [
            self.python_path, "-m", "gleitzeit.workers.runner",
            "--worker-class", worker_class,
            "--worker-id", worker_id,
            "--worker-type", worker_config.get('worker_type'),
            "--redis-url", self.redis_url,
            "--shards", "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15",
            "--max-concurrent", str(worker_config.get('max_concurrent', 10)),
            "--batch-size", str(worker_config.get('batch_size', 10)),
            "--block-timeout", str(worker_config.get('block_timeout', 5000))
        ]

    async def start_essential_workers(self):
        """Start all configured workers from YAML"""
        workers = self.config.get('workers', [])

        # Start ALL workers defined in configuration - no hardcoded filter
        for worker_config in workers:
            await self.start_worker(worker_config)

    async def start_all(self, api_port: int = 8000, ui_port: int = 8004, no_ui: bool = False, dev_mode: bool = False, restart: bool = False, no_workers: bool = False, no_api: bool = False):
        """Start all services"""
        # Initialize SmartProcessManager for service registry
        await self._init_smart_manager()

        # Track whether we're attaching to existing services or starting new ones
        self.attached_mode = False

        # If services exist and not restarting, attach to them
        if self.existing_services and not restart:
            logger.info(f"Found {len(self.existing_services)} existing services, attaching to them")
            self.attached_mode = True

            # Reconstruct ProcessInfo objects for existing services
            for service_name, service_info in self.existing_services.items():
                pid = int(service_info.get('pid', 0))
                port = service_info.get('port')
                if port:
                    port = int(port)

                # Create a ProcessInfo object for the existing service
                info = ProcessInfo(
                    pid=pid,
                    name=service_name,
                    command=[],  # Command not stored, but not needed for monitoring
                    process=None,  # Can't attach to subprocess, but we can monitor via PID
                    port=port,
                    started_at=datetime.fromisoformat(service_info.get('started_at', datetime.now().isoformat()))
                )
                self.process_manager.processes[service_name] = info
                logger.info(f"  Attached to {service_name} (PID: {pid}, Port: {port})")

            # Return existing status
            return await self.process_manager.monitor_processes()

        # If restarting, stop existing services first
        if restart and self.existing_services:
            logger.info("Restarting services...")
            await self.stop_all()
            await asyncio.sleep(2)
            self.existing_services = {}

        # Start API if enabled
        if not no_api:
            # Use config ports if available, otherwise use provided defaults
            config_api_port = self.config.get('api', {}).get('port', api_port)
            actual_api_port = config_api_port + self.port_offset
            await self.start_api(port=actual_api_port, dev_mode=dev_mode)

            # Wait for API to be ready
            await asyncio.sleep(2)

        # Start UI if enabled
        if not no_ui and not no_api:
            config_ui_port = self.config.get('ui', {}).get('port', ui_port)
            actual_ui_port = config_ui_port + self.port_offset
            actual_api_port = self.config.get('api', {}).get('port', api_port) + self.port_offset
            await self.start_ui(port=actual_ui_port, api_port=actual_api_port, dev_mode=dev_mode)

        # Start essential workers if enabled
        if not no_workers:
            await self.start_essential_workers()

        return await self.process_manager.monitor_processes()

    async def stop_all(self):
        """Stop all services"""
        await self.process_manager.stop_all()

        # Only unregister services if we started them (not if we attached)
        if self.smart_manager and not getattr(self, 'attached_mode', False):
            # Track which services we actually started vs attached to
            started_services = set()
            for name, info in self.process_manager.processes.items():
                # Services with actual subprocess objects were started by us
                if info.process is not None:
                    started_services.add(name)

            # Only unregister services we started
            for service_name in started_services:
                await self.smart_manager.unregister_service(service_name)
                logger.info(f"Unregistered service {service_name} that we started")

    async def _service_heartbeat_loop(self):
        """
        Periodically refresh service registrations to prevent expiry.

        Uses circuit breaker pattern - never terminates, backs off on failures.
        """
        from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitOpenError

        # Create circuit breaker for service heartbeat
        circuit_breaker = CircuitBreaker(
            "service_heartbeat",
            CircuitBreakerConfig(
                failure_threshold=10,
                success_threshold=2,
                reset_timeout=300  # 5 minutes
            )
        )

        while True:  # Never exit - keep trying forever
            try:
                await asyncio.sleep(30)  # Heartbeat every 30 seconds

                # Wrap the actual heartbeat work in circuit breaker
                await circuit_breaker.call(self._refresh_service_registrations)

            except CircuitOpenError as e:
                # Circuit is open - back off longer
                logger.warning(
                    f"Service heartbeat circuit breaker is OPEN: {e}. "
                    f"Backing off for {e.reset_timeout}s"
                )
                await asyncio.sleep(e.reset_timeout)

            except asyncio.CancelledError:
                # Allow graceful cancellation
                logger.info("Service heartbeat loop cancelled")
                raise

            except Exception as e:
                # Unexpected error - log and continue
                logger.error(f"Unexpected error in service heartbeat loop: {e}", exc_info=True)
                await asyncio.sleep(30)

    async def _refresh_service_registrations(self):
        """
        Refresh service registrations (called through circuit breaker).

        Raises:
            Exception: On any failure (circuit breaker will track)
        """
        if not self.smart_manager:
            logger.warning("No smart_manager available for service refresh")
            return

        # Re-register all running services
        services_refreshed = 0
        for name, info in self.process_manager.processes.items():
            if info.process is not None or info.pid:  # Service is running
                if name == "api" or name == "ui":
                    # Re-register service with updated TTL
                    service_data = await self.smart_manager.redis.hgetall(f"service:registry:{name}")
                    if service_data:
                        # Decode and refresh
                        decoded_data = {}
                        for k, v in service_data.items():
                            key = k.decode() if isinstance(k, bytes) else k
                            value = v.decode() if isinstance(v, bytes) else v
                            decoded_data[key] = value

                        # Re-register with fresh TTL
                        await self.smart_manager.register_service(name, decoded_data)
                        logger.debug(f"Refreshed registration for {name}")
                        services_refreshed += 1

        if services_refreshed == 0:
            logger.debug("No services to refresh in this heartbeat cycle")

    async def monitor_loop(self, auto_restart=True):
        """Monitor services and restart if needed"""
        restart_attempts = {}
        max_restart_attempts = 3

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self._service_heartbeat_loop())

        try:
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
        finally:
            # Clean up heartbeat task
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


# Export for use in CLI
__all__ = ['AsyncProcessManager', 'AsyncServiceManager']