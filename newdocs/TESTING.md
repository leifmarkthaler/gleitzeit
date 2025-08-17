# Testing Guide

## Overview

This guide covers testing strategies, patterns, and tools for Gleitzeit v0.0.5. It includes unit testing, integration testing, end-to-end testing, and performance testing approaches for workflows, providers, hubs, and the complete system.

## Testing Architecture

```
┌─────────────────────────────────────────────────────┐
│                 Test Pyramid                        │
│                                                     │
│         ┌─────────────────────────┐                │
│         │    E2E Tests (10%)      │                │
│         │  Full workflow execution │                │
│         └───────────┬─────────────┘                │
│                     │                               │
│       ┌─────────────▼──────────────┐               │
│       │  Integration Tests (30%)    │               │
│       │  Component interactions     │               │
│       └─────────────┬──────────────┘               │
│                     │                               │
│     ┌───────────────▼────────────────┐             │
│     │     Unit Tests (60%)           │             │
│     │  Individual component testing   │             │
│     └─────────────────────────────────┘             │
└─────────────────────────────────────────────────────┘
```

## Test Setup

### Project Structure

```
gleitzeit/
├── tests/
│   ├── unit/
│   │   ├── providers/
│   │   │   ├── test_ollama_provider.py
│   │   │   ├── test_python_provider.py
│   │   │   └── test_mcp_provider.py
│   │   ├── hub/
│   │   │   ├── test_ollama_hub.py
│   │   │   ├── test_docker_hub.py
│   │   │   └── test_resource_manager.py
│   │   ├── core/
│   │   │   ├── test_execution_engine.py
│   │   │   ├── test_registry.py
│   │   │   └── test_workflow_loader.py
│   │   └── persistence/
│   │       └── test_unified_persistence.py
│   ├── integration/
│   │   ├── test_workflow_execution.py
│   │   ├── test_provider_hub_integration.py
│   │   └── test_persistence_fallback.py
│   ├── e2e/
│   │   ├── test_complete_workflows.py
│   │   └── test_api_endpoints.py
│   ├── performance/
│   │   ├── test_load.py
│   │   └── test_benchmarks.py
│   ├── fixtures/
│   │   ├── workflows/
│   │   ├── data/
│   │   └── mocks.py
│   └── conftest.py
```

### Test Dependencies

```toml
# pyproject.toml
[tool.poetry.dev-dependencies]
pytest = "^7.4.0"
pytest-asyncio = "^0.21.0"
pytest-cov = "^4.1.0"
pytest-mock = "^3.11.0"
pytest-timeout = "^2.1.0"
pytest-benchmark = "^4.0.0"
httpx = "^0.24.0"
faker = "^19.0.0"
```

### Pytest Configuration

```ini
# pytest.ini
[tool:pytest]
minversion = 7.0
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto

# Coverage settings
addopts = 
    --verbose
    --strict-markers
    --cov=src/gleitzeit
    --cov-report=term-missing
    --cov-report=html
    --cov-report=xml
    --cov-fail-under=80

# Test markers
markers =
    unit: Unit tests
    integration: Integration tests
    e2e: End-to-end tests
    slow: Slow tests
    performance: Performance tests
    docker: Requires Docker
    ollama: Requires Ollama
    redis: Requires Redis

# Timeout settings
timeout = 300
timeout_method = thread
```

## Unit Testing

### Testing Providers

