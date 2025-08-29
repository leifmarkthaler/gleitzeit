#!/usr/bin/env python3
"""
Gleitzeit CLI - Complete command-line interface for Gleitzeit
Uses the client for server management and API endpoints for operations
"""

import asyncio
import click
import httpx
import json
import yaml
import sys
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

# Import the actual Gleitzeit client for server management
from gleitzeit.client import GleitzeitClient
from gleitzeit.client.base import ClientMode


class GleitzeitCLIClient:
    """CLI client that uses API endpoints for operations"""
    
    def __init__(self, host: str = "localhost", port: int = 8000):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.client = httpx.AsyncClient(timeout=60.0)
        self.gleitzeit_client = None  # Will be set if auto-start is used
        
    async def __aenter__(self):
        # Check if server is running, start if needed
        await self.ensure_server_running()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
        # Clean up the gleitzeit client if we created one
        if self.gleitzeit_client:
            await self.gleitzeit_client.__aexit__(None, None, None)
    
    async def ensure_server_running(self) -> bool:
        """Ensure server is running, start if needed using GleitzeitClient"""
        # Use GleitzeitClient which will:
        # 1. Check if server is already running
        # 2. Start it only if needed
        # 3. Use the existing instance if available
        try:
            # The client will automatically detect and use existing server
            # or start a new one if needed
            self.gleitzeit_client = GleitzeitClient(
                mode=ClientMode.AUTO,  # Let it auto-detect
                api_host=self.host,
                api_port=self.port,
                auto_start_server=True,
                keep_server_running=True
            )
            
            # Initialize the client
            await self.gleitzeit_client.__aenter__()
            
            # Check if we have API mode (server is running)
            if self.gleitzeit_client.mode == ClientMode.API:
                if await self.check_server():
                    # Don't show message every time - it's expected behavior
                    return True
            
            # If we're in native mode, the server couldn't be started
            click.echo("⚠️ Running in native mode (no API server)", err=True)
            return False
            
        except Exception as e:
            click.echo(f"❌ Failed to initialize client: {e}", err=True)
            return False
    
    async def check_server(self) -> bool:
        """Check if server is running"""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except:
            return False
    
    # Workflow operations
    async def run_workflow(self, workflow_path: Path, wait: bool = True) -> Dict[str, Any]:
        """Submit and run a workflow"""
        with open(workflow_path, 'r') as f:
            if workflow_path.suffix in ['.yaml', '.yml']:
                workflow_data = yaml.safe_load(f)
            else:
                workflow_data = json.load(f)
        
        response = await self.client.post(f"{self.base_url}/workflows", json=workflow_data)
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
    
    async def list_workflows(self, limit: int = 10, status: Optional[str] = None, 
                           offset: int = 0) -> Dict[str, Any]:
        """List workflows with filtering"""
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        
        response = await self.client.get(f"{self.base_url}/workflows", params=params)
        response.raise_for_status()
        return response.json()
    
    async def get_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow details"""
        response = await self.client.get(f"{self.base_url}/workflows/{workflow_id}")
        response.raise_for_status()
        return response.json()
    
    async def delete_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Delete a workflow"""
        response = await self.client.delete(f"{self.base_url}/workflows/{workflow_id}")
        response.raise_for_status()
        return response.json()
    
    async def pause_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Pause a workflow"""
        response = await self.client.post(f"{self.base_url}/workflows/{workflow_id}/pause")
        response.raise_for_status()
        return response.json()
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Resume a workflow"""
        response = await self.client.post(f"{self.base_url}/workflows/{workflow_id}/resume")
        response.raise_for_status()
        return response.json()
    
    async def retry_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Retry a failed workflow"""
        response = await self.client.post(f"{self.base_url}/workflows/{workflow_id}/retry")
        response.raise_for_status()
        return response.json()
    
    async def get_workflow_results(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow results"""
        response = await self.client.get(f"{self.base_url}/workflows/{workflow_id}/results")
        response.raise_for_status()
        return response.json()
    
    async def get_workflow_timeline(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow execution timeline"""
        response = await self.client.get(f"{self.base_url}/workflows/{workflow_id}/timeline")
        response.raise_for_status()
        return response.json()
    
    # Task operations
    async def list_tasks(self, workflow_id: Optional[str] = None, status: Optional[str] = None,
                        limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """List tasks with filtering"""
        params = {"limit": limit, "offset": offset}
        if workflow_id:
            params["workflow_id"] = workflow_id
        if status:
            params["status"] = status
        
        response = await self.client.get(f"{self.base_url}/tasks", params=params)
        response.raise_for_status()
        return response.json()
    
    async def get_task(self, task_id: str) -> Dict[str, Any]:
        """Get task details"""
        response = await self.client.get(f"{self.base_url}/tasks/{task_id}")
        response.raise_for_status()
        return response.json()
    
    async def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """Cancel a task"""
        response = await self.client.post(f"{self.base_url}/tasks/{task_id}/cancel")
        response.raise_for_status()
        return response.json()
    
    async def retry_task(self, task_id: str) -> Dict[str, Any]:
        """Retry a failed task"""
        response = await self.client.post(f"{self.base_url}/tasks/{task_id}/retry")
        response.raise_for_status()
        return response.json()
    
    async def get_task_result(self, task_id: str) -> Dict[str, Any]:
        """Get task result"""
        response = await self.client.get(f"{self.base_url}/tasks/{task_id}/result")
        response.raise_for_status()
        return response.json()
    
    async def get_task_logs(self, task_id: str) -> Dict[str, Any]:
        """Get task logs"""
        response = await self.client.get(f"{self.base_url}/tasks/{task_id}/logs")
        response.raise_for_status()
        return response.json()
    
    # Queue operations
    async def list_queues(self) -> Dict[str, Any]:
        """List all queues"""
        response = await self.client.get(f"{self.base_url}/queues")
        response.raise_for_status()
        return response.json()
    
    async def get_queue(self, queue_name: str) -> Dict[str, Any]:
        """Get queue details"""
        response = await self.client.get(f"{self.base_url}/queues/{queue_name}")
        response.raise_for_status()
        return response.json()
    
    async def pause_queue(self, queue_name: str) -> Dict[str, Any]:
        """Pause a queue"""
        response = await self.client.post(f"{self.base_url}/queues/{queue_name}/pause")
        response.raise_for_status()
        return response.json()
    
    async def resume_queue(self, queue_name: str) -> Dict[str, Any]:
        """Resume a queue"""
        response = await self.client.post(f"{self.base_url}/queues/{queue_name}/resume")
        response.raise_for_status()
        return response.json()
    
    async def clear_queue(self, queue_name: str) -> Dict[str, Any]:
        """Clear a queue"""
        response = await self.client.post(f"{self.base_url}/queues/{queue_name}/clear")
        response.raise_for_status()
        return response.json()
    
    # System operations
    async def get_status(self) -> Dict[str, Any]:
        """Get system status"""
        response = await self.client.get(f"{self.base_url}/status")
        response.raise_for_status()
        return response.json()
    
    async def get_resources(self) -> Dict[str, Any]:
        """Get resource information"""
        response = await self.client.get(f"{self.base_url}/resources")
        response.raise_for_status()
        return response.json()
    
    async def get_providers(self) -> List[Dict[str, Any]]:
        """Get registered providers"""
        response = await self.client.get(f"{self.base_url}/providers")
        response.raise_for_status()
        return response.json()
    
    async def get_protocols(self) -> List[str]:
        """Get supported protocols"""
        response = await self.client.get(f"{self.base_url}/protocols")
        response.raise_for_status()
        return response.json()
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get task statistics"""
        response = await self.client.get(f"{self.base_url}/statistics/tasks")
        response.raise_for_status()
        return response.json()
    
    # Batch operations
    async def batch_process(self, directory: str, pattern: str, prompt: str) -> Dict[str, Any]:
        """Process files in batch"""
        response = await self.client.post(
            f"{self.base_url}/bulk/directory",
            json={"directory": directory, "pattern": pattern, "prompt": prompt}
        )
        response.raise_for_status()
        return response.json()


# CLI Commands
@click.group()
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
@click.pass_context
def cli(ctx, host: str, port: int):
    """Gleitzeit - Workflow orchestration system"""
    ctx.ensure_object(dict)
    ctx.obj['host'] = host
    ctx.obj['port'] = port


# Workflow commands
@cli.group()
def workflow():
    """Manage workflows"""
    pass


@workflow.command('run')
@click.argument('workflow_file', type=click.Path(exists=True))
@click.option('--wait/--no-wait', default=True, help='Wait for completion')
@click.option('--output', '-o', type=click.Choice(['json', 'yaml', 'text']), default='text')
@click.pass_context
def run_workflow(ctx, workflow_file: str, wait: bool, output: str):
    """Run a workflow from file"""
    async def _run():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            workflow_path = Path(workflow_file)
            click.echo(f"📋 Loading workflow: {workflow_path}")
            
            try:
                result = await client.run_workflow(workflow_path, wait=wait)
                
                if output == 'json':
                    click.echo(json.dumps(result, indent=2))
                elif output == 'yaml':
                    click.echo(yaml.dump(result, default_flow_style=False))
                else:
                    workflow_id = result.get('workflow_id', result.get('id', 'unknown'))
                    status = result.get('status', 'unknown')
                    
                    if wait:
                        if status == 'completed':
                            click.echo(f"✅ Workflow {workflow_id} completed successfully!")
                        elif status == 'failed':
                            click.echo(f"❌ Workflow {workflow_id} failed", err=True)
                            if result.get('error'):
                                click.echo(f"Error: {result['error']}", err=True)
                        else:
                            click.echo(f"⚠️ Workflow {workflow_id} ended with status: {status}")
                    else:
                        click.echo(f"🚀 Workflow submitted: {workflow_id}")
                        click.echo(f"   Use 'gleitzeit workflow get {workflow_id}' to check progress")
                        
            except httpx.HTTPStatusError as e:
                click.echo(f"❌ API error: {e.response.text}", err=True)
                sys.exit(1)
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_run())


