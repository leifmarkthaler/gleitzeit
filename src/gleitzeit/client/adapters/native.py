"""
Native adapter for Gleitzeit client.
"""

import asyncio
from typing import Any, Dict, List, Optional
from gleitzeit.core.models import Task, Workflow, TaskResult
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.persistence.factory import create_persistence
from gleitzeit.registry import ProtocolProviderRegistry
from .base import BaseAdapter


class NativeAdapter(BaseAdapter):
    """Adapter for native mode operations."""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.execution_engine = None
        self.persistence = None
        self.registry = None
    
    async def initialize(self) -> None:
        """Initialize native components."""
        # Create persistence backend
        persistence_type = self.config.get('persistence_type', 'memory')
        self.persistence = create_persistence(persistence_type, self.config)
        await self.persistence.initialize()
        
        # Create provider registry
        self.registry = ProtocolProviderRegistry()
        
        # Create execution engine
        self.execution_engine = ExecutionEngine(
            persistence=self.persistence,
            registry=self.registry
        )
        await self.execution_engine.start()
    
    async def shutdown(self) -> None:
        """Shutdown native components."""
        if self.execution_engine:
            await self.execution_engine.stop()
        if self.persistence:
            await self.persistence.close()
    
    # Workflow operations
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        """Submit workflow natively."""
        if not self.execution_engine:
            raise RuntimeError("Execution engine not initialized")
        
        result = await self.execution_engine.submit_workflow(workflow)
        return {"workflow_id": result.id, "status": "submitted"}
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.get_workflow(workflow_id)
    
    async def list_workflows(self, status: Optional[str] = None,
                           limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List workflows natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        
        workflows = await self.persistence.list_workflows(
            status=status, limit=limit, offset=offset
        )
        return {"workflows": workflows, "total": len(workflows)}
    
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel workflow natively."""
        if not self.execution_engine:
            raise RuntimeError("Execution engine not initialized")
        
        success = await self.execution_engine.cancel_workflow(workflow_id)
        return {"success": success, "workflow_id": workflow_id}
    
    async def pause_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Pause workflow natively."""
        # Would need execution engine support
        return {"error": "Pause not yet implemented in native mode"}
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Resume workflow natively."""
        # Would need execution engine support
        return {"error": "Resume not yet implemented in native mode"}
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete workflow natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.delete_workflow(workflow_id)
    
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """Get workflow tasks natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.get_workflow_tasks(workflow_id)
    
    # Task operations
    async def submit_task(self, task: Task) -> Dict[str, Any]:
        """Submit task natively."""
        if not self.execution_engine:
            raise RuntimeError("Execution engine not initialized")
        
        result = await self.execution_engine.submit_task(task)
        return {"task_id": result.id, "status": "submitted"}
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.get_task(task_id)
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.get_task_result(task_id)
    
    async def list_tasks(self, status: Optional[str] = None,
                        workflow_id: Optional[str] = None,
                        limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List tasks natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        
        tasks = await self.persistence.list_tasks(
            status=status, workflow_id=workflow_id,
            limit=limit, offset=offset
        )
        return {"tasks": tasks, "total": len(tasks)}
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel task natively."""
        if not self.execution_engine:
            raise RuntimeError("Execution engine not initialized")
        return await self.execution_engine.cancel_task(task_id)
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete task natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.delete_task(task_id)
    
    async def wait_for_task(self, task_id: str, timeout: float = 300.0,
                           poll_interval: float = 1.0) -> Optional[TaskResult]:
        """Wait for task completion natively."""
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            task = await self.get_task(task_id)
            if task and task.status in ['completed', 'failed', 'cancelled']:
                return await self.get_task_result(task_id)
            
            await asyncio.sleep(poll_interval)
        
        return None
    
    # Queue operations
    async def get_queues(self) -> Dict[str, Any]:
        """Get queues natively."""
        if not self.execution_engine:
            raise RuntimeError("Execution engine not initialized")
        
        # Would need queue manager access
        return {"default": {"size": 0, "status": "active"}}
    
    async def get_queue_details(self, queue_name: str) -> Dict[str, Any]:
        """Get queue details natively."""
        return {"name": queue_name, "size": 0, "status": "active"}
    
    async def pause_queue(self, queue_name: str) -> Dict[str, Any]:
        """Pause queue natively."""
        return {"error": "Queue operations not yet implemented in native mode"}
    
    async def resume_queue(self, queue_name: str) -> Dict[str, Any]:
        """Resume queue natively."""
        return {"error": "Queue operations not yet implemented in native mode"}
    
    async def clear_queue(self, queue_name: str) -> Dict[str, Any]:
        """Clear queue natively."""
        return {"error": "Queue operations not yet implemented in native mode"}
    
    # Batch operations
    async def batch_process(self, directory: str, pattern: str = "*",
                           method: str = "llm/chat", prompt: str = None,
                           model: str = "llama3.2:latest",
                           max_concurrent: int = 5,
                           name: Optional[str] = None) -> Dict[str, Any]:
        """Batch process natively."""
        # Simple implementation - would be expanded
        from pathlib import Path
        import glob
        
        files = glob.glob(f"{directory}/{pattern}")
        results = {}
        
        for file_path in files[:max_concurrent]:
            task = Task(
                method=method,
                parameters={"file": file_path, "prompt": prompt, "model": model}
            )
            result = await self.submit_task(task)
            results[file_path] = result
        
        return results
    
    async def process_directory(self, directory: str, file_extensions: List[str],
                               workflow_yaml: str, max_concurrent: int = 5,
                               recursive: bool = True) -> Dict[str, Any]:
        """Process directory natively."""
        # Simplified implementation
        from pathlib import Path
        import yaml
        
        dir_path = Path(directory)
        results = {}
        
        for ext in file_extensions:
            if recursive:
                files = dir_path.rglob(f"*{ext}")
            else:
                files = dir_path.glob(f"*{ext}")
            
            for file_path in files:
                # Parse and substitute workflow
                workflow_dict = yaml.safe_load(workflow_yaml)
                workflow_dict['name'] = f"Process {file_path.name}"
                
                # Simple substitution
                workflow_yaml_substituted = workflow_yaml.replace("${file_path}", str(file_path))
                workflow_yaml_substituted = workflow_yaml_substituted.replace("${file_name}", file_path.name)
                
                workflow = Workflow(**yaml.safe_load(workflow_yaml_substituted))
                result = await self.submit_workflow(workflow)
                results[str(file_path)] = result
        
        return results
    
    # Chat operations  
    async def chat(self, message: str, model: str = "llama3.2:latest",
                  temperature: float = 0.7,
                  session_id: Optional[str] = None) -> Dict[str, Any]:
        """Chat natively."""
        task = Task(
            method="llm/chat",
            parameters={"message": message, "model": model, "temperature": temperature}
        )
        result = await self.submit_task(task)
        return result
    
    # System operations
    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status natively."""
        return {
            "status": "running",
            "mode": "native",
            "persistence": self.persistence.__class__.__name__ if self.persistence else "none"
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check natively."""
        return {
            "status": "healthy",
            "components": {
                "execution_engine": self.execution_engine is not None,
                "persistence": self.persistence is not None,
                "registry": self.registry is not None
            }
        }
    
    async def get_providers(self) -> List[Dict[str, Any]]:
        """Get providers natively."""
        if not self.registry:
            return []
        
        providers = []
        for protocol in self.registry.list_protocols():
            provider = self.registry.get_provider(protocol)
            if provider:
                providers.append({
                    "protocol": protocol,
                    "provider": provider.__class__.__name__
                })
        
        return providers
    
    async def get_protocols(self) -> List[Dict[str, Any]]:
        """Get protocols natively."""
        if not self.registry:
            return []
        
        return [{"protocol": p} for p in self.registry.list_protocols()]