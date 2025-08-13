#!/usr/bin/env python3
"""
Targeted monitoring for Gleitzeit

Watch specific workflows, tasks, or queues with minimal UI.
Exits when workflow completes or on user interrupt.
"""

import asyncio
import sys
from datetime import datetime
from typing import Optional, Dict, Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich import box

from .core.cluster import GleitzeitCluster


class WatchTarget:
    """Watch a specific target with focused monitoring"""
    
    def __init__(self, cluster_url: str = "http://localhost:8000"):
        self.cluster_url = cluster_url
        self.console = Console()
        self.cluster: Optional[GleitzeitCluster] = None
    
    async def watch_workflow(self, workflow_id: str, exit_on_complete: bool = True):
        """Watch a specific workflow until completion"""
        
        # Initialize cluster connection
        if not self.cluster:
            self.cluster = GleitzeitCluster(
                socketio_url=self.cluster_url,
                enable_redis=False,
                enable_socketio=True,
                enable_real_execution=False,
                auto_start_services=False
            )
            await self.cluster.start()
        
        self.console.print(f"[cyan]Watching workflow: {workflow_id}[/]\n")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self.console
        ) as progress:
            
            # Create progress task
            task = progress.add_task("Workflow Progress", total=100)
            
            last_status = None
            while True:
                try:
                    # Get workflow status
                    workflow = await self.cluster.get_workflow_status(workflow_id)
                    
                    if not workflow:
                        self.console.print(f"[red]Workflow not found: {workflow_id}[/]")
                        break
                    
                    # Update progress
                    completed = workflow.get('completed_tasks', 0)
                    total = workflow.get('total_tasks', 1)
                    percentage = (completed / total * 100) if total > 0 else 0
                    
                    status = workflow.get('status', 'unknown')
                    
                    # Update progress bar
                    progress.update(
                        task,
                        completed=percentage,
                        description=f"[{self.get_status_color(status)}]{status}[/] - {completed}/{total} tasks"
                    )
                    
                    # Show status change
                    if status != last_status:
                        self.console.print(f"Status: [{self.get_status_color(status)}]{status}[/]")
                        last_status = status
                    
                    # Show task updates
                    for task_data in workflow.get('tasks', []):
                        task_status = task_data.get('status')
                        if task_status == 'running':
                            self.console.print(f"  Running: {task_data.get('name', task_data.get('id'))}")
                        elif task_status == 'failed':
                            self.console.print(f"  [red]Failed: {task_data.get('name')} - {task_data.get('error')}[/]")
                    
                    # Check if complete
                    if status in ['completed', 'failed'] and exit_on_complete:
                        if status == 'completed':
                            self.console.print(f"\n[green]✅ Workflow completed successfully![/]")
                        else:
                            self.console.print(f"\n[red]❌ Workflow failed![/]")
                            if workflow.get('error'):
                                self.console.print(f"Error: {workflow['error']}")
                        break
                    
                    await asyncio.sleep(1)
                    
                except KeyboardInterrupt:
                    self.console.print("\n[yellow]Watch interrupted[/]")
                    break
                except Exception as e:
                    self.console.print(f"[red]Error: {e}[/]")
                    await asyncio.sleep(1)
    
    async def watch_task(self, task_id: str):
        """Watch a specific task until completion"""
        
        if not self.cluster:
            self.cluster = GleitzeitCluster(
                socketio_url=self.cluster_url,
                enable_redis=False,
                enable_socketio=True,
                enable_real_execution=False,
                auto_start_services=False
            )
            await self.cluster.start()
        
        self.console.print(f"[cyan]Watching task: {task_id}[/]\n")
        
        last_status = None
        start_time = datetime.now()
        
        with Live(self.render_task_status({}), refresh_per_second=2, console=self.console) as live:
            while True:
                try:
                    # Get task details
                    task = await self.cluster.get_task_details(task_id)
                    
                    if not task:
                        self.console.print(f"[red]Task not found: {task_id}[/]")
                        break
                    
                    # Update display
                    task['elapsed'] = str(datetime.now() - start_time).split('.')[0]
                    live.update(self.render_task_status(task))
                    
                    status = task.get('status', 'unknown')
                    
                    # Check if complete
                    if status in ['completed', 'failed']:
                        if status == 'completed':
                            self.console.print(f"\n[green]✅ Task completed![/]")
                            if task.get('result'):
                                self.console.print(f"Result: {task['result']}")
                        else:
                            self.console.print(f"\n[red]❌ Task failed![/]")
                            if task.get('error'):
                                self.console.print(f"Error: {task['error']}")
                        break
                    
                    await asyncio.sleep(0.5)
                    
                except KeyboardInterrupt:
                    self.console.print("\n[yellow]Watch interrupted[/]")
                    break
                except Exception as e:
                    await asyncio.sleep(1)
    
    async def watch_queue(self):
        """Watch the task queue"""
        
        if not self.cluster:
            self.cluster = GleitzeitCluster(
                socketio_url=self.cluster_url,
                enable_redis=False,
                enable_socketio=True,
                enable_real_execution=False,
                auto_start_services=False
            )
            await self.cluster.start()
        
        self.console.print("[cyan]Watching task queue[/]\n")
        
        with Live(self.render_queue_status({}), refresh_per_second=1, console=self.console) as live:
            while True:
                try:
                    # Get queue status
                    status = await self.cluster.get_cluster_status()
                    queue_info = {
                        'depth': status.get('queue_depth', 0),
                        'pending_tasks': status.get('pending_tasks', []),
                        'running_tasks': status.get('running_tasks', []),
                        'processing_rate': status.get('tasks_per_second', 0)
                    }
                    
                    live.update(self.render_queue_status(queue_info))
                    
                    await asyncio.sleep(1)
                    
                except KeyboardInterrupt:
                    self.console.print("\n[yellow]Watch interrupted[/]")
                    break
                except Exception:
                    await asyncio.sleep(1)
    
    def render_task_status(self, task: Dict[str, Any]) -> Panel:
        """Render task status panel"""
        table = Table(box=box.SIMPLE, show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        
        status = task.get('status', 'unknown')
        table.add_row("Status", f"[{self.get_status_color(status)}]{status}[/]")
        table.add_row("Type", task.get('type', '-'))
        table.add_row("Node", task.get('node', 'Not assigned'))
        table.add_row("Elapsed", task.get('elapsed', '-'))
        
        if task.get('progress'):
            table.add_row("Progress", f"{task['progress']}%")
        
        if task.get('retry_count', 0) > 0:
            table.add_row("Retries", f"{task['retry_count']}/{task.get('max_retries', 3)}")
        
        return Panel(table, title=f"Task: {task.get('name', task.get('id', 'Unknown'))}", box=box.ROUNDED)
    
    def render_queue_status(self, queue_info: Dict[str, Any]) -> Panel:
        """Render queue status panel"""
        table = Table(box=box.SIMPLE, show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        
        depth = queue_info.get('depth', 0)
        color = 'green' if depth < 10 else 'yellow' if depth < 50 else 'red'
        
        table.add_row("Queue Depth", f"[{color}]{depth}[/]")
        table.add_row("Pending Tasks", str(len(queue_info.get('pending_tasks', []))))
        table.add_row("Running Tasks", str(len(queue_info.get('running_tasks', []))))
        table.add_row("Processing Rate", f"{queue_info.get('processing_rate', 0):.1f} tasks/sec")
        
        # Show next tasks in queue
        pending = queue_info.get('pending_tasks', [])[:5]
        if pending:
            table.add_row("", "")
            table.add_row("[bold]Next in Queue[/]", "")
            for task in pending:
                table.add_row("", f"• {task.get('name', task.get('id', 'Unknown'))}")
        
        return Panel(table, title="Task Queue Status", box=box.ROUNDED)
    
    def get_status_color(self, status: str) -> str:
        """Get color for status"""
        return {
            'completed': 'green',
            'running': 'yellow',
            'failed': 'red',
            'pending': 'white'
        }.get(status, 'white')


async def watch_command_handler(args):
    """Handle watch command"""
    watcher = WatchTarget(
        cluster_url=getattr(args, 'cluster', "http://localhost:8000")
    )
    
    target_type = getattr(args, 'type')
    target_id = getattr(args, 'id', None)
    
    try:
        if target_type == 'workflow':
            await watcher.watch_workflow(
                target_id,
                exit_on_complete=not getattr(args, 'no_exit', False)
            )
        elif target_type == 'task':
            await watcher.watch_task(target_id)
        elif target_type == 'queue':
            await watcher.watch_queue()
        else:
            watcher.console.print(f"[red]Unknown target type: {target_type}[/]")
            
    finally:
        if watcher.cluster:
            await watcher.cluster.stop()


def main():
    """Standalone entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gleitzeit targeted monitoring")
    
    subparsers = parser.add_subparsers(dest='type', help='What to watch')
    
    # Watch workflow
    workflow_parser = subparsers.add_parser('workflow', help='Watch a workflow')
    workflow_parser.add_argument('id', help='Workflow ID')
    workflow_parser.add_argument('--no-exit', action='store_true',
                                help="Don't exit when workflow completes")
    
    # Watch task
    task_parser = subparsers.add_parser('task', help='Watch a task')
    task_parser.add_argument('id', help='Task ID')
    
    # Watch queue
    queue_parser = subparsers.add_parser('queue', help='Watch the task queue')
    
    parser.add_argument('--cluster', default="http://localhost:8000", help='Cluster URL')
    
    args = parser.parse_args()
    
    if not args.type:
        parser.print_help()
        sys.exit(1)
    
    try:
        asyncio.run(watch_command_handler(args))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()