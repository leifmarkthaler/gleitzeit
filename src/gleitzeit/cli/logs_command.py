"""
Unified logs command for Gleitzeit CLI

Provides log viewing for both Docker and native modes.
"""

import click
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from .mode_utils import detect_running_mode


@click.command()
@click.argument('service', required=False)
@click.option('--follow', '-f', is_flag=True, help='Follow log output')
@click.option('--tail', '-n', type=int, default=100, help='Number of lines to show from the end')
@click.option('--since', help='Show logs since timestamp (Docker only, e.g., 2023-01-01, 10m, 1h)')
@click.option('--timestamps', '-t', is_flag=True, help='Show timestamps')
def logs(service: Optional[str], follow: bool, tail: int, since: Optional[str], timestamps: bool):
    """
    View service logs (Docker or native).

    SERVICE can be: api, ui, worker_task_execution, worker_dependency, etc.
    If SERVICE is not specified, shows logs from all services.

    Examples:
        gleitzeit logs               # Show all logs
        gleitzeit logs api           # Show API logs
        gleitzeit logs -f            # Follow all logs
        gleitzeit logs api -n 50     # Show last 50 lines of API logs
        gleitzeit logs --since 10m   # Show logs from last 10 minutes (Docker only)
    """
    mode = detect_running_mode()

    if mode == "docker":
        show_docker_logs(service, follow, tail, since, timestamps)
    elif mode == "native":
        show_native_logs(service, follow, tail, timestamps)
    else:
        click.echo("⚠️  No running services detected")
        click.echo("Start services with: gleitzeit serve")
        click.echo("\nTo view historical logs, check the logs/ directory")


def show_docker_logs(service: Optional[str], follow: bool, tail: int,
                     since: Optional[str], timestamps: bool):
    """Show Docker container logs using docker-compose"""
    compose_file = Path("docker-compose-proper.yml")

    if not compose_file.exists():
        click.echo("❌ Docker compose file not found")
        return

    cmd = ["docker-compose", "-f", str(compose_file), "logs"]

    # Add options
    if follow:
        cmd.append("-f")

    if tail:
        cmd.extend(["--tail", str(tail)])

    if since:
        cmd.extend(["--since", since])

    if timestamps:
        cmd.append("-t")

    # Add service if specified
    if service:
        # Map service names to Docker service names
        service_map = {
            'api': 'api',
            'ui': 'ui',
            'redis': 'redis',
            'worker_task_execution': 'worker-task-execution',
            'worker_dependency': 'worker-dependency',
            'worker_workflow_loader': 'worker-workflow-loader',
            'worker_workflow_submission': 'worker-workflow-submission',
        }

        docker_service = service_map.get(service, service)
        cmd.append(docker_service)

        click.echo(f"🐳 Showing Docker logs for {docker_service}...")
    else:
        click.echo("🐳 Showing Docker logs for all services...")

    try:
        # Run the command
        subprocess.run(cmd)
    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Failed to get Docker logs: {e}")
    except KeyboardInterrupt:
        click.echo("\n👋 Stopped following logs")


def show_native_logs(service: Optional[str], follow: bool, tail: int, timestamps: bool):
    """Show native process logs from log files"""
    log_dir = Path("logs")

    if not log_dir.exists():
        click.echo("📁 No logs directory found")
        click.echo("Native services may not have been started yet")
        return

    # Find log files
    if service:
        # Look for service-specific logs
        pattern = f"{service}_*.log"
        log_files = sorted(log_dir.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)

        if not log_files:
            # Try alternate patterns
            patterns = [
                f"*{service}*.log",
                f"*{service}*.out",
                f"*{service}*.err"
            ]
            for pattern in patterns:
                log_files = sorted(log_dir.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
                if log_files:
                    break

        if not log_files:
            click.echo(f"❌ No log files found for service: {service}")
            click.echo(f"Available services: {', '.join(get_available_services(log_dir))}")
            return
    else:
        # Get all recent log files
        log_files = sorted(log_dir.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)

        if not log_files:
            # Try other extensions
            log_files = sorted(log_dir.glob("*.out"), key=lambda x: x.stat().st_mtime, reverse=True)

        if not log_files:
            click.echo("📁 No log files found in logs/ directory")
            return

    # Show logs
    if service:
        click.echo(f"📝 Showing native logs for {service}...")
        # Show only the most recent log file for the service
        show_log_file(log_files[0], follow, tail, timestamps)
    else:
        click.echo("📝 Showing native logs for all services...")

        if follow:
            # For follow mode with multiple files, use tail -f
            cmd = ["tail", "-f"]
            if tail:
                cmd.extend([f"-n{tail}"])

            # Add all recent log files (limit to last 5 to avoid too many)
            for log_file in log_files[:5]:
                cmd.append(str(log_file))

            try:
                subprocess.run(cmd)
            except KeyboardInterrupt:
                click.echo("\n👋 Stopped following logs")
        else:
            # Show tail from each file
            for log_file in log_files[:5]:  # Show last 5 files
                click.echo(f"\n📄 {log_file.name}")
                click.echo("-" * 60)
                show_log_file(log_file, False, min(tail, 20), timestamps)  # Limit lines per file


def show_log_file(log_file: Path, follow: bool, tail: int, timestamps: bool):
    """Display a single log file"""
    if not log_file.exists():
        click.echo(f"❌ Log file not found: {log_file}")
        return

    try:
        if follow:
            # Use tail -f for following
            cmd = ["tail", "-f"]
            if tail:
                cmd.append(f"-n{tail}")
            cmd.append(str(log_file))

            subprocess.run(cmd)
        else:
            # Read and display the file
            with open(log_file, 'r') as f:
                lines = f.readlines()

                # Get last N lines
                if tail and tail < len(lines):
                    lines = lines[-tail:]

                # Add timestamps if requested and not already present
                for line in lines:
                    if timestamps and not line.startswith('['):
                        # Add timestamp if not present
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        click.echo(f"[{timestamp}] {line}", nl=False)
                    else:
                        click.echo(line, nl=False)

    except KeyboardInterrupt:
        click.echo("\n👋 Stopped reading logs")
    except Exception as e:
        click.echo(f"❌ Error reading log file: {e}")


def get_available_services(log_dir: Path) -> List[str]:
    """Get list of services that have log files"""
    services = set()

    for log_file in log_dir.glob("*.log"):
        # Extract service name from filename
        # Format is usually: service_YYYYMMDD_HHMMSS.log
        name = log_file.stem
        if '_' in name:
            # Get the part before the timestamp
            parts = name.split('_')
            if len(parts) >= 2:
                # Check if the second part looks like a date
                if parts[-2].isdigit() and len(parts[-2]) == 8:
                    service_name = '_'.join(parts[:-2])
                else:
                    service_name = parts[0]
                services.add(service_name)

    return sorted(services)