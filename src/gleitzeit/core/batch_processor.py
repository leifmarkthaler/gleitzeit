"""
Batch Processing for Gleitzeit V4

Handles batch processing of multiple files through workflows,
creating parallel tasks for efficient processing.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from gleitzeit.core.execution_engine import ExecutionEngine
from uuid import uuid4
import glob
import json

from gleitzeit.core.models import Task, Workflow, Priority
from gleitzeit.core.workflow_loader import create_task_from_dict
from gleitzeit.core.errors import ConfigurationError, TaskValidationError

logger = logging.getLogger(__name__)


class BatchResult:
    """Result of a batch processing operation"""
    
    def __init__(self, batch_id: str):
        self.batch_id = batch_id
        self.created_at = datetime.now(timezone.utc)
        self.total_files = 0
        self.successful = 0
        self.failed = 0
        self.results = {}
        self.parameters = {}
        self.processing_time = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'batch_id': self.batch_id,
            'created_at': self.created_at.isoformat(),
            'summary': {
                'total': self.total_files,
                'successful': self.successful,
                'failed': self.failed,
                'processing_time': self.processing_time
            },
            'parameters': self.parameters,
            'results': self.results
        }
    
    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=2)
    
    def to_markdown(self) -> str:
        """Convert to Markdown format"""
        md = f"# Batch Processing Results\n"
        md += f"**Batch ID**: {self.batch_id}\n"
        md += f"**Date**: {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        md += f"**Total Files**: {self.total_files} ({self.successful} successful, {self.failed} failed)\n"
        md += f"**Processing Time**: {self.processing_time:.2f}s\n\n"
        
        md += "## Results\n\n"
        for file_path, result in self.results.items():
            status_icon = "✅" if result.get('status') == 'success' else "❌"
            md += f"### {status_icon} {Path(file_path).name}\n"
            if result.get('status') == 'success':
                content = result.get('content', '')
                # Truncate long content
                if len(content) > 500:
                    content = content[:500] + "..."
                md += f"{content}\n\n"
            else:
                md += f"Error: {result.get('error', 'Unknown error')}\n\n"
        
        return md
    
    def save_to_file(self, output_dir: Path = None) -> Path:
        """Save results to file"""
        if output_dir is None:
            output_dir = Path.home() / '.gleitzeit' / 'batch_results'
        
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{self.batch_id}.json"
        
        with open(output_file, 'w') as f:
            f.write(self.to_json())
        
        logger.info(f"Batch results saved to {output_file}")
        return output_file


class BatchProcessor:
    """
    Handles batch processing of files through workflows.
    Creates parallel tasks for each file.
    """
    
    def __init__(self):
        self.current_batch = None
        self.batch_history = []
    
    def scan_directory(self, directory: str, pattern: str = "*") -> List[str]:
        """
        Scan directory for files matching pattern
        
        Args:
            directory: Directory path to scan
            pattern: Glob pattern for files (e.g., "*.txt", "*.png")
        
        Returns:
            List of file paths
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            raise ConfigurationError(f"Directory not found: {directory}")
        
        if not dir_path.is_dir():
            raise ConfigurationError(f"Not a directory: {directory}")
        
        # Use glob to find matching files
        file_pattern = str(dir_path / pattern)
        files = glob.glob(file_pattern)
        
        # Filter out directories
        files = [f for f in files if Path(f).is_file()]
        
        logger.info(f"Found {len(files)} files matching '{pattern}' in {directory}")
        return sorted(files)
    
    def create_batch_workflow(
        self,
        files: List[str],
        method: str,
        prompt: str,
        model: str = "llama3.2:latest",
        protocol: str = None,
        name: str = None
    ) -> Workflow:
        """
        Create a workflow with parallel tasks for each file
        
        Args:
            files: List of file paths to process
            method: Protocol method (e.g., "llm/chat", "llm/vision", "python/execute")
            prompt: Prompt to use for each file
            model: Model to use
            protocol: Protocol to use (auto-detected from method if not provided)
            name: Optional workflow name
        
        Returns:
            Workflow with tasks for each file
        """
        if not files:
            raise TaskValidationError(
                "batch_task",
                ["No files provided for batch processing"]
            )
        
        # Auto-detect protocol from method if not provided
        if protocol is None:
            if method.startswith("python/"):
                protocol = "python/v1"
            elif method.startswith("mcp/"):
                protocol = "mcp/v1"
            elif method.startswith("template/"):
                protocol = "template/v1"
            else:
                # Default to llm/v1 for chat/vision methods
                protocol = "llm/v1"
        
        workflow_id = f"batch-{uuid4().hex[:8]}"
        workflow_name = name or f"Batch Processing ({len(files)} files)"
        
        tasks = []
        for i, file_path in enumerate(files):
            file_name = Path(file_path).name
            task_id = f"process-{file_name.replace('.', '-')}-{i}"
            
            # Determine if this is a vision task
            is_image = Path(file_path).suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']
            
            if method.startswith("python/"):
                # Python execution task
                task_data = {
                    'id': task_id,
                    'name': f"Process {file_name}",
                    'protocol': protocol,
                    'method': method,
                    'params': {
                        'file': file_path
                    },
                    'priority': 'normal'
                }
            elif is_image and method == "llm/vision":
                # Vision task with image_path
                task_data = {
                    'id': task_id,
                    'name': f"Process {file_name}",
                    'protocol': protocol,
                    'method': method,
                    'params': {
                        'model': model,
                        'image_path': file_path,
                        'messages': [
                            {'role': 'user', 'content': prompt}
                        ]
                    },
                    'priority': 'normal'
                }
            else:
                # Text/LLM task with file_path
                task_data = {
                    'id': task_id,
                    'name': f"Process {file_name}",
                    'protocol': protocol,
                    'method': method,
                    'params': {
                        'model': model,
                        'file_path': file_path,
                        'messages': [
                            {'role': 'user', 'content': prompt}
                        ]
                    },
                    'priority': 'normal'
                }
            
            task = create_task_from_dict(task_data, workflow_id, resolve_dependencies=False)
            tasks.append(task)
        
        workflow = Workflow(
            id=workflow_id,
            name=workflow_name,
            description=f"Batch processing of {len(files)} files",
            tasks=tasks,
            metadata={
                'batch': True,
                'file_count': len(files),
                'prompt': prompt,
                'model': model
            }
        )
        
        logger.info(f"Created batch workflow '{workflow_name}' with {len(tasks)} tasks")
        return workflow
    
    async def process_batch(
        self,
        execution_engine: 'ExecutionEngine',
        files: List[str] = None,
        directory: str = None,
        pattern: str = "*",
        method: str = "llm/chat",
        prompt: str = "Analyze this file",
        model: str = "llama3.2:latest",
        protocol: str = None
    ) -> BatchResult:
        """
        Process a batch of files
        
        Args:
            execution_engine: ExecutionEngine instance
            files: List of file paths (optional)
            directory: Directory to scan (optional)
            pattern: File pattern for directory scan
            method: Protocol method
            prompt: Prompt for processing
            model: Model to use
            protocol: Protocol to use (auto-detected from method if not provided)
        
        Returns:
            BatchResult with processing results
        """
        start_time = asyncio.get_event_loop().time()
        
        # Collect files
        if directory:
            files = self.scan_directory(directory, pattern)
        elif not files:
            raise TaskValidationError(
                "batch_task",
                ["Either 'files' or 'directory' must be provided"]
            )
        
        # Auto-detect protocol if not provided (same logic as create_batch_workflow)
        if protocol is None:
            if method.startswith("python/"):
                protocol = "python/v1"
            elif method.startswith("mcp/"):
                protocol = "mcp/v1"
            elif method.startswith("template/"):
                protocol = "template/v1"
            else:
                protocol = "llm/v1"
        
        # Create batch result
        batch_id = f"batch-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        batch_result = BatchResult(batch_id)
        batch_result.total_files = len(files)
        batch_result.parameters = {
            'method': method,
            'prompt': prompt,
            'model': model,
            'protocol': protocol,
            'directory': directory,
            'pattern': pattern if directory else None
        }
        
        # Handle empty file list
        if not files:
            # No files to process - return empty result
            batch_result.successful = 0
            batch_result.failed = 0
            batch_result.processing_time = asyncio.get_event_loop().time() - start_time
            logger.info(f"No files found matching pattern '{pattern}' in {directory}")
            return batch_result
        
        # Create and execute workflow
        workflow = self.create_batch_workflow(
            files=files,
            method=method,
            prompt=prompt,
            model=model,
            protocol=protocol,
            name=f"Batch {batch_id}"
        )
        
        # Submit workflow
        await execution_engine.submit_workflow(workflow)
        
        # Execute workflow
        try:
            await execution_engine._execute_workflow(workflow)
        except Exception as e:
            logger.error(f"Error executing batch workflow: {e}")
            batch_result.failed = len(files)
            batch_result.processing_time = asyncio.get_event_loop().time() - start_time
            return batch_result
        
        # Collect results
        for task in workflow.tasks:
            file_path = None
            
            # Extract file path from task params
            if 'file_path' in task.params:
                file_path = task.params['file_path']
            elif 'image_path' in task.params:
                file_path = task.params['image_path']
            elif 'file' in task.params:
                file_path = task.params['file']
            
            if file_path:
                result = execution_engine.task_results.get(task.id)
                if result:
                    if result.status == 'completed':
                        # Extract the response text from the result
                        content = ''
                        if result.result:
                            # Try various fields based on provider type
                            # Python tasks return 'output', LLM tasks return 'response'
                            content = result.result.get('output', 
                                        result.result.get('response', 
                                            result.result.get('content', 
                                                result.result.get('text', ''))))
                        batch_result.results[file_path] = {
                            'status': 'success',
                            'content': content
                        }
                        batch_result.successful += 1
                    else:
                        batch_result.results[file_path] = {
                            'status': 'failed',
                            'error': result.error or 'Unknown error'
                        }
                        batch_result.failed += 1
                else:
                    batch_result.results[file_path] = {
                        'status': 'failed',
                        'error': 'No result found'
                    }
                    batch_result.failed += 1
        
        # Calculate processing time
        batch_result.processing_time = asyncio.get_event_loop().time() - start_time
        
        # Save results
        batch_result.save_to_file()
        
        # Store in history
        self.current_batch = batch_result
        self.batch_history.append(batch_id)
        
        logger.info(f"Batch {batch_id} completed: {batch_result.successful}/{batch_result.total_files} successful")
        
        return batch_result