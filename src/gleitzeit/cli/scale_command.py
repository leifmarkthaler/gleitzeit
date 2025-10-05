"""
Scale command for Gleitzeit CLI

Provides worker scaling capabilities for Docker mode.
"""

import click
import subprocess
import yaml
from pathlib import Path
from typing import Dict, Optional
from .mode_utils import detect_running_mode


@click.command()
@click.argument('spec')  # e.g., "task_execution=3"
@click.option('--dry-run', is_flag=True, help='Show what would be scaled without applying')
def scale(spec: str, dry_run: bool):
    """
    Scale worker services.

    SPEC format: service=count (e.g., task_execution=3, dependency=2)

    Examples:
        gleitzeit scale task_execution=3    # Scale task execution workers to 3
        gleitzeit scale dependency=2        # Scale dependency workers to 2
        gleitzeit scale all=0               # Stop all workers
        gleitzeit scale --dry-run task_execution=5  # Preview scaling

    Note: Currently only supported in Docker mode.
    """
    # Parse scaling specification
    try:
        if '=' not in spec:
            raise ValueError("Invalid format")

        service, count = spec.split('=', 1)
        count = int(count)

        if count < 0:
            raise ValueError("Count must be non-negative")

    except (ValueError, IndexError) as e:
        click.echo(f"❌ Invalid scaling specification: {spec}")
        click.echo("   Format: service=count (e.g., task_execution=3)")
        return

    # Detect running mode
    mode = detect_running_mode()

    if mode == "docker":
        scale_docker_services(service, count, dry_run)
    elif mode == "native":
        click.echo("⚠️  Scaling is not yet supported in native mode")
        click.echo("   To change worker count in native mode:")
        click.echo("   1. Stop services: gleitzeit stop")
        click.echo("   2. Modify worker count in gleitzeit.yaml")
        click.echo("   3. Start services: gleitzeit serve")
    else:
        click.echo("⚠️  No running services detected")
        click.echo("   Start services first: gleitzeit serve")


def scale_docker_services(service: str, count: int, dry_run: bool):
    """Scale Docker services using docker-compose"""
    compose_file = Path("docker-compose-proper.yml")

    if not compose_file.exists():
        click.echo("❌ Docker compose file not found")
        click.echo("   Ensure services were started with Docker mode")
        return

    # Map service names to Docker service names
    # Note: Current docker-compose has individual services per worker instance
    service_map = {
        'task_execution': ['worker-task-execution-1', 'worker-task-execution-2'],
        'dependency': ['worker-dependency'],
        'workflow_loader': ['worker-workflow-loader-1', 'worker-workflow-loader-2'],
        'workflow_submission': ['worker-workflow-submission'],
        'timer': ['worker-timer'],
        'retry': ['worker-retry'],
        'all': None  # Special case for all workers
    }

    # Handle 'all' scaling
    if service == 'all':
        if dry_run:
            click.echo(f"🔍 Dry run: Would scale all workers to {count}")
            for svc_name, docker_names in service_map.items():
                if docker_names:
                    for docker_name in docker_names:
                        click.echo(f"   - {docker_name}: {count} instances")
            return
        else:
            click.echo(f"📊 Scaling all workers to {count}...")
            for svc_name, docker_names in service_map.items():
                if docker_names:
                    for docker_name in docker_names:
                        scale_single_service(compose_file, docker_name, count)
            return

    # Get Docker service names
    docker_services = service_map.get(service)

    if not docker_services:
        # Try using the service name as-is
        docker_services = [f"worker-{service}"]
        click.echo(f"ℹ️  Attempting to scale service: {docker_services[0]}")

    if dry_run:
        click.echo(f"🔍 Dry run: Would scale {service} workers to {count} instances")
        for docker_service in docker_services:
            click.echo(f"   - {docker_service}")
        return

    # For services with multiple instances, we need a different approach
    if len(docker_services) > 1:
        click.echo(f"⚠️  Service {service} has {len(docker_services)} separate instances in docker-compose")
        click.echo(f"   Current instances: {', '.join(docker_services)}")
        click.echo(f"   Scaling individual instances is not supported with current docker-compose structure")
        click.echo(f"   To change worker count, modify docker-compose-proper.yml and restart services")
        return

    # Perform scaling for single service
    scale_single_service(compose_file, docker_services[0], count)


def scale_single_service(compose_file: Path, service: str, count: int):
    """Scale a single Docker service"""
    click.echo(f"📊 Scaling {service} to {count} instances...")

    try:
        # Use docker-compose scale command
        cmd = [
            "docker-compose",
            "-f", str(compose_file),
            "up", "-d",
            "--scale", f"{service}={count}",
            "--no-recreate"  # Don't recreate existing containers
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            click.echo(f"✅ Successfully scaled {service} to {count} instances")

            # Show current status
            show_service_status(compose_file, service)
        else:
            click.echo(f"❌ Failed to scale {service}")
            if result.stderr:
                click.echo(f"   Error: {result.stderr}")

                # Check if service exists
                if "no such service" in result.stderr.lower():
                    click.echo(f"   Service '{service}' not found in docker-compose.yml")
                    click.echo("   Available services:")
                    show_available_services(compose_file)

    except subprocess.TimeoutExpired:
        click.echo(f"❌ Scaling operation timed out")
    except Exception as e:
        click.echo(f"❌ Error scaling service: {e}")


def show_service_status(compose_file: Path, service: str):
    """Show status of a specific service"""
    try:
        cmd = [
            "docker-compose",
            "-f", str(compose_file),
            "ps",
            service
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0 and result.stdout:
            click.echo("\n📋 Current status:")
            lines = result.stdout.strip().split('\n')
            for line in lines:
                click.echo(f"   {line}")

    except Exception:
        pass  # Ignore errors in status display


def show_available_services(compose_file: Path):
    """Show available services in docker-compose file"""
    try:
        with open(compose_file, 'r') as f:
            config = yaml.safe_load(f)

        services = config.get('services', {})
        worker_services = [
            name for name in services.keys()
            if name.startswith('worker-')
        ]

        if worker_services:
            for service in worker_services:
                # Extract worker type from service name
                worker_type = service.replace('worker-', '').replace('-', '_')
                click.echo(f"   - {worker_type} (Docker service: {service})")

    except Exception:
        pass  # Ignore errors in listing services


def get_current_scale(compose_file: Path) -> Dict[str, int]:
    """Get current scaling for all services"""
    scale_info = {}

    try:
        cmd = [
            "docker-compose",
            "-f", str(compose_file),
            "ps",
            "--format", "json"
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0 and result.stdout:
            import json

            # Parse JSON output
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        container = json.loads(line)
                        service = container.get('Service', '')
                        if service.startswith('worker-'):
                            scale_info[service] = scale_info.get(service, 0) + 1
                    except json.JSONDecodeError:
                        continue

    except Exception:
        pass

    return scale_info