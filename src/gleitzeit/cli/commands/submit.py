"""
Submit Command - Submit workflows for execution
"""

import click
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict

from gleitzeit.cli.client import GleitzeitClient
from gleitzeit.cli.workflow import load_workflow, validate_workflow

logger = logging.getLogger(__name__)


async def execute(ctx: click.Context, workflow_path: str, watch: bool, 
                 dry_run: bool, priority: str) -> None:
    """Execute submit command"""
    config = ctx.obj['config']
    
    # Load and validate workflow
    try:
        workflow = await load_workflow(Path(workflow_path))
        validation_errors = validate_workflow(workflow)
        
        if validation_errors:
            click.echo("❌ Workflow validation failed:", err=True)
            for error in validation_errors:
                click.echo(f"  • {error}", err=True)
            return
        
        click.echo(f"✅ Workflow loaded: {workflow.name} ({len(workflow.tasks)} tasks)")
        
    except Exception as e:
        click.echo(f"❌ Failed to load workflow: {e}", err=True)
        return
    
    if dry_run:
        click.echo("🧪 Dry run mode - workflow validation successful")
        _display_workflow_summary(workflow)
        return
    
    # Connect to Gleitzeit and submit workflow
    client = GleitzeitClient(config)
    
    try:
        click.echo("🔗 Connecting to Gleitzeit...")
        await client.connect()
        
        click.echo(f"📤 Submitting workflow with priority: {priority}")
        workflow_id = await client.submit_workflow(workflow, priority)
        
        click.echo(f"✅ Workflow submitted successfully!")
        click.echo(f"   Workflow ID: {workflow_id}")
        
        if watch:
            click.echo("👀 Watching workflow execution...")
            await _watch_workflow(client, workflow_id)
        else:
            click.echo(f"💡 Use 'gleitzeit status {workflow_id}' to check progress")
            click.echo(f"💡 Use 'gleitzeit logs {workflow_id} --follow' to watch execution")
        
    except Exception as e:
        click.echo(f"❌ Submission failed: {e}", err=True)
        
    finally:
        await client.disconnect()


def _display_workflow_summary(workflow) -> None:
    """Display workflow summary for dry run"""
    click.echo(f"\n📋 Workflow Summary:")
    click.echo(f"   Name: {workflow.name}")
    click.echo(f"   Description: {workflow.description or 'No description'}")
    click.echo(f"   Tasks: {len(workflow.tasks)}")
    
    # Show task dependency graph
    if workflow.tasks:
        click.echo(f"\n📊 Task Dependencies:")
        for task in workflow.tasks:
            deps = task.dependencies or []
            if deps:
                click.echo(f"   {task.id} ← {', '.join(deps)}")
            else:
                click.echo(f"   {task.id} (no dependencies)")
    
    # Show protocols used
    protocols = set(task.protocol for task in workflow.tasks)
    if protocols:
        click.echo(f"\n🔌 Protocols Required:")
        for protocol in sorted(protocols):
            click.echo(f"   • {protocol}")


async def _watch_workflow(client: GleitzeitClient, workflow_id: str) -> None:
    """Watch workflow execution with live event streaming"""
    try:
        async for event in client.stream_workflow_events(workflow_id):
            _display_event(event)
            
    except KeyboardInterrupt:
        click.echo("\n⏹️  Stopped watching (workflow continues in background)")
    except Exception as e:
        click.echo(f"\n⚠️  Error watching workflow: {e}", err=True)


def _display_event(event: Dict[str, Any]) -> None:
    """Display workflow event in user-friendly format"""
    event_type = event.get('event_type', '')
    timestamp = event.get('timestamp', '')
    
    if 'workflow:' in event_type:
        if event_type == 'workflow:started':
            click.echo(f"🚀 [{timestamp}] Workflow started")
            
        elif event_type == 'workflow:completed':
            duration = event.get('duration', 0)
            click.echo(f"✅ [{timestamp}] Workflow completed in {duration:.2f}s")
            
        elif event_type == 'workflow:failed':
            error = event.get('error', 'Unknown error')
            click.echo(f"❌ [{timestamp}] Workflow failed: {error}")
    
    elif 'task:' in event_type:
        task_id = event.get('task_id', 'unknown')
        
        if event_type == 'task:started':
            click.echo(f"▶️  [{timestamp}] Task {task_id} started")
            
        elif event_type == 'task:completed':
            duration = event.get('duration', 0)
            click.echo(f"✅ [{timestamp}] Task {task_id} completed in {duration:.2f}s")
            
        elif event_type == 'task:failed':
            error = event.get('error', 'Unknown error')
            click.echo(f"❌ [{timestamp}] Task {task_id} failed: {error}")
            
        elif event_type == 'task:retry_executed':
            attempt = event.get('attempt_count', 1)
            click.echo(f"🔄 [{timestamp}] Task {task_id} retry attempt #{attempt}")