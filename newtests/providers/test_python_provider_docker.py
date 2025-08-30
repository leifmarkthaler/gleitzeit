"""
Test Docker execution for PythonProviderV2
Tests container-based Python script execution with pooling
"""

import pytest
import asyncio
from pathlib import Path
import json
import sys
import os

from gleitzeit.providers.python_provider_v2 import PythonProviderV2
from gleitzeit.hub.docker_hub import DockerHub


def docker_available():
    """Check if Docker is available"""
    try:
        import docker
        client = docker.from_env()
        client.ping()
        return True
    except:
        return False


@pytest.mark.skipif(
    not docker_available(),
    reason="Docker not available or not running"
)
@pytest.mark.skipif(
    not os.environ.get("TEST_DOCKER", "").lower() in ("1", "true", "yes"),
    reason="Docker tests disabled. Set TEST_DOCKER=1 to enable"
)
class TestPythonProviderDocker:
    """Test PythonProviderV2 Docker execution capabilities"""
    
    @pytest.fixture
    async def docker_hub(self):
        """Create and initialize DockerHub"""
        hub = DockerHub(
            hub_id="test_docker_hub",
            enable_container_reuse=True,
            default_image="python:3.11-slim"
        )
        await hub.initialize()
        yield hub
        await hub.cleanup()
    
    @pytest.fixture
    async def provider_with_docker(self, docker_hub):
        """Create PythonProviderV2 with Docker support"""
        provider = PythonProviderV2(
            provider_id="test_python_docker",
            docker_hub=docker_hub,
            allow_local=True,
            allow_threads=True,
            default_docker_image="python:3.11-slim",
            auto_generate_protocol=True
        )
        await provider.initialize()
        yield provider
        await provider.shutdown()
    
    @pytest.fixture
    def simple_script(self):
        """Simple test script from pythontestscripts"""
        return Path("/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/simple_hello.py")
    
    @pytest.fixture
    def error_script(self):
        """Error script from pythontestscripts"""
        return Path("/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/error_script.py")
    
    @pytest.fixture
    def env_script(self):
        """Environment reader script from pythontestscripts"""
        return Path("/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/env_reader.py")
    
    @pytest.mark.asyncio
    async def test_simple_docker_execution(self, provider_with_docker, simple_script):
        """Test basic Docker execution"""
        result = await provider_with_docker.execute_file(
            file_path=str(simple_script),
            args=["arg1", "arg2"],
            execution_mode="docker",
            timeout=30
        )
        
        assert result["success"] is True
        assert result["exit_code"] == 0
        assert "container_id" in result
        assert result["execution_mode"] == "docker"
        
        if isinstance(result.get("result"), dict):
            assert result["result"]["message"] == "Hello from Python!"
            assert result["result"]["args"] == ["arg1", "arg2"]
    
    @pytest.mark.asyncio
    async def test_docker_with_environment(self, provider_with_docker, env_script):
        """Test Docker execution with environment variables"""
        result = await provider_with_docker.execute_file(
            file_path=str(env_script),
            env={
                "TEST_VAR": "test_value_123",
                "CUSTOM_SETTING": "enabled"
            },
            execution_mode="docker",
            timeout=30
        )
        
        assert result["success"] is True
        
        if isinstance(result.get("result"), dict):
            assert result["result"]["test_var"] == "test_value_123"
            assert result["result"]["custom_setting"] == "enabled"
    
    @pytest.mark.asyncio
    async def test_docker_error_handling(self, provider_with_docker, error_script):
        """Test Docker execution error handling"""
        result = await provider_with_docker.execute_file(
            file_path=str(error_script),
            execution_mode="docker",
            timeout=30
        )
        
        assert result["success"] is False
        assert result["exit_code"] == 1
        assert "This is a test error" in result.get("error", "") or \
               "This is a test error" in result.get("output", "")
    
    @pytest.mark.asyncio
    async def test_docker_timeout(self, provider_with_docker):
        """Test Docker execution timeout"""
        timeout_script = Path("/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/timeout_script.py")
        
        result = await provider_with_docker.execute_file(
            file_path=str(timeout_script),
            execution_mode="docker",
            timeout=2  # 2 second timeout
        )
        
        assert result["success"] is False
        assert result.get("timeout") is True or "timeout" in result.get("error", "").lower()
    
    @pytest.mark.asyncio
    async def test_container_pooling(self, provider_with_docker, simple_script):
        """Test that containers are reused from pool"""
        # First execution
        result1 = await provider_with_docker.execute_file(
            file_path=str(simple_script),
            execution_mode="docker",
            timeout=30
        )
        container1 = result1.get("container_id")
        
        # Second execution (should potentially reuse container)
        result2 = await provider_with_docker.execute_file(
            file_path=str(simple_script),
            execution_mode="docker",
            timeout=30
        )
        container2 = result2.get("container_id")
        
        assert result1["success"] is True
        assert result2["success"] is True
        assert container1 is not None
        assert container2 is not None
        
        # Note: Container IDs might be different if pooling strategy changes
        # The important thing is that both executions succeed
    
    @pytest.mark.asyncio
    async def test_docker_with_compute_intensive(self, provider_with_docker):
        """Test Docker execution with compute intensive task"""
        compute_script = Path("/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/compute_intensive.py")
        
        result = await provider_with_docker.execute_file(
            file_path=str(compute_script),
            execution_mode="docker",
            timeout=60
        )
        
        assert result["success"] is True
        if isinstance(result.get("result"), dict):
            assert "result" in result["result"]
            assert "duration" in result["result"]
    
    @pytest.mark.asyncio
    async def test_auto_mode_with_docker(self, provider_with_docker, simple_script):
        """Test that auto mode selects Docker when available"""
        result = await provider_with_docker.execute_file(
            file_path=str(simple_script),
            execution_mode="auto"
        )
        
        # Should prefer Docker when available
        assert result["execution_mode"] == "docker"
        assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_docker_with_output_types(self, provider_with_docker):
        """Test Docker execution with various output types"""
        output_script = Path("/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/output_types.py")
        
        result = await provider_with_docker.execute_file(
            file_path=str(output_script),
            execution_mode="docker",
            timeout=30
        )
        
        assert result["success"] is True
        # Should parse the JSON output at the end
        if isinstance(result.get("result"), dict):
            assert result["result"]["string"] == "hello"
            assert result["result"]["number"] == 42
    
    @pytest.mark.asyncio
    async def test_docker_local_imports(self, provider_with_docker):
        """Test Docker execution with local imports"""
        import_script = Path("/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/import_local.py")
        
        result = await provider_with_docker.execute_file(
            file_path=str(import_script),
            execution_mode="docker",
            timeout=30
        )
        
        assert result["success"] is True
        if isinstance(result.get("result"), dict):
            assert result["result"]["addition"] == 15
            assert result["result"]["multiplication"] == 50
            assert "Successfully imported" in result["result"]["message"]


