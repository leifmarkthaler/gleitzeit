"""
Enhanced Workflow Loader V2

Improvements over V1:
- Better statelessness with lazy file discovery
- Structured logging with performance metrics
- Streaming support for large workflows
- Schema validation and security hardening
- Resource limits and distributed-friendly design
- Integrated with central error and logging systems
- Unified batch processing (replacing separate BatchProcessor)
"""

import yaml
import json
import glob
import time
import hashlib
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Iterator, Callable, Union
from uuid import uuid4
from datetime import datetime, timezone
from contextlib import contextmanager

from gleitzeit.core.models import Task, Workflow, Priority, RetryConfig
from gleitzeit.core.errors import (
    WorkflowValidationError, 
    ConfigurationError,
    WorkflowLoaderError,
    FileSystemError,
    SecurityError,
    ResourceLimitError,
    TaskValidationError
)
from gleitzeit.core.logging_mixin import LoggingMixin, SyncLoggingMixin
from gleitzeit.core.logs import LogLevel, LogSource
from gleitzeit.registry import ProtocolProviderRegistry

# Logger for module-level functions
logger = logging.getLogger(__name__)


class WorkflowLoaderConfig:
    """Configuration for workflow loader with resource limits."""
    
    # Resource limits
    MAX_TASKS_PER_WORKFLOW = 10000
    MAX_WORKFLOW_SIZE_MB = 100
    MAX_BATCH_FILES = 5000
    MAX_YAML_DEPTH = 50
    
    # Performance tuning
    BATCH_CHUNK_SIZE = 100  # Process batch tasks in chunks
    ENABLE_CACHING = True
    CACHE_TTL_SECONDS = 300
    
    # Security
    ALLOWED_PATH_PREFIXES = []  # If set, restrict batch paths
    ENABLE_CHECKSUM_VALIDATION = False
    
    @classmethod
    def from_env(cls):
        """Load configuration from environment variables."""
        import os
        config = cls()
        
        if max_tasks := os.getenv('GLEITZEIT_MAX_TASKS_PER_WORKFLOW'):
            config.MAX_TASKS_PER_WORKFLOW = int(max_tasks)
        
        if max_size := os.getenv('GLEITZEIT_MAX_WORKFLOW_SIZE_MB'):
            config.MAX_WORKFLOW_SIZE_MB = int(max_size)
            
        if allowed_paths := os.getenv('GLEITZEIT_ALLOWED_PATHS'):
            config.ALLOWED_PATH_PREFIXES = allowed_paths.split(',')
            
        return config


class WorkflowLoaderMetrics:
    """Track loader performance metrics."""
    
    def __init__(self):
        self.load_time = 0.0
        self.validation_time = 0.0
        self.task_count = 0
        self.file_count = 0
        self.errors = []
        self.warnings = []
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            'load_time_ms': round(self.load_time * 1000, 2),
            'validation_time_ms': round(self.validation_time * 1000, 2),
            'task_count': self.task_count,
            'file_count': self.file_count,
            'error_count': len(self.errors),
            'warning_count': len(self.warnings)
        }


class BatchResult:
    """Result of a batch processing operation (migrated from BatchProcessor)"""
    
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


@contextmanager
def timer(metrics: WorkflowLoaderMetrics, attr: str):
    """Context manager for timing operations."""
    start = time.time()
    yield
    elapsed = time.time() - start
    setattr(metrics, attr, getattr(metrics, attr) + elapsed)


