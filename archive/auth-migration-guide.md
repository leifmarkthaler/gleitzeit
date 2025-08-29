# Authentication Migration Guide

**Status: PARTIALLY IMPLEMENTED** - Dual-mode authentication system is complete. Basic mode (no login) and Admin mode (multi-user) are fully functional. This guide shows the implementation approach used.

## Quick Start Examples

### Example 1: Protecting API Endpoints (main.py changes)

```python
# src/gleitzeit/api/main.py

# Add import at the top
from ..auth.decorators import (
    optional_permission, 
    optional_role,
    check_resource_ownership,
    filter_by_ownership
)

# Update endpoints with decorators

@app.post("/workflows", response_model=WorkflowResponse)
@optional_permission("workflows:create")
async def submit_workflow(request: Request, workflow: WorkflowRequest):
    """Submit a new workflow for execution"""
    
    # Add owner info if auth is enabled
    if hasattr(request.state, 'user') and request.state.user:
        workflow_dict = workflow.dict()
        workflow_dict['owner_id'] = request.state.user.get("id")
        workflow_dict['owner_email'] = request.state.user.get("email")
    else:
        workflow_dict = workflow.dict()
    
    # Rest of existing code...
    result = await workflow_manager.submit_workflow(workflow_dict)
    return WorkflowResponse(**result)


@app.get("/workflows")
@optional_permission("workflows:read")
@filter_by_ownership()
async def list_workflows(
    request: Request,
    status: Optional[str] = None,
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0)
):
    """List all workflows (filtered by ownership if auth enabled)"""
    
    # Existing code to get workflows
    workflows = await persistence.list_workflows(
        status=status,
        limit=limit,
        offset=offset
    )
    
    # The @filter_by_ownership decorator will automatically filter results
    return workflows


# For delete operations, check ownership
async def get_task_for_ownership(task_id: str):
    """Helper function to get task for ownership check"""
    return await persistence.get_task(task_id)

@app.delete("/tasks/{task_id}")
@optional_permission("tasks:delete")
@check_resource_ownership(get_task_for_ownership)
async def delete_task(request: Request, task_id: str):
    """Delete a task (only owner or admin can delete)"""
    
    # Existing deletion code
    await persistence.delete_task(task_id)
    return {"message": f"Task {task_id} deleted"}


# Admin-only endpoints
@app.delete("/system/cleanup")
@optional_role("admin")
async def system_cleanup(request: Request):
    """Clean up old data (admin only)"""
    # Cleanup logic
    return {"message": "System cleanup completed"}
```

### Example 2: First-Time Setup Script

```python
# src/gleitzeit/cli/setup.py

import click
import os
from pathlib import Path
import yaml

@click.command()
def setup_auth():
    """Interactive authentication setup"""
    
    click.echo("🔐 Gleitzeit Authentication Setup")
    click.echo("=" * 40)
    
    # Check if already configured
    config_file = Path.home() / ".gleitzeit" / "config.yaml"
    if config_file.exists():
        if not click.confirm("Configuration exists. Overwrite?", default=False):
            return
    
    config = {}
    
    # Basic auth setup
    if click.confirm("Enable authentication?", default=False):
        config['auth_enabled'] = True
        
        # Admin user setup
        click.echo("\n👤 Admin User Setup")
        config['admin_email'] = click.prompt("Admin email", default="admin@localhost")
        admin_password = click.prompt("Admin password", hide_input=True, 
                                     confirmation_prompt=True)
        
        # Feature selection
        click.echo("\n⚙️  Feature Configuration")
        config['features'] = {
            'api_keys': click.confirm("Enable API keys?", default=True),
            'jwt': click.confirm("Enable JWT tokens?", default=True),
            'rate_limiting': click.confirm("Enable rate limiting?", default=False),
            'audit_log': click.confirm("Enable audit logging?", default=False),
            'user_registration': click.confirm("Allow user self-registration?", default=False)
        }
        
        # Persistence selection
        click.echo("\n💾 Storage Configuration")
        storage_choices = {
            '1': 'memory',
            '2': 'sqlite',
            '3': 'postgresql',
            '4': 'redis'
        }
        
        click.echo("Choose storage backend:")
        for key, value in storage_choices.items():
            click.echo(f"  {key}. {value}")
        
        choice = click.prompt("Selection", type=click.Choice(storage_choices.keys()), 
                             default='1')
        config['persistence_type'] = storage_choices[choice]
        
        # Generate secure JWT secret
        import secrets
        config['jwt_secret'] = secrets.token_urlsafe(32)
        
        # Save configuration
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write config file
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
        
        # Write environment file
        env_file = config_file.parent / ".env"
        with open(env_file, 'w') as f:
            f.write(f"GLEITZEIT_AUTH_ENABLED=true\n")
            f.write(f"GLEITZEIT_AUTH_ADMIN_EMAIL={config['admin_email']}\n")
            f.write(f"GLEITZEIT_AUTH_ADMIN_PASSWORD={admin_password}\n")
            f.write(f"GLEITZEIT_AUTH_JWT_SECRET={config['jwt_secret']}\n")
            f.write(f"GLEITZEIT_PERSISTENCE_TYPE={config['persistence_type']}\n")
            
            for feature, enabled in config['features'].items():
                env_key = f"GLEITZEIT_AUTH_{feature.upper()}"
                f.write(f"{env_key}={str(enabled).lower()}\n")
        
        click.echo("\n✅ Authentication configured successfully!")
        click.echo(f"📁 Configuration saved to: {config_file}")
        click.echo(f"🔑 Environment file created: {env_file}")
        click.echo("\nTo start with authentication:")
        click.echo("  gleitzeit serve")
        
    else:
        # No auth configuration
        config['auth_enabled'] = False
        
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
        
        click.echo("\n⚠️  Authentication disabled")
        click.echo("You can enable it later by running: gleitzeit setup-auth")

if __name__ == "__main__":
    setup_auth()
```

