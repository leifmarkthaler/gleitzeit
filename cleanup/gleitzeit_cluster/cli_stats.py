#!/usr/bin/env python3
"""
Statistics and analytics for Gleitzeit

Performance metrics, resource utilization, and historical analysis.
Export to JSON/CSV for further analysis.
"""

import asyncio
import sys
import json
import csv
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from collections import defaultdict
from statistics import mean, median, stdev

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from .core.cluster import GleitzeitCluster


@dataclass
class TaskStats:
    """Statistics for task execution"""
    total_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    pending_count: int = 0
    running_count: int = 0
    avg_duration_seconds: float = 0.0
    min_duration_seconds: float = 0.0
    max_duration_seconds: float = 0.0
    median_duration_seconds: float = 0.0
    success_rate: float = 0.0


@dataclass
class WorkflowStats:
    """Statistics for workflow execution"""
    total_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    running_count: int = 0
    avg_tasks_per_workflow: float = 0.0
    avg_duration_seconds: float = 0.0
    success_rate: float = 0.0


@dataclass
class NodeStats:
    """Statistics for node performance"""
    node_id: str
    status: str
    tasks_processed: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    avg_task_duration: float = 0.0
    uptime_seconds: float = 0.0
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0


@dataclass
class ClusterStats:
    """Overall cluster statistics"""
    timestamp: str
    total_nodes: int = 0
    active_nodes: int = 0
    total_workflows: int = 0
    total_tasks: int = 0
    tasks_per_second: float = 0.0
    queue_depth: int = 0
    avg_queue_wait_seconds: float = 0.0
    task_stats: Optional[TaskStats] = None
    workflow_stats: Optional[WorkflowStats] = None
    node_stats: List[NodeStats] = None


