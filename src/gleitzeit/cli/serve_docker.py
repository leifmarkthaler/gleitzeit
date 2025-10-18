"""
Docker-based serve command for Gleitzeit

This implementation uses Docker Compose to manage services, avoiding the
subprocess deadlock issue in the native ProcessOrchestrator.
"""

import os
import sys
import subprocess
import shutil
import socket
from pathlib import Path
import click
import yaml
import json
import time
import hashlib
import uuid
import importlib.resources


def check_redis_running(config: dict) -> tuple[bool, str, int]:
    """Check if Redis is running based on gleitzeit.yaml config

    Returns:
        tuple: (is_running, host, port)
    """
    redis_config = config.get("redis", {})
    if not redis_config:
        raise ValueError("Redis configuration missing from gleitzeit.yaml")

    if redis_config.get("mode") == "single":
        single_node = redis_config.get("single_node", {})
        if not single_node:
            raise ValueError("Redis single_node configuration missing from gleitzeit.yaml")

        redis_host = single_node.get("host")
        redis_port = single_node.get("port")

        if not redis_host or not redis_port:
            raise ValueError("Redis host or port missing from gleitzeit.yaml redis.single_node configuration")

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex((redis_host, redis_port))
                return result == 0, redis_host, redis_port
        except (socket.error, socket.gaierror):
            return False, redis_host, redis_port
    else:
        raise ValueError(f"Unsupported Redis mode '{redis_config.get('mode')}' in gleitzeit.yaml. Only 'single' mode is supported.")


def generate_instance_id() -> str:
    """Generate a unique instance ID using UUID"""
    # Simple UUID-based naming for true uniqueness
    return str(uuid.uuid4())[:8]


