# Gleitzeit Authentication System Design Draft

## Overview

This document outlines a comprehensive authentication and authorization system for Gleitzeit, covering both API and UI access control.

## Goals

1. **Secure Access**: Protect API endpoints and UI routes from unauthorized access
2. **Multi-tenancy**: Support multiple users/organizations with isolated resources
3. **Flexibility**: Support multiple authentication methods (API keys, JWT, OAuth)
4. **Audit Trail**: Track user actions for compliance and debugging
5. **Performance**: Minimal impact on request latency
6. **Backwards Compatibility**: Optional authentication to maintain existing deployments

## Architecture

### 1. Authentication Methods

#### 1.1 API Key Authentication
- **Use Case**: Service-to-service communication, CI/CD pipelines
- **Implementation**: Bearer token in Authorization header
- **Storage**: Hashed in database with metadata (name, created_at, last_used)
```python
# Example usage
headers = {"Authorization": "Bearer glzt_prod_a1b2c3d4e5f6"}
```

#### 1.2 JWT (JSON Web Tokens)
- **Use Case**: Web UI sessions, temporary access
- **Implementation**: Short-lived access tokens + refresh tokens
- **Storage**: Refresh tokens in Redis with TTL
```python
# Token structure
{
  "sub": "user_id",
  "email": "user@example.com",
  "roles": ["admin", "developer"],
  "exp": 1234567890,
  "iat": 1234567800
}
```

#### 1.3 OAuth 2.0 / OIDC
- **Use Case**: Enterprise SSO integration
- **Providers**: Google, GitHub, Microsoft, Okta, Auth0
- **Implementation**: Standard OAuth flow with PKCE for SPAs

#### 1.4 Basic Authentication
- **Use Case**: Simple deployments, development
- **Implementation**: Username/password in Authorization header
- **Note**: Should only be used over HTTPS

### 2. Authorization Model

#### 2.1 RBAC (Role-Based Access Control)
```yaml
roles:
  admin:
    description: "Full system access"
    permissions:
      - "*"
  
  developer:
    description: "Create and manage workflows"
    permissions:
      - "workflows:create"
      - "workflows:read"
      - "workflows:update"
      - "workflows:delete"
      - "tasks:create"
      - "tasks:read"
      - "tasks:cancel"
      - "tasks:retry"
  
  operator:
    description: "Monitor and operate workflows"
    permissions:
      - "workflows:read"
      - "workflows:pause"
      - "workflows:resume"
      - "tasks:read"
      - "tasks:cancel"
      - "tasks:retry"
      - "queues:read"
  
  viewer:
    description: "Read-only access"
    permissions:
      - "workflows:read"
      - "tasks:read"
      - "queues:read"
      - "statistics:read"
```

#### 2.2 Resource-Based Permissions
```python
# Fine-grained permissions per resource
{
  "user_id": "user123",
  "resource_type": "workflow",
  "resource_id": "workflow-abc123",
  "permissions": ["read", "update", "delete"]
}
```

### 3. Database Schema

#### 3.1 Users Table
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100) UNIQUE,
    password_hash VARCHAR(255),  -- For basic auth
    full_name VARCHAR(255),
    avatar_url TEXT,
    is_active BOOLEAN DEFAULT true,
    is_superuser BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);
```

#### 3.2 API Keys Table
```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    key_hash VARCHAR(255) NOT NULL,  -- SHA256 hash
    key_prefix VARCHAR(20) NOT NULL,  -- For identification (glzt_prod_)
    name VARCHAR(100),
    description TEXT,
    expires_at TIMESTAMP,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP,
    permissions JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_user_id ON api_keys(user_id);
```

#### 3.3 Roles Table
```sql
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    permissions JSONB NOT NULL DEFAULT '[]',
    is_system BOOLEAN DEFAULT false,  -- Built-in roles
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 3.4 User Roles Table
```sql
CREATE TABLE user_roles (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    granted_by UUID REFERENCES users(id),
    expires_at TIMESTAMP,
    PRIMARY KEY (user_id, role_id)
);
```