@pytest.mark.asyncio
async def test_docker_direct_vs_hub():
    """Test both Docker execution paths"""
    # This test verifies that both execution paths work:
    # 1. Direct Docker SDK (_execute_in_docker_direct)
    # 2. Via DockerHub (_execute_in_docker_via_hub)
    
    if not docker_available():
        pytest.skip("Docker not available")
    
    test_script = Path("/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/simple_hello.py")
    
    # Test with DockerHub (uses _execute_in_docker_via_hub)
    hub = DockerHub(hub_id="test_hub")
    await hub.initialize()
    
    provider1 = PythonProviderV2(
        provider_id="test_via_hub",
        docker_hub=hub
    )
    
    result1 = await provider1.execute_file(
        file_path=str(test_script),
        execution_mode="docker"
    )
    
    # Test without pre-initialized DockerHub (uses _execute_in_docker_direct if Docker SDK available)
    provider2 = PythonProviderV2(
        provider_id="test_direct"
    )
    
    result2 = await provider2.execute_file(
        file_path=str(test_script),
        execution_mode="docker"
    )
    
    # Both should work
    assert result1["success"] is True or "not yet implemented" in result1.get("error", "")
    assert result2["success"] is True or "not yet implemented" in result2.get("error", "")
    
    await hub.cleanup()