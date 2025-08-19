# Timeout Async/Await Analysis

## Summary
After analyzing the codebase, I found that **most timeout operations are properly using async/await**, but there are **2 blocking timeout operations** that need to be fixed.

## ✅ Properly Async Timeouts

### 1. HTTP Client Timeouts (aiohttp)
All HTTP operations use proper async timeout:
```python
# Correct async pattern found throughout:
async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
    ...

# Also correct:
async with session.get(url, timeout=5) as response:
    ...
```

### 2. asyncio.wait_for Usage
Proper async timeout for coroutines:
```python
# In python_provider.py:227
stdout, stderr = await asyncio.wait_for(
    process.communicate(input=code.encode()),
    timeout=timeout_value
)

# In test files - proper pattern
await asyncio.wait_for(provider.initialize(), timeout=3.0)
```

### 3. Async Process Wait
```python
# In python_provider.py:233
await process.wait()  # Proper async wait
```

## ❌ BLOCKING Timeout Operations Found

### 1. **OllamaHub - Process Termination** 
**File**: `src/gleitzeit/hub/ollama_hub.py:252`
```python
# BLOCKING - This blocks the event loop!
process.wait(timeout=10)  # psutil Process.wait is synchronous
```
**Impact**: Blocks async event loop for up to 10 seconds during Ollama instance shutdown

**Fix Needed**:
```python
# Use asyncio with executor for blocking calls
loop = asyncio.get_event_loop()
await loop.run_in_executor(None, process.wait, 10)
```

### 2. **Client - Server Process Termination**
**File**: `src/gleitzeit/client.py:182`
```python
# BLOCKING - subprocess.wait is synchronous!
self._server_process.wait(timeout=5)
```
**Impact**: Blocks event loop for up to 5 seconds during API server shutdown

**Fix Needed**:
```python
# Since this is in async context (__aexit__), use:
loop = asyncio.get_event_loop()
await loop.run_in_executor(None, self._server_process.wait, 5)
```

## ⚠️ Synchronous Code (Acceptable)

### CLI Dev Commands
**File**: `src/gleitzeit/cli/commands/dev.py:115-116`
```python
result = subprocess.run(['redis-cli', 'ping'], 
                      capture_output=True, text=True, timeout=2)
```
**Status**: ✅ OK - This is in a synchronous CLI command context, not async

## 🔍 Timeout Configuration Issues

Found inconsistent timeout values across components:

| Operation | Timeout | Location |
|-----------|---------|----------|
| HTTP health check | 2s | aiohttp.ClientTimeout(total=2) |
| HTTP operations | 5s | timeout=5 |
| Process termination | 10s | process.wait(timeout=10) |
| Server shutdown | 5s | _server_process.wait(timeout=5) |
| Redis operations | 5s | socket_timeout=5 |
| SQL pool | 30s | pool_timeout=30 |
| Lock acquisition | 30s | timeout: int = 30 |
| Task execution | 300s | attempt_timeout=300 |

## 📋 Recommendations

### High Priority Fixes

1. **Fix blocking process.wait() calls**:
   - `ollama_hub.py:252` - Use executor for psutil wait
   - `client.py:182` - Use executor for subprocess wait

2. **Create timeout configuration system**:
   ```python
   class TimeoutConfig:
       http_health: float = 5.0
       http_operation: float = 30.0
       process_shutdown: float = 10.0
       task_execution: float = 300.0
       lock_acquisition: float = 30.0
   ```

3. **Standardize async timeout patterns**:
   - Always use `asyncio.wait_for()` for async operations
   - Always use `run_in_executor()` for blocking operations in async context
   - Always use `aiohttp.ClientTimeout` for HTTP operations

## Code Changes Needed

### Fix 1: OllamaHub
```python
# src/gleitzeit/hub/ollama_hub.py:250-254
# Replace:
try:
    process.wait(timeout=10)
except psutil.TimeoutExpired:
    process.kill()

# With:
try:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, process.wait, 10)
except psutil.TimeoutExpired:
    process.kill()
```

### Fix 2: Client
```python
# src/gleitzeit/client.py:181-184
# Replace:
try:
    self._server_process.wait(timeout=5)
except subprocess.TimeoutExpired:
    self._server_process.kill()

# With:
try:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, self._server_process.wait, 5)
except subprocess.TimeoutExpired:
    self._server_process.kill()
```

## Verification

After fixes, verify with:
```bash
# Check for blocking operations
grep -r "\.wait(timeout" --include="*.py" | grep -v "await"

# Check for subprocess.run in async contexts
grep -r "subprocess\.run\|subprocess\.call" --include="*.py"
```

## Summary

- **2 blocking timeout operations** need immediate fixing
- Both are in shutdown/cleanup code paths
- All other async timeout usage is correct
- Need centralized timeout configuration system