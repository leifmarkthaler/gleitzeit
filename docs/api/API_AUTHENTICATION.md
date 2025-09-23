# Gleitzeit API Authentication Documentation

## Overview

Gleitzeit 0.0.7 implements a flexible authentication system supporting multiple authentication methods for different use cases. The system prioritizes programmatic access through client sessions and JWT tokens rather than browser cookies.

## Authentication Methods

### 1. Client Sessions (Recommended for SDKs)

Client sessions are the primary authentication method for programmatic clients. Sessions are stored server-side in Redis with a unique session ID that clients include in request headers.

#### Creating a Session

```bash
curl -X POST http://localhost:8000/auth/session/create \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username"}'
```

Response:
```json
{
  "session_id": "3f539c9f-f30e-4238-a027-ac5dd5f00783",
  "user": {
    "id": "d686424b-0aa9-4771-8ef7-f5cdc5998584",
    "username": "your_username",
    "role": "user",
    "is_active": true
  }
}
```

#### Using the Session

Include the session ID in the `X-Session-ID` header:

```bash
curl -X POST http://localhost:8000/workflows/submit \
  -H "X-Session-ID: 3f539c9f-f30e-4238-a027-ac5dd5f00783" \
  -H "Content-Type: application/json" \
  -d '{"workflow": {...}}'
```

#### Session Management

- **TTL**: Sessions expire after 24 hours by default
- **Auto-extend**: Sessions are automatically extended on each use
- **Storage**: Sessions are stored in Redis with automatic cleanup

### 2. JWT Tokens (Stateless Authentication)

JWT tokens provide stateless authentication suitable for microservices and distributed systems.

#### Creating a Token

```bash
curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username"}'
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

#### Using JWT Tokens

Include the token in the `Authorization` header:

```bash
curl -X GET http://localhost:8000/workflows/123 \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

### 3. API Keys (Service Accounts)

API keys are designed for service-to-service authentication and long-lived integrations.

#### Using API Keys

Include the API key in the `X-API-Key` header:

```bash
curl -X POST http://localhost:8000/workflows/submit \
  -H "X-API-Key: your-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{"workflow": {...}}'
```

### 4. Auto-Login (Development Only)

For development environments, auto-login creates a temporary user automatically when no credentials are provided.

Enable with environment variable:
```bash
export GLEITZEIT_AUTO_LOGIN=true
```

## Authentication Priority

When multiple authentication methods are present, they are evaluated in this order:

1. JWT Bearer token (Authorization header)
2. Client session ID (X-Session-ID header)
3. API key (X-API-Key header)
4. Auto-login (if enabled)

## Python Client SDK

### Installation

```bash
pip install -e /path/to/gleitzeit
```

### Basic Usage

```python
from gleitzeit.client.client import GleitzeitClient

# Create client
client = GleitzeitClient(api_url="http://localhost:8000")

async def example():
    async with client:
        # Create session
        session_id = await client.create_session("username")

        # Submit workflow
        response = await client.submit_workflow({
            "name": "my_workflow",
            "tasks": [...]
        })

        # Check status
        status = await client.get_workflow(response.workflow_id)
```

### Authentication Options

```python
# Option 1: Client sessions (recommended)
client = GleitzeitClient()
await client.create_session("username")

# Option 2: Use existing session
client = GleitzeitClient(session_id="existing-session-id")

# Option 3: JWT token
client = GleitzeitClient(jwt_token="eyJhbGci...")

# Option 4: API key
client = GleitzeitClient(api_key="your-api-key")
```

### Synchronous Usage

For scripts and notebooks:

```python
client = GleitzeitClient()

# Create session synchronously
session_id = client.create_session_sync("username")

# Submit workflow synchronously
response = client.submit_workflow_sync(workflow)

# Wait for completion
result = client.wait_for_completion(
    response.workflow_id,
    timeout=300  # 5 minutes
)
```

## Security Configuration

### JWT Configuration

Set JWT secret via environment variable:
```bash
export JWT_SECRET="your-secret-key-here"
```

Default configuration:
- Algorithm: HS256
- Access token expiry: 24 hours
- Refresh token expiry: 30 days

### Session Configuration

Sessions are configured in the SessionManager:
- Default TTL: 24 hours (86400 seconds)
- Auto-extend: Enabled by default
- Storage: Redis with automatic expiration

## API Endpoints

### Authentication Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/session/create` | POST | Create new client session |
| `/auth/session/validate` | POST | Validate existing session |
| `/auth/session/destroy` | POST | Destroy session (logout) |
| `/auth/token` | POST | Create JWT token |
| `/auth/token/refresh` | POST | Refresh JWT token |

### Protected Endpoints

All workflow and task endpoints require authentication:

