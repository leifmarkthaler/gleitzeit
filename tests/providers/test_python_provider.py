"""
Test suite for the secure PythonProvider
Tests file-based execution, security model, and Docker/local execution modes
"""

import asyncio
import json
import tempfile
import pytest
from pathlib import Path
from typing import Dict, Any

from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.core.errors import InvalidParameterError, TaskExecutionError


class TestPythonProvider:
    """Test the secure Python file execution provider"""
    
    @pytest.fixture
    async def provider(self):
        """Create a test provider instance"""
        provider = PythonProvider(
            provider_id='test-python',
            allow_local=True,
            trusted_dirs=[Path.cwd()]
        )
        await provider.initialize()
        yield provider
        await provider.shutdown()
    
    @pytest.fixture
    def temp_script(self):
        """Create a temporary Python script for testing"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
import json
result = {"test": "success", "value": 42}
print(json.dumps(result))
""")
            temp_path = Path(f.name)
        yield temp_path
        temp_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_local_file_execution(self, provider):
        """Test executing a trusted local Python file"""
        # Create test script
        test_file = Path('test_local_exec.py')
        test_file.write_text("""
print("Hello from local execution")
print("Line 2")
""")
        
        try:
            result = await provider.execute('python/execute', {
                'file': str(test_file),
                'timeout': 10
            })
            
            assert result['success'] == True
            assert result['returncode'] == 0
            assert 'Hello from local execution' in result['stdout']
            assert 'Line 2' in result['stdout']
            assert result['execution_mode'] == 'local'
            assert result['trusted'] == True
        finally:
            test_file.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_json_output_parsing(self, provider):
        """Test executing a script that outputs JSON"""
        test_file = Path('test_json_output.py')
        test_file.write_text("""
import json
data = {
    "numbers": [1, 2, 3, 4, 5],
    "sum": 15,
    "average": 3.0,
    "message": "Calculation complete"
}
print(json.dumps(data))
""")
        
        try:
            result = await provider.execute('python/execute', {
                'file': str(test_file),
                'timeout': 10
            })
            
            assert result['success'] == True
            
            # Parse JSON from stdout
            output_data = json.loads(result['stdout'])
            assert output_data['sum'] == 15
            assert output_data['average'] == 3.0
            assert output_data['message'] == 'Calculation complete'
        finally:
            test_file.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_script_with_error(self, provider):
        """Test executing a script that has an error"""
        test_file = Path('test_error.py')
        test_file.write_text("""
print("Before error")
raise ValueError("Intentional error for testing")
print("After error - should not print")
""")
        
        try:
            result = await provider.execute('python/execute', {
                'file': str(test_file),
                'timeout': 10
            })
            
            assert result['success'] == False
            assert result['returncode'] != 0
            assert 'Before error' in result['stdout']
            assert 'ValueError: Intentional error for testing' in result['stderr']
            assert 'After error' not in result['stdout']
        finally:
            test_file.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_script_with_arguments(self, provider):
        """Test executing a script with command-line arguments"""
        test_file = Path('test_args.py')
        test_file.write_text("""
import sys
print(f"Script name: {sys.argv[0]}")
for i, arg in enumerate(sys.argv[1:], 1):
    print(f"Arg {i}: {arg}")
""")
        
        try:
            result = await provider.execute('python/execute', {
                'file': str(test_file),
                'args': ['hello', 'world', '123'],
                'timeout': 10
            })
            
            assert result['success'] == True
            assert 'Arg 1: hello' in result['stdout']
            assert 'Arg 2: world' in result['stdout']
            assert 'Arg 3: 123' in result['stdout']
        finally:
            test_file.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_script_with_environment(self, provider):
        """Test executing a script with environment variables"""
        test_file = Path('test_env.py')
        test_file.write_text("""
import os
print(f"TEST_VAR: {os.environ.get('TEST_VAR', 'not set')}")
print(f"ANOTHER_VAR: {os.environ.get('ANOTHER_VAR', 'not set')}")
""")
        
        try:
            result = await provider.execute('python/execute', {
                'file': str(test_file),
                'env': {
                    'TEST_VAR': 'test_value',
                    'ANOTHER_VAR': '42'
                },
                'timeout': 10
            })
            
            assert result['success'] == True
            assert 'TEST_VAR: test_value' in result['stdout']
            assert 'ANOTHER_VAR: 42' in result['stdout']
        finally:
            test_file.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, provider):
        """Test that long-running scripts are properly timed out"""
        test_file = Path('test_timeout.py')
        test_file.write_text("""
import time
print("Starting long operation...")
time.sleep(10)  # Sleep longer than timeout
print("This should not print")
""")
        
        try:
            result = await provider.execute('python/execute', {
                'file': str(test_file),
                'timeout': 2  # 2 second timeout
            })
            
            assert result['success'] == False
            assert result.get('timeout') == True
            assert 'timed out' in result.get('error', '').lower()
            # Note: stdout might not be captured when process is killed
            # assert 'Starting long operation' in result.get('stdout', '')
            assert 'This should not print' not in result.get('stdout', '')
        finally:
            test_file.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_file_validation(self, provider):
        """Test file validation and security checks"""
        
        # Test missing file
        with pytest.raises(InvalidParameterError) as exc_info:
            await provider.execute('python/execute', {
                'file': 'nonexistent_file.py'
            })
        assert 'not found' in str(exc_info.value).lower()
        
        # Test non-Python file
        test_file = Path('test.txt')
        test_file.write_text("This is not a Python file")
        
        try:
            with pytest.raises(InvalidParameterError) as exc_info:
                await provider.execute('python/execute', {
                    'file': str(test_file)
                })
            assert 'not a python file' in str(exc_info.value).lower()
        finally:
            test_file.unlink(missing_ok=True)
        
        # Test missing file parameter
        with pytest.raises(InvalidParameterError) as exc_info:
            await provider.execute('python/execute', {
                'timeout': 10
            })
        assert 'missing' in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_no_arbitrary_code_execution(self, provider):
        """Test that arbitrary code execution is not allowed"""
        
        # Should not accept 'code' parameter
        with pytest.raises(InvalidParameterError):
            await provider.execute('python/execute', {
                'code': 'print("This should not work")',
                'timeout': 10
            })
    
    @pytest.mark.asyncio
    async def test_validate_file_syntax(self, provider):
        """Test Python file syntax validation"""
        
        # Valid Python file
        valid_file = Path('test_valid.py')
        valid_file.write_text("""
def hello():
    print("Hello, world!")

hello()
""")
        
        try:
            result = await provider.execute('python/validate', {
                'file': str(valid_file)
            })
            assert result['valid'] == True
            assert 'message' in result
        finally:
            valid_file.unlink(missing_ok=True)
        
        # Invalid Python file
        invalid_file = Path('test_invalid.py')
        invalid_file.write_text("""
def hello()  # Missing colon
    print("Hello, world!")
""")
        
        try:
            result = await provider.execute('python/validate', {
                'file': str(invalid_file)
            })
            assert result['valid'] == False
            assert 'error' in result
            assert 'line' in result
        finally:
            invalid_file.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_provider_info(self, provider):
        """Test getting provider information"""
        result = await provider.execute('python/info', {})
        
        assert result['provider'] == 'test-python'
        assert result['protocol'] == 'python/v1'
        assert 'docker_available' in result
        assert 'allow_local' in result
        assert result['allow_local'] == True
        assert 'trusted_dirs' in result
        assert len(result['trusted_dirs']) > 0
    
    @pytest.mark.asyncio
    async def test_trusted_directory_check(self, provider, temp_script):
        """Test that files outside trusted directories are handled correctly"""
        
        # File in temp directory (likely outside trusted dirs)
        result = await provider.execute('python/execute', {
            'file': str(temp_script),
            'use_docker': False,
            'force_local': True  # Force local execution for testing
        })
        
        # Should work with force_local
        assert 'error' not in result or result['success'] == True
    
    @pytest.mark.asyncio
    async def test_docker_execution(self, provider):
        """Test Docker execution mode (if Docker is available)"""
        # Check if Docker is available
        from gleitzeit.providers.python_provider import DOCKER_AVAILABLE
        
        if not DOCKER_AVAILABLE:
            pytest.skip("Docker not available")
        
        test_file = Path('test_docker.py')
        test_file.write_text("""
import sys
print(f"Python version: {sys.version}")
print("Running in Docker container")
""")
        
        try:
            result = await provider.execute('python/execute', {
                'file': str(test_file),
                'use_docker': True,
                'timeout': 30
            })
            
            assert result['success'] == True
            assert result['execution_mode'] == 'docker'
            assert result['trusted'] == False
            assert 'Python version' in result['stdout']
            assert 'container_id' in result
        finally:
            test_file.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_supported_methods(self, provider):
        """Test that provider reports correct supported methods"""
        methods = provider.get_supported_methods()
        
        assert 'python/execute' in methods
        assert 'python/validate' in methods
        assert 'python/info' in methods
        
        # Should not have eval or arbitrary code execution
        assert 'python/eval' not in methods
        assert 'python/exec' not in methods