### Example 3: Migration Script for Existing Data

```python
# src/gleitzeit/auth/migrate.py

import asyncio
import logging
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)

async def migrate_to_auth(admin_email: str = "admin@localhost"):
    """
    Migrate existing Gleitzeit data to include authentication ownership.
    
    Args:
        admin_email: Email of the admin user to assign ownership to
    """
    from ..persistence.factory import get_persistence_backend
    from .database import get_auth_db
    
    logger.info("Starting authentication migration...")
    
    # Get backends
    persistence = get_persistence_backend()
    auth_db = get_auth_db()
    
    # Get or create admin user
    admin = await auth_db.get_user_by_email(admin_email)
    if not admin:
        logger.error(f"Admin user {admin_email} not found. Run setup first.")
        return False
    
    admin_id = str(admin.id)
    
    # Migrate workflows
    logger.info("Migrating workflows...")
    workflows = await persistence.list_workflows()
    migrated_workflows = 0
    
    for workflow in workflows:
        if not workflow.get('owner_id'):
            workflow['owner_id'] = admin_id
            workflow['owner_email'] = admin_email
            await persistence.update_workflow(workflow['workflow_id'], workflow)
            migrated_workflows += 1
    
    logger.info(f"Migrated {migrated_workflows} workflows")
    
    # Migrate tasks
    logger.info("Migrating tasks...")
    tasks = await persistence.list_tasks()
    migrated_tasks = 0
    
    for task in tasks:
        if not task.get('owner_id'):
            task['owner_id'] = admin_id
            task['owner_email'] = admin_email
            await persistence.update_task(task['task_id'], task)
            migrated_tasks += 1
    
    logger.info(f"Migrated {migrated_tasks} tasks")
    
    # Create audit log entry
    await auth_db.create_audit_log(
        user_id=admin_id,
        action="migration",
        resource_type="system",
        details={
            "migrated_workflows": migrated_workflows,
            "migrated_tasks": migrated_tasks
        }
    )
    
    logger.info("Migration completed successfully!")
    return True

# CLI command
@click.command()
@click.option('--admin-email', default='admin@localhost', 
              help='Email of admin user to assign ownership')
def migrate(admin_email: str):
    """Migrate existing data for authentication"""
    
    # Check if auth is enabled
    if os.getenv("GLEITZEIT_AUTH_ENABLED", "false").lower() != "true":
        click.echo("⚠️  Authentication is not enabled. Enable it first:")
        click.echo("  export GLEITZEIT_AUTH_ENABLED=true")
        return
    
    click.echo("🔄 Starting authentication migration...")
    click.echo(f"📧 Assigning ownership to: {admin_email}")
    
    if not click.confirm("This will modify all existing workflows and tasks. Continue?"):
        return
    
    # Run migration
    success = asyncio.run(migrate_to_auth(admin_email))
    
    if success:
        click.echo("✅ Migration completed successfully!")
    else:
        click.echo("❌ Migration failed. Check logs for details.")
```

## Step-by-Step Implementation Guide

### Step 1: Install the Updated Package

```bash
# For development
pip install -e .

# For production
pip install gleitzeit
```

### Step 2: Run Without Auth (Default)

```bash
# Works immediately, no configuration needed
gleitzeit serve
# API is fully accessible at http://localhost:8000
```

### Step 3: Enable Basic Authentication

