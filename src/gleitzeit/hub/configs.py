"""
Resource Configuration Classes for Gleitzeit

This module contains configuration dataclasses for various resource types
that can be managed by the hub system.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class OllamaConfig:
    """
    Configuration for an Ollama instance
    
    Attributes:
        host: Hostname or IP address for the Ollama instance
        port: Port number for the Ollama API
        models: List of models to preload
        max_concurrent: Maximum concurrent requests
        gpu_layers: Number of layers to offload to GPU
        cpu_threads: Number of CPU threads to use
        context_size: Context size for model operations
        environment: Environment variables for the process
        auto_pull_models: Automatically pull required models
        process_id: PID for managed instances
    """
    host: str = "127.0.0.1"
    port: int = 11434
    models: List[str] = field(default_factory=list)
    max_concurrent: int = 4
    gpu_layers: Optional[int] = None
    cpu_threads: Optional[int] = None
    context_size: Optional[int] = None
    environment: Dict[str, str] = field(default_factory=dict)
    auto_pull_models: bool = True
    process_id: Optional[int] = None  # For managed instances


@dataclass
class DockerConfig:
    """
    Configuration for a Docker container
    
    Attributes:
        image: Docker image to use
        name: Container name
        command: Command to run in container
        environment: Environment variables
        volumes: Volume mappings
        ports: Port mappings
        memory_limit: Memory limit (e.g., "512m")
        cpu_limit: CPU limit (number of cores)
        network_mode: Network mode (bridge, host, none)
        labels: Container labels
        restart_policy: Restart policy configuration
        auto_remove: Remove container when stopped
        detach: Run container in background
        privileged: Run in privileged mode
        user: User to run as
        working_dir: Working directory in container
        container_id: Actual Docker container ID
    """
    image: str = "python:3.11-slim"
    name: Optional[str] = None
    command: Optional[str] = None
    environment: Dict[str, str] = field(default_factory=dict)
    volumes: Dict[str, Dict[str, str]] = field(default_factory=dict)
    ports: Dict[str, int] = field(default_factory=dict)
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    network_mode: str = "bridge"
    labels: Dict[str, str] = field(default_factory=dict)
    restart_policy: Dict[str, Any] = field(default_factory=dict)
    auto_remove: bool = False
    detach: bool = True
    privileged: bool = False
    user: Optional[str] = None
    working_dir: Optional[str] = None
    container_id: Optional[str] = None  # Actual Docker container ID


# Future configurations can be added here
# Examples:
# - KubernetesConfig for K8s pod management
# - LambdaConfig for AWS Lambda functions
# - VMConfig for virtual machine management