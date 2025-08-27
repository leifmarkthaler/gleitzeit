"""
API adapter for Gleitzeit client.
"""

import aiohttp
import asyncio
import time
import json
from typing import Any, Dict, List, Optional
from gleitzeit.core.models import Task, Workflow, TaskResult
from .base import BaseAdapter


class APIAdapter(BaseAdapter):
    """Adapter for API mode operations."""
    
    def __init__(self, host: str = "localhost", port: int = 8000):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.session: Optional[aiohttp.ClientSession] = None
        self.auth_token: Optional[str] = None
    
    async def initialize(self) -> None:
        """Initialize the API adapter."""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def shutdown(self) -> None:
        """Shutdown the adapter and cleanup."""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def _request(self, method: str, endpoint: str, 
                      json_data: Dict = None, params: Dict = None) -> Any:
        """Make HTTP request to API."""
        if not self.session:
            await self.initialize()
        
        headers = {}
        if self.auth_token:
            headers['Authorization'] = f'Bearer {self.auth_token}'
        
        url = f"{self.base_url}{endpoint}"
        
        async with self.session.request(
            method, url, json=json_data, params=params, headers=headers
        ) as response:
            if response.status >= 400:
                text = await response.text()
                raise Exception(f"API error {response.status}: {text}")
            
            if response.content_type == 'application/json':
                return await response.json()
            return await response.text()
    
    # Workflow operations
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        """Submit a workflow via API."""
        workflow_dict = workflow.dict() if hasattr(workflow, 'dict') else workflow
        return await self._request('POST', '/workflows', json_data=workflow_dict)
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow via API."""
        try:
            data = await self._request('GET', f'/workflows/{workflow_id}')
            return Workflow(**data) if data else None
        except Exception:
            return None
    
    async def list_workflows(self, status: Optional[str] = None,
                           limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List workflows via API."""
        params = {'limit': limit, 'offset': offset}
        if status:
            params['status'] = status
        return await self._request('GET', '/workflows', params=params)
    
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel workflow via API."""
        return await self._request('POST', f'/workflows/{workflow_id}/cancel')
    
    async def pause_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Pause workflow via API."""
        return await self._request('POST', f'/workflows/{workflow_id}/pause')
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Resume workflow via API."""
        return await self._request('POST', f'/workflows/{workflow_id}/resume')
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete workflow via API."""
        try:
            await self._request('DELETE', f'/workflows/{workflow_id}')
            return True
        except Exception:
            return False
    
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """Get workflow tasks via API."""
        data = await self._request('GET', f'/workflows/{workflow_id}/tasks')
        tasks = data.get('tasks', [])
        return [Task(**t) for t in tasks]
    
    # Task operations
    async def submit_task(self, task: Task) -> Dict[str, Any]:
        """Submit task via API."""
        task_dict = task.dict() if hasattr(task, 'dict') else task
        return await self._request('POST', '/tasks', json_data=task_dict)
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task via API."""
        try:
            data = await self._request('GET', f'/tasks/{task_id}')
            return Task(**data) if data else None
        except Exception:
            return None
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result via API."""
        try:
            data = await self._request('GET', f'/tasks/{task_id}/result')
            return TaskResult(**data) if data else None
        except Exception:
            return None
    
    async def list_tasks(self, status: Optional[str] = None,
                        workflow_id: Optional[str] = None,
                        limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List tasks via API."""
        params = {'limit': limit, 'offset': offset}
        if status:
            params['status'] = status
        if workflow_id:
            params['workflow_id'] = workflow_id
        return await self._request('GET', '/tasks', params=params)
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel task via API."""
        try:
            await self._request('POST', f'/tasks/{task_id}/cancel')
            return True
        except Exception:
            return False
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete task via API."""
        try:
            await self._request('DELETE', f'/tasks/{task_id}')
            return True
        except Exception:
            return False
    
    async def wait_for_task(self, task_id: str, timeout: float = 300.0,
                           poll_interval: float = 1.0) -> Optional[TaskResult]:
        """Wait for task completion via API."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            task = await self.get_task(task_id)
            if task and task.status in ['completed', 'failed', 'cancelled']:
                return await self.get_task_result(task_id)
            
            await asyncio.sleep(poll_interval)
        
        return None
    
    # Queue operations
    async def get_queues(self) -> Dict[str, Any]:
        """Get queues via API."""
        return await self._request('GET', '/queues')
    
    async def get_queue_details(self, queue_name: str) -> Dict[str, Any]:
        """Get queue details via API."""
        return await self._request('GET', f'/queues/{queue_name}')
    
    async def pause_queue(self, queue_name: str) -> Dict[str, Any]:
        """Pause queue via API."""
        return await self._request('POST', f'/queues/{queue_name}/pause')
    
    async def resume_queue(self, queue_name: str) -> Dict[str, Any]:
        """Resume queue via API."""
        return await self._request('POST', f'/queues/{queue_name}/resume')
    
    async def clear_queue(self, queue_name: str) -> Dict[str, Any]:
        """Clear queue via API."""
        return await self._request('POST', f'/queues/{queue_name}/clear')
    
    # Batch operations
    async def batch_process(self, directory: str, pattern: str = "*",
                           method: str = "llm/chat", prompt: str = None,
                           model: str = "llama3.2:latest",
                           max_concurrent: int = 5,
                           name: Optional[str] = None) -> Dict[str, Any]:
        """Batch process via API."""
        data = {
            'directory': directory,
            'pattern': pattern,
            'method': method,
            'prompt': prompt,
            'model': model,
            'max_concurrent': max_concurrent
        }
        if name:
            data['name'] = name
        
        return await self._request('POST', '/batch', json_data=data)
    
    async def process_directory(self, directory: str, file_extensions: List[str],
                               workflow_yaml: str, max_concurrent: int = 5,
                               recursive: bool = True) -> Dict[str, Any]:
        """Process directory via API."""
        data = {
            'directory': directory,
            'file_extensions': file_extensions,
            'workflow_yaml': workflow_yaml,
            'max_concurrent': max_concurrent,
            'recursive': recursive
        }
        
        return await self._request('POST', '/bulk/directory', json_data=data)
    
    # Chat operations
    async def chat(self, message: str, model: str = "llama3.2:latest",
                  temperature: float = 0.7,
                  session_id: Optional[str] = None) -> Dict[str, Any]:
        """Chat via API."""
        data = {
            'message': message,
            'model': model,
            'temperature': temperature
        }
        if session_id:
            data['session_id'] = session_id
        
        return await self._request('POST', '/chat', json_data=data)
    
    # System operations
    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status via API."""
        return await self._request('GET', '/status')
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check via API."""
        return await self._request('GET', '/')
    
    async def get_providers(self) -> List[Dict[str, Any]]:
        """Get providers via API."""
        data = await self._request('GET', '/providers')
        return data if isinstance(data, list) else data.get('providers', [])
    
    async def get_protocols(self) -> List[Dict[str, Any]]:
        """Get protocols via API."""
        data = await self._request('GET', '/protocols')
        return data if isinstance(data, list) else data.get('protocols', [])
    
    # Auth operations
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login via API."""
        data = {'username': username, 'password': password}
        result = await self._request('POST', '/auth/login', json_data=data)
        
        # Store token if provided
        if 'access_token' in result:
            self.auth_token = result['access_token']
        
        return result
    
    async def logout(self) -> Dict[str, Any]:
        """Logout via API."""
        result = await self._request('POST', '/auth/logout')
        self.auth_token = None
        return result
    
    async def get_current_user(self) -> Dict[str, Any]:
        """Get current user via API."""
        return await self._request('GET', '/auth/me')