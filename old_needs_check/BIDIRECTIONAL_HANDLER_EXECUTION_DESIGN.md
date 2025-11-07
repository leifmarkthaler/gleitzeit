# Bidirectional Mixed Handler Execution Design

## Executive Summary

Enable Gleitzeit handlers to execute in different environments regardless of how Gleitzeit itself is deployed:
- **Native Gleitzeit** can use Docker containers for specific handlers
- **Docker Gleitzeit** can execute handlers on the host machine (native)
- Full flexibility in mixing execution modes

## The Four Execution Scenarios

### Scenario 1: Native Gleitzeit → Native Handler
```
Host Machine
├── Gleitzeit (native)
└── Python Handler (subprocess on host)
```

### Scenario 2: Native Gleitzeit → Docker Handler
```
Host Machine
├── Gleitzeit (native)
└── Docker Engine
    └── Python Container (isolated execution)
```

### Scenario 3: Docker Gleitzeit → Docker Handler (same container)
```
Host Machine
└── Docker Engine
    └── Gleitzeit Container
        └── Python Handler (subprocess in container)
```

### Scenario 4: Docker Gleitzeit → Native Handler (break out!)
```
Host Machine
├── Python Handler (native execution on host)
└── Docker Engine
    └── Gleitzeit Container (calls out to host)
```

## Architecture Design

```
┌────────────────────────────────────────────────────────────┐
│                      Host Machine                           │
├────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────┐  ┌────────────────────────┐  │
│  │   Native Processes        │  │    Docker Engine       │  │
│  │  ┌──────────────────┐     │  │  ┌─────────────────┐   │  │
│  │  │ Native Handler   │◄────┼──┼──┤ Docker Gleitzeit│   │  │
│  │  │ (Python/Node/Go) │     │  │  │ (Can call host) │   │  │
│  │  └──────────────────┘     │  │  └─────────────────┘   │  │
│  │  ┌──────────────────┐     │  │  ┌─────────────────┐   │  │
│  │  │ Native Gleitzeit │─────┼──┼─►│ Docker Handler  │   │  │
│  │  │ (Can use Docker) │     │  │  │ (Python/Node)   │   │  │
│  │  └──────────────────┘     │  │  └─────────────────┘   │  │
│  └──────────────────────────┘  └────────────────────────┘  │
│                                                             │
│             ▲            Bidirectional            ▲         │
│             └──────────── Execution ──────────────┘         │
└────────────────────────────────────────────────────────────┘
```

## Implementation Components

### 1. Universal Execution Strategy