@workflow.command('list')
@click.option('--limit', default=10, help='Number of workflows')
@click.option('--status', help='Filter by status')
@click.option('--offset', default=0, help='Offset for pagination')
@click.pass_context
def list_workflows(ctx, limit: int, status: Optional[str], offset: int):
    """List workflows"""
    async def _list():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                result = await client.list_workflows(limit=limit, status=status, offset=offset)
                workflows = result.get('workflows', [])
                
                if not workflows:
                    click.echo("No workflows found")
                    return
                
                click.echo(f"Workflows (showing {len(workflows)} of {result.get('total', 0)}):")
                for wf in workflows:
                    if isinstance(wf, dict):
                        wf_id = wf.get('workflow_id', wf.get('id', 'unknown'))
                        name = wf.get('name', 'Unnamed')
                        wf_status = wf.get('status', 'unknown')
                        created = wf.get('created_at', 'unknown')
                        
                        status_icon = {
                            'completed': '✅', 'failed': '❌', 'running': '🔄',
                            'pending': '⏳', 'cancelled': '⚠️'
                        }.get(wf_status, '❓')
                        
                        click.echo(f"{status_icon} {wf_id[:8]}... | {name} | {wf_status} | {created}")
                        
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_list())


@workflow.command('get')
@click.argument('workflow_id')
@click.option('--output', '-o', type=click.Choice(['json', 'yaml', 'text']), default='text')
@click.pass_context
def get_workflow(ctx, workflow_id: str, output: str):
    """Get workflow details"""
    async def _get():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                result = await client.get_workflow(workflow_id)
                
                if output == 'json':
                    click.echo(json.dumps(result, indent=2))
                elif output == 'yaml':
                    click.echo(yaml.dump(result, default_flow_style=False))
                else:
                    click.echo(f"Workflow: {workflow_id}")
                    click.echo(f"Name: {result.get('name', 'Unnamed')}")
                    click.echo(f"Status: {result.get('status', 'unknown')}")
                    click.echo(f"Created: {result.get('created_at', 'unknown')}")
                    
                    tasks = result.get('tasks', [])
                    if tasks:
                        click.echo(f"\nTasks ({len(tasks)}):")
                        for task in tasks:
                            task_id = task.get('id', task.get('task_id'))
                            task_status = task.get('status')
                            click.echo(f"  • {task_id}: {task_status}")
                            
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_get())


