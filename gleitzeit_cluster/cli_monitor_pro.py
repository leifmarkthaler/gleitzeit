#!/usr/bin/env python3
"""
Professional Terminal Monitoring Dashboard for Gleitzeit

Enterprise-grade monitoring with advanced visualizations, real-time metrics,
and professional styling.
"""

import asyncio
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import deque
from dataclasses import dataclass
from enum import Enum

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, SpinnerColumn
from rich.syntax import Syntax
from rich.align import Align
from rich.columns import Columns
from rich.tree import Tree
from rich.rule import Rule
from rich.status import Status
from rich.markdown import Markdown
from rich import box
from rich.style import Style

from .core.cluster import GleitzeitCluster
from .core.task import TaskStatus, TaskType


class Theme:
    """Professional color theme"""
    # Primary colors
    PRIMARY = "#2563eb"      # Blue
    SUCCESS = "#059669"      # Green  
    WARNING = "#d97706"      # Orange
    DANGER = "#dc2626"       # Red
    INFO = "#0891b2"         # Cyan
    
    # Neutral colors
    BACKGROUND = "#0f172a"   # Dark blue-gray
    SURFACE = "#1e293b"      # Lighter blue-gray
    BORDER = "#334155"       # Medium blue-gray
    TEXT_PRIMARY = "#f8fafc" # Off-white
    TEXT_SECONDARY = "#cbd5e1" # Light gray
    TEXT_MUTED = "#64748b"   # Medium gray
    
    # Status colors
    ONLINE = "#10b981"       # Emerald
    OFFLINE = "#ef4444"      # Red
    PROCESSING = "#f59e0b"   # Amber
    PENDING = "#8b5cf6"      # Violet


@dataclass
class MetricSnapshot:
    """Snapshot of system metrics at a point in time"""
    timestamp: datetime
    tasks_per_second: float
    cpu_avg: float
    memory_avg: float
    active_nodes: int
    queue_depth: int
    error_rate: float


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning" 
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Alert:
    """System alert"""
    level: AlertLevel
    message: str
    timestamp: datetime
    component: str
    count: int = 1