#### 3.5 Audit Log Table
```sql
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(255),
    details JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at);
```

### 4. Implementation Components

#### 4.1 Authentication Middleware
```python
# src/gleitzeit/auth/middleware.py
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPBasic
import jwt

class AuthMiddleware:
    def __init__(self, auth_config: dict):
        self.enabled = auth_config.get("enabled", False)
        self.jwt_secret = auth_config.get("jwt_secret")
        self.jwt_algorithm = auth_config.get("jwt_algorithm", "HS256")
        self.api_key_header = auth_config.get("api_key_header", "X-API-Key")
    
    async def __call__(self, request: Request):
        if not self.enabled:
            # Auth disabled, allow all requests
            request.state.user = {"id": "anonymous", "roles": ["admin"]}
            return
        
        # Check for API key
        api_key = request.headers.get(self.api_key_header)
        if api_key:
            user = await self.validate_api_key(api_key)
            if user:
                request.state.user = user
                return
        
        # Check for JWT
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            user = await self.validate_jwt(token)
            if user:
                request.state.user = user
                return
        
        # No valid auth found
        raise HTTPException(status_code=401, detail="Authentication required")
    
    async def validate_api_key(self, api_key: str):
        # Hash the key and lookup in database
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        # ... database lookup logic
        pass
    
    async def validate_jwt(self, token: str):
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
            # ... validate expiry, fetch user details
            return payload
        except jwt.InvalidTokenError:
            return None
```

#### 4.2 Permission Decorator
```python
# src/gleitzeit/auth/permissions.py
from functools import wraps
from fastapi import HTTPException

def require_permission(permission: str):
    """Decorator to check if user has required permission"""
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            user = request.state.user
            
            # Check if user has permission
            if not has_permission(user, permission):
                raise HTTPException(
                    status_code=403, 
                    detail=f"Permission '{permission}' required"
                )
            
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator

def has_permission(user: dict, permission: str) -> bool:
    """Check if user has specific permission"""
    if user.get("is_superuser"):
        return True
    
    user_permissions = set()
    for role in user.get("roles", []):
        user_permissions.update(get_role_permissions(role))
    
    # Check exact match or wildcard
    if permission in user_permissions:
        return True
    
    # Check wildcard permissions (e.g., "workflows:*")
    resource, action = permission.split(":")
    if f"{resource}:*" in user_permissions or "*" in user_permissions:
        return True
    
    return False
```

#### 4.3 API Endpoints for Auth
```python
# src/gleitzeit/api/auth.py
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta

router = APIRouter(prefix="/auth", tags=["authentication"])

@router.post("/login")
async def login(credentials: LoginCredentials):
    """Authenticate user and return JWT token"""
    user = await authenticate_user(credentials.email, credentials.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_jwt_token(user, expires_in=timedelta(hours=1))
    refresh_token = create_refresh_token(user, expires_in=timedelta(days=30))
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 3600
    }

@router.post("/refresh")
async def refresh_token(refresh_token: str):
    """Exchange refresh token for new access token"""
    payload = validate_refresh_token(refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    
    user = await get_user(payload["sub"])
    access_token = create_jwt_token(user, expires_in=timedelta(hours=1))
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 3600
    }

@router.post("/logout")
async def logout(request: Request):
    """Invalidate user's tokens"""
    # Add refresh token to blacklist
    # Clear any server-side sessions
    return {"message": "Logged out successfully"}

@router.get("/me")
@require_permission("users:read_self")
async def get_current_user(request: Request):
    """Get current user details"""
    return request.state.user

@router.post("/api-keys")
@require_permission("api_keys:create")
async def create_api_key(request: Request, key_data: ApiKeyCreate):
    """Generate new API key for current user"""
    user = request.state.user
    api_key = generate_api_key()
    
    # Store hashed key in database
    await store_api_key(user["id"], api_key, key_data)
    
    return {
        "api_key": api_key,  # Only returned once
        "key_id": key_id,
        "created_at": datetime.now()
    }

@router.get("/api-keys")
@require_permission("api_keys:read")
async def list_api_keys(request: Request):
    """List user's API keys (without the actual keys)"""
    user = request.state.user
    keys = await get_user_api_keys(user["id"])
    return keys

@router.delete("/api-keys/{key_id}")
@require_permission("api_keys:delete")
async def revoke_api_key(request: Request, key_id: str):
    """Revoke an API key"""
    user = request.state.user
    await revoke_api_key(user["id"], key_id)
    return {"message": "API key revoked"}
```

