# Changelog

All notable changes to Gleitzeit will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.6] - 2024-08-25

### Added
- **Configurable Task Timeouts**: Task execution timeouts are now configurable via `task_timeout` parameter (default: 300 seconds)
- **Comprehensive Error Handling**: Improved task execution error handling with proper lifecycle management
- **Task Execution Protection**: Automatic timeout protection at both execution engine and provider levels
- **TASK_READY Event Emission**: Fixed missing event emission in dependency resolution for proper task pickup
- **Automatic Web UI**: The `serve` command now automatically starts the Web UI alongside the API server
- **Headless Mode**: New `--headless` flag for `serve` command to run API without the Web UI
- **UI Port Configuration**: New `--ui-port` and `--ui-host` options for customizing UI server settings

### Fixed
- **Task Execution Hanging Issue**: Fixed critical issue where tasks could get stuck in "executing" status indefinitely
- **Event Storm Prevention**: Removed duplicate TASK_COMPLETED event emissions causing database update storms
- **Task Status Synchronization**: Fixed workflow and task status reporting through proper architectural layering
- **Asyncio Task Management**: Implemented proper error callbacks and lifecycle management for async task execution
- **Timeout Error Propagation**: Tasks now properly fail with timeout errors that can be handled by retry logic

### Changed
- **ExecutionEngine Constructor**: Now accepts `task_timeout` parameter for configurable timeout duration
- **Configuration Schema**: Updated to use `task_timeout` instead of `default_timeout` for clarity
- **Error Messages**: Timeout errors now include the configured timeout duration in error messages
- **UI Package Structure**: Moved UI from `/src/ui` to `/src/gleitzeit/ui` for proper Python packaging
- **Serve Command Behavior**: Now starts both API and UI by default (use `--headless` for API-only mode)

### Technical Improvements
- Re-enabled `TaskCompletedHandler` for proper event flow from ExecutionEngine to QueueManager
- Added `get_workflow()` method to Client for proper API architectural compliance
- Fixed individual task status retrieval to get current status from persistence
- Implemented `_execute_task_skip_status_update_with_error_handling()` for comprehensive error handling
- Added proper task execution result logging with `_log_task_execution_result()` callback

## [0.0.5] - 2024-08-19

### Added
- **Unified Client Architecture**: New `GleitzeitClient` supporting API, Native, and Auto modes
- **Hub-Provider Separation**: Clean separation between resource management (hubs) and protocol implementation (providers)
- **Resource Management**: Integrated resource management for Ollama instances and Docker containers
- **Auto Mode**: Client automatically detects and uses API if available, falls back to native
- **Batch Processing**: Built-in batch file processing with pattern matching
- **Template Provider**: Jinja2 template support for dynamic workflow generation
- **Vision Support**: Image analysis capabilities through Ollama vision models (llava)
- **Unified Persistence**: Automatic fallback chain (Redis → SQLite → Memory)
- **CLI Commands**: New commands for batch processing, configuration, and status monitoring
- **Type Hinting**: Comprehensive type hints throughout the codebase
- **Documentation**: New user-friendly `/newdocs` with tutorials and examples

### Changed
- **Client API**: Simplified client initialization with mode selection
- **Provider Architecture**: Providers now work with hub system for resource allocation
- **Persistence Layer**: Unified adapter interface for all storage backends
- **Error Handling**: Improved error messages and retry logic
- **CLI Interface**: Streamlined commands with better defaults
- **Testing**: Expanded test coverage to 56+ test files

### Fixed
- Resource allocation issues in multi-instance scenarios
- Memory leaks in long-running workflows
- Timeout handling in async operations
- Parameter substitution edge cases
- Docker executor cleanup issues

### Security
- Added subprocess isolation for Python script execution
- Improved input validation for workflow parameters
- Sandboxed execution environment options

## [0.0.4] - 2024-08-10

### Added
- **MCP Protocol Support**: Integration with Model Context Protocol
- **Python Provider**: Execute Python scripts within workflows
- **Dependency Resolution**: Automatic task dependency management
- **Parallel Execution**: Tasks without dependencies run concurrently
- **Workflow Templates**: Pre-built workflow templates for common patterns

### Changed
- Refactored protocol registry for better extensibility
- Improved workflow validation and error reporting
- Enhanced logging throughout the system

### Fixed
- Task queue ordering issues
- Memory persistence data loss
- Workflow parameter validation bugs

## [0.0.3] - 2024-07-25

### Added
- **Ollama Integration**: Native support for Ollama LLM models
- **Persistence Layer**: SQLite and Redis backend support
- **Task Queue**: Advanced task scheduling and management
- **CLI Tool**: Command-line interface for workflow execution

### Changed
- Migrated from synchronous to fully async architecture
- Restructured package layout for better organization

### Fixed
- Connection pooling issues
- Async context manager leaks

## [0.0.2] - 2024-07-10

### Added
- **Workflow Engine**: Basic workflow execution engine
- **YAML Support**: Workflow definition via YAML files
- **Parameter Substitution**: Basic ${task.field} substitution

### Changed
- Improved error handling
- Better documentation

### Fixed
- Import path issues
- Configuration loading bugs

## [0.0.1] - 2024-06-28

### Added
- Initial release
- Basic task execution
- Simple workflow support
- Memory-based persistence

---

## Upcoming

### [0.0.6] - Planned
- Performance benchmarks and optimization
- API rate limiting
- Enhanced monitoring and metrics
- Webhook support for workflow notifications
- Migration guide for upgrading

### [0.1.0] - Future
- Production-ready features
- Complete API documentation (OpenAPI/Swagger)
- Enterprise deployment guides
- Advanced scheduling (cron-like)
- Workflow versioning

---

## Migration Notes

### Upgrading to 0.0.5
The unified client architecture in 0.0.5 maintains backward compatibility while adding new features:

```python
# Old way (still works)
from gleitzeit import ExecutionEngine
engine = ExecutionEngine()

# New way (recommended)
from gleitzeit import GleitzeitClient
async with GleitzeitClient() as client:
    await client.run_workflow("workflow.yaml")
```

### Breaking Changes
- None in 0.0.5 - Full backward compatibility maintained

### Deprecations
- Direct `ExecutionEngine` usage is deprecated in favor of `GleitzeitClient`
- Will be removed in v0.1.0

---

[0.0.5]: https://github.com/leifmarkthaler/gleitzeit/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/leifmarkthaler/gleitzeit/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/leifmarkthaler/gleitzeit/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/leifmarkthaler/gleitzeit/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/leifmarkthaler/gleitzeit/releases/tag/v0.0.1