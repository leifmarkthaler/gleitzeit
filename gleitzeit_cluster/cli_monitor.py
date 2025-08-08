#!/usr/bin/env python3
"""
Terminal-based monitoring dashboard for Gleitzeit

Provides real-time monitoring of nodes, tasks, and workflows.
"""

import asyncio
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.syntax import Syntax
from rich.align import Align
from rich import box

from .core.cluster import GleitzeitCluster
from .core.task import TaskStatus, TaskType


class GleitzeitMonitor:
    """Terminal-based monitoring dashboard"""
    
    def __init__(self, cluster_url: str = "http://localhost:8000", refresh_rate: float = 1.0):
        self.cluster_url = cluster_url
        self.refresh_rate = refresh_rate
        self.console = Console()
        
        # Data storage
        self.nodes: Dict[str, Any] = {}
        self.workflows: Dict[str, Any] = {}
        self.tasks: Dict[str, Any] = {}
        self.metrics = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_pending": 0,
            "avg_execution_time": 0,
            "total_workflows": 0
        }
        
        # History for graphs
        self.task_history = deque(maxlen=60)  # Last 60 data points
        self.cpu_history = deque(maxlen=60)
        self.memory_history = deque(maxlen=60)
        
        # Connection
        self.cluster: Optional[GleitzeitCluster] = None
        self.connected = False
        
        # Layout
        self.layout = self._create_layout()
    
    def _create_layout(self) -> Layout:
        """Create the dashboard layout"""
        layout = Layout(name="root")
        
        # Main layout structure
        layout.split(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3)
        )
        
        # Split body into main sections
        layout["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="center", ratio=2),
            Layout(name="right", ratio=1)
        )
        
        # Left panel: Nodes
        layout["left"].split(
            Layout(name="nodes", ratio=2),
            Layout(name="metrics", ratio=1)
        )
        
        # Center panel: Tasks/Workflows
        layout["center"].split(
            Layout(name="workflows", ratio=1),
            Layout(name="tasks", ratio=2)
        )
        
        # Right panel: Performance
        layout["right"].split(
            Layout(name="performance", ratio=1),
            Layout(name="logs", ratio=1)
        )
        
        return layout
    
    def _create_header(self) -> Panel:
        """Create header panel"""
        status = "🟢 Connected" if self.connected else "🔴 Disconnected"
        
        header_text = Text()
        header_text.append("Gleitzeit Monitor", style="bold cyan")
        header_text.append(" | ", style="dim")
        header_text.append(f"Cluster: {self.cluster_url}", style="yellow")
        header_text.append(" | ", style="dim")
        header_text.append(status)
        header_text.append(" | ", style="dim")
        header_text.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), style="dim")
        
        return Panel(
            Align.center(header_text),
            style="bold white on blue",
            box=box.DOUBLE
        )
    
    def _create_nodes_panel(self) -> Panel:
        """Create nodes status panel"""
        table = Table(title="🖥️ Nodes", box=box.ROUNDED)
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Status", style="green")
        table.add_column("Tasks", justify="right")
        table.add_column("CPU", justify="right")
        table.add_column("Mem", justify="right")
        
        for node_id, node in self.nodes.items():
            status_icon = "🟢" if node.get("status") == "active" else "🔴"
            
            # Determine node type
            node_type = "Unknown"
            if "executor" in node.get("name", "").lower():
                node_type = "Executor"
            elif "scheduler" in node.get("name", "").lower():
                node_type = "Scheduler"
            elif "cluster" in node.get("name", "").lower():
                node_type = "Cluster"
            
            cpu = f"{node.get('cpu_usage', 0):.1f}%"
            mem = f"{node.get('memory_usage', 0):.1f}%"
            tasks = str(node.get('active_tasks', 0))
            
            table.add_row(
                node.get("name", node_id[:8]),
                node_type,
                status_icon,
                tasks,
                cpu,
                mem
            )
        
        if not self.nodes:
            table.add_row("No nodes connected", "", "", "", "", "")
        
        return Panel(table, border_style="green")
    
    def _create_workflows_panel(self) -> Panel:
        """Create workflows panel"""
        table = Table(title="📋 Active Workflows", box=box.SIMPLE)
        table.add_column("ID", style="dim", width=8)
        table.add_column("Name", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("Progress", style="green")
        table.add_column("Time", style="dim")
        
        # Sort workflows by created time (most recent first)
        sorted_workflows = sorted(
            self.workflows.items(),
            key=lambda x: x[1].get("created_at", ""),
            reverse=True
        )[:10]  # Show last 10
        
        for wf_id, workflow in sorted_workflows:
            status = workflow.get("status", "unknown")
            
            # Status icon and color
            if status == "completed":
                status_display = Text("✅ Done", style="green")
            elif status == "failed":
                status_display = Text("❌ Failed", style="red")
            elif status == "running":
                status_display = Text("🔄 Running", style="yellow")
            else:
                status_display = Text("⏳ Pending", style="dim")
            
            # Progress
            total_tasks = workflow.get("total_tasks", 0)
            completed = workflow.get("completed_tasks", 0)
            progress = f"{completed}/{total_tasks}"
            
            # Execution time
            if workflow.get("started_at"):
                start = datetime.fromisoformat(workflow["started_at"])
                if workflow.get("completed_at"):
                    end = datetime.fromisoformat(workflow["completed_at"])
                    duration = (end - start).total_seconds()
                else:
                    duration = (datetime.now() - start).total_seconds()
                time_str = f"{duration:.1f}s"
            else:
                time_str = "-"
            
            table.add_row(
                wf_id[:8],
                workflow.get("name", "Unknown")[:20],
                status_display,
                progress,
                time_str
            )
        
        if not sorted_workflows:
            table.add_row("", "No active workflows", "", "", "")
        
        return Panel(table, border_style="blue")
    
    def _create_tasks_panel(self) -> Panel:
        """Create tasks panel"""
        table = Table(title="⚙️ Task Queue", box=box.SIMPLE)
        table.add_column("Task", style="cyan", width=20)
        table.add_column("Type", style="yellow", width=10)
        table.add_column("Status", width=12)
        table.add_column("Node", style="dim", width=12)
        table.add_column("Duration", style="dim", width=8)
        
        # Sort tasks by status (running first, then pending, then completed)
        status_order = {"processing": 0, "queued": 1, "pending": 2, "completed": 3, "failed": 4}
        sorted_tasks = sorted(
            self.tasks.items(),
            key=lambda x: (status_order.get(x[1].get("status", ""), 5), x[1].get("created_at", ""))
        )[:20]  # Show last 20
        
        for task_id, task in sorted_tasks:
            status = task.get("status", "unknown")
            
            # Status display with icons
            status_displays = {
                "processing": Text("🔄 Running", style="yellow bold"),
                "queued": Text("📋 Queued", style="cyan"),
                "pending": Text("⏳ Pending", style="dim"),
                "completed": Text("✅ Done", style="green"),
                "failed": Text("❌ Failed", style="red")
            }
            status_display = status_displays.get(status, Text(status))
            
            # Task type icon
            task_type = task.get("task_type", "unknown")
            type_icons = {
                "text": "💬",
                "vision": "👁️",
                "function": "🔧",
                "http": "🌐",
                "file": "📁"
            }
            type_display = f"{type_icons.get(task_type, '❓')} {task_type}"
            
            # Duration
            if task.get("started_at"):
                start = datetime.fromisoformat(task["started_at"])
                if task.get("completed_at"):
                    end = datetime.fromisoformat(task["completed_at"])
                    duration = (end - start).total_seconds()
                else:
                    duration = (datetime.now() - start).total_seconds()
                duration_str = f"{duration:.1f}s"
            else:
                duration_str = "-"
            
            table.add_row(
                task.get("name", task_id[:8])[:20],
                type_display,
                status_display,
                task.get("node", "-")[:12],
                duration_str
            )
        
        if not sorted_tasks:
            table.add_row("No tasks in queue", "", "", "", "")
        
        return Panel(table, border_style="yellow")
    
    def _create_metrics_panel(self) -> Panel:
        """Create metrics summary panel"""
        metrics_text = Text()
        
        metrics_text.append("📊 Metrics\n\n", style="bold cyan")
        
        metrics_text.append("Tasks:\n", style="bold")
        metrics_text.append(f"  ✅ Completed: {self.metrics['tasks_completed']}\n", style="green")
        metrics_text.append(f"  ❌ Failed: {self.metrics['tasks_failed']}\n", style="red")
        metrics_text.append(f"  ⏳ Pending: {self.metrics['tasks_pending']}\n", style="yellow")
        
        metrics_text.append("\nPerformance:\n", style="bold")
        metrics_text.append(f"  ⚡ Avg Time: {self.metrics['avg_execution_time']:.2f}s\n")
        metrics_text.append(f"  📋 Workflows: {self.metrics['total_workflows']}\n")
        
        # Calculate throughput
        if len(self.task_history) > 0:
            throughput = sum(self.task_history) / len(self.task_history) * 60
            metrics_text.append(f"  📈 Throughput: {throughput:.1f}/min\n")
        
        return Panel(metrics_text, border_style="cyan")
    
    def _create_performance_panel(self) -> Panel:
        """Create performance graphs panel"""
        perf_text = Text()
        perf_text.append("📈 Performance\n\n", style="bold magenta")
        
        # Simple ASCII graph for task completion rate
        if len(self.task_history) > 10:
            perf_text.append("Task Rate (last 60s):\n", style="bold")
            
            # Create simple bar chart
            max_val = max(self.task_history) if self.task_history else 1
            for i in range(0, len(self.task_history), 3):  # Sample every 3rd point
                val = self.task_history[i]
                bar_len = int((val / max_val) * 20) if max_val > 0 else 0
                bar = "█" * bar_len + "░" * (20 - bar_len)
                perf_text.append(f"{bar} {val}\n", style="cyan")
        
        # CPU/Memory usage
        if self.nodes:
            avg_cpu = sum(n.get("cpu_usage", 0) for n in self.nodes.values()) / len(self.nodes)
            avg_mem = sum(n.get("memory_usage", 0) for n in self.nodes.values()) / len(self.nodes)
            
            perf_text.append(f"\n💻 Avg CPU: {avg_cpu:.1f}%\n")
            perf_text.append(f"🧠 Avg Memory: {avg_mem:.1f}%\n")
        
        return Panel(perf_text, border_style="magenta")
    
    def _create_logs_panel(self) -> Panel:
        """Create recent logs panel"""
        logs_text = Text()
        logs_text.append("📜 Recent Activity\n\n", style="bold yellow")
        
        # Show recent task completions
        recent_tasks = sorted(
            [(k, v) for k, v in self.tasks.items() if v.get("status") in ["completed", "failed"]],
            key=lambda x: x[1].get("completed_at", ""),
            reverse=True
        )[:5]
        
        for task_id, task in recent_tasks:
            status_icon = "✅" if task["status"] == "completed" else "❌"
            name = task.get("name", task_id[:8])
            logs_text.append(f"{status_icon} {name}\n", style="dim")
        
        if not recent_tasks:
            logs_text.append("No recent activity", style="dim")
        
        return Panel(logs_text, border_style="yellow")
    
    def _create_footer(self) -> Panel:
        """Create footer with controls"""
        footer_text = Text()
        footer_text.append("Controls: ", style="bold")
        footer_text.append("[Q]uit ", style="red")
        footer_text.append("[R]efresh ", style="yellow")
        footer_text.append("[P]ause ", style="cyan")
        footer_text.append("[W]orkflows ", style="green")
        footer_text.append("[T]asks ", style="blue")
        footer_text.append("[N]odes ", style="magenta")
        footer_text.append(" | Press key for action", style="dim")
        
        return Panel(
            Align.center(footer_text),
            style="bold white on black",
            box=box.DOUBLE
        )
    
    async def connect(self):
        """Connect to cluster"""
        try:
            self.cluster = GleitzeitCluster(
                enable_redis=False,
                enable_real_execution=False
            )
            await self.cluster.start()
            self.connected = True
        except Exception as e:
            self.console.print(f"[red]Failed to connect: {e}[/red]")
            self.connected = False
    
    async def fetch_data(self):
        """Fetch latest data from cluster"""
        if not self.connected or not self.cluster:
            return
        
        try:
            # Fetch nodes
            nodes = await self.cluster.list_nodes()
            self.nodes = {n["id"]: n for n in nodes}
            
            # Fetch workflows
            workflows = await self.cluster.list_workflows()
            self.workflows = {w["id"]: w for w in workflows}
            
            # Fetch tasks (from workflows)
            all_tasks = {}
            for wf_id, workflow in self.workflows.items():
                for task in workflow.get("tasks", []):
                    all_tasks[task["id"]] = task
            self.tasks = all_tasks
            
            # Update metrics
            self._update_metrics()
            
        except Exception as e:
            # Silently handle errors to keep dashboard running
            pass
    
    def _update_metrics(self):
        """Update calculated metrics"""
        # Count task statuses
        completed = sum(1 for t in self.tasks.values() if t.get("status") == "completed")
        failed = sum(1 for t in self.tasks.values() if t.get("status") == "failed")
        pending = sum(1 for t in self.tasks.values() if t.get("status") in ["pending", "queued"])
        
        # Track changes for history
        if len(self.task_history) == 0:
            self.task_history.append(completed)
        else:
            last_completed = self.metrics.get("tasks_completed", 0)
            self.task_history.append(completed - last_completed)
        
        self.metrics["tasks_completed"] = completed
        self.metrics["tasks_failed"] = failed
        self.metrics["tasks_pending"] = pending
        self.metrics["total_workflows"] = len(self.workflows)
        
        # Calculate average execution time
        times = []
        for task in self.tasks.values():
            if task.get("started_at") and task.get("completed_at"):
                start = datetime.fromisoformat(task["started_at"])
                end = datetime.fromisoformat(task["completed_at"])
                times.append((end - start).total_seconds())
        
        if times:
            self.metrics["avg_execution_time"] = sum(times) / len(times)
    
    def update_display(self):
        """Update all panels"""
        self.layout["header"].update(self._create_header())
        self.layout["nodes"].update(self._create_nodes_panel())
        self.layout["metrics"].update(self._create_metrics_panel())
        self.layout["workflows"].update(self._create_workflows_panel())
        self.layout["tasks"].update(self._create_tasks_panel())
        self.layout["performance"].update(self._create_performance_panel())
        self.layout["logs"].update(self._create_logs_panel())
        self.layout["footer"].update(self._create_footer())
        
        return self.layout
    
    async def run(self):
        """Run the monitoring dashboard"""
        await self.connect()
        
        with Live(
            self.update_display(),
            console=self.console,
            refresh_per_second=1,
            screen=True
        ) as live:
            try:
                while True:
                    # Fetch latest data
                    await self.fetch_data()
                    
                    # Update display
                    live.update(self.update_display())
                    
                    # Wait before next update
                    await asyncio.sleep(self.refresh_rate)
                    
            except KeyboardInterrupt:
                pass
            finally:
                if self.cluster:
                    await self.cluster.stop()


async def monitor_command_handler(args):
    """Handle monitor command from CLI"""
    
    monitor = GleitzeitMonitor(
        cluster_url=args.cluster,
        refresh_rate=args.refresh
    )
    
    try:
        await monitor.run()
    except KeyboardInterrupt:
        print("\n👋 Monitoring stopped")
    except Exception as e:
        print(f"❌ Monitor failed: {e}")


def monitor_demo():
    """Run monitor with demo data for testing"""
    import random
    
    monitor = GleitzeitMonitor()
    
    # Add demo nodes
    monitor.nodes = {
        "node1": {
            "id": "node1",
            "name": "executor-1",
            "status": "active",
            "cpu_usage": random.uniform(20, 80),
            "memory_usage": random.uniform(30, 70),
            "active_tasks": random.randint(0, 5)
        },
        "node2": {
            "id": "node2",
            "name": "executor-2",
            "status": "active",
            "cpu_usage": random.uniform(20, 80),
            "memory_usage": random.uniform(30, 70),
            "active_tasks": random.randint(0, 5)
        },
        "node3": {
            "id": "node3",
            "name": "scheduler-1",
            "status": "active",
            "cpu_usage": random.uniform(5, 30),
            "memory_usage": random.uniform(20, 40),
            "active_tasks": 0
        }
    }
    
    # Add demo workflows
    monitor.workflows = {
        "wf1": {
            "id": "wf1",
            "name": "Data Processing",
            "status": "running",
            "total_tasks": 5,
            "completed_tasks": 3,
            "started_at": datetime.now().isoformat(),
            "created_at": datetime.now().isoformat()
        },
        "wf2": {
            "id": "wf2",
            "name": "ML Training",
            "status": "completed",
            "total_tasks": 10,
            "completed_tasks": 10,
            "started_at": (datetime.now() - timedelta(minutes=5)).isoformat(),
            "completed_at": datetime.now().isoformat(),
            "created_at": (datetime.now() - timedelta(minutes=6)).isoformat()
        }
    }
    
    # Add demo tasks
    monitor.tasks = {
        "task1": {
            "id": "task1",
            "name": "Generate Data",
            "task_type": "function",
            "status": "completed",
            "node": "executor-1",
            "started_at": (datetime.now() - timedelta(seconds=30)).isoformat(),
            "completed_at": (datetime.now() - timedelta(seconds=25)).isoformat()
        },
        "task2": {
            "id": "task2",
            "name": "Analyze Text",
            "task_type": "text",
            "status": "processing",
            "node": "executor-2",
            "started_at": (datetime.now() - timedelta(seconds=5)).isoformat()
        },
        "task3": {
            "id": "task3",
            "name": "Process Image",
            "task_type": "vision",
            "status": "queued"
        }
    }
    
    # Add demo history
    monitor.task_history.extend([random.randint(0, 10) for _ in range(30)])
    
    monitor.connected = True
    monitor._update_metrics()
    
    # Display once
    console = Console()
    console.print(monitor.update_display())


if __name__ == "__main__":
    # Run demo for testing
    monitor_demo()