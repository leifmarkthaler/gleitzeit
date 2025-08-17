# GleitzeitClient Test Suite

Comprehensive test suite for the unified Gleitzeit Python client API (v0.0.5).

## Overview

This test suite covers all functionality of the unified `GleitzeitClient` class located at `/src/gleitzeit/client.py`:

- **Task Management**: Submit, retrieve, monitor, and cancel tasks
- **Workflow Management**: Create and manage multi-task workflows with dependencies
- **Resource Management**: Register and monitor computational resources across hubs
- **Unified Persistence**: Memory, SQLite, and Redis backends with automatic fallback
- **System Operations**: Health checks, statistics, cleanup, and cross-domain operations
- **Integration Scenarios**: Real-world usage patterns and performance testing

## Single Client Architecture

As of v0.0.5, Gleitzeit uses a **single unified client** that combines:
- Automatic persistence fallback (Redis → SQLite → Memory)
- Hub-provider separation architecture
- Cross-domain task and resource management
- Unified queue management with persistence

## Test Structure

```
tests/client/
├── conftest.py                    # Shared fixtures and test setup
├── test_task_management.py        # Task operations tests
├── test_workflow_management.py    # Workflow operations tests
├── test_resource_management.py    # Resource operations tests
├── test_persistence_system.py     # Persistence and system tests
├── test_client_integration.py     # Integration and performance tests
└── README.md                      # This file
```

## Test Categories

### Unit Tests
- **Task Management** (`test_task_management.py`)
  - Task submission with various parameters
  - Task retrieval and status checking
  - Task waiting and cancellation
  - Task statistics

- **Workflow Management** (`test_workflow_management.py`)
  - Workflow submission with dependencies
  - Workflow retrieval and task listing
  - Parameter substitution patterns
  - Complex dependency graphs

- **Resource Management** (`test_resource_management.py`)
  - Resource registration and retrieval
  - Resource metrics collection
  - Resource utilization tracking
  - Cross-domain task-resource relationships

### Integration Tests
- **Persistence and System** (`test_persistence_system.py`)
  - Client initialization and lifecycle
  - Multiple persistence backend testing
  - Context manager functionality
  - Health checks and error handling

- **Client Integration** (`test_client_integration.py`)
  - Realistic usage scenarios
  - Performance and scalability tests
  - Error recovery scenarios
  - Edge cases and compatibility

## Running Tests

### Run All Client Tests
```bash
# From project root
pytest tests/client/ -v

# With coverage
pytest tests/client/ --cov=src/gleitzeit.client --cov-report=term-missing
```

### Run Specific Test Categories
```bash
# Task management tests only
pytest tests/client/test_task_management.py -v

# Workflow tests only
pytest tests/client/test_workflow_management.py -v

# Resource tests only
pytest tests/client/test_resource_management.py -v

# System tests only
pytest tests/client/test_persistence_system.py -v

# Integration tests only
pytest tests/client/test_client_integration.py -v
```

### Run by Test Type
```bash
# Unit tests (fast, no external dependencies)
pytest tests/client/ -m "not integration" -v

# Integration tests (slower, with persistence)
pytest tests/client/test_client_integration.py -v

# Memory persistence tests only
pytest tests/client/ -k "memory" -v

# SQLite persistence tests only
pytest tests/client/ -k "sqlite" -v
```

### Run Specific Test Classes
```bash
# Task submission tests
pytest tests/client/test_task_management.py::TestTaskSubmission -v

# Workflow submission tests
pytest tests/client/test_workflow_management.py::TestWorkflowSubmission -v

# Resource utilization tests
pytest tests/client/test_resource_management.py::TestResourceUtilization -v

# Client initialization tests
pytest tests/client/test_persistence_system.py::TestClientInitialization -v
```

## Test Configuration

### Pytest Configuration
The tests use these pytest plugins and features:
- `pytest-asyncio` for async test support
- `pytest-mock` for mocking
- `pytest-cov` for coverage reporting
- Custom fixtures for client setup

### Environment Variables
```bash
# Enable debug logging during tests
export GLEITZEIT_LOG_LEVEL=DEBUG

# Use specific persistence for integration tests
export GLEITZEIT_TEST_PERSISTENCE=memory

# Test with real Redis (if available)
export GLEITZEIT_REDIS_URL=redis://localhost:6379/15
```

## Test Fixtures

### Key Fixtures (`conftest.py`)

- **`memory_client`**: Unified client with memory persistence (real implementation)
- **`sqlite_client`**: Unified client with SQLite persistence (real implementation)
- **`client_with_mocks`**: Unified client with mocked dependencies (fast unit tests)
- **`sample_task`**: Pre-configured Task object for testing
- **`sample_workflow`**: Pre-configured Workflow object for testing
- **`sample_resource`**: Sample resource data for testing
- **`temp_db_path`**: Temporary SQLite database path

### Mock Objects
- **`mock_persistence`**: Mock UnifiedPersistenceAdapter
- **`mock_queue_manager`**: Mock QueueManager
- **`MockAsyncContextManager`**: Helper for testing async context managers

## Test Patterns