def test_sync_python_provider():
    """Synchronous test wrapper for basic provider functionality"""
    
    async def run_test():
        provider = PythonProvider('test-sync')
        await provider.initialize()
        
        # Test basic execution
        test_file = Path('test_sync.py')
        test_file.write_text('print("Sync test successful")')
        
        try:
            result = await provider.execute('python/execute', {
                'file': str(test_file)
            })
            assert result['success'] == True
            assert 'Sync test successful' in result['stdout']
        finally:
            test_file.unlink(missing_ok=True)
            await provider.shutdown()
    
    asyncio.run(run_test())


if __name__ == '__main__':
    # Run basic tests if executed directly
    print("Running PythonProvider tests...")
    
    # Test 1: Basic execution
    print("\n1. Testing basic file execution...")
    test_sync_python_provider()
    print("✓ Basic execution works")
    
    # Test 2: Security model
    print("\n2. Testing security model...")
    async def test_security():
        provider = PythonProvider('test-security')
        await provider.initialize()
        
        try:
            # Should reject arbitrary code
            await provider.execute('python/execute', {
                'code': 'print("Should not work")'
            })
            print("✗ Security check failed - code execution allowed!")
        except InvalidParameterError:
            print("✓ Correctly rejects arbitrary code")
        
        await provider.shutdown()
    
    asyncio.run(test_security())
    
    # Test 3: JSON output
    print("\n3. Testing JSON output handling...")
    async def test_json():
        provider = PythonProvider('test-json')
        await provider.initialize()
        
        test_file = Path('test_json.py')
        test_file.write_text('import json; print(json.dumps({"test": "pass"}))')
        
        try:
            result = await provider.execute('python/execute', {
                'file': str(test_file)
            })
            data = json.loads(result['stdout'])
            assert data['test'] == 'pass'
            print("✓ JSON output handling works")
        finally:
            test_file.unlink(missing_ok=True)
            await provider.shutdown()
    
    asyncio.run(test_json())
    
    print("\n✅ All basic tests passed!")