class ProfessionalGleitzeitMonitor:
    """Enterprise-grade monitoring dashboard"""
    
    def __init__(self, cluster_url: str = "http://localhost:8000", refresh_rate: float = 0.5):
        self.cluster_url = cluster_url
        self.refresh_rate = refresh_rate
        self.console = Console(width=120, height=40)
        
        # System state
        self.nodes: Dict[str, Any] = {}
        self.workflows: Dict[str, Any] = {}
        self.tasks: Dict[str, Any] = {}
        self.connected = False
        self.last_update = None
        
        # Metrics and history (5 minutes at 2Hz = 600 points)
        self.metrics_history: deque[MetricSnapshot] = deque(maxlen=600)
        self.alerts: deque[Alert] = deque(maxlen=100)
        
        # UI state
        self.current_view = "overview"  # overview, nodes, tasks, workflows, alerts
        self.sort_column = "name"
        self.sort_ascending = True
        self.filter_status = "all"
        self.paused = False
        self.show_details = False
        
        # Performance tracking
        self.update_times = deque(maxlen=60)
        self.frame_count = 0
        
        # Connection
        self.cluster: Optional[GleitzeitCluster] = None
        
        # Create layout
        self.layout = self._create_layout()
    
    def _create_layout(self) -> Layout:
        """Create professional dashboard layout"""
        layout = Layout(name="root")
        
        # Main structure: header, body, footer
        layout.split(
            Layout(name="header", size=4),
            Layout(name="body"),
            Layout(name="footer", size=3)
        )
        
        # Body: sidebar + main content
        layout["body"].split_row(
            Layout(name="sidebar", minimum_size=25, ratio=1),
            Layout(name="main", ratio=4)
        )
        
        # Main content: primary panel + secondary panels
        layout["main"].split(
            Layout(name="primary", ratio=3),
            Layout(name="secondary", ratio=2)
        )
        
        # Secondary: split horizontally for metrics and alerts
        layout["secondary"].split_row(
            Layout(name="metrics", ratio=1),
            Layout(name="alerts", ratio=1)
        )
        
        return layout
    
    def _create_header(self) -> Panel:
        """Create professional header with branding and status"""
        # Connection status
        if self.connected and self.last_update:
            time_diff = (datetime.now() - self.last_update).total_seconds()
            if time_diff < 2:
                conn_status = f"[{Theme.ONLINE}]●[/] ONLINE"
            elif time_diff < 10:
                conn_status = f"[{Theme.WARNING}]●[/] SLOW"
            else:
                conn_status = f"[{Theme.OFFLINE}]●[/] TIMEOUT"
        else:
            conn_status = f"[{Theme.OFFLINE}]●[/] OFFLINE"
        
        # Performance metrics
        fps = len(self.update_times) if self.update_times else 0
        avg_update_time = sum(self.update_times) / len(self.update_times) if self.update_times else 0
        
        # Create header content
        title = Text()
        title.append("GLEITZEIT", style=f"bold {Theme.PRIMARY}")
        title.append(" // ", style=Theme.TEXT_MUTED)
        title.append("CLUSTER CONTROL CENTER", style=f"bold {Theme.TEXT_PRIMARY}")
        
        status_info = Text()
        status_info.append(f"Cluster: ", style=Theme.TEXT_SECONDARY)
        status_info.append(f"{self.cluster_url}", style=Theme.INFO)
        status_info.append(f" | Status: {conn_status}")
        status_info.append(f" | View: ", style=Theme.TEXT_SECONDARY)
        status_info.append(f"{self.current_view.upper()}", style=f"bold {Theme.WARNING}")
        status_info.append(f" | FPS: {fps}", style=Theme.TEXT_MUTED)
        
        timestamp = Text()
        timestamp.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"), style=Theme.TEXT_MUTED)
        
        # Combine into header layout
        header_table = Table.grid(expand=True)
        header_table.add_column(justify="left")
        header_table.add_column(justify="center") 
        header_table.add_column(justify="right")
        
        header_table.add_row(title, status_info, timestamp)
        
        return Panel(
            header_table,
            style=f"bold {Theme.TEXT_PRIMARY} on {Theme.SURFACE}",
            border_style=Theme.BORDER,
            box=box.HEAVY
        )
    
    def _create_sidebar(self) -> Panel:
        """Create navigation sidebar"""
        tree = Tree("📊 NAVIGATION", style=f"bold {Theme.PRIMARY}")
        
        # Views
        views = [
            ("overview", "🔍 Overview", "System overview"),
            ("nodes", "🖥️  Nodes", f"{len(self.nodes)} connected"),
            ("workflows", "📋 Workflows", f"{len(self.workflows)} active"),
            ("tasks", "⚙️  Tasks", f"{len(self.tasks)} in queue"),
            ("alerts", "🚨 Alerts", f"{len(self.alerts)} recent")
        ]
        
        for view_id, name, desc in views:
            style = f"bold {Theme.SUCCESS}" if view_id == self.current_view else Theme.TEXT_SECONDARY
            node = tree.add(f"[{style}]{name}[/]")
            node.add(f"[{Theme.TEXT_MUTED}]{desc}[/]")
        
        tree.add("")
        
        # Controls section
        controls = tree.add(f"[bold {Theme.WARNING}]⌨️  CONTROLS[/]")
        controls.add("[dim]1-5[/] Switch views")
        controls.add("[dim]↑↓[/] Navigate items")
        controls.add("[dim]SPACE[/] Pause/Resume")
        controls.add("[dim]F[/] Filter status")
        controls.add("[dim]S[/] Sort column")
        controls.add("[dim]D[/] Show details")
        controls.add("[dim]R[/] Refresh now")
        controls.add("[dim]Q[/] Quit")
        
        tree.add("")
        
        # System health
        health = tree.add(f"[bold {Theme.INFO}]💊 HEALTH[/]")
        
        # Calculate health metrics
        if self.nodes:
            avg_cpu = sum(n.get("cpu_usage", 0) for n in self.nodes.values()) / len(self.nodes)
            avg_mem = sum(n.get("memory_usage", 0) for n in self.nodes.values()) / len(self.nodes)
            
            cpu_color = Theme.SUCCESS if avg_cpu < 70 else Theme.WARNING if avg_cpu < 90 else Theme.DANGER
            mem_color = Theme.SUCCESS if avg_mem < 70 else Theme.WARNING if avg_mem < 90 else Theme.DANGER
            
            health.add(f"[{cpu_color}]CPU: {avg_cpu:.1f}%[/]")
            health.add(f"[{mem_color}]MEM: {avg_mem:.1f}%[/]")
        else:
            health.add(f"[{Theme.TEXT_MUTED}]No data[/]")
        
        # Error rate
        if self.metrics_history:
            recent_errors = [m.error_rate for m in list(self.metrics_history)[-10:]]
            avg_error_rate = sum(recent_errors) / len(recent_errors)
            error_color = Theme.SUCCESS if avg_error_rate < 0.01 else Theme.WARNING if avg_error_rate < 0.05 else Theme.DANGER
            health.add(f"[{error_color}]ERR: {avg_error_rate:.1%}[/]")
        
        return Panel(
            tree,
            title="[bold]CONTROL PANEL[/]",
            border_style=Theme.BORDER,
            box=box.ROUNDED
        )
    
    def _create_overview_panel(self) -> Panel:
        """Create system overview panel"""
        
        # Key metrics cards
        cards = []
        
        # Nodes card
        active_nodes = len([n for n in self.nodes.values() if n.get("status") == "active"])
        total_nodes = len(self.nodes)
        node_health = "🟢" if active_nodes == total_nodes and total_nodes > 0 else "🟡" if active_nodes > 0 else "🔴"
        
        node_card = Panel(
            f"[bold {Theme.PRIMARY}]{active_nodes}[/]\n"
            f"[{Theme.TEXT_SECONDARY}]of {total_nodes} nodes[/]\n"
            f"{node_health} Active",
            title="[bold]Cluster Nodes[/]",
            border_style=Theme.SUCCESS if active_nodes == total_nodes else Theme.WARNING,
            expand=False,
            width=20
        )
        cards.append(node_card)
        
        # Tasks card
        running_tasks = len([t for t in self.tasks.values() if t.get("status") == "processing"])
        total_tasks = len(self.tasks)
        
        task_card = Panel(
            f"[bold {Theme.SUCCESS}]{running_tasks}[/]\n"
            f"[{Theme.TEXT_SECONDARY}]of {total_tasks} tasks[/]\n"
            f"⚡ Processing",
            title="[bold]Active Tasks[/]",
            border_style=Theme.INFO,
            expand=False,
            width=20
        )
        cards.append(task_card)
        
        # Workflows card  
        active_workflows = len([w for w in self.workflows.values() if w.get("status") == "running"])
        total_workflows = len(self.workflows)
        
        workflow_card = Panel(
            f"[bold {Theme.WARNING}]{active_workflows}[/]\n"
            f"[{Theme.TEXT_SECONDARY}]of {total_workflows} workflows[/]\n"
            f"🔄 Running",
            title="[bold]Workflows[/]",
            border_style=Theme.WARNING,
            expand=False,
            width=20
        )
        cards.append(workflow_card)
        
        # Performance card
        if self.metrics_history:
            recent_tps = [m.tasks_per_second for m in list(self.metrics_history)[-10:]]
            avg_tps = sum(recent_tps) / len(recent_tps)
            
            perf_card = Panel(
                f"[bold {Theme.INFO}]{avg_tps:.1f}[/]\n"
                f"[{Theme.TEXT_SECONDARY}]tasks/second[/]\n"
                f"📈 Throughput",
                title="[bold]Performance[/]",
                border_style=Theme.INFO,
                expand=False,
                width=20
            )
            cards.append(perf_card)
        
        # Create cards layout
        cards_layout = Columns(cards, equal=True, expand=True)
        
        # Recent activity
        activity_table = Table(title="Recent Activity", box=box.SIMPLE_HEAVY)
        activity_table.add_column("Time", style=Theme.TEXT_MUTED, width=8)
        activity_table.add_column("Event", style=Theme.TEXT_PRIMARY)
        activity_table.add_column("Component", style=Theme.INFO, width=15)
        activity_table.add_column("Status", width=10)
        
        # Add recent task completions
        recent_tasks = sorted(
            [(k, v) for k, v in self.tasks.items() if v.get("completed_at")],
            key=lambda x: x[1].get("completed_at", ""),
            reverse=True
        )[:8]
        
        for task_id, task in recent_tasks:
            completed_time = task.get("completed_at", "")
            if completed_time:
                time_str = datetime.fromisoformat(completed_time).strftime("%H:%M:%S")
            else:
                time_str = "-"
            
            status = task.get("status", "unknown")
            status_style = {
                "completed": f"[{Theme.SUCCESS}]✓ Done[/]",
                "failed": f"[{Theme.DANGER}]✗ Failed[/]"
            }.get(status, status)
            
            activity_table.add_row(
                time_str,
                task.get("name", task_id[:12]),
                task.get("node", "unknown")[:15],
                status_style
            )
        
        if not recent_tasks:
            activity_table.add_row("-", "No recent activity", "-", "-")
        
        # Combine overview content
        overview_content = Table.grid()
        overview_content.add_row(cards_layout)
        overview_content.add_row("")
        overview_content.add_row(activity_table)
        
        return Panel(
            overview_content,
            title="[bold]System Overview[/]",
            border_style=Theme.PRIMARY,
            box=box.HEAVY
        )
    
    def _create_nodes_panel(self) -> Panel:
        """Create detailed nodes panel"""
        table = Table(title="Cluster Nodes", box=box.HEAVY)
        
        table.add_column("Node", style=f"bold {Theme.PRIMARY}", width=20)
        table.add_column("Type", style=Theme.WARNING, width=10)
        table.add_column("Status", width=12)
        table.add_column("CPU", justify="right", width=8)
        table.add_column("Memory", justify="right", width=8)  
        table.add_column("Tasks", justify="right", width=6)
        table.add_column("Uptime", style=Theme.TEXT_MUTED, width=10)
        table.add_column("Load", justify="right", width=8)
        
        # Sort nodes
        sorted_nodes = sorted(
            self.nodes.items(),
            key=lambda x: x[1].get(self.sort_column, ""),
            reverse=not self.sort_ascending
        )
        
        for node_id, node in sorted_nodes:
            # Node type with icon
            node_name = node.get("name", node_id[:8])
            if "executor" in node_name.lower():
                node_type = "🔧 Exec"
            elif "scheduler" in node_name.lower(): 
                node_type = "📅 Sched"
            else:
                node_type = "❓ Other"
            
            # Status with color
            status = node.get("status", "unknown")
            if status == "active":
                status_display = f"[{Theme.ONLINE}]● ONLINE[/]"
            else:
                status_display = f"[{Theme.OFFLINE}]● OFFLINE[/]"
            
            # Resource usage with color coding
            cpu = node.get("cpu_usage", 0)
            memory = node.get("memory_usage", 0)
            
            cpu_color = Theme.SUCCESS if cpu < 70 else Theme.WARNING if cpu < 90 else Theme.DANGER
            mem_color = Theme.SUCCESS if memory < 70 else Theme.WARNING if memory < 90 else Theme.DANGER
            
            cpu_display = f"[{cpu_color}]{cpu:.1f}%[/]"
            mem_display = f"[{mem_color}]{memory:.1f}%[/]"
            
            # Tasks
            active_tasks = node.get("active_tasks", 0)
            max_tasks = node.get("max_tasks", 0)
            task_display = f"{active_tasks}"
            if max_tasks > 0:
                task_display += f"/{max_tasks}"
            
            # Uptime
            if node.get("started_at"):
                started = datetime.fromisoformat(node["started_at"])
                uptime = datetime.now() - started
                uptime_str = f"{uptime.days}d {uptime.seconds//3600}h"
            else:
                uptime_str = "-"
            
            # Load average
            load = node.get("load_average", 0)
            load_color = Theme.SUCCESS if load < 1 else Theme.WARNING if load < 2 else Theme.DANGER
            load_display = f"[{load_color}]{load:.2f}[/]"
            
            table.add_row(
                node_name,
                node_type,
                status_display,
                cpu_display,
                mem_display,
                task_display,
                uptime_str,
                load_display
            )
        
        if not sorted_nodes:
            table.add_row("No nodes connected", "", "", "", "", "", "", "")
        
        return Panel(
            table,
            border_style=Theme.SUCCESS,
            box=box.HEAVY
        )
    
    def _create_performance_chart(self) -> Panel:
        """Create performance metrics chart"""
        if len(self.metrics_history) < 2:
            return Panel(
                "[dim]Collecting performance data...[/]",
                title="[bold]Performance Metrics[/]",
                border_style=Theme.INFO
            )
        
        # Get recent metrics
        recent_metrics = list(self.metrics_history)[-60:]  # Last 60 seconds
        
        # Create ASCII chart for tasks per second
        chart_lines = ["📈 Tasks/Second (last 60s):", ""]
        
        if recent_metrics:
            values = [m.tasks_per_second for m in recent_metrics]
            max_val = max(values) if values else 1
            
            # Create simple bar chart
            for i in range(0, len(values), 3):  # Sample every 3rd point
                val = values[i]
                if max_val > 0:
                    bar_len = int((val / max_val) * 30)
                    bar = "█" * bar_len + "░" * (30 - bar_len)
                else:
                    bar = "░" * 30
                
                timestamp = recent_metrics[i].timestamp.strftime("%H:%M:%S")
                chart_lines.append(f"[{Theme.TEXT_MUTED}]{timestamp}[/] [{Theme.INFO}]{bar}[/] {val:.1f}")
        
        # Add system metrics
        chart_lines.extend(["", "💻 System Resources:", ""])
        
        if self.nodes:
            avg_cpu = sum(n.get("cpu_usage", 0) for n in self.nodes.values()) / len(self.nodes)
            avg_mem = sum(n.get("memory_usage", 0) for n in self.nodes.values()) / len(self.nodes)
            
            cpu_bar = "█" * int(avg_cpu / 5) + "░" * (20 - int(avg_cpu / 5))
            mem_bar = "█" * int(avg_mem / 5) + "░" * (20 - int(avg_mem / 5))
            
            cpu_color = Theme.SUCCESS if avg_cpu < 70 else Theme.WARNING if avg_cpu < 90 else Theme.DANGER
            mem_color = Theme.SUCCESS if avg_mem < 70 else Theme.WARNING if avg_mem < 90 else Theme.DANGER
            
            chart_lines.append(f"CPU  [{cpu_color}]{cpu_bar}[/] {avg_cpu:.1f}%")
            chart_lines.append(f"MEM  [{mem_color}]{mem_bar}[/] {avg_mem:.1f}%")
        
        chart_text = "\n".join(chart_lines)
        
        return Panel(
            chart_text,
            title="[bold]Performance Metrics[/]",
            border_style=Theme.INFO,
            box=box.ROUNDED
        )
    
    def _create_alerts_panel(self) -> Panel:
        """Create alerts and notifications panel"""
        table = Table(title="System Alerts", box=box.SIMPLE)
        table.add_column("Level", width=8)
        table.add_column("Time", style=Theme.TEXT_MUTED, width=8)
        table.add_column("Component", style=Theme.INFO, width=12)
        table.add_column("Message", style=Theme.TEXT_PRIMARY)
        table.add_column("#", justify="right", width=3)
        
        # Show recent alerts
        recent_alerts = sorted(self.alerts, key=lambda x: x.timestamp, reverse=True)[:10]
        
        for alert in recent_alerts:
            level_styles = {
                AlertLevel.INFO: f"[{Theme.INFO}]ℹ INFO[/]",
                AlertLevel.WARNING: f"[{Theme.WARNING}]⚠ WARN[/]",
                AlertLevel.ERROR: f"[{Theme.DANGER}]✗ ERROR[/]",
                AlertLevel.CRITICAL: f"[{Theme.DANGER} bold]🔥 CRIT[/]"
            }
            
            level_display = level_styles.get(alert.level, str(alert.level.value))
            time_str = alert.timestamp.strftime("%H:%M:%S")
            
            table.add_row(
                level_display,
                time_str,
                alert.component,
                alert.message,
                str(alert.count) if alert.count > 1 else ""
            )
        
        if not recent_alerts:
            table.add_row(
                f"[{Theme.SUCCESS}]✓ OK[/]",
                "Now",
                "System",
                "No alerts - system operating normally",
                ""
            )
        
        return Panel(
            table,
            border_style=Theme.WARNING,
            box=box.ROUNDED
        )
    
    def _create_footer(self) -> Panel:
        """Create professional footer with status and controls"""
        
        # Performance info
        perf_info = Text()
        if self.update_times:
            avg_update = sum(self.update_times) / len(self.update_times) * 1000
            fps = len(self.update_times)
            perf_info.append(f"Update: {avg_update:.1f}ms", style=Theme.TEXT_MUTED)
            perf_info.append(" | ", style=Theme.TEXT_MUTED)
            perf_info.append(f"FPS: {fps}", style=Theme.TEXT_MUTED)
        
        # Status info
        status_info = Text()
        if self.paused:
            status_info.append("⏸️  PAUSED", style=f"bold {Theme.WARNING}")
        else:
            status_info.append("▶️  LIVE", style=f"bold {Theme.SUCCESS}")
        
        status_info.append(f" | Refresh: {self.refresh_rate:.1f}s", style=Theme.TEXT_MUTED)
        status_info.append(f" | Filter: {self.filter_status}", style=Theme.TEXT_MUTED)
        
        # Quick help
        help_info = Text()
        help_info.append("Quick Actions: ", style=Theme.TEXT_SECONDARY)
        help_info.append("[1-5]", style=f"bold {Theme.PRIMARY}")
        help_info.append(" Views ", style=Theme.TEXT_MUTED)
        help_info.append("[SPACE]", style=f"bold {Theme.PRIMARY}")
        help_info.append(" Pause ", style=Theme.TEXT_MUTED)
        help_info.append("[Q]", style=f"bold {Theme.DANGER}")
        help_info.append(" Quit", style=Theme.TEXT_MUTED)
        
        # Create footer table
        footer_table = Table.grid(expand=True)
        footer_table.add_column(justify="left", ratio=1)
        footer_table.add_column(justify="center", ratio=2)
        footer_table.add_column(justify="right", ratio=1)
        
        footer_table.add_row(perf_info, help_info, status_info)
        
        return Panel(
            footer_table,
            style=f"bold {Theme.TEXT_PRIMARY} on {Theme.BACKGROUND}",
            border_style=Theme.BORDER,
            box=box.HEAVY
        )
    
    async def connect(self):
        """Connect to cluster with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.cluster = GleitzeitCluster(
                    enable_redis=False,
                    enable_real_execution=False
                )
                await self.cluster.start()
                self.connected = True
                self._add_alert(AlertLevel.INFO, "Connected to cluster", "monitor")
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    self._add_alert(AlertLevel.ERROR, f"Connection failed: {e}", "monitor")
                    self.connected = False
                else:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
    
    def _add_alert(self, level: AlertLevel, message: str, component: str):
        """Add system alert"""
        # Check if similar alert exists
        for alert in self.alerts:
            if alert.message == message and alert.component == component:
                alert.count += 1
                alert.timestamp = datetime.now()
                return
        
        # Add new alert
        self.alerts.append(Alert(
            level=level,
            message=message,
            component=component,
            timestamp=datetime.now()
        ))
    
    async def fetch_data(self):
        """Fetch and update system data"""
        if not self.connected or not self.cluster:
            return
        
        start_time = datetime.now()
        
        try:
            # Fetch all data concurrently
            nodes_task = self.cluster.list_nodes()
            workflows_task = self.cluster.list_workflows()
            
            nodes, workflows = await asyncio.gather(nodes_task, workflows_task)
            
            # Update data
            self.nodes = {n["id"]: n for n in nodes}
            self.workflows = {w["id"]: w for w in workflows}
            
            # Extract tasks from workflows
            all_tasks = {}
            for workflow in workflows:
                for task in workflow.get("tasks", []):
                    all_tasks[task["id"]] = task
            self.tasks = all_tasks
            
            # Update metrics
            self._update_metrics()
            self.last_update = datetime.now()
            
            # Track performance
            update_time = (datetime.now() - start_time).total_seconds()
            self.update_times.append(update_time)
            
        except Exception as e:
            self._add_alert(AlertLevel.ERROR, f"Data fetch failed: {e}", "monitor")
    
    def _update_metrics(self):
        """Update performance metrics"""
        current_time = datetime.now()
        
        # Calculate tasks per second
        if self.metrics_history:
            last_metric = self.metrics_history[-1]
            time_diff = (current_time - last_metric.timestamp).total_seconds()
            if time_diff > 0:
                completed_now = len([t for t in self.tasks.values() if t.get("status") == "completed"])
                completed_last = sum(1 for _ in range(len(self.tasks)))  # Simplified
                tasks_per_second = max(0, (completed_now - completed_last) / time_diff)
            else:
                tasks_per_second = 0
        else:
            tasks_per_second = 0
        
        # Calculate averages
        cpu_avg = sum(n.get("cpu_usage", 0) for n in self.nodes.values()) / len(self.nodes) if self.nodes else 0
        memory_avg = sum(n.get("memory_usage", 0) for n in self.nodes.values()) / len(self.nodes) if self.nodes else 0
        
        # Error rate
        failed_tasks = len([t for t in self.tasks.values() if t.get("status") == "failed"])
        total_tasks = len(self.tasks)
        error_rate = failed_tasks / total_tasks if total_tasks > 0 else 0
        
        # Create metric snapshot
        metric = MetricSnapshot(
            timestamp=current_time,
            tasks_per_second=tasks_per_second,
            cpu_avg=cpu_avg,
            memory_avg=memory_avg,
            active_nodes=len([n for n in self.nodes.values() if n.get("status") == "active"]),
            queue_depth=len([t for t in self.tasks.values() if t.get("status") in ["pending", "queued"]]),
            error_rate=error_rate
        )
        
        self.metrics_history.append(metric)
        
        # Check thresholds and generate alerts
        if cpu_avg > 90:
            self._add_alert(AlertLevel.CRITICAL, f"High CPU usage: {cpu_avg:.1f}%", "system")
        elif cpu_avg > 80:
            self._add_alert(AlertLevel.WARNING, f"Elevated CPU usage: {cpu_avg:.1f}%", "system")
        
        if memory_avg > 90:
            self._add_alert(AlertLevel.CRITICAL, f"High memory usage: {memory_avg:.1f}%", "system")
        
        if error_rate > 0.1:
            self._add_alert(AlertLevel.ERROR, f"High error rate: {error_rate:.1%}", "tasks")
    
    def update_display(self):
        """Update all display panels"""
        # Header
        self.layout["header"].update(self._create_header())
        
        # Sidebar
        self.layout["sidebar"].update(self._create_sidebar())
        
        # Main content based on current view
        if self.current_view == "overview":
            self.layout["primary"].update(self._create_overview_panel())
        elif self.current_view == "nodes":
            self.layout["primary"].update(self._create_nodes_panel())
        elif self.current_view == "workflows":
            self.layout["primary"].update(self._create_workflows_panel())
        elif self.current_view == "tasks":
            self.layout["primary"].update(self._create_tasks_panel())
        elif self.current_view == "alerts":
            self.layout["primary"].update(self._create_alerts_panel())
        
        # Secondary panels
        self.layout["metrics"].update(self._create_performance_chart())
        self.layout["alerts"].update(self._create_alerts_panel())
        
        # Footer
        self.layout["footer"].update(self._create_footer())
        
        return self.layout
    
    def _create_workflows_panel(self) -> Panel:
        """Create detailed workflows panel (placeholder)"""
        return Panel("Workflows panel - TODO", title="Workflows")
    
    def _create_tasks_panel(self) -> Panel:
        """Create detailed tasks panel (placeholder)"""  
        return Panel("Tasks panel - TODO", title="Tasks")
    
    async def run(self):
        """Run the professional monitoring dashboard"""
        await self.connect()
        
        with Live(
            self.update_display(),
            console=self.console,
            refresh_per_second=2,
            screen=True
        ) as live:
            try:
                while True:
                    if not self.paused:
                        await self.fetch_data()
                        live.update(self.update_display())
                    
                    await asyncio.sleep(self.refresh_rate)
                    self.frame_count += 1
                    
            except KeyboardInterrupt:
                self._add_alert(AlertLevel.INFO, "Monitor stopped by user", "monitor")
            finally:
                if self.cluster:
                    await self.cluster.stop()


async def monitor_pro_command_handler(args):
    """Handle professional monitor command"""
    
    monitor = ProfessionalGleitzeitMonitor(
        cluster_url=args.cluster,
        refresh_rate=args.refresh
    )
    
    try:
        await monitor.run()
    except KeyboardInterrupt:
        print("\n✨ Professional monitoring stopped")
    except Exception as e:
        print(f"❌ Monitor failed: {e}")
        raise


def demo_professional():
    """Demo the professional interface"""
    import random
    
    monitor = ProfessionalGleitzeitMonitor()
    
    # Add demo data
    monitor.nodes = {
        f"node-{i}": {
            "id": f"node-{i}",
            "name": f"executor-{i}",
            "status": "active",
            "cpu_usage": random.uniform(20, 85),
            "memory_usage": random.uniform(30, 75),
            "active_tasks": random.randint(0, 8),
            "max_tasks": 8,
            "load_average": random.uniform(0.5, 2.5),
            "started_at": (datetime.now() - timedelta(hours=random.randint(1, 24))).isoformat()
        }
        for i in range(1, 6)
    }
    
    # Add demo alerts
    monitor._add_alert(AlertLevel.WARNING, "High CPU usage detected", "node-2")
    monitor._add_alert(AlertLevel.INFO, "Task completed successfully", "executor-1") 
    monitor._add_alert(AlertLevel.ERROR, "Connection timeout", "cluster")
    
    monitor.connected = True
    monitor.last_update = datetime.now()
    
    # Display demo
    console = Console()
    console.print(monitor.update_display())


if __name__ == "__main__":
    demo_professional()