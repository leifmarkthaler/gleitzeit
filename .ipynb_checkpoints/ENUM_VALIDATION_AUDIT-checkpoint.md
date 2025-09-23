# Enum & Validation System Audit

## Executive Summary

This audit examines the current use of enums (particularly TaskStatus) and validation patterns across Gleitzeit, and provides recommendations for integrating these with the new provider system.

## Current Enum Usage

### 1. TaskStatus Enum

```python
class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    VALIDATED = "validated"
    ROUTED = "routed"
    EXECUTING = "executing"
    PAUSED = "paused"
    SLEEPING = "sleeping"      # Deprecated - use PAUSED
    WAITING = "waiting"        # Task is waiting for signal
    SCHEDULED = "scheduled"    # Task is scheduled (timer)
    WAITING_SIGNAL = "waiting_signal"  # Deprecated - use WAITING
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY_PENDING = "retry_pending"
    REWOUND = "rewound"
```

### 2. Current Usage Patterns

| Component | TaskStatus Usage | Purpose |
|-----------|-----------------|----------|
| TaskExecutionWorkerV2 | `TaskStatus.SCHEDULED`, `TaskStatus.WAITING` | Handles timer/signal states |
| WorkflowProviderBridge | Maps strings to enums | Backward compatibility |
| Task Model | All statuses | Core workflow state management |
| Archived Providers | Return `TaskResult` with enum | Legacy compatibility |

### 3. Status Flow

```
PENDING → QUEUED → VALIDATED → ROUTED → EXECUTING → COMPLETED
                                    ↓
                                SCHEDULED (timers)
                                WAITING (signals)
                                FAILED
                                RETRY_PENDING
```

## Current Validation Patterns

### 1. Validation Locations

| Layer | Validation Type | Current Implementation |
|-------|----------------|------------------------|
| **Model Layer** | Pydantic validation | Task.validate_params(), validate_dependencies() |
| **Worker Layer** | Pre-execution checks | Basic null checks, workflow existence |
| **Provider Layer** | Runtime validation | Minimal, mostly parameter presence |
| **Bridge Layer** | Format conversion | Type checking during conversion |

### 2. Old Provider Validation

The archived providers had extensive validation:

```python
# Old base.py validation
- provider_id validation (non-empty, no spaces)
- protocol_id format (namespace/version)
- Method implementation checks
- Async method verification
- Parameter serializability
```

### 3. New Provider Validation

Current new providers have minimal validation:

```python
async def validate(self, request: ExecutionRequest) -> bool:
    # Only basic parameter presence checks
    return 'code' in request.params  # Python provider example
```

## Integration Challenges

### 1. Status Type Mismatch

| System | Status Type | Values |
|--------|------------|---------|
| Old System | TaskStatus enum | COMPLETED, FAILED, SCHEDULED, WAITING |
| New Providers | String | "success", "error", "sleeping", "waiting" |
| Bridge | Maps between | Conversion required |

### 2. Validation Responsibility

**Current Split:**
- Models validate structure
- Workers validate workflow context
- Providers validate execution capability
- No unified validation strategy

**Issues:**
- Validation happens too late (at execution)
- No early validation feedback
- Duplicate validation logic
- Inconsistent error messages

## Recommendations

### 1. Keep TaskStatus Enum - Update Provider System

```python
# Updated ExecutionResponse
@dataclass
class ExecutionResponse:
    request_id: str
    status: TaskStatus  # Use enum instead of string
    result: Any = None
    error: Optional[Dict[str, Any]] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**Benefits:**
- Type safety across the system
- Consistent status values
- IDE autocomplete support
- Easier refactoring

### 2. Move Validation to Providers

```python
class Provider(ABC):
    """Enhanced provider with validation"""

    @abstractmethod
    async def validate(self, request: ExecutionRequest) -> ValidationResult:
        """
        Comprehensive validation of execution request

        Returns:
            ValidationResult with:
            - is_valid: bool
            - errors: List[str]
            - warnings: List[str]
            - can_execute: bool
        """
        pass

    async def validate_params(self, params: Dict[str, Any]) -> ValidationResult:
        """Default parameter validation"""
        # Common validation logic
        pass

    async def validate_dependencies(self, deps: List[str]) -> ValidationResult:
        """Validate dependency requirements"""
        pass
