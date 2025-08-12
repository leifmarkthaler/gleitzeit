#!/usr/bin/env python3
"""
Deep inspection tool for Gleitzeit

Detailed inspection of workflows, tasks, and nodes.
Shows complete data, configurations, and error details.
"""

import asyncio
import sys
import json
from datetime import datetime
from typing import Optional, Dict, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich.tree import Tree
from rich import box

from .core.cluster import GleitzeitCluster


class Inspector:
    """Deep inspection tool for cluster entities"""
    
    def __init__(self, cluster_url: str = "http://localhost:8000"):
        self.cluster_url = cluster_url
        self.console = Console()
        self.cluster: Optional[GleitzeitCluster] = None
    
    async def inspect_workflow(self, workflow_id: str, json_output: bool = False):
        """Inspect a specific workflow in detail"""
        
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
        
        # Get workflow details
        workflow = await self.cluster.get_workflow_status(workflow_id)
        
        if not workflow:
            self.console.print(f"[red]Workflow not found: {workflow_id}[/]")
            return
        
        if json_output:
            self.console.print_json(data=workflow)
        else:
            self.display_workflow_details(workflow)
    
    async def inspect_task(self, task_id: str, json_output: bool = False):
        """Inspect a specific task in detail"""
        
        if not self.cluster:
            self.cluster = GleitzeitCluster(
                socketio_url=self.cluster_url,
                enable_redis=False,
                enable_socketio=True,
                enable_real_execution=False,
                auto_start_services=False
            )
            await self.cluster.start()
        
        # Get task details
        task = await self.cluster.get_task_details(task_id)
        
        if not task:
            self.console.print(f"[red]Task not found: {task_id}[/]")
            return
        
        if json_output:
            self.console.print_json(data=task)
        else:
            self.display_task_details(task)
    
    async def inspect_node(self, node_id: str, json_output: bool = False):
        """Inspect a specific node in detail"""
        
        if not self.cluster:
            self.cluster = GleitzeitCluster(
                socketio_url=self.cluster_url,
                enable_redis=False,
                enable_socketio=True,
                enable_real_execution=False,
                auto_start_services=False
            )
            await self.cluster.start()
        
        # Get node details
        status = await self.cluster.get_cluster_status()
        nodes = status.get('nodes', {})
        node = nodes.get(node_id)
        
        if not node:
            # Try to find by partial match
            for nid, ndata in nodes.items():
                if node_id in nid:
                    node = ndata
                    node['id'] = nid
                    break
        
        if not node:
            self.console.print(f"[red]Node not found: {node_id}[/]")
            return
        
        if json_output:
            self.console.print_json(data=node)
        else:
            self.display_node_details(node)
    
    def display_workflow_details(self, workflow: Dict[str, Any]):
        """Display workflow details in rich format"""
        
        # Header
        wf_id = workflow.get('id', 'Unknown')
        wf_name = workflow.get('name', 'Unnamed')
        self.console.print(Panel(f"[bold]Workflow: {wf_name}[/]\nID: {wf_id}", box=box.DOUBLE))
        
        # Status and Progress
        status_table = Table(box=box.SIMPLE, show_header=False)
        status_table.add_column("Field", style="cyan")
        status_table.add_column("Value")
        
        status = workflow.get('status', 'unknown')
        status_color = {
            'completed': 'green',
            'running': 'yellow',
            'failed': 'red',
            'pending': 'white'
        }.get(status, 'white')
        
        status_table.add_row("Status", f"[{status_color}]{status}[/]")
        status_table.add_row("Created", workflow.get('created_at', 'Unknown'))
        
        if workflow.get('completed_at'):
            status_table.add_row("Completed", workflow['completed_at'])
            
        completed = workflow.get('completed_tasks', 0)
        total = workflow.get('total_tasks', 0)
        status_table.add_row("Progress", f"{completed}/{total} tasks")
        
        if workflow.get('error'):
            status_table.add_row("Error", f"[red]{workflow['error']}[/]")
        
        self.console.print(status_table)
        self.console.print()
        
        # Task Tree
        self.console.print("[bold]Task Hierarchy:[/]")
        task_tree = Tree("Tasks")
        
        tasks = workflow.get('tasks', [])
        for task in tasks:
            task_name = task.get('name', task.get('id', 'Unknown'))
            task_status = task.get('status', 'unknown')
            task_type = task.get('type', 'unknown')
            
            status_emoji = {
                'completed': '✅',
                'running': '🔄',
                'failed': '❌',
                'pending': '⏳'
            }.get(task_status, '❓')
            
            task_node = task_tree.add(f"{status_emoji} {task_name} ({task_type})")
            
            # Add dependencies
            deps = task.get('dependencies', [])
            if deps:
                deps_node = task_node.add("[dim]Dependencies:[/]")
                for dep in deps:
                    deps_node.add(f"→ {dep}")
            
            # Add result preview if available
            if task.get('result'):
                result_str = str(task['result'])[:100]
                if len(result_str) == 100:
                    result_str += "..."
                task_node.add(f"[dim]Result: {result_str}[/]")
        
        self.console.print(task_tree)
        self.console.print()
        
        # Workflow Configuration
        if workflow.get('config'):
            self.console.print("[bold]Configuration:[/]")
            config_json = json.dumps(workflow['config'], indent=2)
            syntax = Syntax(config_json, "json", theme="monokai", line_numbers=False)
            self.console.print(syntax)
            self.console.print()
        
        # Error Details
        if workflow.get('error_details'):
            self.console.print(Panel(
                workflow['error_details'],
                title="[red]Error Details[/]",
                box=box.ROUNDED,
                style="red"
            ))
    
    def display_task_details(self, task: Dict[str, Any]):
        """Display task details in rich format"""
        
        # Header
        task_id = task.get('id', 'Unknown')
        task_name = task.get('name', 'Unnamed')
        self.console.print(Panel(f"[bold]Task: {task_name}[/]\nID: {task_id}", box=box.DOUBLE))
        
        # Basic Info
        info_table = Table(box=box.SIMPLE, show_header=False)
        info_table.add_column("Field", style="cyan", width=20)
        info_table.add_column("Value")
        
        status = task.get('status', 'unknown')
        status_color = {
            'completed': 'green',
            'running': 'yellow',
            'failed': 'red',
            'pending': 'white'
        }.get(status, 'white')
        
        info_table.add_row("Status", f"[{status_color}]{status}[/]")
        info_table.add_row("Type", task.get('type', 'Unknown'))
        info_table.add_row("Workflow", task.get('workflow_id', 'Unknown'))
        info_table.add_row("Node", task.get('node', 'Not assigned'))
        info_table.add_row("Created", task.get('created_at', 'Unknown'))
        
        if task.get('started_at'):
            info_table.add_row("Started", task['started_at'])
        
        if task.get('completed_at'):
            info_table.add_row("Completed", task['completed_at'])
            
            # Calculate duration
            try:
                start = datetime.fromisoformat(task['started_at'])
                end = datetime.fromisoformat(task['completed_at'])
                duration = (end - start).total_seconds()
                info_table.add_row("Duration", f"{duration:.2f} seconds")
            except:
                pass
        
        self.console.print(info_table)
        self.console.print()
        
        # Parameters
        if task.get('parameters'):
            self.console.print("[bold]Parameters:[/]")
            params_json = json.dumps(task['parameters'], indent=2)
            syntax = Syntax(params_json, "json", theme="monokai", line_numbers=False)
            self.console.print(syntax)
            self.console.print()
        
        # Result
        if task.get('result'):
            self.console.print("[bold]Result:[/]")
            if isinstance(task['result'], (dict, list)):
                result_json = json.dumps(task['result'], indent=2)
                syntax = Syntax(result_json, "json", theme="monokai", line_numbers=False)
                self.console.print(syntax)
            else:
                self.console.print(Panel(str(task['result']), box=box.ROUNDED))
            self.console.print()
        
        # Error
        if task.get('error'):
            self.console.print(Panel(
                task['error'],
                title="[red]Error[/]",
                box=box.ROUNDED,
                style="red"
            ))
            
            if task.get('error_traceback'):
                self.console.print("[bold red]Traceback:[/]")
                self.console.print(task['error_traceback'])
        
        # Dependencies
        if task.get('dependencies'):
            self.console.print("[bold]Dependencies:[/]")
            for dep in task['dependencies']:
                self.console.print(f"  • {dep}")
            self.console.print()
        
        # Retry Information
        if task.get('retry_count', 0) > 0:
            self.console.print(f"[yellow]Retries: {task['retry_count']}/{task.get('max_retries', 3)}[/]")
    
    def display_node_details(self, node: Dict[str, Any]):
        """Display node details in rich format"""
        
        # Header
        node_id = node.get('id', 'Unknown')
        node_name = node.get('name', node_id)
        self.console.print(Panel(f"[bold]Node: {node_name}[/]\nID: {node_id}", box=box.DOUBLE))
        
        # Status
        status_table = Table(box=box.SIMPLE, show_header=False)
        status_table.add_column("Field", style="cyan", width=20)
        status_table.add_column("Value")
        
        status = node.get('status', 'unknown')
        status_color = 'green' if status == 'active' else 'red'
        
        status_table.add_row("Status", f"[{status_color}]{status}[/]")
        status_table.add_row("Type", node.get('type', 'executor'))
        status_table.add_row("Started", node.get('started_at', 'Unknown'))
        
        # Calculate uptime
        if node.get('started_at'):
            try:
                start = datetime.fromisoformat(node['started_at'])
                uptime = datetime.now() - start
                hours = int(uptime.total_seconds() // 3600)
                minutes = int((uptime.total_seconds() % 3600) // 60)
                status_table.add_row("Uptime", f"{hours}h {minutes}m")
            except:
                pass
        
        status_table.add_row("Last Heartbeat", node.get('last_heartbeat', 'Unknown'))
        
        self.console.print(status_table)
        self.console.print()
        
        # Performance
        self.console.print("[bold]Performance:[/]")
        perf_table = Table(box=box.SIMPLE, show_header=False)
        perf_table.add_column("Metric", style="cyan", width=20)
        perf_table.add_column("Value")
        
        perf_table.add_row("Tasks Processed", str(node.get('tasks_processed', 0)))
        perf_table.add_row("Tasks Succeeded", f"[green]{node.get('tasks_succeeded', 0)}[/]")
        perf_table.add_row("Tasks Failed", f"[red]{node.get('tasks_failed', 0)}[/]")
        perf_table.add_row("Current Load", str(node.get('current_load', 0)))
        perf_table.add_row("Max Concurrent", str(node.get('max_concurrent', 10)))
        
        self.console.print(perf_table)
        self.console.print()
        
        # Resources
        self.console.print("[bold]Resources:[/]")
        resource_table = Table(box=box.SIMPLE, show_header=False)
        resource_table.add_column("Resource", style="cyan", width=20)
        resource_table.add_column("Usage")
        
        cpu = node.get('cpu_usage', 0)
        cpu_color = 'green' if cpu < 50 else 'yellow' if cpu < 80 else 'red'
        resource_table.add_row("CPU Usage", f"[{cpu_color}]{cpu:.1f}%[/]")
        
        mem_mb = node.get('memory_usage', 0)
        mem_gb = mem_mb / 1024
        resource_table.add_row("Memory Usage", f"{mem_gb:.2f} GB")
        
        resource_table.add_row("Has GPU", "Yes" if node.get('has_gpu') else "No")
        
        self.console.print(resource_table)
        self.console.print()
        
        # Capabilities
        if node.get('capabilities'):
            self.console.print("[bold]Capabilities:[/]")
            cap_json = json.dumps(node['capabilities'], indent=2)
            syntax = Syntax(cap_json, "json", theme="monokai", line_numbers=False)
            self.console.print(syntax)
            self.console.print()
        
        # Current Tasks
        if node.get('current_tasks'):
            self.console.print("[bold]Currently Processing:[/]")
            for task_id in node['current_tasks']:
                self.console.print(f"  • {task_id}")


async def inspect_command_handler(args):
    """Handle inspect command"""
    inspector = Inspector(
        cluster_url=getattr(args, 'cluster', "http://localhost:8000")
    )
    
    try:
        entity_type = getattr(args, 'type')
        entity_id = getattr(args, 'id')
        json_output = getattr(args, 'json', False)
        
        if entity_type == 'workflow':
            await inspector.inspect_workflow(entity_id, json_output)
        elif entity_type == 'task':
            await inspector.inspect_task(entity_id, json_output)
        elif entity_type == 'node':
            await inspector.inspect_node(entity_id, json_output)
        else:
            inspector.console.print(f"[red]Unknown entity type: {entity_type}[/]")
            
    finally:
        if inspector.cluster:
            await inspector.cluster.stop()


def main():
    """Standalone entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gleitzeit deep inspection tool")
    parser.add_argument('type', choices=['workflow', 'task', 'node'],
                       help='Entity type to inspect')
    parser.add_argument('id', help='Entity ID to inspect')
    parser.add_argument('--cluster', default="http://localhost:8000", help='Cluster URL')
    parser.add_argument('--json', action='store_true',
                       help='Output as JSON')
    
    args = parser.parse_args()
    
    try:
        asyncio.run(inspect_command_handler(args))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()