```python
# tests/unit/providers/test_ollama_provider.py
import pytest
from unittest.mock import Mock, AsyncMock, patch
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.hub.ollama_hub import OllamaHub

@pytest.fixture
async def mock_hub():
    """Create mock OllamaHub"""
    hub = Mock(spec=OllamaHub)
    hub.get_available_instance = AsyncMock(return_value=Mock(
        id="test-instance",
        endpoint="http://localhost:11434",
        status="HEALTHY"
    ))
    hub.report_error = AsyncMock()
    return hub

@pytest.fixture
async def provider(mock_hub):
    """Create OllamaProvider with mock hub"""
    provider = OllamaProvider(
        provider_id="test-ollama",
        ollama_hub=mock_hub
    )
    await provider.initialize()
    return provider

class TestOllamaProvider:
    """Test OllamaProvider functionality"""
    
    @pytest.mark.asyncio
    async def test_initialization(self, provider, mock_hub):
        """Test provider initialization"""
        assert provider.provider_id == "test-ollama"
        assert provider.protocol_id == "llm/v1"
        assert provider.hub == mock_hub
        assert provider.session is not None
    
    @pytest.mark.asyncio
    async def test_handle_chat_request(self, provider, mock_hub):
        """Test chat request handling"""
        # Mock HTTP response
        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={
                "response": "Hello, world!",
                "model": "llama3.2"
            })
            mock_response.status = 200
            mock_post.return_value.__aenter__.return_value = mock_response
            
            # Execute request
            result = await provider.handle_request(
                method="chat",
                params={
                    "model": "llama3.2",
                    "messages": [
                        {"role": "user", "content": "Hello"}
                    ]
                }
            )
            
            # Assertions
            assert result["response"] == "Hello, world!"
            assert result["provider_id"] == "test-ollama"
            mock_hub.get_available_instance.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_request_no_instances(self, provider, mock_hub):
        """Test handling when no instances available"""
        mock_hub.get_available_instance.return_value = None
        
        with pytest.raises(RuntimeError, match="No Ollama instances available"):
            await provider.handle_request(
                method="chat",
                params={"model": "llama3.2", "messages": []}
            )
    
    @pytest.mark.asyncio
    async def test_parameter_validation(self, provider):
        """Test parameter validation"""
        # Missing required parameter
        with pytest.raises(ValueError, match="Missing required parameter: model"):
            await provider.handle_request(
                method="chat",
                params={"messages": []}
            )
        
        # Invalid parameter type
        with pytest.raises(TypeError, match="messages must be a list"):
            await provider.handle_request(
                method="chat",
                params={"model": "llama3.2", "messages": "invalid"}
            )
    
    @pytest.mark.asyncio
    async def test_error_reporting(self, provider, mock_hub):
        """Test error reporting to hub"""
        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_post.side_effect = Exception("Network error")
            
            with pytest.raises(Exception):
                await provider.handle_request(
                    method="chat",
                    params={"model": "llama3.2", "messages": []}
                )
            
            # Verify error was reported to hub
            mock_hub.report_error.assert_called()
```

### Testing Hubs

```python
# tests/unit/hub/test_ollama_hub.py
import pytest
from unittest.mock import Mock, AsyncMock, patch
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.configs import OllamaConfig
from gleitzeit.hub.base import ResourceStatus

class TestOllamaHub:
    """Test OllamaHub functionality"""
    
    @pytest.fixture
    async def hub(self):
        """Create OllamaHub instance"""
        hub = OllamaHub(
            hub_id="test-hub",
            max_instances=5,
            health_check_interval=30
        )
        await hub.initialize()
        return hub
    
    @pytest.mark.asyncio
    async def test_start_instance(self, hub):
        """Test starting an Ollama instance"""
        config = OllamaConfig(
            host="localhost",
            port=11434
        )
        
        with patch.object(hub, 'check_health', return_value=True):
            instance = await hub.start_instance(config)
            
            assert instance.id == "ollama-localhost-11434"
            assert instance.endpoint == "http://localhost:11434"
            assert instance.status == ResourceStatus.HEALTHY
            assert instance.id in hub.instances
    
    @pytest.mark.asyncio
    async def test_health_check(self, hub):
        """Test health check functionality"""
        instance = Mock(
            endpoint="http://localhost:11434",
            status=ResourceStatus.HEALTHY
        )
        
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_get.return_value.__aenter__.return_value = mock_response
            
            is_healthy = await hub.check_health(instance)
            assert is_healthy is True
    
    @pytest.mark.asyncio
    async def test_get_available_instance(self, hub):
        """Test getting available instance"""
        # Add healthy instance
        healthy_instance = Mock(
            id="healthy",
            status=ResourceStatus.HEALTHY
        )
        hub.instances["healthy"] = healthy_instance
        
        # Add unhealthy instance
        unhealthy_instance = Mock(
            id="unhealthy",
            status=ResourceStatus.UNHEALTHY
        )
        hub.instances["unhealthy"] = unhealthy_instance
        
        # Should return healthy instance
        instance = await hub.get_available_instance()
        assert instance == healthy_instance
    
    @pytest.mark.asyncio
    async def test_auto_recovery(self, hub):
        """Test automatic recovery of unhealthy instances"""
        hub.enable_auto_recovery = True
        
        instance = Mock(
            id="test",
            status=ResourceStatus.UNHEALTHY,
            config=OllamaConfig(host="localhost", port=11434)
        )
        
        with patch.object(hub, '_restart_instance', return_value=None) as mock_restart:
            with patch.object(hub, 'check_health', return_value=True):
                await hub._attempt_recovery(instance)
                mock_restart.assert_called_once_with(instance)
```

