#!/usr/bin/env python3
"""
Simple status command for Gleitzeit

Provides a quick snapshot of cluster status without full dashboard.
"""

import asyncio
from datetime import datetime
from typing import Dict, Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from .core.cluster import GleitzeitCluster


async def status_command_handler(args):
    """Handle status command - simpler alternative to monitor"""
    
    console = Console()
    
    # Connect to cluster
    try:
        cluster = GleitzeitCluster(
            enable_redis=False,
            enable_real_execution=False
        )
        await cluster.start()
        
        # Fetch data
        nodes = await cluster.list_nodes()
        workflows = await cluster.list_workflows()
        
        # Display header
        console.print()
        console.print(Panel.fit(
            f"[bold cyan]Gleitzeit Cluster Status[/bold cyan]\n"
            f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
            border_style="blue"
        ))
        
        # Nodes table
        if nodes:
            console.print("\n[bold]🖥️  Connected Nodes[/bold]")
            nodes_table = Table(box=box.SIMPLE)
            nodes_table.add_column("Name", style="cyan")
            nodes_table.add_column("Type", style="yellow")
            nodes_table.add_column("Status", style="green")
            nodes_table.add_column("Capabilities")
            
            for node in nodes:
                node_type = "Unknown"
                if "executor" in node.get("name", "").lower():
                    node_type = "Executor"
                    caps = node.get("capabilities", {})
                    cap_str = f"Tasks: {caps.get('max_concurrent_tasks', 0)}"
                elif "scheduler" in node.get("name", "").lower():
                    node_type = "Scheduler"
                    cap_str = "Scheduling tasks"
                else:
                    cap_str = "-"
                
                status = "🟢 Active" if node.get("status") == "active" else "🔴 Inactive"
                
                nodes_table.add_row(
                    node.get("name", node["id"][:8]),
                    node_type,
                    status,
                    cap_str
                )
            
            console.print(nodes_table)
        else:
            console.print("\n[yellow]No nodes connected[/yellow]")
        
        # Workflows summary
        if workflows:
            console.print("\n[bold]📋 Workflows[/bold]")
            
            # Count by status
            status_counts = {}
            for wf in workflows:
                status = wf.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
            
            wf_table = Table(box=box.SIMPLE)
            wf_table.add_column("Status", style="cyan")
            wf_table.add_column("Count", justify="right")
            
            for status, count in sorted(status_counts.items()):
                icon = {
                    "completed": "✅",
                    "running": "🔄",
                    "failed": "❌",
                    "pending": "⏳"
                }.get(status, "❓")
                
                wf_table.add_row(f"{icon} {status.capitalize()}", str(count))
            
            console.print(wf_table)
            
            # Recent workflows
            console.print("\n[bold]Recent Workflows:[/bold]")
            recent_table = Table(box=box.SIMPLE)
            recent_table.add_column("Name", style="cyan")
            recent_table.add_column("Status")
            recent_table.add_column("Tasks")
            recent_table.add_column("Created", style="dim")
            
            # Sort by creation time
            sorted_wf = sorted(
                workflows,
                key=lambda x: x.get("created_at", ""),
                reverse=True
            )[:5]
            
            for wf in sorted_wf:
                status = wf.get("status", "unknown")
                status_display = {
                    "completed": "[green]✅ Completed[/green]",
                    "running": "[yellow]🔄 Running[/yellow]",
                    "failed": "[red]❌ Failed[/red]",
                    "pending": "[dim]⏳ Pending[/dim]"
                }.get(status, status)
                
                tasks = f"{wf.get('completed_tasks', 0)}/{wf.get('total_tasks', 0)}"
                
                created = wf.get("created_at", "")
                if created:
                    created_dt = datetime.fromisoformat(created)
                    created_str = created_dt.strftime("%H:%M:%S")
                else:
                    created_str = "-"
                
                recent_table.add_row(
                    wf.get("name", wf["id"][:8])[:30],
                    status_display,
                    tasks,
                    created_str
                )
            
            console.print(recent_table)
        else:
            console.print("\n[yellow]No workflows found[/yellow]")
        
        # Quick stats
        total_tasks = sum(wf.get("total_tasks", 0) for wf in workflows)
        completed_tasks = sum(wf.get("completed_tasks", 0) for wf in workflows)
        
        console.print(f"\n[bold]📊 Statistics:[/bold]")
        console.print(f"  Total Workflows: {len(workflows)}")
        console.print(f"  Total Tasks: {total_tasks}")
        console.print(f"  Completed Tasks: {completed_tasks}")
        
        if args.watch:
            console.print(f"\n[dim]Refreshing every {args.interval} seconds... (Ctrl+C to stop)[/dim]")
            await asyncio.sleep(args.interval)
            console.clear()
            # Recursive call for continuous monitoring
            await status_command_handler(args)
        
        await cluster.stop()
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Status check stopped[/yellow]")
    except Exception as e:
        console.print(f"[red]❌ Failed to get status: {e}[/red]")