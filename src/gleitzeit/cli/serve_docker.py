"""
Docker-based serve command for Gleitzeit

This implementation uses Docker Compose to manage services, avoiding the
subprocess deadlock issue in the native ProcessOrchestrator.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
import click
import yaml
import json
import time


class DockerOrchestrator:
    """Orchestrates Gleitzeit services using Docker Compose"""

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path.cwd()
        self.compose_file = self.project_root / "docker-compose-proper.yml"

    def check_docker(self) -> bool:
        """Check if Docker is available and running"""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return False

            # Check if daemon is running
            result = subprocess.run(
                ["docker", "ps"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def check_compose_file(self) -> bool:
        """Check if docker-compose file exists"""
        return self.compose_file.exists()

    def generate_compose_file(self, config: dict) -> None:
        """Generate docker-compose-proper.yml from gleitzeit.yaml config"""
        compose = {
            "version": "3.8",
            "networks": {
                "gleitzeit": {
                    "driver": "bridge",
                    "name": "gleitzeit_network"
                }
            },
            "volumes": {
                "redis-data": {"name": "gleitzeit_redis_data"},
                "logs": {"name": "gleitzeit_logs"}
            },
            "services": {}
        }

        # Redis service
        compose["services"]["redis"] = {
            "image": "redis:7-alpine",
            "container_name": "gleitzeit_redis",
            "ports": ["6379:6379"],
            "networks": ["gleitzeit"],
            "healthcheck": {
                "test": ["CMD", "redis-cli", "ping"],
                "interval": "10s",
                "timeout": "3s",
                "retries": 3
            },
            "restart": "unless-stopped",
            "volumes": ["redis-data:/data"],
            "command": "redis-server --appendonly yes"
        }

        # API service
        api_config = config.get("serve", {}).get("api", {})
        compose["services"]["api"] = {
            "build": {
                "context": ".",
                "dockerfile": "Dockerfile.api"
            },
            "container_name": "gleitzeit_api",
            "ports": [f"{api_config.get('port', 8000)}:8000"],
            "environment": [
                "REDIS_URL=redis://redis:6379",
                "REDIS_CLUSTER_NODES=redis:6379",  # Critical for workers!
                "LOG_LEVEL=INFO",
                "GLEITZEIT_AUTO_LOGIN=true"
            ],
            "depends_on": {
                "redis": {"condition": "service_healthy"}
            },
            "networks": ["gleitzeit"],
            "restart": "unless-stopped",
            "volumes": [
                "logs:/app/logs",
                "./gleitzeit.yaml:/app/gleitzeit.yaml:ro"
            ]
        }

        # UI service if enabled
        ui_config = config.get("serve", {}).get("ui", {})
        if ui_config.get("enabled", True):
            compose["services"]["ui"] = {
                "build": {
                    "context": ".",
                    "dockerfile": "Dockerfile.ui"
                },
                "container_name": "gleitzeit_ui",
                "ports": [f"{ui_config.get('port', 8004)}:8004"],
                "environment": [
                    "REDIS_URL=redis://redis:6379",
                    "REDIS_CLUSTER_NODES=redis:6379",
                    "API_URL=http://api:8000",
                    "LOG_LEVEL=INFO"
                ],
                "depends_on": ["api"],
                "networks": ["gleitzeit"],
                "restart": "unless-stopped",
                "volumes": [
                    "logs:/app/logs",
                    "./gleitzeit.yaml:/app/gleitzeit.yaml:ro"
                ]
            }

        # Add workers from config
        workers = config.get("workers", [])
        for idx, worker_config in enumerate(workers):
            worker_type = worker_config.get("worker_type")
            worker_class = worker_config.get("worker_class")
            count = worker_config.get("count", 1)

            for i in range(count):
                service_name = f"worker-{worker_type}-{i+1}"
                compose["services"][service_name] = {
                    "build": {
                        "context": ".",
                        "dockerfile": "Dockerfile.worker"
                    },
                    "command": [
                        "python", "-m", "gleitzeit.workers.runner",
                        "--worker-class", worker_class,
                        "--worker-id", f"{worker_type}-{i+1}",
                        "--worker-type", worker_type,
                        "--redis-url", "redis://redis:6379",
                        "--shards", "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15",
                        "--max-concurrent", str(worker_config.get("max_concurrent", 10)),
                        "--batch-size", str(worker_config.get("batch_size", 10)),
                        "--block-timeout", str(worker_config.get("block_timeout", 5000))
                    ],
                    "environment": [
                        "REDIS_URL=redis://redis:6379",
                        "REDIS_CLUSTER_NODES=redis:6379",  # CRITICAL!
                        "LOG_LEVEL=INFO"
                    ],
                    "depends_on": {
                        "redis": {"condition": "service_healthy"}
                    },
                    "networks": ["gleitzeit"],
                    "restart": "unless-stopped",
                    "volumes": [
                        "logs:/app/logs",
                        "./gleitzeit.yaml:/app/gleitzeit.yaml:ro"
                    ]
                }

        # Write compose file
        with open(self.compose_file, 'w') as f:
            yaml.dump(compose, f, default_flow_style=False, sort_keys=False)

        click.echo(f"✅ Generated {self.compose_file}")

    def start_services(self, detached: bool = True, build: bool = False) -> bool:
        """Start all services using docker-compose"""
        cmd = ["docker-compose", "-f", str(self.compose_file)]

        if build:
            # Build images first
            click.echo("🔨 Building Docker images...")
            result = subprocess.run(cmd + ["build"], capture_output=True, text=True)
            if result.returncode != 0:
                click.echo(f"❌ Build failed: {result.stderr}")
                return False

        # Start services
        click.echo("🚀 Starting services with Docker...")
        up_cmd = cmd + ["up"]
        if detached:
            up_cmd.append("-d")

        result = subprocess.run(up_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            click.echo(f"❌ Failed to start services: {result.stderr}")
            return False

        # Wait for services to be healthy
        click.echo("⏳ Waiting for services to be healthy...")
        time.sleep(5)

        # Check status
        result = subprocess.run(cmd + ["ps"], capture_output=True, text=True)
        click.echo(result.stdout)

        click.echo("✅ All services started successfully!")
        click.echo("   API: http://localhost:8000")
        click.echo("   UI:  http://localhost:8004")
        click.echo("   Redis: localhost:6379")
        return True

    def stop_services(self) -> bool:
        """Stop all services"""
        cmd = ["docker-compose", "-f", str(self.compose_file), "down"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            click.echo(f"❌ Failed to stop services: {result.stderr}")
            return False
        click.echo("✅ All services stopped")
        return True

    def get_status(self) -> str:
        """Get status of all services"""
        cmd = ["docker-compose", "-f", str(self.compose_file), "ps", "--format", "table"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout

    def view_logs(self, service: str = None, follow: bool = False, tail: int = None) -> None:
        """View service logs"""
        cmd = ["docker-compose", "-f", str(self.compose_file), "logs"]
        if follow:
            cmd.append("-f")
        if tail:
            cmd.extend(["--tail", str(tail)])
        if service:
            cmd.append(service)

        subprocess.run(cmd)


def serve_with_docker(
    config_file: str = "gleitzeit.yaml",
    host: str = "0.0.0.0",
    api_port: int = None,
    ui_port: int = None,
    dev_mode: bool = False,
    restart: bool = False,
    build: bool = False,
    no_ui: bool = False
) -> None:
    """Start Gleitzeit services using Docker"""

    orchestrator = DockerOrchestrator()

    # Check Docker availability
    if not orchestrator.check_docker():
        click.echo("❌ Docker is not available or not running")
        click.echo("Please ensure Docker is installed and running")
        click.echo("Visit https://docs.docker.com/get-docker/ for installation")
        sys.exit(1)

    # Load config
    config_path = Path(config_file)
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)
    else:
        click.echo(f"⚠️  Config file {config_file} not found, using defaults")
        config = {}

    # Override ports if specified
    if api_port:
        config.setdefault("serve", {}).setdefault("api", {})["port"] = api_port
    if ui_port:
        config.setdefault("serve", {}).setdefault("ui", {})["port"] = ui_port
    if no_ui:
        config.setdefault("serve", {}).setdefault("ui", {})["enabled"] = False

    # Generate or check compose file
    if not orchestrator.check_compose_file() or restart:
        click.echo("📝 Generating docker-compose configuration...")
        orchestrator.generate_compose_file(config)

    # Stop existing services if restart requested
    if restart:
        click.echo("🔄 Restarting services...")
        orchestrator.stop_services()

    # Start services
    if orchestrator.start_services(detached=True, build=build):
        click.echo("\n✨ Gleitzeit is running with Docker!")
        click.echo("\nTo view logs: docker-compose -f docker-compose-proper.yml logs -f")
        click.echo("To stop: docker-compose -f docker-compose-proper.yml down")
    else:
        sys.exit(1)


def fallback_to_native_serve():
    """Fallback to native serve implementation (has subprocess bug)"""
    click.echo("⚠️  Docker not available, falling back to native implementation")
    click.echo("⚠️  WARNING: Native implementation has subprocess deadlock issues!")

    # Import the original serve implementation
    from .serve import serve_command
    serve_command()