### 5. Configuration

#### 5.1 Environment Variables
```bash
# Authentication settings
GLEITZEIT_AUTH_ENABLED=true
GLEITZEIT_AUTH_JWT_SECRET=your-secret-key-here
GLEITZEIT_AUTH_JWT_ALGORITHM=HS256
GLEITZEIT_AUTH_TOKEN_EXPIRY=3600
GLEITZEIT_AUTH_REFRESH_TOKEN_EXPIRY=2592000

# OAuth providers (optional)
GLEITZEIT_OAUTH_GITHUB_CLIENT_ID=xxx
GLEITZEIT_OAUTH_GITHUB_CLIENT_SECRET=xxx
GLEITZEIT_OAUTH_GOOGLE_CLIENT_ID=xxx
GLEITZEIT_OAUTH_GOOGLE_CLIENT_SECRET=xxx

# Database for auth
GLEITZEIT_AUTH_DATABASE_URL=postgresql://user:pass@localhost/gleitzeit_auth
```

#### 5.2 Configuration File
```yaml
# config/auth.yaml
authentication:
  enabled: true
  
  methods:
    - api_key
    - jwt
    - oauth
  
  jwt:
    secret: ${GLEITZEIT_AUTH_JWT_SECRET}
    algorithm: HS256
    access_token_expire_minutes: 60
    refresh_token_expire_days: 30
  
  oauth:
    providers:
      github:
        client_id: ${GLEITZEIT_OAUTH_GITHUB_CLIENT_ID}
        client_secret: ${GLEITZEIT_OAUTH_GITHUB_CLIENT_SECRET}
        authorize_url: https://github.com/login/oauth/authorize
        token_url: https://github.com/login/oauth/access_token
        
  password_policy:
    min_length: 8
    require_uppercase: true
    require_lowercase: true
    require_numbers: true
    require_special: false
  
  session:
    cookie_name: gleitzeit_session
    cookie_secure: true  # HTTPS only
    cookie_httponly: true
    cookie_samesite: lax

authorization:
  default_roles:
    - viewer
  
  superuser_email: admin@example.com
  
  resource_isolation: true  # Users can only see their own resources
```

### 6. Migration Path

#### Phase 1: Foundation (v1.0)
- [ ] Database schema for users and API keys
- [ ] Basic authentication middleware
- [ ] API key generation and validation
- [ ] Simple RBAC with predefined roles

#### Phase 2: JWT Support (v1.1)
- [ ] JWT token generation and validation
- [ ] Login/logout endpoints
- [ ] Refresh token mechanism
- [ ] Session management

#### Phase 3: OAuth Integration (v1.2)
- [ ] OAuth 2.0 flow implementation
- [ ] GitHub and Google providers
- [ ] SSO configuration UI
- [ ] Account linking

#### Phase 4: Advanced Features (v2.0)
- [ ] Multi-tenancy support
- [ ] Fine-grained permissions
- [ ] Audit logging
- [ ] API rate limiting per user
- [ ] 2FA support

### 7. Security Considerations

1. **Password Storage**: Use bcrypt or Argon2 for password hashing
2. **Token Security**: 
   - Short-lived access tokens (1 hour)
   - Longer-lived refresh tokens (30 days)
   - Token rotation on refresh
3. **API Key Security**:
   - Show key only once on creation
   - Store only hashed versions
   - Support key rotation
4. **Rate Limiting**: Implement per-user rate limits
5. **CORS**: Properly configure CORS for web UI
6. **HTTPS**: Enforce HTTPS in production
7. **Audit Trail**: Log all authentication events