### Testing Execution Engine

```python
# tests/unit/core/test_execution_engine.py
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.registry import ProtocolProviderRegistry

class TestExecutionEngine:
    """Test ExecutionEngine functionality"""
    
    @pytest.fixture
    async def mock_registry(self):
        """Create mock registry"""
        registry = Mock(spec=ProtocolProviderRegistry)
        mock_provider = Mock()
        mock_provider.handle_request = AsyncMock(return_value={"result": "success"})
        registry.get_provider_for_method = AsyncMock(return_value=mock_provider)
        return registry
    
    @pytest.fixture
    async def mock_persistence(self):
        """Create mock persistence"""
        persistence = Mock()
        persistence.save_workflow = AsyncMock()
        persistence.save_task = AsyncMock()
        persistence.save_result = AsyncMock()
        persistence.get_workflow = AsyncMock()
        return persistence
    
    @pytest.fixture
    async def engine(self, mock_registry, mock_persistence):
        """Create ExecutionEngine"""
        return ExecutionEngine(
            registry=mock_registry,
            persistence=mock_persistence,
            max_parallel_tasks=5
        )
    
    @pytest.mark.asyncio
    async def test_submit_workflow(self, engine, mock_persistence):
        """Test workflow submission"""
        workflow = {
            "name": "Test Workflow",
            "tasks": [
                {
                    "id": "task1",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "parameters": {"model": "test"}
                }
            ]
        }
        
        workflow_id = await engine.submit_workflow(workflow)
        
        assert workflow_id.startswith("wf-")
        mock_persistence.save_workflow.assert_called_once()
        assert workflow_id in engine.active_workflows
    
    @pytest.mark.asyncio
    async def test_execute_task(self, engine, mock_registry):
        """Test task execution"""
        task = {
            "id": "task1",
            "protocol": "llm/v1",
            "method": "chat",
            "parameters": {"model": "test"}
        }
        
        context = Mock()
        context.results = {}
        
        result = await engine.execute_task(task, context)
        
        assert result == {"result": "success"}
        assert context.results["task1"] == {"result": "success"}
        mock_registry.get_provider_for_method.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_dependency_resolution(self, engine):
        """Test task dependency resolution"""
        tasks = [
            {"id": "task1", "dependencies": []},
            {"id": "task2", "dependencies": ["task1"]},
            {"id": "task3", "dependencies": ["task1", "task2"]},
            {"id": "task4", "dependencies": []},
        ]
        
        layers = engine.dependency_resolver.resolve_dependencies(tasks)
        
        assert len(layers) == 3
        assert set(layers[0]) == {"task1", "task4"}
        assert set(layers[1]) == {"task2"}
        assert set(layers[2]) == {"task3"}
```

## Integration Testing

### Testing Provider-Hub Integration

```python
# tests/integration/test_provider_hub_integration.py
import pytest
import asyncio
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.configs import OllamaConfig

@pytest.mark.integration
@pytest.mark.ollama
class TestProviderHubIntegration:
    """Test integration between providers and hubs"""
    
    @pytest.mark.asyncio
    async def test_ollama_provider_hub_integration(self):
        """Test OllamaProvider with real OllamaHub"""
        # Create hub
        hub = OllamaHub(hub_id="test-hub")
        await hub.initialize()
        
        # Start instance
        config = OllamaConfig(host="localhost", port=11434)
        instance = await hub.start_instance(config)
        
        # Create provider
        provider = OllamaProvider(
            provider_id="test",
            ollama_hub=hub
        )
        await provider.initialize()
        
        try:
            # Execute request
            result = await provider.handle_request(
                method="chat",
                params={
                    "model": "llama3.2",
                    "messages": [
                        {"role": "user", "content": "Say hello"}
                    ]
                }
            )
            
            assert "response" in result
            assert result["provider_id"] == "test"
            
        finally:
            # Cleanup
            await provider.shutdown()
            await hub.stop()
```