```bash
# Option 1: Interactive setup
gleitzeit setup-auth

# Option 2: Environment variables
export GLEITZEIT_AUTH_ENABLED=true
export GLEITZEIT_AUTH_ADMIN_EMAIL=admin@example.com
export GLEITZEIT_AUTH_ADMIN_PASSWORD=secure-password-here
gleitzeit serve
```

### Step 4: Test Authentication

```python
# test_auth.py
import requests

# Without auth (will fail if auth is enabled)
response = requests.get("http://localhost:8000/workflows")
print(f"Without auth: {response.status_code}")

# Login to get token
login_response = requests.post(
    "http://localhost:8000/auth/login",
    json={"username": "admin@example.com", "password": "secure-password-here"}
)
token = login_response.json()["access_token"]

# With auth token
response = requests.get(
    "http://localhost:8000/workflows",
    headers={"Authorization": f"Bearer {token}"}
)
print(f"With auth: {response.status_code}")

# Create API key for programmatic access
api_key_response = requests.post(
    "http://localhost:8000/auth/api-keys",
    json={"name": "CI/CD Pipeline", "description": "Automated deployments"},
    headers={"Authorization": f"Bearer {token}"}
)
api_key = api_key_response.json()["key"]
print(f"API Key: {api_key}")

# Use API key
response = requests.get(
    "http://localhost:8000/workflows",
    headers={"X-API-Key": api_key}
)
print(f"With API key: {response.status_code}")
```

### Step 5: Migrate Existing Data

```bash
# If you have existing workflows/tasks
gleitzeit auth migrate --admin-email admin@example.com
```

### Step 6: Add Users with Different Roles

```python
# admin_tasks.py
import requests

# Login as admin
token = get_admin_token()

# Create a developer user
response = requests.post(
    "http://localhost:8000/auth/register",
    json={
        "email": "dev@example.com",
        "password": "dev-password",
        "full_name": "Developer User"
    },
    headers={"Authorization": f"Bearer {token}"}
)

# Assign developer role (would need an endpoint for this)
# This is a gap that needs to be implemented
```

## Configuration Reference

### Minimal Configuration (No Auth)
```yaml
# ~/.gleitzeit/config.yaml
auth_enabled: false
```

### Basic Authentication
```yaml
# ~/.gleitzeit/config.yaml
auth_enabled: true
admin_email: admin@localhost
persistence_type: memory  # or sqlite, postgresql, redis
```

### Full Authentication with Features
```yaml
# ~/.gleitzeit/config.yaml
auth_enabled: true
admin_email: admin@example.com
persistence_type: postgresql
database_url: postgresql://user:pass@localhost/gleitzeit

features:
  api_keys: true
  jwt: true
  sessions: true
  rate_limiting: true
  audit_log: true
  ownership_filtering: true
  user_registration: false

jwt:
  secret: "your-secret-key-here"
  algorithm: HS256
  access_token_expire_minutes: 60
  refresh_token_expire_days: 30

rate_limiting:
  requests_per_minute: 60
  requests_per_hour: 1000
```

## Troubleshooting

### Issue: "Authentication required" errors after enabling auth

**Solution**: Make sure to create admin user first:
```bash
export GLEITZEIT_AUTH_CREATE_ADMIN=true
export GLEITZEIT_AUTH_ADMIN_EMAIL=admin@localhost
export GLEITZEIT_AUTH_ADMIN_PASSWORD=admin
gleitzeit serve
```

### Issue: Existing workflows/tasks not visible

**Solution**: Run migration to assign ownership:
```bash
gleitzeit auth migrate
```

### Issue: Can't create new users

**Solution**: Enable registration or use admin API:
```bash
export GLEITZEIT_AUTH_ALLOW_REGISTRATION=true
```

### Issue: Performance degradation with auth enabled

**Solution**: Use Redis or SQL backend instead of memory:
```bash
export GLEITZEIT_PERSISTENCE_TYPE=redis
export GLEITZEIT_REDIS_URL=redis://localhost:6379
```

## Security Best Practices

1. **Always use HTTPS in production**
   ```bash
   gleitzeit serve --ssl-cert /path/to/cert.pem --ssl-key /path/to/key.pem
   ```

2. **Use strong JWT secrets**
   ```python
   import secrets
   jwt_secret = secrets.token_urlsafe(32)
   ```

3. **Rotate API keys regularly**
   ```bash
   # Implement key rotation policy
   gleitzeit auth rotate-keys --days 90
   ```

4. **Enable audit logging**
   ```bash
   export GLEITZEIT_AUTH_AUDIT_LOG=true
   ```

5. **Implement rate limiting**
   ```bash
   export GLEITZEIT_AUTH_RATE_LIMIT=true
   ```