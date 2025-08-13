#!/usr/bin/env python3
"""
Gleitzeit V4 CLI - Simple Working Interface
Event-driven workflow orchestration system command line interface.
"""

import asyncio
import click
import json
import logging
import os
import sys
import tempfile
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# Add the parent directory to Python path for imports
current_dir = Path(__file__).parent
gleitzeit_v4_dir = current_dir.parent
sys.path.insert(0, str(gleitzeit_v4_dir))

from core import Task, Workflow, Priority, ExecutionEngine, ExecutionMode
from core.models import RetryConfig
from core.retry_manager import BackoffStrategy
from task_queue import QueueManager, DependencyResolver  
from registry import ProtocolProviderRegistry
from providers.python_function_provider import CustomFunctionProvider
from providers.ollama_provider import OllamaProvider
from protocols import PYTHON_PROTOCOL_V1, LLM_PROTOCOL_V1
from persistence.redis_backend import RedisBackend
from persistence.sqlite_backend import SQLiteBackend

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GleitzeitCLI:
    """Main CLI class for Gleitzeit V4"""
    
    def __init__(self):
        self.config = self._load_config()
        self.execution_engine = None
        self.persistence_backend = None
        
    def _load_config(self) -> Dict[str, Any]:
        """Load CLI configuration"""
        config_file = Path.home() / '.gleitzeit' / 'config.yaml'
        if config_file.exists():
            with open(config_file, 'r') as f:
                return yaml.safe_load(f)
        else:
            # Default configuration
            return {
                'persistence': {
                    'backend': 'sqlite',
                    'sqlite': {
                        'db_path': str(Path.home() / '.gleitzeit' / 'workflows.db')
                    },
                    'redis': {
                        'host': 'localhost',
                        'port': 6379,
                        'db': 0
                    }
                },
                'providers': {
                    'python': {
                        'enabled': True
                    },
                    'ollama': {
                        'enabled': True,
                        'endpoint': 'http://localhost:11434'
                    }
                },
                'execution': {
                    'max_concurrent_tasks': 5
                }
            }
    
    async def _setup_system(self) -> bool:
        """Set up the execution system"""
        try:
            # Initialize persistence backend
            persistence_config = self.config.get('persistence', {})
            backend_type = persistence_config.get('backend', 'sqlite')
            
            if backend_type == 'redis':
                redis_config = persistence_config.get('redis', {})
                self.persistence_backend = RedisBackend(
                    host=redis_config.get('host', 'localhost'),
                    port=redis_config.get('port', 6379),
                    db=redis_config.get('db', 0)
                )
            else:  # Default to SQLite
                sqlite_config = persistence_config.get('sqlite', {})
                db_path = sqlite_config.get('db_path', str(Path.home() / '.gleitzeit' / 'workflows.db'))
                # Ensure directory exists
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                self.persistence_backend = SQLiteBackend(db_path=db_path)
            
            await self.persistence_backend.initialize()
            click.echo(f"✓ {backend_type.title()} persistence initialized")
            
            # Set up execution components
            queue_manager = QueueManager()
            dependency_resolver = DependencyResolver()
            registry = ProtocolProviderRegistry()
            
            execution_config = self.config.get('execution', {})
            max_concurrent = execution_config.get('max_concurrent_tasks', 5)
            self.execution_engine = ExecutionEngine(
                registry=registry,
                queue_manager=queue_manager,
                dependency_resolver=dependency_resolver,
                persistence=self.persistence_backend,
                max_concurrent_tasks=max_concurrent
            )
            
            # Register protocols and providers
            provider_config = self.config.get('providers', {})
            
            # Python provider
            python_config = provider_config.get('python', {})
            if python_config.get('enabled', True):
                registry.register_protocol(PYTHON_PROTOCOL_V1)
                python_provider = CustomFunctionProvider("cli-python-provider")
                await python_provider.initialize()
                registry.register_provider("cli-python-provider", "python/v1", python_provider)
                click.echo("✓ Python provider registered")
            
            # Ollama provider
            ollama_config = provider_config.get('ollama', {})
            if ollama_config.get('enabled', True):
                try:
                    registry.register_protocol(LLM_PROTOCOL_V1)
                    ollama_endpoint = ollama_config.get('endpoint', 'http://localhost:11434')
                    ollama_provider = OllamaProvider("cli-ollama-provider", ollama_endpoint)
                    await ollama_provider.initialize()
                    registry.register_provider("cli-ollama-provider", "llm/v1", ollama_provider)
                    click.echo("✓ Ollama provider registered")
                except Exception as e:
                    click.echo(f"⚠️  Ollama provider failed to initialize: {e}")
            
            return True
            
        except Exception as e:
            click.echo(f"❌ System setup failed: {e}")
            return False
    
    async def _shutdown_system(self):
        """Clean shutdown of the system"""
        if self.persistence_backend:
            await self.persistence_backend.shutdown()