@workflow.command('delete')
@click.argument('workflow_id')
@click.confirmation_option(prompt='Are you sure you want to delete this workflow?')
@click.pass_context
def delete_workflow(ctx, workflow_id: str):
    """Delete a workflow"""
    async def _delete():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                await client.delete_workflow(workflow_id)
                click.echo(f"✅ Workflow {workflow_id} deleted")
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_delete())


@workflow.command('pause')
@click.argument('workflow_id')
@click.pass_context
def pause_workflow(ctx, workflow_id: str):
    """Pause a running workflow"""
    async def _pause():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                await client.pause_workflow(workflow_id)
                click.echo(f"⏸️ Workflow {workflow_id} paused")
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_pause())


@workflow.command('resume')
@click.argument('workflow_id')
@click.pass_context
def resume_workflow(ctx, workflow_id: str):
    """Resume a paused workflow"""
    async def _resume():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                await client.resume_workflow(workflow_id)
                click.echo(f"▶️ Workflow {workflow_id} resumed")
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_resume())


@workflow.command('retry')
@click.argument('workflow_id')
@click.pass_context
def retry_workflow(ctx, workflow_id: str):
    """Retry a failed workflow"""
    async def _retry():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                result = await client.retry_workflow(workflow_id)
                click.echo(f"🔄 Workflow {workflow_id} retry started")
                click.echo(f"   New workflow ID: {result.get('workflow_id', 'unknown')}")
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_retry())


