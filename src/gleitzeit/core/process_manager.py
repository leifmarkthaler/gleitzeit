"""
Smart Process Manager for Gleitzeit

Instance-aware process management with ownership tracking,
distributed locking, and proper lifecycle management.
"""

import os
import time
import signal
import subprocess
import psutil
import asyncio
import logging
import json
from typing import Dict, Optional, Set, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import fcntl
from pathlib import Path
import redis.asyncio as aioredis
from enum import Enum
import sys

from .instance import get_current_instance

logger = logging.getLogger(__name__)


class ProcessType(Enum):
    """Types of managed processes"""
    SERVICE = "service"  # API, UI, etc
    WORKER = "worker"    # Task execution, dependency, etc


@dataclass
class ProcessInfo:
    """Information about a managed process"""
    name: str
    pid: int
    port: Optional[int]  # Workers may not need ports
    command: List[str]
    started_at: datetime
    instance_id: str
    process_type: ProcessType = ProcessType.SERVICE
    assigned_shards: List[int] = field(default_factory=list)
    worker_config: Optional[Dict[str, Any]] = None
    restart_count: int = 0
    last_restart_at: Optional[datetime] = None
    status: str = "starting"  # starting, running, failed, stopped
    exit_code: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "name": self.name,
            "pid": self.pid,
            "port": self.port,
            "command": self.command,
            "started_at": self.started_at.isoformat(),
            "instance_id": self.instance_id,
            "process_type": self.process_type.value,
            "assigned_shards": self.assigned_shards,
            "worker_config": self.worker_config,
            "restart_count": self.restart_count,
            "last_restart_at": self.last_restart_at.isoformat() if self.last_restart_at else None,
            "status": self.status,
            "exit_code": self.exit_code
        }


