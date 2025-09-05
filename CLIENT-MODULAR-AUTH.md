# Client Modular Authentication

## ✅ **Modular Architecture Preserved**

The client now uses the **AuthMixin** for authentication, maintaining the modular design pattern.

### Architecture

```
GleitzeitClient
├── EventWorkflowMixin
├── EventTaskMixin
├── TaskMixin
├── WorkflowMixin
├── SystemMixin
├── AdminMixin
├── MonitoringMixin
└── AuthMixin  ✅ (Authentication via mixin)
```

### How It Works

1. **AuthMixin provides the interface**:
   ```python
   class AuthMixin:
       async def login(self, username: str, password: str) -> Dict[str, Any]
       async def logout(self) -> Dict[str, Any]
       async def get_current_user(self) -> Dict[str, Any]
   ```

2. **APIAdapter handles the backend**:
   ```python
   class APIAdapter:
       async def login(self, username: str, password: str):
           # Call /auth/login endpoint
           # Store token in self.auth_token
           # Return response
       
       async def logout(self):
           # Call /auth/logout endpoint
           # Clear self.auth_token
           # Return response
   ```

3. **Token Management**:
   - Token stored in the **adapter** (backend), not the client
   - Adapter automatically includes token in API requests
   - Token cleared on logout

## 📝 **Usage Examples**

### Basic Authentication
```python
from gleitzeit.client import GleitzeitClient

# Create client
client = GleitzeitClient()
await client.initialize()

# Login (via AuthMixin)
result = await client.login("user@example.com", "password")
# Token is now stored in the adapter

# Make authenticated requests
workflows = await client.list_workflows()  # Token included automatically

# Get current user
user = await client.get_current_user()

# Logout
await client.logout()  # Token cleared
```

### With Initial Token
```python
# Provide token at initialization
client = GleitzeitClient(auth_token="existing-token")
await client.initialize()

# Token is passed to adapter and used for all requests
workflows = await client.list_workflows()
```

## 🏗️ **Benefits of Modular Approach**

1. **Separation of Concerns**
   - Client focuses on orchestration
   - Mixin provides interface
   - Adapter handles implementation
   - Backend manages state

2. **Flexibility**
   - Easy to swap authentication mechanisms
   - Can extend or override AuthMixin
   - Adapter can be customized per backend

3. **Maintainability**
   - Auth logic isolated in mixin
   - Token management in adapter
   - Clear responsibility boundaries

4. **Testability**
   - Mock AuthMixin for testing
   - Mock adapter responses
   - Test auth independently

## 🔄 **Migration from Built-in Auth**

### Before (Built-in)
```python
# Auth methods were part of client class
client.auth_token = "token"
client.set_auth_token("token")
```

### After (Modular)
```python
# Auth via mixin, token in adapter
client = GleitzeitClient(auth_token="token")
# OR
await client.login("user", "pass")
```

## Summary

- ✅ **Modular design preserved** - AuthMixin provides auth interface
- ✅ **Backend handles tokens** - APIAdapter manages token storage
- ✅ **Clean separation** - Client → Mixin → Adapter → Backend
- ✅ **SystemManager integration** - All auth goes through SystemManager API
- ✅ **Consistent with architecture** - Follows mixin pattern like other features