@workflow.command('results')
@click.argument('workflow_id')
@click.option('--output', '-o', type=click.Choice(['json', 'yaml', 'text']), default='text')
@click.pass_context
def get_workflow_results(ctx, workflow_id: str, output: str):
    """Get workflow results"""
    async def _results():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                result = await client.get_workflow_results(workflow_id)
                
                if output == 'json':
                    click.echo(json.dumps(result, indent=2))
                elif output == 'yaml':
                    click.echo(yaml.dump(result, default_flow_style=False))
                else:
                    results = result.get('results', {})
                    click.echo(f"Results for workflow {workflow_id}:")
                    for task_id, task_result in results.items():
                        click.echo(f"\n  Task {task_id}:")
                        click.echo(f"    {task_result}")
                        
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_results())


# Task commands
@cli.group()
def task():
    """Manage tasks"""
    pass


@task.command('list')
@click.option('--workflow-id', help='Filter by workflow')
@click.option('--status', help='Filter by status')
@click.option('--limit', default=50, help='Number of tasks')
@click.pass_context
def list_tasks(ctx, workflow_id: Optional[str], status: Optional[str], limit: int):
    """List tasks"""
    async def _list():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                result = await client.list_tasks(
                    workflow_id=workflow_id, status=status, limit=limit
                )
                tasks = result.get('tasks', [])
                
                if not tasks:
                    click.echo("No tasks found")
                    return
                
                click.echo(f"Tasks (showing {len(tasks)}):")
                for task in tasks:
                    task_id = task.get('task_id', task.get('id'))
                    task_status = task.get('status')
                    wf_id = task.get('workflow_id', '')
                    
                    status_icon = {
                        'completed': '✅', 'failed': '❌', 'running': '🔄',
                        'pending': '⏳', 'cancelled': '⚠️'
                    }.get(task_status, '❓')
                    
                    click.echo(f"{status_icon} {task_id} | {task_status} | Workflow: {wf_id[:8]}...")
                    
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_list())


@task.command('get')
@click.argument('task_id')
@click.option('--output', '-o', type=click.Choice(['json', 'yaml', 'text']), default='text')
@click.pass_context
def get_task(ctx, task_id: str, output: str):
    """Get task details"""
    async def _get():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                result = await client.get_task(task_id)
                
                if output == 'json':
                    click.echo(json.dumps(result, indent=2))
                elif output == 'yaml':
                    click.echo(yaml.dump(result, default_flow_style=False))
                else:
                    click.echo(f"Task: {task_id}")
                    click.echo(f"Status: {result.get('status')}")
                    click.echo(f"Method: {result.get('method')}")
                    click.echo(f"Workflow: {result.get('workflow_id')}")
                    
                    if result.get('error'):
                        click.echo(f"Error: {result['error']}")
                    if result.get('result'):
                        click.echo(f"Result: {result['result']}")
                        
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_get())


