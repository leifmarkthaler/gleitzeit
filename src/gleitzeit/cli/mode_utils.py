"""
Mode detection utilities for Gleitzeit CLI

Detects whether services are running in Docker or native mode
to enable unified commands that work with both implementations.
"""

import subprocess
import psutil
from pathlib import Path
from typing import Optional, List, Dict


def detect_running_mode() -> Optional[str]:
    """
    Detect if services are running in Docker or native mode

    Returns:
        "docker" if Docker containers are running
        "native" if native processes are running
        None if no services are running
    """
    # Check Docker first (more definitive)
    if is_docker_running():
        return "docker"

    # Check native processes
    if is_native_running():
        return "native"

    return None


def is_docker_running() -> bool:
    """Check if Docker containers are running"""
    try:
        # Check if docker-compose file exists
        compose_file = Path("docker-compose-proper.yml")
        if not compose_file.exists():
            return False

        # Check for running containers
        result = subprocess.run(
            ["docker-compose", "-f", str(compose_file), "ps", "-q"],
            capture_output=True,
            text=True,
            timeout=5
        )

        # If command succeeds and returns container IDs, Docker is running
        return result.returncode == 0 and bool(result.stdout.strip())

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def is_native_running() -> bool:
    """Check if native processes are running"""
    try:
        # Check for gleitzeit processes
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if not cmdline:
                    continue

                cmdline_str = ' '.join(cmdline)

                # Check for gleitzeit API, UI, or worker processes
                if 'python' in cmdline_str and 'gleitzeit' in cmdline_str:
                    if any(module in cmdline_str for module in [
                        'gleitzeit.api.main',
                        'gleitzeit.ui.api.app',
                        'gleitzeit.workers.runner'
                    ]):
                        return True

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        return False

    except Exception:
        return False


def get_running_services() -> Dict[str, List[Dict]]:
    """
    Get detailed information about running services

    Returns:
        Dictionary with 'docker' and/or 'native' keys containing service info
    """
    services = {}

    # Check Docker services
    if is_docker_running():
        docker_services = get_docker_services()
        if docker_services:
            services['docker'] = docker_services

    # Check native services
    native_services = get_native_services()
    if native_services:
        services['native'] = native_services

    return services


def get_docker_services() -> List[Dict]:
    """Get information about running Docker containers"""
    try:
        compose_file = Path("docker-compose-proper.yml")
        if not compose_file.exists():
            return []

        result = subprocess.run(
            ["docker-compose", "-f", str(compose_file), "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return []

        # Parse JSON output if available
        import json
        try:
            return json.loads(result.stdout)
        except:
            # Fallback to basic parsing
            services = []
            lines = result.stdout.strip().split('\n')
            for line in lines[1:]:  # Skip header
                if line.strip():
                    services.append({'name': line.split()[0], 'status': 'running'})
            return services

    except Exception:
        return []


def get_native_services() -> List[Dict]:
    """Get information about running native processes"""
    services = []

    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'status', 'create_time']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if not cmdline:
                    continue

                cmdline_str = ' '.join(cmdline)

                # Identify gleitzeit services
                if 'python' in cmdline_str and 'gleitzeit' in cmdline_str:
                    service_info = {
                        'pid': proc.info['pid'],
                        'status': proc.info['status'],
                        'service': None
                    }

                    # Identify service type
                    if 'gleitzeit.api.main' in cmdline_str:
                        service_info['service'] = 'api'
                        service_info['port'] = 8000
                    elif 'gleitzeit.ui.api.app' in cmdline_str:
                        service_info['service'] = 'ui'
                        service_info['port'] = 8004
                    elif 'gleitzeit.workers.runner' in cmdline_str:
                        # Extract worker type from command line
                        if '--worker-type' in cmdline_str:
                            idx = cmdline.index('--worker-type')
                            if idx + 1 < len(cmdline):
                                service_info['service'] = f"worker_{cmdline[idx + 1]}"
                        else:
                            service_info['service'] = 'worker'

                    if service_info['service']:
                        services.append(service_info)

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

    except Exception:
        pass

    return services


def check_docker_available() -> bool:
    """Check if Docker is installed and available"""
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            timeout=2
        )

        if result.returncode != 0:
            return False

        # Also check if Docker daemon is running
        result = subprocess.run(
            ["docker", "ps"],
            capture_output=True,
            timeout=2
        )

        return result.returncode == 0

    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_docker_compose_available() -> bool:
    """Check if docker-compose is installed and available"""
    try:
        result = subprocess.run(
            ["docker-compose", "--version"],
            capture_output=True,
            timeout=2
        )
        return result.returncode == 0

    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False