class SmartProcessManager:
    """Instance-aware process management with proper lifecycle handling"""

    def __init__(self, redis_url: str = "redis://localhost:6379", config: Optional[Dict] = None):
        """
        Initialize Smart Process Manager

        Args:
            redis_url: Redis connection URL for coordination
            config: Configuration dictionary
        """
        self.instance = get_current_instance()
        if not self.instance:
            raise RuntimeError("Instance identity not initialized")

        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self.config = config or {}

        # Worker configuration
        self.worker_configs = self._load_worker_configs()
        self.num_shards = self.config.get('sharding', {}).get('num_shards', 16)
        self.shard_assignments: Dict[int, List[str]] = {i: [] for i in range(self.num_shards)}

        # Process tracking
        self.owned_processes: Dict[str, ProcessInfo] = {}
        self.managed_pids: Set[int] = set()
        self.process_handles: Dict[str, subprocess.Popen] = {}

        # Restart policy
        self.max_restart_attempts = 3
        self.restart_backoff_base = 2  # seconds
        self.restart_backoff_max = 300  # 5 minutes
        self.stable_uptime_seconds = 30

        # Lock files for port management
        self.lock_dir = Path("/tmp/gleitzeit_locks")
        self.lock_dir.mkdir(exist_ok=True)
        self.port_locks: Dict[int, Any] = {}

    def _load_worker_configs(self) -> Dict[str, Dict[str, Any]]:
        """Load worker configurations"""
        default_configs = {
            "task_execution": {
                "enabled": False,  # Disabled by default
                "worker_class": "gleitzeit.workers.task_execution_worker.TaskExecutionWorker",
                "count": 2,
                "max_concurrent": 10,
                "batch_size": 10,
                "block_timeout": 5000,
                "auto_scale": True,
                "min_replicas": 1,
                "max_replicas": 10
            },
            "dependency": {
                "enabled": False,  # Disabled by default
                "worker_class": "gleitzeit.workers.dependency_worker.DependencyWorker",
                "count": 2,
                "max_concurrent": 10,
                "batch_size": 10,
                "block_timeout": 5000,
                "auto_scale": True,
                "min_replicas": 1,
                "max_replicas": 5
            },
            "retry": {
                "enabled": False,
                "worker_class": "gleitzeit.workers.retry_worker.RetryWorker",
                "count": 1,
                "max_concurrent": 10,
                "batch_size": 10,
                "block_timeout": 5000,
                "auto_scale": False
            },
            "workflow_loader": {
                "enabled": False,
                "worker_class": "gleitzeit.workers.workflow_loader_worker.WorkflowLoaderWorker",
                "count": 1,
                "max_concurrent": 10,
                "batch_size": 10,
                "block_timeout": 5000,
                "auto_scale": False
            }
        }

        # Handle both list and dict formats for workers config
        worker_configs = self.config.get('workers', [])

        # If it's a list (as in our gleitzeit.yaml), convert to dict
        if isinstance(worker_configs, list):
            configs_dict = {}
            for worker_config in worker_configs:
                worker_type = worker_config.get('worker_type')
                if worker_type:
                    configs_dict[worker_type] = worker_config
            worker_configs = configs_dict

        # Merge with defaults
        for worker_type, config in worker_configs.items():
            if worker_type in default_configs:
                default_configs[worker_type].update(config)
            else:
                default_configs[worker_type] = config

        return default_configs

    async def _register_machine(self):
        """Register machine information in Redis"""
        machine_key = f"machine:{self.instance.machine_id}:info"
        machine_info = self.instance.machine_info.to_dict()

        # Add additional machine metadata
        machine_info['last_seen'] = datetime.utcnow().isoformat()
        machine_info['capabilities'] = json.dumps(self.instance.capabilities.to_dict())

        # Store machine info
        await self.redis.hset(
            machine_key,
            mapping={k: str(v) for k, v in machine_info.items()}
        )
        await self.redis.expire(machine_key, 3600)  # 1 hour TTL

        # Register machine in global registry
        await self.redis.sadd("machine:registry", self.instance.machine_id)

        # Register machine by datacenter/rack/zone for topology awareness
        if hasattr(self.instance.machine_info, 'datacenter'):
            await self.redis.sadd(
                f"datacenter:{self.instance.machine_info.datacenter}:machines",
                self.instance.machine_id
            )
        if hasattr(self.instance.machine_info, 'rack'):
            await self.redis.sadd(
                f"rack:{self.instance.machine_info.rack}:machines",
                self.instance.machine_id
            )
        if hasattr(self.instance.machine_info, 'network_zone'):
            await self.redis.sadd(
                f"network_zone:{self.instance.machine_info.network_zone}:machines",
                self.instance.machine_id
            )

        logger.info(f"Registered machine {self.instance.machine_id} ({self.instance.machine_info.hostname})")

    async def initialize(self):
        """Initialize Redis connection and register machine/instance"""
        self.redis = aioredis.from_url(
            self.redis_url,
            decode_responses=True
        )

        # Register machine first
        await self._register_machine()

        # Register this instance
        await self.redis.sadd("instance:registry", self.instance.instance_id)

        # Add instance to machine's instance set
        await self.redis.sadd(
            f"machine:{self.instance.machine_id}:instances",
            self.instance.instance_id
        )

        # Store comprehensive instance info
        instance_info = {
            "id": self.instance.instance_id,
            "name": self.instance.instance_name,
            "role": self.instance.role,
            "machine_id": self.instance.machine_id,
            "machine_ip": self.instance.machine_ip,
            "machine_fingerprint": self.instance.get_machine_fingerprint(),
            "deployment_id": self.instance.deployment_id,
            "port_offset": self.instance.port_offset,
            "started_at": datetime.utcnow().isoformat(),
            "capabilities": json.dumps(self.instance.capabilities.to_dict()),
            "metadata": json.dumps(self.instance.metadata.to_dict())
        }
        await self.redis.hset(
            f"instance:{self.instance.instance_id}:info",
            mapping={k: str(v) for k, v in instance_info.items()}
        )
        await self.redis.expire(f"instance:{self.instance.instance_id}:info", 3600)

        logger.info(f"Registered instance {self.instance.instance_id} on machine {self.instance.machine_id}")

        # Start configured workers if enabled
        if self.config.get('workers_enabled', False):
            await self.start_all_workers()

    async def start_all_workers(self):
        """Start all configured workers"""
        for worker_type, config in self.worker_configs.items():
            if not config.get('enabled', False):
                logger.info(f"Skipping {worker_type} workers (disabled)")
                continue

            count = config.get('count', 0)
            if count <= 0:
                logger.info(f"Skipping {worker_type} workers (count={count})")
                continue

            logger.info(f"Starting {count} {worker_type} workers")
            for i in range(count):
                worker_name = f"{worker_type}-{i}"
                assigned_shards = self._assign_shards_to_worker(worker_name, worker_type, i, count)

                await self.start_worker(
                    worker_name=worker_name,
                    worker_type=worker_type,
                    worker_class=config['worker_class'],
                    assigned_shards=assigned_shards,
                    config=config
                )

    def _assign_shards_to_worker(self, worker_name: str, worker_type: str, index: int, total: int) -> List[int]:
        """Assign shards to a worker using round-robin distribution"""
        if total <= 0:
            return []

        assigned = []
        for shard in range(self.num_shards):
            if shard % total == index:
                assigned.append(shard)
                self.shard_assignments[shard].append(worker_name)

        return assigned

    async def start_worker(
        self,
        worker_name: str,
        worker_type: str,
        worker_class: str,
        assigned_shards: List[int],
        config: Dict[str, Any]
    ) -> Optional[ProcessInfo]:
        """Start a worker process"""
        logger.info(f"Starting worker {worker_name} with shards {assigned_shards}")

        # Build command
        cmd = [
            sys.executable, "-m", "gleitzeit.workers.runner",
            "--worker-class", worker_class,
            "--worker-id", worker_name,
            "--redis-url", self.redis_url,
            "--shards", ",".join(map(str, assigned_shards)),
            "--max-concurrent", str(config.get('max_concurrent', 10)),
            "--batch-size", str(config.get('batch_size', 10)),
            "--block-timeout", str(config.get('block_timeout', 5000))
        ]

        # Start as a process without port (workers don't need ports)
        return await self._start_process(
            process_name=worker_name,
            command=cmd,
            process_type=ProcessType.WORKER,
            port=None,
            env=None,
            kill_existing=False,
            assigned_shards=assigned_shards,
            worker_config=config
        )

    async def close(self):
        """Clean up resources"""
        if self.redis:
            await self.redis.close()

        # Release all port locks
        for lock in self.port_locks.values():
            try:
                fcntl.flock(lock, fcntl.LOCK_UN)
                lock.close()
            except:
                pass

    def _get_port_lock_path(self, port: int) -> Path:
        """Get path for port lock file"""
        return self.lock_dir / f"port_{port}.lock"

    def _try_acquire_port_lock(self, port: int) -> bool:
        """
        Try to acquire exclusive lock on a port

        Returns:
            True if lock acquired, False otherwise
        """
        lock_path = self._get_port_lock_path(port)

        # Ensure lock directory exists
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Try to create or open the lock file
            lock_file = open(lock_path, 'w')

            # Try to acquire exclusive non-blocking lock
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Write instance info to lock file
            lock_info = {
                "instance_id": self.instance.instance_id,
                "pid": os.getpid(),
                "acquired_at": datetime.utcnow().isoformat()
            }
            lock_file.write(json.dumps(lock_info))
            lock_file.flush()

            self.port_locks[port] = lock_file
            return True

        except (IOError, OSError) as e:
            # If we opened the file but couldn't lock it, close it
            if 'lock_file' in locals():
                try:
                    lock_file.close()
                except:
                    pass
            return False

    def _release_port_lock(self, port: int):
        """Release lock on a port"""
        if port in self.port_locks:
            try:
                lock_file = self.port_locks[port]
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
                del self.port_locks[port]

                # Remove lock file
                lock_path = self._get_port_lock_path(port)
                if lock_path.exists():
                    lock_path.unlink()
            except:
                pass

    def _check_port_owner(self, port: int) -> Optional[str]:
        """
        Check who owns a port lock

        Returns:
            Instance ID of owner, or None if not locked
        """
        lock_path = self._get_port_lock_path(port)
        if not lock_path.exists():
            return None

        try:
            with open(lock_path, 'r') as f:
                lock_info = json.loads(f.read())
                return lock_info.get("instance_id")
        except:
            return None

    def _find_process_on_port(self, port: int) -> Optional[psutil.Process]:
        """Find process listening on a specific port"""
        # First try using lsof with grep for LISTEN state (most reliable)
        try:
            import subprocess
            # Use lsof to find processes LISTENING on the port
            result = subprocess.run(
                ['lsof', '-i', f':{port}'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout:
                # Parse lsof output to find LISTENING processes only
                for line in result.stdout.strip().split('\n')[1:]:  # Skip header
                    if 'LISTEN' in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                pid = int(parts[1])
                                return psutil.Process(pid)
                            except (ValueError, psutil.NoSuchProcess):
                                continue
        except:
            pass

        # Fallback to psutil, but only check for LISTEN state
        try:
            for proc in psutil.process_iter(['pid', 'connections']):
                connections = proc.info.get('connections', [])
                if connections:
                    for conn in connections:
                        # Check for LISTEN state specifically
                        if (hasattr(conn, 'laddr') and
                            conn.laddr.port == port and
                            hasattr(conn, 'status') and
                            conn.status == psutil.CONN_LISTEN):
                            return proc
        except:
            pass

        return None

    def _kill_process_tree(self, proc: psutil.Process, include_parent: bool = True):
        """Kill a process and all its children"""
        try:
            # First, check if the process has a parent that's a shell
            # This handles cases where a shell script is running the actual server in a loop
            parent_proc = None
            try:
                parent_proc = proc.parent()
                if parent_proc and parent_proc.name() in ['bash', 'sh', 'zsh', 'fish']:
                    logger.debug(f"Found parent shell process {parent_proc.pid} for process {proc.pid}")
                    # Use the parent shell as the root to kill
                    proc = parent_proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            children = proc.children(recursive=True)

            # Kill all children first
            for child in children:
                try:
                    logger.debug(f"Killing child process {child.pid}")
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Then kill the parent
            if include_parent:
                try:
                    logger.debug(f"Killing parent process {proc.pid}")
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Wait for processes to actually die
            gone, alive = psutil.wait_procs(children + ([proc] if include_parent else []), timeout=3)

            # Force kill any survivors with SIGKILL
            for p in alive:
                try:
                    logger.debug(f"Force killing surviving process {p.pid}")
                    p.kill()
                except:
                    pass

        except Exception as e:
            logger.debug(f"Error killing process tree: {e}")

    def _is_our_process(self, pid: int) -> bool:
        """Check if a process belongs to this instance"""
        return pid in self.managed_pids

    def _calculate_restart_backoff(self, restart_count: int) -> int:
        """
        Calculate exponential backoff for restart attempts

        Returns:
            Backoff time in seconds
        """
        backoff = min(
            self.restart_backoff_base ** restart_count,
            self.restart_backoff_max
        )
        return int(backoff)

    async def claim_service(self, service_name: str, port: int) -> bool:
        """
        Try to claim ownership of a service

        Uses distributed locking via Redis to ensure only one instance
        owns a service at a time.

        Returns:
            True if service claimed, False otherwise
        """
        if not self.redis:
            await self.initialize()

        lock_key = f"service_lock:{service_name}"
        lock_value = f"{self.instance.instance_id}:{os.getpid()}"

        # Try to acquire distributed lock with 30 second TTL
        result = await self.redis.set(
            lock_key,
            lock_value,
            nx=True,  # Only set if not exists
            ex=30     # 30 second expiry
        )

        if result:
            logger.info(f"Claimed service {service_name} for instance {self.instance.instance_id}")

            # Add to service registry for discovery
            service_type = self._get_service_type(service_name)
            await self.redis.sadd(
                f"service:registry:{service_type}",
                self.instance.instance_id
            )

            # Store ownership info for coordination
            await self.redis.set(
                f"service:ownership:{service_name}",
                json.dumps({
                    "instance_id": self.instance.instance_id,
                    "instance_name": self.instance.instance_name,
                    "port": port,
                    "claimed_at": datetime.utcnow().isoformat()
                }),
                ex=3600  # 1 hour TTL
            )

            return True
        else:
            # Check who owns it
            owner = await self.redis.get(lock_key)
            logger.info(f"Service {service_name} already claimed by {owner}")
            return False

    async def release_service(self, service_name: str):
        """Release ownership of a service"""
        if not self.redis:
            return

        lock_key = f"service_lock:{service_name}"
        lock_value = f"{self.instance.instance_id}:{os.getpid()}"

        # Remove from service registry
        service_type = self._get_service_type(service_name)
        await self.redis.srem(
            f"service:registry:{service_type}",
            self.instance.instance_id
        )

        # Remove ownership info
        await self.redis.delete(f"service:ownership:{service_name}")

        # Only delete if we own it
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """

        await self.redis.eval(lua_script, 1, lock_key, lock_value)

    async def start_service(
        self,
        service_name: str,
        command: List[str],
        port: int,
        env: Optional[Dict[str, str]] = None,
        kill_existing: bool = False
    ) -> Optional[ProcessInfo]:
        """Start a service process (API, UI, etc)"""
        return await self._start_process(
            process_name=service_name,
            command=command,
            process_type=ProcessType.SERVICE,
            port=port,
            env=env,
            kill_existing=kill_existing
        )

    async def _start_process(
        self,
        process_name: str,
        command: List[str],
        process_type: ProcessType,
        port: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        kill_existing: bool = False,
        assigned_shards: Optional[List[int]] = None,
        worker_config: Optional[Dict[str, Any]] = None
    ) -> Optional[ProcessInfo]:
        """
        Start a service with proper ownership and lifecycle management

        Args:
            service_name: Name of the service
            command: Command to execute
            port: Port the service will use
            env: Environment variables
            kill_existing: Whether to kill existing processes on the port

        Returns:
            ProcessInfo if started successfully, None otherwise
        """
        logger.info(f"Starting process {process_name} on port {port}")

        # Check if we already own this service
        if process_name in self.owned_processes:
            existing = self.owned_processes[process_name]
            if existing.status == "running":
                logger.info(f"Service {process_name} already running (PID: {existing.pid})")
                return existing

        # Try to acquire port lock
        if not self._try_acquire_port_lock(port):
            owner = self._check_port_owner(port)
            if owner == self.instance.instance_id:
                logger.info(f"Port {port} already locked by this instance")
            elif owner:
                logger.warning(f"Port {port} locked by instance {owner}")
                if not kill_existing:
                    return None
                # When kill_existing=True, we need to kill the process and clear the lock
                logger.info(f"Killing existing processes on port {port} (locked by instance {owner})")
                existing_proc = self._find_process_on_port(port)
                if existing_proc:
                    # Kill the entire process tree to handle shell restart loops
                    self._kill_process_tree(existing_proc)
                # Force remove the lock file owned by another instance
                lock_path = self._get_port_lock_path(port)
                try:
                    lock_path.unlink()
                    logger.info(f"Removed stale lock file for port {port}")
                except:
                    pass
                time.sleep(2)  # Give OS time to release port

                # Try multiple times to acquire the lock
                max_retries = 3
                for retry in range(max_retries):
                    if self._try_acquire_port_lock(port):
                        logger.info(f"Successfully acquired port {port} lock after {retry+1} attempts")
                        break

                    # Check if port is still in use and kill again if needed
                    proc_on_port = self._find_process_on_port(port)
                    if proc_on_port:
                        logger.warning(f"Port {port} still in use by PID {proc_on_port.pid}, killing process tree")
                        # Kill the entire process tree to handle shell restart loops
                        self._kill_process_tree(proc_on_port)

                    # Remove lock file again if it exists
                    try:
                        lock_path.unlink()
                    except:
                        pass

                    time.sleep(1)
                else:
                    logger.error(f"Failed to acquire port {port} lock after {max_retries} attempts")
                    return None
            else:
                # Port lock failed but no owner found - port might be in use by external process
                logger.warning(f"Port {port} appears to be in use but lock owner unknown")
                # Check if port is actually in use
                existing_proc = self._find_process_on_port(port)
                if existing_proc:
                    if not kill_existing:
                        logger.warning(f"Port {port} in use by PID {existing_proc.pid} (not managed)")
                        return None
                    else:
                        # Kill the process when kill_existing=True
                        logger.info(f"Killing existing process on port {port} (PID: {existing_proc.pid})")
                        # Kill the entire process tree to handle shell restart loops
                        self._kill_process_tree(existing_proc)
                        # Force remove any stale lock file
                        lock_path = self._get_port_lock_path(port)
                        try:
                            lock_path.unlink()
                            logger.info(f"Removed stale lock file for port {port}")
                        except:
                            pass
                        time.sleep(2)  # Give OS time to release port

                        # Try multiple times to acquire the lock
                        max_retries = 3
                        for retry in range(max_retries):
                            if self._try_acquire_port_lock(port):
                                logger.info(f"Successfully acquired port {port} lock after {retry+1} attempts")
                                break

                            # Check if port is still in use and kill again if needed
                            proc_on_port = self._find_process_on_port(port)
                            if proc_on_port:
                                logger.warning(f"Port {port} still in use by PID {proc_on_port.pid}, killing process tree")
                                # Kill the entire process tree to handle shell restart loops
                                self._kill_process_tree(proc_on_port)

                            # Remove lock file again if it exists
                            try:
                                lock_path.unlink()
                            except:
                                pass

                            time.sleep(1)
                        else:
                            logger.error(f"Failed to acquire port {port} lock after {max_retries} attempts")
                            return None

        # Check for existing process on port
        existing_proc = self._find_process_on_port(port)
        if existing_proc:
            if self._is_our_process(existing_proc.pid):
                logger.info(f"Port {port} used by our process {existing_proc.pid}")
            else:
                if kill_existing:
                    logger.info(f"Killing existing process on port {port} (PID: {existing_proc.pid})")
                    # Kill the entire process tree to handle shell restart loops
                    self._kill_process_tree(existing_proc)
                    time.sleep(2)  # Give OS time to release port
                else:
                    logger.warning(f"Port {port} already in use by PID {existing_proc.pid}")
                    return None

        # Try to claim the service globally
        if not await self.claim_service(process_name, port):
            logger.warning(f"Could not claim service {process_name}")
            self._release_port_lock(port)
            return None

        # Start the process
        try:
            # Prepare environment - include all necessary vars but not PYTHONPATH
            process_env = {
                'PATH': os.environ.get('PATH', ''),
                'HOME': os.environ.get('HOME', ''),
                'USER': os.environ.get('USER', ''),
                'SHELL': os.environ.get('SHELL', '/bin/bash'),
                'TERM': os.environ.get('TERM', 'xterm-256color'),
                'LANG': os.environ.get('LANG', 'en_US.UTF-8'),
                'LC_ALL': os.environ.get('LC_ALL', 'en_US.UTF-8'),
                'TMPDIR': os.environ.get('TMPDIR', '/tmp'),
                # Don't copy PYTHONPATH - venv handles this
            }
            if env:
                process_env.update(env)

            # Add instance information to environment
            process_env['GLEITZEIT_INSTANCE_ID'] = self.instance.instance_id
            process_env['GLEITZEIT_SERVICE_NAME'] = process_name
            process_env['GLEITZEIT_SERVICE_PORT'] = str(port)

            # Log the command being executed
            logger.info(f"Executing command: {' '.join(command)}")

            # Determine working directory (project root)
            from pathlib import Path
            # Go up from src/gleitzeit/core to project root
            cwd = Path(__file__).parent.parent.parent.parent
            logger.info(f"Working directory: {cwd}")

            # Start process in new process group
            proc = subprocess.Popen(
                command,
                env=process_env,
                cwd=str(cwd),  # Set working directory
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # Separate stderr for better debugging
                preexec_fn=os.setsid  # Create new process group
            )

            logger.debug(f"Process started with PID: {proc.pid}")

            # Quick check for immediate failure (0.5 seconds)
            time.sleep(0.5)
            if proc.poll() is not None:
                # Process died immediately - likely import error
                stdout, stderr = proc.communicate()
                logger.error(f"Service {process_name} failed immediately!")
                if stdout:
                    logger.error(f"STDOUT: {stdout.decode('utf-8', errors='ignore')}")
                if stderr:
                    logger.error(f"STDERR: {stderr.decode('utf-8', errors='ignore')}")

                # Clean up and return early
                await self.release_service(process_name)
                self._release_port_lock(port)
                return None

            # Track the process
            process_info = ProcessInfo(
                name=process_name,
                pid=proc.pid,
                port=port,
                command=command,
                started_at=datetime.utcnow(),
                instance_id=self.instance.instance_id,
                status="starting",
                process_type=process_type
            )

            self.owned_processes[process_name] = process_info
            self.managed_pids.add(proc.pid)
            self.process_handles[process_name] = proc

            # Store process info in Redis for monitoring
            await self._update_redis_process_info(process_name, process_info, process_type, assigned_shards)

            # Wait a bit and check if process is still running
            time.sleep(2)
            if proc.poll() is None:
                # Double check - wait a bit more and check again
                time.sleep(1)
                if proc.poll() is None:
                    process_info.status = "running"
                    # Update Redis with running status
                    await self._update_redis_process_info(process_name, process_info, process_type, assigned_shards)
                    logger.info(f"Service {process_name} started successfully (PID: {proc.pid})")
                    return process_info
                else:
                    # Died between checks
                    logger.warning(f"Service {process_name} died after initial success check")

            # Process has died
            process_info.status = "failed"
            process_info.exit_code = proc.poll()

            # Try to get all output for debugging
            try:
                stdout, stderr = proc.communicate(timeout=0.5)
                if stdout:
                    logger.error(f"Service {process_name} STDOUT: {stdout.decode('utf-8', errors='ignore')}")
                if stderr:
                    logger.error(f"Service {process_name} STDERR: {stderr.decode('utf-8', errors='ignore')}")
            except subprocess.TimeoutExpired:
                # Process is still running but returned non-zero somehow
                logger.error(f"Could not get output from {process_name} (timeout)")
            except Exception as e:
                logger.error(f"Could not read process output: {e}")

            logger.error(f"Service {process_name} failed to start (exit code: {proc.poll()})")

            # Clean up
            await self.release_service(process_name)
            self._release_port_lock(port)
            del self.owned_processes[process_name]
            self.managed_pids.discard(proc.pid)
            del self.process_handles[process_name]

            return None

        except Exception as e:
            logger.error(f"Failed to start service {process_name}: {e}")
            await self.release_service(process_name)
            self._release_port_lock(port)
            return None

    async def stop_service(self, service_name: str, timeout: int = 10):
        """
        Stop a service gracefully

        Args:
            service_name: Name of the service to stop
            timeout: Timeout for graceful shutdown
        """
        if service_name not in self.owned_processes:
            logger.warning(f"Service {service_name} not owned by this instance")
            return

        process_info = self.owned_processes[service_name]
        proc = self.process_handles.get(service_name)

        if not proc:
            logger.warning(f"No process handle for service {service_name}")
            return

        logger.info(f"Stopping service {service_name} (PID: {process_info.pid})")

        try:
            # Send SIGTERM for graceful shutdown
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)

            # Wait for process to exit
            proc.wait(timeout=timeout)

        except subprocess.TimeoutExpired:
            # Force kill if timeout
            logger.warning(f"Service {service_name} did not stop gracefully, forcing kill")
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait()

        except Exception as e:
            logger.error(f"Error stopping service {service_name}: {e}")

        # Clean up
        process_info.status = "stopped"
        await self.release_service(service_name)
        self._release_port_lock(process_info.port)
        self.managed_pids.discard(process_info.pid)

        # Remove from tracking
        del self.owned_processes[service_name]
        del self.process_handles[service_name]

    async def monitor_services(self):
        """
        Monitor running services and restart if needed

        This should be called periodically to check service health
        and restart failed services with exponential backoff.
        """
        for service_name, process_info in list(self.owned_processes.items()):
            proc = self.process_handles.get(service_name)

            if not proc:
                continue

            # Check if process is still running
            exit_code = proc.poll()

            if exit_code is not None:
                # Process died
                process_info.status = "failed"
                process_info.exit_code = exit_code

                uptime = (datetime.utcnow() - process_info.started_at).total_seconds()

                logger.warning(
                    f"Service {service_name} died (exit code: {exit_code}, "
                    f"uptime: {uptime:.1f}s, restarts: {process_info.restart_count})"
                )

                # Check if we should restart
                if process_info.restart_count >= self.max_restart_attempts:
                    logger.error(
                        f"Service {service_name} exceeded max restart attempts ({self.max_restart_attempts})"
                    )
                    # Clean up
                    await self.release_service(service_name)
                    self._release_port_lock(process_info.port)
                    del self.owned_processes[service_name]
                    del self.process_handles[service_name]
                    continue

                # Reset restart count if process was stable
                if uptime >= self.stable_uptime_seconds and process_info.restart_count > 0:
                    logger.info(f"Service {service_name} was stable, resetting restart count")
                    process_info.restart_count = 0

                # Calculate backoff
                backoff = self._calculate_restart_backoff(process_info.restart_count)
                logger.info(f"Restarting {service_name} in {backoff} seconds (attempt {process_info.restart_count + 1})")

                # Schedule restart (in production, this would be async)
                await asyncio.sleep(backoff)

                # Update restart info
                process_info.restart_count += 1
                process_info.last_restart_at = datetime.utcnow()

                # Restart the service
                await self.start_service(
                    service_name,
                    process_info.command,
                    process_info.port,
                    kill_existing=False  # Don't kill, we know it's dead
                )

    async def stop_all_services(self):
        """Stop all services owned by this instance"""
        logger.info(f"Stopping all services for instance {self.instance.instance_id}")

        for service_name in list(self.owned_processes.keys()):
            await self.stop_service(service_name)

    def get_service_status(self) -> Dict[str, Any]:
        """Get status of all managed services"""
        return {
            "instance_id": self.instance.instance_id,
            "services": {
                name: info.to_dict()
                for name, info in self.owned_processes.items()
            }
        }

    async def _update_redis_process_info(
        self,
        process_name: str,
        process_info: ProcessInfo,
        process_type: ProcessType,
        assigned_shards: Optional[List[int]] = None
    ):
        """Store process information in Redis for monitoring"""
        # Store in instance-specific hash
        process_key = f"instance:{self.instance.instance_id}:process:{process_name}"

        process_data = {
            "name": process_name,
            "pid": str(process_info.pid),
            "port": str(process_info.port) if process_info.port else "",
            "status": process_info.status,
            "type": process_type.value,
            "started_at": process_info.started_at.isoformat(),
            "restart_count": str(process_info.restart_count),
            "command": " ".join(process_info.command) if process_info.command else ""
        }

        if process_info.last_restart_at:
            process_data["last_restart_at"] = process_info.last_restart_at.isoformat()

        if process_info.exit_code is not None:
            process_data["exit_code"] = str(process_info.exit_code)

        if assigned_shards:
            process_data["assigned_shards"] = json.dumps(assigned_shards)

        await self.redis.hset(process_key, mapping=process_data)

        # Set TTL on process data (1 hour)
        await self.redis.expire(process_key, 3600)

    def _get_service_type(self, service_name: str) -> str:
        """Extract service type from service name"""
        # Handle both "api" and "api-1" style names
        if service_name.startswith("api"):
            return "api"
        elif service_name.startswith("ui"):
            return "ui"
        elif "task_execution" in service_name:
            return "task_execution"
        elif "dependency" in service_name:
            return "dependency"
        elif "workflow_loader" in service_name:
            return "workflow_loader"
        elif "retry" in service_name:
            return "retry"
        else:
            # Default to using the base name (before any dash)
            return service_name.split("-")[0]

    async def discover_services(self, service_type: str) -> List[Dict[str, Any]]:
        """
        Discover all instances of a service type across all machines

        Args:
            service_type: Type of service (api, ui, etc)

        Returns:
            List of service instances with connection info
        """
        if not self.redis:
            await self.initialize()

        instances = []

        # Get all instances registered for this service type
        instance_ids = await self.redis.smembers(f"service:registry:{service_type}")

        for instance_id in instance_ids:
            # Get instance info
            instance_info = await self.redis.hgetall(f"instance:{instance_id}:info")
            if not instance_info:
                continue

            # Get service ownership info
            ownership = await self.redis.get(f"service:ownership:{service_type}")
            if ownership:
                ownership_data = json.loads(ownership)

                # Build service discovery record
                service_record = {
                    "instance_id": instance_id,
                    "instance_name": instance_info.get("name"),
                    "machine_id": instance_info.get("machine_id"),
                    "machine_ip": instance_info.get("machine_ip"),
                    "port": ownership_data.get("port"),
                    "deployment_id": instance_info.get("deployment_id"),
                    "metadata": json.loads(instance_info.get("metadata", "{}")),
                    "capabilities": json.loads(instance_info.get("capabilities", "{}")),
                    "url": f"http://{instance_info.get('machine_ip')}:{ownership_data.get('port')}"
                }

                # Check if we can communicate with this instance
                if hasattr(self.instance, 'can_communicate_with'):
                    other_metadata = service_record["metadata"]
                    can_communicate = bool(
                        set(self.instance.metadata.network_tags) &
                        set(other_metadata.get("network_tags", []))
                    )
                    service_record["can_communicate"] = can_communicate

                instances.append(service_record)

        return instances

    async def discover_machines(self, datacenter: Optional[str] = None,
                              rack: Optional[str] = None,
                              zone: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Discover machines based on location criteria

        Args:
            datacenter: Filter by datacenter
            rack: Filter by rack
            zone: Filter by network zone

        Returns:
            List of machine information
        """
        if not self.redis:
            await self.initialize()

        machines = []

        # Determine which machines to query
        if datacenter:
            machine_ids = await self.redis.smembers(f"datacenter:{datacenter}:machines")
        elif rack:
            machine_ids = await self.redis.smembers(f"rack:{rack}:machines")
        elif zone:
            machine_ids = await self.redis.smembers(f"network_zone:{zone}:machines")
        else:
            machine_ids = await self.redis.smembers("machine:registry")

        for machine_id in machine_ids:
            machine_info = await self.redis.hgetall(f"machine:{machine_id}:info")
            if machine_info:
                # Get instances on this machine
                instance_ids = await self.redis.smembers(f"machine:{machine_id}:instances")

                machine_record = {
                    "machine_id": machine_id,
                    "hostname": machine_info.get("hostname"),
                    "fqdn": machine_info.get("fqdn"),
                    "primary_ip": machine_info.get("primary_ip"),
                    "datacenter": machine_info.get("datacenter"),
                    "rack": machine_info.get("rack"),
                    "network_zone": machine_info.get("network_zone"),
                    "instances": list(instance_ids),
                    "instance_count": len(instance_ids),
                    "last_seen": machine_info.get("last_seen"),
                    "capabilities": json.loads(machine_info.get("capabilities", "{}"))
                }

                machines.append(machine_record)

        return machines

    async def get_topology_map(self) -> Dict[str, Any]:
        """
        Get complete topology map of the deployment

        Returns:
            Hierarchical map of datacenters -> racks -> machines -> instances
        """
        if not self.redis:
            await self.initialize()

        topology = {
            "total_machines": 0,
            "total_instances": 0,
            "datacenters": {}
        }

        # Get all machines
        machine_ids = await self.redis.smembers("machine:registry")
        topology["total_machines"] = len(machine_ids)

        for machine_id in machine_ids:
            machine_info = await self.redis.hgetall(f"machine:{machine_id}:info")
            if not machine_info:
                continue

            dc = machine_info.get("datacenter", "default")
            rack = machine_info.get("rack", "default")

            # Initialize datacenter if needed
            if dc not in topology["datacenters"]:
                topology["datacenters"][dc] = {
                    "racks": {},
                    "machine_count": 0,
                    "instance_count": 0
                }

            # Initialize rack if needed
            if rack not in topology["datacenters"][dc]["racks"]:
                topology["datacenters"][dc]["racks"][rack] = {
                    "machines": {},
                    "machine_count": 0,
                    "instance_count": 0
                }

            # Get instances on this machine
            instance_ids = await self.redis.smembers(f"machine:{machine_id}:instances")

            # Add machine to rack
            topology["datacenters"][dc]["racks"][rack]["machines"][machine_id] = {
                "hostname": machine_info.get("hostname"),
                "ip": machine_info.get("primary_ip"),
                "instances": list(instance_ids),
                "instance_count": len(instance_ids)
            }

            # Update counts
            topology["datacenters"][dc]["machine_count"] += 1
            topology["datacenters"][dc]["instance_count"] += len(instance_ids)
            topology["datacenters"][dc]["racks"][rack]["machine_count"] += 1
            topology["datacenters"][dc]["racks"][rack]["instance_count"] += len(instance_ids)
            topology["total_instances"] += len(instance_ids)

        return topology

    async def register_service(self, name: str, info: Dict):
        """Add persistent service registration with shorter TTL for heartbeat"""
        if not self.redis:
            await self.initialize()

        key = f"service:registry:{name}"
        await self.redis.hset(key, mapping=info)
        # Set TTL to 60 seconds - services will need to heartbeat to refresh
        await self.redis.expire(key, 60)
        logger.info(f"Registered service {name} in registry with 60s TTL")

    async def get_registered_services(self) -> Dict:
        """Get all registered services"""
        if not self.redis:
            await self.initialize()

        services = {}

        # Use scan_iter for simpler iteration
        try:
            async for key in self.redis.scan_iter(match="service:registry:*"):
                # Decode key if it's bytes
                key_str = key.decode() if isinstance(key, bytes) else key
                service_name = key_str.split(":")[-1]

                # Get service info as a hash
                info_raw = await self.redis.hgetall(key_str)

                # Decode the info dictionary (redis-py returns bytes)
                info = {}
                for field, value in info_raw.items():
                    field_str = field.decode() if isinstance(field, bytes) else field
                    value_str = value.decode() if isinstance(value, bytes) else value
                    info[field_str] = value_str

                # Check if process is still running
                if 'pid' in info:
                    try:
                        pid = int(info['pid'])
                        # Check if process exists
                        os.kill(pid, 0)
                        services[service_name] = info
                    except (OSError, ValueError):
                        # Process is dead, clean up registry
                        logger.info(f"Cleaning up dead service {service_name} from registry")
                        await self.redis.delete(key_str)
                else:
                    services[service_name] = info

        except Exception as e:
            logger.error(f"Error scanning service registry: {e}")

        return services

    async def unregister_service(self, name: str):
        """Remove service from registry"""
        if not self.redis:
            await self.initialize()

        key = f"service:registry:{name}"
        await self.redis.delete(key)
        logger.info(f"Unregistered service {name} from registry")