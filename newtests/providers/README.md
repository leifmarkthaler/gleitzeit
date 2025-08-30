# Provider Tests Documentation

This directory contains comprehensive tests for the Gleitzeit provider system, including base providers, specialized implementations, and the protocol auto-generation framework.

## Test Files Overview

### Core Provider Tests

#### `test_python_provider.py`
**Purpose**: Tests the PythonProviderV2 implementation for file-based Python execution.

**Coverage**: 21 comprehensive tests covering:
- Protocol auto-generation from provider methods
- Subprocess execution with argument passing and JSON output parsing
- Thread execution with isolation
- File validation and syntax error detection
- Environment variable handling
- Working directory configuration
- Execution history tracking and management
- Timeout handling and error scenarios
- Trusted directory validation
- Provider lifecycle (initialize/shutdown)

**Key Features Tested**:
- Multiple execution modes (subprocess, thread, auto-selection)
- JSON output parsing and structured result handling
- Python file validation with syntax checking
- Security through file-only execution (no inline code)
- Environment variable passing and isolation
- Execution timeout and resource management

#### `test_python_provider_docker.py`
**Purpose**: Tests Docker-based execution for PythonProviderV2 with container isolation.

**Coverage**: 10 Docker-specific tests covering:
- Basic Docker execution with container pooling
- Environment variable passing to containers
- Error handling and exit code detection
- Timeout handling with container cleanup
- Container reuse and pooling validation
- Local import handling in containers
- Output parsing from containerized scripts
- Both direct Docker SDK and DockerHub execution paths

**Requirements**: Docker daemon running and `TEST_DOCKER=1` environment variable

#### `test_protocol_generation.py`
**Purpose**: Tests the automatic protocol generation functionality for all provider types.

**Coverage**: 18 tests covering:
- SimpleProvider protocol generation from `get_supported_methods()`
- UltraSimpleProvider protocol generation from `@method` decorators
- MCP-style capability-based protocol generation
- Protocol enable/disable functionality
- Factory-level protocol generation and configuration
- Protocol registration with registries
- Integration tests across multiple provider types

**Key Features Tested**:
- Automatic discovery of provider methods
- Parameter type extraction from Python type hints
- Required vs optional parameter detection
- MCP capability to ProtocolSpec conversion
- Return type annotation handling
- **kwargs method detection

#### `test_simple_provider.py`
**Purpose**: Tests the SimpleProvider base class functionality.

**Coverage**:
- Basic provider initialization
- Method execution and routing
- Error handling and retries
- Metrics collection
- Provider lifecycle (initialize/shutdown)

#### `test_ultra_simple.py`
**Purpose**: Tests the UltraSimpleProvider with decorator-based method routing.

**Coverage**:
- `@method` decorator functionality
- Automatic method discovery
- Parameter extraction from function signatures
- Smart parameter matching

### HTTP Provider Tests

#### `test_http_provider.py`
**Purpose**: Comprehensive testing of HTTP-based providers.

**Coverage**: 30+ tests including:
- HTTP method operations (GET, POST, PUT, DELETE, PATCH)
- Authentication (Bearer token, API key)
- Error handling and retries
- Session management
- Metrics collection
- Edge cases (malformed URLs, large responses)

#### `test_rest_provider.py`
**Purpose**: Tests RESTful API provider functionality.

**Coverage**:
- REST endpoint mapping
- Dynamic method creation from endpoint specifications
- Path parameter substitution
- Query parameter handling

### LLM Provider Tests

#### `test_ollama_provider.py`
**Purpose**: Tests the Ollama LLM provider implementation.

**Coverage**:
- Text generation methods
- Chat functionality
- Embeddings generation
- Model management
- Streaming responses

#### `test_ollama_provider2.py`
**Purpose**: Tests the simplified Ollama provider (V2).

**Coverage**:
- Simplified API design
- Code reduction validation (60%+ reduction)
- Backward compatibility

#### `test_ollama_provider3_compatibility.py`
**Purpose**: Tests Ollama V3 with protocol compatibility.

**Coverage**:
- LLM protocol compliance
- Method aliasing (generate/complete)
- Parameter preprocessing
- Response formatting

### Factory and Integration Tests

#### `test_factory.py`
**Purpose**: Tests the ProviderFactory pattern.

**Coverage**:
- Dynamic provider creation
- Configuration management
- Provider registration
- Protocol auto-generation at factory level

#### `test_mcp_provider.py`
**Purpose**: Tests Model Context Protocol (MCP) provider integration.

**Coverage**:
- MCP handshake and capability discovery
- JSON-RPC 2.0 communication
- Dynamic protocol generation from capabilities
- Universal MCP service support

## Protocol Auto-Generation

The protocol auto-generation system is a core feature that enables providers to automatically generate their protocol specifications from their implementation.

### How It Works

1. **Method Discovery**:
   - From `@method` decorated functions (UltraSimpleProvider)
   - From `get_supported_methods()` (SimpleProvider)
   - From MCP capabilities dictionary

