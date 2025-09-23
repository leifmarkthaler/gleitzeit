# Retry and Failure Mechanism Audit

## Executive Summary

This audit examines Gleitzeit's retry and failure mechanisms following recent external modifications. The changes reduce default retry attempts from 3 to 1 and add intelligent validation error detection to prevent unnecessary retries.

## Key Findings

### 1. Recent Configuration Changes

#### Retry Defaults Modified
- **Previous**: `max_retries = 3` (4 total attempts)
- **Current**: `max_retries = 1` (2 total attempts)
- **Impact**: Faster failure detection, reduced resource waste on persistent failures

#### Delay Configuration Reduced
- **Previous**: `max_delay = 60` seconds
- **Current**: `max_delay = 30` seconds
- **Impact**: Shorter maximum wait times between retries

#### Validation Error Detection Added
The retry mechanism now intelligently skips retries for:
- Programming errors (TypeError, AttributeError, KeyError, ValueError)
- Validation errors (containing "validation" or "invalid")
- Invalid parameter errors ("[INVALID_PARAMS]" or "Missing required parameter")

### 2. Retry Flow Analysis

```
Task Execution → Failure
       ↓
Check RetryManager.should_retry()
       ↓
   [No Retry]                    [Retry]
       ↓                            ↓
   Task Failed                Calculate Delay
   Emit Event                      ↓
   Trigger Workflow           Schedule Retry
   Failure                    (via timer mechanism)
```

### 3. Configuration Hierarchy

1. **Task-level retry config** (highest priority)
   - Defined in workflow YAML per task
   - Loaded by WorkflowLoaderWorkerV2

2. **Workflow-level retry config**
   - Default configuration for all tasks
   - Can be overridden per task

3. **System defaults** (lowest priority)
   - `max_retries = 1`
   - `strategy = EXPONENTIAL_JITTER`
   - `base_delay = 1.0`
   - `max_delay = 30.0`

### 4. Backoff Strategies

The system supports multiple backoff strategies:

| Strategy | Behavior | Formula |
|----------|----------|---------|
| FIXED | Constant delay | `base_delay` |
| LINEAR | Linear increase | `base_delay * (attempt + 1) * multiplier` |
| EXPONENTIAL | Exponential growth | `base_delay * (multiplier ^ attempt)` |
| EXPONENTIAL_JITTER | Exponential with randomization | `random(0, exponential_delay)` |

Default: **EXPONENTIAL_JITTER** - Prevents retry storms by randomizing retry times.

### 5. Failure Propagation

```
Task Failure (after retries exhausted)
    ↓
TaskExecutionWorker emits "task:failed"
    ↓
DependencyWorker processes failure
    ↓
Adds to workflow "tasks:failed" set
    ↓
Checks workflow completion
    ↓
If ANY task failed → Workflow marked "failed"
    ↓
Emit "workflow:failed" event
```

### 6. Circuit Breaker Integration

The circuit breaker works **alongside** the retry mechanism:

1. **Circuit CLOSED**: Normal retries occur
2. **Circuit OPEN**: Immediate failure, no retries attempted
3. **Circuit HALF_OPEN**: Limited test requests with retries

**Key Point**: Circuit breaker failures are **not exempt** from retry logic unless specifically configured.

### 7. Worker-Level Configuration

Recent changes added:
- `batch_size`: Number of messages to process per batch
- `block_timeout`: Maximum time to wait for messages
- **Impact**: Better resource utilization and responsiveness

## Strengths of Current Implementation

1. **Intelligent Retry Skipping**: Validation and programming errors fail fast
2. **Exponential Backoff with Jitter**: Prevents retry storms
3. **Configurable per Task**: Fine-grained control where needed
4. **Timer-Based Retry**: Decoupled from worker execution
5. **Hard-Fail Preservation**: Maintains predictable failure semantics
6. **Circuit Breaker Protection**: Fast failure for down services

## Identified Issues and Risks

### Issue 1: Reduced Default Retries May Be Too Aggressive
**Risk**: Transient network issues may cause more workflow failures
**Recommendation**: Consider `max_retries = 2` as default for better tolerance

### Issue 2: Validation Error Detection May Be Too Broad
**Risk**: String matching on "invalid" could skip retries for recoverable errors
**Example**: "Connection invalid after timeout" would not retry
**Recommendation**: Use more specific error type checking

### Issue 3: Circuit Breaker Errors Not Explicitly Handled
**Risk**: CircuitOpenError might trigger unnecessary retries
**Recommendation**: Add CircuitOpenError to non-retryable exceptions

