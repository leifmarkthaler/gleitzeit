"""
Enhanced Workflow Loader Worker for Gleitzeit 0.0.7

Reimplements WorkflowLoaderV2 functionality as a worker.
Properly structures tasks with protocol specifications for providers.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import yaml
import importlib.util
from pathlib import Path
import uuid

from .base import BaseWorker, WorkerConfig
from ..core.sharding import default_sharding
from ..core.errors import WorkflowValidationError, ConfigurationError, GleitzeitError, ResourceLimitError
from ..core.cache import get_workflow_cache
from ..core.file_operations import get_workflow_file_operations
from ..handlers import handler_loader

logger = logging.getLogger(__name__)


class WorkflowLoaderConfig:
    """Configuration for workflow loader with resource limits"""

    # Resource limits
    MAX_TASKS_PER_WORKFLOW = 10000
    MAX_WORKFLOW_SIZE_MB = 100
    MAX_YAML_DEPTH = 50

    # Security
    ALLOWED_PATH_PREFIXES = []  # If set, restrict batch paths

    @classmethod
    def from_env(cls):
        """Load configuration from environment variables"""
        import os
        config = cls()

        if max_tasks := os.getenv('GLEITZEIT_MAX_TASKS_PER_WORKFLOW'):
            config.MAX_TASKS_PER_WORKFLOW = int(max_tasks)

        if max_size := os.getenv('GLEITZEIT_MAX_WORKFLOW_SIZE_MB'):
            config.MAX_WORKFLOW_SIZE_MB = int(max_size)

        if allowed_paths := os.getenv('GLEITZEIT_ALLOWED_PATHS'):
            config.ALLOWED_PATH_PREFIXES = allowed_paths.split(',')

        return config


class WorkflowLoaderWorkerV2(BaseWorker):
    """
    Enhanced workflow loader worker with protocol-based task structuring.

    Reimplements WorkflowLoaderV2 features:
    - Proper protocol assignment for tasks
    - Security validation
    - Resource limits
    - Task transformation for providers
    """

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        # Use LRU cache for workflow caching
        cache_size = config.__dict__.get('workflow_cache_size', 1000)
        cache_ttl = config.__dict__.get('workflow_cache_ttl', 3600)  # 1 hour default
        self.workflow_cache = get_workflow_cache(max_size=cache_size, ttl=cache_ttl)
        self.loader_config = WorkflowLoaderConfig.from_env()

        # Use unified file operations with workflow context
        self.file_ops = get_workflow_file_operations()

        # Build protocol mappings from handler registry
        self._build_protocol_mappings()

        logger.info(f"Built protocol mappings from handler registry with {len(self.type_to_protocol)} task types")
        logger.debug(f"Protocol mappings: {self.type_to_protocol}")

    def _build_protocol_mappings(self):
        """Build protocol mappings from handler registry"""
        capabilities = handler_loader.get_all_capabilities()

        self.type_to_protocol = {}
        self.supported_methods = {}
        self.method_requirements = {}

        for protocol, caps in capabilities.items():
            # Map task types to protocols
            for task_type in caps.get('task_types', []):
                if task_type not in self.type_to_protocol:
                    self.type_to_protocol[task_type] = protocol

            # Track supported methods
            self.supported_methods[protocol] = list(caps.get('methods', {}).keys())

            # Track required params for each method
            for method_name, method_info in caps.get('methods', {}).items():
                if isinstance(method_info, dict):
                    self.method_requirements[method_name] = {
                        'required': method_info.get('required', []),
                        'optional': method_info.get('optional', [])
                    }

    async def on_initialize(self):
        """Initialize workflow loader resources"""
        logger.info(f"WorkflowLoaderWorkerV2 initialized with max tasks: {self.loader_config.MAX_TASKS_PER_WORKFLOW}")
        logger.info(f"Workflow cache configured: size={self.workflow_cache.max_size}, ttl={self.workflow_cache.default_ttl}s")

        # Log available handlers
        logger.info(f"Available protocols: {list(self.supported_methods.keys())}")
        for protocol, methods in self.supported_methods.items():
            logger.debug(f"  {protocol}: {', '.join(methods)}")

    def get_base_streams(self) -> List[str]:
        """Return streams this worker consumes from"""
        return ["workflow:load", "workflow:reload"]

    async def process_message(self, stream: str, message_id: str, data: Dict) -> bool:
        """Process workflow load request

        Returns:
            True if message was processed successfully
            False if message should be retried
        """
        workflow_path = data.get('path')
        workflow_id = data.get('workflow_id', self.generate_workflow_id())
        workflow_format = data.get('format')

        if not workflow_path and not data.get('workflow'):
            logger.error(f"Missing workflow path or inline workflow in message {message_id}")
            # Log validation error to Redis
            await self.log_worker_error(
                "process_message",
                ValueError("Missing workflow path or inline workflow in message"),
                stream=stream,
                message_id=message_id
            )
            return True  # Malformed message, ACK to remove

        logger.info(f"Loading workflow {workflow_id} from {workflow_path or 'inline'}")

        # Log INFO: Workflow loading started
        await self.log_worker_info(
            "workflow_loading_started",
            f"Starting to load workflow {workflow_id}",
            workflow_id=workflow_id,
            source=workflow_path or "inline",
            stream=stream
        )

        raw_workflow = None  # Initialize to handle failures
        try:
            # Load workflow based on source
            if data.get('workflow'):
                # Inline workflow provided
                raw_workflow = data.get('workflow')
                if isinstance(raw_workflow, str):
                    # Try to parse as JSON, otherwise treat as YAML
                    try:
                        raw_workflow = json.loads(raw_workflow)
                    except json.JSONDecodeError:
                        # Might be YAML string or invalid - let validation handle it
                        import yaml
                        try:
                            raw_workflow = yaml.safe_load(raw_workflow)
                        except yaml.YAMLError:
                            raise WorkflowValidationError(
                                workflow_id=workflow_id,
                                validation_errors=["Invalid workflow format: not valid JSON or YAML"]
                            )
            else:
                # Load from path with validation
                raw_workflow = await self.load_workflow_from_path(
                    workflow_path,
                    workflow_format
                )

            # Transform to protocol-based workflow
            logger.info(f"Raw workflow before transform: {json.dumps(raw_workflow, indent=2)}")
            workflow = await self.transform_workflow(raw_workflow, workflow_id)
            logger.info(f"Workflow after transform: {json.dumps(workflow, indent=2)}")

            # Validate workflow
            validation_errors = self.validate_workflow(workflow)
            if validation_errors:
                raise WorkflowValidationError(
                    workflow_id=workflow_id,
                    validation_errors=validation_errors
                )

            # Log DEBUG: Validation details
            await self.log_worker_debug(
                "workflow_validation_passed",
                f"Workflow {workflow_id} passed validation",
                workflow_id=workflow_id,
                task_count=len(workflow.get('tasks', [])),
                has_dependencies=any(t.get('dependencies') for t in workflow.get('tasks', []))
            )

            # Store workflow definition only (state is handled separately)
            await self.redis.hset(
                default_sharding.get_workflow_key("data", workflow_id).encode(),
                mapping={
                    b"workflow": json.dumps(workflow).encode()
                }
            )

            # Update consolidated state to loaded status
            now = datetime.utcnow().isoformat()
            await self.redis.hset(
                default_sharding.get_workflow_key("state", workflow_id).encode(),
                mapping={
                    b"status": b"loaded",
                    b"loaded_at": now.encode(),
                    b"name": workflow.get('name', 'unnamed').encode(),
                    b"description": workflow.get('description', '').encode(),
                    b"version": workflow.get('version', '1.0.0').encode()
                }
            )

            # Emit to workflow:submitted stream (sharded)
            shard = default_sharding.get_shard(workflow_id)
            await self.redis.xadd(
                default_sharding.get_stream_key("workflow:submitted", workflow_id).encode(),
                {
                    b"workflow_id": workflow_id.encode(),
                    b"workflow": json.dumps(workflow).encode(),
                    b"timestamp": datetime.utcnow().isoformat().encode()
                }
            )

            # Add workflow to global shard mapping index
            await self.redis.hset(
                b"{shard:0}:index:workflow_shards",
                workflow_id.encode(),
                str(shard).encode()
            )

            # Add to per-shard workflow index for efficient listing
            await self.redis.sadd(
                f"{{shard:{shard}}}:index:workflows".encode(),
                workflow_id.encode()
            )

            # Store task to workflow mappings for direct task lookups
            for task in workflow.get('tasks', []):
                task_id = task.get('id')
                if task_id:
                    await self.redis.hset(
                        b"{shard:0}:index:task_workflow",
                        task_id.encode(),
                        workflow_id.encode()
                    )

            # Log WARNING: Large workflows
            task_count = len(workflow.get('tasks', []))
            if task_count > 100:
                await self.log_worker_warning(
                    "large_workflow_detected",
                    f"Workflow {workflow_id} has {task_count} tasks (>100)",
                    workflow_id=workflow_id,
                    task_count=task_count
                )

            # Log WARNING: Complex dependency graphs
            total_dependencies = sum(len(t.get('dependencies', [])) for t in workflow.get('tasks', []))
            avg_dependencies = total_dependencies / task_count if task_count > 0 else 0
            if avg_dependencies > 3:
                await self.log_worker_warning(
                    "complex_dependency_graph",
                    f"Workflow {workflow_id} has complex dependencies (avg {avg_dependencies:.1f} per task)",
                    workflow_id=workflow_id,
                    task_count=task_count,
                    total_dependencies=total_dependencies,
                    avg_dependencies=avg_dependencies
                )

            # Log INFO: Workflow loaded successfully
            await self.log_worker_info(
                "workflow_loaded_successfully",
                f"Workflow {workflow_id} loaded with {task_count} tasks",
                workflow_id=workflow_id,
                task_count=task_count,
                shard=shard,
                workflow_name=workflow.get('name', 'unnamed')
            )

            logger.info(f"Workflow {workflow_id} loaded and submitted to shard {shard} with indexes")
            return True  # Successfully processed

        except (WorkflowValidationError, ConfigurationError, ResourceLimitError) as e:
            # Validation/configuration/resource limit errors are unretryable
            logger.error(f"Workflow validation/configuration/resource limit failed: {e}")
            # Log to Redis for queryability
            await self.log_worker_error(
                "process_message",
                e,
                workflow_id=workflow_id,
                workflow_path=workflow_path,
                stream=stream,
                message_id=message_id
            )

            # Extract safe basic metadata from raw workflow (if available)
            workflow_name = "unnamed"
            workflow_description = ""
            if raw_workflow and isinstance(raw_workflow, dict):
                # Safely extract name and description
                workflow_name = str(raw_workflow.get('name', 'unnamed'))[:255]  # Limit length
                workflow_description = str(raw_workflow.get('description', ''))[:1000]  # Limit length

            # Save to consolidated state for failed validation
            await self.redis.hset(
                default_sharding.get_workflow_key("state", workflow_id).encode(),
                mapping={
                    b"workflow_id": workflow_id.encode(),
                    b"status": b"validation_failed",
                    b"name": workflow_name.encode(),
                    b"description": workflow_description.encode(),
                    b"error": str(e).encode(),
                    b"failed_at": datetime.utcnow().isoformat().encode(),
                    b"submitted_at": data.get('submitted_at', datetime.utcnow().isoformat()).encode(),
                    b"total_tasks": b"0",
                    b"completed_tasks": b"0"
                }
            )

            # Emit failure event
            await self.redis.xadd(
                default_sharding.get_global_key("workflow:load:failed").encode(),
                {
                    b"workflow_id": workflow_id.encode(),
                    b"path": (workflow_path or "").encode(),
                    b"error": str(e).encode(),
                    b"error_type": b"validation",
                    b"timestamp": datetime.utcnow().isoformat().encode()
                }
            )
            return True  # Don't retry validation errors

        except Exception as e:
            # Other errors might be retryable (network issues, etc.)
            logger.error(f"Failed to load workflow: {e}", exc_info=True)
            # Log to Redis for queryability
            await self.log_worker_error(
                "process_message",
                e,
                workflow_id=workflow_id,
                workflow_path=workflow_path,
                stream=stream,
                message_id=message_id
            )

            # Emit failure event
            await self.redis.xadd(
                default_sharding.get_global_key("workflow:load:failed").encode(),
                {
                    b"workflow_id": workflow_id.encode(),
                    b"path": (workflow_path or "").encode(),
                    b"error": str(e).encode(),
                    b"error_type": b"runtime",
                    b"timestamp": datetime.utcnow().isoformat().encode()
                }
            )
            return False  # Retry on runtime exceptions

    async def load_workflow_from_path(
        self,
        path: str,
        format: Optional[str] = None
    ) -> Dict:
        """Load workflow from file path using unified file operations"""
        try:
            # Use unified file operations for loading and validation
            file_result = await self.file_ops.load_file(
                path=path,
                encoding='utf-8',
                validate=True  # This handles security and size validation
            )

            content = file_result['content']
            file_path = Path(path)

            # Detect format if not specified
            if not format:
                if path.endswith('.yaml') or path.endswith('.yml'):
                    format = 'yaml'
                elif path.endswith('.json'):
                    format = 'json'
                elif path.endswith('.py'):
                    format = 'python'
                else:
                    format = 'yaml'

            # Parse based on format
            if format == 'yaml':
                return yaml.safe_load(content)
            elif format == 'json':
                return json.loads(content)
            elif format == 'python':
                return await self.load_python_workflow(path)
            else:
                raise ValueError(f"Unsupported workflow format: {format}")

        except GleitzeitError:
            # Re-raise Gleitzeit errors as-is (already properly formatted)
            raise
        except Exception as e:
            # Convert other errors to ConfigurationError for backward compatibility
            raise ConfigurationError(f"Failed to load workflow from {path}: {str(e)}")


    async def load_python_workflow(self, path: str) -> Dict:
        """Load workflow from Python file"""
        spec = importlib.util.spec_from_file_location("workflow", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Look for workflow definition
        if hasattr(module, 'workflow'):
            return module.workflow
        elif hasattr(module, 'get_workflow'):
            return module.get_workflow()
        else:
            raise ValueError(f"No workflow found in Python file: {path}")

    async def transform_workflow(self, raw_workflow: Dict, workflow_id: str) -> Dict:
        """Transform raw workflow into protocol-based format"""
        # If the workflow is nested under a 'workflow' key (common in YAML files), extract it
        if 'workflow' in raw_workflow and isinstance(raw_workflow['workflow'], dict):
            raw_workflow = raw_workflow['workflow']

        workflow = {
            'id': workflow_id,
            'name': raw_workflow.get('name', 'unnamed'),
            'description': raw_workflow.get('description', ''),
            'version': raw_workflow.get('version', '1.0.0'),
            'created_at': datetime.utcnow().isoformat(),
            'tasks': []
        }

        # Transform each task
        raw_tasks = raw_workflow.get('tasks', [])

        if len(raw_tasks) > self.loader_config.MAX_TASKS_PER_WORKFLOW:
            raise ResourceLimitError(
                resource_type="workflow_tasks",
                current_value=len(raw_tasks),
                limit=self.loader_config.MAX_TASKS_PER_WORKFLOW
            )

        # First pass: transform tasks and build name-to-ID mapping
        name_to_id_map = {}
        transformed_tasks = []

        for raw_task in raw_tasks:
            task = await self.transform_task(raw_task, workflow_id)
            transformed_tasks.append(task)
            # Map task id/name to generated ID
            task_identifier = raw_task.get('id') or raw_task.get('name')
            if task_identifier:
                name_to_id_map[task_identifier] = task['id']

        # Second pass: update dependencies to use IDs instead of names
        for task in transformed_tasks:
            if task.get('dependencies'):
                updated_deps = []
                for dep in task['dependencies']:
                    # If dependency is a name, map it to ID; otherwise keep as is
                    dep_id = name_to_id_map.get(dep, dep)
                    updated_deps.append(dep_id)
                task['dependencies'] = updated_deps
            workflow['tasks'].append(task)

        return workflow

    async def transform_task(self, raw_task: Dict, workflow_id: str) -> Dict:
        """Transform raw task into protocol-based format"""
        # Always generate a new ID - don't use any ID from the file
        task_id = str(uuid.uuid4())
        task_type = raw_task.get('type', 'python')

        # Get protocol for task type
        if 'protocol' in raw_task:
            protocol = raw_task['protocol']
        elif task_type in self.type_to_protocol:
            protocol = self.type_to_protocol[task_type]
        else:
            # Unknown task type - create a placeholder protocol that will fail validation
            protocol = f"{task_type}/unknown"
            logger.warning(f"Unknown task type '{task_type}' in task '{task_id}', using placeholder protocol '{protocol}'")

        # Create protocol-based task structure
        task = {
            'id': task_id,
            'workflow_id': workflow_id,
            'name': raw_task.get('name', task_id),
            'description': raw_task.get('description', ''),
            'protocol': protocol,
            'method': self._get_method_for_task(raw_task, task_type),
            'params': self._get_params_for_task(raw_task, task_type),
            'dependencies': raw_task.get('depends_on', raw_task.get('dependencies', [])),
            'timeout': raw_task.get('timeout', 300),  # 5 minutes default
            'retry': self._create_retry_config(raw_task.get('retry', {}))
        }

        return task

    def _create_retry_config(self, retry_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Create proper retry configuration with exponential backoff."""
        # Map workflow retry configuration to format used by StatelessRetryService
        strategy = retry_dict.get('backoff', 'exponential_jitter')
        if strategy == 'exponential':
            strategy = 'exponential_jitter'  # Use jitter by default
        elif strategy == 'linear':
            strategy = 'linear'
        elif strategy == 'fixed':
            strategy = 'fixed'
        else:
            strategy = 'exponential_jitter'

        return {
            'max_retries': retry_dict.get('max_attempts', 3) - 1 if 'max_attempts' in retry_dict else retry_dict.get('max_retries', 2),  # Default to 2 retries (3 attempts total)
            'strategy': strategy,
            'base_delay': retry_dict.get('delay', 1.0),
            'max_delay': retry_dict.get('max_delay', 30.0),
            'jitter': retry_dict.get('jitter', True),
            'multiplier': retry_dict.get('multiplier', 2.0)
        }

    def _get_method_for_task(self, raw_task: Dict, task_type: str) -> str:
        """Get the JSON-RPC method for a task"""
        if 'method' in raw_task:
            return raw_task['method']

        # Get protocol for this task type
        protocol = self.type_to_protocol.get(task_type)
        if not protocol:
            # Unknown task type - will be caught in validation
            return f"{task_type}/execute"

        # Special handling for signal tasks based on signal_action
        if task_type == 'signal':
            signal_action = raw_task.get('signal_action', 'wait')
            if signal_action == 'wait':
                return 'signal/wait'
            elif signal_action == 'wait_any':
                return 'signal/wait_any'
            elif signal_action == 'wait_all':
                return 'signal/wait_all'
            elif signal_action == 'send':
                return 'signal/send'
            elif signal_action == 'broadcast':
                return 'signal/broadcast'
            else:
                return 'signal/wait'

        # Get first available method for the protocol as default
        if protocol in self.supported_methods:
            methods = self.supported_methods[protocol]
            if methods:
                # Try to pick the most appropriate default method
                # Prefer 'execute' or 'sleep' methods as defaults
                for preferred in ['execute', 'sleep', 'wait', 'run', 'call']:
                    for method in methods:
                        if preferred in method:
                            return method
                # If no preferred method found, return first available
                return methods[0]

        # Fallback - construct a method name from protocol
        protocol_base = protocol.split('/')[0]
        return f"{protocol_base}/execute"

    def _get_params_for_task(self, raw_task: Dict, task_type: str) -> Dict:
        """Get the parameters for a task - just pass through as-is"""
        # Simply return params as provided - no transformation
        # The handler is responsible for validating its own params
        return raw_task.get('params', {})

    def validate_workflow(self, workflow: Dict) -> List[str]:
        """
        Validate workflow structure and task parameters.
        """
        errors = []

        # Check required fields
        if not workflow.get('name'):
            errors.append("Workflow must have a 'name' field")

        # Validate tasks
        tasks = workflow.get('tasks', [])
        if not tasks:
            errors.append("Workflow must have at least one task")
            return errors

        task_ids = set()
        for idx, task in enumerate(tasks):
            task_id = task.get('id')
            if not task_id:
                errors.append(f"Task at index {idx} must have an 'id' field")
                continue

            if task_id in task_ids:
                errors.append(f"Duplicate task ID: {task_id}")
            else:
                task_ids.add(task_id)

            # Validate task type/protocol
            task_type = task.get('type')
            protocol = task.get('protocol')

            if task_type:
                # Map type to protocol
                protocol = self.type_to_protocol.get(task_type)
                if not protocol:
                    errors.append(f"Task {task_id}: unsupported type '{task_type}'")
            elif not protocol:
                errors.append(f"Task {task_id} must have either 'type' or 'protocol' field")

            # Validate method and required parameters
            method = task.get('method')
            if method and method in self.method_requirements:
                params = task.get('params', {})
                required_params = self.method_requirements[method].get('required', [])

                for param in required_params:
                    if param not in params:
                        errors.append(f"Task {task_id}: missing required parameter '{param}' for method '{method}'")

        # Validate dependencies reference existing tasks
        for task in tasks:
            task_id = task.get('id')
            if not task_id:
                continue  # Already reported as error in first loop

            dependencies = task.get('dependencies', [])
            for dep in dependencies:
                if dep not in task_ids:
                    errors.append(f"Task {task_id} has unknown dependency: {dep}")

        return errors

    def generate_workflow_id(self) -> str:
        """Generate unique workflow ID"""
        return f"workflow_{uuid.uuid4().hex[:12]}"