# CLI instance
cli_instance = GleitzeitCLI()


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def cli(verbose: bool, debug: bool):
    """
    Gleitzeit V4 - Event-driven workflow orchestration system
    
    Execute workflows with Python code, LLM tasks, and more.
    """
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
    elif verbose:
        logging.getLogger().setLevel(logging.INFO)
    else:
        logging.getLogger().setLevel(logging.WARNING)


@cli.command()
@click.argument('workflow_file', type=click.Path(exists=True))
@click.option('--watch', '-w', is_flag=True, help='Watch execution progress')
@click.option('--backend', type=click.Choice(['sqlite', 'redis']), 
              help='Override persistence backend')
def run(workflow_file: str, watch: bool, backend: Optional[str]):
    """Execute a workflow from a YAML or JSON file"""
    return asyncio.run(_run_workflow(workflow_file, watch, backend))


async def _run_workflow(workflow_file: str, watch: bool, backend: Optional[str]):
    """Execute workflow implementation"""
    try:
        # Override backend if specified
        if backend:
            cli_instance.config['persistence']['backend'] = backend
        
        # Setup system
        if not await cli_instance._setup_system():
            return
        
        # Load workflow file
        with open(workflow_file, 'r') as f:
            if workflow_file.endswith('.yaml') or workflow_file.endswith('.yml'):
                workflow_data = yaml.safe_load(f)
            else:
                workflow_data = json.load(f)
        
        click.echo(f"📄 Loading workflow: {workflow_data['name']}")
        
        # Create tasks from workflow definition
        tasks = []
        name_to_id_map = {}  # Map task names to generated IDs
        
        # First pass: create tasks and build name-to-ID mapping
        for task_def in workflow_data['tasks']:
            # Handle retry config
            retry_config = None
            if 'retry' in task_def:
                retry_def = task_def['retry']
                retry_config = RetryConfig(
                    max_attempts=retry_def.get('max_attempts', 3),
                    base_delay=retry_def.get('base_delay', 1.0),
                    max_delay=retry_def.get('max_delay', 60.0),
                    backoff_strategy=BackoffStrategy(retry_def.get('strategy', 'exponential')),
                    jitter=retry_def.get('jitter', True)
                )
            
            # Create task (without dependencies resolved yet)
            task = Task(
                name=task_def['name'],
                protocol=task_def['protocol'],
                method=task_def['method'],
                params=task_def['parameters'],
                dependencies=[],  # Will resolve in second pass
                retry_config=retry_config,
                priority=Priority(task_def.get('priority', 'normal').lower())
            )
            tasks.append(task)
            name_to_id_map[task.name] = task.id
        
        # Second pass: resolve dependencies (map task names to task IDs)
        for i, task_def in enumerate(workflow_data['tasks']):
            dependencies = task_def.get('dependencies', [])
            resolved_dependencies = []
            
            for dep_name in dependencies:
                if dep_name in name_to_id_map:
                    resolved_dependencies.append(name_to_id_map[dep_name])
                else:
                    click.echo(f"⚠️  Warning: Task '{tasks[i].name}' depends on unknown task '{dep_name}'")
                    # Keep original dependency name for error reporting
                    resolved_dependencies.append(dep_name)
            
            tasks[i].dependencies = resolved_dependencies
        
        # Create workflow
        workflow = Workflow(
            name=workflow_data['name'],
            description=workflow_data.get('description', ''),
            tasks=tasks
        )
        
        click.echo(f"🚀 Executing workflow: {workflow.name}")
        click.echo(f"   Tasks: {len(workflow.tasks)}")
        
        # Submit and execute workflow
        await cli_instance.execution_engine.submit_workflow(workflow)
        
        if watch:
            click.echo("📊 Watching execution...")
        
        # Execute workflow
        await cli_instance.execution_engine._execute_workflow(workflow)
        
        # Show results
        click.echo("\n✅ Workflow completed!")
        for task in workflow.tasks:
            result = cli_instance.execution_engine.task_results.get(task.id)
            if result:
                status_icon = "✅" if result.status == "completed" else "❌"
                click.echo(f"   {status_icon} {task.name}: {result.status}")
                if result.status == "failed" and result.error:
                    click.echo(f"      Error: {result.error}")
                elif result.status == "completed" and result.result:
                    if 'output' in result.result and result.result['output']:
                        output_lines = result.result['output'].strip().split('\n')
                        for line in output_lines[:3]:  # Show first 3 lines
                            click.echo(f"      Output: {line}")
                        if len(output_lines) > 3:
                            click.echo(f"      ... ({len(output_lines) - 3} more lines)")
        
        persistence_backend = cli_instance.config.get('persistence', {}).get('backend', 'sqlite')
        click.echo(f"\n💾 Results persisted to {persistence_backend} backend")
        
    except Exception as e:
        click.echo(f"❌ Workflow execution failed: {e}")
        if logger.isEnabledFor(logging.DEBUG):
            import traceback
            traceback.print_exc()
    finally:
        await cli_instance._shutdown_system()