### Issue 4: No Retry Metrics
**Risk**: Difficult to tune retry configuration without visibility
**Recommendation**: Add retry metrics to monitoring

## Recommendations

### 1. Immediate Actions

```python
# In retry.py - Add circuit breaker awareness
def should_retry(self, attempt: int, error: Optional[Exception] = None) -> bool:
    if error:
        error_type = type(error).__name__

        # Don't retry on circuit breaker open
        if error_type == 'CircuitOpenError':
            logger.debug("Not retrying due to circuit breaker open")
            return False

        # Existing checks...
```

### 2. Configuration Improvements

```yaml
# Recommended default configuration
retry:
  max_retries: 2          # More tolerant default
  strategy: exponential_jitter
  base_delay: 1.0
  max_delay: 30.0
  exclude_errors:         # Explicit exclusion list
    - ValueError
    - TypeError
    - ValidationError
    - CircuitOpenError
```

### 3. Add Retry Metrics

```python
# Add to task execution
retry_metrics = {
    'total_retries': retry_count,
    'retry_reason': str(error),
    'backoff_delay': delay,
    'strategy_used': retry_manager.config.strategy
}
await self.emit_metrics('retry_attempted', retry_metrics)
```

### 4. Enhanced Error Classification

```python
class ErrorClassifier:
    """Classify errors for retry decisions"""

    PERMANENT_ERRORS = {
        'ValidationError',
        'AuthenticationError',
        'PermissionError',
        'CircuitOpenError'
    }

    TRANSIENT_ERRORS = {
        'ConnectionError',
        'TimeoutError',
        'ServiceUnavailable'
    }

    @classmethod
    def is_retryable(cls, error: Exception) -> bool:
        error_type = type(error).__name__

        # Explicit permanent errors
        if error_type in cls.PERMANENT_ERRORS:
            return False

        # Explicit transient errors
        if error_type in cls.TRANSIENT_ERRORS:
            return True

        # Default to retryable for unknown errors
        return True
```

### 5. Workflow-Level Retry Policy

```yaml
# Allow workflow-level retry policy override
workflow:
  name: critical-workflow
  retry_policy:
    mode: aggressive      # Preset configurations
    # Options: conservative (1 retry), standard (2), aggressive (3)

  tasks:
    - id: task1
      # Inherits workflow policy unless overridden
```

## Testing Recommendations

1. **Add retry behavior tests**:
   - Test validation error detection
   - Test circuit breaker interaction
   - Test retry exhaustion scenarios

2. **Load testing with failures**:
   - Inject 10% failure rate
   - Measure retry storm prevention
   - Validate backoff timing

3. **Integration tests**:
   - Test workflow failure with mixed retry configs
   - Test timer-based retry scheduling
   - Test worker restart during retries

## Conclusion

The recent changes improve Gleitzeit's retry mechanism by:
1. Reducing unnecessary retries (1 instead of 3 default)
2. Failing fast on validation errors
3. Maintaining hard-fail semantics

However, the aggressive defaults may cause issues with transient failures. The recommendations above would improve reliability while maintaining the benefits of the recent changes.

### Priority Actions
1. **HIGH**: Add CircuitOpenError to non-retryable exceptions ✅ **IMPLEMENTED**
2. **MEDIUM**: Increase default max_retries to 2 ✅ **IMPLEMENTED**
3. **LOW**: Implement retry metrics for monitoring

The retry and failure mechanism is fundamentally sound but would benefit from these targeted improvements to balance reliability with resource efficiency.

## Implementation Status (Updated)

### Completed Improvements

#### 1. CircuitOpenError Handling
- **File**: `src/gleitzeit/core/retry.py`
- **Change**: Added CircuitOpenError to the list of non-retryable exceptions
- **Impact**: Prevents unnecessary retry attempts when services are known to be down

#### 2. Default Retry Count Increase
- **Files**:
  - `src/gleitzeit/core/retry.py`: Changed default from 1 to 2
  - `src/gleitzeit/workers/workflow_loader_worker_v2.py`: Updated to match
- **Change**: Increased default max_retries from 1 to 2 (3 total attempts)
- **Impact**: Better tolerance for transient network issues while still failing fast

#### 3. Comprehensive Testing
- **File**: `tests/test_retry_improvements.py`
- **Tests Added**:
  - Verification that CircuitOpenError is not retried
  - Default configuration allows 2 retries
  - Programming and validation errors still skip retries
  - All existing tests continue to pass

### Results
All tests pass successfully, confirming:
- CircuitOpenError fails immediately without retries
- Default configuration now provides 3 total attempts
- Backward compatibility maintained
- No regression in existing functionality