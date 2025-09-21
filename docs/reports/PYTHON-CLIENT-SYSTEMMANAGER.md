# Python Client SystemManager Integration

## ✅ **Client Now Always Uses SystemManager**

The Python client (`GleitzeitClient`) has been updated to **always use SystemManager** with no fallback modes.

### Key Changes

1. **Forced API Mode**
   - Client always uses `ClientMode.API` (SystemManager)
   - Native mode completely removed
   - AUTO mode maps to API mode
   - Any mode request results in API mode

2. **Authentication Support**
   ```python
   # Create client with auth token
   client = GleitzeitClient(auth_token="your-token")
   
   # OR login dynamically
   client = GleitzeitClient()
   await client.login("username", "password")
   
   # OR set token later
   client.set_auth_token("your-token")
   ```

3. **Auto-Start SystemManager**
   ```python
   # Default: auto-starts SystemManager if not running
   client = GleitzeitClient()  # auto_start_server=True by default
   await client.initialize()  # Will start server if needed
   
   # Disable for production
   client = GleitzeitClient(
       api_host="api.example.com",
       auto_start_server=False
   )
   ```

## 📝 **Usage Examples**

### Basic Usage (Local Development)
```python
from gleitzeit.client import GleitzeitClient

# Client auto-starts SystemManager if needed
client = GleitzeitClient()
await client.initialize()

# Submit a workflow
result = await client.submit_workflow(workflow)
```

### With Authentication
```python
# Option 1: Provide token upfront
client = GleitzeitClient(auth_token="your-jwt-token")

# Option 2: Login to get token
client = GleitzeitClient()
await client.initialize()
auth_result = await client.login("user@example.com", "password")
# Token is automatically stored and used

# Option 3: Set token manually
client = GleitzeitClient()
client.set_auth_token("your-jwt-token")
```

### Production Usage
```python
client = GleitzeitClient(
    api_host="api.production.com",
    api_port=443,
    auth_token=os.getenv("GLEITZEIT_TOKEN"),
    auto_start_server=False  # Don't try to start server
)
await client.initialize()

# All API calls include auth token
workflows = await client.list_workflows()
```

## 🔒 **Authentication Flow**

1. **Public Endpoints** (no auth required):
   - `/health`
   - `/docs`
   - `/auth/login`
   - `/auth/register`

2. **Protected Endpoints** (auth required):
   - All workflow operations
   - All task operations
   - Admin endpoints
   - System endpoints

3. **Token Management**:
   - Token included in `Authorization: Bearer <token>` header
   - Token persists across all API calls
   - Token cleared on logout

## 🚀 **Benefits**

1. **Consistent Architecture**
   - Python client uses same SystemManager as CLI
   - No dual-mode complexity
   - Single code path for all operations

2. **Distributed System Ready**
   - Always goes through SystemManager
   - Leverages SharedClientPool
   - Benefits from all SystemManager features

3. **Secure by Default**
   - Auth support built-in
   - Token management automatic
   - Protected endpoints enforced

4. **Developer Friendly**
   - Auto-starts server for local dev
   - Simple auth methods
   - Clean API

## 🎯 **Migration Guide**

### Old Code (Pre-Update)
```python
# Could use native or API mode
client = GleitzeitClient(mode=ClientMode.NATIVE)
# No auth support
# No auto-start
```

### New Code (Post-Update)
```python
# Always uses SystemManager
client = GleitzeitClient()  # mode is always API
# Auth support built-in
client.set_auth_token("token")
# Auto-starts SystemManager if needed
await client.initialize()
```

## Summary

The Python client now:
- ✅ **Always uses SystemManager** (no native mode)
- ✅ **Supports authentication** (token, login/logout)
- ✅ **Auto-starts server** if needed (configurable)
- ✅ **Consistent with CLI** architecture
- ✅ **Production ready** with full auth support