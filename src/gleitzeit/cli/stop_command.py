"""
Enhanced stop command for Gleitzeit CLI

Provides intelligent stopping of services in both Docker and native modes.

## Stop Command Flags

### Basic Usage
- `gleitzeit stop` - Gracefully stop all services (recommended for normal use)
  - Sends SIGTERM to processes (allows cleanup)
  - Waits up to 10 seconds for graceful shutdown
  - Force kills any remaining processes
  - Cleans up Redis registry
  - Stops both Docker and native services
  - **This is sufficient for most use cases**

### Optional Flags

#### `--force`
- Immediately kills processes with SIGKILL instead of graceful SIGTERM
- Use when: Processes are hung and not responding to normal shutdown
- Example: `gleitzeit stop --force`

#### `--all`
- Stops ALL gleitzeit processes including serve monitor loops
- Without this flag: Only stops worker/API/UI processes (not serve processes)
- Use when: You want to ensure absolutely everything is stopped
- Example: `gleitzeit stop --all`
- Note: In practice, `gleitzeit stop` already stops everything needed

#### `--timeout N`
- Custom timeout in seconds for graceful shutdown (default: 10)
- Use when: Services need more time to cleanly shut down
- Example: `gleitzeit stop --timeout 30`

#### `--no-validate`
- Skip validation check after stopping
- Use when: You want faster stop without verification
- Example: `gleitzeit stop --no-validate`

### Mixed Deployments
The stop command automatically detects and stops both:
- Docker containers (via docker-compose)
- Native Python processes

### Examples
```bash
gleitzeit stop                    # Normal use - stops everything
gleitzeit stop --force            # Force kill hung processes
gleitzeit stop --all              # Ensure monitor loops are stopped
gleitzeit stop --force --all      # Nuclear option - kill everything immediately
gleitzeit stop --timeout 30       # Wait longer for graceful shutdown
```
"""

import click
import subprocess
import psutil
import time
from pathlib import Path
from typing import List, Set
from .mode_utils import detect_running_mode


@click.command()
@click.option('--force', is_flag=True, help='Immediately kill processes (SIGKILL) instead of graceful shutdown (SIGTERM)')
@click.option('--timeout', type=int, default=10, help='Seconds to wait for graceful shutdown before force killing (default: 10)')
@click.option('--all', is_flag=True, help='Stop ALL processes including serve monitor loops (normally not needed)')
@click.option('--validate/--no-validate', default=True, help='Validate that all services stopped successfully')
def stop(force: bool, timeout: int, all: bool, validate: bool):
    """
    Stop all Gleitzeit services (Docker and/or native).

    Automatically detects running services and stops them appropriately.
    For most use cases, just use 'gleitzeit stop' without any flags.

    \b
    Examples:
        gleitzeit stop                    # Normal use - stops everything gracefully
        gleitzeit stop --force            # Force kill hung processes immediately
        gleitzeit stop --all              # Ensure monitor loops are also stopped
        gleitzeit stop --force --all      # Nuclear option - kill everything now
        gleitzeit stop --timeout 30       # Wait 30s for graceful shutdown

    \b
    Behavior:
        - Detects and stops both Docker containers and native processes
        - Gracefully terminates (SIGTERM) then force kills if needed
        - Cleans up Redis service registry
        - Validates that everything stopped successfully
    """
    # Check for both Docker and native services
    has_docker = has_docker_containers()
    has_native = has_native_processes()

    if not has_docker and not has_native:
        click.echo("⚠️  No running services detected")
        click.echo("   Nothing to stop")
        return

    # Stop both if both are present (handles mixed deployments)
    stopped_any = False
    if has_docker:
        stop_docker_services(force, timeout, all)
        stopped_any = True

    if has_native:
        stop_native_services(force, timeout, all)
        stopped_any = True

    if not stopped_any:
        click.echo("⚠️  No services were stopped")

    # Validate stop operation if requested
    if validate:
        import sys
        sys.exit(validate_and_report_stop())


def has_docker_containers() -> bool:
    """Check if any Gleitzeit Docker containers are running"""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            containers = result.stdout.strip().split('\n')
            return any('gleitzeit' in c.lower() for c in containers if c)
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def has_native_processes() -> bool:
    """Check if any native Gleitzeit processes are running"""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if not cmdline:
                    continue
                cmdline_str = ' '.join(cmdline)
                if 'python' in cmdline_str and 'gleitzeit' in cmdline_str:
                    if any(module in cmdline_str for module in [
                        'gleitzeit.api.main',
                        'gleitzeit.ui.api.app',
                        'gleitzeit.workers.runner'
                    ]):
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False
    except Exception:
        return False