@cli.command()
@click.option('--backend', type=click.Choice(['sqlite', 'redis']), 
              help='Persistence backend to query')
def status(backend: Optional[str]):
    """Show system status and recent workflows"""
    return asyncio.run(_show_status(backend))


async def _show_status(backend: Optional[str]):
    """Show status implementation"""
    try:
        if backend:
            cli_instance.config['persistence']['backend'] = backend
        
        if not await cli_instance._setup_system():
            return
        
        click.echo("📊 Gleitzeit V4 System Status")
        persistence_backend = cli_instance.config.get('persistence', {}).get('backend', 'sqlite')
        click.echo(f"   Backend: {persistence_backend}")
        
        # Get task statistics
        try:
            task_counts = await cli_instance.persistence_backend.get_task_count_by_status()
            click.echo("\n📈 Task Statistics:")
            for status, count in task_counts.items():
                status_icon = {"completed": "✅", "failed": "❌", "queued": "⏳"}.get(status, "📋")
                click.echo(f"   {status_icon} {status.title()}: {count}")
        except Exception as e:
            click.echo(f"   ⚠️  Could not load statistics: {e}")
        
        # Get recent completed tasks
        try:
            completed_tasks = await cli_instance.persistence_backend.get_tasks_by_status("completed")
            if completed_tasks:
                click.echo(f"\n🎯 Recent Completed Tasks ({len(completed_tasks)}):")
                for task in completed_tasks[-5:]:  # Show last 5
                    click.echo(f"   ✅ {task.name} ({task.protocol})")
        except Exception as e:
            click.echo(f"   ⚠️  Could not load recent tasks: {e}")
        
    except Exception as e:
        click.echo(f"❌ Status check failed: {e}")
    finally:
        await cli_instance._shutdown_system()


@cli.command()
@click.argument('name')
@click.option('--type', 'workflow_type', type=click.Choice(['python', 'llm', 'mixed']), 
              default='python', help='Type of workflow to create')
def init(name: str, workflow_type: str):
    """Create a new workflow template"""
    return _create_workflow_template(name, workflow_type)


