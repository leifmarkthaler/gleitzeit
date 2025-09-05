"""
Tests for ShellProvider
"""

import pytest
import asyncio
import os
import tempfile
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from gleitzeit.providers.shell_provider import ShellProvider
from gleitzeit.core.errors import TaskValidationError, TaskExecutionError


class TestShellProviderBasics:
    """Test basic ShellProvider functionality"""
    
    @pytest.fixture
    def provider(self):
        """Create a test provider instance"""
        return ShellProvider(
            provider_id="test-shell",
            sandbox_mode="none",  # Disable sandboxing for tests
            env_whitelist=None,  # Allow all env vars for testing
            timeout=5
        )
    
    @pytest.mark.asyncio
    async def test_execute_simple_command(self, provider):
        """Test executing a simple echo command"""
        result = await provider.execute("shell/exec", {
            "command": "echo",
            "args": ["Hello, World!"]
        })
        
        assert result["success"] is True
        assert result["exit_code"] == 0
        assert "Hello, World!" in result["stdout"]
        assert result["stderr"] == ""
    
    @pytest.mark.asyncio
    async def test_execute_command_with_env(self, provider):
        """Test command with environment variables"""
        # Provider has env_whitelist=None so all env vars are allowed
        result = await provider.execute("shell/exec", {
            "command": "sh",
            "args": ["-c", "echo $TEST_VAR"],
            "env": {"TEST_VAR": "test_value"}
        })
        
        assert result["success"] is True
        assert "test_value" in result["stdout"]
    
    @pytest.mark.asyncio
    async def test_execute_failing_command(self, provider):
        """Test handling of failing commands"""
        result = await provider.execute("shell/exec", {
            "command": "false"  # Always returns exit code 1
        })
        
        assert result["success"] is False
        assert result["exit_code"] != 0
    
    @pytest.mark.asyncio
    async def test_command_timeout(self, provider):
        """Test command timeout handling"""
        with pytest.raises(TaskExecutionError) as exc:
            await provider.execute("shell/exec", {
                "command": "sleep 10",
                "timeout": 1
            })
        
        assert "timed out" in str(exc.value).lower()
    
    @pytest.mark.asyncio
    async def test_json_output_parsing(self, provider):
        """Test automatic JSON output parsing"""
        result = await provider.execute("shell/exec", {
            "command": "echo",
            "args": ['{"key": "value", "number": 42}']
        })
        
        assert result["success"] is True
        # Output should be parsed as JSON
        assert isinstance(result["output"], dict)
        assert result["output"]["key"] == "value"
        assert result["output"]["number"] == 42


class TestShellProviderSecurity:
    """Test ShellProvider security features"""
    
    @pytest.fixture
    def secure_provider(self):
        """Create a provider with security restrictions"""
        return ShellProvider(
            provider_id="secure-shell",
            allowed_commands=["echo", "ls", "cat", "grep"],
            blocked_commands=["rm", "dd", "mkfs"],
            sandbox_mode="restricted",
            timeout=5
        )
    
    @pytest.mark.asyncio
    async def test_blocked_command_rejection(self, secure_provider):
        """Test that blocked commands are rejected"""
        with pytest.raises(TaskExecutionError) as exc:
            await secure_provider.execute("shell/exec", {
                "command": "rm -rf /tmp/test"
            })
        
        assert "blocked command" in str(exc.value).lower()
    
    @pytest.mark.asyncio
    async def test_allowed_command_execution(self, secure_provider):
        """Test that allowed commands work"""
        result = await secure_provider.execute("shell/exec", {
            "command": "echo",
            "args": ["test"]
        })
        
        assert result["success"] is True
        assert "test" in result["stdout"]
    
    @pytest.mark.asyncio
    async def test_command_not_in_allowlist(self, secure_provider):
        """Test command not in allowlist is rejected"""
        with pytest.raises(TaskExecutionError) as exc:
            await secure_provider.execute("shell/exec", {
                "command": "wget http://example.com"
            })
        
        assert "not in allowlist" in str(exc.value).lower()
    
    @pytest.mark.asyncio
    async def test_dangerous_pattern_detection(self):
        """Test detection of dangerous patterns"""
        provider = ShellProvider(
            provider_id="test",
            sandbox_mode="none"
        )
        
        # Fork bomb should be blocked
        with pytest.raises(TaskExecutionError) as exc:
            await provider.execute("shell/exec", {
                "command": ":(){ :|:& };:"
            })
        
        assert "blocked" in str(exc.value).lower()
    
    @pytest.mark.asyncio
    async def test_directory_restriction(self):
        """Test working directory restrictions"""
        provider = ShellProvider(
            provider_id="test",
            allowed_dirs=["/tmp"],
            sandbox_mode="none"
        )
        
        # Should work in /tmp
        result = await provider.execute("shell/exec", {
            "command": "pwd",
            "cwd": "/tmp"
        })
        assert result["success"] is True
        
        # Should fail in /etc
        with pytest.raises(TaskExecutionError):
            await provider.execute("shell/exec", {
                "command": "pwd",
                "cwd": "/etc"
            })
    
    @pytest.mark.asyncio
    async def test_environment_filtering(self):
        """Test environment variable filtering"""
        provider = ShellProvider(
            provider_id="test",
            env_whitelist=["PATH", "TEST_VAR"],
            sandbox_mode="none"
        )
        
        result = await provider.execute("shell/exec", {
            "command": "env",
            "env": {
                "TEST_VAR": "allowed",
                "SECRET_KEY": "should_be_filtered"
            }
        })
        
        assert "TEST_VAR=allowed" in result["stdout"]
        assert "SECRET_KEY" not in result["stdout"]


