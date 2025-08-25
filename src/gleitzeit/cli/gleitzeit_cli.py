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
import subprocess
import time
import httpx
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add the parent directory to Python path for imports
current_dir = Path(__file__).parent
gleitzeit_v4_dir = current_dir.parent
sys.path.insert(0, str(gleitzeit_v4_dir))

from gleitzeit.core import Task, Workflow, Priority, ExecutionEngine, ExecutionMode
from gleitzeit.core.models import RetryConfig
from gleitzeit.core.retry_manager import BackoffStrategy
from gleitzeit.task_queue import QueueManager, DependencyResolver  
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
from gleitzeit.hub.mcp_hub import MCPHub
from gleitzeit.protocols import PYTHON_PROTOCOL_V1, LLM_PROTOCOL_V1, MCP_PROTOCOL_V1
from gleitzeit.persistence.factory import PersistenceFactory, PersistenceType
from gleitzeit.core.batch_processor import BatchProcessor, BatchResult
from gleitzeit.common.shutdown import unified_shutdown

# Import hub system for resource management
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.docker_hub import DockerHub
from gleitzeit.hub.base import ResourceStatus

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
        self.resource_manager = None
        
    def _load_config(self) -> Dict[str, Any]:
        """Load CLI configuration"""
        config_file = Path.home() / '.gleitzeit' / 'config.yaml'
        if config_file.exists():
            with open(config_file, 'r') as f:
                return yaml.safe_load(f)
        else:
            # Default configuration
            return {
                'server': {
                    'api': {
                        'host': '0.0.0.0',
                        'port_range': [8000, 8010],  # Try ports 8000-8010 for API
                        'default_port': 8000
                    },
                    'ui': {
                        'host': '0.0.0.0',
                        'port_range': [8004, 8014],  # Try ports 8004-8014 for UI
                        'default_port': 8004
                    }
                },
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
                    },
                    'template': {
                        'enabled': True
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
    
    async def _setup_system(self, enable_resource_management: bool = True) -> bool:
        """
        DEPRECATED: Legacy setup method - use GleitzeitClient instead
        
        This method is only used for backward compatibility with --local mode.
        The modern system uses GleitzeitClient which properly sets up event bus.
        """
        logger.warning("Using legacy _setup_system - consider using GleitzeitClient instead")
        try:
            # Initialize unified persistence backend
            # This will automatically try Redis -> SQL -> Memory fallback chain
            persistence_config = self.config.get('persistence', {})
            
            # Prepare kwargs for factory
            factory_kwargs = {}
            
            # Redis configuration
            redis_config = persistence_config.get('redis', {})
            if redis_config:
                factory_kwargs['redis_url'] = f"redis://{redis_config.get('host', 'localhost')}:{redis_config.get('port', 6379)}/{redis_config.get('db', 0)}"
            
            # SQLite configuration  
            sqlite_config = persistence_config.get('sqlite', {})
            if sqlite_config:
                db_path = sqlite_config.get('db_path', str(Path.home() / '.gleitzeit' / 'workflows.db'))
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                factory_kwargs['sql_db_path'] = db_path
            
            # Create unified persistence adapter with automatic fallback
            self.persistence_backend = await PersistenceFactory.create(**factory_kwargs)
            
            # Report which backend was selected
            backend_name = type(self.persistence_backend).__name__.replace('Unified', '').replace('Adapter', '')
            click.echo(f"✓ Unified persistence initialized ({backend_name})")
            
            # Set up execution components with event bus (required for proper operation)
            from gleitzeit.events.base import EventBus
            event_bus = EventBus()
            
            queue_manager = QueueManager(persistence=self.persistence_backend, event_bus=event_bus)
            await queue_manager.initialize()
            dependency_resolver = DependencyResolver()
            registry = ProtocolProviderRegistry()
            
            execution_config = self.config.get('execution', {})
            max_concurrent = execution_config.get('max_concurrent_tasks', 5)
            self.execution_engine = ExecutionEngine(
                registry=registry,
                queue_manager=queue_manager,
                dependency_resolver=dependency_resolver,
                persistence=self.persistence_backend,
                max_concurrent_tasks=max_concurrent,
                event_bus=event_bus  # Now properly includes event bus
            )
            
            # Initialize Resource Management (Hub Architecture)
            ollama_hub = None
            docker_hub = None
            
            if enable_resource_management:
                try:
                    # Initialize ResourceManager
                    self.resource_manager = ResourceManager("cli-resources")
                    
                    # Create and add OllamaHub
                    provider_config = self.config.get('providers', {})
                    ollama_config = provider_config.get('ollama', {})
                    if ollama_config.get('enabled', True):
                        ollama_hub = OllamaHub(
                            hub_id="ollama-hub",
                            auto_discover=True,  # Auto-discover running Ollama instances
                            persistence=self.persistence_backend
                        )
                        await ollama_hub.initialize()
                        await self.resource_manager.add_hub("ollama", ollama_hub)
                        click.echo("✓ OllamaHub initialized with auto-discovery")
                    
                    # Create and add DockerHub if configured
                    docker_config = provider_config.get('docker', {})
                    if docker_config.get('enabled', False):
                        docker_hub = DockerHub(
                            hub_id="docker-hub",
                            max_instances=docker_config.get('max_instances', 5),
                            persistence=self.persistence_backend
                        )
                        await docker_hub.initialize()
                        await self.resource_manager.add_hub("docker", docker_hub)
                        click.echo("✓ DockerHub initialized")
                    
                    await self.resource_manager.start()
                    click.echo("✓ Resource management enabled")
                except Exception as e:
                    click.echo(f"⚠️  Resource management initialization failed: {e}")
                    self.resource_manager = None
            else:
                self.resource_manager = None
            
            # Register protocols and providers with hub support
            provider_config = self.config.get('providers', {})
            
            # Python provider
            python_config = provider_config.get('python', {})
            if python_config.get('enabled', True):
                registry.register_protocol(PYTHON_PROTOCOL_V1)
                python_provider = PythonProvider(
                    "cli-python-provider",
                    allow_local=True,
                    resource_manager=self.resource_manager,
                    hub=docker_hub  # Python provider can use Docker hub for isolation
                )
                await python_provider.initialize()
                registry.register_provider("cli-python-provider", "python/v1", python_provider)
                click.echo("✓ Python provider registered")
            
            # Ollama provider with hub
            ollama_config = provider_config.get('ollama', {})
            if ollama_config.get('enabled', True):
                try:
                    registry.register_protocol(LLM_PROTOCOL_V1)
                    ollama_provider = OllamaProvider(
                        "cli-ollama-provider",
                        auto_discover=False,  # Hub handles discovery
                        resource_manager=self.resource_manager,
                        hub=ollama_hub
                    )
                    await ollama_provider.initialize()
                    registry.register_provider("cli-ollama-provider", "llm/v1", ollama_provider)
                    click.echo("✓ Ollama provider registered with hub")
                except Exception as e:
                    click.echo(f"⚠️  Ollama provider failed to initialize: {e}")
            
            # MCP provider
            mcp_config = provider_config.get('mcp', {})
            if mcp_config.get('enabled', True):
                try:
                    registry.register_protocol(MCP_PROTOCOL_V1)
                    mcp_hub = MCPHub(
                        auto_discover=mcp_config.get('auto_discover', False),
                        config_data=mcp_config
                    )
                    mcp_provider = MCPHubProvider(
                        provider_id="cli-mcp-provider",
                        hub=mcp_hub,
                        config_data=mcp_config
                    )
                    await mcp_provider.initialize()
                    registry.register_provider("cli-mcp-provider", "mcp/v1", mcp_provider)
                    click.echo("✓ MCP provider registered")
                except Exception as e:
                    click.echo(f"⚠️  MCP provider failed to initialize: {e}")
            
            # Template provider
            template_config = provider_config.get('template', {})
            
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
            click.echo(f"\n💡 Tip: Start the Web UI to monitor workflows with: gleitzeit serve")
            
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
            elif 'analysis' in result.result:  # Agent analysis field
                display_text = result.result['analysis']
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
        """Clean shutdown of the system including hubs and resource manager"""
        # Use unified shutdown
        await unified_shutdown(
            execution_engine=self.execution_engine,
            resource_manager=self.resource_manager,
            persistence_backend=self.persistence_backend,
            verbose=False  # CLI uses click.echo for output
        )
        
        # CLI-specific output for resource manager
        if self.resource_manager:
            click.echo("✓ Resource manager stopped")


# CLI instance
cli_instance = GleitzeitCLI()


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.version_option(version='0.0.5', prog_name='Gleitzeit')
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
@click.option('--host', default='localhost', help='API server host (default: localhost)')
@click.option('--port', default=8000, type=int, help='API server port (default: 8000)')
@click.option('--local', is_flag=True, help='Run locally without API server')
@click.option('--no-auto-start', is_flag=True, help='Do not auto-start API server if not running')
@click.option('--no-resource-management', is_flag=True, help='Disable hub-based resource management')
@click.option('--auto-discover', is_flag=True, default=True, help='Auto-discover Ollama instances (default: True)')
def run(workflow_file: str, watch: bool, host: str, port: int, local: bool, no_auto_start: bool, 
        no_resource_management: bool, auto_discover: bool):
    """Execute a workflow from a YAML or JSON file (via API by default)"""
    if local:
        # Use the old local execution mode with optional resource management
        enable_rm = not no_resource_management
        return asyncio.run(_run_workflow_local(workflow_file, watch, enable_resource_management=enable_rm))
    else:
        # Use API mode (default) - auto-start server by default unless --no-auto-start is used
        auto_start = not no_auto_start
        return asyncio.run(_run_workflow_api(workflow_file, watch, host, port, auto_start))


async def _run_workflow_local(workflow_file: str, watch: bool, backend: Optional[str] = None, 
                             enable_resource_management: bool = True):
    """Execute workflow locally - auto-start API server if needed"""
    try:
        # Load configuration for server settings
        config = cli_instance.config
        server_config = config.get('server', {})
        api_config = server_config.get('api', {})
        api_host = api_config.get('host', '0.0.0.0')
        api_port_range = api_config.get('port_range', [8000, 8010])
        
        # Check if any API server is running in the port range
        import aiohttp
        api_port = None
        api_running = False
        
        for port in range(api_port_range[0], api_port_range[-1] + 1):
            try:
                api_url = f"http://localhost:{port}"  # Use localhost for client connections
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{api_url}/health", timeout=aiohttp.ClientTimeout(total=0.5)) as resp:
                        if resp.status == 200:
                            # Verify it's actually a Gleitzeit API by checking the response content
                            data = await resp.json()
                            if isinstance(data, dict) and 'status' in data and data['status'] == 'healthy':
                                api_running = True
                                api_port = port
                                click.echo(f"ℹ️  Found running Gleitzeit API at {api_url}")
                                ui_port_range = server_config.get('ui', {}).get('port_range', [8004, 8014])
                                click.echo(f"💡 Tip: View the Web UI at http://localhost:{ui_port_range[0]}")
                                break
            except:
                continue
        
        if not api_running:
            # Find an available port to start the server
            available_port = await _find_available_port(api_host, api_port_range, "API server")
            if not available_port:
                click.echo(f"❌ No available ports in range {api_port_range}")
                return
            
            # Start the API server in the background
            click.echo(f"🚀 No API server found, starting Gleitzeit server on port {available_port}...")
            import subprocess
            import sys
            
            # Start server with --headless flag (no UI for background operation)
            server_cmd = [
                sys.executable, "-m", "gleitzeit.cli.gleitzeit_cli", 
                "serve", "--host", api_host, "--port", str(available_port), "--headless"
            ]
            
            # Set persistence type environment variable if backend specified
            env = os.environ.copy()
            if backend:
                backend_map = {
                    'redis': 'redis',
                    'sqlite': 'sql',
                    'sql': 'sql'
                }
                env['GLEITZEIT_PERSISTENCE_TYPE'] = backend_map.get(backend, backend)
            
            # Start server in background
            server_process = subprocess.Popen(
                server_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env
            )
            
            # Wait for server to be ready
            click.echo("⏳ Waiting for server to start...")
            api_url = f"http://localhost:{available_port}"
            for i in range(30):  # Wait up to 30 seconds
                await asyncio.sleep(1)
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(f"{api_url}/health", timeout=aiohttp.ClientTimeout(total=1)) as resp:
                            if resp.status == 200:
                                click.echo("✅ Server started successfully")
                                click.echo(f"💡 Tip: View the Web UI by running: gleitzeit serve")
                                api_running = True
                                api_port = available_port
                                break
                except:
                    pass
            
            if not api_running:
                click.echo("❌ Failed to start API server")
                if server_process:
                    server_process.terminate()
                return
        
        # Now use API mode to run the workflow with the correct port
        return await _run_workflow_api(workflow_file, watch, "localhost", api_port, start_server=False)
        
    except Exception as e:
        click.echo(f"❌ Workflow execution failed: {e}")
        import logging
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            import traceback
            traceback.print_exc()


async def _check_docker_availability() -> bool:
    """Check if Docker is available and running"""
    import subprocess
    import platform
    
    try:
        # Cross-platform Docker check
        if platform.system() == "Windows":
            # Windows: check if docker.exe is available
            result = subprocess.run(
                ["where", "docker"],
                capture_output=True,
                text=True,
                timeout=2
            )
            docker_found = result.returncode == 0
        else:
            # Unix/Mac: check if docker command exists
            result = subprocess.run(
                ["which", "docker"],
                capture_output=True,
                text=True,
                timeout=2
            )
            docker_found = result.returncode == 0
        
        if not docker_found:
            click.echo("⚠️  Docker not found - Python tasks will run locally without isolation")
            return False
        
        # Check if Docker daemon is running
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            docker_version = result.stdout.strip()
            click.echo(f"🐳 Docker {docker_version} detected - isolated execution available")
            
            # Check Docker daemon socket/port
            info_result = subprocess.run(
                ["docker", "info", "--format", "{{.DockerRootDir}}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if info_result.returncode == 0:
                click.echo(f"   Docker is ready for isolated task execution")
            
            return True
        else:
            click.echo("⚠️  Docker found but daemon not running - starting without Docker support")
            click.echo("   To enable isolated execution, start Docker Desktop/daemon")
            return False
            
    except subprocess.TimeoutExpired:
        click.echo("⚠️  Docker check timed out - starting without Docker support")
        return False
    except Exception as e:
        click.echo(f"⚠️  Could not check Docker status: {e}")
        click.echo("   Starting without Docker support")
        return False


async def _find_available_port(host: str, port_range: List[int], service_name: str = "service") -> Optional[int]:
    """Find an available port in the given range"""
    import socket
    
    start_port, end_port = port_range[0], port_range[-1] if len(port_range) > 1 else port_range[0] + 10
    
    for port in range(start_port, end_port + 1):
        try:
            # Try to bind to the port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.close()
            return port
        except OSError:
            continue
    
    click.echo(f"⚠️  No available ports found for {service_name} in range {start_port}-{end_port}")
    return None


async def _check_api_server(host: str, port: int) -> bool:
    """Check if Gleitzeit API server is running"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://{host}:{port}/health", timeout=2.0)
            if response.status_code == 200:
                # Verify it's actually a Gleitzeit API
                data = response.json()
                return isinstance(data, dict) and 'status' in data and data['status'] == 'healthy'
            return False
    except:
        return False


async def _start_api_server(host: str, port: int) -> Optional[subprocess.Popen]:
    """Start API server in background"""
    try:
        # Start server process in background
        process = subprocess.Popen(
            [sys.executable, "-m", "gleitzeit.cli.gleitzeit_cli", "serve", "--host", host, "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait for server to start
        click.echo(f"⏳ Starting API server at {host}:{port}...")
        for i in range(30):  # Wait up to 30 seconds
            if await _check_api_server(host, port):
                click.echo(f"✅ API server started successfully")
                return process
            await asyncio.sleep(1)
        
        # If server didn't start, terminate the process
        process.terminate()
        click.echo(f"❌ Failed to start API server")
        return None
    except Exception as e:
        click.echo(f"❌ Error starting API server: {e}")
        return None


async def _run_workflow_api(workflow_file: str, watch: bool, host: str, port: int, start_server: bool):
    """Execute workflow via API"""
    api_url = f"http://{host}:{port}"
    server_process = None
    
    try:
        # Check if API server is running
        if not await _check_api_server(host, port):
            if start_server:
                server_process = await _start_api_server(host, port)
                if not server_process:
                    click.echo(f"❌ Could not start API server. Please start it manually with: gleitzeit serve --host {host} --port {port}")
                    return
            else:
                click.echo(f"❌ API server not running at {host}:{port}")
                click.echo(f"   Start it manually with: gleitzeit serve --host {host} --port {port}")
                click.echo(f"   Or remove --no-auto-start flag to start it automatically")
                return
        
        # Load workflow file
        with open(workflow_file, 'r') as f:
            workflow_content = yaml.safe_load(f) if workflow_file.endswith('.yaml') else json.load(f)
        
        # Convert workflow to API format
        api_workflow = {
            "name": workflow_content.get("name", "CLI Workflow"),
            "description": workflow_content.get("description", ""),
            "tasks": []
        }
        
        for task in workflow_content.get("tasks", []):
            # Determine protocol from method or task
            method = task.get("method", "")
            if not method and "protocol" in task:
                protocol = task["protocol"]
            elif "/" in method:
                protocol = method.split("/")[0] + "/v1"
            else:
                # Guess based on content
                params = task.get("params", task.get("parameters", {}))
                if "model" in params or "messages" in params:
                    protocol = "llm/v1"
                elif "file" in params or "code" in params:
                    protocol = "python/v1"
                elif "tool" in method:
                    protocol = "mcp/v1"
                else:
                    protocol = "python/v1"
            
            # Handle priority
            priority = task.get("priority", "normal")
            if isinstance(priority, int):
                priority_map = {0: "low", 1: "normal", 2: "high", 3: "urgent"}
                priority = priority_map.get(priority, "normal")
            elif isinstance(priority, str):
                valid_priorities = ["low", "normal", "high", "urgent", "critical"]
                if priority.lower() not in valid_priorities:
                    priority = "normal"
                else:
                    priority = priority.lower()
            
            api_task = {
                "id": task.get("id") or task.get("name") or f"task_{len(api_workflow['tasks'])}",
                "name": task.get("name", task.get("id", f"Task {len(api_workflow['tasks']) + 1}")),
                "protocol": protocol,
                "method": method or f"{protocol.split('/')[0]}/execute",
                "params": task.get("params", task.get("parameters", {})),
                "dependencies": task.get("dependencies", []),
                "priority": priority
            }
            
            # Add retry config if present
            if "retry" in task:
                api_task["retry"] = task["retry"]
            
            api_workflow["tasks"].append(api_task)
        
        click.echo(f"📄 Submitting workflow: {api_workflow['name']}")
        click.echo(f"   Tasks: {len(api_workflow['tasks'])}")
        click.echo(f"   API Server: {api_url}")
        
        # Submit workflow
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{api_url}/workflows",
                json=api_workflow,
                timeout=30.0
            )
            
            if response.status_code != 200:
                click.echo(f"❌ Failed to submit workflow: {response.text}")
                return
            
            result = response.json()
            workflow_id = result["workflow_id"]
            click.echo(f"✅ Workflow submitted: {workflow_id}")
            
            if watch:
                click.echo("📊 Watching execution...")
                # Poll for status
                while True:
                    await asyncio.sleep(2)
                    status_response = await client.get(f"{api_url}/workflows/{workflow_id}")
                    if status_response.status_code != 200:
                        click.echo(f"❌ Failed to get status: {status_response.text}")
                        break
                    
                    status = status_response.json()
                    
                    # Display progress
                    click.echo(f"\r   Status: {status['status']} | Completed: {status['tasks_completed']}/{status['tasks_total']} | Failed: {status['tasks_failed']}", nl=False)
                    
                    if status["status"] in ["completed", "failed", "cancelled"]:
                        click.echo()  # New line
                        break
                
                # Display final results
                if status["status"] == "completed":
                    click.echo("\n✅ Workflow completed successfully!")
                    if status.get("results"):
                        click.echo("\n📊 Task Results:")
                        for task_id, task_result in status["results"].items():
                            if task_result["status"] == "completed":
                                click.echo(f"   ✓ {task_id}: Success")
                            else:
                                click.echo(f"   ✗ {task_id}: {task_result.get('error', 'Failed')}")
                else:
                    click.echo(f"\n❌ Workflow {status['status']}")
            else:
                click.echo(f"\n💡 Check status with: curl {api_url}/workflows/{workflow_id}")
                
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        if logger.isEnabledFor(logging.DEBUG):
            import traceback
            traceback.print_exc()
    finally:
        # If we started the server and not watching, keep it running
        if server_process and not watch:
            click.echo(f"\n📌 API server is running in background at {api_url}")
            click.echo("   Stop it with: pkill -f 'gleitzeit.*serve'")


@cli.command()
@click.option('--backend', type=click.Choice(['sqlite', 'redis']), 
              help='Persistence backend to query')
@click.option('--resources', is_flag=True, help='Show resource manager status')
def status(backend: Optional[str], resources: bool):
    """Show system status and recent workflows"""
    return asyncio.run(_show_status(backend, resources))


async def _show_status(backend: Optional[str], resources: bool = False):
    """Show status implementation with optional resource information"""
    try:
        if backend:
            cli_instance.config['persistence']['backend'] = backend
        
        if not await cli_instance._setup_system(enable_resource_management=resources):
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
        
        # Show resource manager status if requested
        if resources and cli_instance.resource_manager:
            click.echo("\n🔧 Resource Manager Status:")
            try:
                metrics = await cli_instance.resource_manager.get_global_metrics()
                click.echo(f"   Total resources: {metrics.get('total_resources', 0)}")
                click.echo(f"   Active resources: {metrics.get('active_resources', 0)}")
                
                # Show hub-specific information
                hubs = await cli_instance.resource_manager.get_hubs()
                for hub_name, hub in hubs.items():
                    # Get instance count and health info
                    instances = await hub.list_instances()
                    healthy_count = sum(1 for i in instances if i.status == ResourceStatus.HEALTHY)
                    
                    click.echo(f"\n   📦 {hub_name.upper()} Hub:")
                    click.echo(f"      Instances: {len(instances)}")
                    click.echo(f"      Healthy: {healthy_count}")
                    
                    # Get aggregated metrics if available
                    try:
                        metrics_summary = await hub.get_metrics_summary()
                        if metrics_summary:
                            if 'total_cpu' in metrics_summary:
                                click.echo(f"      Total CPU: {metrics_summary['total_cpu']:.1f}%")
                            if 'total_memory' in metrics_summary:
                                click.echo(f"      Total Memory: {metrics_summary['total_memory']:.0f} MB")
                    except Exception:
                        pass  # Metrics not available
            except Exception as e:
                click.echo(f"   ⚠️  Could not load resource metrics: {e}")
        
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
@click.option('--no-resource-management', is_flag=True, help='Disable hub-based resource management')
def batch(directory: str, pattern: str, prompt: str, model: str, vision: bool, output: Optional[str], 
          no_resource_management: bool):
    """Process multiple files in batch"""
    enable_rm = not no_resource_management
    return asyncio.run(_batch_process(directory, pattern, prompt, model, vision, output, enable_rm))


@cli.command()
@click.option('--host', '-h', default='0.0.0.0', help='Host to bind the API server to')
@click.option('--port', '-p', default=8000, type=int, help='Port to bind the API server to')
@click.option('--reload', is_flag=True, help='Enable auto-reload for development')
@click.option('--workers', '-w', default=1, type=int, help='Number of worker processes')
@click.option('--headless', is_flag=True, help='Run without the Web UI')
@click.option('--ui-port', default=8004, type=int, help='Port for the Web UI (default: 8004)')
@click.option('--ui-host', default='127.0.0.1', help='Host for the Web UI (default: 127.0.0.1)')
def serve(host: str, port: int, reload: bool, workers: int, headless: bool, ui_port: int, ui_host: str):
    """Start the Gleitzeit REST API server (with Web UI by default)"""
    # Run the async serve function
    asyncio.run(_async_serve(host, port, reload, workers, headless, ui_port, ui_host))


async def _async_serve(host: str, port: int, reload: bool, workers: int, headless: bool, ui_port: int, ui_host: str):
    """Async function to run both API and UI servers"""
    try:
        import uvicorn
    except ImportError:
        click.echo("❌ Error: uvicorn is not installed. Install it with: pip install uvicorn")
        sys.exit(1)
    
    # Check Docker availability for isolated execution support
    docker_available = await _check_docker_availability()
    
    # Set environment variable for the API to know Docker status
    import os
    os.environ['GLEITZEIT_DOCKER_AVAILABLE'] = 'true' if docker_available else 'false'
    
    # Load configuration for port ranges
    config = cli_instance.config
    server_config = config.get('server', {})
    api_config = server_config.get('api', {})
    ui_config = server_config.get('ui', {})
    
    # Find available API port if the default is in use
    api_port_range = api_config.get('port_range', [port, port + 10])
    if port not in api_port_range:
        # User specified a specific port outside the range, use it
        actual_api_port = port
    else:
        # Try to find an available port in the range
        actual_api_port = await _find_available_port(host, api_port_range, "API server")
        if not actual_api_port:
            click.echo(f"❌ No available ports for API server in range {api_port_range}")
            sys.exit(1)
    
    click.echo(f"🚀 Starting Gleitzeit API server...")
    click.echo(f"   Host: {host}")
    click.echo(f"   Port: {actual_api_port}")
    if workers > 1:
        click.echo(f"   Workers: {workers}")
    if reload:
        click.echo(f"   Reload: enabled (development mode)")
    click.echo(f"   Mode: {'headless' if headless else 'with Web UI'}")
    click.echo(f"\n📍 API will be available at: http://{host if host != '0.0.0.0' else 'localhost'}:{actual_api_port}")
    click.echo("📚 API documentation available at: /docs")
    
    # Start UI server in background if not headless
    ui_server = None
    ui_task = None
    actual_ui_port = ui_port
    
    if not headless:
        try:
            from gleitzeit.ui.api.app import app as ui_app
            
            # Find available UI port
            ui_port_range = ui_config.get('port_range', [ui_port, ui_port + 10])
            if ui_port not in ui_port_range:
                # User specified a specific port outside the range, use it
                actual_ui_port = ui_port
            else:
                # Try to find an available port in the range
                actual_ui_port = await _find_available_port(ui_host, ui_port_range, "UI server")
                if not actual_ui_port:
                    click.echo(f"⚠️  No available ports for UI in range {ui_port_range}, running headless")
                    headless = True
            
            if not headless:
                # Set the API URL environment variable for the UI
                import os
                api_host = 'localhost' if host == '0.0.0.0' else host
                os.environ['GLEITZEIT_API_URL'] = f"http://{api_host}:{actual_api_port}"
                
                click.echo(f"\n🎨 Starting Web UI...")
                click.echo(f"   UI Host: {ui_host}")
                click.echo(f"   UI Port: {actual_ui_port}")
                click.echo(f"   UI URL: http://{ui_host if ui_host != '0.0.0.0' else 'localhost'}:{actual_ui_port}")
            
            if not headless:
                # Create UI server config
                ui_config_uvicorn = uvicorn.Config(
                    app=ui_app,
                    host=ui_host,
                    port=actual_ui_port,
                    log_level="warning"  # Less verbose for UI
                )
                ui_server = uvicorn.Server(ui_config_uvicorn)
                
                # Start UI server in background task
                ui_task = asyncio.create_task(ui_server.serve())
            
        except ImportError as e:
            click.echo(f"⚠️  Web UI not available: {e}")
            click.echo("   Running in headless mode")
            headless = True
    
    click.echo("\nPress CTRL+C to stop the servers\n")
    
    try:
        # Import the FastAPI app
        from gleitzeit.api.main import app
        
        # Create API server config
        api_config_uvicorn = uvicorn.Config(
            app="gleitzeit.api.main:app",
            host=host,
            port=actual_api_port,
            reload=reload,
            workers=workers if not reload else 1,  # Can't use multiple workers with reload
            log_level="info"
        )
        
        # Run the API server (this blocks)
        if reload:
            # For reload mode, use uvicorn.run directly
            uvicorn.run(
                "gleitzeit.api.main:app",
                host=host,
                port=actual_api_port,
                reload=reload,
                log_level="info"
            )
        else:
            # For production mode, use Server
            api_server = uvicorn.Server(api_config_uvicorn)
            await api_server.serve()
            
    except KeyboardInterrupt:
        click.echo("\n✅ Shutting down servers...")
        
        # Shutdown UI server if running
        if ui_server and ui_task:
            ui_server.should_exit = True
            await ui_task
            
        click.echo("✅ Servers stopped")
    except Exception as e:
        click.echo(f"❌ Error starting server: {e}")
        
        # Cleanup UI server if needed
        if ui_server and ui_task:
            ui_server.should_exit = True
            try:
                await ui_task
            except:
                pass
                
        sys.exit(1)


async def _batch_process(directory: str, pattern: str, prompt: str, model: str, vision: bool, 
                        output: Optional[str], enable_resource_management: bool = True):
    """Process files in batch using API server"""
    try:
        # Use GleitzeitClient to connect to API server (auto-start if needed)
        from gleitzeit import GleitzeitClient
        
        click.echo(f"📁 Scanning directory: {directory}")
        click.echo(f"   Pattern: {pattern}")
        
        # Determine method based on vision flag
        method = "llm/vision" if vision else "llm/chat"
        
        # Use configured default model if not specified
        if model == 'llama3.2:latest':  # Default value from click option
            config = cli_instance.config
            ollama_config = config.get('providers', {}).get('ollama', {})
            default_models = ollama_config.get('default_models', {})
            if vision:
                model = default_models.get('vision', 'llava:latest')
            else:
                model = default_models.get('chat', 'llama3.2:latest')
        
        # Use client to process batch
        click.echo("⏳ Processing files...")
        async with GleitzeitClient(mode="auto") as client:
            # Use client's batch_process method if available
            if hasattr(client, 'batch_process'):
                result = await client.batch_process(
                    directory=directory,
                    pattern=pattern,
                    method=method,
                    prompt=prompt,
                    model=model
                )
            else:
                # Fallback: create batch processor and use client's execution
                from gleitzeit.core.batch_processor import BatchProcessor
                batch_processor = BatchProcessor()
                
                # Create workflow from batch
                workflow = await batch_processor.create_batch_workflow(
                    directory=directory,
                    pattern=pattern,
                    method=method,
                    prompt=prompt,
                    model=model
                )
                
                # Submit workflow via client
                import tempfile
                import yaml
                with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                    yaml.dump(workflow.to_dict(), f)
                    workflow_file = f.name
                
                result = await client.run_workflow(workflow_file, watch=True)
                
                import os
                os.unlink(workflow_file)
        
        # Display results
        click.echo(f"\n✅ Batch processing complete!")
        
        # Handle different result formats
        if isinstance(result, dict):
            # Result from client.batch_process or run_workflow
            if 'workflow_id' in result:
                click.echo(f"   Workflow ID: {result['workflow_id']}")
                click.echo(f"   Status: {result.get('status', 'submitted')}")
                
                # If we have task results, show them
                if 'results' in result:
                    results = result['results']
                    click.echo(f"   Total tasks: {len(results)}")
                    
                    # Show individual results for small batches
                    if len(results) <= 10:
                        click.echo("\n📊 Results:")
                        for task_id, task_result in results.items():
                            if isinstance(task_result, dict):
                                status = task_result.get('status', 'unknown')
                                if status == 'completed':
                                    response = task_result.get('result', {}).get('response', 'No response')
                                    # Truncate long content
                                    if len(response) > 200:
                                        response = response[:200] + "..."
                                    click.echo(f"   ✅ {task_id}: {response}")
                                else:
                                    error = task_result.get('error', 'Unknown error')
                                    click.echo(f"   ❌ {task_id}: {error}")
            else:
                # Other dict format
                click.echo(f"   Result: {result}")
        else:
            # Legacy BatchResult object
            if hasattr(result, 'batch_id'):
                click.echo(f"   Batch ID: {result.batch_id}")
                click.echo(f"   Total files: {result.total_files}")
                click.echo(f"   Successful: {result.successful} ({result.successful/result.total_files*100:.1f}%)")
                click.echo(f"   Failed: {result.failed}")
                click.echo(f"   Processing time: {result.processing_time:.2f}s")
        
        # Save output if requested
        if output:
            output_path = Path(output)
            import json
            if output_path.suffix == '.md':
                # Create markdown output
                md_content = f"# Batch Processing Results\n\n"
                if isinstance(result, dict):
                    md_content += f"## Workflow ID: {result.get('workflow_id', 'N/A')}\n\n"
                    md_content += f"Status: {result.get('status', 'N/A')}\n\n"
                    if 'results' in result:
                        md_content += "### Results\n\n"
                        for task_id, task_result in result['results'].items():
                            md_content += f"- **{task_id}**: {task_result}\n"
                output_path.write_text(md_content)
                click.echo(f"\n💾 Results saved to: {output_path} (Markdown)")
            else:
                output_path.write_text(json.dumps(result, indent=2))
                click.echo(f"\n💾 Results saved to: {output_path} (JSON)")
        
    except Exception as e:
        click.echo(f"❌ Batch processing failed: {e}")
        logger.error(f"Batch processing error: {e}", exc_info=True)


@cli.command()
@click.option('--port', default=8004, help='UI server port')
@click.option('--host', default='127.0.0.1', help='UI server host')
@click.option('--browser', is_flag=True, help='Open browser automatically')
def ui(port: int, host: str, browser: bool):
    """Start the Web UI for monitoring workflows and tasks"""
    asyncio.run(_run_ui(port, host, browser))


async def _run_ui(port: int, host: str, browser: bool):
    """Run the UI server with the current Gleitzeit system"""
    import uvicorn
    from pathlib import Path
    import webbrowser
    
    click.echo(f"🚀 Starting Gleitzeit Web UI on http://{host}:{port}")
    
    try:
        # Import the app from gleitzeit package
        from gleitzeit.ui.api.app import app
        
        # Open browser if requested
        if browser:
            webbrowser.open(f"http://{host}:{port}")
        
        # Run the UI server
        config = uvicorn.Config(
            app=app,
            host=host,
            port=port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        
        click.echo(f"✅ Gleitzeit UI running at http://{host}:{port}")
        click.echo("Press Ctrl+C to stop the server")
        
        await server.serve()
        
    except ImportError as e:
        click.echo(f"❌ Error importing UI app: {e}")
        click.echo("Make sure all UI dependencies are installed")
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Error starting UI server: {e}")
        sys.exit(1)


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