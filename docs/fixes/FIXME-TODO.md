# FIXME-TODO

## Technical Debt and Improvements Tracker

### Critical - System Breaking

#### 1. Fix Provider Registry Access During Execution
- **Problem**: Providers are registered but not accessible during task execution
- **Error**: "No providers available for python/v1::execute" even though provider is registered
- **Location**: `src/gleitzeit/core/execution_engine.py` - `_route_task_to_provider` method
- **Impact**: No tasks can execute, system is non-functional
- **Solution**: Fix provider registry access in execution engine

#### 2. Fix timedelta Import Error in Retry Manager
- **Problem**: UnboundLocalError: cannot access local variable 'timedelta' 
- **Location**: `src/gleitzeit/core/event_driven_retry_manager.py` line 126
- **Impact**: Tasks that fail cannot be retried, crashes error handling
- **Solution**: Add missing import: `from datetime import timedelta`

#### 3. Fix create_task_failed_event Arguments
- **Problem**: "create_task_failed_event() got an unexpected keyword argument 'task_name'"
- **Location**: Task cleanup after execution error
- **Impact**: Failed tasks cannot be properly cleaned up
- **Solution**: Fix the function call to use correct parameters

### High Priority

#### 4. Fix Task Execution with Missing Provider (Original Issue)
- **Problem**: Tasks get stuck in "running" state when no provider exists for the protocol
- **Expected**: Task should fail immediately with error "No provider registered for protocol: X"
- **Location**: Task execution/queue logic
- **Solution**: Check for provider availability before queuing task

#### 5. Fix Workflow Format Incompatibility
- **Problem**: Example workflows use old format (method: "python/execute" with priority as int)
- **API Expects**: Separate protocol and method fields, priority as string
- **Affected**: All example workflows in /examples directory
- **Solution**: Either fix API to handle old format OR update all example workflows

#### 6. Fix API Providers/Protocols Display
- **Problem**: CLI commands for providers/protocols show errors
- **Location**: `src/gleitzeit/cli/main.py` - providers and protocols commands
- **Solution**: Fix formatting of API response data

#### 3. Change UI Backend
- **Current**: UI is using its own FastAPI backend (`gleitzeit.ui.api.app`)
- **Problem**: Creates a separate server instance, duplicates some API logic
- **Solution**: Make UI a static frontend that directly calls the main API
- **Tasks**:
  - [ ] Convert UI to pure static files (HTML/CSS/JS)
  - [ ] Update JavaScript to call main API endpoints directly
  - [ ] Remove duplicate API code in UI module
  - [ ] Serve static files from main API server
  - [ ] Update CLI to serve UI from same process as API

#### 4. Fix API Response Format Inconsistencies
- **Problem**: Some endpoints return workflow data as strings instead of dicts
- **Affected**: `/workflows` list endpoint
- **Solution**: Ensure all endpoints return consistent JSON structures

#### 5. Fix `/status` Endpoint Error
- **Problem**: 500 error - `'str' object has no attribute 'get'`
- **Location**: `src/gleitzeit/api/main.py` status endpoint
- **Solution**: Debug and fix the status endpoint response format

### Medium Priority

#### 4. Complete Event Persistence Integration
- **Current**: Infrastructure exists but not integrated into modern client
- **Files**: `src/gleitzeit/events/store.py` ready but unused
- **Solution**: Integrate EventStore with ModularGleitzeitClient

#### 5. Consolidate Event-Driven Persistence
- **Current**: Separate classes for event-driven versions
- **Files**: `unified_redis_events.py`, `unified_sqlalchemy_events.py`
- **Solution**: Make event-driven a configuration option, not separate classes

#### 6. Update Documentation
- **Problem**: CLI documentation (`docs/cli.md`) is outdated
- **Tasks**:
  - [ ] Document actual CLI commands
  - [ ] Remove references to non-existent commands
  - [ ] Add examples for new command structure

### Low Priority

#### 7. Add Missing CLI Commands
- [ ] `init` - Create workflow templates
- [ ] `validate` - Validate workflow files
- [ ] `config` - Manage configuration

#### 8. Improve Error Messages
- **Problem**: Some errors are too technical for end users
- **Solution**: Add user-friendly error messages with actionable suggestions

#### 9. Add CLI Progress Indicators
- **Problem**: Long-running operations show no progress
- **Solution**: Add progress bars for workflow execution, batch processing

### Code Quality

#### 10. Remove Deprecated Imports
- [ ] Fix commented imports in old CLI files
- [ ] Clean up unused imports across codebase

#### 11. Add Type Hints
- [ ] Complete type hints for all public methods
- [ ] Add mypy configuration and check

#### 12. Test Coverage
- [ ] Add tests for new CLI commands
- [ ] Test auto-start functionality
- [ ] Test UI/API integration

### Performance

#### 13. Optimize Workflow Polling
- **Current**: CLI polls every second for workflow completion
- **Solution**: Use WebSocket or Server-Sent Events for real-time updates

#### 14. Connection Pooling
- **Problem**: Each CLI command creates new HTTP client
- **Solution**: Implement connection pooling for better performance

### Security

#### 15. API Authentication in CLI
- **Problem**: CLI doesn't support authenticated API calls
- **Current State**: 
  - Auth system exists but is disabled by default (`GLEITZEIT_AUTH_ENABLED=false`)
  - API has auth middleware that can be enabled
  - CLI has no auth support at all (no token handling, no login command)
- **Solution**: 
  - Add `login` command to CLI that gets JWT token
  - Store token in config file or keyring
  - Add token to all HTTP requests when auth is enabled
  - Add `logout` command to clear stored credentials
  - Support for API keys as alternative to login

### Future Enhancements

#### 16. Interactive Mode
- [ ] Add REPL mode for CLI
- [ ] Tab completion for commands
- [ ] Command history

#### 17. Pipeline Support
- [ ] Allow piping workflow outputs to other commands
- [ ] Support for workflow composition via CLI

#### 18. Remote Server Management
- [ ] Add commands to manage remote Gleitzeit instances
- [ ] Server discovery via mDNS/Zeroconf

## Notes

- Items marked with high priority should be addressed before next release
- Medium priority items can be scheduled for future sprints
- Low priority items are nice-to-have improvements

## Contributing

When fixing an item:
1. Create a branch named `fix/item-number-description`
2. Update this file to mark item as complete
3. Add tests for the fix
4. Update relevant documentation

---

Last Updated: 2025-01-29