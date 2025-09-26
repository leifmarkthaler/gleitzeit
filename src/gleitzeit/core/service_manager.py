"""
Service Manager for Gleitzeit

Handles service-specific process management (API, UI servers)
with clean separation from core process management concerns.
"""

import sys
import logging
from typing import Dict, Optional, Any
from .process_manager import SmartProcessManager
from .ports import PortManager

logger = logging.getLogger(__name__)


class ServiceManager:
    """Manages Gleitzeit services (API, UI) with proper lifecycle handling"""

    def __init__(self, process_manager: SmartProcessManager, port_manager: PortManager):
        """
        Initialize Service Manager

        Args:
            process_manager: Core process manager for lifecycle handling
            port_manager: Port manager for conflict resolution
        """
        self.process_manager = process_manager
        self.port_manager = port_manager

        # Service configurations
        self.service_configs = {
            'api': {
                'module': 'uvicorn',
                'app': 'gleitzeit.api.main:app',
                'supports_reload': True,
                'health_check_path': '/health'
            },
            'ui': {
                'module': 'uvicorn',
                'app': 'gleitzeit.ui.api.app:app',
                'supports_reload': True,
                'health_check_path': '/health'
            }
        }

    async def start_api(
        self,
        host: str = "0.0.0.0",
        port: Optional[int] = None,
        dev_mode: bool = False,
        env: Optional[Dict[str, str]] = None,
        kill_existing: bool = False
    ) -> bool:
        """Start the API server"""
        service_port = port if port is not None else await self.port_manager.get_service_port('api')

        cmd = self._build_service_command(
            service_name='api',
            host=host,
            port=service_port,
            dev_mode=dev_mode
        )

        # Update command with the correct port
        for i, arg in enumerate(cmd):
            if arg == "--port" and i + 1 < len(cmd):
                cmd[i + 1] = str(service_port)
                break

        process_info = await self.process_manager.start_service(
            service_name="api",
            command=cmd,
            port=service_port,
            env=env,
            kill_existing=kill_existing
        )

        if process_info:
            logger.info(f"✓ API Server started on http://{host}:{service_port} (PID: {process_info.pid})")
            return True
        else:
            logger.error("Failed to start API server")
            return False

    async def start_ui(
        self,
        host: str = "0.0.0.0",
        port: Optional[int] = None,
        dev_mode: bool = False,
        env: Optional[Dict[str, str]] = None,
        kill_existing: bool = False
    ) -> bool:
        """Start the UI server"""
        service_port = port if port is not None else await self.port_manager.get_service_port('ui')

        cmd = self._build_service_command(
            service_name='ui',
            host=host,
            port=service_port,
            dev_mode=dev_mode
        )

        # Update command with the correct port
        for i, arg in enumerate(cmd):
            if arg == "--port" and i + 1 < len(cmd):
                cmd[i + 1] = str(service_port)
                break

        process_info = await self.process_manager.start_service(
            service_name="ui",
            command=cmd,
            port=service_port,
            env=env,
            kill_existing=kill_existing
        )

        if process_info:
            logger.info(f"✓ UI Server started on http://{host}:{service_port} (PID: {process_info.pid})")
            return True
        else:
            logger.error("Failed to start UI server")
            return False

    async def start_all_services(
        self,
        api_config: Dict[str, Any],
        ui_config: Dict[str, Any],
        kill_existing: bool = False
    ) -> bool:
        """Start all configured services"""
        results = []

        # Start API
        if api_config.get('enabled', True):
            api_result = await self.start_api(
                host=api_config.get('host', '0.0.0.0'),
                port=api_config.get('port'),
                dev_mode=api_config.get('dev_mode', False),
                env=api_config.get('env'),
                kill_existing=kill_existing
            )
            results.append(api_result)

        # Start UI
        if ui_config.get('enabled', True):
            ui_result = await self.start_ui(
                host=ui_config.get('host', '0.0.0.0'),
                port=ui_config.get('port'),
                dev_mode=ui_config.get('dev_mode', False),
                env=ui_config.get('env'),
                kill_existing=kill_existing
            )
            results.append(ui_result)

        return all(results)

    async def stop_service(self, service_name: str) -> None:
        """Stop a specific service"""
        await self.process_manager.stop_service(service_name)
        logger.info(f"Service {service_name} stopped")

    async def stop_all_services(self) -> None:
        """Stop all services"""
        services = ['api', 'ui']
        for service_name in services:
            try:
                await self.stop_service(service_name)
            except Exception as e:
                logger.error(f"Error stopping {service_name}: {e}")

    def _build_service_command(
        self,
        service_name: str,
        host: str,
        port: int,
        dev_mode: bool = False
    ) -> list[str]:
        """Build command for starting a service"""
        config = self.service_configs.get(service_name)
        if not config:
            raise ValueError(f"Unknown service: {service_name}")

        cmd = [
            sys.executable, "-m", config['module'],
            config['app'],
            "--host", host,
            "--port", str(port)
        ]

        # Add dev mode reload if supported and enabled
        if dev_mode and config.get('supports_reload', False):
            cmd.append("--reload")

        return cmd

    def get_service_status(self) -> Dict[str, Any]:
        """Get status of all services"""
        return self.process_manager.get_service_status()

    async def health_check(self, service_name: str) -> bool:
        """Perform health check on a service"""
        # For now, just check if the process is running
        # In the future, this could make HTTP requests to health endpoints
        status = self.get_service_status()
        service_info = status.get('services', {}).get(service_name)

        if not service_info:
            return False

        return service_info.get('status') == 'running'