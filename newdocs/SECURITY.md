# Security Guide

## Overview

Gleitzeit v0.0.5 implements multiple layers of security to ensure safe execution of workflows, protection of data, and isolation of resources. This guide covers security architecture, best practices, and configuration for production deployments.

## Security Architecture

```
┌─────────────────────────────────────────────────────┐
│                   API Layer                         │
│         (Authentication & Authorization)            │
│                                                     │
│  • API Key validation                              │
│  • JWT token verification                          │
│  • Rate limiting                                   │
│  • Request validation                              │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│              Execution Layer                        │
│           (Workflow & Task Security)                │
│                                                     │
│  • Parameter sanitization                          │
│  • Resource limits                                 │
│  • Timeout enforcement                             │
│  • Dependency validation                           │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│              Provider Layer                         │
│          (Protocol-Specific Security)               │
│                                                     │
│  • Python: Container isolation                     │
│  • LLM: Prompt sanitization                        │
│  • MCP: Command validation                         │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│              Resource Layer                         │
│            (Infrastructure Security)                │
│                                                     │
│  • Container sandboxing                            │
│  • Network isolation                               │
│  • Resource quotas                                 │
│  • Health monitoring                               │
└──────────────────────────────────────────────────────┘
```

## Authentication & Authorization

### API Key Authentication

#### Configuration
```yaml
# config.yaml
security:
  api_key_required: true
  api_key: ${GLEITZEIT_API_KEY}  # Use environment variable
  api_key_header: "X-API-Key"    # Custom header name
```

#### Usage
```bash
# Set API key
export GLEITZEIT_API_KEY=your-secure-api-key-here

# Use in requests
curl -H "X-API-Key: your-secure-api-key-here" \
  http://localhost:8000/api/workflows

# Or with Authorization header
curl -H "Authorization: Bearer your-secure-api-key-here" \
  http://localhost:8000/api/workflows
```

#### Generating Secure API Keys
```python
import secrets
import string

def generate_api_key(length=32):
    """Generate a secure API key"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

# Generate key
api_key = generate_api_key()
print(f"API Key: {api_key}")
```

### JWT Authentication (Advanced)

#### Configuration
```yaml
security:
  jwt_enabled: true
  jwt_secret: ${JWT_SECRET}  # Must be kept secret
  jwt_algorithm: "HS256"
  jwt_expiration: 3600  # 1 hour
  jwt_refresh_enabled: true
  jwt_refresh_expiration: 86400  # 24 hours
```

#### Implementation
```python
import jwt
from datetime import datetime, timedelta

class JWTAuth:
    def generate_token(self, user_id: str, role: str = "user"):
        """Generate JWT token"""
        payload = {
            "user_id": user_id,
            "role": role,
            "exp": datetime.utcnow() + timedelta(seconds=3600),
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, self.secret, algorithm="HS256")
    
    def verify_token(self, token: str):
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(token, self.secret, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token expired")
        except jwt.InvalidTokenError:
            raise AuthenticationError("Invalid token")
```

### Role-Based Access Control (RBAC)

```yaml
security:
  rbac_enabled: true
  roles:
    admin:
      permissions:
        - workflow:*
        - resource:*
        - system:*
    developer:
      permissions:
        - workflow:submit
        - workflow:status
        - workflow:cancel
        - resource:list
    viewer:
      permissions:
        - workflow:status
        - workflow:list
        - resource:list
```

## Container Security

### Python Execution Isolation

Gleitzeit v0.0.5 executes all Python code in isolated Docker containers:

#### Security Features
1. **No arbitrary script execution** - Only containerized execution
2. **Network isolation** - Containers run without network access
3. **Resource limits** - CPU and memory constraints
4. **Read-only filesystems** - Prevent system modifications
5. **User namespace mapping** - Run as non-root user

#### Container Configuration
```yaml
resources:
  docker:
    security:
      network_mode: "none"  # No network access
      read_only: true       # Read-only root filesystem
      no_new_privileges: true
      user: "1000:1000"     # Non-root user
      security_opt:
        - "no-new-privileges:true"
        - "seccomp=default"
      cap_drop:
        - ALL  # Drop all capabilities
      cap_add: []  # Add only necessary capabilities
      memory_limit: "512m"
      cpu_limit: 1.0
      pids_limit: 100
      tmpfs:
        /tmp: "size=100m,mode=1777"  # Writable tmp only
```

