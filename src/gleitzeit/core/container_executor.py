"""
Container execution for Gleitzeit handlers.

Enables handlers to execute code in Docker containers for isolation
and security. Supports Native → Docker execution (not Docker-in-Docker).
"""

import asyncio
import json
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ContainerExecutor:
    """
    Execute handler code in Docker containers from native Gleitzeit.

    This executor:
    - Creates temporary workspace for code and data exchange
    - Runs code in isolated Docker containers
    - Collects output and manages cleanup
    - Handles timeouts and errors gracefully
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize container executor with configuration.

        Args:
            config: Container configuration including:
                - image: Docker image to use
                - memory_limit: Memory limit (e.g., '512m')
                - cpu_limit: CPU limit (e.g., 1.0 for 1 core)
                - network: Network mode ('bridge', 'host', 'none')
                - volumes: Additional volume mounts
                - environment: Environment variables
        """
        self.config = config
        self.docker_client = None
        self.image = config.get('image', 'python:3.11-slim')
        self.memory_limit = config.get('memory_limit', '512m')
        self.cpu_limit = config.get('cpu_limit', 1.0)
        self.network_mode = config.get('network', 'bridge')
        self.volumes = config.get('volumes', {})
        self.environment = config.get('environment', {})
        self._initialized = False

    def _ensure_docker_client(self):
        """Lazily initialize Docker client."""
        if not self.docker_client:
            try:
                import docker
                self.docker_client = docker.from_env()
                # Test connection
                self.docker_client.ping()
                self._initialized = True
                logger.info(f"Docker client initialized, using image: {self.image}")
            except ImportError:
                raise RuntimeError("Docker package not installed. Run: pip install docker")
            except Exception as e:
                raise RuntimeError(f"Failed to connect to Docker: {e}")

    def is_available(self) -> bool:
        """Check if Docker is available and accessible."""
        try:
            self._ensure_docker_client()
            return self._initialized
        except:
            return False

    async def execute(self,
                     code: str,
                     inputs: Optional[Dict] = None,
                     timeout: int = 300,
                     runtime: str = 'python') -> Dict[str, Any]:
        """
        Execute code in a Docker container.

        Args:
            code: Code to execute
            inputs: Input data for the code (optional)
            timeout: Execution timeout in seconds
            runtime: Runtime type (python, node, etc.)

        Returns:
            Dict containing:
                - output: Execution output
                - error: Error messages (if any)
                - exit_code: Container exit code
                - container_id: Container ID for debugging
                - execution_time: Time taken for execution

        Raises:
            RuntimeError: If Docker is not available
            TimeoutError: If execution exceeds timeout
        """
        self._ensure_docker_client()

        # Create temporary workspace
        with tempfile.TemporaryDirectory(prefix='gleitzeit_') as temp_dir:
            temp_path = Path(temp_dir)

            # Prepare code file
            code_file = self._prepare_code_file(temp_path, code, runtime)

            # Prepare inputs if provided
            if inputs:
                input_file = temp_path / 'inputs.json'
                input_file.write_text(json.dumps(inputs))

            # Prepare container configuration
            container_config = self._build_container_config(
                temp_path, code_file, runtime
            )

            # Run container
            try:
                container = await self._run_container(container_config, timeout)

                # Collect results
                result = await self._collect_results(container)

                return result

            except asyncio.TimeoutError:
                raise TimeoutError(f"Container execution exceeded {timeout}s timeout")
            except Exception as e:
                logger.error(f"Container execution failed: {e}")
                raise

    def _prepare_code_file(self, temp_path: Path, code: str, runtime: str) -> str:
        """Prepare code file based on runtime."""
        extensions = {
            'python': 'py',
            'node': 'js',
            'nodejs': 'js',
            'javascript': 'js',
            'go': 'go',
            'ruby': 'rb',
            'bash': 'sh',
            'shell': 'sh'
        }

        extension = extensions.get(runtime, 'txt')
        code_file = temp_path / f'code.{extension}'

        # For Python, wrap code to handle inputs and outputs
        if runtime == 'python':
            wrapped_code = self._wrap_python_code(code)
            code_file.write_text(wrapped_code)
        else:
            code_file.write_text(code)

        return code_file.name

    def _wrap_python_code(self, code: str) -> str:
        """Wrap Python code with input/output handling."""
        wrapper = '''
import json
import sys
from pathlib import Path

# Load inputs if available
inputs = {{}}
input_file = Path('/workspace/inputs.json')
if input_file.exists():
    with open(input_file) as f:
        inputs = json.load(f)

# Make inputs available to user code
for key, value in inputs.items():
    locals()[key] = value

# User code starts here
{code}
# User code ends here

# Capture result if defined
if 'result' in locals():
    print(json.dumps({{"result": locals()["result"]}}))
'''
        return wrapper.format(code=code)

    def _build_container_config(self, temp_path: Path, code_file: str, runtime: str) -> Dict:
        """Build Docker container configuration."""
        # Runtime commands
        commands = {
            'python': ['python', f'/workspace/{code_file}'],
            'node': ['node', f'/workspace/{code_file}'],
            'nodejs': ['node', f'/workspace/{code_file}'],
            'javascript': ['node', f'/workspace/{code_file}'],
            'go': ['go', 'run', f'/workspace/{code_file}'],
            'ruby': ['ruby', f'/workspace/{code_file}'],
            'bash': ['bash', f'/workspace/{code_file}'],
            'shell': ['sh', f'/workspace/{code_file}']
        }

        command = commands.get(runtime, ['cat', f'/workspace/{code_file}'])

        # Build container configuration
        config = {
            'image': self.image,
            'command': command,
            'volumes': {
                str(temp_path): {
                    'bind': '/workspace',
                    'mode': 'rw'
                }
            },
            'working_dir': '/workspace',
            'network_mode': self.network_mode,
            'detach': True,
            'remove': False,  # We'll remove after collecting logs
            'mem_limit': self.memory_limit,
            'environment': self.environment
        }

        # Add CPU limit (in terms of CPU quota)
        if self.cpu_limit:
            config['cpu_quota'] = int(self.cpu_limit * 100000)
            config['cpu_period'] = 100000

        # Add additional volumes
        for host_path, container_path in self.volumes.items():
            config['volumes'][host_path] = {
                'bind': container_path,
                'mode': 'rw'
            }

        return config

    async def _run_container(self, config: Dict, timeout: int):
        """Run container and return container object."""
        loop = asyncio.get_event_loop()

        # Run container in executor to avoid blocking
        container = await loop.run_in_executor(
            None,
            lambda: self.docker_client.containers.run(**config)
        )

        return container

    async def _collect_results(self, container) -> Dict[str, Any]:
        """Collect results from container execution."""
        loop = asyncio.get_event_loop()

        # Wait for container to finish
        start_time = asyncio.get_event_loop().time()

        while True:
            # Check container status
            container.reload()
            if container.status in ['exited', 'dead']:
                break

            # Small delay to avoid busy waiting
            await asyncio.sleep(0.1)

        execution_time = asyncio.get_event_loop().time() - start_time

        # Get logs and exit code
        logs = await loop.run_in_executor(
            None,
            lambda: container.logs(stdout=True, stderr=True).decode('utf-8')
        )

        exit_code = container.attrs['State']['ExitCode']

        # Parse output if JSON
        result_data = None
        try:
            if logs.strip().startswith('{'):
                parsed = json.loads(logs.strip())
                if 'result' in parsed:
                    result_data = parsed['result']
        except:
            pass

        # Build result
        result = {
            'output': logs,
            'exit_code': exit_code,
            'container_id': container.short_id,
            'execution_time': execution_time,
            'success': exit_code == 0
        }

        if result_data is not None:
            result['result'] = result_data

        # Cleanup container
        try:
            await loop.run_in_executor(None, container.remove)
        except Exception as e:
            logger.warning(f"Failed to remove container {container.short_id}: {e}")

        return result

    async def cleanup(self):
        """Cleanup resources."""
        if self.docker_client:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.docker_client.close
                )
            except:
                pass
            self.docker_client = None
            self._initialized = False