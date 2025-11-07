# File Handler vs Workflow Loader Clash Analysis & Design

## Problem Statement

The new File Handler (`file/v1` protocol) has potential conflicts with the existing Workflow Loader Worker, creating inconsistencies in file operations, error handling, and configuration.

## Current Architecture Analysis

### File Handler (`src/gleitzeit/handlers/file.py`)
- **Purpose**: General file operations for workflows (load text/images, list directories, metadata)
- **Protocol**: `file/v1`
- **Error Codes**: Custom range (-22999 to -22000)
- **Size Limits**: 50MB default (`MAX_FILE_SIZE_MB`)
- **Security**: Path traversal detection, blocked extensions
- **Error Pattern**: Uses `GleitzeitError` with specific codes + `HandlerExecutionError` wrapper

### Workflow Loader (`src/gleitzeit/workers/workflow_loader_worker_v2.py`)
- **Purpose**: Load workflow definitions from YAML/JSON/Python files
- **Protocol**: N/A (worker, not handler)
- **Error Codes**: Uses existing codes (-23999 to -23000)
- **Size Limits**: 100MB for workflows (`MAX_WORKFLOW_SIZE_MB`)
- **Security**: Path traversal detection, allowed path prefixes
- **Error Pattern**: Uses `ConfigurationError`, `WorkflowValidationError`

## Identified Clashes

### 1. Overlapping Functionality
| Aspect | File Handler | Workflow Loader | Conflict |
|--------|-------------|----------------|----------|
| File reading | ✓ General files | ✓ Workflow files | Both read files |
| Path validation | ✓ Security checks | ✓ Security checks | Duplicate logic |
| Size validation | ✓ 50MB limit | ✓ 100MB limit | Different limits |
| Error handling | ✓ Specific codes | ✓ Generic errors | Inconsistent |

### 2. Error Code Conflicts
```
Workflow Loader Errors (-23999 to -23000):
  FILE_SYSTEM_ERROR = -23002
  SECURITY_ERROR = -23003
  RESOURCE_LIMIT_ERROR = -23004

File Handler Errors (-22999 to -22000):
  FILE_NOT_FOUND = -22001
  FILE_PERMISSION_DENIED = -22002
  FILE_TOO_LARGE = -22003
  FILE_SECURITY_VIOLATION = -22007
```

**Issue**: Same scenarios (file not found, security violation) use different error codes depending on which component handles them.

### 3. Security Validation Duplication
Both implement `_validate_file_path()` with similar but not identical logic:

**Workflow Loader**:
```python
def _validate_file_path(self, path: Path):
    # Check allowed path prefixes
    if self.loader_config.ALLOWED_PATH_PREFIXES: ...
    # Check path traversal
    if ".." in str(path):
        raise ConfigurationError(...)
```

**File Handler**:
```python
def _validate_file_path(self, path: Path):
    # Check path traversal
    if ".." in str(path):
        raise GleitzeitError(..., code=ErrorCode.FILE_SECURITY_VIOLATION)
    # Check blocked extensions
    if ext in BLOCKED_EXTENSIONS:
        raise GleitzeitError(..., code=ErrorCode.FILE_SECURITY_VIOLATION)
```

### 4. Configuration Inconsistencies
- **Size limits**: 50MB vs 100MB
- **Security policies**: Different approaches to path restrictions
- **Error handling**: Different exception types and codes

### 5. Retry System Confusion
The central retry system expects consistent error classification:
- File Handler: Provides detailed error metadata with retry strategies
- Workflow Loader: Uses legacy error types that may not map correctly

## Design Solution

### Option 1: Unified File Operations (Recommended)

Create a shared file operations core that both components use:

```
Core File Operations Layer
├── FileValidator (security, size validation)
├── FileLoader (actual file reading)
├── ErrorMapper (consistent error codes)
└── ConfigManager (unified configuration)

Components Using Core:
├── FileHandler (protocol handler for workflows)
└── WorkflowLoader (worker for loading workflow definitions)
```

#### Benefits:
- ✅ Consistent error handling
- ✅ Shared security validation
- ✅ Unified configuration
- ✅ No code duplication
- ✅ Clear separation of concerns

#### Implementation:
1. Create `src/gleitzeit/core/file_operations.py`
2. Migrate common logic from both components
3. Update both components to use shared core
4. Align error codes and retry strategies