#### Secure Python Provider Configuration
```python
from gleitzeit.providers.python_provider import PythonProvider

provider = PythonProvider(
    docker_hub=docker_hub,
    allowed_imports=[  # Whitelist imports
        "json",
        "math",
        "datetime",
        "re"
    ],
    forbidden_modules=[  # Explicitly block
        "os",
        "subprocess",
        "eval",
        "exec",
        "__import__"
    ],
    max_execution_time=60,
    max_memory="256m"
)
```

### Container Image Security

#### Use Verified Images
```yaml
resources:
  docker:
    allowed_images:
      - python:3.11-slim@sha256:abc123...  # Pin by digest
      - node:18-alpine@sha256:def456...
    image_pull_policy: "always"  # Always pull latest
    registry_auth:
      username: ${DOCKER_USERNAME}
      password: ${DOCKER_PASSWORD}
```

#### Image Scanning
```bash
# Scan images for vulnerabilities
docker scan python:3.11-slim

# Use Trivy for comprehensive scanning
trivy image python:3.11-slim
```

## Input Validation & Sanitization

### Workflow Validation

```python
from gleitzeit.core.validation import WorkflowValidator

class SecureWorkflowValidator(WorkflowValidator):
    def validate_workflow(self, workflow: dict) -> bool:
        """Comprehensive workflow validation"""
        
        # 1. Schema validation
        self.validate_schema(workflow)
        
        # 2. Task validation
        for task in workflow.get('tasks', []):
            self.validate_task_security(task)
        
        # 3. Parameter validation
        self.validate_parameters(workflow.get('parameters', {}))
        
        # 4. Resource limits
        self.validate_resource_limits(workflow)
        
        return True
    
    def validate_task_security(self, task: dict):
        """Validate task security constraints"""
        
        # Check protocol is allowed
        allowed_protocols = ['llm/v1', 'python/v1', 'mcp/v1']
        if task.get('protocol') not in allowed_protocols:
            raise SecurityError(f"Protocol not allowed: {task.get('protocol')}")
        
        # Validate timeout
        max_timeout = 3600  # 1 hour max
        if task.get('timeout', 0) > max_timeout:
            raise SecurityError(f"Timeout exceeds maximum: {max_timeout}")
        
        # Check for injection attempts
        self.check_injection(task.get('parameters', {}))
```

### Parameter Sanitization

```python
import re
from typing import Any

class ParameterSanitizer:
    """Sanitize workflow parameters"""
    
    # Dangerous patterns
    DANGEROUS_PATTERNS = [
        r'__[a-z]+__',  # Python magic methods
        r'eval\s*\(',    # eval calls
        r'exec\s*\(',    # exec calls
        r'import\s+',    # import statements
        r'open\s*\(',    # file operations
        r'\$\{.*\}',     # Shell substitutions
        r'`.*`',         # Command substitution
    ]
    
    def sanitize(self, value: Any) -> Any:
        """Recursively sanitize parameters"""
        
        if isinstance(value, str):
            return self.sanitize_string(value)
        elif isinstance(value, dict):
            return {k: self.sanitize(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self.sanitize(item) for item in value]
        return value
    
    def sanitize_string(self, text: str) -> str:
        """Sanitize string values"""
        
        # Check for dangerous patterns
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                raise SecurityError(f"Dangerous pattern detected: {pattern}")
        
        # Escape special characters
        text = text.replace('\\', '\\\\')
        text = text.replace('"', '\\"')
        text = text.replace("'", "\\'")
        
        # Limit length
        max_length = 10000
        if len(text) > max_length:
            text = text[:max_length]
        
        return text
```

## Network Security

### TLS/SSL Configuration

```yaml
security:
  tls:
    enabled: true
    cert_file: /etc/gleitzeit/certs/server.crt
    key_file: /etc/gleitzeit/certs/server.key
    ca_file: /etc/gleitzeit/certs/ca.crt
    min_version: "TLS1.2"
    ciphers:
      - "ECDHE-RSA-AES256-GCM-SHA384"
      - "ECDHE-RSA-AES128-GCM-SHA256"
    client_auth: true  # Require client certificates
```