```python
# src/gleitzeit/core/execution_strategy.py

from abc import ABC, abstractmethod
from enum import Enum
import os
import docker
import subprocess
import asyncio
import json
import tempfile
from pathlib import Path

class ExecutionLocation(Enum):
    """Where the handler execution happens"""
    NATIVE_HOST = "native_host"      # On bare metal host
    DOCKER_CONTAINER = "docker_container"  # In Docker container
    SAME_PROCESS = "same_process"    # In same process as worker
    SUBPROCESS = "subprocess"         # In subprocess of worker

class DeploymentMode(Enum):
    """How Gleitzeit itself is deployed"""
    NATIVE = "native"    # Running directly on host
    DOCKER = "docker"    # Running in Docker container


class ExecutionStrategy(ABC):
    """Base class for all execution strategies"""

    @abstractmethod
    async def execute(self, code: str, runtime: str, **kwargs) -> Dict:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this execution strategy is available in current environment"""
        pass


class HostExecutionStrategy(ExecutionStrategy):
    """
    Execute on the host machine (for Docker → Native scenario).
    Uses mounted socket or SSH to communicate with host.
    """

    def __init__(self, config: Dict):
        self.config = config
        self.host_socket = config.get('host_socket', '/var/run/gleitzeit/executor.sock')
        self.host_command = config.get('host_command', '/usr/local/bin/gleitzeit-executor')

    def is_available(self) -> bool:
        """Check if we can reach the host executor"""
        # Option 1: Check for mounted socket
        if Path(self.host_socket).exists():
            return True

        # Option 2: Check for host command via mounted binary
        if Path(self.host_command).exists():
            return True

        return False

    async def execute(self, code: str, runtime: str, **kwargs) -> Dict:
        """Execute code on the host machine from within Docker container"""

        # Create temporary files in shared volume
        shared_dir = Path('/host-shared')  # Must be mounted from host

        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix=f'.{runtime}',
            dir=shared_dir,
            delete=False
        ) as f:
            f.write(code)
            code_path = f.name

        try:
            # Option 1: Use socket communication
            if Path(self.host_socket).exists():
                return await self._execute_via_socket(code_path, runtime, **kwargs)

            # Option 2: Use mounted binary
            elif Path(self.host_command).exists():
                return await self._execute_via_binary(code_path, runtime, **kwargs)

            else:
                raise RuntimeError("No host execution method available")

        finally:
            # Cleanup temp file
            Path(code_path).unlink(missing_ok=True)

    async def _execute_via_socket(self, code_path: str, runtime: str, **kwargs):
        """Execute via Unix socket to host executor daemon"""
        import socket
        import json

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(self.host_socket)

            # Send execution request
            request = {
                'action': 'execute',
                'runtime': runtime,
                'code_path': code_path,
                'timeout': kwargs.get('timeout', 300)
            }
            sock.send(json.dumps(request).encode())

            # Receive response
            response = sock.recv(65536).decode()
            return json.loads(response)

    async def _execute_via_binary(self, code_path: str, runtime: str, **kwargs):
        """Execute via mounted host binary"""
        cmd = [
            self.host_command,
            '--runtime', runtime,
            '--file', code_path,
            '--timeout', str(kwargs.get('timeout', 300))
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await proc.communicate()

        return {
            'output': stdout.decode(),
            'error': stderr.decode(),
            'exit_code': proc.returncode
        }


class DockerExecutionStrategy(ExecutionStrategy):
    """
    Execute in Docker container (for Native → Docker scenario).
    Creates and manages Docker containers from native process.
    """

    def __init__(self, config: Dict):
        self.config = config
        self.docker_client = None

    def is_available(self) -> bool:
        """Check if Docker is available"""
        try:
            self.docker_client = docker.from_env()
            self.docker_client.ping()
            return True
        except:
            return False

    async def execute(self, code: str, runtime: str, **kwargs) -> Dict:
        """Execute code in a Docker container from native Gleitzeit"""

        if not self.docker_client:
            self.docker_client = docker.from_env()

        # Select image based on runtime
        images = {
            'python': 'python:3.11-slim',
            'node': 'node:18-slim',
            'go': 'golang:1.21-alpine',
            'ruby': 'ruby:3.2-slim'
        }

        image = self.config.get('image', images.get(runtime, 'ubuntu:latest'))

        with tempfile.TemporaryDirectory() as temp_dir:
            # Write code to temp directory
            code_file = Path(temp_dir) / f"code.{runtime}"
            code_file.write_text(code)

            # Run container
            container = self.docker_client.containers.run(
                image=image,
                command=self._get_command(runtime, '/workspace/code'),
                volumes={temp_dir: {'bind': '/workspace', 'mode': 'rw'}},
                working_dir='/workspace',
                detach=True,
                remove=False,
                mem_limit=self.config.get('memory_limit', '512m'),
                network_mode=self.config.get('network', 'bridge')
            )

            # Wait for completion
            result = container.wait(timeout=kwargs.get('timeout', 300))
            logs = container.logs().decode()

            # Cleanup
            container.remove()

            return {
                'output': logs,
                'exit_code': result['StatusCode'],
                'container_id': container.short_id
            }

    def _get_command(self, runtime: str, code_path: str) -> List[str]:
        """Get execution command for runtime"""
        commands = {
            'python': ['python', f"{code_path}.python"],
            'node': ['node', f"{code_path}.node"],
            'go': ['go', 'run', f"{code_path}.go"],
            'ruby': ['ruby', f"{code_path}.ruby"]
        }
        return commands.get(runtime, ['sh', '-c', f"cat {code_path}"])


class SubprocessExecutionStrategy(ExecutionStrategy):
    """Execute in subprocess (same environment as worker)"""

    def __init__(self, config: Dict):
        self.config = config

    def is_available(self) -> bool:
        """Always available"""
        return True

    async def execute(self, code: str, runtime: str, **kwargs) -> Dict:
        """Execute in subprocess"""
        # Existing subprocess implementation
        pass
```

