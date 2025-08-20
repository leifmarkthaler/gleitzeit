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


@dataclass
class MCPConfig:
    """
    Configuration for an MCP (Model Context Protocol) server instance
    
    Supports multiple connection types:
    - stdio: Subprocess with stdin/stdout communication
    - websocket: WebSocket connection to remote server  
    - http: HTTP/REST API connection
    
    Attributes:
        name: Friendly name for the MCP server
        connection_type: Type of connection (stdio, websocket, http)
        command: Command to launch stdio server
        working_dir: Working directory for stdio server
        env: Environment variables for stdio server
        url: URL for network connections
        auth_token: Authentication token for network connections
        headers: HTTP headers for network connections
        auto_start: Automatically start stdio servers
        restart_on_failure: Restart server if it fails
        max_retries: Maximum connection retry attempts
        timeout: Request timeout in seconds
        health_check_interval: Health check interval in seconds
        tool_prefix: Prefix for tool names (e.g., "github.")
        advertise_tools: Whether to advertise available tools
        max_memory_mb: Memory limit for stdio servers
        max_cpu_percent: CPU limit for stdio servers
    """
    name: str = "mcp-server"
    connection_type: str = "stdio"  # stdio, websocket, http
    
    # For stdio connections
    command: Optional[List[str]] = None
    working_dir: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    
    # For network connections
    url: Optional[str] = None
    auth_token: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    
    # Behavior settings
    auto_start: bool = True
    restart_on_failure: bool = True
    max_retries: int = 3
    timeout: float = 30.0
    health_check_interval: float = 30.0
    
    # Tool configuration
    tool_prefix: Optional[str] = None  # e.g., "github." for github tools
    advertise_tools: bool = True
    
    # Resource limits (for stdio)
    max_memory_mb: Optional[int] = None
    max_cpu_percent: Optional[float] = None
    
    def validate(self) -> None:
        """Validate configuration"""
        if self.connection_type == "stdio":
            if not self.command:
                raise ValueError("stdio connection requires 'command' to be specified")
        elif self.connection_type in ["websocket", "http"]:
            if not self.url:
                raise ValueError(f"{self.connection_type} connection requires 'url' to be specified")
        else:
            raise ValueError(f"Unknown connection type: {self.connection_type}")


# Future configurations can be added here
# Examples:
# - KubernetesConfig for K8s pod management
# - LambdaConfig for AWS Lambda functions
# - VMConfig for virtual machine management