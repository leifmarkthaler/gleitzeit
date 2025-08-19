# Additional Alignment Issues Found

## 1. Persistence Configuration ⚠️

**Issue**: Inconsistent persistence configuration across components

| Component | Configuration Method | Customizable |
|-----------|---------------------|--------------|
| **CLI** | Passes `factory_kwargs` with Redis/SQL config | ✅ Yes |
| **API** | No configuration passed | ❌ No |
| **Client** | No configuration passed | ❌ No |

**Current Code**:
```python
# CLI - Configurable
self.persistence_backend = await PersistenceFactory.create(**factory_kwargs)

# API - Not configurable
app_state.persistence_backend = await PersistenceFactory.create()

# Client - Not configurable
self._persistence_adapter = await PersistenceFactory.create()
```

**Fix Needed**: API and Client should accept persistence configuration

---

## 2. Max Concurrent Tasks ⚠️

**Issue**: Inconsistent configuration methods

| Component | Configuration | Default |
|-----------|--------------|---------|
| **CLI** | Via config file `execution.max_concurrent_tasks` | 5 |
| **API** | Hardcoded | 5 |
| **Client** | Via `native_config['max_concurrent_tasks']` | 5 |

**Current Code**:
```python
# CLI - Configurable via config
max_concurrent = execution_config.get('max_concurrent_tasks', 5)

# API - Hardcoded
max_concurrent_tasks=5

# Client - Configurable via native_config
max_concurrent_tasks=self.native_config.get('max_concurrent_tasks', 5)
```

**Fix Needed**: API should be configurable

---

## 3. Provider ID Naming Convention ⚠️

**Issue**: Different ID prefixes across components

| Provider | CLI ID | API ID | Client ID |
|----------|--------|--------|-----------|
| Python | `cli-python-provider` | `api-python-provider` | `python-provider` |
| Ollama | `cli-ollama-provider` | `api-ollama-provider` | `ollama-provider` |
| MCP | `cli-mcp-provider` | `api-mcp-provider` | `mcp-provider` |
| Template | `cli-template-provider` | `api-template-provider` | `template-provider` |

**Impact**: This doesn't break functionality but makes debugging harder

**Recommendation**: Keep unique prefixes for clarity but document the convention

---

## 4. Logging Consistency ✅

**Observation**: Different logging approaches

| Component | Logging Method |
|-----------|---------------|
| **CLI** | Uses `click.echo()` for user output, `logger` for debug |
| **API** | Uses `logger` consistently |
| **Client** | Uses `logger` consistently |

**Status**: This is appropriate - CLI needs user-friendly output

---

## 5. Error Response Format ⚠️

**Issue**: Inconsistent error handling

| Component | Error Format |
|-----------|-------------|
| **CLI** | Prints error with `click.echo()` and exits |
| **API** | Returns HTTP error with JSON body |
| **Client** | Raises Python exceptions |

**Status**: This is somewhat expected but could be more consistent

---

## 6. Configuration File Support ⚠️

**Issue**: Different configuration approaches

| Component | Configuration Method |
|-----------|---------------------|
| **CLI** | YAML config file at `~/.gleitzeit/config.yaml` |
| **API** | Environment variables only |
| **Client** | Dict passed to constructor |

**Recommendation**: Add unified configuration system

---

## 7. Default Values Alignment ✅

**Good News**: These are aligned:
- All use `allow_local=True` for Python provider
- All use `auto_discover=True` for OllamaHub initialization
- All use same default port (8000) for API
- All use same resource manager pattern
- All have BatchProcessor initialized

---

## 8. Missing Features in API ⚠️

**Issue**: Some CLI/Client features not exposed in API

| Feature | CLI | API | Client |
|---------|-----|-----|--------|
| Init workflow template | ✅ | ❌ | ❌ |
| Config management | ✅ | ❌ | ❌ |
| Cleanup old data | ❌ | ❌ | ✅ |
| Resource pool creation | ❌ | ❌ | ✅ |

---

## 9. Workflow File Handling ✅

**Good**: All three support loading workflows from files
- CLI: Direct file path in command
- API: `/workflows/upload` endpoint
- Client: `run_workflow(file_path)`

---

## 10. Health Check Methods ✅

**Good**: All have health/status checking
- CLI: `status` command
- API: `/health` and `/status` endpoints  
- Client: `health_check()` method

---

## Priority Fixes Needed

### High Priority
1. **Persistence Configuration**: Add configuration options to API and Client
2. **Max Concurrent Tasks**: Make API configurable
3. **Provider IDs**: Document the naming convention

### Medium Priority
4. **Configuration System**: Consider unified config approach
5. **Error Format**: Standardize error responses where possible

### Low Priority
6. **Missing Features**: Add remaining features to API as needed

---

## Summary

Found **6 alignment issues** that need fixing:
- 3 High priority (configuration inconsistencies)
- 2 Medium priority (system-wide improvements)
- 1 Low priority (feature parity)

The core functionality is well-aligned, but configuration and initialization could be more consistent.