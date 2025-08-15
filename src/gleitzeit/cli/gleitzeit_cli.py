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

from gleitzeit.core import Task, Workflow, Priority, ExecutionEngine, ExecutionMode
from gleitzeit.core.models import RetryConfig
from gleitzeit.core.retry_manager import BackoffStrategy
from gleitzeit.task_queue import QueueManager, DependencyResolver  
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.providers.python_function_provider import CustomFunctionProvider
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider
from gleitzeit.protocols import PYTHON_PROTOCOL_V1, LLM_PROTOCOL_V1, MCP_PROTOCOL_V1
from gleitzeit.persistence.redis_backend import RedisBackend
from gleitzeit.persistence.sqlite_backend import SQLiteBackend
from gleitzeit.core.batch_processor import BatchProcessor, BatchResult

# Import error formatter
from gleitzeit.core.error_formatter import set_debug_mode, get_clean_logger

# Set up logging - will be configured based on verbosity
logger = get_clean_logger(__name__)


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
                        'endpoint': 'http://localhost:11434',
                        'default_models': {
                            'chat': 'llama3.2:latest',
                            'vision': 'llava:latest',
                            'embedding': 'nomic-embed-text:latest'
                        }
                    }
                },
                'execution': {
                    'max_concurrent_tasks': 5
                },
                'batch': {
                    'max_file_size': 1048576,  # 1MB
                    'max_concurrent': 5,
                    'results_directory': str(Path.home() / '.gleitzeit' / 'batch_results')
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
            
            # MCP provider
            mcp_config = provider_config.get('mcp', {})
            if mcp_config.get('enabled', True):
                try:
                    registry.register_protocol(MCP_PROTOCOL_V1)
                    mcp_provider = SimpleMCPProvider("cli-mcp-provider")
                    await mcp_provider.initialize()
                    registry.register_provider("cli-mcp-provider", "mcp/v1", mcp_provider)
                    click.echo("✓ MCP provider registered")
                except Exception as e:
                    click.echo(f"⚠️  MCP provider failed to initialize: {e}")
            
            return True
            
        except Exception as e:
            click.echo(f"❌ System setup failed: {e}")
            return False
    
    async def run(self, workflow_file: str) -> bool:
        """Run a workflow programmatically"""
        try:
            # Setup system
            if not await self._setup_system():
                return False
            
            # Load workflow using the unified loader
            from gleitzeit.core.workflow_loader import load_workflow_from_file, validate_workflow
            
            workflow = load_workflow_from_file(workflow_file)
            click.echo(f"📄 Loading workflow: {workflow.name}")
            
            # Validate workflow
            validation_errors = validate_workflow(workflow)
            if validation_errors:
                click.echo("❌ Workflow validation failed:")
                for error in validation_errors:
                    click.echo(f"  • {error}")
                return False
            
            click.echo(f"🚀 Executing workflow: {workflow.name}")
            click.echo(f"   Tasks: {len(workflow.tasks)}")
            
            # Submit and execute workflow using the same method as CLI
            await self.execution_engine.submit_workflow(workflow)
            
            # Execute workflow
            await self.execution_engine._execute_workflow(workflow)
            
            # Show results
            click.echo("\n✅ Workflow completed!")
            for task in workflow.tasks:
                result = self.execution_engine.task_results.get(task.id)
                self._display_task_result(task.name, result)
            
            persistence_backend = self.config.get('persistence', {}).get('backend', 'sqlite')
            click.echo(f"\n💾 Results persisted to {persistence_backend} backend")
            return True
                
        except Exception as e:
            click.echo(f"❌ Workflow execution failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            await self._shutdown_system()
    
    def _display_task_result(self, task_name: str, result):
        """Display task result in a consistent format"""
        if not result:
            return
            
        status_icon = "✅" if result.status == "completed" else "❌"
        click.echo(f"   {status_icon} {task_name}: {result.status}")
        
        if result.status == "failed" and result.error:
            click.echo(f"      Error: {result.error}")
        elif result.status == "completed" and result.result:
            # Use standard fields based on provider type
            display_text = None
            
            # Check standard fields in order of preference
            if 'response' in result.result:  # LLM standard field
                display_text = result.result['response']
            elif 'result' in result.result:  # Python standard field
                display_text = str(result.result['result'])
            elif 'content' in result.result:  # Backward compatibility for LLM
                display_text = result.result['content']
            elif 'output' in result.result:  # Additional Python output
                display_text = result.result['output']
            
            if display_text:
                # Truncate long responses for display
                if len(display_text) > 200:
                    display_text = display_text[:200] + "..."
                click.echo(f"      Result: {display_text}")
    
    async def _shutdown_system(self):
        """Clean shutdown of the system"""
        if self.persistence_backend:
            await self.persistence_backend.shutdown()


# CLI instance
cli_instance = GleitzeitCLI()


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.version_option(version='0.0.4', prog_name='Gleitzeit')
def cli(verbose: bool, debug: bool):
    """
    Gleitzeit - Protocol-based workflow orchestration system
    
    Execute workflows with Python code, LLM tasks, MCP tools, and more.
    """
    # Configure logging and error formatting based on verbosity
    if debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        set_debug_mode(True)
    elif verbose:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        set_debug_mode(False)
    else:
        # Production mode - only show warnings and errors
        logging.basicConfig(
            level=logging.WARNING,
            format='%(levelname)s: %(message)s'
        )
        set_debug_mode(False)


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
        
        # Use the unified workflow loader
        from gleitzeit.core.workflow_loader import load_workflow_from_file, validate_workflow
        
        workflow = load_workflow_from_file(workflow_file)
        click.echo(f"📄 Loading workflow: {workflow.name}")
        
        # Validate workflow
        validation_errors = validate_workflow(workflow)
        if validation_errors:
            click.echo("❌ Workflow validation failed:")
            for error in validation_errors:
                click.echo(f"  • {error}")
            return
        
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
            cli_instance._display_task_result(task.name, result)
        
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
    # Create a script file for Python workflows
    script_name = f"{name.replace(' ', '_').lower()}_script.py"
    
    templates = {
        'python': {
            'name': name,
            'description': f'Python workflow: {name}',
            'tasks': [
                {
                    'name': 'Calculate Data',
                    'protocol': 'python/v1',
                    'method': 'python/execute',
                    'params': {
                        'file': script_name,
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
                    'params': {
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
                    'params': {
                        'file': f"{name.replace(' ', '_').lower()}_prompt.py",
                        'timeout': 5
                    },
                    'priority': 'high'
                },
                {
                    'name': 'Generate Haiku',
                    'protocol': 'llm/v1',
                    'method': 'llm/chat', 
                    'params': {
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
    
    # Create associated Python files
    if workflow_type == 'python':
        script_file = script_name
        with open(script_file, 'w') as f:
            f.write('''#!/usr/bin/env python3
"""
Example Python script for workflow
"""

# Example calculation
result = {
    'message': 'Hello from Gleitzeit!',
    'numbers': [1, 2, 3, 4, 5],
    'sum': sum([1, 2, 3, 4, 5])
}

print(f"Calculated sum: {result['sum']}")
''')
        click.echo(f"✅ Created Python script: {script_file}")
    
    elif workflow_type == 'mixed':
        prompt_file = f"{name.replace(' ', '_').lower()}_prompt.py"
        with open(prompt_file, 'w') as f:
            f.write('''#!/usr/bin/env python3
"""
Generate a random prompt for haiku generation
"""

import random

topics = ['automation', 'efficiency', 'innovation', 'technology']
topic = random.choice(topics)

result = {
    'topic': topic,
    'prompt': f'Write a haiku about {topic}'
}

print(f"Generated prompt: {result['prompt']}")
''')
        click.echo(f"✅ Created Python script: {prompt_file}")
    
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
@click.argument('directory', type=click.Path(exists=True))
@click.option('--pattern', default='*', help='File pattern to match (e.g., "*.txt", "*.png")')
@click.option('--prompt', default='Analyze this file', help='Prompt to use for each file')
@click.option('--model', default='llama3.2:latest', help='Model to use')
@click.option('--vision', is_flag=True, help='Use vision model for images')
@click.option('--output', type=click.Path(), help='Save results to file')
def batch(directory: str, pattern: str, prompt: str, model: str, vision: bool, output: Optional[str]):
    """Process multiple files in batch"""
    return asyncio.run(_batch_process(directory, pattern, prompt, model, vision, output))


@cli.command()
@click.argument('code')
@click.option('--timeout', default=10, help='Execution timeout in seconds')
def exec(code: str, timeout: int):
    """Execute Python code directly"""
    return asyncio.run(_exec_code(code, timeout))


async def _batch_process(directory: str, pattern: str, prompt: str, model: str, vision: bool, output: Optional[str]):
    """Process files in batch using BatchProcessor"""
    try:
        if not await cli_instance._setup_system():
            return
        
        click.echo(f"📁 Scanning directory: {directory}")
        click.echo(f"   Pattern: {pattern}")
        
        # Create batch processor
        batch_processor = BatchProcessor()
        
        # Determine method based on vision flag
        method = "llm/vision" if vision else "llm/chat"
        
        # Use configured default model if not specified
        if model == 'llama3.2:latest':  # Default value from click option
            ollama_config = cli_instance.config.get('providers', {}).get('ollama', {})
            default_models = ollama_config.get('default_models', {})
            if vision:
                model = default_models.get('vision', 'llava:latest')
            else:
                model = default_models.get('chat', 'llama3.2:latest')
        
        # Process batch
        click.echo("⏳ Processing files...")
        result = await batch_processor.process_batch(
            execution_engine=cli_instance.execution_engine,
            directory=directory,
            pattern=pattern,
            method=method,
            prompt=prompt,
            model=model
        )
        
        # Display results
        click.echo(f"\n✅ Batch processing complete!")
        click.echo(f"   Batch ID: {result.batch_id}")
        click.echo(f"   Total files: {result.total_files}")
        click.echo(f"   Successful: {result.successful} ({result.successful/result.total_files*100:.1f}%)")
        click.echo(f"   Failed: {result.failed}")
        click.echo(f"   Processing time: {result.processing_time:.2f}s")
        
        # Show individual results
        if result.total_files <= 10:  # Show details for small batches
            click.echo("\n📊 Results:")
            for file_path, file_result in result.results.items():
                file_name = Path(file_path).name
                if file_result['status'] == 'success':
                    content = file_result.get('content', '')
                    # Truncate long content
                    if len(content) > 200:
                        content = content[:200] + "..."
                    click.echo(f"   ✅ {file_name}: {content}")
                else:
                    click.echo(f"   ❌ {file_name}: {file_result.get('error', 'Unknown error')}")
        
        # Save output if requested
        if output:
            output_path = Path(output)
            if output_path.suffix == '.md':
                output_path.write_text(result.to_markdown())
                click.echo(f"\n💾 Results saved to: {output_path} (Markdown)")
            else:
                output_path.write_text(result.to_json())
                click.echo(f"\n💾 Results saved to: {output_path} (JSON)")
        
    except Exception as e:
        click.echo(f"❌ Batch processing failed: {e}")
        logger.error(f"Batch processing error: {e}", exc_info=True)
    finally:
        await cli_instance._shutdown_system()


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