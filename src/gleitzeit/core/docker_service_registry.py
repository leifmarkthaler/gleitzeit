"""Docker service registration module for container startup/shutdown"""
import os
import sys
import asyncio
import socket
import signal
from datetime import datetime
from typing import Optional

from .instance import initialize_instance
from .process_manager import SmartProcessManager
from .config_manager import ConfigurationManager


async def register_service(service_type: str, redis_url: Optional[str] = None) -> None:
    """Register Docker service in existing Redis service registry on startup"""
    # Use provided redis_url or get from ConfigurationManager
    if not redis_url:
        config_manager = ConfigurationManager(os.environ.get('GLEITZEIT_CONFIG', 'gleitzeit.yaml'), {})
        redis_url = config_manager.get_redis_url()

    hostname = socket.gethostname()

    # Initialize instance identity for Docker container
    # Use container hostname as instance name, service type as role
    instance_name = os.getenv('HOSTNAME', hostname)  # Docker sets HOSTNAME to container ID
    initialize_instance(
        instance_name=f"docker-{instance_name}",
        role=service_type,
        port_offset=0  # Docker containers handle their own port mapping
    )

    # Use existing SmartProcessManager - now instance is initialized
    manager = SmartProcessManager(redis_url=redis_url)

    # Get port from environment or config
    port = os.getenv('PORT')
    if not port and service_type in ['api', 'ui']:
        # Get port from ConfigurationManager for known services
        config_manager = ConfigurationManager(os.environ.get('GLEITZEIT_CONFIG', 'gleitzeit.yaml'), {})
        port = str(config_manager.get_port(service_type))

    # Register using existing service registry infrastructure
    await manager.register_service(service_type, {
        'host': hostname,
        'port': port,
        'container_id': os.getenv('HOSTNAME'),
        'started_at': datetime.now().isoformat(),
        'mode': 'docker',
        'pid': os.getpid()  # Container PID for compatibility
    })

    print(f"Registered {service_type} service in Redis registry")


async def unregister_service(service_type: str, redis_url: Optional[str] = None) -> None:
    """Deregister Docker service from existing Redis registry on shutdown"""
    # Use provided redis_url or get from ConfigurationManager
    if not redis_url:
        config_manager = ConfigurationManager(os.environ.get('GLEITZEIT_CONFIG', 'gleitzeit.yaml'), {})
        redis_url = config_manager.get_redis_url()

    hostname = socket.gethostname()

    # Initialize instance identity for Docker container (same as register)
    instance_name = os.getenv('HOSTNAME', hostname)
    initialize_instance(
        instance_name=f"docker-{instance_name}",
        role=service_type,
        port_offset=0
    )

    # Use existing SmartProcessManager
    manager = SmartProcessManager(redis_url=redis_url)
    await manager.unregister_service(service_type)

    print(f"Deregistered {service_type} service from Redis registry")


class DockerServiceMonitor:
    """Monitor Docker service for shutdown signals and handle cleanup"""

    def __init__(self, service_type: str, redis_url: Optional[str] = None):
        self.service_type = service_type
        self.redis_url = redis_url
        self.running = True

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, sig, frame):
        """Handle shutdown signals"""
        print(f"Received signal {sig}, shutting down {self.service_type} service...")
        asyncio.create_task(self._cleanup_and_exit())

    async def _cleanup_and_exit(self):
        """Cleanup service registration and exit"""
        try:
            await unregister_service(self.service_type, self.redis_url)
        except Exception as e:
            print(f"Error during cleanup: {e}")
        finally:
            self.running = False
            sys.exit(0)

    async def monitor(self):
        """Monitor service and handle signals"""
        self.setup_signal_handlers()
        print(f"Monitoring {self.service_type} service for shutdown signals...")

        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await self._cleanup_and_exit()


# CLI entry points for docker containers
async def main():
    """Main entry point for docker service registration"""
    if len(sys.argv) < 2:
        print("Usage: python -m gleitzeit.core.docker_service_registry <command> [service_type]")
        print("Commands: register, monitor, unregister")
        sys.exit(1)

    command = sys.argv[1]

    if command == 'register' and len(sys.argv) >= 3:
        service_type = sys.argv[2]
        await register_service(service_type)

    elif command == 'unregister' and len(sys.argv) >= 3:
        service_type = sys.argv[2]
        await unregister_service(service_type)

    elif command == 'monitor' and len(sys.argv) >= 3:
        service_type = sys.argv[2]
        monitor = DockerServiceMonitor(service_type)
        await monitor.monitor()

    else:
        print(f"Invalid command or missing service_type: {command}")
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())