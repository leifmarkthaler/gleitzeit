"""
Gleitzeit V2 Client

Clean client interface for submitting workflows and receiving results.
Uses pure Socket.IO communication with event-driven completion.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

import socketio

from ..core.models import Workflow, Task, TaskType, TaskParameters, Priority

logger = logging.getLogger(__name__)


class GleitzeitClient:
    """
    Gleitzeit V2 client for workflow submission and monitoring
    
    Features:
    - Clean Socket.IO communication
    - Event-driven workflow completion
    - Async/await interface
    - Result streaming
    - Progress monitoring
    """
    
    def __init__(self, server_url: str = "http://localhost:8000"):
        self.server_url = server_url
        self.sio = socketio.AsyncClient()
        
        # Connection state
        self.connected = False
        self.server_capabilities = []
        
        # Event tracking
        self.workflow_futures: Dict[str, asyncio.Future] = {}
        self.progress_callbacks: Dict[str, Callable] = {}
        
        # Setup event handlers
        self._setup_handlers()
        
        logger.info(f"GleitzeitClient initialized: {server_url}")
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect():
            self.connected = True
            logger.info("✅ Connected to central Socket.IO server")
            
            # Register as client
            await self.sio.emit('component:register', {
                'type': 'client',
                'id': f'client_{id(self)}'
            })
        
        @self.sio.event
        async def disconnect():
            self.connected = False
            logger.info("🔌 Disconnected from central Socket.IO server")
        
        @self.sio.event
        async def server_ready(data):
            self.server_capabilities = data.get('capabilities', [])
            logger.info(f"Server ready - capabilities: {self.server_capabilities}")
        
        @self.sio.on('workflow:submitted')
        async def workflow_submitted(data):
            workflow_id = data.get('workflow_id')
            logger.info(f"Workflow submitted: {workflow_id}")
        
        @self.sio.on('workflow:completed')
        async def workflow_completed(data):
            workflow_id = data.get('workflow_id')
            status = data.get('status')
            results = data.get('results', {})
            
            logger.info(f"Workflow completed: {workflow_id} ({status})")
            
            # Resolve future if waiting
            if workflow_id in self.workflow_futures:
                future = self.workflow_futures.pop(workflow_id)
                if not future.done():
                    future.set_result({
                        'status': status,
                        'results': results,
                        'workflow_id': workflow_id
                    })
        
        @self.sio.on('task:progress')
        async def task_progress(data):
            task_id = data.get('task_id')
            progress = data.get('progress', {})
            
            # Find workflow for progress callback
            for workflow_id, callback in self.progress_callbacks.items():
                try:
                    await callback(task_id, progress)
                except Exception as e:
                    logger.warning(f"Progress callback error: {e}")
        
        @self.sio.event
        async def task_completed(data):
            task_id = data.get('task_id')
            logger.debug(f"Task completed: {task_id}")
        
        @self.sio.event
        async def error(data):
            message = data.get('message', 'Unknown error')
            logger.error(f"Server error: {message}")
    
    async def connect(self):
        """Connect to server"""
        if self.connected:
            return
        
        try:
            await self.sio.connect(self.server_url)
            
            # Wait for server ready
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Failed to connect to server: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from server"""
        if self.connected:
            await self.sio.disconnect()
    
    async def submit_workflow(
        self, 
        workflow: Workflow, 
        timeout: float = 300.0,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Submit workflow and wait for completion
        
        Args:
            workflow: Workflow to submit
            timeout: Timeout in seconds
            progress_callback: Optional callback for progress updates
            
        Returns:
            Workflow results
        """
        if not self.connected:
            await self.connect()
        
        workflow_id = workflow.id
        
        # Setup progress callback
        if progress_callback:
            self.progress_callbacks[workflow_id] = progress_callback
        
        # Create future for result
        future = asyncio.Future()
        self.workflow_futures[workflow_id] = future
        
        try:
            # Submit workflow
            await self.sio.emit('workflow:submit', {
                'workflow': workflow.to_dict()
            })
            
            logger.info(f"Submitted workflow: {workflow.name} ({workflow_id})")
            
            # Wait for completion
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
            
        except asyncio.TimeoutError:
            logger.warning(f"Workflow timeout after {timeout}s: {workflow_id}")
            return {
                'status': 'timeout',
                'workflow_id': workflow_id,
                'timeout': timeout
            }
        
        finally:
            # Cleanup
            self.workflow_futures.pop(workflow_id, None)
            self.progress_callbacks.pop(workflow_id, None)
    
    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status"""
        if not self.connected:
            await self.connect()
        
        # Create future for response
        response_future = asyncio.Future()
        
        @self.sio.event
        async def workflow_status_response(data):
            if data.get('workflow_id') == workflow_id:
                response_future.set_result(data.get('status', {}))
        
        # Request status
        await self.sio.emit('workflow:status', {
            'workflow_id': workflow_id
        })
        
        try:
            result = await asyncio.wait_for(response_future, timeout=10.0)
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Status request timeout for workflow: {workflow_id}")
            return {}
    
    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel workflow"""
        if not self.connected:
            await self.connect()
        
        await self.sio.emit('workflow:cancel', {
            'workflow_id': workflow_id
        })
        
        logger.info(f"Cancelled workflow: {workflow_id}")
        return True
    
    # ===================
    # Convenience Methods
    # ===================
    
    async def run_text_generation(
        self,
        prompt: str,
        model: str = "llama3",
        temperature: float = 0.7,
        max_tokens: int = 500,
        timeout: float = 60.0
    ) -> str:
        """Run simple text generation task"""
        
        task = Task(
            name="Text Generation",
            task_type=TaskType.LLM_GENERATE,
            parameters=TaskParameters(
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens
            )
        )
        
        workflow = Workflow(
            name=f"Text Generation: {prompt[:50]}..."
        )
        workflow.add_task(task)
        
        result = await self.submit_workflow(workflow, timeout=timeout)
        
        if result['status'] == 'completed':
            task_results = result['results']
            if task.id in task_results:
                return task_results[task.id]
        
        raise RuntimeError(f"Text generation failed: {result.get('status', 'unknown error')}")
    
    async def run_vision_analysis(
        self,
        image_path: str,
        prompt: str,
        model: str = "llava",
        timeout: float = 60.0
    ) -> str:
        """Run vision analysis task"""
        
        task = Task(
            name="Vision Analysis",
            task_type=TaskType.LLM_VISION,
            parameters=TaskParameters(
                image_path=image_path,
                prompt=prompt,
                model=model
            )
        )
        
        workflow = Workflow(
            name=f"Vision Analysis: {image_path}",
            tasks=[task]
        )
        
        result = await self.submit_workflow(workflow, timeout=timeout)
        
        if result['status'] == 'completed':
            task_results = result['results']
            if task.id in task_results:
                return task_results[task.id]
        
        raise RuntimeError(f"Vision analysis failed: {result.get('status', 'unknown error')}")
    
    async def run_function(
        self,
        function_name: str,
        args: List[Any] = None,
        kwargs: Dict[str, Any] = None,
        timeout: float = 60.0
    ) -> Any:
        """Run function execution task"""
        
        task = Task(
            name=f"Function: {function_name}",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name=function_name,
                args=args or [],
                kwargs=kwargs or {}
            )
        )
        
        workflow = Workflow(
            name=f"Function Execution: {function_name}",
            tasks=[task]
        )
        
        result = await self.submit_workflow(workflow, timeout=timeout)
        
        if result['status'] == 'completed':
            task_results = result['results']
            if task.id in task_results:
                return task_results[task.id]
        
        raise RuntimeError(f"Function execution failed: {result.get('status', 'unknown error')}")
    
    async def run_batch_processing(
        self,
        tasks: List[Task],
        workflow_name: str = "Batch Processing",
        timeout: float = 300.0,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """Run batch of tasks"""
        
        workflow = Workflow(
            name=workflow_name,
            max_parallel=len(tasks)  # Allow all tasks to run in parallel if no dependencies
        )
        for task in tasks:
            workflow.add_task(task)
        
        return await self.submit_workflow(workflow, timeout=timeout, progress_callback=progress_callback)
    
    async def run_mcp_function(
        self,
        server: str,
        function: str,
        arguments: Dict[str, Any] = None,
        timeout: float = 30.0
    ) -> Any:
        """Run MCP function on specified server"""
        
        task = Task(
            name=f"MCP: {server}.{function}",
            task_type=TaskType.MCP_FUNCTION,
            parameters=TaskParameters(
                server=server,
                function=function,
                arguments=arguments or {}
            )
        )
        
        workflow = Workflow(
            name=f"MCP Function: {server}.{function}",
            tasks=[task]
        )
        
        result = await self.submit_workflow(workflow, timeout=timeout)
        
        if result['status'] == 'completed':
            task_results = result['results']
            if task.id in task_results:
                return task_results[task.id]
        
        raise RuntimeError(f"MCP function failed: {result.get('status', 'unknown error')}")
    
    async def run_mcp_query(
        self,
        server: str,
        query: str,
        parameters: Dict[str, Any] = None,
        timeout: float = 30.0
    ) -> Any:
        """Run MCP query on specified server"""
        
        task = Task(
            name=f"MCP Query: {server}",
            task_type=TaskType.MCP_QUERY,
            parameters=TaskParameters(
                server=server,
                query=query,
                parameters=parameters or {}
            )
        )
        
        workflow = Workflow(
            name=f"MCP Query: {query[:50]}",
            tasks=[task]
        )
        
        result = await self.submit_workflow(workflow, timeout=timeout)
        
        if result['status'] == 'completed':
            task_results = result['results']
            if task.id in task_results:
                return task_results[task.id]
        
        raise RuntimeError(f"MCP query failed: {result.get('status', 'unknown error')}")
    
    def __str__(self) -> str:
        return f"GleitzeitClient(server={self.server_url}, connected={self.connected})"