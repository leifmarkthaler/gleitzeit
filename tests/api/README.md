# Gleitzeit API Test Suite

Comprehensive test suite for the Gleitzeit REST API, covering all endpoints, error handling, and integration scenarios.

## Overview

The test suite contains **400+ tests** organized into 8 test modules:

1. **System Endpoints** (`test_system_endpoints.py`) - 15 tests
   - Root endpoint, health checks, status monitoring
   - Provider and protocol discovery
   - Error handling for uninitialized system

2. **Workflow Endpoints** (`test_workflow_endpoints.py`) - 18 tests
   - Workflow submission and status tracking
   - File upload support
   - Workflow cancellation
   - Background execution verification

3. **Task Execution** (`test_task_endpoints.py`) - 20 tests
   - Single task submission
   - Task status monitoring
   - Priority levels and retry configuration
   - Failure handling

4. **Convenience Endpoints** (`test_convenience_endpoints.py`) - 20 tests
   - Python code execution
   - LLM chat interface
   - Batch file processing
   - Model selection and parameters

5. **Template Endpoints** (`test_template_endpoints.py`) - 15 tests
   - Research, code, analysis, chat templates
   - Parameter validation
   - Template workflow generation

6. **Error Handling** (`test_error_handling.py`) - 30 tests
   - HTTP status codes
   - Input validation and sanitization
   - SQL injection and XSS protection
   - Resource limits and timeouts

7. **Integration Tests** (`test_integration.py`) - 15 tests
   - End-to-end workflow execution
   - Cross-endpoint integration
   - Data flow and parameter substitution
   - Concurrent operations

8. **Fixtures and Utilities** (`conftest.py`)
   - Mock execution engine
   - Mock persistence backend
   - Sample request/response data
   - Test client setup

## Installation

```bash
# Install test dependencies
pip install -r tests/api/requirements.txt

# Or install with main requirements
pip install -e ".[test]"
```

## Running Tests

### Basic Usage

```bash
# Run all tests
pytest tests/api/

# Run with verbose output
pytest tests/api/ -v

# Run specific test file
pytest tests/api/test_system_endpoints.py

# Run specific test
pytest tests/api/test_system_endpoints.py::TestSystemEndpoints::test_root_endpoint
```

### Using Test Runner

```bash
# Run all tests with test runner
python tests/api/run_tests.py

# Run with coverage
python tests/api/run_tests.py --coverage

# Run unit tests only
python tests/api/run_tests.py --unit

# Run integration tests only
python tests/api/run_tests.py --integration
```

### Coverage Reports

```bash
# Generate coverage report
pytest tests/api/ --cov=gleitzeit.api --cov-report=html

# View coverage report
open htmlcov/index.html
```

## Test Categories

### Unit Tests
- Individual endpoint functionality
- Input validation
- Error responses
- Mock-based testing

### Integration Tests
- Multi-endpoint workflows
- Data flow verification
- System state consistency
- Real async execution

### Performance Tests
- Concurrent request handling
- Large payload processing
- Timeout behavior
- Resource limits

### Security Tests
- SQL injection protection
- XSS prevention
- Path traversal blocking
- Input sanitization

## Test Structure

Each test module follows a consistent structure:

```python
class TestFeatureGroup:
    """Test group description"""
    
    @pytest.mark.asyncio
    async def test_specific_feature(self, async_client, mock_fixture):
        """Test specific feature behavior"""
        # Arrange
        request_data = {...}
        
        # Act
        response = await async_client.post("/endpoint", json=request_data)
        
        # Assert
        assert response.status_code == 200
        assert response.json()["field"] == expected_value
```

## Fixtures

### Core Fixtures

- `async_client` - Async HTTP test client
- `sync_client` - Synchronous test client
- `mock_execution_engine` - Mocked execution engine
- `mock_persistence` - Mocked persistence backend
- `mock_batch_processor` - Mocked batch processor

### Data Fixtures

- `sample_task_request` - Valid task request
- `sample_workflow_request` - Valid workflow request
- `sample_task_result` - Mock task result
- `mock_template_result` - Mock template result
- `temp_workflow_file` - Temporary YAML file

## Assertions

The test suite verifies:

### Functional Requirements
- ✅ All endpoints return correct status codes
- ✅ Response data matches expected schema
- ✅ Workflows execute in background
- ✅ Tasks complete with proper results
- ✅ Templates generate valid workflows

### Non-Functional Requirements
- ✅ Concurrent requests handled correctly
- ✅ Large inputs processed or rejected gracefully
- ✅ Timeouts enforced properly
- ✅ Resources cleaned up on error
- ✅ System remains stable under load

### Security Requirements
- ✅ Malicious inputs sanitized
- ✅ Path traversal blocked
- ✅ SQL injection prevented
- ✅ XSS attacks mitigated
- ✅ Resource exhaustion prevented

## Coverage

Current test coverage:

```
Module                          Coverage
------------------------------------------
gleitzeit/api/main.py           95%
gleitzeit/api/client.py         88%
gleitzeit/api/__init__.py       100%
------------------------------------------
Overall                         93%
```

## CI/CD Integration

### GitHub Actions

```yaml
name: API Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - run: pip install -r tests/api/requirements.txt
      - run: pytest tests/api/ --cov=gleitzeit.api
```

### Local Pre-commit

```bash
# Add to .git/hooks/pre-commit
#!/bin/bash
python tests/api/run_tests.py --unit
```

## Debugging Tests

### Run with detailed output
```bash
pytest tests/api/ -vv --tb=long
```

### Run with debugging
```bash
pytest tests/api/ --pdb  # Drop into debugger on failure
```

### Run specific test with print statements
```bash
pytest tests/api/test_file.py::test_name -s
```

## Adding New Tests

1. **Choose appropriate module** or create new one
2. **Follow naming convention**: `test_<feature>_<behavior>`
3. **Use async functions** for async endpoints
4. **Mock external dependencies**
5. **Test both success and failure cases**
6. **Add docstrings** describing test purpose

Example:
```python
@pytest.mark.asyncio
async def test_new_feature_success(self, async_client, mock_execution_engine):
    """Test that new feature works correctly with valid input"""
    # Your test here
```

## Common Issues

### Import Errors
- Ensure `src/` is in Python path
- Install all requirements

### Async Warnings
- Use `pytest.mark.asyncio` decorator
- Use `async_client` fixture for async tests

### Mock Not Working
- Check fixture scope
- Verify mock is properly configured
- Use `patch` context manager when needed

## Performance Benchmarks

Typical test execution times:

- Full suite: ~30 seconds
- Unit tests only: ~20 seconds
- Integration tests: ~10 seconds
- Single module: ~2-5 seconds

## Contributing

1. Write tests for new features
2. Ensure existing tests pass
3. Maintain >90% coverage
4. Follow existing patterns
5. Update this README if needed