@task.command('cancel')
@click.argument('task_id')
@click.pass_context
def cancel_task(ctx, task_id: str):
    """Cancel a running task"""
    async def _cancel():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                await client.cancel_task(task_id)
                click.echo(f"✅ Task {task_id} cancelled")
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_cancel())


@task.command('retry')
@click.argument('task_id')
@click.pass_context
def retry_task(ctx, task_id: str):
    """Retry a failed task"""
    async def _retry():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                result = await client.retry_task(task_id)
                click.echo(f"🔄 Task {task_id} retry started")
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_retry())


@task.command('logs')
@click.argument('task_id')
@click.pass_context
def task_logs(ctx, task_id: str):
    """Get task logs"""
    async def _logs():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                result = await client.get_task_logs(task_id)
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
                    
                    if level == 'ERROR':
                        click.echo(click.style(f"[{timestamp}] {level}: {message}", fg='red'))
                    elif level == 'WARNING':
                        click.echo(click.style(f"[{timestamp}] {level}: {message}", fg='yellow'))
                    else:
                        click.echo(f"[{timestamp}] {level}: {message}")
                        
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_logs())


# Queue commands
@cli.group()
def queue():
    """Manage queues"""
    pass


@queue.command('list')
@click.pass_context
def list_queues(ctx):
    """List all queues"""
    async def _list():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                result = await client.list_queues()
                queues = result.get('queues', [])
                
                click.echo("Queues:")
                for q in queues:
                    name = q.get('name', 'unknown')
                    size = q.get('size', 0)
                    status = q.get('status', 'unknown')
                    click.echo(f"  • {name}: {size} items, status: {status}")
                    
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_list())


@queue.command('pause')
@click.argument('queue_name')
@click.pass_context
def pause_queue(ctx, queue_name: str):
    """Pause a queue"""
    async def _pause():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                await client.pause_queue(queue_name)
                click.echo(f"⏸️ Queue {queue_name} paused")
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_pause())


@queue.command('resume')
@click.argument('queue_name')
@click.pass_context
def resume_queue(ctx, queue_name: str):
    """Resume a queue"""
    async def _resume():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                await client.resume_queue(queue_name)
                click.echo(f"▶️ Queue {queue_name} resumed")
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_resume())


@queue.command('clear')
@click.argument('queue_name')
@click.confirmation_option(prompt='Are you sure you want to clear this queue?')
@click.pass_context
def clear_queue(ctx, queue_name: str):
    """Clear a queue"""
    async def _clear():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                await client.clear_queue(queue_name)
                click.echo(f"✅ Queue {queue_name} cleared")
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_clear())


# System commands
@cli.command('status')
@click.pass_context
def system_status(ctx):
    """Get system status"""
    async def _status():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                result = await client.get_status()
                
                click.echo("System Status:")
                click.echo(f"  Version: {result.get('version', 'unknown')}")
                click.echo(f"  API: ✅ Running on {ctx.obj['host']}:{ctx.obj['port']}")
                
                if result.get('persistence'):
                    click.echo(f"  Persistence: {result['persistence'].get('type', 'unknown')}")
                
                if result.get('resources'):
                    click.echo("  Resources:")
                    for resource, info in result['resources'].items():
                        click.echo(f"    • {resource}: {info}")
                        
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_status())


@cli.command('resources')
@click.pass_context
def resources(ctx):
    """Get resource information"""
    async def _resources():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                result = await client.get_resources()
                
                click.echo("Resources:")
                for category, items in result.items():
                    click.echo(f"\n{category}:")
                    if isinstance(items, dict):
                        for key, value in items.items():
                            click.echo(f"  • {key}: {value}")
                    elif isinstance(items, list):
                        for item in items:
                            click.echo(f"  • {item}")
                    else:
                        click.echo(f"  {items}")
                        
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_resources())


