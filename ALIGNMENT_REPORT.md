# Gleitzeit Worker Alignment Report

## Critical Issues Found

### 1. Data Format Compatibility

#### Issue: WorkflowLoaderWorkerV2 JSON Parsing
- **Problem**: V2 attempts to parse file paths as JSON when receiving inline workflow data
- **Location**: `workflow_loader_worker_v2.py:147`
- **Impact**: Workflows submitted via CLI are rejected with JSON parsing errors
- **Root Cause**: Misalignment between what CLI sends and what V2 expects

#### Current Data Flow:
1. **CLI Submission** (`cli/main.py:239-246`):
   ```python
   {
       b"workflow_id": workflow_id.encode(),
       b"path": workflow_file.encode(),  # File path string
       b"format": fmt.encode()
   }
   ```

2. **BaseWorker Decoding** (`base.py:_process_with_semaphore`):
   - Converts all byte keys/values to strings
   - Result: `{"workflow_id": "...", "path": "file.yaml", "format": "yaml"}`

3. **WorkflowLoaderWorkerV2 Processing**:
   - Correctly handles `path` field for file loading
   - Bug: When `workflow` field present, tries `json.loads(raw_workflow)` even if it's a file path

### 2. Stream Naming Conventions

#### Verified Patterns:
- **Sharded streams**: `{shard:N}:stream:name` (e.g., `{shard:0}:workflow:load`)
- **Global streams**: `global:stream:name` (e.g., `global:workflow:load:failed`)
- **Workflow-specific**: Uses `default_sharding.get_stream_key()` for consistent naming

#### Issue: WorkflowSubmissionWorker Stream Name
- **Problem**: Line 158 uses `"workflow:loader"` instead of `"workflow:load"`
- **Impact**: Messages sent to wrong stream name, not picked up by loaders

### 3. Worker Version Mismatches

#### WorkflowLoaderWorker Versions:
- **V1** (`workflow_loader_worker.py`):
  - Simple, working implementation
  - Handles both file paths and inline workflows
  - Successfully processes workflows

- **V2** (`workflow_loader_worker_v2.py`):
  - Enhanced with protocol mapping, caching
  - Has import issue with retry module
  - Data format parsing bug for inline workflows

#### Recommendation:
Use V1 in production until V2 issues are resolved

### 4. Missing Retry Module

- **Location**: `workflow_loader_worker_v2.py` imports
- **Impact**: V2 cannot start due to missing module
- **Workaround**: Import commented out, but functionality incomplete

### 5. Consumer Group Configuration

All workers properly use:
- Group name: `f"{worker_type}-{worker_id}-group"`
- Stream patterns properly configured
- Consumer group creation handled in BaseWorker

## Fixes Applied

### 1. RetryWorker Constructor (FIXED)
```python
# Before: def __init__(self, worker_id, redis_url, assigned_shards)
# After: def __init__(self, config: WorkerConfig)
```

### 2. WorkflowSubmissionWorker Shard References (FIXED)
```python
# Before: self.shard
# After: self.config.assigned_shards
```

### 3. Async File I/O (FIXED)
- All synchronous file operations replaced with aiofiles
- Added to setup.py dependencies

## Recommended Fixes

### 1. Fix WorkflowLoaderWorkerV2 Data Parsing
```python
# In workflow_loader_worker_v2.py:143-147
if data.get('workflow'):
    # Inline workflow provided
    raw_workflow = data.get('workflow')
    if isinstance(raw_workflow, str):
        # Check if it's JSON or YAML string
        try:
            raw_workflow = json.loads(raw_workflow)
        except json.JSONDecodeError:
            # Might be YAML or invalid - let validation handle it
            pass
```

### 2. Fix WorkflowSubmissionWorker Stream Name
```python
# In workflow_submission_worker.py:158
# Change: "workflow:loader"
# To: "workflow:load"
```

### 3. Standardize Data Format

Create a common message format specification:
```python
# Workflow submission format
{
    "workflow_id": str,
    "path": str (optional),        # File path
    "workflow": str/dict (optional), # Inline workflow
    "format": str,                  # yaml/json/python
    "source": str                   # cli/api/parent
}
```

## Testing Recommendations

1. **Integration Test**: Submit workflow via CLI and verify all workers process it
2. **Format Test**: Test both file path and inline workflow submissions
3. **Stream Test**: Verify messages flow through correct stream names
4. **Recovery Test**: Kill workers mid-process and verify recovery

## Current System State

- **Working**: WorkflowLoaderWorker V1 successfully processes workflows
- **Broken**: WorkflowLoaderWorkerV2 due to import and parsing issues
- **Fixed**: RetryWorker, WorkflowSubmissionWorker constructor issues
- **Pending**: Stream name alignment, data format standardization