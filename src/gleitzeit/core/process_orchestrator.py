"""
Process Orchestrator for Gleitzeit

Top-level orchestration layer that coordinates ServiceManager and WorkerManager
with proper startup sequencing and unified lifecycle management.
"""

import asyncio
import signal
import logging
import os
from typing import Dict, Optional, Any
from pathlib import Path

from .process_manager import SmartProcessManager
from .service_manager import ServiceManager
from .worker_manager import WorkerManager
from .ports import PortManager
from .instance import get_current_instance

logger = logging.getLogger(__name__)


class ProcessOrchestrator:
    """Orchestrates all Gleitzeit processes with layered management"""

    def __init__(self, config: Dict[str, Any], redis_url: Optional[str] = None):
        """
        Initialize Process Orchestrator

        Args:
            config: Full configuration dictionary
            redis_url: Redis connection URL (will be determined from config if not provided)
        """
        self.config = config
        self.instance = get_current_instance()
        if not self.instance:
            raise RuntimeError("Instance identity not initialized")

        # Determine Redis URL
        self.redis_url = self._get_redis_url(redis_url)

        # Initialize core managers
        self.process_manager = SmartProcessManager(redis_url=self.redis_url)
        self.port_manager = PortManager()  # Will share Redis connection in initialize()

        # Initialize domain managers
        self.service_manager = ServiceManager(self.process_manager, self.port_manager)
        self.worker_manager = WorkerManager(self.process_manager, config)

        # State
        self.running = False
        self.monitor_task: Optional[asyncio.Task] = None

    def _get_redis_url(self, redis_url: Optional[str]) -> str:
        """Determine Redis URL from config or parameter"""
        if redis_url:
            return redis_url

        redis_config = self.config.get('redis', {})
        if redis_config.get('mode') == 'single':
            single_node = redis_config.get('single_node', {})
            host = single_node.get('host', 'localhost')
            port = single_node.get('port', 6379)
            db = single_node.get('db', 0)
            return f"redis://{host}:{port}/{db}"
        else:
            # For cluster mode, use first node
            cluster_nodes = redis_config.get('cluster_nodes', [])
            if cluster_nodes:
                node = cluster_nodes[0]
                return f"redis://{node['host']}:{node['port']}"
            else:
                return "redis://localhost:6379"

    async def initialize(self) -> None:
        """Initialize all managers"""
        logger.info("Initializing ProcessOrchestrator")

        # Initialize core process manager
        await self.process_manager.initialize()

        # Share Redis connection with PortManager
        self.port_manager.redis = self.process_manager.redis

        logger.info(f"ProcessOrchestrator initialized for instance {self.instance.instance_id}")

    async def start_all(self, restart: bool = False) -> bool:
        """Start all services and workers with proper sequencing"""
        logger.info("=" * 60)
        logger.info("🚀 Starting Gleitzeit 0.0.7 (Layered Process Management)")
        logger.info("=" * 60)

        try:
            # Initialize managers
            await self.initialize()

            # Check for port conflicts
            conflicts = await self.port_manager.check_port_conflicts()
            if conflicts:
                logger.warning("⚠️  Port conflicts detected:")
                for conflict, owner in conflicts.items():
                    logger.warning(f"   • {conflict} used by {owner}")

                if not restart:
                    logger.error("Use --restart flag to override")
                    return False

            # Start services first (they're required by workers)
            logger.info("Starting services...")
            services_started = await self._start_services(restart)
            if not services_started:
                logger.error("Failed to start services")
                return False

            # Small delay to ensure services are ready
            await asyncio.sleep(2)

            # Start workers
            logger.info("Starting workers...")
            workers_started = await self._start_workers(restart)
            if not workers_started:
                logger.warning("Some workers failed to start, but continuing...")

            # Mark as running
            self.running = True

            # Print status
            self._print_status()

            # Start monitoring
            self.monitor_task = asyncio.create_task(self._monitor_loop())

            return True

        except Exception as e:
            logger.error(f"Failed to start ProcessOrchestrator: {e}")
            await self.stop_all()
            return False

    async def _start_services(self, restart: bool) -> bool:
        """Start all services"""
        serve_config = self.config.get('serve', {})

        # Build service configs
        api_config = {
            'enabled': serve_config.get('api', {}).get('enabled', True),
            'host': serve_config.get('api', {}).get('host', '0.0.0.0'),
            'port': serve_config.get('api', {}).get('port'),
            'dev_mode': serve_config.get('dev_mode', False),
            'env': await self._get_service_env()
        }

        ui_config = {
            'enabled': serve_config.get('ui', {}).get('enabled', True),
            'host': serve_config.get('ui', {}).get('host', '0.0.0.0'),
            'port': serve_config.get('ui', {}).get('port'),
            'dev_mode': serve_config.get('dev_mode', False),
            'env': await self._get_service_env()
        }

        return await self.service_manager.start_all_services(
            api_config=api_config,
            ui_config=ui_config,
            kill_existing=restart
        )

    async def _start_workers(self, restart: bool) -> bool:
        """Start all workers"""
        return await self.worker_manager.start_all_workers(kill_existing=restart)

    async def _get_service_env(self) -> Dict[str, str]:
        """Get environment variables for services"""
        env = {}

        # Instance identity
        env['GLEITZEIT_INSTANCE_ID'] = self.instance.instance_id
        env['GLEITZEIT_INSTANCE_NAME'] = self.instance.instance_name
        env['GLEITZEIT_INSTANCE_ROLE'] = self.instance.role
        env['GLEITZEIT_DEPLOYMENT_ID'] = self.instance.deployment_id
        env['GLEITZEIT_REDIS_NAMESPACE'] = self.instance.get_redis_namespace()

        # Redis configuration
        env['REDIS_URL'] = self.redis_url

        # Authentication
        auth_config = self.config.get('auth', {})
        if 'auto_login' in auth_config:
            env['GLEITZEIT_AUTO_LOGIN'] = str(auth_config['auto_login']).lower()

        # JWT configuration
        jwt_config = auth_config.get('jwt', {})
        if 'secret' in jwt_config:
            jwt_secret = str(jwt_config['secret'])
            # Handle environment variable substitution
            if jwt_secret.startswith('${') and jwt_secret.endswith('}'):
                var_content = jwt_secret[2:-1]
                if ':-' in var_content:
                    var_name, default = var_content.split(':-', 1)
                    jwt_secret = os.environ.get(var_name, default)
            env['JWT_SECRET'] = jwt_secret

        # CORS origins
        cors_origins = await self._compute_cors_origins()
        env['CORS_ORIGINS'] = ','.join(cors_origins)

        # API URL for UI
        # Use default port calculation for now until we have ports allocated
        api_port = 8000 + self.instance.port_offset
        env['GLEITZEIT_API_URL'] = f"http://localhost:{api_port}"

        return env

    async def _compute_cors_origins(self) -> list[str]:
        """Compute CORS origins from service configuration"""
        origins = []

        # Get service ports
        api_port = await self.port_manager.get_service_port('api')
        ui_port = await self.port_manager.get_service_port('ui')

        # Add API origins
        origins.append(f"http://localhost:{api_port}")
        origins.append(f"http://127.0.0.1:{api_port}")

        # Add UI origins if enabled
        serve_config = self.config.get('serve', {})
        if serve_config.get('ui', {}).get('enabled', True):
            origins.append(f"http://localhost:{ui_port}")
            origins.append(f"http://127.0.0.1:{ui_port}")

        return list(set(origins))

    def _print_status(self) -> None:
        """Print status summary"""
        print("\\n" + "=" * 60)
        print("✨ Gleitzeit is running!")
        print("=" * 60)
        print(f"\\n📦 Instance: {self.instance.instance_name} ({self.instance.instance_id[:8]})")
        print(f"   Role: {self.instance.role}")
        if self.instance.port_offset > 0:
            print(f"   Port Offset: +{self.instance.port_offset}")

        print("\\n📍 Service URLs:")
        service_status = self.service_manager.get_service_status()
        services = service_status.get('services', {})

        if 'api' in services:
            api_port = services['api'].get('port')
            print(f"   API Server:  http://localhost:{api_port}")
            print(f"   API Docs:    http://localhost:{api_port}/docs")

        if 'ui' in services:
            ui_port = services['ui'].get('port')
            print(f"   Web UI:      http://localhost:{ui_port}")

        print("\\n📊 Components:")
        for name, info in services.items():
            status_text = "✓ Running" if info.get("status") == "running" else "✗ " + info.get("status", "unknown").capitalize()
            print(f"   {name.capitalize()}: {status_text} (PID: {info.get('pid')})")

        # Worker status
        worker_status = self.worker_manager.get_worker_status()
        if worker_status['total_workers'] > 0:
            print(f"\\n👷 Workers: {worker_status['total_workers']} active")
            for worker_type, worker_list in worker_status['workers_by_type'].items():
                print(f"   {worker_type.capitalize()}: {len(worker_list)} workers")

        print("\\nPress Ctrl+C to stop all services")
        print("=" * 60 + "\\n")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop"""
        while self.running:
            try:
                # Monitor services and workers
                await self.process_manager.monitor_services()

                # Wait before next check
                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(5)

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal"""
        # Setup signal handlers
        stop_event = asyncio.Event()

        def signal_handler():
            logger.info("Shutdown signal received")
            stop_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler)

        # Wait for signal
        await stop_event.wait()

    async def stop_all(self) -> None:
        """Stop all processes"""
        logger.info("\\n\\nShutting down Gleitzeit...")
        self.running = False

        # Cancel monitoring
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        # Stop workers first (they depend on services)
        try:
            await self.worker_manager.stop_all_workers()
        except Exception as e:
            logger.error(f"Error stopping workers: {e}")

        # Stop services
        try:
            await self.service_manager.stop_all_services()
        except Exception as e:
            logger.error(f"Error stopping services: {e}")

        # Close process manager
        try:
            await self.process_manager.stop_all_services()
            await self.process_manager.close()
        except Exception as e:
            logger.error(f"Error closing process manager: {e}")

        # Clean up port manager
        try:
            await self.port_manager.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up port manager: {e}")

        logger.info("All services stopped")

    def get_full_status(self) -> Dict[str, Any]:
        """Get comprehensive status of all processes"""
        return {
            'instance': {
                'id': self.instance.instance_id,
                'name': self.instance.instance_name,
                'role': self.instance.role,
                'port_offset': self.instance.port_offset
            },
            'services': self.service_manager.get_service_status(),
            'workers': self.worker_manager.get_worker_status(),
            'running': self.running
        }