| Endpoint | Method | Required Auth |
|----------|--------|---------------|
| `/workflows/submit` | POST | Any valid auth |
| `/workflows/{id}` | GET | Any valid auth |
| `/workflows/{id}/cancel` | POST | Any valid auth |
| `/tasks/{id}` | GET | Any valid auth |
| `/tasks/{id}/retry` | POST | Any valid auth |
| `/system/status` | GET | Any valid auth |
| `/system/metrics` | GET | Any valid auth |

## Connection Pooling

The API server implements connection pooling to efficiently manage client connections:

### Server-Side Pooling

- **Per-user pools**: Each authenticated user gets a dedicated connection pool
- **Max connections**: 10 connections per user (configurable)
- **Idle cleanup**: Pools are cleaned up after 5 minutes of inactivity
- **Health checks**: Connections are validated before use

### Client-Side Pooling

The Python SDK includes built-in connection pooling:

```python
client = GleitzeitClient(
    api_url="http://localhost:8000",
    pool_size=5  # Number of connections in pool
)
```

## Error Handling

### Authentication Errors

| Status Code | Description |
|-------------|-------------|
| 401 | Unauthorized - Invalid or missing credentials |
| 403 | Forbidden - Valid credentials but insufficient permissions |
| 404 | Session not found |

### Example Error Response

```json
{
  "detail": "Not authenticated",
  "status_code": 401
}
```

## Best Practices

### For Production

1. **Use strong JWT secrets**: Generate cryptographically secure secrets
2. **Enable HTTPS**: Always use TLS in production
3. **Implement rate limiting**: Protect against brute force attacks
4. **Monitor sessions**: Track and audit active sessions
5. **Rotate secrets**: Regularly rotate JWT secrets and API keys

### For Development

1. **Use auto-login**: Simplifies development workflow
2. **Short session TTLs**: Help catch session issues early
3. **Log authentication**: Debug auth issues with detailed logging

### Client Session Management

1. **Store session IDs securely**: Use secure storage on client side
2. **Handle expiration**: Implement session refresh logic
3. **Clean up**: Destroy sessions on logout
4. **Monitor usage**: Track session activity and patterns

## Migration from 0.0.6

The authentication system in 0.0.7 maintains compatibility with the 0.0.6 design:

- ✅ Client sessions via headers (not cookies)
- ✅ JWT token support
- ✅ API key authentication
- ✅ Connection pooling per user
- ✅ Redis-based session storage

### Key Differences

| Feature | 0.0.6 | 0.0.7 |
|---------|-------|-------|
| Session Storage | Redis | Redis (same) |
| Session Header | X-Session-ID | X-Session-ID (same) |
| JWT Support | Planned | Implemented |
| API Keys | Planned | Implemented |
| Connection Pooling | Per-user | Per-user (same) |
| Auto-login | Basic | Environment-controlled |

## Examples

### Complete Workflow Example

```python
import asyncio
from gleitzeit.client.client import GleitzeitClient

async def submit_authenticated_workflow():
    client = GleitzeitClient(api_url="http://localhost:8000")

    async with client:
        # Authenticate
        session_id = await client.create_session("my_user")
        print(f"Authenticated with session: {session_id}")

        # Define workflow
        workflow = {
            "name": "data_processing",
            "tasks": [
                {
                    "id": "fetch_data",
                    "type": "python",
                    "handler": "python",
                    "config": {
                        "code": """
import pandas as pd
result = {'rows': 1000, 'status': 'fetched'}
"""
                    }
                },
                {
                    "id": "process_data",
                    "type": "python",
                    "handler": "python",
                    "depends_on": ["fetch_data"],
                    "config": {
                        "code": """
result = {'processed': True, 'output_size': 500}
"""
                    }
                }
            ]
        }

        # Submit workflow
        response = await client.submit_workflow(workflow)
        print(f"Workflow {response.workflow_id} submitted")

        # Monitor progress
        while True:
            status = await client.get_workflow(response.workflow_id)
            state = status['state']['status']

            if state in ['completed', 'failed']:
                print(f"Workflow {state}")
                break

            print(f"Status: {state}")
            await asyncio.sleep(2)

        # Get results
        tasks = await client.get_workflow_tasks(response.workflow_id)
        for task in tasks['tasks']:
            print(f"Task {task['task_id']}: {task.get('status')}")

        # Clean up
        await client.destroy_session()
        print("Session destroyed")

# Run the example
asyncio.run(submit_authenticated_workflow())
```

## Troubleshooting

### Common Issues

1. **Session expired**: Sessions expire after 24 hours. Create a new session or implement refresh logic.

2. **Invalid JWT token**: Tokens may be expired or malformed. Check token expiry and format.

3. **Connection pool exhausted**: Too many concurrent requests. Increase pool size or implement queuing.

4. **Redis connection failed**: Ensure Redis is running and accessible.

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Health Check

Verify API server health:

```bash
curl http://localhost:8000/health/
```

Expected response:
```json
{
  "status": "healthy",
  "components": {
    "api": "healthy",
    "redis": "healthy"
  }
}
```