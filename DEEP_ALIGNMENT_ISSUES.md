# Deep Alignment Issues Found

## 1. Timeout Values Inconsistency ⚠️ HIGH

**Issue**: Different timeout values used across components without configuration

| Operation | CLI | API | Client | Recommended |
|-----------|-----|-----|--------|-------------|
| Health check | - | - | 2s | 5s |
| Server startup | - | - | 30s | 30s |
| Workflow execution | - | - | 120s | Configurable |
| Task execution | - | - | 300s | Configurable |
| Provider operations | 2s | 2s | 2s | Configurable |
| Shutdown | 5s | 5s | 5s | 5s |

**Current Issues**:
- No centralized timeout configuration
- Hardcoded values scattered throughout code
- No way for users to adjust timeouts

**Fix Needed**: Create timeout configuration system

---

## 2. HTTP Client Library Mix ⚠️ MEDIUM

**Issue**: Using both aiohttp and httpx inconsistently

| Component | Library Used | Where |
|-----------|-------------|-------|
| CLI | httpx | API health checks |
| API | aiohttp | Internal |
| Client | httpx (API mode) | Server checks |
| Client | aiohttp (Native) | Via providers |
| Providers | aiohttp | Ollama, etc. |
| Hubs | aiohttp | All hubs |

**Problems**:
- Two different HTTP libraries with different APIs
- Different connection pooling behavior
- Different timeout handling

**Recommendation**: Standardize on aiohttp (already used more widely)

---

## 3. Task ID Generation Patterns ⚠️ LOW

**Issue**: Different ID generation patterns

| Component | Pattern | Example |
|-----------|---------|---------|
| CLI | `{type}-{hex8}` | `task-a1b2c3d4` |
| API | `api_{type}_{hex8}` | `api_task_a1b2c3d4` |
| Client | No generation | Relies on ExecutionEngine |
| Templates | `template_{type}_{hex8}` | `template_research_a1b2c3d4` |

**Impact**: Makes tracing tasks across components harder

**Recommendation**: Document ID patterns or unify them

---

## 4. Priority Handling Type Mismatch ⚠️ HIGH

**Issue**: API accepts string, Client uses enum

```python
# API - accepts string
priority: str = Field("normal", description="Task priority (low, normal, high, critical)")
Priority[task_req.priority.upper()]  # Converts to enum

# Client - uses enum directly  
priority: Priority = Priority.NORMAL

# CLI - mixed usage
```

**Problems**:
- Type inconsistency
- Potential validation issues
- API has to convert strings to enums

**Fix Needed**: Client should accept both string and enum

---

## 5. Default Directory Structure ⚠️ MEDIUM

**Issue**: Only CLI has default directory structure

| Component | Default Directory | Config Location |
|-----------|------------------|-----------------|
| CLI | `~/.gleitzeit/` | `~/.gleitzeit/config.yaml` |
| API | None | Environment only |
| Client | None | Constructor only |

**Subdirectories** (CLI only):
- `~/.gleitzeit/workflows.db` - SQLite database
- `~/.gleitzeit/batch_results/` - Batch processing results
- `~/.gleitzeit/logs/` - Log files (if configured)

**Problems**:
- API and Client don't have persistent storage location
- No shared configuration directory
- Batch results saved differently

**Recommendation**: Define standard directory structure for all

---

## 6. Workflow Watch Behavior ⚠️ LOW

**Issue**: Watch parameter defaults and behavior

| Component | Default | Behavior |
|-----------|---------|----------|
| CLI | False (flag) | Prints progress to console |
| API | N/A | Client polls `/workflows/{id}` |
| Client | False | Returns immediately unless True |

**Good**: Defaults are consistent (False)
**Issue**: No streaming/websocket support for real-time updates

---

## 7. Error Types and Handling ⚠️ MEDIUM

**Issue**: Different error types used

| Component | Error Types | Response Format |
|-----------|------------|-----------------|
| CLI | Python exceptions → click.echo | Text message |
| API | HTTPException | JSON with detail |
| Client | Python exceptions | Raised to caller |

