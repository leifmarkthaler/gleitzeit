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
import json
from typing import Dict, Optional, List, Any
from pathlib import Path
import click
import yaml
import asyncio
import redis.asyncio as aioredis
from datetime import datetime

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
from ..core.config_manager import ConfigurationManager

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

        # Initialize ConfigurationManager with CLI args
        cli_args = {}
        if api_port is not None:
            cli_args['api_port'] = api_port
        if ui_port is not None:
            cli_args['ui_port'] = ui_port
        if api_host is not None:
            cli_args['api_host'] = api_host
        if ui_host is not None:
            cli_args['ui_host'] = ui_host
        if no_ui is not None:
            cli_args['no_ui'] = no_ui
        if no_orchestrator is not None:
            cli_args['no_orchestrator'] = no_orchestrator
        if dev_mode is not None:
            cli_args['dev_mode'] = dev_mode

        self.config_manager = ConfigurationManager(self.config_file, cli_args)
        self.config = self._load_config()  # Keep for compatibility

        # Store command line overrides for compatibility
        self.api_port_override = api_port
        self.ui_port_override = ui_port

        # Use ConfigurationManager for all config values
        self.api_host = self.config_manager.get_host('api')
        self.ui_host = self.config_manager.get_host('ui')
        self.dev_mode = self.config_manager.get_value('dev_mode') or False

        # Ports will be allocated properly in _allocate_ports()
        self.api_port = None
        self.ui_port = None

        # Service state from ConfigurationManager
        # API is always enabled (no CLI flag to disable it)
        self.no_api = False
        self.no_ui = not self.config_manager.is_enabled('ui')
        self.no_orchestrator = not self.config_manager.is_enabled('orchestrator')
        self.restart = restart

        # Process management with Smart Process Manager
        self.process_manager = SmartProcessManager()
        self.port_manager = PortManager()
        self.running = False

        # Create event loop for async operations
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # Track allocated ports
        self.allocated_ports = {}

        # Keep legacy process tracking for compatibility
        self.processes: Dict[str, subprocess.Popen] = {}
        self.restart_attempts: Dict[str, int] = {}
        self.max_restart_attempts = 3
        self.process_start_time: Dict[str, float] = {}
        self.stable_uptime_seconds = 30

        # Setup Python path
        src_path = Path(__file__).parent.parent.parent.absolute()
        self.env = os.environ.copy()
        self.env['PYTHONPATH'] = f"{src_path}:{self.env.get('PYTHONPATH', '')}"

        # Add auth and security environment variables from config
        self._setup_environment_from_config()

        # Add instance identity to environment
        self.env['GLEITZEIT_INSTANCE_ID'] = self.instance.instance_id
        self.env['GLEITZEIT_INSTANCE_NAME'] = self.instance.instance_name
        self.env['GLEITZEIT_INSTANCE_ROLE'] = self.instance.role
        self.env['GLEITZEIT_DEPLOYMENT_ID'] = self.instance.deployment_id
        self.env['GLEITZEIT_REDIS_NAMESPACE'] = self.instance.get_redis_namespace()

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
            "orchestrator": self._check_orchestrator_running(),
            "zombie_serve": self._check_zombie_serve_processes()
        }
        return existing

    def _check_zombie_serve_processes(self) -> bool:
        """Check for zombie serve processes that failed to start properly"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                cmdline = proc.info.get('cmdline', [])
                if cmdline and 'gleitzeit.cli.serve' in ' '.join(cmdline):
                    # Check if this is a different serve process (not ourselves)
                    if proc.pid != os.getpid():
                        return True
        except:
            pass
        return False

    def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is in use"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return False
            except socket.error:
                return True

    def _find_process_on_port(self, port: int) -> Optional[Dict]:
        """Find what process is using a specific port"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    for conn in proc.connections(kind='inet'):
                        if conn.laddr.port == port and conn.status == 'LISTEN':
                            cmdline = proc.info.get('cmdline', [])
                            # Check if it's a Gleitzeit process
                            is_gleitzeit = any('gleitzeit' in str(cmd).lower() for cmd in cmdline)
                            return {
                                'pid': proc.pid,
                                'name': proc.info['name'],
                                'cmdline': ' '.join(cmdline) if cmdline else proc.info['name'],
                                'is_gleitzeit': is_gleitzeit
                            }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.debug(f"Error finding process on port {port}: {e}")
        return None

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

        # First, kill any zombie serve processes
        self._kill_zombie_serve_processes()

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

    def _cleanup_zombie_serve_processes(self):
        """Kill zombie serve processes automatically"""
        current_pid = os.getpid()
        killed_pids = []

        try:
            for proc in psutil.process_iter(['pid', 'cmdline', 'create_time']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    if not cmdline:
                        continue

                    # Identify serve processes (multiple patterns)
                    is_serve = False
                    cmdline_str = ' '.join(str(c) for c in cmdline)

                    if any(pattern in cmdline_str for pattern in [
                        'gleitzeit.cli.serve',
                        'gleitzeit.cli.main serve',
                        'python -m gleitzeit.cli.serve'
                    ]):
                        is_serve = True

                    if not is_serve or proc.pid == current_pid:
                        continue

                    # Check if process is stuck (older than 30 seconds and not binding ports)
                    create_time = proc.info.get('create_time', 0)
                    age = time.time() - create_time

                    if age > 30:  # Process older than 30 seconds
                        # Check if it has any listening ports
                        has_ports = False
                        try:
                            for conn in proc.connections():
                                if conn.status == 'LISTEN':
                                    has_ports = True
                                    break
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                        if not has_ports:
                            # It's a zombie - kill it
                            logger.warning(f"Killing zombie serve process {proc.pid} (age: {age:.0f}s)")
                            proc.terminate()
                            killed_pids.append(proc.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.debug(f"Process access error: {e}")
                    continue

            # Wait for termination and force kill if needed
            for pid in killed_pids:
                try:
                    p = psutil.Process(pid)
                    p.wait(timeout=2)
                except psutil.TimeoutExpired:
                    try:
                        p.kill()  # Force kill if needed
                        logger.info(f"Force killed zombie process {pid}")
                    except:
                        pass
                except psutil.NoSuchProcess:
                    pass  # Already gone

            if killed_pids:
                logger.info(f"Cleaned up {len(killed_pids)} zombie serve processes")
                time.sleep(1)  # Give OS time to release resources

        except Exception as e:
            logger.error(f"Error during zombie cleanup: {e}")

    def _kill_zombie_serve_processes(self):
        """Legacy method - now calls cleanup method"""
        self._cleanup_zombie_serve_processes()

    def _allocate_ports(self):
        """Properly allocate ports using PortManager"""
        async def allocate():
            # Ensure PortManager has Redis connection
            await self.port_manager._ensure_redis()

            # Allocate API port using ConfigurationManager for precedence
            requested_port = self.config_manager.get_port('api')
            try:
                allocated = await self.port_manager._allocate_port('api', requested_port)
                if self.api_port_override and allocated != requested_port:
                    # If user specified a port and we couldn't get it, fail
                    raise RuntimeError(f"Port {requested_port} not available (allocated {allocated} instead)")
                self.api_port = allocated
                logger.info(f"Allocated API port {self.api_port} (requested: {requested_port})")
            except Exception as e:
                logger.error(f"Failed to allocate API port {requested_port}: {e}")
                raise RuntimeError(f"Cannot allocate API port {requested_port}: {e}")

            # Allocate UI port if enabled
            if not self.no_ui:
                requested_port = self.config_manager.get_port('ui')
                try:
                    allocated = await self.port_manager._allocate_port('ui', requested_port)
                    if self.ui_port_override and allocated != requested_port:
                        # If user specified a port and we couldn't get it, fail
                        raise RuntimeError(f"Port {requested_port} not available (allocated {allocated} instead)")
                    self.ui_port = allocated
                    logger.info(f"Allocated UI port {self.ui_port} (requested: {requested_port})")
                except Exception as e:
                    logger.error(f"Failed to allocate UI port {requested_port}: {e}")
                    raise RuntimeError(f"Cannot allocate UI port {requested_port}: {e}")

            self.allocated_ports = {
                'api': self.api_port,
                'ui': self.ui_port if not self.no_ui else None
            }

            return self.api_port, self.ui_port

        # Execute async allocation
        try:
            api_port, ui_port = self.loop.run_until_complete(allocate())
            logger.info(f"Port allocation complete - API: {api_port}, UI: {ui_port if not self.no_ui else 'disabled'}")
        except Exception as e:
            logger.error(f"Port allocation failed: {e}")
            raise

    def start(self):
        """Start all components"""
        # ALWAYS clean up zombie serve processes first
        self._cleanup_zombie_serve_processes()

        # Allocate ports using PortManager
        try:
            self._allocate_ports()
        except Exception as e:
            logger.error(f"Failed to allocate ports: {e}")
            sys.exit(1)

        # Check for existing processes on allocated ports
        existing = self.check_existing_processes()

        # Always kill zombie serve processes - they're failed attempts
        if existing.get("zombie_serve"):
            print("\n⚠️  Cleaning up failed serve attempts...")
            self._kill_zombie_serve_processes()
            # Re-check after cleanup
            existing = self.check_existing_processes()

        if any([existing.get(k) for k in ["orchestrator", "api", "ui"]]):
            if self.restart:
                print("\n⚠️  Existing Gleitzeit processes detected")
                self.kill_existing_processes()
                time.sleep(2)  # Give processes time to fully terminate
            else:
                print("\n⚠️  Existing Gleitzeit processes detected:")
                if existing["orchestrator"]:
                    print("   • Orchestrator is already running")
                if existing["api"]:
                    proc_info = self._find_process_on_port(self.api_port)
                    if proc_info and proc_info['is_gleitzeit']:
                        print(f"   • API port {self.api_port} is in use by Gleitzeit API (PID: {proc_info['pid']})")
                    else:
                        proc_desc = f" by {proc_info['name']}" if proc_info else ""
                        print(f"   • API port {self.api_port} is already in use{proc_desc}")
                if existing["ui"]:
                    proc_info = self._find_process_on_port(self.ui_port)
                    if proc_info and proc_info['is_gleitzeit']:
                        print(f"   • UI port {self.ui_port} is in use by Gleitzeit UI (PID: {proc_info['pid']})")
                    else:
                        proc_desc = f" by {proc_info['name']}" if proc_info else ""
                        print(f"   • UI port {self.ui_port} is already in use{proc_desc}")
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
            metrics_last_collected = 0
            metrics_interval = 30  # Collect metrics every 30 seconds

            while self.running:
                current_time = time.time()

                # Collect and log metrics periodically
                if current_time - metrics_last_collected >= metrics_interval:
                    metrics = self.collect_metrics()
                    if metrics:
                        logger.info(f"Process metrics: {json.dumps(metrics, indent=2)}")
                    metrics_last_collected = current_time

                # Reset restart counters for processes that have been stable
                for name in list(self.process_start_time.keys()):
                    if name in self.processes and self.processes[name].poll() is None:
                        # Process is still running
                        uptime = current_time - self.process_start_time[name]
                        if uptime >= self.stable_uptime_seconds and self.restart_attempts.get(name, 0) > 0:
                            logger.info(f"{name} has been stable for {uptime:.0f}s, resetting restart counter")
                            self.restart_attempts[name] = 0

                # Check process health using improved health checks
                for name in list(self.processes.keys()):
                    proc = self.processes.get(name)
                    if not proc:
                        continue

                    # First check if process is alive
                    if proc.poll() is not None:
                        logger.warning(f"{name} process died (exit code: {proc.returncode})")
                        del self.processes[name]
                        needs_restart = True
                    else:
                        # Process is alive, check if it's healthy
                        is_healthy = self.check_process_health(name)
                        if not is_healthy:
                            logger.warning(f"{name} process is unhealthy, will restart")
                            # Kill the unhealthy process
                            try:
                                proc.terminate()
                                proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait()
                            del self.processes[name]
                            needs_restart = True
                        else:
                            needs_restart = False

                    if needs_restart:
                        # Check restart limit
                        restart_count = self.restart_attempts.get(name, 0)
                        if restart_count >= self.max_restart_attempts:
                            error = ServiceRegistrationError(
                                service_id=name,
                                operation="restart",
                                data={
                                    "reason": f"Maximum restart attempts ({self.max_restart_attempts}) exceeded",
                                    "exit_code": proc.returncode if proc else None
                                }
                            )
                            logger.error(error.to_json_string())
                            continue  # Skip restart attempt

                        # Use exponential backoff for restart delay
                        wait_time = self.get_restart_wait_time(name)
                        logger.info(f"Waiting {wait_time}s before restarting {name} (exponential backoff)")
                        time.sleep(wait_time)

                        try:
                            self.restart_attempts[name] = restart_count + 1
                            logger.info(f"Attempting to restart {name} (attempt {self.restart_attempts[name]}/{self.max_restart_attempts})")

                            if name == "orchestrator" and not self.no_orchestrator:
                                self.start_orchestrator()
                            elif name == "api":
                                self.start_api(kill_existing=False)
                            elif name == "ui" and not self.no_ui:
                                self.start_ui(kill_existing=False)

                            # Don't reset counter immediately - wait to see if process stays alive
                            # Counter will be reset after the process runs successfully for a while

                        except Exception as e:
                            # Use Gleitzeit's error system for proper error handling
                            error = ServiceRegistrationError(
                                service_id=name,
                                operation="restart",
                                cause=e,
                                data={
                                    "attempt": self.restart_attempts[name],
                                    "max_attempts": self.max_restart_attempts
                                }
                            )
                            logger.error(error.to_json_string())
                            # Don't try again immediately to avoid rapid loops
                            time.sleep(10)

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
            self.process_start_time["orchestrator"] = time.time()

            print("✓ Orchestrator started")

        except Exception as e:
            logger.error(f"Failed to start orchestrator: {e}")
            raise

    async def _register_service(self, service_name: str, port: int, pid: int):
        """Register service in Redis for discovery"""
        try:
            redis = await aioredis.from_url(self.env.get('REDIS_URL', 'redis://localhost:6379'))

            # Service registration key
            service_key = f"service:{self.instance.machine_id}:{self.instance.instance_id}:{service_name}"

            service_info = {
                'name': service_name,
                'instance_id': self.instance.instance_id,
                'machine_id': self.instance.machine_id,
                'host': self.api_host if service_name == 'api' else self.ui_host,
                'port': port,
                'pid': pid,
                'status': 'running',
                'started_at': datetime.utcnow().isoformat(),
                'metadata': {
                    'datacenter': getattr(self.instance.metadata, 'datacenter', 'default'),
                    'rack': getattr(self.instance.metadata, 'rack', 'default'),
                    'network_zone': getattr(self.instance.metadata, 'network_zone', 'default')
                }
            }

            # Store service info with TTL
            import json
            await redis.setex(
                service_key,
                300,  # 5 minute TTL
                json.dumps(service_info)
            )

            # Add to service index
            await redis.sadd(f"services:{service_name}", service_key)
            await redis.sadd(f"machine:{self.instance.machine_id}:services", service_key)

            logger.info(f"Registered {service_name} service on port {port}")
            await redis.close()

        except Exception as e:
            logger.error(f"Failed to register service {service_name}: {e}")

    async def _deregister_service(self, service_name: str):
        """Deregister service from Redis"""
        try:
            redis = await aioredis.from_url(self.env.get('REDIS_URL', 'redis://localhost:6379'))

            service_key = f"service:{self.instance.machine_id}:{self.instance.instance_id}:{service_name}"

            # Remove service info
            await redis.delete(service_key)

            # Remove from indexes
            await redis.srem(f"services:{service_name}", service_key)
            await redis.srem(f"machine:{self.instance.machine_id}:services", service_key)

            logger.info(f"Deregistered {service_name} service")
            await redis.close()

        except Exception as e:
            logger.error(f"Failed to deregister service {service_name}: {e}")

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

            # Wait a moment and check if process is still alive
            time.sleep(0.5)
            if proc.poll() is not None:
                # Process died immediately
                stderr_output = proc.stderr.read() if proc.stderr else ""
                raise ServiceRegistrationError(
                    service_id="api",
                    operation="start",
                    data={
                        "exit_code": proc.returncode,
                        "stderr": stderr_output,
                        "port": self.api_port
                    }
                )

            self.processes["api"] = proc
            self.process_start_time["api"] = time.time()

            # Register service in discovery
            self.loop.run_until_complete(
                self._register_service('api', self.api_port, proc.pid)
            )

            print(f"✓ API Server started on http://{self.api_host}:{self.api_port}")

        except Exception as e:
            logger.error(f"Failed to start API: {e}")
            raise

    def start_ui(self, kill_existing=True):
        """Start the UI server"""
        print(f"Starting UI Server on port {self.ui_port}...")

        # Only kill existing processes if explicitly requested
        # IMPORTANT: When kill_existing=False, we assume the port is free or we want to fail
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

        # Set API URL for UI - use the actual API port that's running
        # This ensures UI connects to the right port even if there was an override
        self.env["GLEITZEIT_API_URL"] = f"http://localhost:{self.api_port}"
        self.env["GLEITZEIT_UI_PORT"] = str(self.ui_port)
        self.env["GLEITZEIT_UI_HOST"] = self.ui_host

        # Also pass the config file path so UI can read the same config
        self.env["GLEITZEIT_CONFIG_FILE"] = self.config_file

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

            # Wait a moment and check if process is still alive
            time.sleep(0.5)
            if proc.poll() is not None:
                # Process died immediately
                stderr_output = proc.stderr.read() if proc.stderr else ""
                raise ServiceRegistrationError(
                    service_id="ui",
                    operation="start",
                    data={
                        "exit_code": proc.returncode,
                        "stderr": stderr_output,
                        "port": self.ui_port
                    }
                )

            self.processes["ui"] = proc
            self.process_start_time["ui"] = time.time()

            # Register service in discovery
            self.loop.run_until_complete(
                self._register_service('ui', self.ui_port, proc.pid)
            )

            print(f"✓ UI Server started on http://{self.ui_host}:{self.ui_port}")

        except Exception as e:
            logger.error(f"Failed to start UI: {e}")
            raise

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
        for name, proc in self.processes.items():
            status = "✓ Running" if proc.poll() is None else "✗ Stopped"
            print(f"   {name.capitalize()}: {status}")
        print("\nPress Ctrl+C to stop all services")
        print("=" * 60 + "\n")

    def check_process_health(self, name: str) -> bool:
        """
        Simple health check for a process

        Args:
            name: Name of the process to check

        Returns:
            True if process is healthy, False otherwise
        """
        proc = self.processes.get(name)
        if not proc:
            return False

        # Check if process is alive
        if proc.poll() is not None:
            return False

        # Check if port is responsive for services
        if name == "api":
            return self._check_port_responsive(self.api_port, "/health")
        elif name == "ui":
            return self._check_port_responsive(self.ui_port, "/")
        elif name == "orchestrator":
            # Orchestrator doesn't have a port, just check process
            return True

        return True

    def _check_port_responsive(self, port: int, path: str = "/") -> bool:
        """Check if a port is responsive via HTTP"""
        import socket
        import http.client

        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=2)
            conn.request("GET", path)
            response = conn.getresponse()
            conn.close()
            return response.status < 500  # Any non-5xx is considered healthy
        except:
            return False

    def get_restart_wait_time(self, service: str) -> float:
        """
        Calculate exponential backoff wait time for restart

        Args:
            service: Name of the service

        Returns:
            Wait time in seconds
        """
        restart_count = self.restart_attempts.get(service, 0)
        # Exponential backoff: 2^n seconds, max 60 seconds
        wait_time = min(2 ** restart_count, 60)
        return wait_time

    def collect_metrics(self) -> Dict[str, Any]:
        """
        Collect basic metrics about running processes

        Returns:
            Dictionary of metrics for each process
        """
        metrics = {}
        current_time = time.time()

        for name, proc in self.processes.items():
            if proc and proc.poll() is None:
                uptime = current_time - self.process_start_time.get(name, current_time)

                # Get process memory info if available
                try:
                    process = psutil.Process(proc.pid)
                    memory_mb = process.memory_info().rss / 1024 / 1024
                    cpu_percent = process.cpu_percent(interval=0.1)
                except:
                    memory_mb = None
                    cpu_percent = None

                metrics[name] = {
                    'status': 'running',
                    'healthy': self.check_process_health(name),
                    'pid': proc.pid,
                    'uptime_seconds': round(uptime, 1),
                    'restarts': self.restart_attempts.get(name, 0),
                    'memory_mb': round(memory_mb, 1) if memory_mb else None,
                    'cpu_percent': round(cpu_percent, 1) if cpu_percent else None
                }
            else:
                metrics[name] = {
                    'status': 'stopped',
                    'healthy': False,
                    'restarts': self.restart_attempts.get(name, 0)
                }

        return metrics

    def _handle_signal(self, signum, frame):
        """Handle shutdown signals"""
        print("\n\nShutting down Gleitzeit...")
        self.running = False

        # Release allocated ports
        self._release_ports()

        self.stop()
        sys.exit(0)

    def _release_ports(self):
        """Release allocated ports in Redis"""
        async def release():
            try:
                await self.port_manager._ensure_redis()
                for service in ['api', 'ui']:
                    if service in self.allocated_ports and self.allocated_ports[service]:
                        await self.port_manager.release_port(service)
                        logger.info(f"Released port for {service}")

                        # Also deregister from discovery
                        await self._deregister_service(service)
            except Exception as e:
                logger.error(f"Error releasing ports: {e}")

        if self.allocated_ports:
            self.loop.run_until_complete(release())

    def stop(self):
        """Stop all components"""
        # Deregister services first
        async def deregister_all():
            for name in self.processes.keys():
                await self._deregister_service(name)

        if self.processes:
            self.loop.run_until_complete(deregister_all())

        # Then stop processes
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
@click.option('--instance-name', help='Name for this instance (used for identification and namespacing)')
@click.option('--instance-role', default='standalone', help='Instance role: standalone, worker, coordinator, gateway')
@click.option('--port-offset', type=int, default=0, help='Port offset for all services (useful for multiple instances)')
def serve(config, api_port, ui_port, api_host, ui_host, dev, no_ui, no_orchestrator, restart, instance_name, instance_role, port_offset):
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