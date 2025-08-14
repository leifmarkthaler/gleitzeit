"""
Command Line Interface for Gleitzeit V4

Provides user-friendly commands for task submission, workflow management,
provider registration, and system monitoring.
"""

import asyncio
import click
import json
import yaml
import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from core.models import (
    Task, Workflow, Priority, RetryConfig
)
from core.execution_engine import ExecutionEngine, ExecutionMode
from core.workflow_manager import WorkflowManager, WorkflowExecutionPolicy
from registry import ProtocolProviderRegistry
from task_queue.task_queue import QueueManager
from task_queue.dependency_resolver import DependencyResolver

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class GleitzeitV4CLI:
    """Main CLI application for Gleitzeit V4"""
    
    def __init__(self):
        self.registry: Optional[ProtocolProviderRegistry] = None
        self.queue_manager: Optional[QueueManager] = None
        self.dependency_resolver: Optional[DependencyResolver] = None
        self.execution_engine: Optional[ExecutionEngine] = None
        self.workflow_manager: Optional[WorkflowManager] = None
        self.config_file = Path.home() / ".gleitzeit" / "v4_config.json"
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    return json.load(f)
            except Exception as e:
                click.echo(f"Warning: Failed to load config: {e}")
        
        # Default configuration
        return {
            "max_concurrent_tasks": 10,
            "queue_names": ["default"],
            "template_directory": str(Path.home() / ".gleitzeit" / "templates"),
            "log_level": "INFO",
            "persistence_backend": "none",  # Options: "redis", "sqlite", "none"
            "redis_url": "redis://localhost:6379/0",
            "sqlite_path": str(Path.home() / ".gleitzeit" / "gleitzeit.db")
        }
    
    def _save_config(self) -> None:
        """Save configuration to file"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            click.echo(f"Warning: Failed to save config: {e}")
    
    async def _initialize_components(self) -> None:
        """Initialize all system components"""
        if self.registry is None:
            self.registry = ProtocolProviderRegistry()
            self.queue_manager = QueueManager()
            self.dependency_resolver = DependencyResolver()
            
            # Initialize persistence backend if configured
            persistence = await self._initialize_persistence()
            
            self.execution_engine = ExecutionEngine(
                registry=self.registry,
                queue_manager=self.queue_manager,
                dependency_resolver=self.dependency_resolver,
                max_concurrent_tasks=self.config["max_concurrent_tasks"],
                persistence=persistence
            )
            self.workflow_manager = WorkflowManager(
                execution_engine=self.execution_engine,
                dependency_resolver=self.dependency_resolver,
                template_directory=Path(self.config["template_directory"])
            )
            
            # Load workflow templates
            self.workflow_manager.load_templates_from_directory()
            
            # Register protocols and providers
            await self._register_protocols_and_providers()
    
    async def _initialize_persistence(self):
        """Initialize persistence backend based on configuration"""
        backend_type = self.config.get("persistence_backend", "none")
        
        if backend_type == "redis":
            try:
                from persistence.redis_backend import RedisBackend
                # Parse Redis URL or use defaults
                redis_url = self.config.get("redis_url", "redis://localhost:6379/0")
                # For now, use default connection parameters
                redis_backend = RedisBackend()
                await redis_backend.initialize()
                logger.info(f"✅ Redis persistence backend initialized: {redis_url}")
                return redis_backend
            except Exception as e:
                logger.warning(f"Failed to initialize Redis backend: {e}")
                logger.info("Falling back to in-memory persistence")
        
        elif backend_type == "sqlite":
            try:
                from persistence.sqlite_backend import SQLiteBackend
                sqlite_backend = SQLiteBackend(db_path=self.config["sqlite_path"])
                await sqlite_backend.initialize()
                logger.info(f"✅ SQLite persistence backend initialized: {self.config['sqlite_path']}")
                return sqlite_backend
            except Exception as e:
                logger.warning(f"Failed to initialize SQLite backend: {e}")
                logger.info("Falling back to in-memory persistence")
        
        # Default to in-memory backend
        from persistence.base import InMemoryBackend
        in_memory_backend = InMemoryBackend()
        await in_memory_backend.initialize()
        if backend_type != "none":
            logger.info("✅ In-memory persistence backend initialized (fallback)")
        else:
            logger.info("✅ In-memory persistence backend initialized")
        return in_memory_backend
    
    async def _register_protocols_and_providers(self) -> None:
        """Register built-in protocols and providers"""
        try:
            # Register LLM protocol
            from protocols import LLM_PROTOCOL_V1
            self.registry.register_protocol(LLM_PROTOCOL_V1)
            
            # Register Ollama provider if available
            try:
                from providers.ollama_provider import OllamaProvider
                ollama_provider = OllamaProvider(provider_id="cli-ollama")
                await ollama_provider.initialize()
                self.registry.register_provider(
                    provider_id="cli-ollama",
                    protocol_id="llm/v1",
                    provider_instance=ollama_provider
                )
                logger.info("✅ Ollama provider registered successfully")
            except Exception as e:
                logger.warning(f"Ollama provider not available: {e}")
            
            # Register MCP protocol and provider if available
            try:
                from protocols.mcp_protocol import mcp_protocol
                self.registry.register_protocol(mcp_protocol)
                logger.info("✅ MCP protocol registered")
            except Exception as e:
                logger.warning(f"MCP protocol not available: {e}")
                
        except Exception as e:
            logger.warning(f"Error registering protocols/providers: {e}")


cli_app = GleitzeitV4CLI()


# Main CLI Group
@click.group(invoke_without_command=True)
@click.option('--config', help='Configuration file path')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
@click.pass_context
def cli(ctx, config, verbose):
    """Gleitzeit V4 - Protocol-Based Task Execution System"""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if config:
        cli_app.config_file = Path(config)
        cli_app.config = cli_app._load_config()
    
    if ctx.invoked_subcommand is None:
        click.echo("Gleitzeit V4 - Protocol-Based Task Execution System")
        click.echo("Use --help to see available commands")


# Task Management Commands
@cli.group()
def task():
    """Task management commands"""
    pass


@task.command()
@click.option('--protocol', required=True, help='Protocol identifier (e.g., web-search/v1)')
@click.option('--method', required=True, help='Method name')
@click.option('--params', default='{}', help='JSON parameters')
@click.option('--priority', type=click.Choice(['urgent', 'high', 'normal', 'low']), default='normal')
@click.option('--timeout', type=int, help='Task timeout in seconds')
@click.option('--depends-on', multiple=True, help='Task dependencies')
@click.option('--queue', default='default', help='Target queue')
@click.option('--wait', is_flag=True, help='Wait for task completion')
@click.option('--output-file', help='Save response to JSON file')
def submit(protocol, method, params, priority, timeout, depends_on, queue, wait, output_file):
    """Submit a single task for execution"""
    async def _submit_task():
        await cli_app._initialize_components()
        
        try:
            params_dict = json.loads(params)
        except json.JSONDecodeError:
            click.echo("Error: Invalid JSON in params", err=True)
            return
        
        task = Task(
            name=f"CLI Task {protocol}::{method}",  # Provide task name
            protocol=protocol,
            method=method,
            params=params_dict,
            priority=Priority(priority),
            dependencies=list(depends_on),
            timeout=timeout
        )
        
        click.echo(f"Submitting task {task.id}...")
        
        await cli_app.execution_engine.submit_task(task, queue)
        
        # Prepare response data
        response_data = {
            "submission_type": "task",
            "task_id": task.id,
            "task_name": task.name,
            "protocol": task.protocol,
            "method": task.method,
            "priority": task.priority,
            "queue": queue,
            "submitted_at": datetime.utcnow().isoformat(),
            "status": "submitted"
        }
        
        if wait or output_file:
            click.echo("Waiting for completion...")
            
            # Start execution engine if not running
            if not cli_app.execution_engine.running:
                await cli_app.execution_engine.start(ExecutionMode.SINGLE_SHOT)
            
            # Wait for result
            while task.id not in cli_app.execution_engine.task_results:
                await asyncio.sleep(0.5)
            
            result = cli_app.execution_engine.get_task_result(task.id)
            if result:
                # Handle status field (might be string from Redis or TaskStatus enum)
                status_str = result.status.value if hasattr(result.status, 'value') else str(result.status)
                click.echo(f"Task completed with status: {status_str}")
                
                # Update response data with results
                response_data.update({
                    "status": status_str,
                    "completed_at": result.completed_at.isoformat() if result.completed_at else None,
                    "execution_time": (result.completed_at - result.started_at).total_seconds() if result.completed_at and result.started_at else None,
                    "result": result.result,
                    "error": result.error
                })
                
                if result.result:
                    click.echo(f"Result: {json.dumps(result.result, indent=2)}")
                if result.error:
                    click.echo(f"Error: {result.error}", err=True)
        else:
            click.echo(f"Task {task.id} submitted successfully")
        
        # Save response to file if requested
        if output_file:
            try:
                with open(output_file, 'w') as f:
                    json.dump(response_data, f, indent=2, default=str)
                click.echo(f"Response saved to: {output_file}")
            except Exception as e:
                click.echo(f"Failed to save response file: {e}", err=True)
    
    asyncio.run(_submit_task())


@task.command()
@click.argument('task_id')
def status(task_id):
    """Get task status and result"""
    async def _get_status():
        await cli_app._initialize_components()
        
        result = cli_app.execution_engine.get_task_result(task_id)
        if result:
            click.echo(f"Task ID: {result.task_id}")
            click.echo(f"Status: {result.status.value}")
            click.echo(f"Started: {result.started_at}")
            click.echo(f"Completed: {result.completed_at}")
            
            if result.result:
                click.echo("Result:")
                click.echo(json.dumps(result.result, indent=2))
            
            if result.error:
                click.echo(f"Error: {result.error}")
        else:
            click.echo(f"Task {task_id} not found")
    
    asyncio.run(_get_status())


# Workflow Management Commands
@cli.group()
def workflow():
    """Workflow management commands"""
    pass


@workflow.command()
@click.argument('workflow_file', type=click.Path(exists=True))
@click.option('--params', default='{}', help='JSON parameters for workflow')
@click.option('--wait', is_flag=True, help='Wait for workflow completion')
@click.option('--output-file', help='Save response to JSON file')
def submit(workflow_file, params, wait, output_file):
    """Submit a workflow from JSON or YAML file"""
    async def _submit_workflow():
        await cli_app._initialize_components()
        
        try:
            # Load workflow file (support both JSON and YAML)
            workflow_path = Path(workflow_file)
            with open(workflow_path) as f:
                content = f.read()
            
            if workflow_path.suffix.lower() in ['.yaml', '.yml']:
                workflow_data = yaml.safe_load(content)
            else:
                workflow_data = json.loads(content)
            
            params_dict = json.loads(params)
        except (json.JSONDecodeError, yaml.YAMLError, FileNotFoundError) as e:
            click.echo(f"Error: {e}", err=True)
            return
        
        # Create workflow from data
        tasks = []
        for task_data in workflow_data.get("tasks", []):
            # Only set id if provided in YAML, otherwise let Task generate it
            # Support both 'params' and 'parameters' for backward compatibility
            task_params = task_data.get("params") or task_data.get("parameters", {})
            
            task_kwargs = {
                "name": task_data.get("name", f"Task {len(tasks) + 1}"),  # Provide default name
                "protocol": task_data["protocol"],
                "method": task_data["method"],
                "params": task_params,
                "dependencies": task_data.get("dependencies", []),
                "priority": Priority(task_data.get("priority", "normal"))
            }
            
            # Only add optional fields if they're provided
            if task_data.get("id"):
                task_kwargs["id"] = task_data["id"]
            if task_data.get("timeout"):
                task_kwargs["timeout"] = task_data["timeout"]
            
            task = Task(**task_kwargs)
            tasks.append(task)
        
        workflow = Workflow(
            name=workflow_data.get("name", "CLI Workflow"),
            description=workflow_data.get("description"),
            tasks=tasks
        )
        
        click.echo(f"Submitting workflow {workflow.id} with {len(tasks)} tasks...")
        
        execution = await cli_app.workflow_manager.execute_workflow(workflow)
        
        # Prepare response data
        response_data = {
            "submission_type": "workflow",
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "execution_id": execution.execution_id,
            "task_count": len(tasks),
            "task_ids": [task.id for task in tasks],
            "workflow_file": workflow_file,
            "submitted_at": datetime.utcnow().isoformat(),
            "status": "submitted",
            "tasks": [
                {
                    "task_id": task.id,
                    "task_name": task.name,
                    "protocol": task.protocol,
                    "method": task.method,
                    "priority": task.priority
                }
                for task in tasks
            ]
        }
        
        if wait or output_file:
            click.echo("Waiting for completion...")
            
            # Start execution engine in single-shot mode for CLI workflows
            if not cli_app.execution_engine.running:
                await cli_app.execution_engine.start(ExecutionMode.SINGLE_SHOT)
            
            # Wait for completion with timeout
            timeout_seconds = 30 if not wait else 300  # Longer timeout if explicitly waiting
            waited = 0
            while execution.execution_id in cli_app.workflow_manager.active_executions and waited < timeout_seconds:
                await asyncio.sleep(1.0)
                waited += 1
        
        if wait or output_file:
            status = cli_app.workflow_manager.get_execution_status(execution.execution_id)
            if status:
                click.echo(f"Workflow completed with status: {status['status']}")
                click.echo(f"Tasks: {status['completed_tasks']}/{status['total_tasks']} completed")
                
                # Get task results for JSON output
                task_results = []
                for task in tasks:
                    task_result = cli_app.execution_engine.get_task_result(task.id)
                    if task_result:
                        task_results.append({
                            "task_id": task.id,
                            "task_name": task.name,
                            "status": task_result.status.value,
                            "result": task_result.result,
                            "error": task_result.error,
                            "execution_time": (task_result.completed_at - task_result.started_at).total_seconds() if task_result.completed_at and task_result.started_at else None
                        })
                
                # Update response data with completion status and results
                response_data.update({
                    "status": status["status"],
                    "completed_at": status.get("completed_at"),
                    "total_tasks": status["total_tasks"],
                    "completed_tasks": status["completed_tasks"],
                    "failed_tasks": status["failed_tasks"],
                    "progress": status["progress"],
                    "retry_count": status["retry_count"],
                    "task_results": task_results
                })
                
                # Show detailed results if wait flag was used
                if wait:
                    for task_result in task_results:
                        if task_result.get("result"):
                            click.echo(f"Task {task_result['task_name']} result: {json.dumps(task_result['result'], indent=2)}")
        else:
            click.echo(f"Workflow {workflow.id} submitted successfully")
        
        # Save response to file if requested
        if output_file:
            try:
                with open(output_file, 'w') as f:
                    json.dump(response_data, f, indent=2, default=str)
                click.echo(f"Response saved to: {output_file}")
            except Exception as e:
                click.echo(f"Failed to save response file: {e}", err=True)
    
    asyncio.run(_submit_workflow())


@workflow.command()
@click.argument('template_id')
@click.option('--params', default='{}', help='JSON parameters for template')
@click.option('--wait', is_flag=True, help='Wait for workflow completion')
def from_template(template_id, params, wait):
    """Create and submit workflow from template"""
    async def _from_template():
        await cli_app._initialize_components()
        
        try:
            params_dict = json.loads(params)
        except json.JSONDecodeError:
            click.echo("Error: Invalid JSON in params", err=True)
            return
        
        try:
            workflow = await cli_app.workflow_manager.create_workflow_from_template(
                template_id=template_id,
                parameters=params_dict
            )
            
            click.echo(f"Created workflow {workflow.id} from template {template_id}")
            
            execution = await cli_app.workflow_manager.execute_workflow(workflow)
            
            if wait:
                click.echo("Waiting for completion...")
                
                if not cli_app.execution_engine.running:
                    await cli_app.execution_engine.start(ExecutionMode.SINGLE_SHOT)
                
                while execution.execution_id in cli_app.workflow_manager.active_executions:
                    await asyncio.sleep(1.0)
                
                status = cli_app.workflow_manager.get_execution_status(execution.execution_id)
                if status:
                    click.echo(f"Workflow completed with status: {status['status']}")
            else:
                click.echo(f"Workflow {workflow.id} submitted successfully")
                
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
    
    asyncio.run(_from_template())


@workflow.command()
def list_templates():
    """List available workflow templates"""
    async def _list_templates():
        await cli_app._initialize_components()
        
        templates = cli_app.workflow_manager.list_templates()
        
        if not templates:
            click.echo("No workflow templates found")
            return
        
        click.echo("Available workflow templates:")
        for template in templates:
            click.echo(f"  {template['id']}: {template['name']} (v{template['version']})")
            if template['description']:
                click.echo(f"    {template['description']}")
            click.echo(f"    Tasks: {template['task_count']}, Parameters: {', '.join(template['parameters'])}")
    
    asyncio.run(_list_templates())


@workflow.command()
def list_active():
    """List active workflow executions"""
    async def _list_active():
        await cli_app._initialize_components()
        
        executions = cli_app.workflow_manager.list_active_executions()
        
        if not executions:
            click.echo("No active workflows")
            return
        
        click.echo("Active workflow executions:")
        for execution in executions:
            click.echo(f"  {execution['execution_id']}: {execution['workflow_id']}")
            click.echo(f"    Status: {execution['status']}, Progress: {execution['progress']:.1%}")
    
    asyncio.run(_list_active())


# Queue Management Commands
@cli.group()
def queue():
    """Queue management commands"""
    pass


@queue.command()
@click.option('--queue', default='default', help='Queue name')
def stats(queue):
    """Show queue statistics"""
    async def _queue_stats():
        await cli_app._initialize_components()
        
        if queue == 'all':
            stats = await cli_app.queue_manager.get_global_stats()
            click.echo("Global Queue Statistics:")
            click.echo(f"  Total queues: {stats['total_queues']}")
            click.echo(f"  Total size: {stats['total_size']}")
            click.echo(f"  Total enqueued: {stats['total_enqueued']}")
            click.echo(f"  Total dequeued: {stats['total_dequeued']}")
            
            click.echo("\nPer-queue details:")
            for name, queue_stats in stats['queue_details'].items():
                click.echo(f"  {name}: {queue_stats['current_size']} tasks")
        else:
            queue_obj = cli_app.queue_manager.get_queue(queue)
            if queue_obj:
                stats = await queue_obj.get_stats()
                click.echo(f"Queue '{queue}' Statistics:")
                click.echo(f"  Current size: {stats['current_size']}")
                click.echo(f"  Total enqueued: {stats['total_enqueued']}")
                click.echo(f"  Total dequeued: {stats['total_dequeued']}")
                click.echo(f"  Completed tasks: {stats['completed_tasks']}")
                click.echo(f"  Failed tasks: {stats['failed_tasks']}")
            else:
                click.echo(f"Queue '{queue}' not found")
    
    asyncio.run(_queue_stats())


# Provider Management Commands  
@cli.group()
def provider():
    """Provider management commands"""
    pass


@provider.command(name="list")
def list_providers():
    """List registered providers"""
    async def _list_providers():
        await cli_app._initialize_components()
        
        providers = await cli_app.registry.list_providers()
        
        if not providers:
            click.echo("No providers registered")
            return
        
        click.echo("Registered providers:")
        for provider_id, info in providers.items():
            click.echo(f"  {provider_id}: {info['protocol_id']}")
            click.echo(f"    Status: {info['status']}, Health: {info['health_status']}")
            click.echo(f"    Success rate: {info['success_rate']:.1f}%")
    
    asyncio.run(_list_providers())


@provider.command()
@click.argument('provider_id')
def health(provider_id):
    """Check provider health"""
    async def _check_health():
        await cli_app._initialize_components()
        
        try:
            health_info = await cli_app.registry.check_provider_health(provider_id)
            click.echo(f"Provider {provider_id} health:")
            click.echo(f"  Status: {health_info['status']}")
            click.echo(f"  Details: {health_info['details']}")
        except Exception as e:
            click.echo(f"Health check failed: {e}", err=True)
    
    asyncio.run(_check_health())


# Backend Commands
@cli.group()
def backend():
    """Persistence backend management commands"""
    pass


@backend.command(name="get-task")
@click.argument('task_id')
def get_task(task_id):
    """Get task details from persistence backend"""
    async def _get_task():
        await cli_app._initialize_components()
        
        # Check if persistence is configured
        if not cli_app.execution_engine.persistence:
            click.echo("Error: No persistence backend configured", err=True)
            return
        
        task = await cli_app.execution_engine.persistence.get_task(task_id)
        if task:
            click.echo(f"Task ID: {task.id}")
            click.echo(f"Name: {task.name}")
            click.echo(f"Protocol: {task.protocol}")
            click.echo(f"Method: {task.method}")
            click.echo(f"Status: {task.status}")
            click.echo(f"Priority: {task.priority}")
            click.echo(f"Created: {task.created_at}")
            click.echo(f"Started: {task.started_at}")
            click.echo(f"Completed: {task.completed_at}")
            if task.params:
                click.echo("Parameters:")
                click.echo(json.dumps(task.params, indent=2))
            if task.dependencies:
                click.echo(f"Dependencies: {', '.join(task.dependencies)}")
        else:
            click.echo(f"Task {task_id} not found in backend")
    
    asyncio.run(_get_task())


@backend.command(name="get-result")
@click.argument('task_id')
def get_result(task_id):
    """Get task result from persistence backend"""
    async def _get_result():
        await cli_app._initialize_components()
        
        if not cli_app.execution_engine.persistence:
            click.echo("Error: No persistence backend configured", err=True)
            return
        
        result = await cli_app.execution_engine.persistence.get_task_result(task_id)
        if result:
            click.echo(f"Task ID: {result.task_id}")
            
            # Handle status field (might be string from Redis or TaskStatus enum)
            status_str = result.status.value if hasattr(result.status, 'value') else str(result.status)
            click.echo(f"Status: {status_str}")
            
            click.echo(f"Started: {result.started_at}")
            click.echo(f"Completed: {result.completed_at}")
            if result.completed_at and result.started_at:
                duration = (result.completed_at - result.started_at).total_seconds()
                click.echo(f"Duration: {duration:.3f}s")
            
            if result.result:
                click.echo("Result:")
                click.echo(json.dumps(result.result, indent=2))
            
            if result.error:
                click.echo(f"Error: {result.error}")
        else:
            click.echo(f"Task result for {task_id} not found in backend")
    
    asyncio.run(_get_result())


@backend.command(name="list-tasks")
@click.option('--status', help='Filter by task status')
@click.option('--workflow-id', help='Filter by workflow ID')
@click.option('--workflow-name', help='Filter by workflow name')
@click.option('--limit', type=int, default=20, help='Limit number of results')
def list_tasks(status, workflow_id, workflow_name, limit):
    """List tasks from persistence backend"""
    async def _list_tasks():
        await cli_app._initialize_components()
        
        if not cli_app.execution_engine.persistence:
            click.echo("Error: No persistence backend configured", err=True)
            return
        
        tasks = []
        filter_desc = ""
        
        if status:
            tasks = await cli_app.execution_engine.persistence.get_tasks_by_status(status)
            filter_desc = f"with status '{status}'"
        elif workflow_id:
            tasks = await cli_app.execution_engine.persistence.get_tasks_by_workflow(workflow_id)
            filter_desc = f"in workflow ID '{workflow_id}'"
        elif workflow_name:
            # Need to find workflow ID by name first, then get tasks
            # This requires getting all workflows and filtering by name
            try:
                # Get all tasks and filter by workflow name
                all_tasks = await cli_app.execution_engine.persistence.get_all_queued_tasks()
                # Also get completed tasks by trying different statuses
                for task_status in ["completed", "failed", "running"]:
                    try:
                        status_tasks = await cli_app.execution_engine.persistence.get_tasks_by_status(task_status)
                        all_tasks.extend(status_tasks)
                    except:
                        pass
                
                # Filter by workflow name by checking workflow_id and getting workflow details
                filtered_tasks = []
                workflow_cache = {}
                
                for task in all_tasks:
                    if task.workflow_id and task.workflow_id not in workflow_cache:
                        try:
                            wf = await cli_app.execution_engine.persistence.get_workflow(task.workflow_id)
                            workflow_cache[task.workflow_id] = wf.name if wf else None
                        except:
                            workflow_cache[task.workflow_id] = None
                    
                    workflow_task_name = workflow_cache.get(task.workflow_id)
                    if workflow_task_name and workflow_name.lower() in workflow_task_name.lower():
                        filtered_tasks.append(task)
                
                tasks = filtered_tasks
                filter_desc = f"in workflow name containing '{workflow_name}'"
                
            except Exception as e:
                click.echo(f"Error filtering by workflow name: {e}", err=True)
                return
        else:
            # Get all queued tasks as a reasonable default
            tasks = await cli_app.execution_engine.persistence.get_all_queued_tasks()
        
        if not tasks:
            click.echo(f"No tasks found {filter_desc}")
            return
        
        # Limit results and sort by creation time
        tasks = sorted(tasks, key=lambda t: t.created_at or datetime.min, reverse=True)[:limit]
        
        click.echo(f"Found {len(tasks)} task(s) {filter_desc}:")
        
        # Build workflow name cache for display
        workflow_name_cache = {}
        for task in tasks:
            if task.workflow_id and task.workflow_id not in workflow_name_cache:
                try:
                    wf = await cli_app.execution_engine.persistence.get_workflow(task.workflow_id)
                    workflow_name_cache[task.workflow_id] = wf.name if wf else f"Workflow-{task.workflow_id[:8]}"
                except:
                    workflow_name_cache[task.workflow_id] = f"Workflow-{task.workflow_id[:8]}"
        
        for task in tasks:
            created = task.created_at.strftime("%Y-%m-%d %H:%M:%S") if task.created_at else "Unknown"
            
            # Add workflow info if available
            workflow_info = ""
            if task.workflow_id:
                wf_name = workflow_name_cache.get(task.workflow_id, f"Workflow-{task.workflow_id[:8]}")
                workflow_info = f" [Workflow: {wf_name}]"
            
            # Handle status display
            status_str = task.status.value if hasattr(task.status, 'value') else str(task.status)
            
            click.echo(f"  {task.id[:8]}... - {task.name} ({status_str}) - {created}{workflow_info}")
    
    asyncio.run(_list_tasks())


@backend.command(name="stats")
def backend_stats():
    """Show persistence backend statistics"""
    async def _backend_stats():
        await cli_app._initialize_components()
        
        if not cli_app.execution_engine.persistence:
            click.echo("Error: No persistence backend configured", err=True)
            return
        
        # Get backend type
        backend_type = type(cli_app.execution_engine.persistence).__name__
        click.echo(f"Backend Type: {backend_type}")
        
        # Get task counts by status
        try:
            counts = await cli_app.execution_engine.persistence.get_task_count_by_status()
            click.echo("\nTask Counts by Status:")
            total = 0
            for status, count in sorted(counts.items()):
                click.echo(f"  {status}: {count}")
                total += count
            click.echo(f"  Total: {total}")
        except Exception as e:
            click.echo(f"Could not retrieve statistics: {e}")
    
    asyncio.run(_backend_stats())


@backend.command(name="get-workflow")
@click.argument('workflow_id')
def get_workflow(workflow_id):
    """Get workflow details from persistence backend"""
    async def _get_workflow():
        await cli_app._initialize_components()
        
        if not cli_app.execution_engine.persistence:
            click.echo("Error: No persistence backend configured", err=True)
            return
        
        workflow = await cli_app.execution_engine.persistence.get_workflow(workflow_id)
        if workflow:
            click.echo(f"Workflow ID: {workflow.id}")
            click.echo(f"Name: {workflow.name}")
            click.echo(f"Description: {workflow.description or 'None'}")
            click.echo(f"Status: {workflow.status}")
            click.echo(f"Priority: {workflow.priority}")
            click.echo(f"Tasks: {len(workflow.tasks)}")
            
            click.echo("\nTasks:")
            for task in workflow.tasks:
                click.echo(f"  - {task.name} ({task.id[:8]}...): {task.protocol}/{task.method}")
        else:
            click.echo(f"Workflow {workflow_id} not found in backend")
    
    asyncio.run(_get_workflow())


@backend.command(name="list-workflows")
@click.option('--name-filter', help='Filter workflows by name (case-insensitive substring match)')
@click.option('--limit', type=int, default=20, help='Limit number of results')
def list_workflows(name_filter, limit):
    """List workflows from persistence backend"""
    async def _list_workflows():
        await cli_app._initialize_components()
        
        if not cli_app.execution_engine.persistence:
            click.echo("Error: No persistence backend configured", err=True)
            return
        
        try:
            # Get workflows by looking at unique workflow IDs from tasks
            all_tasks = []
            for task_status in ["queued", "completed", "failed", "running"]:
                try:
                    status_tasks = await cli_app.execution_engine.persistence.get_tasks_by_status(task_status)
                    all_tasks.extend(status_tasks)
                except:
                    pass
            
            # Get unique workflow IDs
            workflow_ids = set()
            for task in all_tasks:
                if task.workflow_id:
                    workflow_ids.add(task.workflow_id)
            
            # Get workflow details
            workflows = []
            for wf_id in workflow_ids:
                try:
                    wf = await cli_app.execution_engine.persistence.get_workflow(wf_id)
                    if wf:
                        workflows.append(wf)
                except:
                    pass
            
            # Filter by name if specified
            if name_filter:
                workflows = [wf for wf in workflows if name_filter.lower() in wf.name.lower()]
            
            # Sort by name and limit
            workflows = sorted(workflows, key=lambda w: w.name)[:limit]
            
            if not workflows:
                filter_desc = f" matching '{name_filter}'" if name_filter else ""
                click.echo(f"No workflows found{filter_desc}")
                return
            
            click.echo(f"Found {len(workflows)} workflow(s):")
            for wf in workflows:
                # Count tasks for this workflow
                wf_tasks = [t for t in all_tasks if t.workflow_id == wf.id]
                completed_tasks = len([t for t in wf_tasks if str(t.status) == "completed"])
                total_tasks = len(wf_tasks)
                
                status_display = wf.status.value if hasattr(wf.status, 'value') else str(wf.status)
                
                click.echo(f"  {wf.id[:8]}... - {wf.name}")
                click.echo(f"    Status: {status_display}, Tasks: {completed_tasks}/{total_tasks} completed")
                if wf.description:
                    click.echo(f"    Description: {wf.description}")
                
        except Exception as e:
            click.echo(f"Error listing workflows: {e}", err=True)
    
    asyncio.run(_list_workflows())


@backend.command(name="get-results-by-workflow")
@click.argument('workflow_name')
def get_results_by_workflow(workflow_name):
    """Get all task results from a workflow by name"""
    async def _get_results_by_workflow():
        await cli_app._initialize_components()
        
        if not cli_app.execution_engine.persistence:
            click.echo("Error: No persistence backend configured", err=True)
            return
        
        try:
            # First, find workflows matching the name
            all_tasks = []
            for task_status in ["queued", "completed", "failed", "running", "retry_pending"]:
                try:
                    status_tasks = await cli_app.execution_engine.persistence.get_tasks_by_status(task_status)
                    all_tasks.extend(status_tasks)
                except:
                    pass
            
            # Get unique workflow IDs
            workflow_ids = set()
            for task in all_tasks:
                if task.workflow_id:
                    workflow_ids.add(task.workflow_id)
            
            # Find workflows matching the name
            matching_workflows = []
            for wf_id in workflow_ids:
                try:
                    wf = await cli_app.execution_engine.persistence.get_workflow(wf_id)
                    if wf and workflow_name.lower() in wf.name.lower():
                        matching_workflows.append(wf)
                except:
                    pass
            
            if not matching_workflows:
                click.echo(f"No workflows found matching name: {workflow_name}")
                return
            
            click.echo(f"Found {len(matching_workflows)} workflow(s) matching '{workflow_name}':")
            click.echo()
            
            for wf in matching_workflows:
                click.echo(f"Workflow: {wf.name} ({wf.id})")
                click.echo(f"Status: {wf.status}")
                click.echo(f"Description: {wf.description or 'N/A'}")
                click.echo("=" * 50)
                
                # Get all tasks for this workflow
                wf_tasks = [t for t in all_tasks if t.workflow_id == wf.id]
                
                if not wf_tasks:
                    click.echo("No tasks found for this workflow")
                    click.echo()
                    continue
                
                # Get results for each task
                for task in wf_tasks:
                    click.echo(f"Task: {task.name} ({task.id})")
                    click.echo(f"  Status: {task.status}")
                    click.echo(f"  Protocol: {task.protocol}")
                    click.echo(f"  Method: {task.method}")
                    
                    if task.started_at:
                        click.echo(f"  Started: {task.started_at}")
                    if task.completed_at:
                        click.echo(f"  Completed: {task.completed_at}")
                        duration = (task.completed_at - task.started_at).total_seconds() if task.started_at else 0
                        click.echo(f"  Duration: {duration:.3f}s")
                    
                    # Get the task result
                    try:
                        result = await cli_app.execution_engine.persistence.get_task_result(task.id)
                        if result:
                            click.echo(f"  Result:")
                            if result.result:
                                import json
                                result_str = json.dumps(result.result, indent=4, default=str)
                                for line in result_str.split('\n'):
                                    click.echo(f"    {line}")
                            else:
                                click.echo(f"    No result data")
                            
                            if result.error:
                                click.echo(f"  Error: {result.error}")
                        else:
                            click.echo(f"  No result found")
                    except Exception as e:
                        click.echo(f"  Error getting result: {e}")
                    
                    click.echo()
                
                click.echo()
                
        except Exception as e:
            click.echo(f"Error getting workflow results: {e}", err=True)
    
    asyncio.run(_get_results_by_workflow())


# System Commands
@cli.group()
def system():
    """System management commands"""
    pass


@system.command()
@click.option('--mode', type=click.Choice(['single', 'workflow', 'event']), default='event')
def start(mode):
    """Start the execution engine"""
    async def _start_engine():
        await cli_app._initialize_components()
        
        execution_mode = {
            'single': ExecutionMode.SINGLE_SHOT,
            'workflow': ExecutionMode.WORKFLOW_ONLY,
            'event': ExecutionMode.EVENT_DRIVEN
        }[mode]
        
        click.echo(f"Starting execution engine in {mode} mode...")
        click.echo("Press Ctrl+C to stop")
        
        try:
            await cli_app.execution_engine.start(execution_mode)
        except KeyboardInterrupt:
            click.echo("\nStopping execution engine...")
            await cli_app.execution_engine.stop()
    
    asyncio.run(_start_engine())


@system.command()
def status():
    """Show system status"""
    async def _system_status():
        await cli_app._initialize_components()
        
        # Engine stats
        stats = cli_app.execution_engine.get_stats()
        click.echo("Execution Engine:")
        click.echo(f"  Running: {cli_app.execution_engine.running}")
        click.echo(f"  Tasks processed: {stats.tasks_processed}")
        click.echo(f"  Success rate: {stats.tasks_succeeded / stats.tasks_processed * 100 if stats.tasks_processed > 0 else 0:.1f}%")
        click.echo(f"  Active tasks: {len(cli_app.execution_engine.active_tasks)}")
        
        # Workflow stats
        wf_stats = cli_app.workflow_manager.get_workflow_statistics()
        click.echo("\nWorkflow Manager:")
        click.echo(f"  Templates: {wf_stats['total_templates']}")
        click.echo(f"  Active executions: {wf_stats['active_executions']}")
        click.echo(f"  Success rate: {wf_stats['success_rate']:.1f}%")
        
        # Queue stats
        queue_stats = await cli_app.queue_manager.get_global_stats()
        click.echo("\nQueues:")
        click.echo(f"  Total size: {queue_stats['total_size']}")
        click.echo(f"  Total processed: {queue_stats['total_dequeued']}")
    
    asyncio.run(_system_status())


@system.command()
@click.option('--key', help='Configuration key')
@click.option('--value', help='Configuration value')
def config(key, value):
    """Show or update configuration"""
    if key and value:
        # Set configuration
        try:
            # Try to parse as JSON first
            try:
                parsed_value = json.loads(value)
            except json.JSONDecodeError:
                parsed_value = value
            
            cli_app.config[key] = parsed_value
            cli_app._save_config()
            click.echo(f"Set {key} = {parsed_value}")
        except Exception as e:
            click.echo(f"Error setting config: {e}", err=True)
    else:
        # Show configuration
        click.echo("Current configuration:")
        for k, v in cli_app.config.items():
            click.echo(f"  {k}: {v}")


if __name__ == '__main__':
    cli()