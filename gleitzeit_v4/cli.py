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

from .core import (
    Task, Workflow, Priority, ExecutionEngine, ExecutionMode,
    WorkflowManager, WorkflowExecutionPolicy
)
from .core.models import RetryConfig
from .registry import ProtocolProviderRegistry
from .queue import QueueManager, DependencyResolver

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
            "log_level": "INFO"
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
            self.execution_engine = ExecutionEngine(
                registry=self.registry,
                queue_manager=self.queue_manager,
                dependency_resolver=self.dependency_resolver,
                max_concurrent_tasks=self.config["max_concurrent_tasks"]
            )
            self.workflow_manager = WorkflowManager(
                execution_engine=self.execution_engine,
                dependency_resolver=self.dependency_resolver,
                template_directory=Path(self.config["template_directory"])
            )
            
            # Load workflow templates
            self.workflow_manager.load_templates_from_directory()


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
def submit(protocol, method, params, priority, timeout, depends_on, queue, wait):
    """Submit a single task for execution"""
    async def _submit_task():
        await cli_app._initialize_components()
        
        try:
            params_dict = json.loads(params)
        except json.JSONDecodeError:
            click.echo("Error: Invalid JSON in params", err=True)
            return
        
        task = Task(
            protocol=protocol,
            method=method,
            params=params_dict,
            priority=Priority(priority),
            dependencies=list(depends_on),
            timeout=timeout
        )
        
        click.echo(f"Submitting task {task.id}...")
        
        await cli_app.execution_engine.submit_task(task, queue)
        
        if wait:
            click.echo("Waiting for completion...")
            
            # Start execution engine if not running
            if not cli_app.execution_engine.running:
                await cli_app.execution_engine.start(ExecutionMode.SINGLE_SHOT)
            
            # Wait for result
            while task.id not in cli_app.execution_engine.task_results:
                await asyncio.sleep(0.5)
            
            result = cli_app.execution_engine.get_task_result(task.id)
            if result:
                click.echo(f"Task completed with status: {result.status.value}")
                if result.result:
                    click.echo(f"Result: {json.dumps(result.result, indent=2)}")
                if result.error:
                    click.echo(f"Error: {result.error}", err=True)
        else:
            click.echo(f"Task {task.id} submitted successfully")
    
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
def submit(workflow_file, params, wait):
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
            task = Task(
                id=task_data.get("id"),
                protocol=task_data["protocol"],
                method=task_data["method"],
                params=task_data.get("params", {}),
                dependencies=task_data.get("dependencies", []),
                priority=Priority(task_data.get("priority", "normal")),
                timeout=task_data.get("timeout")
            )
            tasks.append(task)
        
        workflow = Workflow(
            name=workflow_data.get("name", "CLI Workflow"),
            description=workflow_data.get("description"),
            tasks=tasks
        )
        
        click.echo(f"Submitting workflow {workflow.id} with {len(tasks)} tasks...")
        
        execution = await cli_app.workflow_manager.execute_workflow(workflow)
        
        if wait:
            click.echo("Waiting for completion...")
            
            # Start execution engine in event-driven mode
            if not cli_app.execution_engine.running:
                await cli_app.execution_engine.start(ExecutionMode.EVENT_DRIVEN)
            
            # Wait for completion
            while execution.execution_id in cli_app.workflow_manager.active_executions:
                await asyncio.sleep(1.0)
            
            status = cli_app.workflow_manager.get_execution_status(execution.execution_id)
            if status:
                click.echo(f"Workflow completed with status: {status['status']}")
                click.echo(f"Tasks: {status['completed_tasks']}/{status['total_tasks']} completed")
        else:
            click.echo(f"Workflow {workflow.id} submitted successfully")
    
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
                    await cli_app.execution_engine.start(ExecutionMode.EVENT_DRIVEN)
                
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


@provider.command()
def list():
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