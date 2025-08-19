# Bug Reports and Fixes

## Issue #1: ResourceMetrics Field Mismatch in OllamaHub

**Date**: August 17, 2024  
**Status**: IDENTIFIED - Needs proper solution

### Description
The OllamaHub (`src/gleitzeit/hub/ollama_hub.py`) has a field name mismatch in its metrics handling:

- **Line 478**: `instance.metrics.total_requests += 1`
- **Line 486-487**: Uses `instance.metrics.total_requests` in calculation

However, the ResourceMetrics class in `src/gleitzeit/hub/base.py` defines:
- `request_count: int = 0` (not `total_requests`)

### Current Impact
- OllamaHub `execute_on_instance` method fails with AttributeError
- Agent workflows fall back to mock responses instead of using real LLM
- Standard LLM workflows work fine (they use OllamaProvider, not OllamaHub)

### Root Cause
Inconsistency between:
1. ResourceMetrics schema in `hub/base.py` (uses `request_count`)
2. ResourceMetrics usage in `hub/ollama_hub.py` (expects `total_requests`)
3. Different ResourceMetrics in `common/metrics.py` (has `total_requests`)

### Evidence
```bash
$ grep -n "total_requests.*=" src/gleitzeit/hub/
base.py:593:        total_requests = sum(i.metrics.request_count for i in self.instances.values())
ollama_hub.py:478:            instance.metrics.total_requests += 1
```

Line 593 in base.py shows the correct field is `request_count`.

### Temporary Workaround
Agent workflows use mock responses when OllamaHub fails.

### Proper Solution Needed
1. **Option A**: Update OllamaHub to use `request_count` consistently
2. **Option B**: Add `total_requests` field to ResourceMetrics in base.py
3. **Option C**: Unify the two ResourceMetrics classes

The solution should maintain backward compatibility and not break the existing architecture.

### Testing
- Standard LLM workflows: ✅ Working (use OllamaProvider)
- Agent workflows: ❌ Fall back to mocks (use OllamaHub)

### Files Affected
- `src/gleitzeit/hub/ollama_hub.py` (lines 478, 486-487)
- `src/gleitzeit/hub/base.py` (ResourceMetrics definition)
- `src/gleitzeit/common/metrics.py` (alternative ResourceMetrics)

---

## Testing Status

**Agent Hub Integration**: ✅ Working with mocks  
**Agent Hub + OllamaHub**: ❌ Blocked by ResourceMetrics issue  
**Standard Workflows**: ✅ Working with real Ollama  