### 2. Smart Handler with Auto-Detection

```python
# src/gleitzeit/handlers/python.py

@HandlerRegistry.register
class PythonHandler(BaseHandler):
    """
    Python handler with intelligent execution mode selection.
    Can execute in Docker, native, or subprocess based on configuration
    and environment detection.
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)

        # Detect current deployment mode
        self.deployment_mode = self._detect_deployment_mode()

        # Get desired execution mode from config
        self.desired_execution = self.config.get('execution_mode', 'auto')

        # Initialize execution strategy
        self.strategy = self._select_strategy()

        logger.info(
            f"Python handler initialized: "
            f"deployment={self.deployment_mode}, "
            f"execution={self.strategy.__class__.__name__}"
        )

    def _detect_deployment_mode(self) -> DeploymentMode:
        """Detect if we're running in Docker or native"""
        # Check for Docker indicators
        if Path('/.dockerenv').exists():
            return DeploymentMode.DOCKER

        try:
            with open('/proc/self/cgroup', 'r') as f:
                if 'docker' in f.read() or 'containerd' in f.read():
                    return DeploymentMode.DOCKER
        except:
            pass

        return DeploymentMode.NATIVE

    def _select_strategy(self) -> ExecutionStrategy:
        """
        Select execution strategy based on deployment mode and configuration.

        Matrix:
        Deployment | Desired    | Strategy
        -----------|------------|------------------
        Native     | docker     | DockerExecutionStrategy
        Native     | native     | SubprocessExecutionStrategy
        Native     | auto       | SubprocessExecutionStrategy
        Docker     | docker     | SubprocessExecutionStrategy (already isolated)
        Docker     | native     | HostExecutionStrategy (break out!)
        Docker     | auto       | SubprocessExecutionStrategy
        """

        if self.desired_execution == 'auto':
            # Auto mode: use subprocess (safest default)
            return SubprocessExecutionStrategy(self.config)

        # Native Gleitzeit
        if self.deployment_mode == DeploymentMode.NATIVE:
            if self.desired_execution == 'docker':
                strategy = DockerExecutionStrategy(self.config.get('docker', {}))
                if strategy.is_available():
                    return strategy
                logger.warning("Docker not available, falling back to subprocess")
                return SubprocessExecutionStrategy(self.config)

            elif self.desired_execution == 'native':
                return SubprocessExecutionStrategy(self.config)

        # Docker Gleitzeit
        elif self.deployment_mode == DeploymentMode.DOCKER:
            if self.desired_execution == 'native':
                # Try to execute on host (requires special setup)
                strategy = HostExecutionStrategy(self.config.get('host', {}))
                if strategy.is_available():
                    logger.warning("Using host execution from Docker (security risk!)")
                    return strategy
                logger.warning("Host execution not available, falling back to subprocess")
                return SubprocessExecutionStrategy(self.config)

            elif self.desired_execution == 'docker':
                # Already in Docker, use subprocess
                logger.info("Already in Docker, using subprocess instead of nested containers")
                return SubprocessExecutionStrategy(self.config)

        # Default fallback
        return SubprocessExecutionStrategy(self.config)

    async def execute(self, task: Task) -> TaskResult:
        """Execute Python code using selected strategy"""

        try:
            code = task.params.get('code')
            inputs = task.params.get('inputs', {})
            timeout = task.params.get('timeout', 300)

            result = await self.strategy.execute(
                code=code,
                runtime='python',
                inputs=inputs,
                timeout=timeout
            )

            return self.create_result(
                task=task,
                status=TaskStatus.COMPLETED,
                result=result,
                metadata={
                    'deployment_mode': self.deployment_mode.value,
                    'execution_strategy': self.strategy.__class__.__name__
                }
            )

        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}")
            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=str(e)
            )
```

