# FIXME: Method Validation Issues

## Current Status
✅ **Primary Goal Achieved**: Invalid methods are now rejected at submission time, not execution time.

## Remaining Issues

### 1. LoggingMixin Error
- **Error**: `LoggingMixin.log_error() got multiple values for argument 'error'`
- **Location**: When validation fails and error is being logged
- **Impact**: Causes confusing secondary error messages

### 2. Task Save Error Message  
- **Error**: `Task cannot be saved without a workflow_id`
- **Note**: This is NOT actually happening - the workflow structure correctly prevents saving when validation fails
- **Issue**: The error message appears in the exception handling chain, likely from error logging

### 3. WebSocket/Event Errors
- `Error in connection callback: gleitzeit.client.events.models.WebSocketMessage() got multiple values for keyword argument 'type'`
- `Unknown message type: connection`
- `Unknown message type: None`

### 4. Resource Cleanup Issues
- `RuntimeError: Event loop is closed`
- `Unclosed client session`
- `Unclosed connector`

## Architecture Notes

The workflow submission flow is actually correct:
1. Validation happens first (lines 155-180 in workflow_manager.py)
2. If validation fails, WorkflowValidationError is raised (lines 182-192)
3. Workflow and tasks are ONLY saved if validation passes (lines 200-217)

**Key Point**: The workflow and tasks are NOT being saved when validation fails. The confusing error messages are coming from bugs in the error handling/logging code, not from the core validation logic.

## Test Results
- Invalid method `ollama/generate` is correctly rejected at submission ✅
- Valid method `llm/generate` should work (but has other errors to fix)
- **CRITICAL**: Even valid workflows fail with "Task cannot be saved without a workflow_id" error
  - This happens during workflow submission, not just during validation failures
  - The error suggests tasks are being saved before the workflow gets its ID assigned