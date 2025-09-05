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
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from gleitzeit.client import GleitzeitClient, ClientMode
from .workflow import load_workflow, validate_workflow_file

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GleitzeitCLI:
    """CLI client that always uses SystemManager via API"""
    
    def __init__(self, host: str = "localhost", port: int = 8000):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        # Use httpx with cookie support for stateless auth
        self.client = httpx.AsyncClient(
            timeout=60.0,
            cookies=httpx.Cookies()  # Cookie jar for session management
        )
        self.gleitzeit_client = None
        
    async def __aenter__(self):
        await self.ensure_server()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
        if self.gleitzeit_client:
            await self.gleitzeit_client.shutdown()
    
    async def ensure_server(self) -> bool:
        """Ensure SystemManager server is running"""
        if await self.check_server():
            click.echo("✅ SystemManager server already running")
            self.gleitzeit_client = GleitzeitClient(
                mode=ClientMode.API,
                api_host=self.host,
                api_port=self.port
            )
            return True
            
        click.echo("🚀 Starting SystemManager server...")
        process = subprocess.Popen(
            ["python", "-m", "uvicorn", "gleitzeit.api.main:app",
             "--host", self.host, "--port", str(self.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
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
        # Use centralized workflow loader for consistency
        workflow = load_workflow(workflow_file)
        
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
                
                # Validate workflow before submission
                validation_errors = validate_workflow_file(workflow_path)
                if validation_errors:
                    click.echo("❌ Workflow validation failed:", err=True)
                    for error in validation_errors:
                        click.echo(f"   • {error}", err=True)
                    sys.exit(1)
                
                result = await cli.submit_workflow(workflow_path)
                workflow_id = result.get('workflow_id', result.get('id'))
                
                click.echo(f"✅ Workflow submitted: {workflow_id}")
                
                if wait:
                    click.echo("⏳ Waiting for completion...")
                    while True:
                        await asyncio.sleep(2)
                        status = await cli.get_workflow_status(workflow_id)
                        state = status.get('status', 'unknown')
                        
                        if state == 'completed':
                            click.echo("✅ Workflow completed successfully!")
                            break
                        elif state == 'failed':
                            click.echo(f"❌ Workflow failed: {status.get('error')}")
                            sys.exit(1)
                        elif state == 'cancelled':
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
                    'completed': '✅', 'failed': '❌', 'running': '🔄',
                    'pending': '⏳', 'cancelled': '⚠️'
                }.get(state, '❓')
                
                click.echo(f"{icon} Workflow: {workflow_id}")
                click.echo(f"   Status: {state.upper()}")
                
                if status.get('created_at'):
                    click.echo(f"   Created: {status['created_at']}")
                
                tasks = status.get('tasks', [])
                if tasks:
                    completed = sum(1 for t in tasks if t.get('status') == 'completed')
                    click.echo(f"   Tasks: {completed}/{len(tasks)} completed")
                    
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_status())


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
                        'completed': '✅', 'failed': '❌', 'running': '🔄',
                        'pending': '⏳', 'cancelled': '⚠️'
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
@click.option('--host', default='0.0.0.0', help='Server host')
@click.option('--port', default=8000, help='Server port')
@click.option('--headless', is_flag=True, help='Run without UI (API only)')
@click.option('--ui-port', default=8001, help='UI port (if not headless)')
def serve(host: str, port: int, headless: bool, ui_port: int):
    """Start the SystemManager API server (and UI unless --headless)"""
    click.echo(f"🚀 Starting SystemManager API server on {host}:{port}")
    
    ui_process = None
    if not headless:
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