# Current Client Architecture

## Overview
The GleitzeitClient is a stateless client that provides a unified interface for workflow orchestration. It supports multiple modes of operation and maintains security through token-based authentication for internal use.

## Client Modes

### 1. API Mode (ClientMode.API)
- **Purpose**: For external clients to interact with Gleitzeit server
- **Communication**: HTTP/WebSocket to API server
- **Authentication**: Cookie-based sessions (stateless)
- **Use Case**: External Python scripts, CLI tools, user applications
- **Example**:
```python
client = GleitzeitClient(
    mode=ClientMode.API,
    api_host="localhost",
    api_port=8000
)
await client.initialize()
await client.login("username", "password")  # Sets session cookie
workflows = await client.list_workflows()
```

### 2. NATIVE Mode (ClientMode.NATIVE)
- **Purpose**: Internal API server use only
- **Communication**: Direct persistence access (bypasses HTTP)
- **Authentication**: Service token required (prevents external access)
- **Security**: Token validation with constant-time comparison
- **Use Case**: API server's internal operations
- **Example** (API internal only):
```python
# This only works inside the API server with valid service token
client = GleitzeitClient(
    mode=ClientMode.NATIVE,
    service_token=valid_token,  # Required!
    event_mode='direct'
)
```

## Security Architecture

### Service Token Authentication (NATIVE Mode)
1. **Token Generation**: 
   - API server generates cryptographically secure token at startup
   - Can be configured via `GLEITZEIT_SERVICE_TOKEN` env var
   - 256-bit entropy (32 bytes hex encoded)

2. **Token Storage**:
   - Stored as class variable in GleitzeitClient
   - Set by API during startup via `GleitzeitClient.set_service_token()`
   - Never logged or exposed

3. **Token Validation**:
   - Required parameter for NATIVE mode
   - Validated using constant-time comparison (prevents timing attacks)
   - Rejection raises PermissionError

4. **Protection Against**:
   - External code using NATIVE mode to bypass auth
   - Token guessing via timing attacks
   - Unauthorized direct persistence access

### Cookie-Based Authentication (API Mode)
- Stateless session management
- Cookies stored in httpx client's cookie jar
- No tokens stored in client instance
- Sessions managed by backend persistence

## Architecture Components

### 1. Client Core (`client.py`)
```python
class GleitzeitClient(
    EventWorkflowMixin,    # Event-driven workflow methods
    EventTaskMixin,        # Event-driven task methods
    TaskMixin,             # Standard task operations
    WorkflowMixin,         # Workflow management
    SystemMixin,           # System status/control
    AdminMixin,            # Administrative operations
    MonitoringMixin,       # Monitoring capabilities
    AuthMixin              # Authentication methods
):
```

### 2. Adapters
**APIAdapter** (`adapters/api.py`):
- Makes HTTP requests to API server
- Manages cookie-based sessions
- Handles response parsing and error mapping

**NativeAdapter** (`adapters/native.py`):
- Direct persistence access
- Bypasses HTTP layer entirely
- Used only by API server internally
- Requires service token authentication

### 3. Event System
- **EventMode.WEBSOCKET**: Real-time events via WebSocket
- **EventMode.POLLING**: Periodic polling for events
- **EventMode.DIRECT**: Direct event bus connection (NATIVE mode)
- Events only enabled in API mode by default

## Stateless Design Principles

1. **No Client-Side State**:
   - No auth tokens stored in client
   - No session data in client instance
   - All state in backend persistence (Redis/SQL)

2. **Distributed Operation**:
   - Multiple API servers share state via persistence
   - Client pools coordinated across instances
   - No single point of failure

3. **Resource Management**:
   - SharedClientPool manages client lifecycle
   - Automatic cleanup of idle clients
   - Connection pooling for efficiency

## API Server Integration

### Dependency Injection (`dependencies.py`)
```python
# API uses NATIVE mode internally with service token
_shared_client_pool = SharedClientPool(
    persistence=persistence,
    instance_id=instance_id,
    max_size=20,
    mode=ClientMode.NATIVE,
    service_token=service_token  # From API startup
)
```

### Request Flow
1. API receives HTTP request
2. Gets client from SharedClientPool (NATIVE mode)
3. Client uses NativeAdapter for direct persistence
4. Results returned via HTTP response
5. Client returned to pool

## Usage Examples

### External Client (API Mode)
```python
# External Python script
from gleitzeit.client import GleitzeitClient, ClientMode

async def main():
    # Create API client
    client = GleitzeitClient(
        mode=ClientMode.API,
        api_host="localhost",
        api_port=8000
    )
    await client.initialize()
    
    # Authenticate (sets session cookie)
    await client.login("user", "pass")
    
    # Use client
    workflows = await client.list_workflows()
    status = await client.get_system_status()
    
    await client.shutdown()
```

### CLI Usage
```bash
# CLI uses API mode with cookie persistence
gleitzeit login user pass
gleitzeit workflow list
gleitzeit task submit my_task.yaml
```

### Attempting NATIVE Mode Externally (Blocked)
```python
# This will FAIL with security error
client = GleitzeitClient(
    mode=ClientMode.NATIVE  # Missing required service_token
)
# ValueError: NATIVE mode requires service_token parameter

# This will also FAIL
client = GleitzeitClient(
    mode=ClientMode.NATIVE,
    service_token="wrong_token"  # Invalid token
)
# PermissionError: Invalid service token
```

## Key Security Features

1. **Mode Separation**:
   - API mode for external use (with auth)
   - NATIVE mode for internal use only (token required)

2. **Token Security**:
   - Cryptographically secure generation
   - Constant-time validation
   - Never exposed in logs or errors

3. **Stateless Operation**:
   - No sensitive data in client memory
   - All auth handled by backend
   - Sessions via secure cookies

4. **Audit Trail**:
   - All operations logged
   - Failed auth attempts tracked
   - Service token usage monitored

## Benefits of Current Architecture

1. **Security**: NATIVE mode cannot be abused by external code
2. **Performance**: Direct persistence access for API server
3. **Simplicity**: No circular dependencies
4. **Consistency**: All modes require proper authentication
5. **Scalability**: Stateless design enables horizontal scaling
6. **Maintainability**: Clear separation of concerns

## Migration from Previous Versions

If upgrading from versions without service token auth:

1. **API Server**: Will auto-generate token on startup
2. **External Clients**: Continue using API mode (no changes)
3. **NATIVE Mode Users**: Must add service_token parameter
4. **Environment**: Can set `GLEITZEIT_SERVICE_TOKEN` for consistency

## Future Improvements

Potential enhancements while maintaining security:

1. **Token Rotation**: Periodic token refresh
2. **Multiple Tokens**: Different tokens for different services
3. **Token Scoping**: Limit token permissions
4. **Audit Enhancement**: More detailed token usage tracking
5. **Certificate Auth**: Alternative to token-based auth