2. **Type Extraction**:
   - Python type hints → ParameterType mapping
   - Optional/Union type handling
   - Default value extraction
   - Return type annotations

3. **Schema Generation**:
   - JSON Schema → ParameterSpec conversion
   - Nested object handling
   - Array item specifications
   - Constraint preservation (min/max, patterns, enums)

### Supported Python Types

| Python Type | ParameterType | Notes |
|------------|---------------|-------|
| `str` | STRING | Basic string type |
| `int` | INTEGER | Integer numbers |
| `float` | NUMBER | Floating point |
| `bool` | BOOLEAN | True/False |
| `None` | NULL | None type |
| `list`, `List[T]` | ARRAY | Lists and typed lists |
| `dict`, `Dict[K,V]` | OBJECT | Dictionaries |
| `set`, `Set[T]` | ARRAY | Sets become arrays |
| `tuple`, `Tuple[...]` | ARRAY | Tuples become arrays |
| `Optional[T]` | T | Unwrapped, marked not required |
| `Union[T1, T2]` | T1 | First non-None type |
| `Any` | STRING | Safe default |
| Custom classes | STRING | Dataclass, Enum, etc. |
| `Callable` | STRING | Function types |
| `datetime` | STRING | Date/time objects |
| `Path` | STRING | Path objects |

### Complex Function Support

The system handles complex real-world Python functions including:
- Keyword-only arguments (after `*,`)
- `*args` and `**kwargs`
- Nested generic types
- Forward references
- Lambda defaults
- TypeVars and Generics
- Async iterators and generators

## Test Support Files

### Python Test Scripts (`/newtests/pythontestscripts/`)

The Python provider tests use a collection of stable test scripts instead of temporary files:

#### Basic Functionality Scripts
- **`simple_hello.py`**: Basic execution with JSON output and argument handling
- **`env_reader.py`**: Environment variable reading and JSON output
- **`compute_intensive.py`**: Resource usage testing with timing

#### Error and Edge Case Scripts
- **`error_script.py`**: Controlled error conditions with proper exit codes
- **`syntax_error.py`**: Python syntax validation testing  
- **`timeout_script.py`**: Long-running process for timeout testing
- **`exception_raiser.py`**: Exception handling validation

#### Advanced Feature Scripts
- **`output_types.py`**: Multiple output types (stdout, stderr, warnings, JSON)
- **`import_local.py`** + **`math_utils.py`**: Local module import testing
- **`simple_no_exit.py`**: Thread-safe execution without sys.exit()

**Benefits of Stable Test Scripts**:
- No temporary file cleanup needed
- Consistent test behavior across runs  
- Easier debugging and test development
- Trusted directory compliance for security tests
- Reusable across different test suites

## Running Tests

### Run All Provider Tests
```bash
pytest newtests/providers/ -v
```

### Run Python Provider Tests
```bash
# Core functionality
pytest newtests/providers/test_python_provider.py -v

# Docker execution (requires Docker)
TEST_DOCKER=1 pytest newtests/providers/test_python_provider_docker.py -v
```

### Run Protocol Generation Tests
```bash
pytest newtests/providers/test_protocol_generation.py -v
```

### Run Specific Test Class
```bash
pytest newtests/providers/test_http_provider.py::TestHTTPAuthentication -v
```

### Run with Coverage
```bash
pytest newtests/providers/ --cov=gleitzeit.providers --cov-report=html
```

## Test Utilities

### Mock Providers
Several mock providers are defined for testing:
- `MockHTTPProvider` - HTTP operations testing
- `AuthenticatedHTTPProvider` - Authentication testing
- `TestSimpleProvider` - Basic provider testing
- `MCPStyleProvider` - MCP capability testing

### Fixtures
Common fixtures available:
- `http_provider` - Configured HTTP provider instance
- `auth_provider` - Provider with authentication
- `rest_provider` - REST API provider
- `ollama_provider` - Ollama LLM provider

## Adding New Tests

When adding new provider tests:

1. **Test Protocol Generation**: If your provider has unique method discovery or type patterns, add tests to `test_protocol_generation.py`

2. **Test Provider Functionality**: Create specific test files for provider implementations

3. **Test Edge Cases**: Include tests for error conditions, edge cases, and complex scenarios

4. **Document Type Mappings**: If introducing new type conversions, document them in this README

## Known Issues and Limitations

1. **Complex Type Defaults**: Some complex types (Callable, custom classes) default to STRING type
2. **Lambda Defaults**: Lambda default values cannot be properly serialized
3. **Circular References**: Forward references and circular types need careful handling
4. **Streaming Types**: AsyncIterator and Generator types have limited support

## Related Documentation

- `/src/gleitzeit/providers/base.py` - Base provider implementation
- `/src/gleitzeit/providers/ultra_simple.py` - Ultra-simple provider
- `/src/gleitzeit/core/protocol.py` - Protocol specifications
- `/PROTOCOL_INTEGRATION_COMPLETE.md` - Protocol integration details