### Network Isolation

```yaml
resources:
  docker:
    networks:
      internal:
        driver: bridge
        internal: true  # No external access
        ipam:
          config:
            - subnet: 172.20.0.0/16
      
  ollama:
    bind_address: "127.0.0.1"  # Local only
    allowed_ips:
      - "127.0.0.1"
      - "::1"
```

### Rate Limiting

```yaml
security:
  rate_limiting:
    enabled: true
    rules:
      - path: "/api/workflows"
        method: "POST"
        limit: 10
        window: 60  # 10 requests per minute
      - path: "/api/tasks"
        method: "POST"
        limit: 100
        window: 60  # 100 requests per minute
      - path: "/api/*"
        method: "*"
        limit: 1000
        window: 60  # 1000 requests per minute total
    
    # Per-user limits
    user_limits:
      default:
        requests_per_minute: 100
        concurrent_workflows: 5
      premium:
        requests_per_minute: 1000
        concurrent_workflows: 50
```

## Data Security

### Encryption at Rest

```yaml
persistence:
  encryption:
    enabled: true
    algorithm: "AES-256-GCM"
    key_file: ${ENCRYPTION_KEY_FILE}
    key_rotation_days: 90
    
  redis:
    tls_enabled: true
    tls_cert: /etc/redis/certs/redis.crt
    tls_key: /etc/redis/certs/redis.key
    
  sqlite:
    encryption: "sqlcipher"
    key: ${SQLITE_ENCRYPTION_KEY}
```

### Encryption in Transit

```python
import aiohttp
import ssl

class SecureClient:
    def __init__(self):
        # Create SSL context
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = True
        self.ssl_context.verify_mode = ssl.CERT_REQUIRED
        
        # Load certificates
        self.ssl_context.load_cert_chain(
            certfile="client.crt",
            keyfile="client.key"
        )
        
    async def make_request(self, url: str, data: dict):
        """Make secure HTTPS request"""
        connector = aiohttp.TCPConnector(ssl=self.ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(url, json=data) as response:
                return await response.json()
```

### Secrets Management

```yaml
# Never store secrets in configuration files
# Use environment variables or secret management systems

secrets:
  provider: "vault"  # or "aws_secrets_manager", "azure_keyvault"
  vault:
    url: ${VAULT_URL}
    token: ${VAULT_TOKEN}
    path: "secret/gleitzeit"
    
  # Reference secrets
  api_key: "vault://secret/gleitzeit/api_key"
  jwt_secret: "vault://secret/gleitzeit/jwt_secret"
```

#### Using HashiCorp Vault
```python
import hvac

class VaultSecretManager:
    def __init__(self, url: str, token: str):
        self.client = hvac.Client(url=url, token=token)
    
    def get_secret(self, path: str) -> str:
        """Retrieve secret from Vault"""
        response = self.client.secrets.kv.v2.read_secret_version(
            path=path
        )
        return response['data']['data']['value']
    
    def rotate_secret(self, path: str, new_value: str):
        """Rotate a secret"""
        self.client.secrets.kv.v2.create_or_update_secret(
            path=path,
            secret={'value': new_value}
        )
```

## Audit Logging

### Configuration

```yaml
security:
  audit:
    enabled: true
    log_file: /var/log/gleitzeit/audit.log
    events:
      - authentication
      - authorization
      - workflow_submission
      - resource_access
      - configuration_change
      - security_violation
    
    format: json  # Structured logging
    retention_days: 90
    
    # Send to SIEM
    siem:
      enabled: true
      type: "splunk"  # or "elasticsearch", "datadog"
      endpoint: ${SIEM_ENDPOINT}
      token: ${SIEM_TOKEN}
```

### Audit Event Structure

```json
{
  "timestamp": "2024-01-15T10:30:45Z",
  "event_type": "workflow_submission",
  "user_id": "user123",
  "ip_address": "192.168.1.100",
  "action": "submit_workflow",
  "resource": "workflow/wf-abc123",
  "result": "success",
  "metadata": {
    "workflow_name": "Data Processing",
    "task_count": 5
  }
}
```

## Security Scanning

### Dependency Scanning