### Testing Workflow Execution

```python
# tests/integration/test_workflow_execution.py
import pytest
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.registry import ProtocolProviderRegistry
from gleitzeit.persistence import UnifiedPersistenceAdapter
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.hub.ollama_hub import OllamaHub

@pytest.mark.integration
class TestWorkflowExecution:
    """Test complete workflow execution"""
    
    @pytest.mark.asyncio
    async def test_simple_workflow(self):
        """Test execution of simple workflow"""
        # Setup
        persistence = UnifiedPersistenceAdapter(adapter_type="memory")
        await persistence.initialize()
        
        registry = ProtocolProviderRegistry()
        
        hub = OllamaHub()
        await hub.initialize()
        
        provider = OllamaProvider(ollama_hub=hub)
        await provider.initialize()
        await registry.register_provider("llm/v1", provider)
        
        engine = ExecutionEngine(
            registry=registry,
            persistence=persistence
        )
        
        # Define workflow
        workflow = {
            "name": "Test Workflow",
            "tasks": [
                {
                    "id": "task1",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Count to 3"}
                        ]
                    }
                }
            ]
        }
        
        try:
            # Execute workflow
            workflow_id = await engine.submit_workflow(workflow)
            
            # Wait for completion
            await asyncio.sleep(5)
            
            # Check results
            results = await persistence.get_workflow_results(workflow_id)
            assert results is not None
            assert "task1" in results
            
        finally:
            # Cleanup
            await engine.shutdown()
            await provider.shutdown()
            await hub.stop()
    
    @pytest.mark.asyncio
    async def test_workflow_with_dependencies(self):
        """Test workflow with task dependencies"""
        # Similar setup...
        
        workflow = {
            "name": "Dependent Workflow",
            "tasks": [
                {
                    "id": "generate",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Generate a number"}
                        ]
                    }
                },
                {
                    "id": "process",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["generate"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Double this: ${generate.response}"}
                        ]
                    }
                }
            ]
        }
        
        # Execute and verify dependencies were respected
```

## End-to-End Testing

### Testing Complete Workflows

```python
# tests/e2e/test_complete_workflows.py
import pytest
import httpx
from pathlib import Path

@pytest.mark.e2e
class TestE2EWorkflows:
    """End-to-end workflow tests"""
    
    @pytest.fixture
    def api_client(self):
        """Create API client"""
        return httpx.AsyncClient(base_url="http://localhost:8000")
    
    @pytest.mark.asyncio
    async def test_submit_and_execute_workflow(self, api_client):
        """Test complete workflow submission and execution"""
        # Read workflow file
        workflow_path = Path("examples/simple_llm_workflow.yaml")
        workflow_content = workflow_path.read_text()
        
        # Submit workflow
        response = await api_client.post(
            "/api/workflows",
            json={"workflow": workflow_content}
        )
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Poll for completion
        max_attempts = 30
        for _ in range(max_attempts):
            status_response = await api_client.get(
                f"/api/workflows/{workflow_id}"
            )
            status = status_response.json()["status"]
            
            if status == "completed":
                break
            elif status == "failed":
                pytest.fail("Workflow failed")
            
            await asyncio.sleep(2)
        
        # Get results
        results_response = await api_client.get(
            f"/api/workflows/{workflow_id}/results"
        )
        assert results_response.status_code == 200
        results = results_response.json()
        assert len(results) > 0
```

### Testing API Endpoints

```python
# tests/e2e/test_api_endpoints.py
import pytest
import httpx

@pytest.mark.e2e
class TestAPIEndpoints:
    """Test all API endpoints"""
    
    @pytest.fixture
    async def api_client(self):
        async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self, api_client):
        """Test health check endpoint"""
        response = await api_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    @pytest.mark.asyncio
    async def test_workflow_endpoints(self, api_client):
        """Test workflow CRUD operations"""
        # Create
        create_response = await api_client.post(
            "/api/workflows",
            json={
                "workflow": {
                    "name": "Test",
                    "tasks": []
                }
            }
        )
        assert create_response.status_code == 200
        workflow_id = create_response.json()["workflow_id"]
        
        # Read
        get_response = await api_client.get(f"/api/workflows/{workflow_id}")
        assert get_response.status_code == 200
        
        # List
        list_response = await api_client.get("/api/workflows")
        assert list_response.status_code == 200
        assert len(list_response.json()["workflows"]) > 0
        
        # Delete
        delete_response = await api_client.delete(f"/api/workflows/{workflow_id}")
        assert delete_response.status_code == 200
```