### Option 2: Handler Delegation

Make Workflow Loader use File Handler for file operations:

```
WorkflowLoader
└── calls FileHandler for file reading
    └── returns structured data
        └── WorkflowLoader processes workflow-specific logic
```

#### Benefits:
- ✅ Reuses existing File Handler
- ✅ Consistent error handling
- ✅ Less refactoring needed

#### Drawbacks:
- ❌ Introduces dependency between worker and handler
- ❌ May complicate workflow loader logic
- ❌ Different size limits still problematic

### Option 3: Separate Domains (Status Quo)

Keep components separate but align interfaces:

#### Actions:
1. Align error codes between components
2. Create shared configuration values
3. Document which component handles what

#### Drawbacks:
- ❌ Still maintains code duplication
- ❌ Requires ongoing coordination
- ❌ Potential for future drift

## Recommended Implementation Plan

### Phase 1: Core File Operations Module
Create unified file operations infrastructure:

```python
# src/gleitzeit/core/file_operations.py

class FileOperationConfig:
    MAX_FILE_SIZE_MB = 50        # General files
    MAX_WORKFLOW_SIZE_MB = 100   # Workflow files
    ALLOWED_PATH_PREFIXES = []   # Security
    BLOCKED_EXTENSIONS = [...]   # Security

class FileValidator:
    def validate_path(self, path, context) -> None
    def validate_size(self, path, context) -> None
    def validate_security(self, path, context) -> None

class FileLoader:
    def load_text_file(self, path, encoding) -> str
    def load_binary_file(self, path, as_base64) -> str
    def get_file_metadata(self, path) -> dict

class FileErrorMapper:
    def map_os_error(self, error, context) -> GleitzeitError
    def get_retry_strategy(self, error_code) -> dict
```

### Phase 2: Update File Handler
Refactor File Handler to use core operations:

```python
class FileHandler(BaseHandler):
    def __init__(self, config):
        self.file_ops = FileOperations(context="handler")

    async def _load_file(self, task):
        # Use unified operations
        self.file_ops.validate_all(path)
        content = self.file_ops.load_file(path, params)
        return self.file_ops.format_result(content, metadata)
```

### Phase 3: Update Workflow Loader
Refactor Workflow Loader to use core operations:

```python
class WorkflowLoaderWorkerV2(BaseWorker):
    def __init__(self, config):
        self.file_ops = FileOperations(context="workflow")

    async def load_workflow_from_path(self, path, format):
        # Use unified operations
        self.file_ops.validate_all(path)
        content = self.file_ops.load_file(path, {"encoding": "utf-8"})
        return self.parse_workflow(content, format)
```

### Phase 4: Error Code Alignment
Update central error codes to be context-aware:

```python
# Enhanced error codes with context
FILE_NOT_FOUND = -22001          # Used by both
FILE_PERMISSION_DENIED = -22002  # Used by both
FILE_TOO_LARGE = -22003         # Used by both
FILE_SECURITY_VIOLATION = -22007 # Used by both

# Workflow-specific (keep separate)
WORKFLOW_VALIDATION_FAILED = -28001
WORKFLOW_FORMAT_ERROR = -28008
```

## Testing Strategy

1. **Unit Tests**: Test core file operations independently
2. **Integration Tests**: Test both components using shared core
3. **Error Scenario Tests**: Verify consistent error handling
4. **Regression Tests**: Ensure existing functionality preserved
5. **Performance Tests**: Verify no performance degradation

## Migration Plan

1. **Week 1**: Implement core file operations module
2. **Week 2**: Update File Handler to use core (with feature flag)
3. **Week 3**: Update Workflow Loader to use core (with feature flag)
4. **Week 4**: Enable unified mode, deprecate old logic
5. **Week 5**: Remove old code, update documentation

## Risk Mitigation

1. **Feature Flags**: Enable gradual rollout
2. **Backward Compatibility**: Maintain existing APIs during transition
3. **Comprehensive Testing**: Prevent regressions
4. **Monitoring**: Track error patterns during migration
5. **Rollback Plan**: Quick revert if issues detected

## Success Criteria

- ✅ No code duplication between components
- ✅ Consistent error codes and retry behavior
- ✅ Unified configuration management
- ✅ All existing tests pass
- ✅ No performance regression
- ✅ Clear documentation of file operation patterns