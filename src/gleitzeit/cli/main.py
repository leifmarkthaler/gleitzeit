#!/usr/bin/env python3
"""
Gleitzeit CLI - Clean, SystemManager-integrated command-line interface
"""

import asyncio
import click
import httpx
import json
import yaml
import sys
import subprocess
import time
import os
import logging
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import TaskStatus, WorkflowStatus
from .workflow import load_workflow, validate_workflow_file
from .auth import auth as auth_group

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GleitzeitCLI:
    """CLI client that can use SystemManager directly or via API"""
    
    def __init__(self, host: str = "localhost", port: int = 8000, mode: str = "auto"):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.mode = mode  # "native", "api", or "auto"
        # Use httpx with cookie support for stateless auth when in API mode
        self.client = httpx.AsyncClient(
            timeout=60.0,
            cookies=httpx.Cookies()  # Cookie jar for session management
        )
        self.gleitzeit_client = None
        self.system_manager = None
        
    async def __aenter__(self):
        await self.ensure_server()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
        if self.gleitzeit_client:
            await self.gleitzeit_client.shutdown()
    
    async def ensure_server(self) -> bool:
        """Ensure SystemManager server is running"""
        import shutil
        import platform

        if await self.check_server():
            click.echo("✅ SystemManager server already running")
            self.gleitzeit_client = GleitzeitClient(
                mode=ClientMode.API,
                api_host=self.host,
                api_port=self.port
            )
            return True

        click.echo("🚀 Starting SystemManager server...")

        # Prepare environment with config from gleitzeit.yaml if exists
        import os
        import yaml
        env = os.environ.copy()

        # Load project-level configuration if available
        config_file = "gleitzeit.yaml"
        if os.path.exists(config_file):
            try:
                with open(config_file) as f:
                    config = yaml.safe_load(f)
                    if config:
                        click.echo(f"Loading configuration from {config_file}")
                        for key, value in config.items():
                            # Convert key to environment variable format
                            env_key = f"GLEITZEIT_{key.upper()}"
                            # Only set if not already in environment (env vars take precedence)
                            if env_key not in env:
                                env[env_key] = str(value)
            except Exception as e:
                click.echo(f"Warning: Could not load {config_file}: {e}", err=True)

        # Determine the Python command (python or python3)
        python_cmd = sys.executable or "python"

        # Try to use gleitzeit CLI command first (preferred)
        gleitzeit_cmd = shutil.which('gleitzeit')

        # On Windows, also check for .cmd and .exe versions
        if not gleitzeit_cmd and platform.system() == 'Windows':
            gleitzeit_cmd = shutil.which('gleitzeit.cmd') or shutil.which('gleitzeit.exe')

        if gleitzeit_cmd:
            cmd = [gleitzeit_cmd, "serve",
                   "--host", self.host,
                   "--port", str(self.port),
                   "--headless"]  # No UI needed for CLI operations

            # On Windows, use shell=True for .cmd files
            shell = platform.system() == 'Windows' and gleitzeit_cmd.endswith('.cmd')

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,  # Pass the enhanced environment
                shell=shell
            )
        else:
            # Fallback to direct uvicorn if CLI not available
            process = subprocess.Popen(
                [python_cmd, "-m", "uvicorn", "gleitzeit.api.main:app",
                 "--host", self.host, "--port", str(self.port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env  # Pass the enhanced environment
            )

        for i in range(30):
            await asyncio.sleep(1)
            if await self.check_server():
                click.echo("✅ SystemManager server started")
                self.gleitzeit_client = GleitzeitClient(
                    mode=ClientMode.API,
                    api_host=self.host,
                    api_port=self.port
                )
                return True

        click.echo("❌ Failed to start SystemManager server", err=True)
        return False
    
    async def check_server(self) -> bool:
        """Check if server is running"""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except:
            return False
    
    # API Methods
    async def submit_workflow(self, workflow_file: Path) -> Dict[str, Any]:
        """Submit a workflow"""
        # Load workflow file without validation - let server validate
        with open(workflow_file, 'r') as f:
            if workflow_file.suffix.lower() in ['.yaml', '.yml']:
                workflow = yaml.safe_load(f)
            else:
                workflow = json.load(f)
        
        response = await self.client.post(
            f"{self.base_url}/workflows/",
            json={"workflow": workflow}
        )
        response.raise_for_status()
        return response.json()
    
    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status"""
        response = await self.client.get(
            f"{self.base_url}/workflows/{workflow_id}"
        )
        response.raise_for_status()
        return response.json()
    
    async def list_workflows(self, limit: int = 10) -> list:
        """List workflows"""
        response = await self.client.get(
            f"{self.base_url}/workflows",
            params={"limit": limit}
        )
        response.raise_for_status()
        return response.json()
    
    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status"""
        response = await self.client.get(f"{self.base_url}/status")
        response.raise_for_status()
        return response.json()
    
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login and receive session cookie (stateless)"""
        response = await self.client.post(
            f"{self.base_url}/auth/login",
            json={"username": username, "password": password}
        )
        response.raise_for_status()
        # Cookie automatically stored in client.cookies
        return response.json()
    
    async def logout(self) -> Dict[str, Any]:
        """Logout and clear session cookie"""
        response = await self.client.post(f"{self.base_url}/auth/logout")
        response.raise_for_status()
        # Cookie automatically cleared
        return response.json()


# CLI Commands
@click.group()
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
@click.pass_context
def cli(ctx, host: str, port: int):
    """Gleitzeit - Distributed workflow orchestration with SystemManager"""
    ctx.ensure_object(dict)
    ctx.obj['cli'] = GleitzeitCLI(host, port)


# Add auth subcommand group
cli.add_command(auth_group)


@cli.command()
@click.argument('workflow_file', type=click.Path(exists=True))
@click.option('--wait', is_flag=True, help='Wait for completion')
@click.pass_context
def run(ctx, workflow_file: str, wait: bool):
    """Run a workflow"""
    async def _run():
        async with ctx.obj['cli'] as cli:
            try:
                workflow_path = Path(workflow_file)
                click.echo(f"📋 Submitting workflow: {workflow_path.name}")
                
                # Server will validate workflow with all providers available
                result = await cli.submit_workflow(workflow_path)
                workflow_id = result.get('workflow_id', result.get('id'))
                
                click.echo(f"✅ Workflow submitted: {workflow_id}")
                
                if wait:
                    click.echo("⏳ Waiting for completion...")
                    while True:
                        await asyncio.sleep(2)
                        status = await cli.get_workflow_status(workflow_id)
                        state = status.get('status', 'unknown')
                        
                        if state == WorkflowStatus.COMPLETED.value:
                            click.echo("✅ Workflow completed successfully!")
                            break
                        elif state == WorkflowStatus.FAILED.value:
                            click.echo(f"❌ Workflow failed: {status.get('error')}")
                            sys.exit(1)
                        elif state == WorkflowStatus.CANCELLED.value:
                            click.echo("⚠️ Workflow cancelled")
                            break
                            
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_run())


@cli.command()
@click.argument('workflow_id')
@click.pass_context
def status(ctx, workflow_id: str):
    """Get workflow status"""
    async def _status():
        async with ctx.obj['cli'] as cli:
            try:
                status = await cli.get_workflow_status(workflow_id)
                
                state = status.get('status', 'unknown')
                icon = {
                    WorkflowStatus.COMPLETED.value: '✅', WorkflowStatus.FAILED.value: '❌', WorkflowStatus.RUNNING.value: '🔄',
                    WorkflowStatus.PENDING.value: '⏳', WorkflowStatus.CANCELLED.value: '⚠️', WorkflowStatus.PAUSED.value: '⏸️'
                }.get(state, '❓')
                
                click.echo(f"{icon} Workflow: {workflow_id}")
                click.echo(f"   Status: {state.upper()}")
                
                if status.get('created_at'):
                    click.echo(f"   Created: {status['created_at']}")
                
                tasks = status.get('tasks', [])
                if tasks:
                    completed = sum(1 for t in tasks if t.get('status') == TaskStatus.COMPLETED.value)
                    click.echo(f"   Tasks: {completed}/{len(tasks)} completed")
                    
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_status())


@cli.command()
@click.argument('workflow_id')
@click.option('--reason', help='Reason for pausing')
@click.option('--rewind-to-task', help='Task ID to rewind to')
@click.option('--rewind-to-step', type=int, help='Step number to rewind to (1-based)')
@click.pass_context
def pause(ctx, workflow_id: str, reason: Optional[str], rewind_to_task: Optional[str], rewind_to_step: Optional[int]):
    """Pause a running workflow with optional rewind"""
    async def _pause():
        async with ctx.obj['cli'] as cli:
            try:
                # Initialize the client if needed
                if cli.gleitzeit_client:
                    await cli.gleitzeit_client.initialize()
                    
                    # Call pause with optional rewind
                    result = await cli.gleitzeit_client.pause_workflow(
                        workflow_id=workflow_id,
                        rewind_to_task=rewind_to_task,
                        rewind_to_step=rewind_to_step,
                        reason=reason
                    )
                    
                    if result.get('status') == WorkflowStatus.PAUSED.value:
                        click.echo(f"⏸️  Workflow {workflow_id} paused")
                        
                        if result.get('cancelled_tasks'):
                            click.echo(f"   Cancelled tasks: {result['cancelled_tasks']}")
                        
                        if result.get('rewind_task_id'):
                            click.echo(f"   Rewound to task: {result['rewind_task_id']}")
                        elif result.get('rewind_point') is not None:
                            click.echo(f"   Rewound to step: {result['rewind_point'] + 1}")
                            
                        if result.get('reset_tasks'):
                            click.echo(f"   Tasks to rerun: {result['reset_tasks']}")
                    else:
                        click.echo(f"❌ Failed to pause workflow: {result}")
                else:
                    # Fallback to direct API call
                    request_data = {}
                    if rewind_to_task:
                        request_data['rewind_to'] = rewind_to_task
                    elif rewind_to_step:
                        request_data['rewind_to_step'] = rewind_to_step
                    if reason:
                        request_data['reason'] = reason
                        
                    response = await cli.client.post(
                        f"{cli.base_url}/workflows/{workflow_id}/pause",
                        json=request_data
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    click.echo(f"⏸️  Workflow {workflow_id} paused")
                    if result.get('reset_tasks'):
                        click.echo(f"   Tasks to rerun: {result['reset_tasks']}")
                        
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_pause())


@cli.command()
@click.argument('workflow_id')
@click.pass_context
def resume(ctx, workflow_id: str):
    """Resume a paused workflow"""
    async def _resume():
        async with ctx.obj['cli'] as cli:
            try:
                # Initialize the client if needed
                if cli.gleitzeit_client:
                    await cli.gleitzeit_client.initialize()
                    
                    result = await cli.gleitzeit_client.resume_workflow(workflow_id)
                    
                    if result.get('status') == WorkflowStatus.RUNNING.value:
                        click.echo(f"▶️  Workflow {workflow_id} resumed")
                        
                        if result.get('requeued_tasks'):
                            click.echo(f"   Requeued tasks: {result['requeued_tasks']}")
                    else:
                        click.echo(f"❌ Failed to resume workflow: {result}")
                else:
                    # Fallback to direct API call
                    response = await cli.client.post(
                        f"{cli.base_url}/workflows/{workflow_id}/resume"
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    click.echo(f"▶️  Workflow {workflow_id} resumed")
                    if result.get('requeued_tasks'):
                        click.echo(f"   Requeued tasks: {result['requeued_tasks']}")
                        
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_resume())


@cli.command('pause-status')
@click.argument('workflow_id')
@click.pass_context
def pause_status(ctx, workflow_id: str):
    """Get pause status and metadata for a workflow"""
    async def _pause_status():
        async with ctx.obj['cli'] as cli:
            try:
                # Initialize the client if needed
                if cli.gleitzeit_client:
                    await cli.gleitzeit_client.initialize()
                    
                    result = await cli.gleitzeit_client.get_pause_status(workflow_id)
                else:
                    # Fallback to direct API call
                    response = await cli.client.get(
                        f"{cli.base_url}/workflows/{workflow_id}/pause-status"
                    )
                    response.raise_for_status()
                    result = response.json()
                
                if result.get('paused'):
                    click.echo(f"⏸️  Workflow {workflow_id} is PAUSED")
                    click.echo(f"   Paused at: {result.get('paused_at', 'Unknown')}")
                    click.echo(f"   Paused by: {result.get('paused_by', 'Unknown')}")
                    
                    if result.get('pause_reason'):
                        click.echo(f"   Reason: {result['pause_reason']}")
                        
                    if result.get('rewind_task_id'):
                        click.echo(f"   Rewind to task: {result['rewind_task_id']}")
                    elif result.get('rewind_point') is not None:
                        click.echo(f"   Rewind to step: {result['rewind_point'] + 1}")
                        
                    if result.get('cancelled_tasks'):
                        click.echo(f"   Cancelled tasks: {result['cancelled_tasks']}")
                        
                    if result.get('reset_tasks'):
                        click.echo(f"   Tasks to rerun: {result['reset_tasks']}")
                        
                    if result.get('preserved_results'):
                        click.echo(f"   Preserved results: {len(result['preserved_results'])} tasks")
                else:
                    click.echo(f"▶️  Workflow {workflow_id} is NOT paused")
                    
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_pause_status())


@cli.command()
@click.option('--limit', default=10, help='Number to show')
@click.pass_context
def list(ctx, limit: int):
    """List recent workflows"""
    async def _list():
        async with ctx.obj['cli'] as cli:
            try:
                workflows = await cli.list_workflows(limit)
                
                if not workflows:
                    click.echo("No workflows found")
                    return
                
                click.echo("Recent Workflows:")
                for wf in workflows:
                    wf_id = wf.get('id', wf.get('workflow_id'))
                    status = wf.get('status', 'unknown')
                    name = wf.get('name', 'Unnamed')
                    
                    icon = {
                        WorkflowStatus.COMPLETED.value: '✅', WorkflowStatus.FAILED.value: '❌', WorkflowStatus.RUNNING.value: '🔄',
                        WorkflowStatus.PENDING.value: '⏳', WorkflowStatus.CANCELLED.value: '⚠️', WorkflowStatus.PAUSED.value: '⏸️'
                    }.get(status, '❓')
                    
                    click.echo(f"{icon} {wf_id[:8]}... | {name} | {status}")
                    
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_list())


@cli.command()
@click.pass_context
def system(ctx):
    """Get system status"""
    async def _system():
        async with ctx.obj['cli'] as cli:
            try:
                status = await cli.get_system_status()
                
                click.echo("System Status:")
                click.echo(f"  Version: {status.get('version', 'unknown')}")
                click.echo(f"  API: ✅ Running on {ctx.obj['cli'].base_url}")
                
                if status.get('system_manager'):
                    sm = status['system_manager']
                    click.echo(f"  SystemManager: {sm.get('status', 'unknown')}")
                    
                    if sm.get('components'):
                        click.echo("  Components:")
                        for comp, info in sm['components'].items():
                            click.echo(f"    • {comp}: {info}")
                
                if status.get('persistence'):
                    click.echo(f"  Persistence: {status['persistence'].get('type', 'unknown')}")
                    
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_system())


@cli.command()
@click.option('--port', default=8001, help='UI port')
@click.option('--api-host', default='localhost', help='API server host')
@click.option('--api-port', default=8000, help='API server port')
def ui(port: int, api_host: str, api_port: int):
    """Start only the Web UI (connect to existing API server)"""
    click.echo(f"🌐 Starting Gleitzeit Web UI on port {port}")
    click.echo(f"   Connecting to API at: http://{api_host}:{api_port}")
    
    import uvicorn
    from gleitzeit.ui.api.app import app
    
    # Set environment variable for UI to know API endpoint
    os.environ['GLEITZEIT_API_URL'] = f"http://{api_host}:{api_port}"
    
    uvicorn.run(app, host='0.0.0.0', port=port)


@cli.command()
@click.option('--workers', '-w', default=1, help='Number of workers to start')
@click.option('--type', 'worker_type', type=click.Choice(['stream', 'timer', 'signal', 'auto']),
              default='auto', help='Worker type: stream (events), timer (timers), signal (signals), or auto')
@click.option('--priority', default=5, help='Leader priority for timer/signal workers (0-10)')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def worker(workers: int, worker_type: str, priority: int, host: str, port: int):
    """Start Kafka-style workers for event/timer/signal processing"""
    import httpx
    from gleitzeit.persistence.factory import PersistenceFactory
    from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
    from gleitzeit.workers.stream_worker import StreamWorker
    from gleitzeit.workers.timer_worker import TimerWorker
    from gleitzeit.workers.signal_worker import SignalWorker

    async def run_workers():
        # Check API is running
        try:
            response = httpx.get(f"http://{host}:{port}/health", timeout=2)
            if response.status_code != 200:
                click.echo(f"❌ API server not reachable at {host}:{port}")
                click.echo("   Run 'gleitzeit serve' first")
                return
        except:
            click.echo(f"❌ Cannot connect to API at {host}:{port}")
            click.echo("   Run 'gleitzeit serve' first")
            return

        # Initialize system components
        persistence = await PersistenceFactory.create()
        system_manager = ModularStreamSystemManager(
            instance_id=f"worker-pool-{uuid.uuid4().hex[:8]}",
            persistence=persistence
        )
        await system_manager.initialize()

        # Determine worker type
        actual_type = worker_type
        if worker_type == 'auto':
            # Check if dedicated timer and signal workers exist
            timer_exists = await persistence.redis.exists("timer:leader")
            signal_exists = await persistence.redis.exists("signal:leader")

            if timer_exists and signal_exists:
                actual_type = 'stream'
                click.echo("🔍 Detected timer and signal workers, starting stream workers only")
            elif timer_exists:
                # Need signal worker
                actual_type = 'mixed-signal'
                click.echo("🔍 Timer worker found, starting signal + stream workers")
            elif signal_exists:
                # Need timer worker
                actual_type = 'mixed-timer'
                click.echo("🔍 Signal worker found, starting timer + stream workers")
            else:
                # Need both timer and signal
                actual_type = 'mixed-all'
                click.echo("🔍 No dedicated workers found, starting mixed mode (timer + signal + stream)")

        # Start workers based on type
        worker_tasks = []

        if actual_type == 'timer':
            # Start timer workers only
            click.echo(f"⏰ Starting {workers} timer worker(s) with leader election")
            for i in range(workers):
                worker = TimerWorker(
                    system_manager=system_manager,
                    worker_id=f"timer-{i}",
                    priority=priority if i == 0 else max(0, priority - 1)  # First has highest priority
                )
                task = asyncio.create_task(worker.start())
                worker_tasks.append(task)
                click.echo(f"   ✅ Timer worker {i} started (priority {worker.priority})")

        elif actual_type == 'signal':
            # Start signal workers only
            click.echo(f"📨 Starting {workers} signal worker(s) with leader election")
            for i in range(workers):
                worker = SignalWorker(
                    system_manager=system_manager,
                    worker_id=f"signal-{i}",
                    priority=priority if i == 0 else max(0, priority - 1)
                )
                task = asyncio.create_task(worker.start())
                worker_tasks.append(task)
                click.echo(f"   ✅ Signal worker {i} started (priority {worker.priority})")

        elif actual_type == 'stream':
            # Start stream workers only
            click.echo(f"📡 Starting {workers} stream worker(s)")
            for i in range(workers):
                worker = StreamWorker(
                    system_manager=system_manager,
                    worker_id=f"stream-{i}"
                )
                task = asyncio.create_task(worker.start())
                worker_tasks.append(task)
                click.echo(f"   ✅ Stream worker {i} started")

        elif actual_type == 'mixed-all':
            # Start one timer, one signal, and the rest as stream workers
            if workers < 3:
                click.echo(f"⚠️  Mixed-all mode needs at least 3 workers, got {workers}")
                workers = 3

            click.echo(f"🔀 Starting mixed workers (1 timer, 1 signal, {workers-2} stream)")

            # Start timer worker
            timer_worker = TimerWorker(
                system_manager=system_manager,
                worker_id="timer-0",
                priority=priority
            )
            task = asyncio.create_task(timer_worker.start())
            worker_tasks.append(task)
            click.echo(f"   ⏰ Timer worker started (priority {priority})")

            # Start signal worker
            signal_worker = SignalWorker(
                system_manager=system_manager,
                worker_id="signal-0",
                priority=priority
            )
            task = asyncio.create_task(signal_worker.start())
            worker_tasks.append(task)
            click.echo(f"   📨 Signal worker started (priority {priority})")

            # Start stream workers
            for i in range(workers - 2):
                stream_worker = StreamWorker(
                    system_manager=system_manager,
                    worker_id=f"stream-{i}"
                )
                task = asyncio.create_task(stream_worker.start())
                worker_tasks.append(task)
                click.echo(f"   📡 Stream worker {i} started")

        elif actual_type == 'mixed-timer':
            # Start one timer and the rest as stream workers
            click.echo(f"🔀 Starting mixed workers (1 timer, {workers-1} stream)")

            timer_worker = TimerWorker(
                system_manager=system_manager,
                worker_id="timer-0",
                priority=priority
            )
            task = asyncio.create_task(timer_worker.start())
            worker_tasks.append(task)
            click.echo(f"   ⏰ Timer worker started")

            for i in range(workers - 1):
                stream_worker = StreamWorker(
                    system_manager=system_manager,
                    worker_id=f"stream-{i}"
                )
                task = asyncio.create_task(stream_worker.start())
                worker_tasks.append(task)
                click.echo(f"   📡 Stream worker {i} started")

        elif actual_type == 'mixed-signal':
            # Start one signal and the rest as stream workers
            click.echo(f"🔀 Starting mixed workers (1 signal, {workers-1} stream)")

            signal_worker = SignalWorker(
                system_manager=system_manager,
                worker_id="signal-0",
                priority=priority
            )
            task = asyncio.create_task(signal_worker.start())
            worker_tasks.append(task)
            click.echo(f"   📨 Signal worker started")

            for i in range(workers - 1):
                stream_worker = StreamWorker(
                    system_manager=system_manager,
                    worker_id=f"stream-{i}"
                )
                task = asyncio.create_task(stream_worker.start())
                worker_tasks.append(task)
                click.echo(f"   📡 Stream worker {i} started")

        click.echo(f"\n✨ Workers running in {actual_type} mode")
        click.echo("   Press Ctrl+C to stop")

        # Wait for shutdown
        try:
            await asyncio.gather(*worker_tasks)
        except KeyboardInterrupt:
            click.echo("\n👋 Shutting down workers...")

    try:
        asyncio.run(run_workers())
    except KeyboardInterrupt:
        click.echo("Workers stopped")


@cli.command()
@click.option('--host', default='0.0.0.0', help='Server host')
@click.option('--port', default=8000, help='Server port')
@click.option('--headless', is_flag=True, help='Run without UI (API only)')
@click.option('--ui-port', default=8001, help='UI port (if not headless)')
@click.option('--restart', is_flag=True, help='Restart server if already running')
@click.option('--force', is_flag=True, help='Force kill existing server and start fresh')
def serve(host: str, port: int, headless: bool, ui_port: int, restart: bool, force: bool):
    """Start the SystemManager API server (and UI unless --headless)"""
    import httpx
    import signal

    # Check if server is already running
    try:
        response = httpx.get(f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}/health", timeout=2)
        if response.status_code == 200:
            if not restart and not force:
                click.echo(f"✅ SystemManager server already running on {host}:{port}")
                click.echo("   Use --restart to restart or --force to kill and start fresh")
                return

            # Kill existing server if restart or force
            click.echo(f"🔄 Found existing server on port {port}")

            # Find and kill processes on the port
            if sys.platform != 'win32':
                # Unix/Mac - use lsof
                result = subprocess.run(['lsof', '-t', f'-i:{port}'], capture_output=True, text=True)
                if result.stdout:
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        try:
                            if force:
                                os.kill(int(pid), signal.SIGKILL)
                                click.echo(f"   Force killed process {pid}")
                            else:
                                os.kill(int(pid), signal.SIGTERM)
                                click.echo(f"   Terminated process {pid}")
                        except:
                            pass
                    time.sleep(2)  # Wait for processes to die
            else:
                # Windows - use netstat
                click.echo("   Note: On Windows, please manually stop the existing server")
                if not click.confirm("   Continue anyway?"):
                    return
    except:
        # Server not running, proceed normally
        pass

    click.echo(f"🚀 Starting SystemManager API server on {host}:{port}")

    ui_process = None
    if not headless:
        # Check if UI port is also available
        try:
            response = httpx.get(f"http://localhost:{ui_port}/", timeout=1)
            if response.status_code == 200 and (restart or force):
                # Kill UI process too
                if sys.platform != 'win32':
                    result = subprocess.run(['lsof', '-t', f'-i:{ui_port}'], capture_output=True, text=True)
                    if result.stdout:
                        pids = result.stdout.strip().split('\n')
                        for pid in pids:
                            try:
                                os.kill(int(pid), signal.SIGTERM)
                                click.echo(f"   Terminated UI process {pid}")
                            except:
                                pass
                        time.sleep(1)
        except:
            pass

        # Start UI in background
        click.echo(f"🌐 Starting Web UI on port {ui_port}")
        ui_process = subprocess.Popen(
            ["python", "-m", "uvicorn", "gleitzeit.ui.api.app:app",
             "--host", "0.0.0.0", "--port", str(ui_port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(1)  # Give UI a moment to start
        click.echo(f"✨ Web UI available at http://localhost:{ui_port}")
        click.echo(f"   API endpoint configured to: http://{host}:{port}")
    else:
        click.echo("🔧 Running in headless mode (API only)")

    import uvicorn
    from gleitzeit.api.main import app

    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        if ui_process:
            click.echo("\n🛑 Shutting down UI...")
            ui_process.terminate()
            ui_process.wait(timeout=5)


def main():
    """Main entry point"""
    cli()


if __name__ == '__main__':
    main()