class TestShellProviderMethods:
    """Test different shell provider methods"""
    
    @pytest.fixture
    def provider(self):
        return ShellProvider(
            provider_id="test",
            sandbox_mode="none",
            timeout=5
        )
    
    @pytest.mark.asyncio
    async def test_exec_script(self, provider):
        """Test script execution"""
        # Create a temporary script
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write("#!/bin/bash\n")
            f.write("echo 'Script output'\n")
            f.write("echo $1\n")  # Print first argument
            script_path = f.name
        
        try:
            result = await provider.execute("shell/script", {
                "script": script_path,
                "args": ["test_arg"]
            })
            
            assert result["success"] is True
            assert "Script output" in result["stdout"]
            assert "test_arg" in result["stdout"]
        finally:
            os.unlink(script_path)
    
    @pytest.mark.asyncio
    async def test_exec_pipe(self, provider):
        """Test piped command execution"""
        result = await provider.execute("shell/pipe", {
            "commands": [
                "echo 'line1\nline2\nline3'",
                "grep line2"
            ]
        })
        
        assert result["success"] is True
        assert "line2" in result["stdout"]
        assert "line1" not in result["stdout"]
        assert "line3" not in result["stdout"]
    
    @pytest.mark.asyncio
    async def test_exec_batch(self, provider):
        """Test batch command execution"""
        result = await provider.execute("shell/batch", {
            "commands": [
                "echo 'First command'",
                "echo 'Second command'",
                "echo 'Third command'"
            ]
        })
        
        assert result["success"] is True
        assert result["executed"] == 3
        assert result["total"] == 3
        assert len(result["results"]) == 3
        
        # Check each command result
        for i, cmd_result in enumerate(result["results"]):
            assert cmd_result["success"] is True
            assert f"command" in cmd_result["stdout"].lower()
    
    @pytest.mark.asyncio
    async def test_batch_stop_on_error(self, provider):
        """Test batch execution stops on error"""
        result = await provider.execute("shell/batch", {
            "commands": [
                "echo 'First'",
                "false",  # This will fail
                "echo 'Should not execute'"
            ],
            "stop_on_error": True
        })
        
        assert result["success"] is False
        assert result["executed"] == 2  # Only first two executed
        assert result["total"] == 3
        assert result["results"][0]["success"] is True
        assert result["results"][1]["success"] is False
        assert len(result["results"]) == 2  # Third command not executed
    
    @pytest.mark.asyncio
    async def test_batch_continue_on_error(self, provider):
        """Test batch execution continues on error"""
        result = await provider.execute("shell/batch", {
            "commands": [
                "echo 'First'",
                "false",  # This will fail
                "echo 'Still executes'"
            ],
            "stop_on_error": False
        })
        
        assert result["success"] is False  # Overall failed
        assert result["executed"] == 3  # All executed
        assert result["results"][0]["success"] is True
        assert result["results"][1]["success"] is False
        assert result["results"][2]["success"] is True
        assert "Still executes" in result["results"][2]["stdout"]