### 8. UI Integration

#### 8.1 Login Page
```html
<!-- templates/auth/login.html -->
<form id="login-form">
  <input type="email" name="email" required>
  <input type="password" name="password" required>
  <button type="submit">Login</button>
  
  <!-- OAuth options -->
  <a href="/auth/oauth/github">Login with GitHub</a>
  <a href="/auth/oauth/google">Login with Google</a>
</form>
```

#### 8.2 Protected Routes
```javascript
// Frontend route protection
const protectedRoute = (component) => {
  const token = localStorage.getItem('access_token');
  if (!token) {
    window.location.href = '/login';
    return null;
  }
  return component;
};
```

#### 8.3 API Client with Auth
```javascript
class AuthenticatedClient {
  constructor() {
    this.token = localStorage.getItem('access_token');
  }
  
  async request(url, options = {}) {
    options.headers = {
      ...options.headers,
      'Authorization': `Bearer ${this.token}`
    };
    
    const response = await fetch(url, options);
    
    if (response.status === 401) {
      // Try to refresh token
      const refreshed = await this.refreshToken();
      if (refreshed) {
        return this.request(url, options);
      } else {
        // Redirect to login
        window.location.href = '/login';
      }
    }
    
    return response;
  }
}
```

### 9. CLI Authentication

```bash
# Login with username/password
gleitzeit auth login --username admin --password secret

# Login with API key
gleitzeit auth login --api-key glzt_prod_abc123

# Set authentication for session
export GLEITZEIT_API_KEY=glzt_prod_abc123

# Or in config file
cat ~/.gleitzeit/config.yaml
api_key: glzt_prod_abc123
api_url: https://api.example.com
```

### 10. Backwards Compatibility

To maintain backwards compatibility:

1. **Opt-in Authentication**: Disabled by default
2. **Anonymous Mode**: When disabled, all users have admin permissions
3. **Gradual Migration**: 
   - v1: Optional auth with API keys
   - v2: Full auth with deprecation warnings
   - v3: Required auth (major version bump)

### 11. Testing Strategy

```python
# tests/test_auth.py
import pytest
from fastapi.testclient import TestClient

def test_unauthenticated_request(client):
    """Test that unauthenticated requests are rejected"""
    response = client.get("/api/workflows")
    assert response.status_code == 401

def test_api_key_auth(client, api_key):
    """Test API key authentication"""
    response = client.get(
        "/api/workflows",
        headers={"X-API-Key": api_key}
    )
    assert response.status_code == 200

def test_jwt_auth(client, jwt_token):
    """Test JWT authentication"""
    response = client.get(
        "/api/workflows",
        headers={"Authorization": f"Bearer {jwt_token}"}
    )
    assert response.status_code == 200

def test_permission_check(client, viewer_token):
    """Test that viewers cannot create workflows"""
    response = client.post(
        "/api/workflows",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"name": "Test"}
    )
    assert response.status_code == 403
```

## Next Steps

1. **Review and Feedback**: Gather requirements from stakeholders
2. **Technology Selection**: Choose auth libraries (e.g., FastAPI-Users, Authlib)
3. **Database Design**: Finalize schema based on requirements
4. **Prototype**: Build minimal MVP with API key auth
5. **Security Audit**: Review implementation with security team
6. **Documentation**: Create user guides and API documentation
7. **Migration Tools**: Build tools to migrate existing deployments

## Open Questions

1. Should we support LDAP/Active Directory integration?
2. Do we need multi-factor authentication (2FA)?
3. Should API keys have expiration dates?
4. How should we handle service accounts?
5. Do we need IP allowlisting for API keys?
6. Should we support WebAuthn/Passkeys?
7. Rate limiting strategy per user/role?
8. How to handle authentication in distributed deployments?

## Resources

- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [JWT Best Practices](https://datatracker.ietf.org/doc/html/rfc8725)
- [OAuth 2.0 Security Best Practices](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-security-topics)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)