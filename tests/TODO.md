# Test Suite TODO

## Overview
This directory contains the new test suite for Gleitzeit. Tests are organized by component/feature area.

## Test Organization

### ✅ Completed Tests

#### `/providers/`
- `test_python_provider.py` - Comprehensive tests for secure PythonProvider
  - File execution (local and Docker)
  - Security model validation
  - No eval/exec vulnerabilities
  - Timeout handling
  - Environment variables and arguments

#### `/protocols/`
- *TODO: Protocol tests needed*

### 📝 Tests Needed

#### High Priority Tests

##### ProtocolProvider Base Class (`/providers/`)
- [ ] `test_protocol_provider.py`
  - Provider lifecycle (initialize, shutdown)
  - Method registration and discovery
  - Error handling patterns
  - Abstract method enforcement
  - Provider metadata

##### Protocol Definitions (`/protocols/`)
- [ ] `test_llm_protocol.py`
  - LLM protocol compliance
  - Method validation
  - Parameter schemas
  - Response formats

- [ ] `test_python_protocol.py`
  - Python execution protocol
  - Security constraints
  - File-only execution

- [ ] `test_mcp_protocol.py`
  - MCP tool protocol
  - Tool discovery
  - Tool execution

##### Registry Tests (`/registry/`)
- [ ] `test_provider_registry.py`
  - Provider registration
  - Method-to-provider mapping
  - Protocol compliance checking
  - Auto-discovery of methods

##### Hub Architecture (`/hub/`)
- [ ] `test_hub_provider.py`
  - Resource management
  - Load balancing
  - Health monitoring
  - Circuit breaker

- [ ] `test_persistence.py`
  - Redis adapter
  - SQL adapter
  - State persistence
  - Distributed locking

#### Medium Priority Tests

##### Enhanced Client (`/client/`)
- [ ] `test_enhanced_client.py`
  - Provider initialization
  - Auto-discovery
  - Fallback mechanisms

##### Batch Processing (`/batch/`)
- [ ] `test_batch_processor.py`
  - Batch execution
  - Error handling in batches
  - Result aggregation

##### Error Handling (`/errors/`)
- [ ] `test_error_handling.py`
  - Error propagation
  - Error formatting
  - Recovery mechanisms

#### Low Priority Tests

##### CLI (`/cli/`)
- [ ] `test_cli.py`
  - Command parsing
  - Workflow execution
  - Output formatting

##### Examples (`/examples/`)
- [ ] `test_examples.py`
  - Validate all example workflows
  - Documentation accuracy

## Test Guidelines

### Security Tests
- **No eval/exec**: Ensure no arbitrary code execution
- **Input validation**: Test all input boundaries
- **SQL injection**: Verify parameterized queries
- **Path traversal**: Check file access restrictions

### Performance Tests
- **Timeouts**: Verify timeout handling
- **Resource limits**: Check memory/CPU constraints
- **Connection pooling**: Test pool exhaustion
- **Concurrent execution**: Race condition testing

### Integration Tests
- **Provider integration**: Cross-provider workflows
- **Persistence integration**: State recovery
- **Registry integration**: Dynamic provider registration

## Running Tests

```bash
# Run all tests
pytest tests/

# Run specific test directory
pytest tests/providers/

# Run with coverage
pytest --cov=gleitzeit tests/

# Run specific test file
pytest tests/providers/test_python_provider.py

# Run with verbose output
pytest -v tests/
```

## Test Coverage Goals

- **Minimum coverage**: 80% overall
- **Critical paths**: 95% coverage
  - Security functions
  - Provider execution
  - Error handling
  
## Known Issues to Test

From ARCHITECTURE_INCONSISTENCIES.md:
1. **Bare except statements** - Ensure proper exception handling
2. **Print statements** - Should use logging
3. **SQL injection risks** - Verify safe queries
4. **Missing input validation** - Test boundaries
5. **No connection pooling** - Test resource exhaustion
6. **Inconsistent error handling** - Verify error propagation

## Contributing Tests

When adding new tests:
1. Follow existing test structure
2. Use descriptive test names
3. Include docstrings
4. Test both success and failure cases
5. Mock external dependencies
6. Keep tests fast and isolated

## Next Steps

1. **Immediate**: Create ProtocolProvider base tests
2. **Next**: Add protocol compliance tests
3. **Then**: Registry and hub tests
4. **Finally**: Integration tests