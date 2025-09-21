"""
API adapter with WebSocket support for Gleitzeit client.

This adapter provides a thin layer for API communication with event-driven capabilities.
"""

import aiohttp
import asyncio
import time
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from gleitzeit.core.models import Task, Workflow, TaskResult, TaskStatus
from gleitzeit.core.events import EventType
from gleitzeit.core.errors import NetworkError
from .event_driven import EventDrivenAdapter
from ..events import ClientEventBus, ClientEvent

logger = logging.getLogger(__name__)


class APIAdapter(EventDrivenAdapter):
    """
    API adapter with event-driven WebSocket support.
    
    This adapter:
    - Provides HTTP REST API communication
    - Uses WebSocket for real-time events
    - Falls back to polling when WebSocket unavailable
    """
    
    def __init__(self,
                 host: str = "localhost",
                 port: int = 8000,
                 enable_events: bool = True,
                 enable_websocket: bool = True,
                 fallback_to_polling: bool = True,
                 event_bus: Optional[ClientEventBus] = None):
        """
        Initialize API adapter with event support.
        
        Args:
            host: API server hostname
            port: API server port
            enable_events: Enable event-driven features
            enable_websocket: Enable WebSocket for events
            fallback_to_polling: Fall back to polling if WebSocket fails
            event_bus: Optional shared event bus
            
        Note: Authentication is stateless - tokens are passed via headers
        from the backend, not stored in the adapter.
        """
        # Initialize event-driven base
        super().__init__(
            enable_events=enable_events,
            enable_websocket=enable_websocket,
            fallback_to_polling=fallback_to_polling,
            event_bus=event_bus
        )
        
        # API configuration
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        
        # HTTP session with cookie jar for stateless auth
        self.session: Optional[aiohttp.ClientSession] = None
        self.cookie_jar = aiohttp.CookieJar()  # Handles session cookies
        
        # WebSocket URL for events
        protocol = 'wss' if port == 443 else 'ws'
        self.websocket_url = f"{protocol}://{host}:{port}/events/stream"
        
        logger.info(f"APIAdapter configured for {self.base_url}")
        
    async def initialize(self) -> None:
        """Initialize HTTP session and event components."""
        # Create HTTP session with cookie jar for stateless auth
        if not self.session:
            self.session = aiohttp.ClientSession(cookie_jar=self.cookie_jar)
            
        # Initialize event-driven components
        await super().initialize()
        
        logger.info("APIAdapter initialized")
        
    async def shutdown(self) -> None:
        """Shutdown HTTP session and event components."""
        # Shutdown event components
        await super().shutdown()
        
        # Close HTTP session
        if self.session:
            await self.session.close()
            self.session = None
            
        logger.info("APIAdapter shutdown")
        
    async def _request(self, method: str, endpoint: str,
                      json_data: Dict = None, params: Dict = None) -> Any:
        """
        Make HTTP request to API server.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            json_data: JSON request body
            params: Query parameters
            
        Returns:
            Response data
        """
        if not self.session:
            await self.initialize()
            
        url = f"{self.base_url}{endpoint}"
        
        # Session cookies handle auth automatically (stateless)
        async with self.session.request(
            method, url, json=json_data, params=params
        ) as response:
            if response.status >= 400:
                text = await response.text()
                
                # Parse error detail from JSON response if available
                try:
                    import json
                    error_data = json.loads(text)
                    detail = error_data.get('detail', text)
                except:
                    detail = text
                
                # Map HTTP status to appropriate Gleitzeit error
                if response.status == 401:
                    from gleitzeit.core.errors import AuthenticationError
                    raise AuthenticationError(
                        endpoint=endpoint,
                        auth_method="bearer_token"
                    )
                elif response.status == 403:
                    from gleitzeit.core.errors import AuthorizationError
                    # Extract resource info from URL if possible
                    resource = "unknown"
                    action = "access"
                    if url:
                        parts = url.split('/')
                        if 'workflows' in parts:
                            idx = parts.index('workflows')
                            if idx + 1 < len(parts) and parts[idx + 1]:
                                resource = f"workflow/{parts[idx + 1]}"
                        elif 'tasks' in parts:
                            idx = parts.index('tasks')
                            if idx + 1 < len(parts) and parts[idx + 1]:
                                resource = f"task/{parts[idx + 1]}"
                    raise AuthorizationError(
                        resource=resource,
                        action=action,
                        reason=detail
                    )
                elif response.status == 404:
                    from gleitzeit.core.errors import ResourceNotFoundError
                    # Try to extract resource info from the error
                    raise ResourceNotFoundError(
                        resource_type="resource",
                        resource_id="unknown",
                        message=detail
                    )
                elif response.status == 429:
                    from gleitzeit.core.errors import RateLimitError
                    raise RateLimitError(f"Rate limit exceeded: {detail}")
                elif response.status >= 500:
                    from gleitzeit.core.errors import SystemError, ErrorCode
                    raise SystemError(
                        message=f"Server error: {detail}",
                        code=ErrorCode.INTERNAL_ERROR
                    )
                else:
                    raise NetworkError(f"API error {response.status}: {detail}")
                
            if response.content_type == 'application/json':
                return await response.json()
            return await response.text()
            
    async def _init_websocket(self) -> None:
        """Initialize WebSocket connection for events."""
        try:
            # Check if event endpoint is available
            ws_check_url = f"{self.base_url}/events/types"
            try:
                async with self.session.get(ws_check_url) as response:
                    if response.status != 200:
                        logger.warning(f"Event endpoint not available: {response.status}")
                        self._event_mode_available = False
                        return
            except Exception as e:
                logger.warning(f"Could not check event endpoint: {e}")
                self._event_mode_available = False
                return
                
            # Create WebSocket URL with auto-subscribe
            ws_url = f"{self.websocket_url}?auto_subscribe=*&client_id=api-{self.host}-{self.port}"
            
            # Create WebSocket manager
            self.websocket_manager = await self._create_websocket_manager(
                url=ws_url,
                # No auth token stored - cookies handle auth
                auth_headers={},
                client_id=f"api-{self.host}-{self.port}",
                reconnect_enabled=True,
                reconnect_max_attempts=10
            )
            
            # Connect WebSocket
            connected = await self.websocket_manager.connect()
            if connected:
                self._event_mode_available = True
                logger.info(f"WebSocket connected to {self.websocket_url}")
            else:
                logger.warning("WebSocket connection failed, will use polling")
                self._event_mode_available = False
                
        except Exception as e:
            logger.error(f"Failed to initialize WebSocket: {e}")
            self._event_mode_available = False
            
    # Workflow operations
    
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        """Submit workflow via API."""
        workflow_dict = workflow.dict() if hasattr(workflow, 'dict') else workflow
        # API expects workflow wrapped in a request object
        response = await self._request('POST', '/workflows', json_data={'workflow': workflow_dict})
        
        # Set up event tracking if available
        if self._event_mode_available:
            # Get workflow ID from dict or object
            workflow_id = workflow_dict.get('id') if isinstance(workflow_dict, dict) else workflow.id
            if workflow_id and workflow_id not in self._workflow_futures:
                self._workflow_futures[workflow_id] = asyncio.Future()
            
        return response
        
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow via API."""
        try:
            data = await self._request('GET', f'/workflows/{workflow_id}')
            return Workflow(**data) if data else None
        except Exception:
            return None
            
    async def list_workflows(self, status: Optional[str] = None,
                           limit: int = 100, offset: int = 0) -> List[Workflow]:
        """List workflows via API."""
        params = {'limit': limit, 'offset': offset}
        if status:
            params['status'] = status
        data = await self._request('GET', '/workflows', params=params)
        workflows = data.get('workflows', [])
        return [Workflow(**w) for w in workflows]
        
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel workflow via API."""
        return await self._request('POST', f'/workflows/{workflow_id}/cancel')
        
    async def pause_workflow(
        self, 
        workflow_id: str,
        rewind_to_task: Optional[str] = None,
        rewind_to_step: Optional[int] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Pause workflow via API with optional rewind."""
        request_data = {}
        if rewind_to_task:
            request_data["rewind_to"] = rewind_to_task
        elif rewind_to_step:
            request_data["rewind_to_step"] = rewind_to_step
        if reason:
            request_data["reason"] = reason
        
        return await self._request('POST', f'/workflows/{workflow_id}/pause', json_data=request_data)
        
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Resume workflow via API."""
        return await self._request('POST', f'/workflows/{workflow_id}/resume')
    
    async def get_pause_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get pause status and metadata via API."""
        return await self._request('GET', f'/workflows/{workflow_id}/pause-status')
        
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
    
    async def get_workflow_results(self, workflow_id: str) -> List[Dict[str, Any]]:
        """Get all task results for a workflow via API."""
        data = await self._request('GET', f'/workflows/{workflow_id}/results')
        # API returns {"items": [...]} format
        return data.get('items', [])
        
    # Task operations
    # Note: submit_task removed - all tasks must be submitted as workflows
        
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
                        limit: int = 100, offset: int = 0) -> List[Task]:
        """List tasks via API."""
        params = {'limit': limit, 'offset': offset}
        if status:
            params['status'] = status
        if workflow_id:
            params['workflow_id'] = workflow_id
        data = await self._request('GET', '/tasks', params=params)
        tasks = data.get('tasks', [])
        return [Task(**t) for t in tasks]
        
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
        """
        Wait for task completion using events or polling.
        
        If events are available, waits for completion event.
        Otherwise falls back to polling.
        """
        # Use event-driven wait from parent class
        return await super().wait_for_task(task_id, timeout)
        
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
                          provider: str = "default",
                          concurrency: int = 5,
                          task_params: Optional[Dict] = None) -> Dict[str, Any]:
        """Batch process via API."""
        data = {
            'directory': directory,
            'pattern': pattern,
            'provider': provider,
            'concurrency': concurrency,
            'params': task_params or {}
        }
        return await self._request('POST', '/batch/process', json_data=data)
        
    async def process_directory(self, directory: str, file_extensions: List[str],
                               provider: str = "default",
                               task_params: Optional[Dict] = None) -> Dict[str, Any]:
        """Process directory via API."""
        data = {
            'directory': directory,
            'extensions': file_extensions,
            'provider': provider,
            'params': task_params or {}
        }
        return await self._request('POST', '/batch/directory', json_data=data)
        
    # Chat operations
    
    async def chat(self, message: str, model: str = "llama3.2:latest",
                  session_id: Optional[str] = None,
                  context: Optional[Dict] = None) -> str:
        """Chat via API."""
        data = {
            'message': message,
            'model': model,
            'session_id': session_id,
            'context': context or {}
        }
        response = await self._request('POST', '/chat', json_data=data)
        return response.get('response', '')
    
    # Authentication operations
    
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login via API. Backend sets session cookie for stateless auth."""
        data = {'username': username, 'password': password}
        response = await self._request('POST', '/auth/login', json_data=data)
        
        # Backend sets session cookie - no token storage in adapter!
        if response.get('success'):
            logger.info(f"User {username} logged in successfully")
        
        return response
    
    async def logout(self) -> Dict[str, Any]:
        """Logout via API. Backend clears session cookie."""
        response = await self._request('POST', '/auth/logout')
        
        # Backend clears session cookie - no state in adapter!
        
        return response
    
    async def get_current_user(self) -> Dict[str, Any]:
        """Get current authenticated user via API."""
        return await self._request('GET', '/auth/me')
    
    # User Management
    
    async def create_user(self, username: str, email: str, password: str, 
                          role: str = "user", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a new user via API."""
        data = {
            'username': username,
            'email': email,
            'password': password,
            'role': role,
            'metadata': metadata or {}
        }
        return await self._request('POST', '/users', json_data=data)
    
    async def list_users(self, offset: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """List users via API."""
        params = {'offset': offset, 'limit': limit}
        return await self._request('GET', '/users', params=params)
    
    async def get_user(self, user_id: str) -> Dict[str, Any]:
        """Get user by ID via API."""
        return await self._request('GET', f'/users/{user_id}')
    
    async def update_user(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update user via API."""
        return await self._request('PUT', f'/users/{user_id}', json_data=updates)
    
    async def delete_user(self, user_id: str) -> Dict[str, Any]:
        """Delete user via API."""
        return await self._request('DELETE', f'/users/{user_id}')
    
    async def activate_user(self, user_id: str) -> Dict[str, Any]:
        """Activate user via API."""
        return await self._request('POST', f'/users/{user_id}/activate')
    
    async def deactivate_user(self, user_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """Deactivate user via API."""
        data = {'reason': reason} if reason else {}
        return await self._request('POST', f'/users/{user_id}/deactivate', json_data=data)
    
    async def search_users(self, query: str, field: str = "username", limit: int = 10) -> List[Dict[str, Any]]:
        """Search users via API."""
        params = {'field': field, 'limit': limit}
        return await self._request('GET', f'/users/search/{query}', params=params)
    
    # Password Management
    
    async def change_password(self, old_password: str, new_password: str) -> Dict[str, Any]:
        """Change password via API."""
        data = {'old_password': old_password, 'new_password': new_password}
        return await self._request('POST', '/auth/change-password', json_data=data)
    
    async def request_password_reset(self, email: str) -> Dict[str, Any]:
        """Request password reset via API."""
        data = {'email': email}
        return await self._request('POST', '/auth/reset-password/request', json_data=data)
    
    async def reset_password(self, token: str, new_password: str) -> Dict[str, Any]:
        """Reset password with token via API."""
        data = {'token': token, 'new_password': new_password}
        return await self._request('POST', '/auth/reset-password/confirm', json_data=data)
    
    # Session Management
    
    async def get_sessions(self) -> List[Dict[str, Any]]:
        """Get active sessions via API."""
        return await self._request('GET', '/sessions')
    
    async def revoke_session(self, session_id: str) -> Dict[str, Any]:
        """Revoke a session via API."""
        return await self._request('DELETE', f'/sessions/{session_id}')
    
    async def revoke_all_sessions(self) -> Dict[str, Any]:
        """Revoke all sessions via API."""
        return await self._request('DELETE', '/sessions')
    
    async def get_devices(self) -> List[Dict[str, Any]]:
        """Get user devices via API."""
        return await self._request('GET', '/sessions/devices')
    
    async def trust_device(self, trust_days: int = 30) -> Dict[str, Any]:
        """Trust current device via API."""
        params = {'trust_days': trust_days}
        return await self._request('POST', '/sessions/devices/trust', params=params)
    
    async def get_auth_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get authentication history via API."""
        params = {'limit': limit}
        return await self._request('GET', '/sessions/history', params=params)
    
    # Email Verification
    
    async def send_verification_email(self, user_id: str) -> Dict[str, Any]:
        """Send verification email via API."""
        return await self._request('POST', f'/users/{user_id}/send-verification')
    
    async def verify_email(self, token: str) -> Dict[str, Any]:
        """Verify email with token via API."""
        data = {'token': token}
        return await self._request('POST', '/auth/verify-email', json_data=data)
        
    # System operations
    
    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status via API."""
        return await self._request('GET', '/system/status')
        
    async def health_check(self) -> Dict[str, Any]:
        """Health check via API."""
        return await self._request('GET', '/health')
        
    async def get_providers(self) -> List[Dict[str, Any]]:
        """Get providers via API."""
        data = await self._request('GET', '/providers')
        return data.get('providers', [])
        
    async def get_protocols(self) -> List[Dict[str, Any]]:
        """Get protocols via API."""
        data = await self._request('GET', '/protocols')
        return data.get('protocols', [])

    async def get_provider_instance(self, provider_id: str) -> Any:
        """
        Get provider instance for error discovery.
        Note: This returns a dict representation, not actual instance.
        """
        providers = await self.get_providers()
        for provider in providers:
            if provider.get("provider_id") == provider_id:
                return provider
        return None
        
    async def get_task_logs(self, 
                          task_id: str,
                          level: Optional[str] = None,
                          limit: int = 100,
                          offset: int = 0) -> List[Dict[str, Any]]:
        """Get logs for a specific task via API."""
        params = {
            'limit': limit,
            'offset': offset
        }
        if level:
            params['level'] = level
        
        data = await self._request('GET', f'/logs/task/{task_id}', params=params)
        return data if isinstance(data, list) else []
    
    async def get_logs(self, 
                      level: Optional[str] = None,
                      source: Optional[str] = None,
                      start_time: Optional[datetime] = None,
                      end_time: Optional[datetime] = None,
                      limit: int = 100,
                      offset: int = 0) -> List[Dict[str, Any]]:
        """Get logs with optional filtering via API."""
        params = {
            'limit': limit,
            'offset': offset
        }
        if level:
            params['level'] = level
        if source:
            params['source'] = source
        if start_time:
            params['start_time'] = start_time.isoformat()
        if end_time:
            params['end_time'] = end_time.isoformat()
        
        data = await self._request('GET', '/logs', params=params)
        return data if isinstance(data, list) else []
    
    async def get_log_levels(self) -> List[str]:
        """Get available log levels via API."""
        data = await self._request('GET', '/logs/levels')
        return data.get('levels', ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])
    
    async def query_logs(self, 
                        query: str,
                        limit: int = 100,
                        offset: int = 0) -> List[Dict[str, Any]]:
        """Query logs using a search string via API."""
        params = {
            'query': query,
            'limit': limit,
            'offset': offset
        }
        data = await self._request('GET', '/logs/search', params=params)
        return data if isinstance(data, list) else []
    
    async def tail_logs(self,
                       lines: int = 100,
                       follow: bool = False,
                       source: Optional[str] = None) -> List[Dict[str, Any]]:
        """Tail logs (get most recent logs) via API."""
        params = {
            'lines': lines,
            'follow': follow
        }
        if source:
            params['source'] = source
        
        data = await self._request('GET', '/logs/tail', params=params)
        return data if isinstance(data, list) else []
    
    async def download_logs(self,
                          format: str = "json",
                          start_time: Optional[datetime] = None,
                          end_time: Optional[datetime] = None) -> bytes:
        """Download logs in specified format via API."""
        params = {'format': format}
        if start_time:
            params['start_time'] = start_time.isoformat()
        if end_time:
            params['end_time'] = end_time.isoformat()
        
        # This endpoint should return raw bytes
        data = await self._request('GET', '/logs/download', params=params)
        if isinstance(data, str):
            return data.encode('utf-8')
        return data
    
    async def clear_logs(self,
                        before: Optional[datetime] = None,
                        level: Optional[str] = None) -> Dict[str, Any]:
        """Clear logs with optional filtering via API."""
        data = {}
        if before:
            data['before'] = before.isoformat()
        if level:
            data['level'] = level
        
        return await self._request('POST', '/logs/clear', json_data=data)
    
    async def get_log_size(self) -> Dict[str, Any]:
        """Get log storage size information via API."""
        return await self._request('GET', '/logs/size')
    
    async def get_workflow_logs(self, workflow_id: str) -> List[Dict[str, Any]]:
        """Get logs for a specific workflow via API."""
        data = await self._request('GET', f'/logs/workflow/{workflow_id}')
        return data if isinstance(data, list) else []
        
    # Event-specific methods
    
    async def _poll_for_task(self, task_id: str, timeout: float,
                            poll_interval: float) -> Optional[TaskResult]:
        """Poll for task completion via API."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            task = await self.get_task(task_id)
            if task and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                return await self.get_task_result(task_id)
                
            await asyncio.sleep(poll_interval)
            
        return None
        
    async def _poll_for_workflow(self, workflow_id: str, timeout: float,
                                poll_interval: float) -> List[TaskResult]:
        """Poll for workflow completion via API."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            workflow = await self.get_workflow(workflow_id)
            if workflow and workflow.status in ['completed', 'failed', 'cancelled']:
                tasks = await self.get_workflow_tasks(workflow_id)
                results = []
                for task in tasks:
                    result = await self.get_task_result(task.id)
                    if result:
                        results.append(result)
                return results
                
            await asyncio.sleep(poll_interval)
            
        return []