class DockerOrchestrator:
    """Orchestrates Gleitzeit services using Docker Compose"""

    def __init__(self, project_root: Path = None, instance_id: str = None):
        self.project_root = project_root or Path.cwd()
        self.instance_id = instance_id or "default"
        # Generate instance-specific compose file name
        if self.instance_id == "default":
            self.compose_file = self.project_root / "docker-compose-gleitzeit.yml"
        else:
            self.compose_file = self.project_root / f"docker-compose-gleitzeit-{self.instance_id}.yml"

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

    def copy_dockerfiles_from_package(self) -> None:
        """Copy Dockerfile templates from package to project root"""
        dockerfile_names = ["Dockerfile.api", "Dockerfile.ui", "Dockerfile.base", "Dockerfile.worker"]

        try:
            # For Python 3.9+
            if sys.version_info >= (3, 9):
                from importlib.resources import files
                docker_pkg = files('gleitzeit.docker')

                for dockerfile in dockerfile_names:
                    source = docker_pkg.joinpath(dockerfile)
                    dest = self.project_root / dockerfile

                    # Read from package and write to destination
                    content = source.read_text()
                    dest.write_text(content)
            else:
                # Fallback for Python 3.8
                import pkg_resources
                for dockerfile in dockerfile_names:
                    content = pkg_resources.resource_string('gleitzeit.docker', dockerfile).decode('utf-8')
                    dest = self.project_root / dockerfile
                    dest.write_text(content)

        except Exception as e:
            click.echo(f"⚠️  Warning: Could not copy Dockerfiles from package: {e}")
            click.echo("ℹ️  Assuming Dockerfiles exist in current directory")

    def generate_compose_file(self, config: dict, api_only: bool = False, workers_only: bool = False, redis_url: str = None, isolated: bool = False) -> None:
        """Generate docker-compose-proper.yml from gleitzeit.yaml config"""
        # Copy Dockerfiles from package to project root
        self.copy_dockerfiles_from_package()

        # Import ConfigurationManager for proper Redis URL handling
        from ..core.config_manager import ConfigurationManager
        config_manager = ConfigurationManager(str(self.project_root / "gleitzeit.yaml"), {})

        # Network strategy:
        # - Shared mode (default): Use shared network "gleitzeit_network" for worker collaboration
        # - Isolated mode: Use instance-specific network for complete isolation
        if isolated:
            network_name = f"gleitzeit_network_{self.instance_id}" if self.instance_id != "default" else "gleitzeit_network"
            use_external_network = False
            click.echo(f"🔒 Using isolated network '{network_name}'")
            click.echo("   ⚠️  This instance cannot share workers with other instances")
        else:
            network_name = "gleitzeit_network"
            use_external_network = True
            click.echo(f"🔗 Using shared network '{network_name}' for multi-instance deployment")
            click.echo("   ✅ This instance can share workers with other instances")

        compose = {
            "version": "3.8",
            "networks": {
                "gleitzeit": {
                    "name": network_name
                }
            },
            "volumes": {
                "redis-data": {"name": f"gleitzeit_redis_data_{self.instance_id}"},
                "logs": {"name": f"gleitzeit_logs_{self.instance_id}"}
            },
            "services": {}
        }

        # Configure network based on mode
        if use_external_network:
            # For shared deployments, ensure network exists and mark as external
            result = subprocess.run(
                ["docker", "network", "inspect", network_name],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                # Network doesn't exist, create it
                click.echo(f"📡 Creating shared network '{network_name}'...")
                subprocess.run(
                    ["docker", "network", "create", network_name],
                    capture_output=True,
                    text=True
                )
            compose["networks"]["gleitzeit"]["external"] = True
        else:
            # For isolated deployments, let compose manage the network
            compose["networks"]["gleitzeit"]["driver"] = "bridge"

        # External Redis support - use ConfigurationManager for proper URL handling
        if redis_url:
            redis_connection = redis_url
        else:
            # Get Redis URL using ConfigurationManager's new method
            redis_connection = config_manager.get_redis_url()

            # Parse the URL to check if we need to adjust for Docker
            import urllib.parse
            parsed = urllib.parse.urlparse(redis_connection)
            redis_host = parsed.hostname
            redis_port = parsed.port or 6379
            redis_path = parsed.path or '/'

            # If Redis is on localhost, we need to handle it differently for Docker
            if redis_host in ['localhost', '127.0.0.1']:
                # Check if we're creating a Redis container or using external Redis
                redis_running, _, _ = check_redis_running(config)
                if redis_running:
                    # External Redis on host machine - use host.docker.internal
                    redis_connection = f"redis://host.docker.internal:{redis_port}{redis_path}"
                    click.echo(f"🔗 Converting localhost Redis to host.docker.internal for Docker containers")
                else:
                    # Will create Redis container - use container name
                    redis_connection = f"redis://redis:{redis_port}{redis_path}"

        # Only create Redis container if using internal Redis
        if not redis_url:
            # Check if external Redis is running
            redis_running, redis_host, redis_port = check_redis_running(config)

            if not redis_running:
                # Need to create Redis container
                redis_container_name = f"gleitzeit_redis_{self.instance_id}" if self.instance_id != "default" else "gleitzeit_redis"
                compose["services"]["redis"] = {
                "image": "redis:7-alpine",
                "container_name": redis_container_name,
                "ports": [f"{redis_port}:{redis_port}"],
                "networks": ["gleitzeit"],
                "healthcheck": {
                    "test": ["CMD", "redis-cli", "ping"],
                    "interval": "10s",
                    "timeout": "3s",
                    "retries": 3
                },
                "restart": "unless-stopped",
                "volumes": ["redis-data:/data"],
                "command": f"redis-server --port {redis_port} --appendonly yes"
            }

        # API/UI services (skip if workers-only)
        if not workers_only:
            api_config = config.get("serve", {}).get("api", {})
            api_port = api_config.get("port", 8000)

            api_container_name = f"gleitzeit_api_{self.instance_id}" if self.instance_id != "default" else "gleitzeit_api"
            api_hostname = f"gleitzeit-api-{self.instance_id}" if self.instance_id != "default" else "gleitzeit-api"

            compose["services"]["api"] = {
                "build": {
                    "context": ".",
                    "dockerfile": "Dockerfile.api"
                },
                "container_name": api_container_name,
                "hostname": api_hostname,  # Consistent hostname for service discovery
                "ports": [f"{api_port}:{api_port}"],
                "environment": [
                    f"REDIS_URL={redis_connection}",
                    "SERVICE_TYPE=api",
                    f"PORT={api_port}",
                    "LOG_LEVEL=INFO",
                    "GLEITZEIT_AUTO_LOGIN=true"
                ],
                "networks": ["gleitzeit"],
                "restart": "unless-stopped",
                "volumes": [
                    "logs:/app/logs",
                    "./gleitzeit.yaml:/app/gleitzeit.yaml:ro"
                ]
            }

            # Add depends_on only if we're creating a Redis container
            if "redis" in compose["services"]:
                compose["services"]["api"]["depends_on"] = {
                    "redis": {"condition": "service_healthy"}
                }

            # UI service if enabled
            ui_config = config.get("serve", {}).get("ui", {})
            if ui_config.get("enabled", True):
                ui_port = ui_config.get("port", 8004)

                ui_container_name = f"gleitzeit_ui_{self.instance_id}" if self.instance_id != "default" else "gleitzeit_ui"
                ui_hostname = f"gleitzeit-ui-{self.instance_id}" if self.instance_id != "default" else "gleitzeit-ui"

                compose["services"]["ui"] = {
                    "build": {
                        "context": ".",
                        "dockerfile": "Dockerfile.ui"
                    },
                    "container_name": ui_container_name,
                    "hostname": ui_hostname,
                    "ports": [f"{ui_port}:{ui_port}"],
                    "environment": [
                        f"REDIS_URL={redis_connection}",
                        "SERVICE_TYPE=ui",
                        f"PORT={ui_port}",
                        f"API_URL=http://{api_hostname}:{api_port}"
                    ],
                    "depends_on": ["api"],
                    "networks": ["gleitzeit"],
                    "restart": "unless-stopped",
                    "volumes": [
                        "logs:/app/logs",
                        "./gleitzeit.yaml:/app/gleitzeit.yaml:ro"
                    ]
                }

        # Worker services (skip if api-only)
        if not api_only:
            workers = config.get("workers", [])
            total_shards = 16

            for idx, worker_config in enumerate(workers):
                worker_type = worker_config.get("worker_type")
                worker_class = worker_config.get("worker_class")
                count = worker_config.get("count", 1)

                # Distribute shards evenly across workers of this type
                # This enables true horizontal scaling
                for i in range(count):
                    # Calculate shard assignment for this specific worker instance
                    shards_per_worker = total_shards // count
                    remainder = total_shards % count

                    # Each worker gets base share, first `remainder` workers get +1 shard
                    start_shard = i * shards_per_worker + min(i, remainder)
                    end_shard = start_shard + shards_per_worker + (1 if i < remainder else 0)
                    assigned_shards = list(range(start_shard, end_shard))
                    shards_str = ",".join(str(s) for s in assigned_shards)

                    service_name = f"worker-{worker_type}-{i+1}"
                    container_name = f"gleitzeit_{service_name}_{self.instance_id}" if self.instance_id != "default" else f"gleitzeit_{service_name}"
                    hostname = f"gleitzeit-{service_name}-{self.instance_id}" if self.instance_id != "default" else f"gleitzeit-{service_name}"

                    compose["services"][service_name] = {
                        "build": {
                            "context": ".",
                            "dockerfile": "Dockerfile.worker"
                        },
                        "container_name": container_name,
                        "hostname": hostname,
                        "command": [
                            "python", "-m", "gleitzeit.workers.runner",
                            "--worker-class", worker_class,
                            "--worker-id", f"{worker_type}-{i+1}",
                            "--worker-type", worker_type,
                            "--redis-url", redis_connection,
                            "--shards", shards_str,  # Distributed shard assignment
                            "--max-concurrent", str(worker_config.get("max_concurrent", 10)),
                            "--batch-size", str(worker_config.get("batch_size", 10)),
                            "--block-timeout", str(worker_config.get("block_timeout", 5000))
                        ],
                        "environment": [
                            f"REDIS_URL={redis_connection}",
                            f"SERVICE_TYPE={service_name}",
                            "LOG_LEVEL=INFO"
                        ],
                        "networks": ["gleitzeit"],
                        "restart": "unless-stopped",
                        "volumes": [
                            "logs:/app/logs",
                            "./gleitzeit.yaml:/app/gleitzeit.yaml:ro"
                        ]
                    }

                    # Add depends_on only if we're creating a Redis container
                    if "redis" in compose["services"]:
                        compose["services"][service_name]["depends_on"] = {
                            "redis": {"condition": "service_healthy"}
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
    no_ui: bool = False,
    # NEW HORIZONTAL SCALING PARAMETERS
    api_only: bool = False,
    workers_only: bool = False,
    redis_url: str = None,
    config_url: str = None,
    isolated: bool = False
) -> None:
    """Start Gleitzeit services using Docker"""

    # Generate unique instance ID
    instance_id = generate_instance_id()

    orchestrator = DockerOrchestrator(instance_id=instance_id)

    # Check Docker availability
    if not orchestrator.check_docker():
        click.echo("❌ Docker is not available or not running")
        click.echo("Please ensure Docker is installed and running")
        click.echo("Visit https://docs.docker.com/get-docker/ for installation")
        sys.exit(1)

    # Load config using ConfigurationManager (supports fallback to packaged config)
    from ..core.config_manager import ConfigurationManager
    config_path = Path(config_file)
    config_manager = ConfigurationManager(str(config_path), {})
    config = config_manager.yaml_config

    # Auto-detect external Redis if not explicitly provided
    if not redis_url:
        redis_running, redis_host, redis_port = check_redis_running(config)
        if redis_running:
            # For Docker containers accessing host Redis, we'll handle conversion in generate_compose_file
            click.echo(f"🔍 Detected running Redis at {redis_host}:{redis_port}")
            if redis_host in ['localhost', '127.0.0.1']:
                click.echo(f"🔗 Will use host.docker.internal:{redis_port} for Docker containers")
            else:
                click.echo(f"🔗 Using external Redis: redis://{redis_host}:{redis_port}")
        else:
            click.echo(f"🚫 No Redis detected at {redis_host}:{redis_port}")
            click.echo("📦 Will create Redis container with persistent storage")
            click.echo("💾 Redis data will persist in Docker volume 'gleitzeit_redis_data'")
            click.echo("ℹ️  For production scaling, consider external Redis")

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
        orchestrator.generate_compose_file(config, api_only, workers_only, redis_url, isolated)

    # Stop existing services if restart requested
    if restart:
        click.echo("🔄 Restarting services...")
        orchestrator.stop_services()

    # Start services
    if orchestrator.start_services(detached=True, build=build):
        click.echo("\n✨ Gleitzeit is running with Docker!")
        click.echo(f"   Instance: {instance_id}")
        click.echo(f"\nTo view logs: docker-compose -f {orchestrator.compose_file.name} logs -f")
        click.echo(f"To stop: docker-compose -f {orchestrator.compose_file.name} down")
        click.echo(f"Or use: gleitzeit stop")
    else:
        sys.exit(1)


def fallback_to_native_serve():
    """Fallback to native serve implementation (has subprocess bug)"""
    click.echo("⚠️  Docker not available, falling back to native implementation")
    click.echo("⚠️  WARNING: Native implementation has subprocess deadlock issues!")

    # Import the original serve implementation
    from .serve import serve_command
    serve_command()