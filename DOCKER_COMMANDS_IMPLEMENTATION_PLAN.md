# Docker Commands Implementation Plan

## Overview
Enhance Gleitzeit CLI to provide seamless Docker and native mode operations through unified commands.

## Current State Analysis

### Existing Commands
- `gleitzeit serve` - ✅ Works with both Docker and native (auto-detection)
- `gleitzeit serve --restart` - ✅ Works with both modes
- `gleitzeit serve --force-docker` - ✅ Forces Docker mode
- `gleitzeit serve --force-native` - ✅ Forces native mode
- `gleitzeit serve --build` - ✅ Docker image building
- `gleitzeit stop` - ⚠️ Exists but may not detect mode correctly
- `gleitzeit ps` - ⚠️ Exists but doesn't show Docker containers

### Mode Detection Requirements
Need to detect which mode is currently running to apply correct commands:
1. Check for running Docker containers with gleitzeit labels
2. Check for docker-compose-proper.yml file
3. Check for native process PIDs in logs/
4. Check for running Python processes with gleitzeit modules

## Implementation Plan

### 1. Mode Detection Utility
**File:** `src/gleitzeit/cli/mode_utils.py`

```python
import subprocess
import psutil
from pathlib import Path

def detect_running_mode() -> str:
    """Detect if services are running in Docker or native mode"""

    # Check Docker containers
    if is_docker_running():
        return "docker"

    # Check native processes
    if is_native_running():
        return "native"

    return None

def is_docker_running() -> bool:
    """Check if Docker containers are running"""
    try:
        result = subprocess.run(
            ["docker-compose", "-f", "docker-compose-proper.yml", "ps", "-q"],
            capture_output=True
        )
        return result.returncode == 0 and result.stdout.strip()
    except:
        return False

def is_native_running() -> bool:
    """Check if native processes are running"""
    # Check for gleitzeit.api.main or gleitzeit.workers processes
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if cmdline and 'gleitzeit' in str(cmdline):
                if any(x in str(cmdline) for x in ['api.main', 'workers.runner', 'ui.api']):
                    return True
        except:
            continue
    return False
```

### 2. Enhanced Stop Command
**File:** Update `src/gleitzeit/cli/main.py`

```python
@cli.command('stop')
@click.option('--force', is_flag=True, help='Force stop all processes')
def stop(force):
    """Stop all Gleitzeit services (Docker or native)"""
    from .mode_utils import detect_running_mode
    from .serve_docker import DockerOrchestrator
    from ..core.async_process_manager import AsyncServiceManager

    mode = detect_running_mode()

    if mode == "docker":
        click.echo("🐳 Stopping Docker services...")
        orchestrator = DockerOrchestrator()
        orchestrator.stop_services()
    elif mode == "native":
        click.echo("🔧 Stopping native services...")
        # Kill processes by port
        import psutil
        for proc in psutil.process_iter(['pid', 'connections']):
            try:
                for conn in proc.connections():
                    if hasattr(conn, 'laddr') and conn.laddr.port in [8000, 8004]:
                        click.echo(f"Stopping process on port {conn.laddr.port} (PID: {proc.pid})")
                        proc.terminate()
                        proc.wait(timeout=5)
            except:
                pass
    else:
        click.echo("⚠️ No running services detected")
```

### 3. Unified Logs Command
**File:** `src/gleitzeit/cli/logs_command.py`

```python
import click
import subprocess
from pathlib import Path
from .mode_utils import detect_running_mode

@click.command()
@click.argument('service', required=False)
@click.option('--follow', '-f', is_flag=True, help='Follow log output')
@click.option('--tail', '-n', type=int, default=100, help='Number of lines to show')
@click.option('--since', help='Show logs since timestamp (Docker only)')
def logs(service, follow, tail, since):
    """View service logs (Docker or native)"""
    mode = detect_running_mode()

    if mode == "docker":
        show_docker_logs(service, follow, tail, since)
    elif mode == "native":
        show_native_logs(service, follow, tail)
    else:
        click.echo("⚠️ No running services detected")
        click.echo("Start services with: gleitzeit serve")

def show_docker_logs(service, follow, tail, since):
    """Show Docker container logs"""
    cmd = ["docker-compose", "-f", "docker-compose-proper.yml", "logs"]

    if follow:
        cmd.append("-f")
    if tail:
        cmd.extend(["--tail", str(tail)])
    if since:
        cmd.extend(["--since", since])
    if service:
        cmd.append(service)

    subprocess.run(cmd)

def show_native_logs(service, follow, tail):
    """Show native process logs"""
    log_dir = Path("logs")

    if not log_dir.exists():
        click.echo("No logs directory found")
        return

    # Find latest log files
    if service:
        pattern = f"{service}_*.log"
    else:
        pattern = "*.log"

    log_files = sorted(log_dir.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)

    if not log_files:
        click.echo(f"No log files found for {service or 'any service'}")
        return

    # Show logs
    for log_file in log_files[:1]:  # Show only latest
        click.echo(f"\n📄 {log_file.name}")
        click.echo("-" * 40)

        if follow:
            subprocess.run(["tail", "-f", str(log_file)])
        else:
            subprocess.run(["tail", f"-n{tail}", str(log_file)])
```

### 4. Enhanced PS Command
**File:** Update `src/gleitzeit/cli/main.py` or `process_commands.py`