### 3. Host Executor Service (for Docker → Native)

```python
# src/gleitzeit/services/host_executor.py
"""
Host executor service that runs on the host machine
and accepts execution requests from Docker containers.
"""

import asyncio
import socket
import json
import subprocess
import tempfile
from pathlib import Path

class HostExecutorService:
    """
    Daemon that runs on host and executes code for Docker containers.
    Provides a Unix socket interface for Docker containers to request
    native execution.
    """

    def __init__(self, socket_path: str = '/var/run/gleitzeit/executor.sock'):
        self.socket_path = socket_path
        self.server = None

    async def start(self):
        """Start the executor service"""
        # Ensure socket directory exists
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)

        # Remove old socket if exists
        Path(self.socket_path).unlink(missing_ok=True)

        # Create Unix socket server
        self.server = await asyncio.start_unix_server(
            self.handle_client,
            path=self.socket_path
        )

        # Set permissions for Docker containers to access
        Path(self.socket_path).chmod(0o666)

        print(f"Host executor listening on {self.socket_path}")

        async with self.server:
            await self.server.serve_forever()

    async def handle_client(self, reader, writer):
        """Handle execution request from Docker container"""
        try:
            # Read request
            data = await reader.read(65536)
            request = json.loads(data.decode())

            # Execute based on runtime
            result = await self.execute_code(
                runtime=request['runtime'],
                code_path=request['code_path'],
                timeout=request.get('timeout', 300)
            )

            # Send response
            writer.write(json.dumps(result).encode())
            await writer.drain()

        except Exception as e:
            error_response = {'error': str(e), 'success': False}
            writer.write(json.dumps(error_response).encode())
            await writer.drain()

        finally:
            writer.close()
            await writer.wait_closed()

    async def execute_code(self, runtime: str, code_path: str, timeout: int):
        """Execute code on the host"""

        commands = {
            'python': ['python', code_path],
            'node': ['node', code_path],
            'go': ['go', 'run', code_path],
            'ruby': ['ruby', code_path],
            'bash': ['bash', code_path]
        }

        cmd = commands.get(runtime, ['sh', code_path])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout
            )

            return {
                'output': stdout.decode(),
                'error': stderr.decode(),
                'exit_code': proc.returncode,
                'success': proc.returncode == 0
            }

        except asyncio.TimeoutError:
            if proc:
                proc.kill()
            return {
                'error': f'Execution timeout ({timeout}s)',
                'success': False
            }


# Service runner
if __name__ == '__main__':
    service = HostExecutorService()
    asyncio.run(service.start())
```

### 4. Configuration for Bidirectional Execution