## Performance Testing

### Load Testing

```python
# tests/performance/test_load.py
import pytest
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from gleitzeit import GleitzeitClient

@pytest.mark.performance
class TestLoadPerformance:
    """Load and stress testing"""
    
    @pytest.mark.asyncio
    async def test_concurrent_workflows(self):
        """Test concurrent workflow execution"""
        client = GleitzeitClient()
        
        workflow = {
            "name": "Load Test",
            "tasks": [
                {
                    "id": "task1",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [{"role": "user", "content": "Hello"}]
                    }
                }
            ]
        }
        
        # Submit multiple workflows concurrently
        num_workflows = 50
        start_time = time.time()
        
        tasks = [
            client.submit_workflow(workflow)
            for _ in range(num_workflows)
        ]
        workflow_ids = await asyncio.gather(*tasks)
        
        # Wait for all to complete
        completion_tasks = [
            client.wait_for_completion(wf_id)
            for wf_id in workflow_ids
        ]
        await asyncio.gather(*completion_tasks)
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Assertions
        assert len(workflow_ids) == num_workflows
        assert duration < 60  # Should complete within 1 minute
        
        throughput = num_workflows / duration
        print(f"Throughput: {throughput:.2f} workflows/second")
```

### Benchmark Testing

```python
# tests/performance/test_benchmarks.py
import pytest

@pytest.mark.benchmark
class TestBenchmarks:
    """Performance benchmarks"""
    
    def test_parameter_substitution_performance(self, benchmark):
        """Benchmark parameter substitution"""
        from gleitzeit.core.parameter_resolver import ParameterResolver
        
        resolver = ParameterResolver()
        context = {
            "results": {
                "task1": {"response": "Hello"},
                "task2": {"data": {"value": 42}}
            }
        }
        
        params = {
            "input": "${task1.response}",
            "value": "${task2.data.value}",
            "nested": {
                "ref": "${task1.response}"
            }
        }
        
        result = benchmark(resolver.resolve_parameters, params, context)
        assert result["input"] == "Hello"
        assert result["value"] == 42
    
    def test_workflow_parsing_performance(self, benchmark):
        """Benchmark workflow parsing"""
        from gleitzeit.core.workflow_loader import WorkflowLoader
        
        loader = WorkflowLoader()
        workflow_yaml = """
        name: Benchmark Workflow
        tasks:
          - id: task1
            method: test
            parameters:
              key: value
        """ * 100  # Large workflow
        
        result = benchmark(loader.parse_yaml, workflow_yaml)
        assert len(result["tasks"]) == 100
```

## Test Fixtures and Mocks

### Common Fixtures

```python
# tests/fixtures/mocks.py
from unittest.mock import Mock, AsyncMock
from datetime import datetime

def create_mock_workflow(num_tasks=3):
    """Create mock workflow"""
    return {
        "id": "wf-test",
        "name": "Test Workflow",
        "tasks": [
            {
                "id": f"task{i}",
                "protocol": "llm/v1",
                "method": "chat",
                "parameters": {"model": "test"}
            }
            for i in range(num_tasks)
        ]
    }

def create_mock_provider():
    """Create mock provider"""
    provider = Mock()
    provider.provider_id = "mock-provider"
    provider.protocol_id = "mock/v1"
    provider.handle_request = AsyncMock(return_value={"result": "success"})
    provider.initialize = AsyncMock()
    provider.shutdown = AsyncMock()
    return provider

def create_mock_hub():
    """Create mock resource hub"""
    hub = Mock()
    hub.hub_id = "mock-hub"
    hub.get_available_instance = AsyncMock(return_value=Mock(
        id="instance-1",
        endpoint="http://localhost:8000",
        status="HEALTHY"
    ))
    hub.start_instance = AsyncMock()
    hub.stop_instance = AsyncMock()
    return hub
```

### Shared Test Configuration

