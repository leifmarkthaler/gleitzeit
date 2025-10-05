"""
Unified serve command for Gleitzeit that prefers Docker when available

Automatically detects and uses Docker if available, otherwise falls back
to native AsyncProcessManager (async subprocess implementation that fixes deadlock).
"""

import asyncio
import subprocess
import sys
import os
import logging
from pathlib import Path
from typing import Optional
import click
import yaml

logger = logging.getLogger(__name__)


def check_docker_available() -> bool:
    """Check if Docker is installed and running"""
    try:
        # Check if Docker is installed
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode != 0:
            return False

        # Check if Docker daemon is running
        result = subprocess.run(
            ["docker", "ps"],
            capture_output=True,
            text=True,
            timeout=2
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_docker_compose_available() -> bool:
    """Check if docker-compose is available"""
    try:
        result = subprocess.run(
            ["docker-compose", "--version"],
            capture_output=True,
            text=True,
            timeout=2
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@click.command()
@click.option('--config-file', '-c', default='gleitzeit.yaml', help='Config file path')
@click.option('--api-host', default=None, help='API host (default: 0.0.0.0)')
@click.option('--api-port', type=int, default=None, help='API port (default: from config or 8000)')
@click.option('--ui-host', default=None, help='UI host (default: 0.0.0.0)')
@click.option('--ui-port', type=int, default=None, help='UI port (default: from config or 8004)')
@click.option('--dev-mode', is_flag=True, help='Enable development mode with auto-reload')
@click.option('--no-ui', is_flag=True, help='Disable UI service')
@click.option('--no-orchestrator', is_flag=True, help='Disable orchestrator (run API/UI only)')
@click.option('--restart', is_flag=True, help='Stop and restart all services')
@click.option('--instance-name', help='Instance name for multi-instance deployments')
@click.option('--instance-role', default='standalone', help='Instance role: standalone, coordinator, worker')
@click.option('--port-offset', type=int, default=0, help='Port offset for multi-instance on same machine')
@click.option('--force-native', is_flag=True, help='Force native implementation (bypass Docker)')
@click.option('--force-docker', is_flag=True, help='Force Docker implementation (fail if Docker unavailable)')
@click.option('--build', is_flag=True, help='Build Docker images before starting')
@click.option('--api-only', is_flag=True, help='Run only API/UI services, no workers')
@click.option('--workers-only', is_flag=True, help='Run only workers, no API/UI')
@click.option('--redis-url', envvar='REDIS_URL', help='Redis URL (also via REDIS_URL env var)')
@click.option('--config-url', envvar='CONFIG_URL', help='Remote config URL (http/s3) or path')
def serve_unified(
    config_file: str,
    api_host: Optional[str],
    api_port: Optional[int],
    ui_host: Optional[str],
    ui_port: Optional[int],
    dev_mode: bool,
    no_ui: bool,
    no_orchestrator: bool,
    restart: bool,
    instance_name: Optional[str],
    instance_role: str,
    port_offset: int,
    force_native: bool,
    force_docker: bool,
    build: bool,
    api_only: bool,
    workers_only: bool,
    redis_url: Optional[str],
    config_url: Optional[str]
):
    """
    Start Gleitzeit services (API, UI, workers).

    Automatically uses Docker if available, otherwise falls back to native implementation.

    Examples:
        # Start with defaults (auto-detect Docker)
        gleitzeit serve

        # Force Docker usage
        gleitzeit serve --force-docker

        # Force native implementation (has subprocess issues!)
        gleitzeit serve --force-native

        # Custom ports
        gleitzeit serve --api-port 8080 --ui-port 8081

        # Development mode
        gleitzeit serve --dev-mode

        # No UI
        gleitzeit serve --no-ui
    """

    # Check for conflicting flags
    if force_native and force_docker:
        click.echo("❌ Cannot use both --force-native and --force-docker")
        sys.exit(1)

    if api_only and workers_only:
        click.echo("❌ Cannot use both --api-only and --workers-only")
        sys.exit(1)

    # Handle remote configuration loading
    if config_url:
        import tempfile
        import urllib.request

        # Download config from remote URL
        click.echo(f"📥 Loading configuration from {config_url}")
        try:
            with urllib.request.urlopen(config_url) as response:
                config_content = response.read()

            # Save to temp file
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.yaml', delete=False) as f:
                f.write(config_content)
                config_file = f.name
            click.echo(f"✅ Loaded config from {config_url}")
        except Exception as e:
            click.echo(f"❌ Failed to load config from {config_url}: {e}")
            sys.exit(1)

    # Determine which implementation to use
    use_docker = False

    # Check if config has mixed handler execution modes
    config_path = Path(config_file)
    has_mixed_modes = False
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
            handlers = config.get('handlers', {})
            if handlers:
                # Check if handlers have different execution modes
                modes = set()
                for handler_config in handlers.values():
                    if 'execution' in handler_config:
                        modes.add(handler_config['execution'].get('mode', 'native'))
                # If we have container mode mixed with other modes, use native services
                if 'container' in modes and len(modes) > 1:
                    has_mixed_modes = True
                    click.echo("🔀 Mixed handler execution modes detected in configuration")

    if force_docker:
        use_docker = True
        if not check_docker_available():
            click.echo("❌ Docker is not available or not running")
            click.echo("Please ensure Docker is installed and running")
            click.echo("Visit https://docs.docker.com/get-docker/ for installation")
            sys.exit(1)
        if not check_docker_compose_available():
            click.echo("❌ docker-compose is not available")
            click.echo("Please install docker-compose")
            sys.exit(1)
    elif not force_native and not has_mixed_modes:
        # Auto-detect Docker only if we don't have mixed modes
        if check_docker_available() and check_docker_compose_available():
            use_docker = True
            click.echo("🐳 Docker detected, using Docker-based implementation")
        else:
            click.echo("ℹ️  Docker not available, using native async implementation")
            click.echo("✅ Using fixed async subprocess implementation (no deadlock)")
            click.echo("   Note: For production scaling, Docker is still recommended")
            click.echo("   Visit https://docs.docker.com/get-docker/ for Docker installation")
    elif has_mixed_modes:
        # Use native services when handlers have mixed modes
        click.echo("🔧 Using native services with mixed handler execution")
        click.echo("   - Python handler will run in Docker containers")
        click.echo("   - Other handlers will run natively")
        if check_docker_available():
            click.echo("✅ Docker is available for container-based handlers")
        else:
            click.echo("⚠️  Docker not available - container-based handlers will fallback to subprocess")

    if use_docker:
        # Use Docker implementation
        from .serve_docker import serve_with_docker

        # Convert parameters to Docker implementation format
        serve_with_docker(
            config_file=config_file,
            host=api_host or "0.0.0.0",
            api_port=api_port,
            ui_port=ui_port,
            dev_mode=dev_mode,
            restart=restart,
            build=build,
            no_ui=no_ui,
            # ADD HORIZONTAL SCALING PARAMETERS
            api_only=api_only,
            workers_only=workers_only,
            redis_url=redis_url,
            config_url=config_url
        )
    else:
        # Use native async implementation (fixed!)
        asyncio.run(serve_native_async(
            config_file=config_file,
            api_host=api_host or "0.0.0.0",
            api_port=api_port or 8000,
            ui_host=ui_host or "0.0.0.0",
            ui_port=ui_port or 8004,
            dev_mode=dev_mode,
            no_ui=no_ui,
            restart=restart,
            api_only=api_only,
            workers_only=workers_only,
            redis_url=redis_url,
            port_offset=port_offset
        ))


async def serve_native_async(
    config_file: str,
    api_host: str,
    api_port: int,
    ui_host: str,
    ui_port: int,
    dev_mode: bool,
    no_ui: bool,
    restart: bool = False,
    api_only: bool = False,
    workers_only: bool = False,
    redis_url: Optional[str] = None,
    port_offset: int = 0
):
    """Native serve using AsyncProcessManager (fixes subprocess deadlock)"""
    from ..core.async_process_manager import AsyncServiceManager
    import signal

    # Apply port offset
    api_port = api_port + port_offset
    ui_port = ui_port + port_offset

    # Load configuration
    config_path = Path(config_file)
    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    # Create async service manager with config file path and Redis URL
    manager = AsyncServiceManager(
        config=config,
        log_dir=Path("logs"),
        config_file=config_path,
        redis_url=redis_url,
        port_offset=port_offset
    )

    # Handle restart flag - use proper restart coordinator
    if restart:
        click.echo("🔄 Restarting services...")

        # Check Redis first
        import redis.asyncio as aioredis
        try:
            redis_client = await aioredis.from_url(redis_url or 'redis://localhost:6379')
            await redis_client.ping()
        except Exception as e:
            click.echo(f"⚠️  Redis not available for stateless shutdown, falling back to process kill")
            redis_client = None

        if redis_client:
            # Use stateless shutdown coordinator
            from ..core.shutdown_coordinator import RestartCoordinator

            click.echo("  Using stateless shutdown via Redis...")
            restart_result = await RestartCoordinator.restart_all(
                redis_client=redis_client,
                api_port=api_port,
                ui_port=ui_port,
                force=False,
                grace_period=10
            )

            await redis_client.close()

            if restart_result['success']:
                click.echo("  ✅ Restart cleanup complete")
            else:
                click.echo("  ⚠️  Restart cleanup had issues:")
                for issue in restart_result['validation']['issues']:
                    click.echo(f"     - {issue}")
        else:
            # Fallback: Force kill all Gleitzeit processes
            click.echo("  Using fallback process cleanup...")
            import psutil
            killed = 0
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    if not cmdline:
                        continue
                    cmdline_str = ' '.join(cmdline)

                    if 'python' in cmdline_str and 'gleitzeit' in cmdline_str:
                        click.echo(f"  Killing process PID {proc.pid}")
                        proc.kill()
                        killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass

            click.echo(f"  Killed {killed} processes")
            # Wait longer for ports to be released
            await asyncio.sleep(5)

    # Setup signal handlers
    def signal_handler(sig, frame):
        click.echo("\n🛑 Stopping services...")
        asyncio.create_task(manager.stop_all())
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        click.echo("\n🎯 Starting Gleitzeit in native async mode")
        if restart:
            click.echo("   (Restart mode - stopped existing services)")
        click.echo("=" * 60)

        # Check Redis
        import redis
        try:
            r = redis.Redis(host='localhost', port=6379)
            r.ping()
            click.echo("✅ Redis is running")
        except:
            click.echo("❌ Redis is not running!")
            click.echo("Please start Redis first:")
            click.echo("  brew services start redis  # macOS")
            click.echo("  sudo systemctl start redis  # Linux")
            click.echo("  redis-server                # Manual")
            sys.exit(1)

        # Start services based on mode
        if api_only:
            click.echo("🎯 Starting API/UI only (no workers)")
            status = await manager.start_all(
                api_port=api_port,
                ui_port=ui_port,
                no_ui=no_ui,
                dev_mode=dev_mode,
                restart=restart,
                no_workers=True
            )
        elif workers_only:
            click.echo("🎯 Starting workers only (no API/UI)")
            status = await manager.start_all(
                api_port=api_port,
                ui_port=ui_port,
                no_ui=True,
                no_api=True,
                dev_mode=dev_mode,
                restart=restart
            )
        else:
            status = await manager.start_all(
                api_port=api_port,
                ui_port=ui_port,
                no_ui=no_ui,
                dev_mode=dev_mode,
                restart=restart
            )

        click.echo("\n" + "=" * 60)
        click.echo("✨ Gleitzeit is running!")
        click.echo(f"   API: http://{api_host}:{api_port}")
        if not no_ui:
            click.echo(f"   UI:  http://{ui_host}:{ui_port}")
        click.echo(f"   Logs: logs/")
        click.echo("\nPress Ctrl+C to stop all services")
        click.echo("=" * 60)

        # Monitor services
        await manager.monitor_loop()

    except KeyboardInterrupt:
        click.echo("\n🛑 Stopping services...")
        await manager.stop_all()
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        await manager.stop_all()
        sys.exit(1)


# Export for use in main.py
__all__ = ['serve_unified']