def stop_docker_services(force: bool, timeout: int, stop_all: bool):
    """Stop Docker services"""
    click.echo("🐳 Stopping Docker services...")

    # Method 1: Stop via compose files
    # Find all compose files (including main ones and observability)
    compose_files = []

    # Check for main compose files
    for main_file in ["docker-compose.yml", "docker-compose.yaml"]:
        main_path = Path(main_file)
        if main_path.exists():
            compose_files.append(main_path)

    # Check for additional compose files (observability, dev, prod, etc.)
    for pattern in ["docker-compose.*.yml", "docker-compose-*.yml"]:
        for f in Path(".").glob(pattern):
            if f not in compose_files:
                compose_files.append(f)

    # Static compose files that should NOT be deleted
    static_compose_files = {
        "docker-compose.yml",
        "docker-compose.yaml",
        "docker-compose.observability.yml",
        "docker-compose.dev.yml",
        "docker-compose.prod.yml"
    }

    stopped_via_compose = 0
    if compose_files:
        click.echo(f"   Found {len(compose_files)} compose file(s)")
        for compose_file in compose_files:
            try:
                click.echo(f"   Stopping via {compose_file.name}...")
                cmd = ["docker-compose", "-f", str(compose_file), "down"]
                if force:
                    cmd.extend(["-t", "1"])
                else:
                    cmd.extend(["-t", str(timeout)])

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
                if result.returncode == 0:
                    stopped_via_compose += 1
                    # Only delete dynamically generated compose files
                    if compose_file.name not in static_compose_files:
                        try:
                            compose_file.unlink()
                        except Exception:
                            pass
            except Exception as e:
                click.echo(f"   ⚠️  Error with {compose_file.name}: {e}")

    # Method 2: Stop containers directly (catches orphaned containers)
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            containers = [c for c in result.stdout.strip().split('\n')
                         if c and 'gleitzeit' in c.lower()]

            if containers:
                click.echo(f"   Found {len(containers)} running container(s)")
                for container in containers:
                    try:
                        if force:
                            click.echo(f"   Force killing container: {container}")
                            subprocess.run(["docker", "kill", container],
                                         capture_output=True, timeout=5)
                        else:
                            click.echo(f"   Stopping container: {container}")
                            subprocess.run(["docker", "stop", "-t", str(timeout), container],
                                         capture_output=True, timeout=timeout + 5)
                    except Exception as e:
                        click.echo(f"   ⚠️  Error stopping {container}: {e}")

                click.echo(f"✅ Stopped Docker containers")
            elif stopped_via_compose == 0:
                click.echo("   No Docker containers found")
    except Exception as e:
        if stopped_via_compose == 0:
            click.echo(f"   ⚠️  Could not check for containers: {e}")


