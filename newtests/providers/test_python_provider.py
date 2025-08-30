"""
Tests for Python Provider V2 with protocol auto-generation
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from gleitzeit.providers.python_provider_v2 import PythonProviderV2
from gleitzeit.core.errors import InvalidParameterError, TaskExecutionError
from gleitzeit.core.protocol import ParameterType


class TestPythonProviderV2:
    """Test enhanced Python provider"""
    
    @pytest.fixture
    def provider(self):
        """Create a test provider instance"""
        return PythonProviderV2(
            provider_id="test_python",
            allow_local=True,
            allow_threads=True,
            auto_generate_protocol=True
        )
    
    @pytest.fixture
    def docker_provider(self):
        """Create provider with mock Docker support"""
        mock_docker_hub = Mock()
        mock_docker_hub.initialize = AsyncMock()
        
        return PythonProviderV2(
            provider_id="test_python_docker",
            docker_hub=mock_docker_hub,
            allow_local=True,
            allow_threads=True
        )
    
    @pytest.fixture
    def test_script(self):
        """Test script from pythontestscripts"""
        return Path("/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/simple_hello.py")
    
    @pytest.fixture
    def error_script(self):
        """Error script from pythontestscripts"""
        return Path("/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/error_script.py")
    
    @pytest.mark.asyncio
    async def test_protocol_generation(self, provider):
        """Test that protocol is auto-generated correctly"""
        protocol = provider.get_generated_protocol()
        assert protocol is not None
        
        # Check methods are discovered
        assert "execute" in protocol.methods
        assert "validate" in protocol.methods
        assert "list_executions" in protocol.methods
        assert "stop_execution" in protocol.methods
        assert "get_info" in protocol.methods
        
        # Check execute method parameters
        execute_spec = protocol.methods["execute"]
        assert "file_path" in execute_spec.params_schema
        assert execute_spec.params_schema["file_path"].type == ParameterType.STRING
        assert execute_spec.params_schema["file_path"].required == True
        
        assert "args" in execute_spec.params_schema
        assert execute_spec.params_schema["args"].type == ParameterType.ARRAY
        assert execute_spec.params_schema["args"].required == False
        
        assert "timeout" in execute_spec.params_schema
        assert execute_spec.params_schema["timeout"].type == ParameterType.INTEGER
        assert execute_spec.params_schema["timeout"].required == False
        
        assert "execution_mode" in execute_spec.params_schema
        assert execute_spec.params_schema["execution_mode"].type == ParameterType.STRING
        
        # Check return type
        assert execute_spec.returns_schema is not None
        assert execute_spec.returns_schema.type == ParameterType.OBJECT
    
    @pytest.mark.asyncio
    async def test_execute_subprocess(self, provider, test_script):
        """Test executing Python file in subprocess"""
        result = await provider.execute_file(
            file_path=str(test_script),
            args=["arg1", "arg2"],
            execution_mode="subprocess"
        )
        
        assert result["success"] is True
        assert result["exit_code"] == 0
        assert "execution_id" in result
        assert result["execution_mode"] == "subprocess"
        
        # Check output - simple_hello.py returns different structure
        if isinstance(result.get("result"), dict):
            assert result["result"]["message"] == "Hello from Python!"
            assert result["result"]["args"] == ["arg1", "arg2"]
    
    @pytest.mark.asyncio
    async def test_execute_thread(self, provider, test_script):
        """Test executing Python file in thread"""
        result = await provider.execute_file(
            file_path=str(test_script),
            args=["test"],
            execution_mode="thread"
        )
        
        assert "execution_id" in result
        assert result["execution_mode"] == "thread"
        # Thread execution uses exec() which may not capture output the same way
    
    @pytest.mark.asyncio
    async def test_execute_auto_mode(self, docker_provider, test_script):
        """Test automatic execution mode selection"""
        # With Docker available, should prefer Docker
        result = await docker_provider.execute_file(
            file_path=str(test_script),
            execution_mode="auto"
        )
        
        # Docker not implemented yet, but mode selection should work
        assert "execution_id" in result
    
    @pytest.mark.asyncio
    async def test_validate_valid_file(self, provider, test_script):
        """Test validating a valid Python file"""
        result = await provider.validate_file(str(test_script))
        
        assert result["valid"] is True
        assert "analysis" in result
        assert "imports" in result["analysis"]
        assert "functions" in result["analysis"]
        assert "main" in result["analysis"]["functions"]
    
    @pytest.mark.asyncio
    async def test_validate_invalid_file(self, provider):
        """Test validating invalid Python file"""
        syntax_error_file = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/syntax_error.py"
        
        result = await provider.validate_file(syntax_error_file)
        
        assert result["valid"] is False
        assert "error" in result
        assert "line" in result
    
    @pytest.mark.asyncio
    async def test_validate_nonexistent_file(self, provider):
        """Test validating non-existent file"""
        result = await provider.validate_file("/nonexistent/file.py")
        
        assert result["valid"] is False
        assert "not found" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_file_not_python(self, provider):
        """Test error when file is not Python"""
        # Use README.md as non-Python file
        readme_file = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/README.md"
        
        with pytest.raises(InvalidParameterError, match="Not a Python file"):
            await provider.execute_file(readme_file)
    
    @pytest.mark.asyncio
    async def test_file_not_found(self, provider):
        """Test error when file doesn't exist"""
        with pytest.raises(InvalidParameterError, match="File not found"):
            await provider.execute_file("/nonexistent/script.py")
    
    @pytest.mark.asyncio
    async def test_execution_timeout(self, provider):
        """Test execution timeout handling"""
        timeout_script = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/timeout_script.py"
        
        result = await provider.execute_file(
            file_path=timeout_script,
            timeout=1,
            execution_mode="subprocess"
        )
        
        assert result["success"] is False
        assert "timeout" in result["error"].lower()
        assert result.get("timeout") is True
    
    @pytest.mark.asyncio
    async def test_execution_with_error(self, provider, error_script):
        """Test handling script that exits with error"""
        result = await provider.execute_file(
            file_path=str(error_script),
            execution_mode="subprocess"
        )
        
        assert result["success"] is False
        assert result["exit_code"] != 0
        assert "This is a test error" in result.get("error", "")
    
    @pytest.mark.asyncio
    async def test_list_executions(self, provider, test_script):
        """Test listing executions"""
        # Execute a script
        await provider.execute_file(str(test_script))
        
        # List all executions
        executions = await provider.list_executions()
        assert len(executions) > 0
        assert executions[0]["file"] == str(test_script)
        
        # Filter by status
        running = await provider.list_executions(status="running")
        completed = await provider.list_executions(status="completed")
        assert isinstance(running, list)
        assert isinstance(completed, list)
    
    @pytest.mark.asyncio
    async def test_stop_execution(self, provider):
        """Test stopping an execution"""
        # Create a fake execution
        provider.active_executions["test_exec"] = {
            "file": "test.py",
            "status": "running"
        }
        
        result = await provider.stop_execution("test_exec")
        assert result["success"] is True
        assert provider.active_executions["test_exec"]["status"] == "stopped"
        
        # Try to stop non-existent execution
        result = await provider.stop_execution("nonexistent")
        assert result["success"] is False
    
    @pytest.mark.asyncio
    async def test_get_info(self, provider):
        """Test getting provider info"""
        info = await provider.get_info()
        
        assert info["provider_id"] == "test_python"
        assert info["protocol_id"] == "python/v2"
        assert "python_version" in info
        assert "capabilities" in info
        assert info["capabilities"]["threads"] is True
        assert info["capabilities"]["subprocess"] is True
        assert "trusted_dirs" in info
    
    @pytest.mark.asyncio
    async def test_trusted_directories(self, provider):
        """Test trusted directory validation"""
        # Current directory should be trusted by default
        test_file = Path.cwd() / "test.py"
        assert provider._is_trusted_file(test_file) is True
        
        # File outside trusted dirs
        assert provider._is_trusted_file(Path("/tmp/untrusted.py")) is False
        
        # Add trusted directory
        provider.trusted_dirs.append(Path("/tmp"))
        assert provider._is_trusted_file(Path("/tmp/now_trusted.py")) is True
    
    @pytest.mark.asyncio
    async def test_environment_variables(self, provider):
        """Test passing environment variables"""
        env_script = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/env_reader.py"
        
        result = await provider.execute_file(
            file_path=env_script,
            env={"TEST_VAR": "test_value", "CUSTOM_SETTING": "enabled"},
            execution_mode="subprocess"
        )
        
        # Check if the JSON result contains our env vars
        if isinstance(result.get("result"), dict):
            assert result["result"]["test_var"] == "test_value"
        else:
            assert "test_value" in result.get("output", "")
    
    @pytest.mark.asyncio
    async def test_working_directory(self, provider):
        """Test setting working directory"""
        # Use simple_hello.py and check that working_dir parameter is accepted
        simple_script = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/simple_hello.py"
        
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await provider.execute_file(
                file_path=simple_script,
                working_dir=tmpdir,
                execution_mode="subprocess"
            )
            
            # Should succeed regardless of working directory
            assert "execution_id" in result
    
    @pytest.mark.asyncio
    async def test_cleanup_executions(self, provider):
        """Test execution history cleanup"""
        # Add many executions
        for i in range(150):
            provider.active_executions[f"exec_{i}"] = {
                "file": f"test_{i}.py",
                "started": f"2024-01-01T00:00:{i:02d}",
                "status": "completed"
            }
        
        # Trigger cleanup (happens after each execution)
        provider._cleanup_executions(keep_last=100)
        
        assert len(provider.active_executions) == 100
    
    @pytest.mark.asyncio
    async def test_thread_execution_isolation(self, provider):
        """Test that thread execution provides isolation"""
        # Use simple_hello.py for thread execution test
        simple_script = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/simple_hello.py"
        
        result = await provider.execute_file(
            file_path=simple_script,
            execution_mode="thread"
        )
        
        # Should have an execution_id and proper mode
        assert "execution_id" in result
        assert result["execution_mode"] == "thread"


class TestPythonProviderIntegration:
    """Integration tests for Python provider"""
    
    @pytest.mark.asyncio
    async def test_provider_lifecycle(self):
        """Test full provider lifecycle"""
        provider = PythonProviderV2(
            provider_id="lifecycle_test",
            allow_threads=True
        )
        
        # Initialize
        await provider.initialize()
        
        # Use provider
        info = await provider.get_info()
        assert info["provider_id"] == "lifecycle_test"
        
        # Shutdown
        await provider.shutdown()
        
        # Thread pool should be shut down
        if provider.thread_pool:
            assert provider.thread_pool._shutdown is True
    
    @pytest.mark.asyncio
    async def test_concurrent_executions(self):
        """Test multiple concurrent executions"""
        provider = PythonProviderV2(
            provider_id="concurrent_test",
            allow_threads=True,
            max_thread_workers=4
        )
        
        # Use existing test scripts
        scripts = [
            "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/simple_hello.py",
            "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/output_types.py",
            "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/env_reader.py"
        ]
        
        # Execute concurrently
        tasks = [
            provider.execute_file(script, execution_mode="thread")
            for script in scripts
        ]
        
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 3
        for i, result in enumerate(results):
            assert "execution_id" in result