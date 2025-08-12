#!/usr/bin/env python3
"""
Real-time monitoring dashboard for Gleitzeit

Simple, clean terminal dashboard for monitoring workflows, tasks, and nodes.
Focuses on current state without excessive styling.
"""

import asyncio
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich import box

from .core.cluster import GleitzeitCluster
from .core.task import TaskStatus


class MonitorDashboard:
    """Clean, focused monitoring dashboard"""
    
    def __init__(self, cluster_url: str = "http://localhost:8000", refresh_rate: float = 1.0):
        self.cluster_url = cluster_url
        self.refresh_rate = refresh_rate
        self.console = Console()
        self.cluster: Optional[GleitzeitCluster] = None
        
        # Current state
        self.workflows = {}
        self.tasks = {}
        self.nodes = {}
        self.stats = {
            "total_workflows": 0,
            "active_workflows": 0,
            "completed_workflows": 0,
            "total_tasks": 0,
            "pending_tasks": 0,
            "running_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "active_nodes": 0
        }
    
    def create_layout(self) -> Layout:
        """Create dashboard layout"""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=1)
        )
        
        # Split main area
        layout["main"].split_row(
            Layout(name="workflows", ratio=1),
            Layout(name="tasks", ratio=1)
        )
        
        return layout
    
    def render_header(self) -> Panel:
        """Render header with title and stats"""
        stats_text = (
            f"Workflows: [green]{self.stats['active_workflows']}[/] active / "
            f"[blue]{self.stats['completed_workflows']}[/] completed | "
            f"Tasks: [yellow]{self.stats['running_tasks']}[/] running / "
            f"[green]{self.stats['completed_tasks']}[/] completed / "
            f"[red]{self.stats['failed_tasks']}[/] failed | "
            f"Nodes: [cyan]{self.stats['active_nodes']}[/]"
        )
        
        header = Table.grid(padding=0)
        header.add_column(justify="left")
        header.add_column(justify="right")
        header.add_row(
            "[bold]Gleitzeit Monitor[/]",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        header.add_row(stats_text, "")
        
        return Panel(header, box=box.ROUNDED, style="blue")
    
    def render_workflows(self) -> Panel:
        """Render active workflows table"""
        table = Table(
            title="Active Workflows",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold"
        )
        
        table.add_column("ID", width=12)
        table.add_column("Name", width=20)
        table.add_column("Status", width=10)
        table.add_column("Progress", width=12)
        table.add_column("Duration", width=10)
        
        # Add workflow rows (sorted by most recent)
        for wf_id, wf in sorted(self.workflows.items(), key=lambda x: x[1].get('created_at', ''), reverse=True)[:10]:
            status = wf.get('status', 'unknown')
            completed = wf.get('completed_tasks', 0)
            total = wf.get('total_tasks', 0)
            
            # Status color
            status_color = {
                'running': 'yellow',
                'completed': 'green',
                'failed': 'red',
                'pending': 'white'
            }.get(status, 'white')
            
            # Progress
            progress = f"{completed}/{total}" if total > 0 else "0/0"
            
            # Duration
            if 'created_at' in wf:
                start = datetime.fromisoformat(wf['created_at'])
                duration = str(datetime.now() - start).split('.')[0]
            else:
                duration = "-"
            
            table.add_row(
                wf_id[:8] + "...",
                wf.get('name', 'Unnamed')[:20],
                f"[{status_color}]{status}[/]",
                progress,
                duration
            )
        
        if not self.workflows:
            table.add_row("[dim]No active workflows[/]", "", "", "", "")
        
        return Panel(table, title="[bold]Workflows[/]", box=box.ROUNDED)
    
    def render_tasks(self) -> Panel:
        """Render recent tasks table"""
        table = Table(
            title="Recent Tasks",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold"
        )
        
        table.add_column("Task", width=20)
        table.add_column("Type", width=10)
        table.add_column("Status", width=10)
        table.add_column("Node", width=15)
        table.add_column("Time", width=8)
        
        # Add task rows (most recent first)
        recent_tasks = sorted(
            self.tasks.items(),
            key=lambda x: x[1].get('updated_at', ''),
            reverse=True
        )[:15]
        
        for task_id, task in recent_tasks:
            name = task.get('name', task_id[:8])[:20]
            task_type = task.get('type', 'unknown')
            status = task.get('status', 'unknown')
            node = task.get('node', '-')[:15]
            
            # Status color
            status_color = {
                'running': 'yellow',
                'completed': 'green',
                'failed': 'red',
                'pending': 'white'
            }.get(status, 'white')
            
            # Time
            if 'updated_at' in task:
                time_str = datetime.fromisoformat(task['updated_at']).strftime("%H:%M:%S")
            else:
                time_str = "-"
            
            table.add_row(
                name,
                task_type,
                f"[{status_color}]{status}[/]",
                node,
                time_str
            )
        
        if not self.tasks:
            table.add_row("[dim]No recent tasks[/]", "", "", "", "")
        
        return Panel(table, title="[bold]Tasks[/]", box=box.ROUNDED)
    
    def render_footer(self) -> Panel:
        """Render footer with help text"""
        help_text = "Press [bold]Ctrl+C[/] to exit | [dim]Refreshing every {:.1f}s[/]".format(self.refresh_rate)
        return Panel(
            Align.center(help_text),
            box=box.ROUNDED,
            style="dim"
        )
    
    async def fetch_data(self):
        """Fetch latest data from cluster"""
        if not self.cluster:
            return
        
        try:
            # Get cluster status
            status = await self.cluster.get_cluster_status()
            
            # Update nodes
            self.nodes = status.get('nodes', {})
            self.stats['active_nodes'] = len([n for n in self.nodes.values() if n.get('status') == 'active'])
            
            # Get workflows
            workflows = await self.cluster.list_workflows()
            self.workflows = {w['id']: w for w in workflows if w.get('status') in ['running', 'pending']}
            
            # Update stats
            self.stats['active_workflows'] = len(self.workflows)
            
            # Get recent tasks
            # This would need an API endpoint for recent tasks
            # For now, extract from workflows
            self.tasks = {}
            for wf in self.workflows.values():
                for task in wf.get('tasks', []):
                    self.tasks[task['id']] = task
            
            # Update task stats
            self.stats['total_tasks'] = len(self.tasks)
            self.stats['running_tasks'] = len([t for t in self.tasks.values() if t.get('status') == 'running'])
            self.stats['completed_tasks'] = len([t for t in self.tasks.values() if t.get('status') == 'completed'])
            self.stats['failed_tasks'] = len([t for t in self.tasks.values() if t.get('status') == 'failed'])
            self.stats['pending_tasks'] = len([t for t in self.tasks.values() if t.get('status') == 'pending'])
            
        except Exception as e:
            # Connection error - show in UI but don't crash
            pass
    
    def render(self) -> Layout:
        """Render the complete dashboard"""
        layout = self.create_layout()
        
        layout["header"].update(self.render_header())
        layout["workflows"].update(self.render_workflows())
        layout["tasks"].update(self.render_tasks())
        layout["footer"].update(self.render_footer())
        
        return layout
    
    async def run(self):
        """Run the monitoring dashboard"""
        # Initialize cluster connection
        self.cluster = GleitzeitCluster(
            socketio_url=self.cluster_url,
            enable_redis=False,
            enable_socketio=True,
            enable_real_execution=False,
            auto_start_services=False
        )
        
        try:
            await self.cluster.start()
            
            # Main monitoring loop
            with Live(self.render(), refresh_per_second=1, console=self.console) as live:
                while True:
                    await self.fetch_data()
                    live.update(self.render())
                    await asyncio.sleep(self.refresh_rate)
                    
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Monitoring stopped[/]")
        finally:
            if self.cluster:
                await self.cluster.stop()


async def monitor_command_handler(args):
    """Handle monitor command"""
    dashboard = MonitorDashboard(
        cluster_url=args.cluster if hasattr(args, 'cluster') else "http://localhost:8000",
        refresh_rate=args.refresh if hasattr(args, 'refresh') else 1.0
    )
    
    await dashboard.run()


def main():
    """Standalone entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gleitzeit real-time monitor")
    parser.add_argument('--cluster', default="http://localhost:8000", help='Cluster URL')
    parser.add_argument('--refresh', type=float, default=1.0, help='Refresh rate in seconds')
    
    args = parser.parse_args()
    
    try:
        asyncio.run(monitor_command_handler(args))
    except KeyboardInterrupt:
        print("\nMonitoring stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()