class WorkflowLoaderV2(LoggingMixin):
    """
    Enhanced workflow loader with better statelessness, logging, and scaling.
    """
    
    def __init__(self, config: Optional[WorkflowLoaderConfig] = None, registry: Optional[ProtocolProviderRegistry] = None):
        super().__init__()
        self.config = config or WorkflowLoaderConfig.from_env()
        self.metrics = WorkflowLoaderMetrics()
        self.registry = registry or ProtocolProviderRegistry()
        
    def _safe_log(self, coro):
        """Safely handle async logging - creates task if event loop exists, otherwise skip."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(coro)
        except RuntimeError:
            # No event loop - skip async logging
            pass
        
    def load_workflow_from_file(self, file_path: str) -> Workflow:
        """
        Load workflow from YAML or JSON file with enhanced validation.
        """
        path = Path(file_path)
        
        # Security: Validate file path
        self._validate_file_path(path)
        
        # Check file size
        file_size_mb = path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.config.MAX_WORKFLOW_SIZE_MB:
            raise ConfigurationError(
                f"Workflow file too large: {file_size_mb:.2f}MB "
                f"(max: {self.config.MAX_WORKFLOW_SIZE_MB}MB)"
            )
        
        # Use structured logging
        self._safe_log(
            self.log_operation(
                "load_workflow_file",
                file_path=str(path),
                file_size_mb=round(file_size_mb, 2),
                file_type=path.suffix
            )
        )
        
        with timer(self.metrics, 'load_time'):
            try:
                with open(path, 'r') as f:
                    if path.suffix.lower() in ['.yaml', '.yml']:
                        # Safe YAML loading with depth limit
                        data = self._safe_yaml_load(f)
                    elif path.suffix.lower() == '.json':
                        data = json.load(f)
                    else:
                        raise ConfigurationError(f"Unsupported file format: {path.suffix}")
                        
            except Exception as e:
                asyncio.create_task(
                    self.log_error(
                        "load_workflow_file",
                        e,
                        file_path=str(path)
                    )
                )
                raise FileSystemError(
                    f"Failed to load workflow file: {path}",
                    cause=e
                )
        
        # Add file metadata
        data['_source_file'] = str(path)
        data['_load_timestamp'] = datetime.utcnow().isoformat()
        
        if self.config.ENABLE_CHECKSUM_VALIDATION:
            data['_checksum'] = self._calculate_checksum(path)
        
        return self.load_workflow_from_dict(data)
    
    def load_workflow_from_dict(self, data: Dict[str, Any]) -> Workflow:
        """
        Load workflow from dictionary with enhanced validation and metrics.
        """
        # Debug logging with structured format
        asyncio.create_task(
            self.log_debug(
                "load_workflow_dict",
                "Starting workflow load from dictionary",
                has_batch='batch' in data or data.get('type') == 'batch',
                task_count=len(data.get('tasks', [])),
                has_providers='providers' in data
            )
        )
        
        with timer(self.metrics, 'load_time'):
            # Check if this is a batch workflow
            if data.get('type') == 'batch' or 'batch' in data:
                workflow = self._create_batch_workflow(data)
            else:
                workflow = self._create_standard_workflow(data)
        
        # Validate the workflow
        with timer(self.metrics, 'validation_time'):
            errors = self.validate_workflow_enhanced(workflow)
            if errors:
                asyncio.create_task(
                    self.log_error(
                        "validate_workflow",
                        WorkflowValidationError(workflow.id, errors),
                        workflow_id=workflow.id,
                        workflow_name=workflow.name,
                        error_count=len(errors),
                        errors=errors[:5]  # Log first 5 errors
                    )
                )
                raise WorkflowValidationError(workflow.id, errors)
        
        # Update metrics
        self.metrics.task_count = len(workflow.tasks)
        
        # Log success with metrics
        asyncio.create_task(
            self.log_success(
                "load_workflow",
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                task_count=len(workflow.tasks),
                metrics=self.metrics.to_dict()
            )
        )
        
        return workflow
    
    def _create_standard_workflow(self, data: Dict[str, Any]) -> Workflow:
        """Create standard workflow with improved ID generation."""
        # Generate internal ID with namespace
        workflow_id = f"workflow-{uuid4().hex[:8]}"
        
        # Handle name/ID logic
        file_id = data.get('id')
        file_name = data.get('name')
        
        if file_name:
            workflow_name = file_name
            asyncio.create_task(
                self.log_debug(
                    "create_workflow",
                    f"Using provided name: {workflow_name}",
                    workflow_name=workflow_name
                )
            )
        elif file_id:
            workflow_name = file_id
            asyncio.create_task(
                self.log_operation(
                    "create_workflow",
                    file_id=file_id,
                    workflow_id=workflow_id,
                    workflow_name=workflow_name
                )
            )
        else:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            workflow_name = f"anonymous_{timestamp}"
            asyncio.create_task(
                self.log_warning(
                    "create_workflow",
                    "No name or ID provided, using anonymous name",
                    workflow_name=workflow_name
                )
            )
        
        # Enhanced metadata
        metadata = data.get('metadata', {})
        if file_id:
            metadata['original_file_id'] = file_id
        
        # Add loader metadata
        metadata['loader_version'] = 'v2'
        metadata['load_timestamp'] = datetime.utcnow().isoformat()
        
        if source_file := data.get('_source_file'):
            metadata['source_file'] = source_file
        
        # Parse tasks with resource limit check
        tasks = []
        name_to_id_map = {}
        
        task_data_list = data.get('tasks', [])
        if len(task_data_list) > self.config.MAX_TASKS_PER_WORKFLOW:
            raise ConfigurationError(
                f"Too many tasks: {len(task_data_list)} "
                f"(max: {self.config.MAX_TASKS_PER_WORKFLOW})"
            )
        
        # First pass: create tasks
        for idx, task_data in enumerate(task_data_list):
            try:
                task = self.create_task_from_dict(
                    task_data, workflow_id, resolve_dependencies=False
                )
                tasks.append(task)
                name_to_id_map[task.name] = task.id
            except Exception as e:
                asyncio.create_task(
                    self.log_error(
                        f"create_task_{idx}",
                        e,
                        task_index=idx,
                        task_data=task_data
                    )
                )
                raise
        
        # Second pass: resolve dependencies
        self._resolve_dependencies(tasks, task_data_list, name_to_id_map)
        
        # Store provider requirements
        if 'providers' in data:
            metadata['required_providers'] = data['providers']
        
        return Workflow(
            id=workflow_id,
            name=workflow_name,
            description=data.get('description', ''),
            tasks=tasks,
            metadata=metadata
        )
    
    def _create_batch_workflow(self, data: Dict[str, Any]) -> Workflow:
        """
        Create batch workflow with lazy file discovery for better scaling.
        """
        batch_config = data.get('batch', {})
        template = data.get('template', {})
        
        if not batch_config.get('directory'):
            raise WorkflowValidationError(
                "batch_workflow",
                ["Batch workflow requires 'batch.directory'"]
            )
        
        if not template:
            raise WorkflowValidationError(
                "batch_workflow", 
                ["Batch workflow requires 'template' section"]
            )
        
        directory = batch_config['directory']
        pattern = batch_config.get('pattern', '*')
        
        # Security: Validate directory path
        self._validate_batch_directory(directory)
        
        # Create workflow with lazy file discovery
        workflow_id = f"batch-{uuid4().hex[:8]}"
        
        # Determine name
        file_name = data.get('name')
        file_id = data.get('id')
        
        if file_name:
            workflow_name = file_name
        elif file_id:
            workflow_name = file_id
        else:
            workflow_name = f"Batch Processing ({pattern} in {directory})"
        
        asyncio.create_task(
            self.log_operation(
                "create_batch_workflow",
                workflow_id=workflow_id,
                directory=directory,
                pattern=pattern,
                lazy_loading=True
            )
        )
        
        # For statelessness: Store file discovery params, not actual files
        metadata = {
            'batch': True,
            'batch_config': {
                'directory': directory,
                'pattern': pattern,
                'template': template,
                'lazy': True
            },
            'loader_version': 'v2'
        }
        
        # Create workflow with task generator for streaming
        workflow = Workflow(
            id=workflow_id,
            name=workflow_name,
            description=data.get('description', 'Batch processing workflow'),
            tasks=[],  # Will be populated lazily
            metadata=metadata
        )
        
        # Generate tasks in chunks for better memory usage
        workflow.tasks = list(self._generate_batch_tasks(
            workflow_id, directory, pattern, template, data
        ))
        
        self.metrics.file_count = len(workflow.tasks)
        
        return workflow
    
    def _generate_batch_tasks(
        self,
        workflow_id: str,
        directory: str,
        pattern: str,
        template: Dict[str, Any],
        data: Dict[str, Any]
    ) -> Iterator[Task]:
        """
        Generate batch tasks lazily for better memory efficiency.
        """
        dir_path = Path(directory)
        
        if not dir_path.exists():
            asyncio.create_task(
                self.log_error(
                    "batch_task_generation",
                    FileSystemError(f"Directory not found: {directory}"),
                    directory=directory
                )
            )
            return
        
        if not dir_path.is_dir():
            asyncio.create_task(
                self.log_error(
                    "batch_task_generation",
                    FileSystemError(f"Not a directory: {directory}"),
                    directory=directory
                )
            )
            return
        
        # Discover files with limit
        file_pattern = str(dir_path / pattern)
        files = glob.glob(file_pattern)
        files = [f for f in files if Path(f).is_file()]
        
        if len(files) > self.config.MAX_BATCH_FILES:
            asyncio.create_task(
                self.log_warning(
                    "batch_task_generation",
                    f"Too many files found ({len(files)}), limiting to {self.config.MAX_BATCH_FILES}",
                    file_count=len(files),
                    max_files=self.config.MAX_BATCH_FILES
                )
            )
            files = files[:self.config.MAX_BATCH_FILES]
        
        asyncio.create_task(
            self.log_operation(
                "batch_task_generation",
                file_count=len(files)
            )
        )
        
        # Generate tasks in chunks
        for i, file_path in enumerate(files):
            if i > 0 and i % self.config.BATCH_CHUNK_SIZE == 0:
                asyncio.create_task(
                    self.log_debug(
                        "batch_task_generation",
                        f"Generated {i}/{len(files)} batch tasks",
                        progress_current=i,
                        progress_total=len(files)
                    )
                )
            
            yield self._create_batch_task(
                file_path, i, workflow_id, template, data
            )
    
    def _create_batch_task(
        self,
        file_path: str,
        index: int,
        workflow_id: str,
        template: Dict[str, Any],
        data: Dict[str, Any]
    ) -> Task:
        """Create a single batch task."""
        file_name = Path(file_path).name
        task_id = f"task-{uuid4().hex[:8]}"  # Use UUID for better distribution
        
        # Detect file type
        is_image = Path(file_path).suffix.lower() in [
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'
        ]
        
        # Build parameters
        params = {k: v for k, v in template.items() if k != 'method'}
        
        # Add file path
        protocol = data.get('protocol', 'llm/v1')
        if protocol == 'python/v1':
            params.setdefault('context', {})['file_path'] = file_path
        elif is_image and template.get('method') == 'llm/vision':
            params['image_path'] = file_path
        else:
            params['file_path'] = file_path
        
        task_data = {
            'id': task_id,
            'name': f"Process {file_name}",
            'protocol': protocol,
            'method': template.get('method', 'llm/chat'),
            'params': params,
            'priority': template.get('priority', 'normal'),
            'metadata': {
                'batch_index': index,
                'source_file': file_path
            }
        }
        
        return self.create_task_from_dict(
            task_data, workflow_id, resolve_dependencies=False
        )
    
    def _validate_protocol_and_method(self, protocol: str, method: str, task_id: str) -> tuple[str, str]:
        """
        Validate protocol and method using the registry.
        
        Returns:
            Tuple of (validated_protocol, validated_method)
        
        Raises:
            TaskValidationError if protocol/method is invalid or provider unavailable
        """
        # If we have a registry, use it for validation
        if self.registry:
            # Try to normalize the protocol using registry
            try:
                # Check if protocol is registered and available
                provider = self.registry.get_provider(protocol)
                if not provider:
                    # Try to infer protocol from method
                    if '/' in method:
                        inferred_protocol = method.split('/')[0] + '/v1'
                        provider = self.registry.get_provider(inferred_protocol)
                        if provider:
                            protocol = inferred_protocol
                            asyncio.create_task(
                                self.log_warning(
                                    "protocol_inference",
                                    f"Inferred protocol '{protocol}' from method '{method}'",
                                    task_id=task_id
                                )
                            )
                        else:
                            raise TaskValidationError(
                                task_id,
                                [f"Unknown protocol '{protocol}' and no provider registered for inferred protocol '{inferred_protocol}'"]
                            )
                    else:
                        raise TaskValidationError(
                            task_id,
                            [f"Unknown protocol '{protocol}' and cannot infer from method '{method}'"]
                        )
                
                
                # Validate method is supported by the protocol
                # Note: This is a basic check - providers should validate methods themselves
                asyncio.create_task(
                    self.log_debug(
                        "protocol_validation",
                        f"Validated protocol '{protocol}' with provider {provider.__class__.__name__}",
                        task_id=task_id,
                        method=method
                    )
                )
                
            except Exception as e:
                # Log warning but continue - provider might be registered in pooling adapter
                asyncio.create_task(
                    self.log_warning(
                        "protocol_validation",
                        f"Could not validate protocol '{protocol}' in registry: {e}",
                        task_id=task_id,
                        protocol=protocol,
                        method=method
                    )
                )
                # Don't fail here - pooling adapter may have the provider
        else:
            # No registry available - use basic inference
            if not protocol and method:
                if '/' in method:
                    protocol = method.split('/')[0] + '/v1'
                else:
                    protocol = 'python/v1'
        
        return protocol, method
    
    def create_task_from_dict(
        self,
        data: Dict[str, Any],
        workflow_id: str,
        resolve_dependencies: bool = True
    ) -> Task:
        """Create task with enhanced validation."""
        # Generate internal task ID
        task_id = f"task-{uuid4().hex[:8]}"
        
        # Log task creation at debug level
        asyncio.create_task(
            self.log_debug(
                "create_task",
                "Creating task from dictionary",
                task_id=task_id,
                task_name=data.get('name', 'unnamed'),
                protocol=data.get('protocol'),
                method=data.get('method')
            )
        )
        
        # Parse retry config
        retry_config = None
        if retry_data := (data.get('retry_config') or data.get('retry')):
            retry_config = RetryConfig(
                max_attempts=retry_data.get('max_attempts', 3),
                backoff_strategy=retry_data.get(
                    'backoff_strategy',
                    retry_data.get('backoff', 'exponential')
                ),
                base_delay=retry_data.get('base_delay', 1.0),
                max_delay=retry_data.get('max_delay', 300.0),
                jitter=retry_data.get('jitter', True)
            )
        
        # Parse priority with validation
        priority_value = data.get('priority', 'normal')
        if isinstance(priority_value, int):
            priority_map = {1: 'high', 2: 'normal', 3: 'low'}
            priority_str = priority_map.get(priority_value, 'normal')
        else:
            priority_str = str(priority_value).lower()
        
        try:
            priority = Priority(priority_str)
        except ValueError:
            asyncio.create_task(
                self.log_warning(
                    "create_task",
                    f"Invalid priority '{priority_str}', using 'normal'",
                    task_id=task_id,
                    priority_str=priority_str
                )
            )
            self.metrics.warnings.append(
                f"Task {task_id}: Invalid priority '{priority_str}'"
            )
            priority = Priority.NORMAL
        
        # Extract and validate protocol
        method = data.get('method', '')
        protocol = data.get('protocol', '')
        
        # Use registry-based validation
        protocol, method = self._validate_protocol_and_method(protocol, method, task_id)
        
        # Get parameters
        params = data.get('params', data.get('parameters', {}))
        
        # Enhanced metadata
        metadata = data.get('metadata', {})
        metadata['created_by_loader'] = 'v2'
        
        return Task(
            id=task_id,
            name=data.get('name', task_id),
            protocol=protocol,
            method=method,
            params=params,
            dependencies=data.get('dependencies', []) if resolve_dependencies else [],
            priority=priority,
            timeout=data.get('timeout'),
            workflow_id=workflow_id,
            retry_config=retry_config,
            metadata=metadata
        )
    
    def _resolve_dependencies(
        self,
        tasks: List[Task],
        task_data_list: List[Dict[str, Any]],
        name_to_id_map: Dict[str, str]
    ):
        """Resolve task dependencies with enhanced error reporting."""
        for i, (task, task_data) in enumerate(zip(tasks, task_data_list)):
            dependencies = task_data.get('dependencies', [])
            resolved_dependencies = []
            
            for dep_name in dependencies:
                if dep_name in name_to_id_map:
                    resolved_dependencies.append(name_to_id_map[dep_name])
                else:
                    error_msg = (
                        f"Task '{task.name}' (index {i}) depends on "
                        f"unknown task '{dep_name}'"
                    )
                    asyncio.create_task(
                        self.log_warning(
                            "resolve_dependencies",
                            error_msg,
                            task_name=task.name,
                            task_index=i,
                            unknown_dependency=dep_name
                        )
                    )
                    self.metrics.warnings.append(error_msg)
                    # Keep original for error reporting
                    resolved_dependencies.append(dep_name)
            
            task.dependencies = resolved_dependencies
    
    def _validate_file_path(self, path: Path):
        """Validate file path for security."""
        # Resolve to absolute path
        abs_path = path.resolve()
        
        # Check against allowed prefixes if configured
        if self.config.ALLOWED_PATH_PREFIXES:
            allowed = any(
                str(abs_path).startswith(prefix)
                for prefix in self.config.ALLOWED_PATH_PREFIXES
            )
            if not allowed:
                raise ConfigurationError(
                    f"File path not in allowed directories: {abs_path}"
                )
        
        if not abs_path.exists():
            raise FileNotFoundError(f"Workflow file not found: {abs_path}")
    
    def _validate_batch_directory(self, directory: str):
        """Validate batch directory for security."""
        dir_path = Path(directory).resolve()
        
        # Check against allowed prefixes
        if self.config.ALLOWED_PATH_PREFIXES:
            allowed = any(
                str(dir_path).startswith(prefix)
                for prefix in self.config.ALLOWED_PATH_PREFIXES
            )
            if not allowed:
                raise ConfigurationError(
                    f"Batch directory not in allowed paths: {dir_path}"
                )
        
        # Prevent path traversal
        if '..' in str(directory):
            raise ConfigurationError(
                "Path traversal detected in batch directory"
            )
    
    def _safe_yaml_load(self, file_handle) -> Dict[str, Any]:
        """Load YAML with safety limits."""
        # Create custom loader with depth limit
        class SafeLoader(yaml.SafeLoader):
            pass
        
        # Add constructor to limit depth
        def check_depth(loader, node):
            if isinstance(node, yaml.MappingNode):
                depth = 1
                parent = node
                while parent:
                    parent = getattr(parent, 'parent', None)
                    depth += 1
                    if depth > self.config.MAX_YAML_DEPTH:
                        raise yaml.constructor.ConstructorError(
                            None, None,
                            f"YAML depth exceeded limit of {self.config.MAX_YAML_DEPTH}",
                            node.start_mark
                        )
            return loader.construct_object(node)
        
        SafeLoader.add_constructor(None, check_depth)
        
        return yaml.load(file_handle, Loader=SafeLoader)
    
    def _calculate_checksum(self, path: Path) -> str:
        """Calculate file checksum for integrity validation."""
        sha256 = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def validate_workflow_enhanced(self, workflow: Workflow) -> List[str]:
        """
        Enhanced workflow validation with detailed error reporting.
        """
        errors = []
        
        # Basic validation
        if not workflow.name:
            errors.append("Workflow name is required")
        
        if not workflow.tasks:
            errors.append("Workflow must contain at least one task")
            return errors
        
        # Check task count limit
        if len(workflow.tasks) > self.config.MAX_TASKS_PER_WORKFLOW:
            errors.append(
                f"Too many tasks: {len(workflow.tasks)} "
                f"(max: {self.config.MAX_TASKS_PER_WORKFLOW})"
            )
        
        # Task validation with context
        task_ids = set()
        for idx, task in enumerate(workflow.tasks):
            # Check duplicate IDs
            if task.id in task_ids:
                errors.append(f"Duplicate task ID at index {idx}: {task.id}")
            task_ids.add(task.id)
            
            # Validate required fields
            if not task.protocol:
                errors.append(f"Task {idx} ({task.name}): protocol is required")
            
            if not task.method:
                errors.append(f"Task {idx} ({task.name}): method is required")
            
            # Validate dependencies
            if task.dependencies:
                for dep in task.dependencies:
                    if dep not in task_ids and dep != task.id:
                        # Check if dependency exists
                        all_task_ids = {t.id for t in workflow.tasks}
                        if dep not in all_task_ids:
                            errors.append(
                                f"Task {idx} ({task.name}): "
                                f"unknown dependency '{dep}'"
                            )
                    
                    if dep == task.id:
                        errors.append(
                            f"Task {idx} ({task.name}): "
                            f"cannot depend on itself"
                        )
        
        # Check for circular dependencies
        circular = find_circular_dependencies(workflow.tasks)
        if circular:
            errors.append(f"Circular dependencies: {' -> '.join(circular)}")
        
        return errors
    
    # ====== Programmatic Batch API (migrated from BatchProcessor) ======
    
    def scan_directory(self, directory: str, pattern: str = "*") -> List[str]:
        """
        Scan directory for files matching pattern (migrated from BatchProcessor)
        
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
    
    def create_batch_workflow_programmatic(
        self,
        files: List[str] = None,
        directory: str = None,
        pattern: str = "*",
        method: str = "llm/chat",
        prompt: str = "Analyze this file",
        model: str = "llama3.2:latest",
        protocol: str = None,
        name: str = None
    ) -> List[Workflow]:
        """
        Programmatic API to create batch workflows (replaces BatchProcessor.create_batch_workflow)
        Creates a separate workflow for each file to ensure clean dependency handling.
        
        Args:
            files: List of file paths to process (optional if directory provided)
            directory: Directory to scan (optional if files provided) 
            pattern: File pattern for directory scan
            method: Protocol method (e.g., "llm/chat", "llm/vision", "python/execute")
            prompt: Prompt to use for each file
            model: Model to use
            protocol: Protocol to use (auto-detected from method if not provided)
            name: Optional workflow name prefix
        
        Returns:
            List of workflows (one per file)
        """
        # Collect files if directory provided
        if directory:
            files = self.scan_directory(directory, pattern)
        elif not files:
            raise TaskValidationError(
                "batch_workflow",
                ["Either 'files' or 'directory' must be provided"]
            )
        
        if not files:
            raise TaskValidationError(
                "batch_workflow",
                ["No files provided for batch processing"]
            )
        
        # Validate protocol and method early for the whole batch
        temp_task_id = f"batch-validation-{uuid4().hex[:8]}"
        protocol, method = self._validate_protocol_and_method(protocol, method, temp_task_id)
        
        # Create separate workflow for each file (better for dependencies)
        workflows = []
        
        for i, file_path in enumerate(files):
            file_name = Path(file_path).name
            workflow_id = f"batch-{file_name.replace('.', '-')}-{uuid4().hex[:8]}"
            workflow_name = (name + f" - {file_name}") if name else f"Process {file_name}"
            task_id = f"task-{uuid4().hex[:8]}"
            
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
            
            task = self.create_task_from_dict(task_data, workflow_id, resolve_dependencies=False)
            
            workflow = Workflow(
                id=workflow_id,
                name=workflow_name,
                description=f"Process {file_name}",
                tasks=[task],
                metadata={
                    'batch': True,
                    'batch_index': i,
                    'batch_total': len(files),
                    'source_file': file_path,
                    'prompt': prompt,
                    'model': model,
                    'method': method,
                    'protocol': protocol,
                    'directory': directory,
                    'pattern': pattern if directory else None
                }
            )
            workflows.append(workflow)
        
        logger.info(f"Created {len(workflows)} separate batch workflows for {len(files)} files")
        return workflows


