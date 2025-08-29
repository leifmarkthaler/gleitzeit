"""
Status Command - Get workflow and task status
"""

import click
import asyncio
from typing import Any, Dict

from gleitzeit.client import GleitzeitClient

async def execute(ctx: click.Context, workflow_id: str, detailed: bool) -> None:
    """Execute status command"""
    config = ctx.obj['config']
    client = GleitzeitClient(config)
    
    try:
        await client.connect()
        
        click.echo(f"📊 Getting status for: {workflow_id}")
        status = await client.get_workflow_status(workflow_id)
        
        if status.get('status') == 'not_found':
            click.echo(f"❌ Workflow not found: {workflow_id}")
            return
        
        _display_workflow_status(status, detailed)
        
    except Exception as e:
        click.echo(f"❌ Failed to get status: {e}", err=True)
    finally:
        await client.disconnect()


def _display_workflow_status(status: Dict[str, Any], detailed: bool) -> None:
    """Display workflow status in user-friendly format"""
    workflow_id = status.get('workflow_id', 'unknown')
    workflow_status = status.get('status', 'unknown')
    
    # Status emoji
    status_emoji = {
        'pending': '⏳',
        'running': '🏃',
        'completed': '✅', 
        'failed': '❌',
        'cancelled': '⏹️'
    }.get(workflow_status, '❓')
    
    click.echo(f"\n{status_emoji} Workflow: {workflow_id}")
    click.echo(f"   Status: {workflow_status.upper()}")
    
    if status.get('started_at'):
        click.echo(f"   Started: {status['started_at']}")
    
    if status.get('completed_at'):
        click.echo(f"   Completed: {status['completed_at']}")
    
    # Task summary
    task_count = status.get('task_count', 0)
    completed_tasks = status.get('completed_tasks', 0)
    failed_tasks = status.get('failed_tasks', 0)
    
    if task_count > 0:
        click.echo(f"\n📋 Tasks: {completed_tasks}/{task_count} completed")
        if failed_tasks > 0:
            click.echo(f"   ❌ Failed: {failed_tasks}")
        
        # Progress bar
        if task_count > 0:
            progress = completed_tasks / task_count
            bar_length = 20
            filled = int(progress * bar_length)
            bar = '█' * filled + '░' * (bar_length - filled)
            click.echo(f"   Progress: [{bar}] {progress:.1%}")
    
    # Detailed task status
    if detailed and 'tasks' in status:
        click.echo(f"\n📝 Task Details:")
        
        for task in status['tasks']:
            task_status = task.get('status', 'unknown')
            task_emoji = {
                'queued': '⏳',
                'executing': '▶️',
                'completed': '✅',
                'failed': '❌',
                'retry_pending': '🔄'
            }.get(task_status, '❓')
            
            task_name = task.get('name', task.get('id', 'unknown'))
            click.echo(f"   {task_emoji} {task_name} ({task_status})")
            
            if task.get('started_at'):
                click.echo(f"      Started: {task['started_at']}")
            if task.get('completed_at'):
                click.echo(f"      Completed: {task['completed_at']}")