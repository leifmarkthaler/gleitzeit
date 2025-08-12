# Gleitzeit V4 Test Suite

This directory contains comprehensive tests for Gleitzeit V4, covering all major components and functionality.

## Test Structure

### Core Test Files
- `test_parameter_substitution.py` - Parameter substitution between workflow tasks
- `test_distributed_coordination.py` - Socket.IO distributed architecture tests  
- `test_provider_management.py` - Provider health monitoring and load balancing
- `test_error_handling.py` - Error scenarios and retry mechanisms (TODO)
- `test_complex_workflows.py` - Complex workflow patterns (TODO)
- `test_performance.py` - Performance and scalability tests (TODO)
- `test_cli_integration.py` - Command-line interface tests (TODO)

### Configuration Files
- `conftest.py` - Global pytest configuration and fixtures
- `requirements.txt` - Test dependencies
- `README.md` - This file

## Quick Start

### Install Test Dependencies
```bash
python run_tests.py install
```

### Run Basic Tests
```bash
python run_tests.py basic
```

### Run All Tests
```bash
python run_tests.py all
```

## Test Categories

### Unit Tests (`@pytest.mark.unit`)
Fast tests that test individual components in isolation.
```bash
pytest -m unit
```

### Integration Tests (`@pytest.mark.integration`)  
Tests that verify interaction between multiple components.
```bash
pytest -m integration
```

### Distributed Tests (`@pytest.mark.distributed`)
Tests that require Socket.IO and multiple processes.
```bash
python run_tests.py distributed
```

### Performance Tests (`@pytest.mark.performance`)
Tests that measure system performance and scalability.
```bash
python run_tests.py performance
```

### Slow Tests (`@pytest.mark.slow`)
Tests that take more than 5 seconds to complete.
```bash
pytest -m "not slow"  # Skip slow tests
pytest -m slow       # Run only slow tests
```

## Running Specific Tests

### Run a specific test file
```bash
python run_tests.py --test tests/test_parameter_substitution.py
```

### Run a specific test function
```bash
python run_tests.py --test tests/test_parameter_substitution.py::TestBasicParameterSubstitution::test_simple_field_substitution
```

### Run tests matching a pattern
```bash
pytest -k "parameter_substitution"
```

## Test Coverage

Run tests with coverage reporting:
```bash
python run_tests.py coverage
```

This generates:
- Terminal coverage report
- HTML coverage report in `htmlcov/`
- Fails if coverage is below 80%

## Manual Testing

Some tests include manual test runners for debugging:
```bash
python tests/test_parameter_substitution.py manual
python tests/test_distributed_coordination.py manual
python tests/test_provider_management.py manual
```

## Test Data and Fixtures

### Global Fixtures (conftest.py)
- `event_loop` - Async event loop for session
- `cleanup_tasks` - Automatic task cleanup  
- `temp_dir` - Temporary directory for test files
- `sample_task_data` - Sample task data structure
- `sample_workflow_data` - Sample workflow data structure
- `sample_protocol_spec` - Sample protocol specification

### Test-Specific Fixtures
Each test file defines its own fixtures for specific testing needs.

## Testing Best Practices

### Async Testing
```python
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is not None
```

### Mocking External Dependencies
```python
from unittest.mock import AsyncMock, patch

@patch('gleitzeit_v4.external_service')
async def test_with_mock(mock_service):
    mock_service.return_value = AsyncMock()
    # Test implementation
```

### Testing Error Conditions
```python
@pytest.mark.asyncio
async def test_error_handling():
    with pytest.raises(ValueError, match="Expected error message"):
        await function_that_should_fail()
```

### Performance Testing
```python
@pytest.mark.performance
@pytest.mark.asyncio
async def test_performance():
    import time
    start_time = time.time()
    
    # Run performance test
    
    elapsed_time = time.time() - start_time
    assert elapsed_time < 1.0, f"Too slow: {elapsed_time:.3f}s"
```

## Debugging Tests

### Verbose Output
```bash
pytest -v -s tests/test_specific.py
```

### Stop on First Failure
```bash
pytest -x tests/
```

### Debug with PDB
```bash
pytest --pdb tests/test_specific.py
```

### Show Local Variables on Failure
```bash
pytest --tb=long tests/
```

## Continuous Integration

The test suite is designed to work in CI environments:

### GitHub Actions Example
```yaml
- name: Install dependencies
  run: python run_tests.py install

- name: Run basic tests  
  run: python run_tests.py basic

- name: Run integration tests
  run: python run_tests.py integration

- name: Generate coverage report
  run: python run_tests.py coverage
```

## Test Development Guidelines

### Writing New Tests
1. Follow the existing test structure and naming conventions
2. Use appropriate pytest markers (`@pytest.mark.unit`, etc.)
3. Include docstrings explaining what each test verifies
4. Mock external dependencies appropriately
5. Clean up resources in test teardown

### Test Organization
- Group related tests in classes
- Use descriptive test method names
- Include both positive and negative test cases
- Test error conditions and edge cases

### Async Test Guidelines
- Always use `@pytest.mark.asyncio` for async tests
- Properly handle async context managers and cleanup
- Test timeout scenarios where appropriate
- Avoid blocking operations in async tests

## Troubleshooting

### Common Issues

**Import Errors**
- Make sure project root is in Python path
- Install test dependencies: `python run_tests.py install`

**Async Test Failures**
- Check that all async functions are properly awaited
- Ensure event loop is properly configured
- Look for unclosed coroutines or resources

**Socket.IO Tests Failing**
- Install Socket.IO dependencies: `pip install python-socketio[asyncio]`
- Check that ports are available for testing
- Ensure proper cleanup of Socket.IO connections

**Performance Tests Flaky**
- Run on a dedicated test machine when possible
- Increase timeout thresholds if system is slow
- Use `@pytest.mark.slow` for tests that take time

### Getting Help

1. Check test logs in `tests/test.log`
2. Run with verbose output: `pytest -v -s`
3. Use manual test runners for debugging
4. Check the main project documentation

## Future Improvements

- [ ] Add property-based testing with Hypothesis
- [ ] Implement mutation testing
- [ ] Add visual test reports
- [ ] Set up automated performance benchmarking
- [ ] Add integration with external monitoring tools