def stop_native_services(force: bool, timeout: int, stop_all: bool):
    """Stop native Python processes with complete cleanup"""
    if stop_all:
        click.echo("🔧 Stopping ALL native services and instances...")
    else:
        click.echo("🔧 Stopping native services...")

    # Find all gleitzeit processes (not just main ones)
    stopped_count = 0
    processes_to_stop: List[psutil.Process] = []

    # Collect processes to stop
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if not cmdline:
                continue

            cmdline_str = ' '.join(cmdline)

            # Check if it's a gleitzeit process
            if 'python' in cmdline_str and 'gleitzeit' in cmdline_str:
                # Stop ALL gleitzeit processes (workers, api, ui, handlers, etc.)
                if stop_all:
                    # Stop everything including serve processes
                    processes_to_stop.append(proc)
                else:
                    # Stop service processes (not serve monitor)
                    if any(module in cmdline_str for module in [
                        'gleitzeit.api.main',
                        'gleitzeit.ui.api.app',
                        'gleitzeit.workers.runner',
                        'gleitzeit.handlers'
                    ]):
                        processes_to_stop.append(proc)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not processes_to_stop:
        click.echo("   No native processes found running")
        return

    click.echo(f"   Found {len(processes_to_stop)} processes to stop")

    # Stop processes
    for proc in processes_to_stop:
        try:
            if force:
                click.echo(f"   Force killing PID {proc.pid}")
                proc.kill()
            else:
                click.echo(f"   Terminating PID {proc.pid}")
                proc.terminate()
            stopped_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Wait for processes to stop
    if not force and processes_to_stop:
        click.echo(f"   Waiting up to {timeout} seconds for graceful shutdown...")

        gone, alive = psutil.wait_procs(
            processes_to_stop,
            timeout=timeout,
            callback=None
        )

        if alive:
            click.echo(f"   {len(alive)} processes still running, force killing...")
            for proc in alive:
                try:
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

    # Also check for processes on known ports
    ports_to_check = [8000, 8004]  # API and UI ports
    for port in ports_to_check:
        try:
            for conn in psutil.net_connections():
                if conn.laddr.port == port and conn.status == 'LISTEN':
                    proc = psutil.Process(conn.pid)
                    if force:
                        proc.kill()
                    else:
                        proc.terminate()
                    stopped_count += 1
                    click.echo(f"   Stopped process on port {port} (PID: {conn.pid})")
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            continue

    if stopped_count > 0:
        click.echo(f"✅ Stopped {stopped_count} native processes")
    else:
        click.echo("   No processes were stopped")

    # ALWAYS clean Redis keys (not just with --all)
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379)

        # Track what we're cleaning
        keys_deleted = 0

        # Clear service registry
        for key in r.scan_iter(match="service:registry:*"):
            r.delete(key)
            keys_deleted += 1

        # Clear worker metrics
        for key in r.scan_iter(match="{shard:0}:worker:metrics:*"):
            r.delete(key)
            keys_deleted += 1

        # Clear worker registry
        for key in r.scan_iter(match="{shard:0}:worker:registry:*"):
            r.delete(key)
            keys_deleted += 1

        # Clear handler registrations
        for key in r.scan_iter(match="handler:registration:*"):
            r.delete(key)
            keys_deleted += 1

        # Clear worker configs (if --all)
        if stop_all:
            for key in r.scan_iter(match="worker:config:*"):
                r.delete(key)
                keys_deleted += 1

        if keys_deleted > 0:
            click.echo(f"   ✅ Cleaned {keys_deleted} Redis keys (registry, metrics, handlers)")
        else:
            click.echo("   No Redis keys to clean")

    except Exception as e:
        click.echo(f"   ⚠️  Redis cleanup failed: {e}")

    # Clean up log directory pid files
    log_dir = Path("logs")
    if log_dir.exists():
        pid_files = list(log_dir.glob("*.pid"))
        if pid_files:
            click.echo(f"   Cleaning up {len(pid_files)} PID files")
            for pid_file in pid_files:
                try:
                    pid_file.unlink()
                except Exception:
                    pass


def check_if_stopped() -> tuple[bool, list[str]]:
    """
    Check if all services have been stopped.

    Returns:
        (success: bool, issues: List[str])
    """
    import os
    issues = []

    # Get current process and parent to exclude from check
    current_pid = os.getpid()
    try:
        current_proc = psutil.Process(current_pid)
        parent_pid = current_proc.ppid()
    except:
        parent_pid = None

    # 1. Check for running processes
    running_procs = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if not cmdline:
                continue
            cmdline_str = ' '.join(cmdline)
            if 'gleitzeit' in cmdline_str and 'python' in cmdline_str:
                # Exclude the stop command itself and its parent
                if proc.pid != current_pid and proc.pid != parent_pid:
                    running_procs.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if running_procs:
        issues.append(f"Found {len(running_procs)} running processes: {running_procs}")

    # 2. Check for Docker containers
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "ps", "--filter", "label=gleitzeit", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            containers = [c for c in result.stdout.strip().split('\n') if c]
            if containers:
                issues.append(f"Found {len(containers)} running containers: {containers}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # Docker not available

    # 3. Check Redis for stale service registry
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379)
        stale_keys = []
        for key in r.scan_iter(match="service:registry:*"):
            stale_keys.append(key.decode())
        if stale_keys:
            issues.append(f"Found {len(stale_keys)} stale registry keys: {stale_keys[:5]}")
    except:
        pass  # Redis not available

    return (len(issues) == 0, issues)


def validate_and_report_stop():
    """Validate stop operation and report detailed feedback"""
    success, issues = check_if_stopped()

    if success:
        click.echo("\n✅ All services stopped successfully")
        click.echo("   - No running processes")
        click.echo("   - No running containers")
        click.echo("   - Service registry cleared")
        return 0
    else:
        click.echo("\n⚠️  Stop completed with issues:")
        for issue in issues:
            click.echo(f"   - {issue}")
        click.echo("\nRun 'gleitzeit stop --force --all' to force cleanup")
        return 1