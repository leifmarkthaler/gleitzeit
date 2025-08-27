"""
Gleitzeit API Client

Python client for interacting with the Gleitzeit REST API.
"""

import asyncio
import json
from typing import Dict, Any, List, Optional
from pathlib import Path

import aiohttp
from pydantic import BaseModel


class GleitzeitAPIClient:
    """Async client for Gleitzeit REST API"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request to API"""
        if not self.session:
            raise RuntimeError("Client session not initialized. Use 'async with' context manager.")
        
        url = f"{self.base_url}{endpoint}"
        async with self.session.request(method, url, **kwargs) as response:
            if response.status >= 400:
                error_text = await response.text()
                raise Exception(f"API error ({response.status}): {error_text}")
            return await response.json()
    
    # System endpoints
    
    async def get_status(self) -> Dict[str, Any]:
        """Get system status"""
        return await self._request("GET", "/status")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check API health"""
        return await self._request("GET", "/health")
    
    async def list_providers(self) -> List[Dict[str, Any]]:
        """List all registered providers"""
        result = await self._request("GET", "/providers")
        return result["providers"]
    
    async def list_protocols(self) -> List[str]:
        """List all registered protocols"""
        result = await self._request("GET", "/protocols")
        return result["protocols"]
    
    # Workflow endpoints
    
    async def submit_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a workflow for execution"""
        return await self._request("POST", "/workflows", json=workflow)
    
    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status"""
        return await self._request("GET", f"/workflows/{workflow_id}")
    
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel a running workflow"""
        return await self._request("DELETE", f"/workflows/{workflow_id}")
    
    async def upload_workflow_file(self, file_path: str, execute: bool = True) -> Dict[str, Any]:
        """Upload and optionally execute a workflow file"""
        with open(file_path, 'rb') as f:
            data = aiohttp.FormData()
            data.add_field('file', f, filename=Path(file_path).name)
            return await self._request(
                "POST", 
                f"/workflows/upload?execute={str(execute).lower()}",
                data=data
            )
    
    # Task endpoints
    
    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single task"""
        return await self._request("POST", "/tasks", json=task)
    
    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Get task status"""
        return await self._request("GET", f"/tasks/{task_id}")
    
    # Convenience endpoints
    
    async def execute_python(self, code: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute Python code directly"""
        return await self._request("POST", "/execute/python", json={
            "code": code,
            "timeout": timeout
        })
    
    async def chat(self, message: str, model: str = "llama3.2:latest", 
                   temperature: float = 0.7, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Chat with LLM"""
        return await self._request("POST", "/chat", json={
            "message": message,
            "model": model,
            "temperature": temperature,
            "session_id": session_id
        })
    
    async def batch_process(self, directory: str, pattern: str = "*", 
                           prompt: str = "Analyze this file",
                           model: str = "llama3.2:latest",
                           max_concurrent: int = 5) -> Dict[str, Any]:
        """Process files in batch"""
        return await self._request("POST", "/batch", json={
            "directory": directory,
            "pattern": pattern,
            "prompt": prompt,
            "model": model,
            "max_concurrent": max_concurrent
        })
    
    # Template endpoints
    
    async def execute_template(self, template_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a workflow template"""
        return await self._request("POST", f"/templates/{template_type}", json=params)
    
    async def research(self, topic: str, depth: str = "medium", max_steps: int = 5) -> Dict[str, Any]:
        """Execute research template"""
        return await self.execute_template("research", {
            "topic": topic,
            "depth": depth,
            "max_steps": max_steps
        })
    
    async def generate_code(self, task: str, language: str = "python") -> Dict[str, Any]:
        """Execute code generation template"""
        return await self.execute_template("code", {
            "task": task,
            "language": language
        })
    
    async def analyze(self, content: str, question: Optional[str] = None) -> Dict[str, Any]:
        """Execute analysis template"""
        params = {"content": content}
        if question:
            params["question"] = question
        return await self.execute_template("analyze", params)
    
    # Authentication endpoints
    
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login with username/email and password"""
        return await self._request("POST", "/auth/login", json={
            "username": username,
            "password": password
        })
    
    async def logout(self) -> Dict[str, Any]:
        """Logout current user"""
        return await self._request("POST", "/auth/logout")
    
    async def get_current_user(self) -> Dict[str, Any]:
        """Get current user information"""
        return await self._request("GET", "/auth/me")
    
    async def register(self, email: str, password: str, username: str = None, full_name: str = None) -> Dict[str, Any]:
        """Register a new user"""
        user_data = {
            "email": email,
            "password": password,
            "username": username,
            "full_name": full_name
        }
        return await self._request("POST", "/auth/register", json=user_data)
    
    async def change_password(self, old_password: str, new_password: str) -> Dict[str, Any]:
        """Change password for current user"""
        return await self._request("POST", "/auth/change-password", json={
            "old_password": old_password,
            "new_password": new_password
        })
    
    # User management endpoints (admin only)
    
    async def create_user(self, email: str, password: str, username: str = None, 
                         full_name: str = None, roles: List[str] = None) -> Dict[str, Any]:
        """Create a new user (admin only)"""
        user_data = {
            "email": email,
            "password": password,
            "username": username,
            "full_name": full_name,
            "roles": roles
        }
        return await self._request("POST", "/auth/users", json=user_data)
    
    async def get_user(self, user_id: str) -> Dict[str, Any]:
        """Get user by ID"""
        return await self._request("GET", f"/auth/users/{user_id}")
    
    async def list_users(self, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
        """List all users"""
        return await self._request("GET", f"/auth/users?skip={skip}&limit={limit}")
    
    async def update_user(self, user_id: str, **updates) -> Dict[str, Any]:
        """Update user by ID"""
        return await self._request("PUT", f"/auth/users/{user_id}", json=updates)
    
    async def delete_user(self, user_id: str) -> Dict[str, Any]:
        """Delete user by ID"""
        return await self._request("DELETE", f"/auth/users/{user_id}")
    
    async def assign_user_role(self, user_id: str, role: str) -> Dict[str, Any]:
        """Assign role to user"""
        return await self._request("POST", f"/auth/users/{user_id}/roles", json={"role": role})
    
    async def remove_user_role(self, user_id: str, role_name: str) -> Dict[str, Any]:
        """Remove role from user"""
        return await self._request("DELETE", f"/auth/users/{user_id}/roles/{role_name}")
    
    # API key management
    
    async def create_api_key(self, name: str, description: str = None, 
                           expires_in_days: int = None) -> Dict[str, Any]:
        """Create an API key"""
        key_data = {
            "name": name,
            "description": description,
            "expires_in_days": expires_in_days
        }
        return await self._request("POST", "/auth/api-keys", json=key_data)
    
    async def list_api_keys(self) -> List[Dict[str, Any]]:
        """List API keys for current user"""
        return await self._request("GET", "/auth/api-keys")
    
    async def revoke_api_key(self, key_id: str) -> Dict[str, Any]:
        """Revoke an API key"""
        return await self._request("DELETE", f"/auth/api-keys/{key_id}")
    
    # Role management
    
    async def list_roles(self) -> List[Dict[str, Any]]:
        """List all available roles"""
        return await self._request("GET", "/auth/roles")
    
    # Audit logs
    
    async def get_audit_logs(self, user_id: str = None, action: str = None, 
                           resource_type: str = None, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
        """Get audit logs"""
        params = {"skip": skip, "limit": limit}
        if user_id:
            params["user_id"] = user_id
        if action:
            params["action"] = action
        if resource_type:
            params["resource_type"] = resource_type
        
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return await self._request("GET", f"/auth/audit-logs?{query_string}")
    
    # Auth status
    
    async def get_auth_status(self) -> Dict[str, Any]:
        """Get authentication status and mode"""
        return await self._request("GET", "/auth/status")


# Synchronous wrapper for convenience
class GleitzeitAPIClientSync:
    """Synchronous wrapper for the API client"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.async_client = GleitzeitAPIClient(base_url)
    
    def _run_async(self, coro):
        """Run async coroutine synchronously"""
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running (e.g., in Jupyter), create new task
            import nest_asyncio
            nest_asyncio.apply()
        return loop.run_until_complete(coro)
    
    def get_status(self) -> Dict[str, Any]:
        async def _get():
            async with self.async_client as client:
                return await client.get_status()
        return self._run_async(_get())
    
    def submit_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        async def _submit():
            async with self.async_client as client:
                return await client.submit_workflow(workflow)
        return self._run_async(_submit())
    
    def execute_python(self, code: str, timeout: int = 30) -> Dict[str, Any]:
        async def _exec():
            async with self.async_client as client:
                return await client.execute_python(code, timeout)
        return self._run_async(_exec())
    
    def chat(self, message: str, model: str = "llama3.2:latest") -> Dict[str, Any]:
        async def _chat():
            async with self.async_client as client:
                return await client.chat(message, model)
        return self._run_async(_chat())
    
    def research(self, topic: str, depth: str = "medium") -> Dict[str, Any]:
        async def _research():
            async with self.async_client as client:
                return await client.research(topic, depth)
        return self._run_async(_research())
    
    # Auth methods for sync client
    
    def login(self, username: str, password: str) -> Dict[str, Any]:
        async def _login():
            async with self.async_client as client:
                return await client.login(username, password)
        return self._run_async(_login())
    
    def logout(self) -> Dict[str, Any]:
        async def _logout():
            async with self.async_client as client:
                return await client.logout()
        return self._run_async(_logout())
    
    def get_current_user(self) -> Dict[str, Any]:
        async def _get_user():
            async with self.async_client as client:
                return await client.get_current_user()
        return self._run_async(_get_user())
    
    def create_user(self, email: str, password: str, username: str = None, 
                   full_name: str = None, roles: List[str] = None) -> Dict[str, Any]:
        async def _create():
            async with self.async_client as client:
                return await client.create_user(email, password, username, full_name, roles)
        return self._run_async(_create())
    
    def list_users(self, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
        async def _list():
            async with self.async_client as client:
                return await client.list_users(skip, limit)
        return self._run_async(_list())
    
    def create_api_key(self, name: str, description: str = None, expires_in_days: int = None) -> Dict[str, Any]:
        async def _create_key():
            async with self.async_client as client:
                return await client.create_api_key(name, description, expires_in_days)
        return self._run_async(_create_key())
    
    def get_auth_status(self) -> Dict[str, Any]:
        async def _get_status():
            async with self.async_client as client:
                return await client.get_auth_status()
        return self._run_async(_get_status())


# Example usage
if __name__ == "__main__":
    async def main():
        # Example async usage
        async with GleitzeitAPIClient() as client:
            # Check system status
            status = await client.get_status()
            print(f"System status: {status['status']}")
            
            # Check authentication status
            auth_status = await client.get_auth_status()
            print(f"Auth mode: {auth_status['mode']}")
            print(f"Login required: {auth_status['requires_login']}")
            
            # Get current user (works in both basic and admin mode)
            try:
                user = await client.get_current_user()
                print(f"Current user: {user['email']}")
                
                # Demo admin operations (will fail in basic mode)
                if auth_status['mode'] == 'admin':
                    print("\\n--- Admin Operations ---")
                    
                    # List users
                    users_response = await client.list_users(limit=3)
                    print(f"Users: {len(users_response.get('users', []))}")
                    
                    # List roles
                    roles = await client.list_roles()
                    print(f"Available roles: {[r.get('name', r) for r in roles]}")
                    
                    # Create API key (store the result securely!)
                    api_key = await client.create_api_key(
                        name="Demo Key",
                        description="Example API key",
                        expires_in_days=30
                    )
                    print(f"Created API key: {api_key['key_prefix']}...")
                    
                    # Clean up - revoke the demo key
                    await client.revoke_api_key(api_key['id'])
                    print("Revoked demo API key")
                    
                else:
                    print("\\n--- Basic Mode (Limited Operations) ---")
                    print("Admin operations not available in basic mode")
                    
            except Exception as e:
                print(f"Auth operations failed: {e}")
            
            # Execute Python code
            result = await client.execute_python("print('Hello from API!'); result = 2 + 2")
            print(f"\\nPython result: {result}")
            
            # Chat with LLM
            chat_result = await client.chat("What is workflow orchestration?")
            print(f"Chat response: {chat_result.get('response', 'No response')[:200]}...")
            
            # Submit a workflow
            workflow = {
                "name": "Test Workflow",
                "description": "API test workflow",
                "tasks": [
                    {
                        "name": "Calculate",
                        "protocol": "python/v1", 
                        "method": "python/execute",
                        "params": {
                            "code": "result = 10 * 20"
                        }
                    }
                ]
            }
            workflow_result = await client.submit_workflow(workflow)
            print(f"\\nWorkflow submitted: {workflow_result['workflow_id']}")
    
    # Example sync usage
    def sync_example():
        from gleitzeit.api.client import GleitzeitAPIClientSync
        
        print("\\n=== Sync Client Example ===")
        client = GleitzeitAPIClientSync()
        
        # Check auth status
        auth_status = client.get_auth_status()
        print(f"Auth mode (sync): {auth_status['mode']}")
        
        # Get current user
        user = client.get_current_user()
        print(f"Current user (sync): {user['email']}")
        
        # Execute Python
        result = client.execute_python("result = 5 * 5")
        print(f"Python result (sync): {result}")
    
    # Run examples
    print("=== Async Client Example ===")
    asyncio.run(main())
    sync_example()