# Stateless Authentication Design

## 🎯 **Core Principle: No Client-Side State**

The Gleitzeit library should be completely stateless. Authentication tokens and user data must ONLY exist in:
1. **Unified Backend** (Redis/SQL persistence layer)
2. **Request Context** (headers, cookies)
3. **NOT in client objects or adapters**

## 🏗️ **Current Problems**

### ❌ **Stateful Anti-Patterns Found**
```python
# Client storing token
self.auth_token = auth_token  # BAD - client has state

# Adapter storing token  
self.auth_token = response['access_token']  # BAD - adapter has state

# Token passed to adapter constructor
APIAdapter(auth_token="token")  # BAD - adapter instance has state
```

## ✅ **Stateless Authentication Patterns**

### 1. **Session-Based (Web Clients)**
```python
# Browser handles cookies automatically
client = GleitzeitClient()
await client.login("user", "pass")  # Sets session cookie
# Cookie sent automatically with requests
workflows = await client.list_workflows()  # Cookie in headers
```

### 2. **Header-Based (API Clients)**
```python
# Pass auth per request
client = GleitzeitClient()

# Option A: Use context manager with token
async with client.authenticated("api-key-123") as auth_client:
    workflows = await auth_client.list_workflows()

# Option B: Pass auth to each method
workflows = await client.list_workflows(auth="Bearer token123")

# Option C: Use request context
client.set_request_headers({"Authorization": "Bearer token123"})
workflows = await client.list_workflows()  # Headers applied
```

### 3. **Backend Session Management**
```python
# Backend stores sessions in Redis/SQL
class AuthPersistence:
    def create_session(user_id) -> session_id
    def get_session(session_id) -> user_data
    def delete_session(session_id)
    
# No session data in client library!
```

## 📋 **Required Changes**

### 1. **Remove Token Storage from Client**
```python
# Before
class GleitzeitClient:
    def __init__(self, auth_token=None):
        self.auth_token = auth_token  # ❌
        
# After  
class GleitzeitClient:
    def __init__(self):
        # No auth state stored ✅
        pass
```

### 2. **Remove Token Storage from Adapter**
```python
# Before
class APIAdapter:
    async def login(self, username, password):
        response = await self._request(...)
        self.auth_token = response['token']  # ❌
        
# After
class APIAdapter:
    async def login(self, username, password):
        response = await self._request(...)
        # Token returned to caller, not stored ✅
        return response
```

### 3. **Use HTTP Session for Auth**
```python
class APIAdapter:
    def __init__(self):
        # Use session with cookie jar
        self.session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar()  # Handles cookies
        )
    
    async def login(self, username, password):
        # Server sets session cookie
        response = await self.session.post('/auth/login', ...)
        # Cookie automatically stored in jar
        return response
    
    async def list_workflows(self):
        # Cookie automatically sent
        return await self.session.get('/workflows')
```

### 4. **Optional: Request Context Pattern**
```python
class APIAdapter:
    def with_auth(self, token: str) -> 'APIAdapter':
        """Return adapter with auth headers for this request only"""
        # Create temporary adapter with headers
        temp = copy(self)
        temp.headers = {"Authorization": f"Bearer {token}"}
        return temp
    
# Usage
adapter = APIAdapter()
auth_adapter = adapter.with_auth("token123")
workflows = await auth_adapter.list_workflows()
# Original adapter unchanged - no state!
```

## 🔐 **Authentication Flow**

### Web/Session Flow
```
1. Client → POST /auth/login → Backend
2. Backend → Create session → Store in Redis/SQL
3. Backend → Set cookie → Client
4. Client → GET /workflows (cookie) → Backend  
5. Backend → Verify session → Return data
```

### API Key Flow
```
1. Client → GET /workflows + Header → Backend
2. Backend → Verify API key → Return data
(No state in client!)
```

## 📊 **Benefits**

1. **True Statelessness**
   - Client library has no auth state
   - Can scale horizontally
   - No sync issues

2. **Security**
   - Tokens only in secure backend
   - No token leakage in client code
   - Sessions can be revoked centrally

3. **Flexibility**
   - Multiple auth methods supported
   - Easy to switch auth mechanisms
   - Works with any auth provider

## 🚀 **Implementation Priority**

### Phase 1: Remove State (HIGH PRIORITY)
- [ ] Remove `auth_token` from `GleitzeitClient.__init__`
- [ ] Remove `auth_token` from `APIAdapter.__init__`  
- [ ] Remove `self.auth_token` storage from adapters
- [ ] Update login/logout to not store tokens

### Phase 2: Use Sessions (MEDIUM PRIORITY)
- [ ] Configure `aiohttp.ClientSession` with `CookieJar`
- [ ] Let backend set session cookies
- [ ] Test cookie-based auth flow

### Phase 3: Optional Enhancements (LOW PRIORITY)
- [ ] Add `with_auth()` context manager
- [ ] Add per-request auth headers
- [ ] Support multiple auth methods

## Summary

**Current State**: Client and adapters store auth tokens (STATEFUL ❌)

**Target State**: Auth only in backend + request context (STATELESS ✅)

**Key Change**: Remove ALL token storage from client library!