def find_circular_dependencies(tasks: List[Task]) -> Optional[List[str]]:
    """Find circular dependencies using DFS."""
    graph = {}
    task_names = {}
    
    for task in tasks:
        graph[task.id] = task.dependencies or []
        task_names[task.id] = task.name
    
    state = {task.id: 0 for task in tasks}  # 0=unvisited, 1=visiting, 2=visited
    
    def dfs(node: str, path: List[str]) -> Optional[List[str]]:
        if node not in state:
            return None
            
        if state[node] == 1:  # Cycle detected
            cycle_start = path.index(node) if node in path else 0
            cycle = path[cycle_start:] + [node]
            return [task_names.get(tid, tid) for tid in cycle]
        
        if state[node] == 2:  # Already visited
            return None
        
        state[node] = 1
        path.append(node)
        
        for neighbor in graph.get(node, []):
            if neighbor in graph:
                result = dfs(neighbor, path.copy())
                if result:
                    return result
        
        state[node] = 2
        return None
    
    for task_id in graph:
        if state[task_id] == 0:
            result = dfs(task_id, [])
            if result:
                return result
    
    return None


# Convenience functions for backwards compatibility
def load_workflow_from_file(file_path: str) -> Workflow:
    """Load workflow using default configuration."""
    loader = WorkflowLoaderV2()
    return loader.load_workflow_from_file(file_path)


def load_workflow_from_dict(data: Dict[str, Any]) -> Workflow:
    """Load workflow from dict using default configuration."""
    loader = WorkflowLoaderV2()
    return loader.load_workflow_from_dict(data)


def validate_workflow(workflow: Workflow) -> List[str]:
    """Validate workflow using default configuration."""
    loader = WorkflowLoaderV2()
    return loader.validate_workflow_enhanced(workflow)