class StatsAnalyzer:
    """Analyze and display cluster statistics"""
    
    def __init__(self, cluster_url: str = "http://localhost:8000"):
        self.cluster_url = cluster_url
        self.console = Console()
        self.cluster: Optional[GleitzeitCluster] = None
    
    async def collect_stats(self, time_range: Optional[int] = None) -> ClusterStats:
        """Collect statistics from cluster"""
        
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
        
        # Get cluster status
        status = await self.cluster.get_cluster_status()
        
        # Get workflows
        workflows = await self.cluster.list_workflows()
        
        # Calculate task statistics
        task_stats = self.calculate_task_stats(workflows)
        
        # Calculate workflow statistics
        workflow_stats = self.calculate_workflow_stats(workflows)
        
        # Calculate node statistics
        node_stats = self.calculate_node_stats(status.get('nodes', {}))
        
        # Build overall stats
        stats = ClusterStats(
            timestamp=datetime.now().isoformat(),
            total_nodes=len(status.get('nodes', {})),
            active_nodes=len([n for n in status.get('nodes', {}).values() if n.get('status') == 'active']),
            total_workflows=len(workflows),
            total_tasks=task_stats.total_count,
            queue_depth=status.get('queue_depth', 0),
            task_stats=task_stats,
            workflow_stats=workflow_stats,
            node_stats=node_stats
        )
        
        return stats
    
    def calculate_task_stats(self, workflows: List[Dict]) -> TaskStats:
        """Calculate task statistics from workflows"""
        all_tasks = []
        for wf in workflows:
            all_tasks.extend(wf.get('tasks', []))
        
        if not all_tasks:
            return TaskStats()
        
        # Count by status
        status_counts = defaultdict(int)
        durations = []
        
        for task in all_tasks:
            status = task.get('status', 'unknown')
            status_counts[status] += 1
            
            # Calculate duration if available
            if 'started_at' in task and 'completed_at' in task:
                try:
                    start = datetime.fromisoformat(task['started_at'])
                    end = datetime.fromisoformat(task['completed_at'])
                    duration = (end - start).total_seconds()
                    durations.append(duration)
                except:
                    pass
        
        # Calculate statistics
        stats = TaskStats(
            total_count=len(all_tasks),
            completed_count=status_counts.get('completed', 0),
            failed_count=status_counts.get('failed', 0),
            pending_count=status_counts.get('pending', 0),
            running_count=status_counts.get('running', 0)
        )
        
        if durations:
            stats.avg_duration_seconds = mean(durations)
            stats.min_duration_seconds = min(durations)
            stats.max_duration_seconds = max(durations)
            stats.median_duration_seconds = median(durations)
        
        if stats.total_count > 0:
            stats.success_rate = stats.completed_count / stats.total_count
        
        return stats
    
    def calculate_workflow_stats(self, workflows: List[Dict]) -> WorkflowStats:
        """Calculate workflow statistics"""
        if not workflows:
            return WorkflowStats()
        
        status_counts = defaultdict(int)
        task_counts = []
        durations = []
        
        for wf in workflows:
            status = wf.get('status', 'unknown')
            status_counts[status] += 1
            
            # Task count
            task_counts.append(len(wf.get('tasks', [])))
            
            # Duration
            if 'created_at' in wf and wf.get('status') == 'completed':
                try:
                    start = datetime.fromisoformat(wf['created_at'])
                    if 'completed_at' in wf:
                        end = datetime.fromisoformat(wf['completed_at'])
                    else:
                        end = datetime.now()
                    duration = (end - start).total_seconds()
                    durations.append(duration)
                except:
                    pass
        
        stats = WorkflowStats(
            total_count=len(workflows),
            completed_count=status_counts.get('completed', 0),
            failed_count=status_counts.get('failed', 0),
            running_count=status_counts.get('running', 0)
        )
        
        if task_counts:
            stats.avg_tasks_per_workflow = mean(task_counts)
        
        if durations:
            stats.avg_duration_seconds = mean(durations)
        
        if stats.total_count > 0:
            stats.success_rate = stats.completed_count / stats.total_count
        
        return stats
    
    def calculate_node_stats(self, nodes: Dict[str, Any]) -> List[NodeStats]:
        """Calculate node statistics"""
        node_stats = []
        
        for node_id, node_data in nodes.items():
            stats = NodeStats(
                node_id=node_id,
                status=node_data.get('status', 'unknown'),
                tasks_processed=node_data.get('tasks_processed', 0),
                tasks_succeeded=node_data.get('tasks_succeeded', 0),
                tasks_failed=node_data.get('tasks_failed', 0),
                cpu_usage_percent=node_data.get('cpu_usage', 0),
                memory_usage_mb=node_data.get('memory_usage', 0)
            )
            
            # Calculate average duration
            if stats.tasks_processed > 0:
                total_duration = node_data.get('total_task_duration', 0)
                stats.avg_task_duration = total_duration / stats.tasks_processed
            
            # Calculate uptime
            if 'started_at' in node_data:
                try:
                    start = datetime.fromisoformat(node_data['started_at'])
                    stats.uptime_seconds = (datetime.now() - start).total_seconds()
                except:
                    pass
            
            node_stats.append(stats)
        
        return node_stats
    
    def display_stats(self, stats: ClusterStats, format: str = "table"):
        """Display statistics in requested format"""
        
        if format == "json":
            # JSON output
            output = asdict(stats)
            self.console.print_json(data=output)
            
        elif format == "csv":
            # CSV output (simplified flat structure)
            writer = csv.writer(sys.stdout)
            writer.writerow(['Metric', 'Value'])
            writer.writerow(['Timestamp', stats.timestamp])
            writer.writerow(['Total Nodes', stats.total_nodes])
            writer.writerow(['Active Nodes', stats.active_nodes])
            writer.writerow(['Total Workflows', stats.total_workflows])
            writer.writerow(['Total Tasks', stats.total_tasks])
            
            if stats.task_stats:
                writer.writerow(['Tasks Completed', stats.task_stats.completed_count])
                writer.writerow(['Tasks Failed', stats.task_stats.failed_count])
                writer.writerow(['Task Success Rate', f"{stats.task_stats.success_rate:.2%}"])
                writer.writerow(['Avg Task Duration (s)', f"{stats.task_stats.avg_duration_seconds:.2f}"])
            
            if stats.workflow_stats:
                writer.writerow(['Workflows Completed', stats.workflow_stats.completed_count])
                writer.writerow(['Workflow Success Rate', f"{stats.workflow_stats.success_rate:.2%}"])
                writer.writerow(['Avg Tasks per Workflow', f"{stats.workflow_stats.avg_tasks_per_workflow:.1f}"])
        
        else:
            # Table format (default)
            self.display_table_stats(stats)
    
    def display_table_stats(self, stats: ClusterStats):
        """Display statistics in rich table format"""
        
        # Cluster Overview
        overview = Table(title="Cluster Overview", box=box.ROUNDED)
        overview.add_column("Metric", style="cyan")
        overview.add_column("Value", style="white")
        
        overview.add_row("Timestamp", stats.timestamp.split('T')[1].split('.')[0])
        overview.add_row("Total Nodes", str(stats.total_nodes))
        overview.add_row("Active Nodes", f"[green]{stats.active_nodes}[/]")
        overview.add_row("Total Workflows", str(stats.total_workflows))
        overview.add_row("Total Tasks", str(stats.total_tasks))
        overview.add_row("Queue Depth", str(stats.queue_depth))
        
        self.console.print(overview)
        self.console.print()
        
        # Task Statistics
        if stats.task_stats:
            task_table = Table(title="Task Statistics", box=box.ROUNDED)
            task_table.add_column("Metric", style="cyan")
            task_table.add_column("Value", style="white")
            
            ts = stats.task_stats
            task_table.add_row("Total Tasks", str(ts.total_count))
            task_table.add_row("Completed", f"[green]{ts.completed_count}[/]")
            task_table.add_row("Failed", f"[red]{ts.failed_count}[/]")
            task_table.add_row("Pending", f"[yellow]{ts.pending_count}[/]")
            task_table.add_row("Running", f"[blue]{ts.running_count}[/]")
            task_table.add_row("Success Rate", f"{ts.success_rate:.1%}")
            
            if ts.avg_duration_seconds > 0:
                task_table.add_row("Avg Duration", f"{ts.avg_duration_seconds:.2f}s")
                task_table.add_row("Min Duration", f"{ts.min_duration_seconds:.2f}s")
                task_table.add_row("Max Duration", f"{ts.max_duration_seconds:.2f}s")
                task_table.add_row("Median Duration", f"{ts.median_duration_seconds:.2f}s")
            
            self.console.print(task_table)
            self.console.print()
        
        # Workflow Statistics  
        if stats.workflow_stats:
            wf_table = Table(title="Workflow Statistics", box=box.ROUNDED)
            wf_table.add_column("Metric", style="cyan")
            wf_table.add_column("Value", style="white")
            
            ws = stats.workflow_stats
            wf_table.add_row("Total Workflows", str(ws.total_count))
            wf_table.add_row("Completed", f"[green]{ws.completed_count}[/]")
            wf_table.add_row("Failed", f"[red]{ws.failed_count}[/]")
            wf_table.add_row("Running", f"[blue]{ws.running_count}[/]")
            wf_table.add_row("Success Rate", f"{ws.success_rate:.1%}")
            wf_table.add_row("Avg Tasks/Workflow", f"{ws.avg_tasks_per_workflow:.1f}")
            
            if ws.avg_duration_seconds > 0:
                wf_table.add_row("Avg Duration", f"{ws.avg_duration_seconds:.1f}s")
            
            self.console.print(wf_table)
            self.console.print()
        
        # Node Statistics
        if stats.node_stats:
            node_table = Table(title="Node Performance", box=box.ROUNDED)
            node_table.add_column("Node", style="cyan")
            node_table.add_column("Status", style="white")
            node_table.add_column("Tasks", style="white")
            node_table.add_column("Success", style="green")
            node_table.add_column("Failed", style="red")
            node_table.add_column("Avg Time", style="white")
            node_table.add_column("CPU %", style="yellow")
            node_table.add_column("Memory MB", style="yellow")
            
            for ns in stats.node_stats:
                status_color = "green" if ns.status == "active" else "red"
                node_table.add_row(
                    ns.node_id[:12] + "...",
                    f"[{status_color}]{ns.status}[/]",
                    str(ns.tasks_processed),
                    str(ns.tasks_succeeded),
                    str(ns.tasks_failed),
                    f"{ns.avg_task_duration:.2f}s" if ns.avg_task_duration > 0 else "-",
                    f"{ns.cpu_usage_percent:.1f}",
                    f"{ns.memory_usage_mb:.0f}"
                )
            
            self.console.print(node_table)


async def stats_command_handler(args):
    """Handle stats command"""
    analyzer = StatsAnalyzer(
        cluster_url=getattr(args, 'cluster', "http://localhost:8000")
    )
    
    try:
        # Collect statistics
        stats = await analyzer.collect_stats(
            time_range=getattr(args, 'range', None)
        )
        
        # Display statistics
        analyzer.display_stats(
            stats,
            format=getattr(args, 'format', 'table')
        )
        
    finally:
        if analyzer.cluster:
            await analyzer.cluster.stop()


def main():
    """Standalone entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gleitzeit statistics and analytics")
    parser.add_argument('--cluster', default="http://localhost:8000", help='Cluster URL')
    parser.add_argument('--format', choices=['table', 'json', 'csv'], default='table',
                       help='Output format')
    parser.add_argument('--range', type=int,
                       help='Time range in minutes (e.g., 60 for last hour)')
    
    args = parser.parse_args()
    
    try:
        asyncio.run(stats_command_handler(args))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()