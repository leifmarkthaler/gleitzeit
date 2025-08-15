"""
Gleitzeit Python Client API

Simple Python interface for using Gleitzeit programmatically.
"""

import asyncio
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
import tempfile
import yaml
import json

from gleitzeit.core import ExecutionEngine, Task, Workflow, Priority
from gleitzeit.core.workflow_loader import load_workflow_from_file, load_workflow_from_dict
from gleitzeit.core.batch_processor import BatchProcessor
from gleitzeit.core.error_handler import (
    ErrorHandler, get_error_handler,
    task_not_found_error, provider_not_available_error
)
from gleitzeit.core.errors import TaskError, ErrorCode, InvalidParameterError
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.persistence.sqlite_backend import SQLiteBackend
from gleitzeit.persistence.redis_backend import RedisBackend
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.python_function_provider import CustomFunctionProvider
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider
from gleitzeit.protocols import PYTHON_PROTOCOL_V1, LLM_PROTOCOL_V1, MCP_PROTOCOL_V1


class GleitzeitClient:
    """
    High-level Python client for Gleitzeit workflow orchestration.
    
    Example:
        ```python
        from gleitzeit.client import GleitzeitClient
        
        # Initialize client
        client = GleitzeitClient()
        
        # Run a workflow
        result = await client.run_workflow("workflow.yaml")
        
        # Or create and run workflow programmatically
        result = await client.chat("Tell me a joke")
        ```
    """
    
    def __init__(
        self,
        persistence: str = "sqlite",
        db_path: Optional[str] = None,
        redis_url: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
        debug: bool = False
    ):
        """
        Initialize Gleitzeit client.
        
        Args:
            persistence: Backend type ("sqlite", "redis", "memory")
            db_path: SQLite database path (auto-generated if not provided)
            redis_url: Redis connection URL
            ollama_url: Ollama API endpoint
        """
        self.persistence_type = persistence
        self.db_path = db_path
        self.redis_url = redis_url
        self.ollama_url = ollama_url
        self.debug = debug
        
        self.backend = None
        self.registry = None
        self.engine = None
        self.batch_processor = None
        self._initialized = False
        
        # Setup error handler
        self.error_handler = ErrorHandler(debug=debug, suppress_warnings=not debug)
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.shutdown()
    
    async def initialize(self):
        """Initialize the client resources."""
        if self._initialized:
            return
        
        # Setup persistence
        if self.persistence_type == "redis":
            self.backend = RedisBackend(self.redis_url or "redis://localhost:6379/0")
        elif self.persistence_type == "memory":
            from gleitzeit.persistence.base import InMemoryBackend
            self.backend = InMemoryBackend()
        else:  # sqlite
            if not self.db_path:
                self.db_path = Path(tempfile.gettempdir()) / "gleitzeit.db"
            self.backend = SQLiteBackend(str(self.db_path))
        
        await self.backend.initialize()
        
        # Setup registry and providers
        self.registry = ProtocolProviderRegistry()
        
        # Register protocols
        self.registry.register_protocol(PYTHON_PROTOCOL_V1)
        self.registry.register_protocol(LLM_PROTOCOL_V1)
        self.registry.register_protocol(MCP_PROTOCOL_V1)
        
        # Register providers
        # Python provider
        python_provider = CustomFunctionProvider("python-1")
        await python_provider.initialize()
        self.registry.register_provider("python-1", "python/v1", python_provider)
        
        # Ollama provider
        ollama_provider = OllamaProvider("ollama-1", self.ollama_url)
        await ollama_provider.initialize()
        self.registry.register_provider("ollama-1", "llm/v1", ollama_provider)
        
        # MCP provider
        mcp_provider = SimpleMCPProvider("mcp-1")
        await mcp_provider.initialize()
        self.registry.register_provider("mcp-1", "mcp/v1", mcp_provider)
        
        # Setup execution engine
        self.engine = ExecutionEngine(
            registry=self.registry,
            queue_manager=QueueManager(),
            dependency_resolver=DependencyResolver(),
            persistence=self.backend,
            max_concurrent_tasks=5
        )
        
        # Setup batch processor
        self.batch_processor = BatchProcessor()
        
        self._initialized = True
    
    async def shutdown(self):
        """Shutdown and cleanup resources."""
        if self.backend:
            await self.backend.shutdown()
        if self.registry:
            await self.registry.stop()
        self._initialized = False
    
    # High-level convenience methods
    
    async def chat(
        self,
        prompt: str,
        model: str = "llama3.2:latest",
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        Simple chat completion.
        
        Args:
            prompt: User prompt
            model: LLM model to use
            system: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
        
        Returns:
            Generated text response
        """
        await self.initialize()
        
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        task = Task(
            id=f"chat-{asyncio.get_event_loop().time():.0f}",
            name="Chat completion",
            protocol="llm/v1",
            method="llm/chat",
            params={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                **({"max_tokens": max_tokens} if max_tokens else {})
            }
        )
        
        workflow = Workflow(
            id=f"chat-workflow-{task.id}",
            name="Chat workflow",
            tasks=[task]
        )
        
        await self.backend.save_workflow(workflow)
        await self.backend.save_task(task)
        await self.engine._execute_workflow(workflow)
        
        if task.id in self.engine.task_results:
            result = self.engine.task_results[task.id]
            if isinstance(result, dict) and "response" in result:
                return result["response"]
            return str(result)
        
        raise TaskError(
            "Chat completion failed - no result returned",
            ErrorCode.TASK_EXECUTION_FAILED,
            task_id=task.id
        )
    
    async def vision(
        self,
        image_path: str,
        prompt: str = "Describe this image",
        model: str = "llava:latest"
    ) -> str:
        """
        Analyze an image with vision model.
        
        Args:
            image_path: Path to image file
            prompt: Question about the image
            model: Vision model to use
        
        Returns:
            Image analysis response
        """
        await self.initialize()
        
        task = Task(
            id=f"vision-{asyncio.get_event_loop().time():.0f}",
            name="Vision analysis",
            protocol="llm/v1",
            method="llm/vision",
            params={
                "model": model,
                "image_path": image_path,
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        
        workflow = Workflow(
            id=f"vision-workflow-{task.id}",
            name="Vision workflow",
            tasks=[task]
        )
        
        await self.backend.save_workflow(workflow)
        await self.backend.save_task(task)
        await self.engine._execute_workflow(workflow)
        
        if task.id in self.engine.task_results:
            result = self.engine.task_results[task.id]
            if isinstance(result, dict) and "response" in result:
                return result["response"]
            return str(result)
        
        raise TaskError(
            "Vision analysis failed - no result returned",
            ErrorCode.TASK_EXECUTION_FAILED,
            task_id=task.id
        )
    
    async def execute_python(
        self,
        script_file: str,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = 10
    ) -> Any:
        """
        Execute a Python script file.
        
        Args:
            script_file: Path to Python script
            context: Variables to pass to the script
            timeout: Execution timeout in seconds
        
        Returns:
            Script execution result
        """
        await self.initialize()
        
        task = Task(
            id=f"python-{asyncio.get_event_loop().time():.0f}",
            name="Python execution",
            protocol="python/v1",
            method="python/execute",
            params={
                "file": script_file,
                "context": context or {},
                "timeout": timeout
            }
        )
        
        workflow = Workflow(
            id=f"python-workflow-{task.id}",
            name="Python workflow",
            tasks=[task]
        )
        
        await self.backend.save_workflow(workflow)
        await self.backend.save_task(task)
        await self.engine._execute_workflow(workflow)
        
        if task.id in self.engine.task_results:
            result = self.engine.task_results[task.id]
            if isinstance(result, dict) and "result" in result:
                return result["result"]
            return result
        
        raise TaskError(
            f"Python script execution failed: {script_file}",
            ErrorCode.TASK_EXECUTION_FAILED,
            task_id=task.id,
            data={"script_file": script_file}
        )
    
    # Workflow methods
    
    async def run_workflow(
        self,
        workflow: Union[str, Path, Dict, Workflow]
    ) -> Dict[str, Any]:
        """
        Run a workflow from file, dict, or Workflow object.
        
        Args:
            workflow: Workflow file path, dict, or Workflow object
        
        Returns:
            Dictionary of task results keyed by task ID
        """
        await self.initialize()
        
        # Load workflow based on input type
        if isinstance(workflow, (str, Path)):
            workflow_obj = load_workflow_from_file(str(workflow))
        elif isinstance(workflow, dict):
            workflow_obj = load_workflow_from_dict(workflow)
        elif isinstance(workflow, Workflow):
            workflow_obj = workflow
        else:
            raise InvalidParameterError(
                "workflow",
                f"Unsupported workflow type: {type(workflow)}"
            )
        
        # Store and execute
        await self.backend.save_workflow(workflow_obj)
        for task in workflow_obj.tasks:
            await self.backend.save_task(task)
        
        await self.engine._execute_workflow(workflow_obj)
        
        # Return all task results
        return dict(self.engine.task_results)
    
    async def create_workflow(
        self,
        name: str,
        tasks: List[Dict[str, Any]]
    ) -> Workflow:
        """
        Create a workflow programmatically.
        
        Args:
            name: Workflow name
            tasks: List of task dictionaries
        
        Returns:
            Workflow object
        """
        workflow_dict = {
            "name": name,
            "tasks": tasks
        }
        return load_workflow_from_dict(workflow_dict)
    
    # Batch processing methods
    
    async def batch_process(
        self,
        directory: Optional[str] = None,
        files: Optional[List[str]] = None,
        pattern: str = "*",
        method: str = "llm/chat",
        prompt: str = "Analyze this file",
        model: str = "llama3.2:latest",
        protocol: str = "llm/v1"
    ) -> Dict[str, Any]:
        """
        Process multiple files in batch.
        
        Args:
            directory: Directory to scan for files
            files: List of file paths (alternative to directory)
            pattern: Glob pattern for file matching
            method: Processing method
            prompt: Prompt for LLM processing
            model: Model to use
            protocol: Protocol to use
        
        Returns:
            Batch processing results
        """
        await self.initialize()
        
        result = await self.batch_processor.process_batch(
            execution_engine=self.engine,
            files=files,
            directory=directory,
            pattern=pattern,
            method=method,
            prompt=prompt,
            model=model,
            protocol=protocol
        )
        
        return result.to_dict()
    
    async def batch_chat(
        self,
        directory: str,
        pattern: str = "*.txt",
        prompt: str = "Summarize this document",
        model: str = "llama3.2:latest"
    ) -> Dict[str, Any]:
        """
        Batch process text files with LLM.
        
        Args:
            directory: Directory containing files
            pattern: File pattern to match
            prompt: Prompt for each file
            model: LLM model to use
        
        Returns:
            Batch results
        """
        return await self.batch_process(
            directory=directory,
            pattern=pattern,
            method="llm/chat",
            prompt=prompt,
            model=model,
            protocol="llm/v1"
        )
    
    async def batch_python(
        self,
        directory: str,
        pattern: str,
        script_file: str,
        timeout: int = 10
    ) -> Dict[str, Any]:
        """
        Batch process files with Python script.
        
        Note: Python batch processing requires using the workflow YAML approach
        due to the current BatchProcessor limitations.
        
        Args:
            directory: Directory containing files
            pattern: File pattern to match
            script_file: Python script to execute
            timeout: Execution timeout per file
        
        Returns:
            Batch results
        """
        # For now, Python batch processing needs to be done via workflows
        # The BatchProcessor currently only supports LLM protocols directly
        return await self.batch_process(
            directory=directory,
            pattern=pattern,
            protocol="python/v1",
            method="python/execute",
            prompt=f"Execute script: {script_file}"
        )
    
    # Workflow status and results
    
    async def get_workflow_status(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow status."""
        await self.initialize()
        return await self.backend.get_workflow(workflow_id)
    
    async def get_task_result(self, task_id: str) -> Optional[Any]:
        """Get task result."""
        await self.initialize()
        return await self.backend.get_task_result(task_id)
    
    async def list_workflows(self, limit: int = 20) -> List[Workflow]:
        """List recent workflows."""
        await self.initialize()
        return await self.backend.list_workflows(limit=limit)


# Convenience functions for simple usage

async def chat(prompt: str, **kwargs) -> str:
    """Quick chat completion."""
    async with GleitzeitClient() as client:
        return await client.chat(prompt, **kwargs)


async def vision(image_path: str, prompt: str = "Describe this image", **kwargs) -> str:
    """Quick image analysis."""
    async with GleitzeitClient() as client:
        return await client.vision(image_path, prompt, **kwargs)


async def run_workflow(workflow_path: str) -> Dict[str, Any]:
    """Quick workflow execution."""
    async with GleitzeitClient() as client:
        return await client.run_workflow(workflow_path)


async def batch_process(directory: str, pattern: str, prompt: str, **kwargs) -> Dict[str, Any]:
    """Quick batch processing."""
    async with GleitzeitClient() as client:
        return await client.batch_chat(directory, pattern, prompt, **kwargs)


async def execute_python(script_file: str, context: Optional[Dict[str, Any]] = None, **kwargs) -> Any:
    """Quick Python script execution."""
    async with GleitzeitClient() as client:
        return await client.execute_python(script_file, context, **kwargs)