```python
@cli.command('ps')
@click.option('--all', '-a', is_flag=True, help='Show all processes/containers')
def ps(all):
    """List running services (Docker or native)"""
    from .mode_utils import detect_running_mode

    mode = detect_running_mode()

    if mode == "docker":
        click.echo("🐳 Docker Services:")
        result = subprocess.run(
            ["docker-compose", "-f", "docker-compose-proper.yml", "ps"],
            capture_output=True, text=True
        )
        click.echo(result.stdout)
    elif mode == "native":
        click.echo("🔧 Native Processes:")
        import psutil

        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'status']):
            try:
                cmdline = ' '.join(proc.info.get('cmdline', []))
                if 'gleitzeit' in cmdline:
                    if any(x in cmdline for x in ['api.main', 'workers.runner', 'ui.api']):
                        processes.append({
                            'PID': proc.info['pid'],
                            'Status': proc.info['status'],
                            'Service': extract_service_name(cmdline)
                        })
            except:
                continue

        if processes:
            for p in processes:
                click.echo(f"  PID {p['PID']}: {p['Service']} [{p['Status']}]")
        else:
            click.echo("  No native processes running")
    else:
        click.echo("⚠️ No services running")
```

### 5. Scale Command
**File:** `src/gleitzeit/cli/scale_command.py`

```python
import click
import yaml
from pathlib import Path
from .mode_utils import detect_running_mode

@click.command()
@click.argument('spec')  # e.g., "task_execution=3"
def scale(spec):
    """Scale worker services"""
    try:
        service, count = spec.split('=')
        count = int(count)
    except ValueError:
        click.echo("❌ Invalid format. Use: service=count (e.g., task_execution=3)")
        return

    mode = detect_running_mode()

    if mode == "docker":
        scale_docker_service(service, count)
    elif mode == "native":
        click.echo("⚠️ Native mode scaling not yet implemented")
        click.echo("Restart with different worker count in config")
    else:
        click.echo("⚠️ No services running")

def scale_docker_service(service, count):
    """Scale Docker service"""
    # Update docker-compose scale
    subprocess.run([
        "docker-compose", "-f", "docker-compose-proper.yml",
        "up", "-d", "--scale", f"{service}={count}"
    ])
    click.echo(f"✅ Scaled {service} to {count} instances")
```

### 6. Clean Command
**File:** `src/gleitzeit/cli/clean_command.py`

```python
import click
import subprocess
import shutil
from pathlib import Path

@click.command()
@click.option('--volumes', is_flag=True, help='Remove Docker volumes')
@click.option('--images', is_flag=True, help='Remove Docker images')
@click.option('--logs', is_flag=True, help='Remove log files')
@click.option('--all', is_flag=True, help='Remove everything')
@click.pass_context
def clean(ctx, volumes, images, logs, all):
    """Clean up resources"""

    if all:
        volumes = images = logs = True

    # Clean Docker resources
    if volumes or images:
        if subprocess.run(["docker", "--version"], capture_output=True).returncode == 0:
            if volumes:
                click.echo("🗑️ Removing Docker volumes...")
                subprocess.run(["docker-compose", "-f", "docker-compose-proper.yml", "down", "-v"])

            if images:
                click.echo("🗑️ Removing Docker images...")
                subprocess.run(["docker-compose", "-f", "docker-compose-proper.yml", "down", "--rmi", "all"])

    # Clean logs
    if logs:
        log_dir = Path("logs")
        if log_dir.exists():
            click.echo("🗑️ Removing log files...")
            shutil.rmtree(log_dir)
            log_dir.mkdir()

    click.echo("✅ Cleanup complete")
```

### 7. Integration into main.py
**File:** Update `src/gleitzeit/cli/main.py`

```python
# Add imports
from .logs_command import logs
from .scale_command import scale
from .clean_command import clean

# Register commands
cli.add_command(logs)
cli.add_command(scale)
cli.add_command(clean)
```

## Testing Plan

### Phase 1: Mode Detection
1. Start services with Docker, verify `detect_running_mode()` returns "docker"
2. Start services with native, verify `detect_running_mode()` returns "native"
3. Stop all services, verify `detect_running_mode()` returns None

### Phase 2: Command Testing
1. **Stop Command:**
   - Test stopping Docker services
   - Test stopping native services
   - Test when no services running

2. **Logs Command:**
   - Test viewing Docker logs
   - Test viewing native logs
   - Test follow mode
   - Test tail option

3. **PS Command:**
   - Test showing Docker containers
   - Test showing native processes
   - Test when nothing running

4. **Scale Command:**
   - Test scaling Docker workers
   - Test error handling for native mode

5. **Clean Command:**
   - Test cleaning Docker volumes
   - Test cleaning logs
   - Test --all flag

## Implementation Order

1. **Week 1:** Mode detection utility + Enhanced stop command
2. **Week 2:** Logs command + Enhanced ps command
3. **Week 3:** Scale command + Clean command
4. **Week 4:** Testing and documentation

## Success Criteria

- ✅ All commands auto-detect running mode
- ✅ Commands work seamlessly with both Docker and native
- ✅ Clear error messages when operations not supported
- ✅ No breaking changes to existing functionality
- ✅ Commands are intuitive and consistent