@cli.command('providers')
@click.pass_context
def providers(ctx):
    """List registered providers"""
    async def _providers():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                providers = await client.get_providers()
                
                click.echo("Registered Providers:")
                for provider in providers:
                    name = provider.get('name', 'unknown')
                    protocol = provider.get('protocol', 'unknown')
                    methods = provider.get('methods', [])
                    click.echo(f"\n  {name} ({protocol}):")
                    for method in methods:
                        click.echo(f"    • {method}")
                        
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_providers())


@cli.command('protocols')
@click.pass_context
def protocols(ctx):
    """List supported protocols"""
    async def _protocols():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                protocols = await client.get_protocols()
                
                click.echo("Supported Protocols:")
                for protocol in protocols:
                    click.echo(f"  • {protocol}")
                    
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_protocols())


@cli.command('statistics')
@click.pass_context
def statistics(ctx):
    """Get task statistics"""
    async def _stats():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                stats = await client.get_statistics()
                
                click.echo("Task Statistics:")
                click.echo(f"  Total: {stats.get('total', 0)}")
                click.echo(f"  Completed: {stats.get('completed', 0)}")
                click.echo(f"  Failed: {stats.get('failed', 0)}")
                click.echo(f"  Running: {stats.get('running', 0)}")
                click.echo(f"  Pending: {stats.get('pending', 0)}")
                
                if stats.get('by_method'):
                    click.echo("\nBy Method:")
                    for method, count in stats['by_method'].items():
                        click.echo(f"  • {method}: {count}")
                        
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_stats())


# Batch operations
@cli.command('batch')
@click.argument('directory', type=click.Path(exists=True))
@click.option('--pattern', '-p', default='*', help='File pattern')
@click.option('--prompt', default='Process this file', help='Processing prompt')
@click.pass_context
def batch_process(ctx, directory: str, pattern: str, prompt: str):
    """Process files in batch"""
    async def _batch():
        async with GleitzeitCLIClient(
            ctx.obj['host'], ctx.obj['port']
        ) as client:
            try:
                click.echo(f"🔄 Processing files in {directory} matching {pattern}")
                result = await client.batch_process(directory, pattern, prompt)
                
                workflow_id = result.get('workflow_id')
                click.echo(f"✅ Batch workflow submitted: {workflow_id}")
                click.echo(f"   Use 'gleitzeit workflow get {workflow_id}' to check progress")
                
            except Exception as e:
                click.echo(f"❌ Error: {e}", err=True)
                sys.exit(1)
    
    asyncio.run(_batch())


# Server commands
@cli.command('serve')
@click.option('--host', default='0.0.0.0', help='Server host')
@click.option('--port', default=8000, help='Server port')
def serve(host: str, port: int):
    """Start the API server"""
    click.echo(f"🚀 Starting Gleitzeit API server on {host}:{port}")
    
    import uvicorn
    from gleitzeit.api.main import app
    
    uvicorn.run(app, host=host, port=port)


@cli.command('ui')
@click.option('--port', default=8001, help='UI port')
@click.pass_context
def ui(ctx, port: int):
    """Start the Web UI"""
    click.echo(f"🌐 Starting Gleitzeit Web UI on port {port}")
    click.echo(f"   API endpoint: http://{ctx.obj['host']}:{ctx.obj['port']}")
    
    import uvicorn
    from gleitzeit.ui.api.app import app
    
    uvicorn.run(app, host='0.0.0.0', port=port)


# Convenience aliases for common operations
@cli.command('run')
@click.argument('workflow_file', type=click.Path(exists=True))
@click.option('--wait/--no-wait', default=True, help='Wait for completion')
@click.pass_context
def run(ctx, workflow_file: str, wait: bool):
    """Run a workflow (alias for workflow run)"""
    ctx.invoke(run_workflow, workflow_file=workflow_file, wait=wait, output='text')


@cli.command('list')
@click.option('--tasks', is_flag=True, help='List tasks instead of workflows')
@click.option('--limit', default=10, help='Number to show')
@click.pass_context
def list_items(ctx, tasks: bool, limit: int):
    """List workflows or tasks"""
    if tasks:
        ctx.invoke(list_tasks, limit=limit)
    else:
        ctx.invoke(list_workflows, limit=limit)


if __name__ == '__main__':
    cli()