def _create_workflow_template(name: str, workflow_type: str):
    """Create workflow template implementation"""
    templates = {
        'python': {
            'name': name,
            'description': f'Python workflow: {name}',
            'tasks': [
                {
                    'name': 'Calculate Data',
                    'protocol': 'python/v1',
                    'method': 'python/execute',
                    'parameters': {
                        'code': '''
# Example Python task
result = {
    'message': 'Hello from Gleitzeit!',
    'numbers': [1, 2, 3, 4, 5],
    'sum': sum([1, 2, 3, 4, 5])
}

print(f"Calculated sum: {result['sum']}")
''',
                        'timeout': 10
                    },
                    'priority': 'normal'
                }
            ]
        },
        'llm': {
            'name': name,
            'description': f'LLM workflow: {name}',
            'tasks': [
                {
                    'name': 'Generate Text',
                    'protocol': 'llm/v1', 
                    'method': 'llm/chat',
                    'parameters': {
                        'model': 'llama3.2:latest',
                        'messages': [
                            {'role': 'user', 'content': 'Write a short poem about workflow automation'}
                        ],
                        'temperature': 0.7
                    },
                    'priority': 'normal',
                    'retry': {
                        'max_attempts': 2,
                        'base_delay': 5.0
                    }
                }
            ]
        },
        'mixed': {
            'name': name,
            'description': f'Mixed workflow: {name}',
            'tasks': [
                {
                    'name': 'Generate Prompt',
                    'protocol': 'python/v1',
                    'method': 'python/execute',
                    'parameters': {
                        'code': '''
import random

topics = ['automation', 'efficiency', 'innovation', 'technology']
topic = random.choice(topics)

result = {
    'topic': topic,
    'prompt': f'Write a haiku about {topic}'
}

print(f"Generated prompt: {result['prompt']}")
''',
                        'timeout': 5
                    },
                    'priority': 'high'
                },
                {
                    'name': 'Generate Haiku',
                    'protocol': 'llm/v1',
                    'method': 'llm/chat', 
                    'parameters': {
                        'model': 'llama3.2:latest',
                        'messages': [
                            {'role': 'user', 'content': '${Generate Prompt.result.result.prompt}'}
                        ],
                        'temperature': 0.8
                    },
                    'dependencies': ['Generate Prompt'],
                    'priority': 'normal'
                }
            ]
        }
    }
    
    template = templates[workflow_type]
    filename = f"{name.replace(' ', '_').lower()}.yaml"
    
    with open(filename, 'w') as f:
        yaml.dump(template, f, default_flow_style=False, indent=2)
    
    click.echo(f"✅ Created workflow template: {filename}")
    click.echo(f"   Type: {workflow_type}")
    click.echo(f"   Tasks: {len(template['tasks'])}")
    click.echo(f"\n🚀 Run with: gleitzeit run {filename}")


@cli.command()
def config():
    """Show current configuration"""
    config_file = Path.home() / '.gleitzeit' / 'config.yaml'
    
    if config_file.exists():
        click.echo(f"📋 Configuration: {config_file}")
        with open(config_file, 'r') as f:
            config_data = yaml.safe_load(f)
        click.echo(yaml.dump(config_data, default_flow_style=False, indent=2))
    else:
        click.echo("⚠️  No configuration file found")
        click.echo(f"   Default location: {config_file}")
        click.echo("\n🔧 Create default configuration? [y/N]: ", nl=False)
        if click.getchar().lower() == 'y':
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, 'w') as f:
                yaml.dump(cli_instance.config, f, default_flow_style=False, indent=2)
            click.echo(f"\n✅ Created default configuration: {config_file}")


@cli.command()
@click.argument('code')
@click.option('--timeout', default=10, help='Execution timeout in seconds')
def exec(code: str, timeout: int):
    """Execute Python code directly"""
    return asyncio.run(_exec_code(code, timeout))


async def _exec_code(code: str, timeout: int):
    """Execute code implementation"""
    try:
        if not await cli_instance._setup_system():
            return
        
        click.echo("🐍 Executing Python code...")
        
        # Create and execute task
        task = Task(
            name="CLI Code Execution",
            protocol="python/v1",
            method="python/execute",
            params={
                "code": code,
                "timeout": timeout
            },
            priority=Priority.HIGH
        )
        
        await cli_instance.execution_engine.submit_task(task)
        await cli_instance.execution_engine.start(ExecutionMode.SINGLE_SHOT)
        
        # Show result
        result = cli_instance.execution_engine.task_results.get(task.id)
        if result and result.status == "completed":
            click.echo("✅ Code executed successfully")
            if result.result and 'output' in result.result:
                output = result.result['output'].strip()
                if output:
                    click.echo(f"\n📤 Output:\n{output}")
            if result.result and 'result' in result.result and result.result['result']:
                click.echo(f"\n📊 Result: {result.result['result']}")
        else:
            click.echo("❌ Code execution failed")
            if result and result.error:
                click.echo(f"   Error: {result.error}")
        
    except Exception as e:
        click.echo(f"❌ Execution failed: {e}")
    finally:
        await cli_instance._shutdown_system()


def main():
    """Main CLI entry point"""
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()