**Specific Errors**:
```python
# API
raise HTTPException(status_code=404, detail="Task not found")

# Client  
raise RuntimeError(f"API server not available at {self.api_url}")

# CLI
click.echo(f"❌ Error: {e}", err=True)
sys.exit(1)
```

**Recommendation**: Create common error types module

---

## 8. Session Lifecycle Management ⚠️ HIGH

**Issue**: Inconsistent session cleanup

| Component | Session Creation | Cleanup |
|-----------|-----------------|---------|
| OllamaHub | On initialize | ⚠️ No explicit cleanup |
| Providers | On initialize | Sometimes in shutdown |
| API Client | On __aenter__ | On __aexit__ |
| Client | Per request (httpx) | Auto cleanup |

**Problems**:
- "Unclosed client session" warnings
- Resource leaks possible
- No connection reuse in some cases

**Fix Needed**: Ensure all sessions are closed in shutdown

---

## 9. Retry Configuration Inconsistency ⚠️ MEDIUM

**Issue**: Retry config not consistently available

| Component | Retry Support | Configuration |
|-----------|--------------|---------------|
| CLI | ✅ Via workflow YAML | In task definition |
| API | ✅ Via request | In task object |
| Client | ✅ Via RetryConfig | Pass to submit_task |

**Default Values**:
- max_attempts: 3 (inconsistent)
- base_delay: 1.0
- backoff_strategy: exponential

**Issue**: No global retry configuration

---

## 10. Logging Configuration ⚠️ MEDIUM

**Issue**: No unified logging configuration

| Component | Logger Setup | Output |
|-----------|-------------|--------|
| CLI | Basic config + click.echo | Console |
| API | Basic config | Console/File |
| Client | Get logger | Inherits |

**Problems**:
- No log level configuration
- No log rotation
- No structured logging
- Mix of logger and click.echo in CLI

---

## 11. Provider Initialization Parameters ⚠️ LOW

**Issue**: Inconsistent provider initialization

```python
# CLI
OllamaProvider("cli-ollama-provider", auto_discover=False, hub=ollama_hub)

# API  
OllamaProvider("api-ollama-provider", auto_discover=False, hub=ollama_hub)

# Client
OllamaProvider("ollama-provider", auto_discover=False, hub=self._ollama_hub)
```

**Note**: The `auto_discover` parameter is redundant when hub is provided

---

## 12. Batch Processing Configuration ⚠️ LOW

**Issue**: Different batch result handling

| Component | Output Directory | Configurable |
|-----------|-----------------|--------------|
| CLI | `~/.gleitzeit/batch_results` | Via config |
| API | Returns in response | N/A |
| Client | Returns BatchResult object | N/A |

---

## Priority Fixes Summary

### 🔴 HIGH Priority (Breaking/Critical)
1. **Timeout Configuration** - Add configurable timeouts
2. **Priority Type Mismatch** - Fix API/Client type handling
3. **Session Cleanup** - Fix resource leaks

### 🟡 MEDIUM Priority (Important)
4. **HTTP Client Library** - Standardize on aiohttp
5. **Default Directories** - Create standard structure
6. **Error Handling** - Common error types
7. **Retry Configuration** - Global defaults
8. **Logging** - Unified configuration

### 🟢 LOW Priority (Nice to Have)
9. **Task ID Patterns** - Document convention
10. **Watch Behavior** - Consider WebSocket
11. **Provider Parameters** - Clean up redundancy
12. **Batch Output** - Standardize handling

---

## Recommendations

1. **Create Configuration Module**:
   - Centralized timeout settings
   - Retry defaults
   - Logging configuration
   - Directory paths

2. **Standardize Libraries**:
   - Use aiohttp everywhere
   - Common error types
   - Shared utilities

3. **Fix Resource Management**:
   - Ensure all sessions cleaned up
   - Add session pooling configuration
   - Monitor for leaks

4. **Improve Type Safety**:
   - Accept both strings and enums for priority
   - Validate inputs consistently
   - Use TypedDict for configs

5. **Documentation**:
   - Document all conventions
   - Explain design decisions
   - Migration guides