```python
# tests/conftest.py
import pytest
import asyncio
import tempfile
from pathlib import Path

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def temp_dir():
    """Create temporary directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def mock_config():
    """Create mock configuration"""
    return {
        "persistence": {
            "type": "memory"
        },
        "execution": {
            "max_parallel_tasks": 5,
            "task_timeout": 10
        }
    }

@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton instances between tests"""
    from gleitzeit.core.registry import ProtocolProviderRegistry
    ProtocolProviderRegistry._instance = None
    yield
```

## Testing Best Practices

### 1. Test Isolation
```python
# Each test should be independent
class TestExample:
    def setup_method(self):
        """Setup before each test"""
        self.data = []
    
    def teardown_method(self):
        """Cleanup after each test"""
        self.data.clear()
```

### 2. Async Testing
```python
# Always use pytest.mark.asyncio for async tests
@pytest.mark.asyncio
async def test_async_function():
    result = await async_function()
    assert result is not None
```

### 3. Mocking External Dependencies
```python
# Mock external services
@patch('requests.get')
def test_external_api(mock_get):
    mock_get.return_value.json.return_value = {"status": "ok"}
    result = function_that_calls_api()
    assert result["status"] == "ok"
```

### 4. Parameterized Testing
```python
@pytest.mark.parametrize("input,expected", [
    ("hello", "HELLO"),
    ("world", "WORLD"),
    ("", ""),
])
def test_uppercase(input, expected):
    assert input.upper() == expected
```

### 5. Testing Error Cases
```python
def test_error_handling():
    with pytest.raises(ValueError, match="Invalid input"):
        function_that_raises("invalid")
```

## Continuous Integration

### GitHub Actions Configuration

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11']
    
    services:
      redis:
        image: redis:alpine
        ports:
          - 6379:6379
      
      ollama:
        image: ollama/ollama
        ports:
          - 11434:11434
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install dependencies
        run: |
          pip install poetry
          poetry install
      
      - name: Run tests
        run: |
          poetry run pytest tests/ \
            --cov=src/gleitzeit \
            --cov-report=xml \
            --junit-xml=test-results.xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

## Test Commands

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/unit/providers/test_ollama_provider.py

# Run specific test class
pytest tests/unit/providers/test_ollama_provider.py::TestOllamaProvider

# Run specific test method
pytest tests/unit/providers/test_ollama_provider.py::TestOllamaProvider::test_initialization

# Run tests by marker
pytest -m unit           # Unit tests only
pytest -m integration    # Integration tests only
pytest -m "not slow"     # Skip slow tests

# Run with coverage
pytest --cov=src/gleitzeit --cov-report=html

# Run in parallel
pytest -n auto

# Run with verbose output
pytest -vv

# Run and stop on first failure
pytest -x

# Run last failed tests
pytest --lf
```

### Test Coverage

```bash
# Generate coverage report
pytest --cov=src/gleitzeit --cov-report=term-missing

# Generate HTML report
pytest --cov=src/gleitzeit --cov-report=html
open htmlcov/index.html

# Check coverage threshold
pytest --cov=src/gleitzeit --cov-fail-under=80
```

### Performance Testing

```bash
# Run benchmarks
pytest tests/performance --benchmark-only

# Compare benchmarks
pytest tests/performance --benchmark-compare

# Save benchmark results
pytest tests/performance --benchmark-save=baseline

# Profile tests
pytest tests/performance --profile
```

## Testing Checklist

### Before Committing

- [ ] All tests pass locally
- [ ] Code coverage > 80%
- [ ] No lint errors
- [ ] Type checking passes
- [ ] Documentation updated
- [ ] Integration tests pass
- [ ] Performance benchmarks acceptable

### Test Categories

- [ ] **Unit Tests**: Individual components
- [ ] **Integration Tests**: Component interactions
- [ ] **E2E Tests**: Full workflow execution
- [ ] **Performance Tests**: Load and benchmarks
- [ ] **Security Tests**: Input validation, sanitization
- [ ] **Error Tests**: Error handling and recovery

## Summary

Comprehensive testing in Gleitzeit includes:
- **Unit tests** for individual components (60%)
- **Integration tests** for component interactions (30%)
- **E2E tests** for complete workflows (10%)
- **Performance tests** for load and benchmarks
- **Fixtures and mocks** for test isolation
- **CI/CD integration** for automated testing
- **Coverage tracking** to ensure quality

Follow the testing pyramid and best practices to maintain high code quality and reliability.