class TestShellProviderAdvanced:
    """Test advanced ShellProvider features"""
    
    @pytest.mark.asyncio
    async def test_output_size_limit(self):
        """Test output size limiting"""
        provider = ShellProvider(
            provider_id="test",
            max_output_size=100,  # Very small limit
            sandbox_mode="none"
        )
        
        # Generate large output
        result = await provider.execute("shell/exec", {
            "command": "seq 1 1000"  # Generate numbers 1-1000
        })
        
        assert result["success"] is True
        assert len(result["stdout"]) <= 150  # Should be truncated (with message)
        assert "[Output truncated]" in result["stdout"]
    
    @pytest.mark.asyncio
    async def test_working_directory(self):
        """Test working directory setting"""
        provider = ShellProvider(
            provider_id="test",
            sandbox_mode="none"
        )
        
        # Create temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test content")
            
            # Execute command in that directory
            result = await provider.execute("shell/exec", {
                "command": "ls",
                "cwd": tmpdir
            })
            
            assert result["success"] is True
            assert "test.txt" in result["stdout"]
    
    @pytest.mark.asyncio
    async def test_shell_selection(self):
        """Test using different shells"""
        # Test with bash
        provider_bash = ShellProvider(
            provider_id="bash",
            shell="/bin/bash",
            sandbox_mode="none"
        )
        
        result = await provider_bash.execute("shell/exec", {
            "command": "echo $BASH_VERSION",
            "shell": "/bin/bash"
        })
        
        # Should have some bash version output (or empty if not available)
        assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_execution_history(self):
        """Test execution history tracking"""
        provider = ShellProvider(
            provider_id="test",
            sandbox_mode="none"
        )
        
        # Execute some commands
        await provider.execute("shell/exec", {"command": "echo 1"})
        await provider.execute("shell/exec", {"command": "echo 2"})
        await provider.execute("shell/exec", {"command": "echo 3"})
        
        # Check history
        assert len(provider.execution_history) == 3
        assert provider.execution_history[0]["command"] == "echo 1"
        assert provider.execution_history[1]["command"] == "echo 2"
        assert provider.execution_history[2]["command"] == "echo 3"
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test provider health check"""
        provider = ShellProvider(
            provider_id="test",
            sandbox_mode="none"
        )
        
        health = await provider.health_check()
        
        assert health["healthy"] is True
        assert health["provider"] == "test"
        assert health["sandbox_mode"] == "none"
        assert "executions" in health


class TestShellProviderIntegration:
    """Integration tests for ShellProvider"""
    
    @pytest.mark.asyncio
    async def test_complex_pipe(self):
        """Test complex piped commands"""
        provider = ShellProvider(
            provider_id="test",
            sandbox_mode="none"
        )
        
        result = await provider.execute("shell/pipe", {
            "commands": [
                "seq 1 10",
                "grep -E '[02468]'",  # Even numbers
                "wc -l"  # Count lines
            ]
        })
        
        assert result["success"] is True
        # Should output "5" (even numbers from 1-10)
        assert "5" in result["stdout"].strip()
    
    @pytest.mark.asyncio
    async def test_script_with_error_handling(self):
        """Test script execution with error handling"""
        provider = ShellProvider(
            provider_id="test",
            sandbox_mode="none"
        )
        
        # Create script with error handling
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write("""#!/bin/bash
set -e  # Exit on error
echo "Starting"
if [ "$1" = "fail" ]; then
    echo "Failing as requested" >&2
    exit 1
fi
echo "Success"
exit 0
""")
            script_path = f.name
        
        try:
            # Test successful execution
            result = await provider.execute("shell/script", {
                "script": script_path,
                "args": ["succeed"]
            })
            assert result["success"] is True
            assert "Success" in result["stdout"]
            
            # Test failed execution
            result = await provider.execute("shell/script", {
                "script": script_path,
                "args": ["fail"]
            })
            assert result["success"] is False
            assert "Failing as requested" in result["stderr"]
            
        finally:
            os.unlink(script_path)
    
    @pytest.mark.asyncio
    async def test_supported_methods(self):
        """Test get_supported_methods"""
        provider = ShellProvider()
        methods = provider.get_supported_methods()
        
        assert "shell/exec" in methods
        assert "shell/script" in methods
        assert "shell/pipe" in methods
        assert "shell/batch" in methods
        assert len(methods) == 4
    
    @pytest.mark.asyncio
    async def test_invalid_method(self):
        """Test handling of invalid method"""
        provider = ShellProvider(sandbox_mode="none")
        
        with pytest.raises(TaskValidationError) as exc:
            await provider.execute("shell/invalid", {
                "command": "echo test"
            })
        
        assert "unsupported method" in str(exc.value).lower()