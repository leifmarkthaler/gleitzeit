"""
Shell command execution provider for Gleitzeit

Allows execution of shell commands and scripts within workflows
with comprehensive security controls and sandboxing options.
"""

import asyncio
import os
import json
import shlex
import tempfile
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Literal
from datetime import datetime
import logging

from gleitzeit.providers.simple import SimpleProvider
from gleitzeit.core.errors import ProviderError, TaskValidationError, TaskExecutionError, MethodNotSupportedError


class ShellProvider(SimpleProvider):
    """
    Execute shell commands in workflows with security controls
    
    Protocol: shell/v1
    
    Methods:
    - shell/exec: Execute single command
    - shell/script: Execute shell script file  
    - shell/pipe: Execute piped commands
    - shell/batch: Execute multiple commands in sequence
    
    Security features:
    - Command allowlist/blocklist
    - Working directory restrictions
    - Environment variable filtering
    - Timeout enforcement
    - Output size limits
    - Optional Docker sandboxing
    """
    
    def __init__(
        self,
        provider_id: str = "shell-provider",
        protocol_id: str = "shell/v1",
        allowed_commands: Optional[List[str]] = None,
        blocked_commands: Optional[List[str]] = None,
        allowed_dirs: Optional[List[str]] = None,
        working_dir: Optional[str] = None,
        timeout: int = 60,
        max_output_size: int = 10 * 1024 * 1024,  # 10MB
        shell: str = "/bin/bash",
        sandbox_mode: Literal["none", "docker", "restricted"] = "restricted",
        docker_image: str = "alpine:latest",
        env_whitelist: Optional[List[str]] = None,
        allow_sudo: bool = False,
        **kwargs
    ):
        """
        Initialize the Shell Provider
        
        Args:
            provider_id: Unique provider identifier
            allowed_commands: List of allowed command prefixes (if set, only these are allowed)
            blocked_commands: List of blocked command patterns
            allowed_dirs: List of allowed working directories
            working_dir: Default working directory
            timeout: Default command timeout in seconds
            max_output_size: Maximum output size in bytes
            shell: Shell to use for execution
            sandbox_mode: Sandboxing level ('none', 'docker', 'restricted')
            docker_image: Docker image for sandbox mode
            env_whitelist: List of allowed environment variables
            allow_sudo: Whether to allow sudo commands
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id=protocol_id,
            **kwargs
        )
        
        self.logger = logging.getLogger(__name__)
        
        # Security settings
        self.allow_sudo = allow_sudo
        self.allowed_commands = allowed_commands or []
        self.blocked_commands = blocked_commands or self._get_default_blocked_commands()
        self.allowed_dirs = [Path(d).resolve() for d in (allowed_dirs or [])]
        
        # Execution settings
        self.working_dir = Path(working_dir or os.getcwd()).resolve()
        self.timeout = timeout
        self.max_output_size = max_output_size
        self.shell = shell
        
        # Sandbox settings
        self.sandbox_mode = sandbox_mode
        self.docker_image = docker_image
        
        # Environment settings
        # None means no filtering, empty list means block all, otherwise use specified list
        if env_whitelist is None:
            self.env_whitelist = None  # No filtering
        elif env_whitelist == []:
            self.env_whitelist = []  # Block all custom env vars
        else:
            self.env_whitelist = env_whitelist or self._get_default_env_whitelist()
        
        # Execution history for audit
        self.execution_history = []
    
    def _get_default_blocked_commands(self) -> List[str]:
        """Get default list of dangerous commands to block"""
        dangerous = [
            "rm -rf /", "rm -rf /*", "rm -rf ~",
            "dd if=/dev/zero of=/dev/", "dd if=/dev/random of=/dev/",
            "mkfs", "fdisk", "parted",
            "shutdown", "reboot", "halt", "poweroff",
            "kill -9 -1", "killall",
            "chmod -R 777 /", "chmod -R 000 /",
            "chown -R", "chgrp -R",
            ":(){ :|:& };:",  # Fork bomb
            "> /dev/sda",
            "wget -O - | sh", "curl -s | bash",  # Remote execution
        ]
        
        if not self.allow_sudo:
            dangerous.extend(["sudo", "su -", "su root"])
        
        return dangerous
    
    def _get_default_env_whitelist(self) -> List[str]:
        """Get default list of safe environment variables"""
        return [
            "PATH", "HOME", "USER", "SHELL", "TERM", "LANG", "LC_ALL",
            "PWD", "TMPDIR", "TMP", "TEMP",
            # Add common development variables
            "PYTHON_PATH", "NODE_PATH", "JAVA_HOME", "GOPATH",
            "CARGO_HOME", "RUSTUP_HOME",
        ]
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute shell commands based on method"""
        
        # Validate method
        if method not in self.get_supported_methods():
            raise TaskValidationError("shell_task", [f"Unsupported method: {method}"])
        
        # Log execution attempt
        self._log_execution(method, params)
        
        try:
            if method == "shell/exec":
                result = await self._exec_command(params)
            elif method == "shell/script":
                result = await self._exec_script(params)
            elif method == "shell/pipe":
                result = await self._exec_pipe(params)
            elif method == "shell/batch":
                result = await self._exec_batch(params)
            else:
                raise MethodNotSupportedError(method, self.provider_id)
            
            # Add metadata
            result["provider"] = self.provider_id
            result["method"] = method
            result["timestamp"] = datetime.now().isoformat()
            
            return result
            
        except Exception as e:
            self.logger.error(f"Shell execution failed: {e}")
            raise TaskExecutionError(method, str(e))
    
    async def _exec_command(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single shell command"""
        
        command = params.get("command", "").strip()
        if not command:
            raise TaskValidationError("shell_exec", ["No command provided"])
        
        args = params.get("args", [])
        env = params.get("env", {})
        cwd = params.get("cwd", str(self.working_dir))
        timeout = params.get("timeout", self.timeout)
        capture_output = params.get("capture_output", True)
        shell = params.get("shell", self.shell)
        
        # Security validation
        self._validate_command(command)
        self._validate_working_dir(cwd)
        
        # Build full command
        if args:
            # Properly quote arguments to prevent injection
            safe_args = [shlex.quote(str(arg)) for arg in args]
            full_command = f"{command} {' '.join(safe_args)}"
        else:
            full_command = command
        
        # Apply sandboxing if needed
        if self.sandbox_mode == "docker":
            full_command = self._wrap_in_docker(full_command, cwd, env)
            cwd = "/"  # Docker handles the working directory
        elif self.sandbox_mode == "restricted":
            full_command = self._apply_restrictions(full_command)
        
        # Prepare environment
        process_env = self._prepare_environment(env)
        
        # Execute command
        self.logger.info(f"Executing command: {full_command[:100]}...")
        
        process = await asyncio.create_subprocess_shell(
            full_command,
            stdout=asyncio.subprocess.PIPE if capture_output else None,
            stderr=asyncio.subprocess.PIPE if capture_output else None,
            cwd=cwd,
            env=process_env,
            shell=True,
            executable=shell
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise TimeoutError(f"Command timed out after {timeout}s: {command}")
        
        # Process output
        stdout_text = self._decode_output(stdout) if stdout else ""
        stderr_text = self._decode_output(stderr) if stderr else ""
        
        # Check output size
        if len(stdout_text) > self.max_output_size:
            stdout_text = stdout_text[:self.max_output_size] + "\n[Output truncated]"
        if len(stderr_text) > self.max_output_size:
            stderr_text = stderr_text[:self.max_output_size] + "\n[Output truncated]"
        
        # Try to parse output as JSON
        output = stdout_text
        try:
            if stdout_text.strip().startswith('{') or stdout_text.strip().startswith('['):
                output = json.loads(stdout_text)
        except:
            pass
        
        return {
            "exit_code": process.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "output": output,
            "success": process.returncode == 0,
            "command": command  # Include for audit
        }
    
    async def _exec_script(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a shell script file"""
        
        script_path = params.get("script")
        if not script_path:
            raise TaskValidationError("shell_script", ["No script path provided"])
        
        script_path = Path(script_path).resolve()
        
        # Validate script exists and is readable
        if not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")
        if not script_path.is_file():
            raise TaskValidationError("shell_script", [f"Not a file: {script_path}"])
        
        # Security check - ensure script is in allowed directory
        self._validate_working_dir(str(script_path.parent))
        
        # Read script content for validation
        try:
            with open(script_path, 'r') as f:
                script_content = f.read()
        except Exception as e:
            raise ProviderError(f"Cannot read script: {e}")
        
        # Validate script content
        self._validate_script_content(script_content)
        
        # Make script executable
        script_path.chmod(0o755)
        
        # Execute as command
        return await self._exec_command({
            "command": str(script_path),
            "args": params.get("args", []),
            **{k: v for k, v in params.items() if k not in ["script", "args"]}
        })
    
    async def _exec_pipe(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute piped commands"""
        
        commands = params.get("commands", [])
        if not commands:
            raise TaskValidationError("shell_pipe", ["No commands provided for pipe"])
        
        # Validate each command
        for cmd in commands:
            self._validate_command(cmd)
        
        # Build pipe command with proper escaping
        safe_commands = []
        for cmd in commands:
            # If command has special chars, quote it
            if any(char in cmd for char in ['$', '`', '"', '\\']):
                safe_commands.append(shlex.quote(cmd))
            else:
                safe_commands.append(cmd)
        
        pipe_command = " | ".join(safe_commands)
        
        return await self._exec_command({
            "command": pipe_command,
            **{k: v for k, v in params.items() if k != "commands"}
        })
    
    async def _exec_batch(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute multiple commands in sequence"""
        
        commands = params.get("commands", [])
        if not commands:
            raise TaskValidationError("shell_batch", ["No commands provided for batch"])
        
        stop_on_error = params.get("stop_on_error", True)
        
        results = []
        overall_success = True
        
        for i, cmd in enumerate(commands):
            # Execute command
            cmd_params = {
                "command": cmd,
                **{k: v for k, v in params.items() 
                   if k not in ["commands", "stop_on_error"]}
            }
            
            try:
                result = await self._exec_command(cmd_params)
                results.append(result)
                
                if not result["success"]:
                    overall_success = False
                    if stop_on_error:
                        break
                        
            except Exception as e:
                error_result = {
                    "command": cmd,
                    "success": False,
                    "error": str(e),
                    "exit_code": -1
                }
                results.append(error_result)
                overall_success = False
                
                if stop_on_error:
                    break
        
        return {
            "success": overall_success,
            "results": results,
            "executed": len(results),
            "total": len(commands)
        }
    
    def _validate_command(self, command: str) -> None:
        """Validate command against security rules"""
        
        if not command:
            raise TaskValidationError("shell_exec", ["Empty command"])
        
        # Check against blocked commands
        for blocked in self.blocked_commands:
            if blocked in command:
                raise PermissionError(f"Blocked command pattern detected: {blocked}")
        
        # If allowlist is specified, check it
        if self.allowed_commands:
            base_command = command.split()[0] if command else ""
            if not any(base_command.startswith(allowed) for allowed in self.allowed_commands):
                raise PermissionError(f"Command not in allowlist: {base_command}")
        
        # Check for dangerous patterns
        dangerous_patterns = [
            "eval", "exec", "compile",  # Code execution
            "import os", "import subprocess",  # Python imports
            "require('child_process')",  # Node.js
            "System.exec", "Runtime.exec",  # Java
        ]
        
        for pattern in dangerous_patterns:
            if pattern in command:
                self.logger.warning(f"Potentially dangerous pattern in command: {pattern}")
    
    def _validate_working_dir(self, cwd: str) -> None:
        """Validate working directory is allowed"""
        
        target_dir = Path(cwd).resolve()
        
        # If allowed directories are specified, check them
        if self.allowed_dirs:
            if not any(self._is_subdir(target_dir, allowed) for allowed in self.allowed_dirs):
                raise PermissionError(f"Directory not allowed: {cwd}")
        
        # Always block certain system directories
        blocked_dirs = [
            Path("/"),
            Path("/etc"),
            Path("/bin"),
            Path("/sbin"),
            Path("/usr/bin"),
            Path("/usr/sbin"),
            Path("/boot"),
            Path("/dev"),
            Path("/proc"),
            Path("/sys"),
        ]
        
        for blocked in blocked_dirs:
            if target_dir == blocked or self._is_subdir(blocked, target_dir):
                raise PermissionError(f"System directory access denied: {cwd}")
    
    def _validate_script_content(self, content: str) -> None:
        """Validate script content for security issues"""
        
        # Check for dangerous patterns in script
        for blocked in self.blocked_commands:
            if blocked in content:
                raise PermissionError(f"Blocked pattern in script: {blocked}")
    
    def _filter_environment(self, env: Dict[str, str]) -> Dict[str, str]:
        """Filter environment variables for security"""
        
        if not self.env_whitelist:
            return env
        
        filtered = {}
        for key, value in env.items():
            if key in self.env_whitelist:
                filtered[key] = value
            else:
                self.logger.debug(f"Filtered out environment variable: {key}")
        
        return filtered
    
    def _prepare_environment(self, custom_env: Dict[str, str]) -> Dict[str, str]:
        """Prepare process environment"""
        
        # Start with filtered system environment
        if self.env_whitelist:
            env = {}
            for key in self.env_whitelist:
                if key in os.environ:
                    env[key] = os.environ[key]
        else:
            # If no whitelist, start with all environment variables
            env = os.environ.copy()
        
        # Add custom environment (filtered if whitelist is set)
        if self.env_whitelist:
            for key, value in custom_env.items():
                if key in self.env_whitelist:
                    env[key] = value
        else:
            env.update(custom_env)
        
        # Add security environment variables
        env["GLEITZEIT_PROVIDER"] = self.provider_id
        env["GLEITZEIT_SANDBOX"] = self.sandbox_mode
        
        return env
    
    def _wrap_in_docker(self, command: str, cwd: str, env: Dict[str, str]) -> str:
        """Wrap command for Docker execution"""
        
        # Build docker run command
        docker_cmd = ["docker", "run", "--rm"]
        
        # Add working directory
        docker_cmd.extend(["-w", "/workspace"])
        
        # Mount current directory
        docker_cmd.extend(["-v", f"{cwd}:/workspace:ro"])  # Read-only by default
        
        # Add environment variables
        for key, value in env.items():
            docker_cmd.extend(["-e", f"{key}={value}"])
        
        # Add resource limits
        docker_cmd.extend(["--memory", "512m"])
        docker_cmd.extend(["--cpus", "1"])
        
        # Add security options
        docker_cmd.extend(["--security-opt", "no-new-privileges"])
        docker_cmd.extend(["--cap-drop", "ALL"])
        
        # Add image and command
        docker_cmd.append(self.docker_image)
        docker_cmd.extend(["sh", "-c", command])
        
        return " ".join(shlex.quote(arg) for arg in docker_cmd)
    
    def _apply_restrictions(self, command: str) -> str:
        """Apply restrictions for restricted mode"""
        
        # Check for timeout command (gtimeout on macOS, timeout on Linux)
        import shutil
        if shutil.which("timeout"):
            return f"timeout {self.timeout} {command}"
        elif shutil.which("gtimeout"):
            return f"gtimeout {self.timeout} {command}"
        else:
            # Fallback to no timeout wrapper if not available
            return command
    
    def _decode_output(self, data: bytes) -> str:
        """Safely decode command output"""
        
        if not data:
            return ""
        
        # Try different encodings
        for encoding in ['utf-8', 'latin-1', 'ascii']:
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        
        # Fallback to lossy decode
        return data.decode('utf-8', errors='replace')
    
    def _is_subdir(self, child: Path, parent: Path) -> bool:
        """Check if child is subdirectory of parent"""
        
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False
    
    def _log_execution(self, method: str, params: Dict[str, Any]) -> None:
        """Log command execution for audit"""
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "method": method,
            "command": params.get("command", params.get("script", "N/A")),
            "user": os.environ.get("USER", "unknown")
        }
        
        self.execution_history.append(entry)
        
        # Keep only last 1000 entries
        if len(self.execution_history) > 1000:
            self.execution_history = self.execution_history[-1000:]
    
    def get_supported_methods(self) -> List[str]:
        """Return list of supported methods"""
        return ["shell/exec", "shell/script", "shell/pipe", "shell/batch"]
    
    async def health_check(self) -> Dict[str, Any]:
        """Provider health check"""
        
        # Test basic command execution
        try:
            result = await self._exec_command({"command": "echo 'health check'"})
            healthy = result["success"]
        except:
            healthy = False
        
        return {
            "healthy": healthy,
            "provider": self.provider_id,
            "sandbox_mode": self.sandbox_mode,
            "executions": len(self.execution_history)
        }