```bash
# Python dependencies
pip-audit

# Node dependencies
npm audit

# Container scanning
trivy fs .
```

### Static Code Analysis

```bash
# Security linting
bandit -r src/

# General linting with security checks
pylint --enable=security src/
```

### Runtime Security Monitoring

```python
class SecurityMonitor:
    """Runtime security monitoring"""
    
    def __init__(self):
        self.alerts = []
        self.thresholds = {
            'failed_auth_attempts': 5,
            'rate_limit_violations': 10,
            'resource_limit_exceeded': 3
        }
    
    async def monitor(self):
        """Monitor security events"""
        while True:
            metrics = await self.collect_metrics()
            
            # Check for anomalies
            if metrics['failed_auth'] > self.thresholds['failed_auth_attempts']:
                await self.alert("Multiple failed authentication attempts")
            
            if metrics['rate_violations'] > self.thresholds['rate_limit_violations']:
                await self.alert("Excessive rate limit violations")
            
            await asyncio.sleep(60)  # Check every minute
```

## Production Security Checklist

### Pre-Deployment

- [ ] Enable authentication (API key or JWT)
- [ ] Configure TLS/SSL certificates
- [ ] Set up network isolation
- [ ] Configure resource limits
- [ ] Enable audit logging
- [ ] Scan dependencies for vulnerabilities
- [ ] Review and sanitize all inputs
- [ ] Configure secrets management
- [ ] Set up rate limiting
- [ ] Enable encryption at rest

### Runtime Security

- [ ] Monitor authentication failures
- [ ] Track rate limit violations
- [ ] Review audit logs regularly
- [ ] Monitor resource usage
- [ ] Check for abnormal patterns
- [ ] Update dependencies regularly
- [ ] Rotate secrets periodically
- [ ] Review container images
- [ ] Test disaster recovery
- [ ] Conduct security audits

### Incident Response

```yaml
incident_response:
  detection:
    - Security monitoring alerts
    - Audit log analysis
    - User reports
    
  containment:
    - Disable affected accounts
    - Block suspicious IPs
    - Isolate affected resources
    
  investigation:
    - Review audit logs
    - Analyze system metrics
    - Check configuration changes
    
  recovery:
    - Restore from backups
    - Rotate compromised credentials
    - Patch vulnerabilities
    
  lessons_learned:
    - Document incident
    - Update security policies
    - Improve monitoring
```

## Security Best Practices

### 1. Principle of Least Privilege
```yaml
# Grant minimum necessary permissions
roles:
  workflow_executor:
    permissions:
      - workflow:submit
      - workflow:status
    # NOT workflow:* or system:*
```

### 2. Defense in Depth
- Multiple authentication layers
- Network segmentation
- Container isolation
- Input validation
- Audit logging

### 3. Secure Defaults
```python
# Secure by default configuration
DEFAULT_CONFIG = {
    'security': {
        'api_key_required': True,
        'tls_enabled': True,
        'container_network': 'none',
        'audit_enabled': True
    }
}
```

### 4. Regular Updates
```bash
# Automated security updates
#!/bin/bash
pip list --outdated | grep -E 'security|crypto' | awk '{print $1}' | xargs pip install -U
docker images | awk '{print $1":"$2}' | xargs -I {} docker pull {}
```

### 5. Security Training
- Regular security awareness training
- Code review for security issues
- Penetration testing
- Security documentation

## Compliance

### GDPR Compliance
- Data encryption
- Audit logging
- Right to erasure
- Data portability

### HIPAA Compliance
- Encryption at rest and in transit
- Access controls
- Audit logs
- Business Associate Agreements

### SOC 2 Requirements
- Security policies
- Access controls
- Monitoring
- Incident response

## Summary

Gleitzeit v0.0.5 provides comprehensive security features:
- **Authentication & Authorization**: API keys, JWT, RBAC
- **Container Security**: Isolated execution, resource limits
- **Network Security**: TLS/SSL, network isolation, rate limiting
- **Data Security**: Encryption, secrets management
- **Audit & Monitoring**: Comprehensive logging, security monitoring
- **Compliance**: GDPR, HIPAA, SOC 2 ready

Always follow security best practices and regularly review and update security configurations for production deployments.