```yaml
# gleitzeit.yaml

handlers:
  # Python handler with flexible execution
  python:
    execution:
      mode: auto  # auto, docker, native, subprocess

      # When running Native → Docker
      docker:
        image: python:3.11-slim
        memory_limit: "512m"
        cpu_limit: 1.0
        network: bridge
        volumes:
          /tmp/gleitzeit: /workspace

      # When running Docker → Native (requires setup)
      host:
        # Option 1: Unix socket to host executor service
        host_socket: /var/run/gleitzeit/executor.sock

        # Option 2: Mounted host binary
        host_command: /host/usr/local/bin/gleitzeit-executor

        # Shared directory between Docker and host
        shared_dir: /host-shared

      # Subprocess settings (default fallback)
      subprocess:
        pool_enabled: true
        pool_min_size: 2
        pool_max_size: 10

    config:
      default_timeout: 300

  # Node.js handler
  nodejs:
    execution:
      mode: docker  # Always use Docker when available
      docker:
        image: node:18-slim
        memory_limit: "256m"

  # Ollama handler - always remote
  ollama:
    execution:
      mode: remote
    config:
      base_url: http://localhost:11434

  # Shell commands - prefer native for performance
  shell:
    execution:
      mode: native  # Run directly on host when possible
      host:
        allowed_commands: ["ls", "cat", "grep", "awk", "sed"]
```

### 5. Docker Compose Setup for Docker → Native

```yaml
# docker-compose.yml with host execution support

services:
  # Host executor service (runs on host)
  host-executor:
    image: gleitzeit-host-executor
    network_mode: host
    volumes:
      - /var/run/gleitzeit:/var/run/gleitzeit
      - /tmp/gleitzeit:/host-shared
    restart: unless-stopped
    # This actually runs on the host, not in Docker!
    # Started separately: gleitzeit-host-executor --daemon

  # Gleitzeit worker with access to host executor
  worker-task-execution:
    build:
      context: .
      dockerfile: Dockerfile.worker
    volumes:
      # Mount socket for host communication
      - /var/run/gleitzeit:/var/run/gleitzeit

      # Shared directory for file exchange
      - /tmp/gleitzeit:/host-shared

      # Optional: Mount host binaries
      - /usr/local/bin/gleitzeit-executor:/host/usr/local/bin/gleitzeit-executor:ro

    environment:
      - ALLOW_HOST_EXECUTION=true  # Security flag
      - HOST_SHARED_DIR=/host-shared
```

## Security Considerations

### Docker → Native Risks
1. **Container Escape**: Executing on host breaks container isolation
2. **Privilege Escalation**: Container code runs with host privileges
3. **File System Access**: Shared directories expose host filesystem

### Mitigation Strategies
1. **Explicit Opt-In**: Require `ALLOW_HOST_EXECUTION=true`
2. **Command Whitelist**: Limit allowed commands for host execution
3. **User Isolation**: Run host executor as unprivileged user
4. **Audit Logging**: Log all host execution requests
5. **Network Isolation**: Use Unix sockets instead of network ports

### Recommended Deployment

#### Development
- Use `mode: auto` for flexibility
- Allow Docker → Native for convenience

#### Production
- Restrict to Native → Docker only
- Disable host execution from containers
- Use subprocess mode in Docker

## Example Use Cases

### Use Case 1: Development Environment
```yaml
# Developer runs Gleitzeit natively
# Python code runs in Docker for isolation
# Ollama runs natively for GPU access

handlers:
  python:
    execution:
      mode: docker  # Isolate Python code

  ollama:
    execution:
      mode: native  # Direct GPU access
```

### Use Case 2: CI/CD Pipeline
```yaml
# Gleitzeit runs in Docker container
# Build steps run on host for cache access
# Test steps run in containers

handlers:
  build:
    execution:
      mode: native  # Access host build cache

  test:
    execution:
      mode: subprocess  # Already isolated by container
```

### Use Case 3: Mixed Workload
```yaml
# Some handlers need host resources (GPU, special hardware)
# Others need strong isolation

handlers:
  ml-training:
    execution:
      mode: native  # GPU access

  user-code:
    execution:
      mode: docker  # Untrusted code isolation
```

## Conclusion

This bidirectional design enables complete flexibility:
- **Native Gleitzeit** can use Docker for isolation
- **Docker Gleitzeit** can access host for special resources
- **Auto mode** intelligently selects the best strategy
- **Security controls** prevent unauthorized host access

The system adapts to any deployment scenario while maintaining security boundaries through explicit configuration and opt-in mechanisms.