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


# Example usage
if __name__ == "__main__":
    async def main():
        # Example async usage
        async with GleitzeitAPIClient() as client:
            # Check status
            status = await client.get_status()
            print(f"System status: {status['status']}")
            
            # Execute Python code
            result = await client.execute_python("print('Hello from API!'); result = 2 + 2")
            print(f"Python result: {result}")
            
            # Chat with LLM
            chat_result = await client.chat("What is workflow orchestration?")
            print(f"Chat response: {chat_result['response'][:200]}...")
            
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
            print(f"Workflow submitted: {workflow_result['workflow_id']}")
    
    # Run example
    asyncio.run(main())