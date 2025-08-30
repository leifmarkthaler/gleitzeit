"""
Enhanced Python Provider with Protocol Auto-Generation
Executes Python files in Docker containers or separate threads
"""

import asyncio
import logging
import json
import sys
import tempfile
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Literal
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from gleitzeit.providers.ultra_simple import UltraSimpleProvider, method
from gleitzeit.core.errors import InvalidParameterError, TaskExecutionError

logger = logging.getLogger(__name__)


class PythonProviderV2(UltraSimpleProvider):
    """
    Enhanced Python file execution provider with auto-protocol generation.
    
    Features:
    - Execute Python files (NO inline code execution for security)
    - Docker container isolation (preferred)
    - Thread-based isolation (fallback)
    - Subprocess isolation (local trusted files)
    - Automatic protocol generation
    - Comprehensive security model
    
    Security Model:
    1. Docker (preferred): Full isolation in containers
    2. Thread (fallback): Separate thread with limited scope
    3. Subprocess (trusted): Only for files in trusted directories
    """
    
    def __init__(
        self,
        provider_id: str = "python_v2",
        protocol_id: str = "python/v2",
        docker_hub: Optional[Any] = None,
        resource_manager: Optional[Any] = None,
        allow_local: bool = True,
        allow_threads: bool = True,
        trusted_dirs: Optional[List[str]] = None,
        default_docker_image: str = "python:3.11-slim",
        max_thread_workers: int = 4,
        default_timeout: int = 30,
        auto_generate_protocol: bool = True,
        **kwargs
    ):
        """
        Initialize enhanced Python provider.
        
        Args:
            provider_id: Unique provider ID
            protocol_id: Protocol identifier
            docker_hub: Optional DockerHub for container execution
            resource_manager: Optional ResourceManager for resource allocation
            allow_local: Allow local subprocess execution
            allow_threads: Allow thread-based execution
            trusted_dirs: Directories with trusted Python files
            default_docker_image: Default Docker image for containers
            max_thread_workers: Maximum thread pool workers
            default_timeout: Default execution timeout in seconds
            auto_generate_protocol: Enable protocol auto-generation
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id=protocol_id,
            auto_generate_protocol=auto_generate_protocol,
            **kwargs
        )
        
        self.docker_hub = docker_hub
        self.resource_manager = resource_manager
        self.allow_local = allow_local
        self.allow_threads = allow_threads
        self.default_docker_image = default_docker_image
        self.default_timeout = default_timeout
        
        # Set up trusted directories
        self.trusted_dirs = [Path(d).resolve() for d in (trusted_dirs or [])]
        if not self.trusted_dirs:
            self.trusted_dirs.append(Path.cwd())
        
        # Thread pool for isolated execution
        self.thread_pool = ThreadPoolExecutor(max_workers=max_thread_workers) if allow_threads else None
        
        # Track active executions
        self.active_executions: Dict[str, Dict[str, Any]] = {}
        
        logger.info(
            f"Initialized {self.__class__.__name__} with: "
            f"docker={'enabled' if docker_hub else 'disabled'}, "
            f"threads={'enabled' if allow_threads else 'disabled'}, "
            f"local={'enabled' if allow_local else 'disabled'}"
        )
    
    async def initialize(self) -> None:
        """Initialize the provider"""
        await super().initialize()
        
        # Check Docker availability
        if self.docker_hub:
            try:
                await self.docker_hub.initialize()
                logger.info("Docker execution available")
            except Exception as e:
                logger.warning(f"Docker initialization failed: {e}")
                self.docker_hub = None
    
    async def shutdown(self) -> None:
        """Shutdown the provider"""
        # Shutdown thread pool
        if self.thread_pool:
            self.thread_pool.shutdown(wait=True)
        
        await super().shutdown()
    
    @method("execute")
    async def execute_file(
        self,
        file_path: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        execution_mode: Optional[Literal["auto", "docker", "thread", "subprocess"]] = "auto",
        docker_image: Optional[str] = None,
        working_dir: Optional[str] = None,
        capture_output: bool = True
    ) -> Dict[str, Any]:
        """
        Execute a Python file with configurable isolation.
        
        Args:
            file_path: Path to Python file to execute
            args: Command line arguments to pass
            env: Environment variables
            timeout: Execution timeout in seconds
            execution_mode: Execution mode (auto selects best available)
            docker_image: Docker image to use (if docker mode)
            working_dir: Working directory for execution
            capture_output: Whether to capture stdout/stderr
            
        Returns:
            Execution result with output, exit code, and metadata
        """
        # Validate file
        file_path = Path(file_path).resolve()
        if not file_path.exists():
            raise InvalidParameterError("file_path", f"File not found: {file_path}")
        if not file_path.suffix == '.py':
            raise InvalidParameterError("file_path", f"Not a Python file: {file_path}")
        
        # Set defaults
        args = args or []
        env = env or {}
        timeout = timeout or self.default_timeout
        docker_image = docker_image or self.default_docker_image
        
        # Track execution
        execution_id = f"exec_{datetime.now().timestamp()}"
        self.active_executions[execution_id] = {
            "file": str(file_path),
            "started": datetime.now().isoformat(),
            "status": "running"
        }
        
        try:
            # Determine execution mode
            if execution_mode == "auto":
                execution_mode = self._select_execution_mode(file_path)
            
            # Execute based on mode
            if execution_mode == "docker":
                result = await self._execute_in_docker(
                    file_path, args, env, timeout, docker_image, working_dir, capture_output
                )
            elif execution_mode == "thread":
                result = await self._execute_in_thread(
                    file_path, args, env, timeout, working_dir, capture_output
                )
            elif execution_mode == "subprocess":
                result = await self._execute_in_subprocess(
                    file_path, args, env, timeout, working_dir, capture_output
                )
            else:
                raise InvalidParameterError("execution_mode", f"Invalid mode: {execution_mode}")
            
            # Update tracking
            self.active_executions[execution_id]["status"] = "completed"
            self.active_executions[execution_id]["completed"] = datetime.now().isoformat()
            
            return {
                **result,
                "execution_id": execution_id,
                "execution_mode": execution_mode
            }
            
        except Exception as e:
            self.active_executions[execution_id]["status"] = "failed"
            self.active_executions[execution_id]["error"] = str(e)
            raise
        finally:
            # Clean up old executions
            self._cleanup_executions()
    
    @method("validate")
    async def validate_file(self, file_path: str) -> Dict[str, Any]:
        """
        Validate Python file syntax.
        
        Args:
            file_path: Path to Python file
            
        Returns:
            Validation result with error details if invalid
        """
        file_path = Path(file_path).resolve()
        
        if not file_path.exists():
            return {
                "valid": False,
                "error": f"File not found: {file_path}",
                "file": str(file_path)
            }
        
        try:
            with open(file_path, 'r') as f:
                source = f.read()
            
            # Try to compile
            compile(source, str(file_path), 'exec')
            
            # Analyze imports and complexity
            import ast
            tree = ast.parse(source)
            
            imports = []
            functions = []
            classes = []
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.append(node.module or '')
                elif isinstance(node, ast.FunctionDef):
                    functions.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
            
            return {
                "valid": True,
                "file": str(file_path),
                "analysis": {
                    "imports": list(set(imports)),
                    "functions": functions,
                    "classes": classes,
                    "lines": len(source.splitlines())
                }
            }
            
        except SyntaxError as e:
            return {
                "valid": False,
                "error": f"Syntax error at line {e.lineno}: {e.msg}",
                "line": e.lineno,
                "offset": e.offset,
                "file": str(file_path)
            }
        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "file": str(file_path)
            }
    
    @method("list_executions")
    async def list_executions(
        self,
        status: Optional[Literal["running", "completed", "failed"]] = None
    ) -> List[Dict[str, Any]]:
        """
        List active and recent executions.
        
        Args:
            status: Filter by execution status
            
        Returns:
            List of execution records
        """
        executions = []
        for exec_id, exec_data in self.active_executions.items():
            if status is None or exec_data.get("status") == status:
                executions.append({
                    "id": exec_id,
                    **exec_data
                })
        
        return sorted(executions, key=lambda x: x.get("started", ""), reverse=True)
    
    @method("stop_execution")
    async def stop_execution(self, execution_id: str) -> Dict[str, bool]:
        """
        Stop a running execution.
        
        Args:
            execution_id: ID of execution to stop
            
        Returns:
            Success status
        """
        if execution_id in self.active_executions:
            # TODO: Implement actual stopping logic based on execution mode
            self.active_executions[execution_id]["status"] = "stopped"
            return {"success": True, "execution_id": execution_id}
        else:
            return {"success": False, "error": "Execution not found"}
    
    @method("get_info")
    async def get_info(self) -> Dict[str, Any]:
        """
        Get provider configuration and status.
        
        Returns:
            Provider information and capabilities
        """
        return {
            "provider_id": self.provider_id,
            "protocol_id": self.protocol_id,
            "python_version": sys.version,
            "capabilities": {
                "docker": self.docker_hub is not None,
                "threads": self.allow_threads,
                "subprocess": self.allow_local
            },
            "trusted_dirs": [str(d) for d in self.trusted_dirs],
            "default_timeout": self.default_timeout,
            "default_docker_image": self.default_docker_image,
            "active_executions": len([
                e for e in self.active_executions.values()
                if e.get("status") == "running"
            ])
        }
    
    def _select_execution_mode(self, file_path: Path) -> str:
        """Select best available execution mode"""
        is_trusted = self._is_trusted_file(file_path)
        
        # Prefer Docker if available
        if self.docker_hub:
            return "docker"
        
        # Use thread for untrusted files if available
        if not is_trusted and self.allow_threads:
            return "thread"
        
        # Use subprocess for trusted files
        if is_trusted and self.allow_local:
            return "subprocess"
        
        # Use thread as last resort
        if self.allow_threads:
            return "thread"
        
        raise TaskExecutionError(
            task_id="python_exec",
            message="No suitable execution mode available"
        )
    
    def _is_trusted_file(self, file_path: Path) -> bool:
        """Check if file is in a trusted directory"""
        file_path = file_path.resolve()
        for trusted_dir in self.trusted_dirs:
            try:
                file_path.relative_to(trusted_dir)
                return True
            except ValueError:
                continue
        return False
    
    async def _execute_in_docker(
        self,
        file_path: Path,
        args: List[str],
        env: Dict[str, str],
        timeout: int,
        docker_image: str,
        working_dir: Optional[str],
        capture_output: bool
    ) -> Dict[str, Any]:
        """Execute Python file in Docker container"""
        if not self.docker_hub:
            # Try to initialize Docker support if not available
            try:
                from gleitzeit.hub.docker_hub import DockerHub
                self.docker_hub = DockerHub(
                    hub_id=f"{self.provider_id}_docker",
                    default_image=docker_image
                )
                await self.docker_hub.initialize()
            except Exception as e:
                raise TaskExecutionError("python_docker", f"Docker not available: {e}")
        
        # Use direct Docker SDK if available, otherwise use DockerHub
        try:
            import docker
            DOCKER_SDK_AVAILABLE = True
        except ImportError:
            DOCKER_SDK_AVAILABLE = False
        
        if DOCKER_SDK_AVAILABLE:
            return await self._execute_in_docker_direct(
                file_path, args, env, timeout, docker_image, working_dir, capture_output
            )
        else:
            return await self._execute_in_docker_via_hub(
                file_path, args, env, timeout, docker_image, working_dir, capture_output
            )
    
    async def _execute_in_docker_direct(
        self,
        file_path: Path,
        args: List[str],
        env: Dict[str, str],
        timeout: int,
        docker_image: str,
        working_dir: Optional[str],
        capture_output: bool
    ) -> Dict[str, Any]:
        """Execute directly using Docker SDK"""
        import docker
        import tarfile
        import io
        import os
        
        try:
            # Connect to Docker
            client = docker.from_env()
            
            # Ensure image exists
            try:
                client.images.get(docker_image)
            except docker.errors.ImageNotFound:
                logger.info(f"Pulling Docker image: {docker_image}")
                client.images.pull(docker_image)
            
            # Prepare container configuration
            container_config = {
                "image": docker_image,
                "command": ["python", f"/workspace/{file_path.name}"] + args,
                "environment": env,
                "working_dir": working_dir or "/workspace",
                "detach": True,
                "labels": {
                    "gleitzeit.provider": self.provider_id,
                    "gleitzeit.type": "python_execution"
                },
                # Resource limits
                "mem_limit": "512m",
                "cpu_quota": 50000,  # 50% of a CPU
                "network_mode": "none",  # No network access by default
                # Security options
                "read_only": False,  # Need to write temp files
                "security_opt": ["no-new-privileges"],
            }
            
            # Create container
            container = client.containers.create(**container_config)
            
            try:
                # Copy Python file into container
                # Create a tar archive in memory
                tar_stream = io.BytesIO()
                with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                    # Add the Python file
                    tar.add(str(file_path), arcname=file_path.name)
                    
                    # If file has local imports, try to copy the directory
                    if file_path.parent != Path.cwd():
                        # Check for __init__.py or other Python files
                        python_files = list(file_path.parent.glob("*.py"))
                        if len(python_files) > 1:  # More than just our script
                            logger.debug(f"Copying {len(python_files)} Python files from {file_path.parent}")
                            for py_file in python_files:
                                tar.add(str(py_file), arcname=py_file.name)
                
                # Put archive into container
                tar_stream.seek(0)
                container.put_archive("/workspace", tar_stream.read())
                
                # Start container
                container.start()
                
                # Wait for completion with timeout
                try:
                    exit_code = container.wait(timeout=timeout)["StatusCode"]
                except docker.errors.NotFound:
                    # Container was removed
                    return {
                        "success": False,
                        "error": "Container was removed during execution",
                        "exit_code": -1
                    }
                except Exception as e:
                    # Timeout or other error
                    container.kill()
                    return {
                        "success": False,
                        "error": f"Execution timed out after {timeout} seconds",
                        "timeout": True,
                        "exit_code": -1
                    }
                
                # Get logs
                logs = container.logs(stdout=capture_output, stderr=capture_output)
                output = logs.decode('utf-8', errors='replace') if logs else ""
                
                # Separate stdout and stderr if possible
                stdout = ""
                stderr = ""
                if capture_output:
                    # Docker SDK combines logs, but we can try to parse
                    stdout = container.logs(stdout=True, stderr=False).decode('utf-8', errors='replace')
                    stderr = container.logs(stdout=False, stderr=True).decode('utf-8', errors='replace')
                
                # Try to parse output as JSON
                result_data = stdout
                try:
                    if stdout.strip():
                        result_data = json.loads(stdout.strip())
                except:
                    pass
                
                return {
                    "success": exit_code == 0,
                    "result": result_data,
                    "output": stdout,
                    "error": stderr if exit_code != 0 else "",
                    "exit_code": exit_code,
                    "container_id": container.short_id
                }
                
            finally:
                # Clean up container
                try:
                    container.remove(force=True)
                except:
                    pass
                    
        except docker.errors.DockerException as e:
            logger.error(f"Docker execution failed: {e}")
            return {
                "success": False,
                "error": f"Docker error: {str(e)}",
                "exit_code": -1
            }
        except Exception as e:
            logger.error(f"Unexpected error in Docker execution: {e}")
            return {
                "success": False,
                "error": str(e),
                "exit_code": -1
            }
    
    async def _execute_in_docker_via_hub(
        self,
        file_path: Path,
        args: List[str],
        env: Dict[str, str],
        timeout: int,
        docker_image: str,
        working_dir: Optional[str],
        capture_output: bool
    ) -> Dict[str, Any]:
        """Execute using DockerHub abstraction"""
        if not self.docker_hub:
            raise TaskExecutionError("python_docker", "DockerHub not available")
        
        from gleitzeit.hub.configs import DockerConfig
        
        # Create Docker configuration
        config = DockerConfig(
            image=docker_image,
            command=["python", f"/workspace/{file_path.name}"] + args,
            environment=env,
            working_dir=working_dir or "/workspace",
            memory_limit="512m",
            cpu_limit=0.5,
            network_mode="none",
            mounts=[{
                "type": "bind",
                "source": str(file_path.parent),
                "target": "/workspace",
                "readonly": True
            }]
        )
        
        # Start or get a container from the pool
        instance = await self.docker_hub.start_instance(config)
        
        if not instance:
            return {
                "success": False,
                "error": "Failed to allocate Docker container",
                "exit_code": -1
            }
        
        try:
            # Copy the Python file into the container
            import tarfile
            import io
            
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                tar.add(str(file_path), arcname=file_path.name)
                # Add other Python files if needed
                if file_path.parent != Path.cwd():
                    python_files = list(file_path.parent.glob("*.py"))
                    if len(python_files) > 1:
                        for py_file in python_files:
                            tar.add(str(py_file), arcname=py_file.name)
            
            # Put files into container (requires direct Docker access)
            if hasattr(instance.config, 'container_id'):
                import docker
                client = docker.from_env()
                container = client.containers.get(instance.config.container_id)
                tar_stream.seek(0)
                container.put_archive("/workspace", tar_stream.read())
            
            # Execute Python script in container
            result = await self.docker_hub.execute_in_container(
                instance.id,
                f"python /workspace/{file_path.name} " + " ".join(args),
                environment=env
            )
            
            # Parse output
            output = result.get("output", "")
            result_data = output
            try:
                if output.strip():
                    result_data = json.loads(output.strip())
            except:
                pass
            
            return {
                "success": result.get("success", False),
                "result": result_data,
                "output": output,
                "error": "" if result.get("success") else output,
                "exit_code": result.get("exit_code", -1),
                "container_id": instance.id
            }
            
        finally:
            # Return container to pool (DockerHub handles this)
            # Container stays running for reuse
            if self.docker_hub.enable_container_reuse:
                logger.debug(f"Container {instance.id} returned to pool for reuse")
            else:
                await self.docker_hub.stop_instance(instance.id)
    
    async def _execute_in_thread(
        self,
        file_path: Path,
        args: List[str],
        env: Dict[str, str],
        timeout: int,
        working_dir: Optional[str],
        capture_output: bool
    ) -> Dict[str, Any]:
        """Execute Python file in separate thread"""
        if not self.thread_pool:
            raise TaskExecutionError("python_thread", "Thread execution not available")
        
        import io
        import contextlib
        from concurrent.futures import TimeoutError as FutureTimeoutError
        
        def run_in_thread():
            """Function to run in thread"""
            # Set up environment
            import os
            old_env = os.environ.copy()
            os.environ.update(env)
            
            # Change working directory if specified
            old_cwd = os.getcwd()
            if working_dir:
                os.chdir(working_dir)
            
            # Capture output
            output_buffer = io.StringIO()
            error_buffer = io.StringIO()
            
            try:
                # Modify sys.argv for the script
                old_argv = sys.argv
                sys.argv = [str(file_path)] + args
                
                # Execute the file
                with open(file_path, 'r') as f:
                    source = f.read()
                
                # Create isolated namespace
                namespace = {
                    '__name__': '__main__',
                    '__file__': str(file_path)
                }
                
                # Redirect stdout/stderr if capturing
                if capture_output:
                    with contextlib.redirect_stdout(output_buffer), \
                         contextlib.redirect_stderr(error_buffer):
                        exec(compile(source, str(file_path), 'exec'), namespace)
                else:
                    exec(compile(source, str(file_path), 'exec'), namespace)
                
                return {
                    "success": True,
                    "output": output_buffer.getvalue() if capture_output else "",
                    "error": error_buffer.getvalue() if capture_output else "",
                    "exit_code": 0
                }
                
            except Exception as e:
                return {
                    "success": False,
                    "output": output_buffer.getvalue() if capture_output else "",
                    "error": str(e),
                    "exit_code": 1
                }
            finally:
                # Restore environment
                sys.argv = old_argv
                os.environ.clear()
                os.environ.update(old_env)
                os.chdir(old_cwd)
        
        try:
            # Run in thread with timeout
            future = self.thread_pool.submit(run_in_thread)
            result = await asyncio.get_event_loop().run_in_executor(
                None, future.result, timeout
            )
            return result
            
        except FutureTimeoutError:
            return {
                "success": False,
                "error": f"Execution timed out after {timeout} seconds",
                "timeout": True,
                "exit_code": -1
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "exit_code": -1
            }
    
    async def _execute_in_subprocess(
        self,
        file_path: Path,
        args: List[str],
        env: Dict[str, str],
        timeout: int,
        working_dir: Optional[str],
        capture_output: bool
    ) -> Dict[str, Any]:
        """Execute Python file in subprocess"""
        if not self.allow_local:
            raise TaskExecutionError("python_subprocess", "Local execution not allowed")
        
        if not self._is_trusted_file(file_path):
            raise TaskExecutionError(
                "python_subprocess",
                f"File {file_path} is not in trusted directories"
            )
        
        import os
        
        # Build command
        cmd = [sys.executable, str(file_path)] + args
        
        # Prepare environment
        process_env = os.environ.copy()
        process_env.update(env)
        
        try:
            # Create subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE if capture_output else None,
                stderr=asyncio.subprocess.PIPE if capture_output else None,
                env=process_env,
                cwd=working_dir
            )
            
            try:
                # Wait with timeout
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {
                    "success": False,
                    "error": f"Execution timed out after {timeout} seconds",
                    "timeout": True,
                    "exit_code": -1
                }
            
            # Process output
            output = stdout.decode('utf-8', errors='replace') if stdout else ""
            error = stderr.decode('utf-8', errors='replace') if stderr else ""
            
            # Try to parse output as JSON
            result_data = output
            try:
                result_data = json.loads(output)
            except:
                pass
            
            return {
                "success": process.returncode == 0,
                "result": result_data,
                "output": output,
                "error": error if process.returncode != 0 else "",
                "exit_code": process.returncode
            }
            
        except Exception as e:
            logger.error(f"Subprocess execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "exit_code": -1
            }
    
    def _cleanup_executions(self, keep_last: int = 100):
        """Clean up old execution records"""
        if len(self.active_executions) > keep_last:
            # Sort by start time and keep only recent ones
            sorted_execs = sorted(
                self.active_executions.items(),
                key=lambda x: x[1].get("started", ""),
                reverse=True
            )
            self.active_executions = dict(sorted_execs[:keep_last])