```

### 3. Validation Result Model

```python
@dataclass
class ValidationResult:
    """Standardized validation response"""
    is_valid: bool
    can_execute: bool = True  # Valid but may need resources
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    required_params: List[str] = field(default_factory=list)
    missing_params: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### 4. Provider-Specific Validation Examples

#### Python Provider
```python
async def validate(self, request: ExecutionRequest) -> ValidationResult:
    result = ValidationResult(is_valid=True)

    # Check required parameters
    if request.method == "exec":
        if 'code' not in request.params:
            result.errors.append("Missing required parameter: 'code'")
            result.missing_params.append('code')
            result.is_valid = False
        else:
            # Validate Python syntax
            try:
                compile(request.params['code'], '<string>', 'exec')
            except SyntaxError as e:
                result.errors.append(f"Invalid Python syntax: {e}")
                result.is_valid = False

    # Check timeout
    if request.timeout > 3600:
        result.warnings.append("Long timeout may impact system resources")

    return result
```

#### Timer Provider
```python
async def validate(self, request: ExecutionRequest) -> ValidationResult:
    result = ValidationResult(is_valid=True)

    if request.method == "sleep":
        duration = request.params.get('duration')
        if duration is None:
            result.errors.append("Missing required parameter: 'duration'")
            result.is_valid = False
        elif duration < 0:
            result.errors.append("Duration must be non-negative")
            result.is_valid = False
        elif duration > 86400:  # 24 hours
            result.warnings.append("Very long sleep duration")

    return result
```

### 5. Early Validation Strategy

```python
# In WorkflowLoaderWorker
async def validate_workflow(workflow: Dict) -> WorkflowValidationResult:
    """Validate entire workflow before execution"""

    results = {}
    for task in workflow['tasks']:
        # Get provider for task type
        provider = await orchestrator.get_provider(task['type'])

        # Create request for validation
        request = create_request(task)

        # Validate through provider
        validation = await provider.validate(request)
        results[task['id']] = validation

    return WorkflowValidationResult(
        is_valid=all(r.is_valid for r in results.values()),
        task_results=results
    )
```

## Implementation Plan

### Phase 1: Update Core Models (Day 1)
1. ✅ Keep TaskStatus enum as-is
2. Update ExecutionResponse to use TaskStatus
3. Create ValidationResult model
4. Update Provider base class with validation methods

### Phase 2: Enhance Provider Validation (Day 2)
1. Implement comprehensive validation in each provider
2. Add syntax checking for code execution
3. Add resource limit validation
4. Add dependency validation

### Phase 3: Integration (Day 3)
1. Update WorkflowProviderBridge to handle enums
2. Remove string-to-enum mapping
3. Add early validation in workflow loader
4. Update tests

### Phase 4: Migration (Day 4)
1. Update all workers to use enum-based responses
2. Remove deprecated status values
3. Update documentation
4. Add validation metrics

## Benefits of This Approach

### 1. Type Safety
- Enum usage throughout prevents invalid states
- Compile-time checking of status values
- Better IDE support

### 2. Early Failure Detection
- Validation before execution saves resources
- Clear error messages for users
- Prevents invalid tasks from entering queue

### 3. Provider Autonomy
- Each provider knows its own validation rules
- Easy to add new providers with custom validation
- Validation logic close to execution logic

### 4. Consistency
- Single source of truth for statuses (TaskStatus enum)
- Standardized validation results
- Uniform error reporting

## Migration Path

### From Current State
```python
# Current: String status
response = ExecutionResponse(
    status="success",  # String
    result=data
)
```

### To Target State
```python
# Target: Enum status
response = ExecutionResponse(
    status=TaskStatus.COMPLETED,  # Enum
    result=data
)
```

### Compatibility During Migration
```python
# Bridge can handle both during transition
if isinstance(response.status, str):
    # Legacy string status
    status = self.status_map[response.status]
else:
    # New enum status
    status = response.status
```

## Conclusion

By keeping the TaskStatus enum and moving validation to providers, we achieve:

1. **Type Safety**: Enums prevent invalid states
2. **Early Validation**: Catch errors before execution
3. **Provider Expertise**: Each provider validates what it knows best
4. **Clean Architecture**: Clear separation of concerns
5. **Easy Extension**: New providers can implement custom validation

This approach maintains backward compatibility while providing a cleaner, more maintainable system for the future.