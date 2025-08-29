#!/usr/bin/env python3
"""
Simple Gleitzeit CLI - A thin wrapper around the API
"""

import asyncio
import click
import httpx
import json
import yaml
import sys
from pathlib import Path
from typing import Optional, Dict, Any
import time


class GleitzeitCLI:
    """Simple CLI client that uses the API endpoints"""
    
    def __init__(self, host: str = "localhost", port: int = 8000):
        self.base_url = f"http://{host}:{port}"
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def check_server(self) -> bool:
        """Check if server is running"""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except:
            return False
    
    async def run_workflow(self, workflow_path: Path, wait: bool = True) -> Dict[str, Any]:
        """Submit and run a workflow"""
        # Load workflow file
        with open(workflow_path, 'r') as f:
            if workflow_path.suffix == '.yaml' or workflow_path.suffix == '.yml':
                workflow_data = yaml.safe_load(f)
            else:
                workflow_data = json.load(f)
        
        # Submit workflow
        response = await self.client.post(
            f"{self.base_url}/workflows",
            json=workflow_data
        )
        response.raise_for_status()
        result = response.json()
        workflow_id = result['workflow_id']
        
        if not wait:
            return result
        
        # Poll for completion
        while True:
            response = await self.client.get(f"{self.base_url}/workflows/{workflow_id}")
            response.raise_for_status()
            workflow = response.json()
            
            status = workflow.get('status', 'pending')
            if status in ['completed', 'failed', 'cancelled']:
                return workflow
            
            await asyncio.sleep(1)
    
    async def get_status(self, workflow_id: Optional[str] = None) -> Dict[str, Any]:
        """Get system or workflow status"""
        if workflow_id:
            response = await self.client.get(f"{self.base_url}/workflows/{workflow_id}")
        else:
            response = await self.client.get(f"{self.base_url}/status")
        
        response.raise_for_status()
        return response.json()
    
    async def list_workflows(self, limit: int = 10) -> Dict[str, Any]:
        """List recent workflows"""
        response = await self.client.get(
            f"{self.base_url}/workflows",
            params={"limit": limit}
        )
        response.raise_for_status()
        return response.json()
    
    async def list_tasks(self, workflow_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """List tasks"""
        params = {"limit": limit}
        if workflow_id:
            params["workflow_id"] = workflow_id
        
        response = await self.client.get(
            f"{self.base_url}/tasks",
            params=params
        )
        response.raise_for_status()
        return response.json()
    
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel a workflow"""
        response = await self.client.post(f"{self.base_url}/workflows/{workflow_id}/cancel")
        response.raise_for_status()
        return response.json()
    
    async def get_logs(self, task_id: str) -> Dict[str, Any]:
        """Get task logs"""
        response = await self.client.get(f"{self.base_url}/tasks/{task_id}/logs")
        response.raise_for_status()
        return response.json()


@click.group()
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
@click.pass_context
def cli(ctx, host: str, port: int):
    """Gleitzeit - Workflow orchestration system"""
    ctx.ensure_object(dict)
    ctx.obj['host'] = host
    ctx.obj['port'] = port


@cli.command()
@click.argument('workflow', type=click.Path(exists=True))
@click.option('--wait/--no-wait', default=True, help='Wait for completion')
@click.option('--output', '-o', type=click.Choice(['json', 'yaml', 'text']), default='text')
@click.pass_context
def run(ctx, workflow: str, wait: bool, output: str):
    """Run a workflow"""
    async def _run():
        async with GleitzeitCLI(ctx.obj['host'], ctx.obj['port']) as client:
            # Check server
            if not await client.check_server():
                click.echo("❌ API server is not running. Start it with: gleitzeit serve", err=True)
                sys.exit(1)
            
            workflow_path = Path(workflow)
            click.echo(f"📋 Loading workflow: {workflow_path}")
            
            try:
                result = await client.run_workflow(workflow_path, wait=wait)
                
                if output == 'json':
                    click.echo(json.dumps(result, indent=2))
                elif output == 'yaml':
                    click.echo(yaml.dump(result, default_flow_style=False))
                else:
                    # Text output
                    workflow_id = result.get('workflow_id', result.get('id', 'unknown'))
                    status = result.get('status', 'unknown')
                    
                    if wait:
                        if status == 'completed':
                            click.echo(f"✅ Workflow {workflow_id} completed successfully!")
                            
                            # Show task results
                            tasks = await client.list_tasks(workflow_id=workflow_id)
                            for task in tasks.get('tasks', []):
                                task_id = task.get('task_id', task.get('id'))
                                task_status = task.get('status')
                                click.echo(f"  • Task {task_id}: {task_status}")
                                
                                if task.get('result'):
                                    click.echo(f"    Result: {task['result']}")
                        
                        elif status == 'failed':
                            click.echo(f"❌ Workflow {workflow_id} failed", err=True)
                            
                            # Show error details
                            if result.get('error'):
                                click.echo(f"Error: {result['error']}", err=True)
                        
                        else:
                            click.echo(f"⚠️ Workflow {workflow_id} ended with status: {status}")
                    else:
                        click.echo(f"🚀 Workflow submitted: {workflow_id}")
                        click.echo(f"   Status: {status}")
                        click.echo(f"   Use 'gleitzeit status {workflow_id}' to check progress")
            
            except httpx.HTTPStatusError as e:
                click.echo(f"❌ API error: {e.response.text}", err=True)
                sys.exit(1)
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_run())


@cli.command()
@click.argument('workflow_id', required=False)
@click.pass_context
def status(ctx, workflow_id: Optional[str]):
    """Get status of system or workflow"""
    async def _status():
        async with GleitzeitCLI(ctx.obj['host'], ctx.obj['port']) as client:
            if not await client.check_server():
                click.echo("❌ API server is not running", err=True)
                sys.exit(1)
            
            try:
                result = await client.get_status(workflow_id)
                
                if workflow_id:
                    # Workflow status
                    status = result.get('status', 'unknown')
                    click.echo(f"Workflow: {workflow_id}")
                    click.echo(f"Status: {status}")
                    click.echo(f"Created: {result.get('created_at', 'unknown')}")
                    
                    if result.get('tasks'):
                        click.echo(f"\nTasks ({len(result['tasks'])}):")
                        for task in result['tasks']:
                            task_id = task.get('id', task.get('task_id'))
                            task_status = task.get('status')
                            click.echo(f"  • {task_id}: {task_status}")
                else:
                    # System status
                    click.echo("System Status:")
                    click.echo(f"  API: ✅ Running")
                    click.echo(f"  Version: {result.get('version', 'unknown')}")
                    
                    if result.get('persistence'):
                        click.echo(f"  Persistence: {result['persistence']['type']}")
                    
                    if result.get('resources'):
                        click.echo(f"  Resources:")
                        for resource, info in result['resources'].items():
                            click.echo(f"    • {resource}: {info}")
            
            except httpx.HTTPStatusError as e:
                click.echo(f"❌ API error: {e.response.text}", err=True)
                sys.exit(1)
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_status())


@cli.command()
@click.option('--limit', default=10, help='Number of workflows to list')
@click.pass_context
def list(ctx, limit: int):
    """List recent workflows"""
    async def _list():
        async with GleitzeitCLI(ctx.obj['host'], ctx.obj['port']) as client:
            if not await client.check_server():
                click.echo("❌ API server is not running", err=True)
                sys.exit(1)
            
            try:
                result = await client.list_workflows(limit=limit)
                workflows = result.get('workflows', [])
                
                if not workflows:
                    click.echo("No workflows found")
                    return
                
                click.echo(f"Recent Workflows (showing {len(workflows)} of {result.get('total', 0)}):")
                click.echo()
                
                for wf in workflows:
                    # Handle both dict and object responses
                    if isinstance(wf, dict):
                        wf_id = wf.get('workflow_id', wf.get('id'))
                        name = wf.get('name', 'Unnamed')
                        status = wf.get('status', 'unknown')
                        created = wf.get('created_at', 'unknown')
                    else:
                        # Handle string or other format
                        wf_id = str(wf)
                        name = 'Unknown'
                        status = 'unknown'
                        created = 'unknown'
                    
                    # Status emoji
                    status_icon = {
                        'completed': '✅',
                        'failed': '❌',
                        'running': '🔄',
                        'pending': '⏳',
                        'cancelled': '⚠️'
                    }.get(status, '❓')
                    
                    click.echo(f"{status_icon} {wf_id[:8]}... | {name} | {status} | {created}")
            
            except httpx.HTTPStatusError as e:
                click.echo(f"❌ API error: {e.response.text}", err=True)
                sys.exit(1)
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_list())


@cli.command()
@click.argument('workflow_id')
@click.pass_context
def cancel(ctx, workflow_id: str):
    """Cancel a running workflow"""
    async def _cancel():
        async with GleitzeitCLI(ctx.obj['host'], ctx.obj['port']) as client:
            if not await client.check_server():
                click.echo("❌ API server is not running", err=True)
                sys.exit(1)
            
            try:
                result = await client.cancel_workflow(workflow_id)
                click.echo(f"✅ Workflow {workflow_id} cancelled")
            
            except httpx.HTTPStatusError as e:
                click.echo(f"❌ API error: {e.response.text}", err=True)
                sys.exit(1)
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_cancel())


@cli.command()
@click.argument('task_id')
@click.pass_context
def logs(ctx, task_id: str):
    """Get logs for a task"""
    async def _logs():
        async with GleitzeitCLI(ctx.obj['host'], ctx.obj['port']) as client:
            if not await client.check_server():
                click.echo("❌ API server is not running", err=True)
                sys.exit(1)
            
            try:
                result = await client.get_logs(task_id)
                logs = result.get('logs', [])
                
                if not logs:
                    click.echo(f"No logs found for task {task_id}")
                    return
                
                click.echo(f"Logs for task {task_id}:")
                click.echo("-" * 50)
                
                for log in logs:
                    timestamp = log.get('timestamp', '')
                    level = log.get('level', 'INFO')
                    message = log.get('message', '')
                    
                    # Color based on level
                    if level == 'ERROR':
                        click.echo(click.style(f"[{timestamp}] {level}: {message}", fg='red'))
                    elif level == 'WARNING':
                        click.echo(click.style(f"[{timestamp}] {level}: {message}", fg='yellow'))
                    else:
                        click.echo(f"[{timestamp}] {level}: {message}")
            
            except httpx.HTTPStatusError as e:
                click.echo(f"❌ API error: {e.response.text}", err=True)
                sys.exit(1)
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_logs())


@cli.command()
@click.option('--host', default='0.0.0.0', help='Server host')
@click.option('--port', default=8000, help='Server port')
def serve(host: str, port: int):
    """Start the API server"""
    click.echo(f"🚀 Starting Gleitzeit API server on {host}:{port}")
    
    # Import and run the API server
    import uvicorn
    from gleitzeit.api.main import app
    
    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.option('--port', default=8001, help='UI port')
@click.pass_context
def ui(ctx, port: int):
    """Start the Web UI"""
    click.echo(f"🌐 Starting Gleitzeit Web UI on port {port}")
    click.echo(f"   API endpoint: http://{ctx.obj['host']}:{ctx.obj['port']}")
    
    # Import and run the UI server
    import uvicorn
    from gleitzeit.ui.api.app import app
    
    uvicorn.run(app, host='0.0.0.0', port=port)


if __name__ == '__main__':
    cli()