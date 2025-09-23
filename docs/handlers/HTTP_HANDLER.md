# HTTP Handler Documentation

## Overview

The HTTP Handler provides external API integration capabilities for Gleitzeit workflows, enabling REST API calls, webhooks, and general HTTP communication.

**Protocol**: `http/v1`

## Table of Contents

1. [Installation](#installation)
2. [Basic Usage](#basic-usage)
3. [Authentication](#authentication)
4. [Advanced Features](#advanced-features)
5. [Error Handling](#error-handling)
6. [Examples](#examples)
7. [API Reference](#api-reference)

## Installation

The HTTP handler is included in the core Gleitzeit distribution. No additional dependencies required beyond:

```bash
pip install aiohttp
```

## Basic Usage

### Simple GET Request

```yaml
workflow:
  name: Fetch User Data
  tasks:
    - name: get_user
      protocol: http/v1
      method: http/get
      params:
        url: https://api.example.com/users/123
```

### POST with JSON Body

```yaml
workflow:
  name: Create Order
  tasks:
    - name: create_order
      protocol: http/v1
      method: http/post
      params:
        url: https://api.shop.com/orders
        json:
          customer_id: 456
          items:
            - product_id: "ABC123"
              quantity: 2
          total: 99.99
```

### Using Task Results

```yaml
workflow:
  name: Chain API Calls
  tasks:
    - name: get_auth_token
      protocol: http/v1
      method: http/post
      params:
        url: https://auth.example.com/token
        json:
          client_id: "${env.CLIENT_ID}"
          client_secret: "${env.CLIENT_SECRET}"

    - name: fetch_protected_data
      protocol: http/v1
      method: http/get
      dependencies: [get_auth_token]
      params:
        url: https://api.example.com/protected
        auth:
          type: bearer
          token: "${get_auth_token.result.access_token}"
```

## Authentication

### Bearer Token

```yaml
params:
  url: https://api.example.com/protected
  auth:
    type: bearer
    token: "${env.API_TOKEN}"
```

### Basic Authentication

```yaml
params:
  url: https://api.example.com/admin
  auth:
    type: basic
    username: "${env.API_USER}"
    password: "${env.API_PASS}"
```

### API Key

```yaml
params:
  url: https://api.example.com/data
  auth:
    type: api_key
    key: "${env.API_KEY}"
    header_name: X-API-Key  # Optional, defaults to X-API-Key
```

## Advanced Features

### Rate Limiting

Prevent overwhelming external APIs:

```yaml
params:
  url: https://api.example.com/search
  rate_limit: 10  # Max 10 requests per second
  rate_limit_key: "example_api"  # Group rate limits by key
```

### Response Validation

Ensure expected status codes:

```yaml
params:
  url: https://api.example.com/users
  expected_status: [200, 201]  # Fail if not 200 or 201
```

### Response Type Handling

```yaml
# JSON (auto-detected or explicit)
params:
  url: https://api.example.com/data.json
  response_type: json  # or 'auto', 'text', 'binary'

# Extract specific field from JSON
params:
  url: https://api.example.com/user
  response_type: json
  extract_path: "$.data.user.email"  # JSONPath expression
```

### Custom Headers

```yaml
params:
  url: https://api.example.com/webhook
  headers:
    Accept: application/json
    X-Custom-Header: my-value
    User-Agent: Gleitzeit/0.0.7
```

### Query Parameters

```yaml
params:
  url: https://api.example.com/search
  params:  # Query string parameters
    q: "python"
    limit: 10
    offset: 0
```

### Form Data

```yaml
params:
  url: https://api.example.com/upload
  method: http/post
  data:  # Form encoded data
    field1: value1
    field2: value2
```

### Timeouts

```yaml
params:
  url: https://slow-api.example.com/data
  timeout: 60  # Seconds, default is 30
```

### SSL Verification

```yaml
params:
  url: https://self-signed.example.com/api
  verify_ssl: false  # Disable SSL verification (not recommended)
```

## Error Handling

### Automatic Retry

The HTTP handler integrates with Gleitzeit's retry system:

```yaml
tasks:
  - name: api_call
    protocol: http/v1
    method: http/get
    params:
      url: https://flaky-api.example.com/data
    retry:
      max_attempts: 3
      strategy: exponential
      base_delay: 1.0
      max_delay: 30.0
```

### Error Codes

The handler uses standard Gleitzeit error codes:

- `PROVIDER_ERROR`: HTTP status code mismatch or API errors
- `CONNECTION_REFUSED`: Cannot connect to server
- `INVALID_CONFIGURATION`: Missing or invalid authentication
- `METHOD_NOT_SUPPORTED`: Unknown HTTP method

### Validation with Conditional Tasks

```yaml
tasks:
  - name: check_service
    protocol: http/v1
    method: http/get
    params:
      url: https://api.example.com/health
      expected_status: [200]

  - name: validate_healthy
    protocol: validation/v1
    dependencies: [check_service]
    params:
      conditions:
        - expression: "result.status == 'healthy'"
      context:
        result: "${check_service.result}"
      on_failure: skip  # Skip dependent tasks if unhealthy

  - name: main_api_call
    protocol: http/v1
    method: http/post
    dependencies: [validate_healthy]
    params:
      url: https://api.example.com/process
```

## Examples

### GraphQL Query

```yaml
tasks:
  - name: graphql_query
    protocol: http/v1
    method: http/post
    params:
      url: https://api.example.com/graphql
      headers:
        Content-Type: application/json
      json:
        query: |
          query GetUser($id: ID!) {
            user(id: $id) {
              id
              name
              email
              posts {
                title
                published
              }
            }
          }
        variables:
          id: "${user_id}"
```

### Webhook with Callback

```yaml
tasks:
  - name: trigger_async_job
    protocol: http/v1
    method: http/post
    params:
      url: https://api.example.com/jobs
      json:
        type: "process_data"
        callback_url: "${workflow.callback_url}"
        data: "${input.data}"

  - name: wait_for_completion
    protocol: signal/v1
    dependencies: [trigger_async_job]
    params:
      signal: "job_complete_${trigger_async_job.result.job_id}"
      timeout: 3600  # Wait up to 1 hour
```

### Pagination Loop (using workflow-per-page pattern)

```yaml
# Parent workflow
workflow:
  name: Fetch All Pages
  tasks:
    - name: get_page_count
      protocol: http/v1
      method: http/get
      params:
        url: https://api.example.com/data
        params:
          page: 1
          limit: 1

    - name: spawn_page_workflows
      protocol: python/v1
      dependencies: [get_page_count]
      method: python/execute
      params:
        code: |
          import json
          total_pages = result['pagination']['total_pages']

          for page in range(1, total_pages + 1):
              # Spawn workflow for each page
              workflow = {
                  'workflow_id': f'page_{page}',
                  'workflow': {
                      'name': f'Process Page {page}',
                      'tasks': [{
                          'name': 'fetch_page',
                          'protocol': 'http/v1',
                          'method': 'http/get',
                          'params': {
                              'url': 'https://api.example.com/data',
                              'params': {'page': page, 'limit': 100}
                          }
                      }]
                  }
              }
              # Emit to workflow loader
              emit_workflow(workflow)
        context:
          result: "${get_page_count.result}"
```

### Health Check Pattern

```yaml
tasks:
  - name: health_check
    protocol: http/v1
    method: http/get
    params:
      url: https://api.example.com/health
      timeout: 5
      expected_status: [200]
    retry:
      max_attempts: 1  # Don't retry health checks

  - name: alert_if_down
    protocol: http/v1
    method: http/post
    when: "${health_check.status == 'failed'}"
    params:
      url: https://alerts.example.com/webhook
      json:
        service: "API Service"
        status: "down"
        error: "${health_check.error}"
```

## API Reference

### Supported Methods

- `http/get` - HTTP GET request
- `http/post` - HTTP POST request
- `http/put` - HTTP PUT request
- `http/delete` - HTTP DELETE request
- `http/patch` - HTTP PATCH request

### Task Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | Full URL to request |
| `method` | string | Yes | HTTP method (via task.method) |
| `headers` | dict | No | HTTP headers |
| `params` | dict | No | Query string parameters |
| `json` | any | No | JSON body (sets Content-Type) |
| `data` | any | No | Form data body |
| `auth` | dict | No | Authentication configuration |
| `timeout` | int | No | Request timeout in seconds (default: 30) |
| `expected_status` | list | No | Expected status codes |
| `response_type` | string | No | Response parsing: 'auto', 'json', 'text', 'binary' |
| `extract_path` | string | No | JSONPath for extraction |
| `rate_limit` | int | No | Requests per second limit |
| `rate_limit_key` | string | No | Rate limit grouping key |
| `verify_ssl` | bool | No | SSL verification (default: true) |

### Authentication Configuration

```python
auth = {
    'type': 'bearer|basic|api_key',

    # Bearer token
    'token': 'string',  # for type: bearer

    # Basic auth
    'username': 'string',  # for type: basic
    'password': 'string',  # for type: basic

    # API key
    'key': 'string',  # for type: api_key
    'header_name': 'string'  # optional, default: X-API-Key
}
```

### Response Format

The handler returns a TaskResult with:

```python
result = {
    'status': 200,  # HTTP status code
    'headers': {...},  # Response headers
    'data': ...,  # Parsed response (JSON, text, or binary)
    'url': 'https://...'  # Final URL after redirects
}
```

### Error Response

On failure, TaskResult includes:

```python
error = "Error message"
metadata = {
    'error_code': 'PROVIDER_ERROR',
    'error_data': {
        'expected': [200],
        'actual': 404,
        'response': 'Not found'
    }
}
```

## Integration with Other Handlers

### With Timer Handler (Polling)

```yaml
tasks:
  - name: check_status
    protocol: http/v1
    method: http/get
    params:
      url: https://api.example.com/job/${job_id}/status

  - name: wait_if_pending
    protocol: timer/v1
    dependencies: [check_status]
    when: "${check_status.result.data.status == 'pending'}"
    params:
      delay: 10

  - name: retry_check
    protocol: http/v1
    method: http/get
    dependencies: [wait_if_pending]
    params:
      url: https://api.example.com/job/${job_id}/status
```

### With Validation Handler

```yaml
tasks:
  - name: fetch_config
    protocol: http/v1
    method: http/get
    params:
      url: https://config.example.com/settings

  - name: validate_config
    protocol: validation/v1
    dependencies: [fetch_config]
    params:
      conditions:
        - expression: "version >= 2.0"
        - expression: "features.includes('required_feature')"
      context:
        version: "${fetch_config.result.data.version}"
        features: "${fetch_config.result.data.features}"
```

### With Signal Handler

```yaml
tasks:
  - name: start_long_process
    protocol: http/v1
    method: http/post
    params:
      url: https://api.example.com/process/start
      json:
        callback_signal: "process_${workflow_id}"

  - name: wait_for_callback
    protocol: signal/v1
    dependencies: [start_long_process]
    params:
      signal: "process_${workflow_id}"
      timeout: 7200  # 2 hours
```

## Best Practices

1. **Use Environment Variables for Secrets**
   ```yaml
   auth:
     type: bearer
     token: "${env.API_TOKEN}"  # Not hardcoded
   ```

2. **Set Appropriate Timeouts**
   - Short for health checks (5s)
   - Medium for normal APIs (30s)
   - Long for file uploads (300s)

3. **Implement Rate Limiting**
   - Respect API rate limits
   - Group by API endpoint

4. **Use Expected Status Validation**
   - Catch API changes early
   - Fail fast on errors

5. **Handle Pagination with Workflow-per-Page**
   - Spawn separate workflow for each page
   - Maintains isolation and parallelism

6. **Add Retry Logic**
   - Use exponential backoff
   - Set max attempts based on API

7. **Monitor with Event Store**
   - All requests/responses logged
   - Track latency and errors

## Limitations

- No streaming responses (full response buffered)
- No multipart/file uploads (use base64 in JSON)
- No WebSocket support (use signals for async)
- No automatic OAuth flow (manual token management)

## Troubleshooting

### Connection Refused

```yaml
# Check URL is correct
# Verify network connectivity
# Check if service is running
params:
  url: http://localhost:8080  # Ensure service is on this port
```

### SSL Errors

```yaml
# For development only
params:
  verify_ssl: false  # Disable verification

# For production, add proper certificates
```

### Rate Limit Exceeded

```yaml
# Reduce rate limit
params:
  rate_limit: 2  # Fewer requests per second

# Or add retry with backoff
retry:
  strategy: exponential
  base_delay: 60  # Wait 1 minute on 429
```

### Timeout Issues

```yaml
# Increase timeout
params:
  timeout: 120  # 2 minutes

# Or break into smaller requests
```

## Performance Considerations

- **Connection Pooling**: Reuses connections per domain
- **Rate Limiting**: Prevents API throttling
- **Async Execution**: Non-blocking I/O
- **Resource Cleanup**: Automatic session management

## Security Notes

1. Never hardcode credentials in workflows
2. Use HTTPS for sensitive data
3. Validate SSL certificates in production
4. Sanitize user input in URLs/parameters
5. Use authentication for all sensitive endpoints
6. Monitor for unusual request patterns

## Future Enhancements

Planned features:
- Streaming response support
- File upload/download
- OAuth 2.0 flow automation
- Request signing (AWS, etc.)
- Response caching
- Circuit breaker integration