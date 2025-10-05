"""
Clean command for Gleitzeit CLI

Provides cleanup of Docker resources, logs, and other artifacts.
"""

import click
import subprocess
import shutil
from pathlib import Path
from typing import List
from .mode_utils import detect_running_mode


@click.command()
@click.option('--volumes', is_flag=True, help='Remove Docker volumes')
@click.option('--images', is_flag=True, help='Remove Docker images')
@click.option('--logs', is_flag=True, help='Remove log files')
@click.option('--cache', is_flag=True, help='Remove cache files')
@click.option('--all', is_flag=True, help='Remove everything (volumes, images, logs, cache)')
@click.option('--force', is_flag=True, help='Force removal without confirmation')
def clean(volumes: bool, images: bool, logs: bool, cache: bool, all: bool, force: bool):
    """
    Clean up Gleitzeit resources.

    Removes Docker volumes, images, logs, and cache files.

    Examples:
        gleitzeit clean --logs        # Remove log files
        gleitzeit clean --volumes     # Remove Docker volumes
        gleitzeit clean --all         # Remove everything
        gleitzeit clean --all --force # Remove everything without confirmation
    """
    if all:
        volumes = images = logs = cache = True

    if not any([volumes, images, logs, cache]):
        click.echo("ℹ️  No cleanup options specified. Use --help to see available options.")
        return

    # Check if services are running
    mode = detect_running_mode()
    if mode and not force:
        click.echo("⚠️  Services are currently running")
        click.echo("   Stop services first: gleitzeit stop")
        click.echo("   Or use --force to clean anyway")
        return

    # Confirm cleanup
    if not force:
        items_to_clean = []
        if volumes:
            items_to_clean.append("Docker volumes")
        if images:
            items_to_clean.append("Docker images")
        if logs:
            items_to_clean.append("log files")
        if cache:
            items_to_clean.append("cache files")

        click.echo(f"🗑️  This will remove: {', '.join(items_to_clean)}")
        if not click.confirm("   Continue?"):
            click.echo("   Cleanup cancelled")
            return

    # Perform cleanup
    success = True

    if volumes:
        success = clean_docker_volumes() and success

    if images:
        success = clean_docker_images() and success

    if logs:
        success = clean_log_files() and success

    if cache:
        success = clean_cache_files() and success

    if success:
        click.echo("✅ Cleanup completed successfully")
    else:
        click.echo("⚠️  Some cleanup operations failed. Check messages above.")