### Async Test Pattern
```python
@pytest.mark.asyncio
async def test_async_operation(memory_client):
    result = await memory_client.some_async_operation()
    assert result is not None
```

### Mocked Test Pattern
```python
@pytest.mark.asyncio
async def test_with_mocks(client_with_mocks):
    client_with_mocks.adapter.some_method.return_value = expected_value
    
    result = await client_with_mocks.operation()
    
    assert result == expected_value
    client_with_mocks.adapter.some_method.assert_called_once()
```

### Integration Test Pattern
```python
@pytest.mark.asyncio
async def test_integration_scenario(memory_client):
    # Submit data
    item = await memory_client.submit_item(data)
    
    # Verify persistence
    retrieved = await memory_client.get_item(item.id)
    assert retrieved is not None
    
    # Check system state
    stats = await memory_client.get_statistics()
    assert stats["total"] >= 1
```

## Coverage Goals

Target coverage levels:
- **Overall Client Coverage**: 95%+
- **Task Management**: 98%+
- **Workflow Management**: 95%+
- **Resource Management**: 90%+
- **Persistence Layer**: 85%+

### Coverage Reports
```bash
# Generate HTML coverage report
pytest tests/client/ --cov=src/gleitzeit.client --cov-report=html
open htmlcov/index.html

# Terminal coverage report
pytest tests/client/ --cov=src/gleitzeit.client --cov-report=term-missing

# XML coverage for CI
pytest tests/client/ --cov=src/gleitzeit.client --cov-report=xml
```

## Performance Benchmarks

### Baseline Performance Targets
- **Task Submission**: <10ms per task (memory), <50ms (SQLite)
- **Workflow Submission**: <100ms for 10-task workflow
- **Resource Registration**: <5ms per resource
- **Statistics Queries**: <20ms
- **Bulk Operations**: 100+ tasks/second

### Performance Test Examples
```bash
# Run performance tests
pytest tests/client/test_client_integration.py::TestPerformanceScenarios -v

# Run with timing
pytest tests/client/ --durations=10
```

## Debugging Tests

### Debug Failed Tests
```bash
# Run with pdb on failure
pytest tests/client/ --pdb

# Verbose output with logging
pytest tests/client/ -v -s --log-cli-level=DEBUG

# Run single test with full output
pytest tests/client/test_task_management.py::TestTaskSubmission::test_submit_task_basic -v -s
```

### Common Debug Commands
```python
# In test code - add breakpoint
import pdb; pdb.set_trace()

# Print client state
print(f"Client initialized: {client._initialized}")
print(f"Adapter type: {type(client.adapter)}")
print(f"Queue manager: {client.queue_manager}")
```

## CI/CD Integration

### GitHub Actions Example
```yaml
- name: Run Client Tests
  run: |
    pytest tests/client/ \
      --cov=src/gleitzeit.client \
      --cov-report=xml \
      --cov-report=term-missing \
      --junit-xml=client-test-results.xml

- name: Upload Coverage
  uses: codecov/codecov-action@v3
  with:
    file: ./coverage.xml
    flags: client
```

### Test Matrix
The tests should pass on:
- Python 3.9, 3.10, 3.11, 3.12
- Linux, macOS, Windows
- With/without Redis available
- Memory and SQLite persistence

## Contributing

### Adding New Tests
1. Choose appropriate test file based on functionality
2. Follow existing test patterns and naming
3. Use appropriate fixtures (mocked vs. real persistence)
4. Add docstrings explaining test purpose
5. Ensure tests are independent and can run in any order

### Test Naming Convention
- Test files: `test_<functionality>.py`
- Test classes: `Test<Functionality>`
- Test methods: `test_<specific_behavior>`

Example:
```python
class TestTaskManagement:
    @pytest.mark.asyncio
    async def test_submit_task_with_dependencies(self, memory_client):
        """Test submitting task that depends on other tasks"""
        # Test implementation
```

### Mock vs Real Testing
- **Use mocks** for unit tests focusing on client logic
- **Use real persistence** for integration tests
- **Use memory persistence** for most integration tests (fast)
- **Use SQLite** for persistence-specific testing
- **Avoid Redis** in CI unless specifically testing Redis features

## Troubleshooting

### Common Issues

1. **Async Test Failures**
   ```python
   # Wrong - missing asyncio mark
   def test_async_function():
       await client.operation()
   
   # Correct
   @pytest.mark.asyncio
   async def test_async_function():
       await client.operation()
   ```

2. **Fixture Scope Issues**
   ```python
   # Wrong - session scope with async
   @pytest.fixture(scope="session")
   async def client():
       return await create_client()
   
   # Correct - function scope
   @pytest.fixture
   async def client():
       c = await create_client()
       yield c
       await c.shutdown()
   ```

3. **Mock Configuration**
   ```python
   # Wrong - mock not properly configured
   mock.method = Mock()
   
   # Correct - async mock for async methods
   mock.method = AsyncMock()
   ```

### Getting Help
- Check test output for detailed error messages
- Use `-v` flag for verbose test output
- Use `--tb=long` for full tracebacks
- Run single test with `-s` to see print statements
- Check the conftest.py for available fixtures