def clean_docker_volumes() -> bool:
    """Remove Docker volumes"""
    compose_file = Path("docker-compose-proper.yml")

    if not compose_file.exists():
        click.echo("📁 No Docker compose file found, skipping volume cleanup")
        return True

    click.echo("🗑️  Removing Docker volumes...")

    try:
        # First try docker-compose down with volumes
        result = subprocess.run(
            ["docker-compose", "-f", str(compose_file), "down", "-v"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            click.echo("   ✓ Docker volumes removed")
            return True
        else:
            # Fallback to direct volume removal
            # List volumes with gleitzeit prefix
            list_result = subprocess.run(
                ["docker", "volume", "ls", "-q", "--filter", "name=gleitzeit"],
                capture_output=True,
                text=True
            )

            if list_result.returncode == 0 and list_result.stdout:
                volumes = list_result.stdout.strip().split('\n')
                removed_count = 0

                for volume in volumes:
                    if volume:
                        remove_result = subprocess.run(
                            ["docker", "volume", "rm", volume],
                            capture_output=True
                        )
                        if remove_result.returncode == 0:
                            removed_count += 1

                if removed_count > 0:
                    click.echo(f"   ✓ Removed {removed_count} Docker volumes")
                else:
                    click.echo("   No Docker volumes to remove")
                return True
            else:
                click.echo("   No Docker volumes found")
                return True

    except subprocess.TimeoutExpired:
        click.echo("   ✗ Volume removal timed out")
        return False
    except FileNotFoundError:
        click.echo("   ✗ Docker or docker-compose not found")
        return False
    except Exception as e:
        click.echo(f"   ✗ Error removing volumes: {e}")
        return False


def clean_docker_images() -> bool:
    """Remove Docker images"""
    compose_file = Path("docker-compose-proper.yml")

    if not compose_file.exists():
        click.echo("📁 No Docker compose file found, skipping image cleanup")
        return True

    click.echo("🗑️  Removing Docker images...")

    try:
        # Get list of images used in docker-compose
        result = subprocess.run(
            ["docker-compose", "-f", str(compose_file), "config", "--images"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout:
            images = result.stdout.strip().split('\n')
            removed_count = 0

            for image in images:
                if image and ('gleitzeit' in image or image.startswith('gleitzeit')):
                    # Remove the image
                    remove_result = subprocess.run(
                        ["docker", "rmi", image, "-f"],
                        capture_output=True
                    )
                    if remove_result.returncode == 0:
                        removed_count += 1
                        click.echo(f"   ✓ Removed image: {image}")

            if removed_count == 0:
                click.echo("   No Docker images to remove")
            else:
                click.echo(f"   ✓ Removed {removed_count} Docker images")

            return True

    except subprocess.TimeoutExpired:
        click.echo("   ✗ Image removal timed out")
        return False
    except FileNotFoundError:
        click.echo("   ✗ Docker or docker-compose not found")
        return False
    except Exception as e:
        click.echo(f"   ✗ Error removing images: {e}")
        return False

    return True


def clean_log_files() -> bool:
    """Remove log files"""
    log_dir = Path("logs")

    if not log_dir.exists():
        click.echo("📁 No logs directory found")
        return True

    click.echo("🗑️  Removing log files...")

    try:
        # Count files before removal
        log_files = list(log_dir.glob("*"))
        file_count = len(log_files)

        if file_count == 0:
            click.echo("   No log files to remove")
            return True

        # Remove all files in logs directory
        for log_file in log_files:
            try:
                if log_file.is_file():
                    log_file.unlink()
                elif log_file.is_dir():
                    shutil.rmtree(log_file)
            except Exception as e:
                click.echo(f"   ✗ Failed to remove {log_file.name}: {e}")

        # Count remaining files
        remaining = len(list(log_dir.glob("*")))
        removed = file_count - remaining

        if removed > 0:
            click.echo(f"   ✓ Removed {removed} log files")

        if remaining > 0:
            click.echo(f"   ⚠️ {remaining} files could not be removed")

        return remaining == 0

    except Exception as e:
        click.echo(f"   ✗ Error removing log files: {e}")
        return False


def clean_cache_files() -> bool:
    """Remove cache files"""
    cache_locations = [
        Path("__pycache__"),
        Path(".pytest_cache"),
        Path(".mypy_cache"),
        Path(".ruff_cache"),
    ]

    # Find all __pycache__ directories
    pycache_dirs: List[Path] = []
    for root_dir in [Path("."), Path("src")]:
        if root_dir.exists():
            pycache_dirs.extend(root_dir.rglob("__pycache__"))

    all_cache_dirs = cache_locations + pycache_dirs
    existing_dirs = [d for d in all_cache_dirs if d.exists()]

    if not existing_dirs:
        click.echo("📁 No cache directories found")
        return True

    click.echo("🗑️  Removing cache files...")

    removed_count = 0
    for cache_dir in existing_dirs:
        try:
            shutil.rmtree(cache_dir)
            removed_count += 1
        except Exception as e:
            click.echo(f"   ✗ Failed to remove {cache_dir}: {e}")

    if removed_count > 0:
        click.echo(f"   ✓ Removed {removed_count} cache directories")

    # Also clean .pyc files
    pyc_files = []
    for root_dir in [Path("."), Path("src")]:
        if root_dir.exists():
            pyc_files.extend(root_dir.rglob("*.pyc"))
            pyc_files.extend(root_dir.rglob("*.pyo"))

    if pyc_files:
        pyc_removed = 0
        for pyc_file in pyc_files:
            try:
                pyc_file.unlink()
                pyc_removed += 1
            except Exception:
                pass

        if pyc_removed > 0:
            click.echo(f"   ✓ Removed {pyc_removed} compiled Python files")

    return True


def get_disk_usage_stats() -> dict:
    """Get disk usage statistics for Gleitzeit resources"""
    stats = {
        'logs': 0,
        'docker_volumes': 0,
        'docker_images': 0,
        'cache': 0
    }

    # Calculate log files size
    log_dir = Path("logs")
    if log_dir.exists():
        for item in log_dir.rglob("*"):
            if item.is_file():
                stats['logs'] += item.stat().st_size

    # Calculate cache size
    cache_dirs = [
        Path("__pycache__"),
        Path(".pytest_cache"),
        Path(".mypy_cache"),
        Path(".ruff_cache"),
    ]
    for cache_dir in cache_dirs:
        if cache_dir.exists():
            for item in cache_dir.rglob("*"):
                if item.is_file():
                    stats['cache'] += item.stat().st_size

    # Get Docker stats (if available)
    try:
        # Get volume sizes
        result = subprocess.run(
            ["docker", "system", "df", "-v", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            # Parse Docker stats (implementation depends on Docker version)
    except Exception:
        pass

    return stats