#!/usr/bin/env python3
"""
Gleitzeit CLI - Modern workflow orchestration interface

A clean, intuitive command-line interface for managing Gleitzeit components,
workflows, and distributed execution.
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import yaml

# Rich for beautiful terminal output
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.syntax import Syntax
    from rich.live import Live
    from rich.layout import Layout
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("⚠️  Install 'rich' for better terminal output: pip install rich")

# Import components
try:
    from gleitzeit_v5.hub.central_hub import CentralHub
    from gleitzeit_v5.base.config import ComponentConfig
    from gleitzeit_v5.components import (
        QueueManagerClient,
        DependencyResolverClient,
        ExecutionEngineClient
    )
except ImportError:
    # Try relative imports when running as script
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    from hub.central_hub import CentralHub
    from base.config import ComponentConfig
    from components import (
        QueueManagerClient,
        DependencyResolverClient,
        ExecutionEngineClient
    )

# Initialize console for rich output
console = Console() if RICH_AVAILABLE else None


class GleitzeitCLI:
    """Main CLI handler for Gleitzeit"""
    
    def __init__(self):
        self.hub = None
        self.components = {}
        self.running = False
        self.console = console
        self.hub_auto_started = False
    
    async def check_hub_running(self, hub_url: str = "http://localhost:8001") -> bool:
        """Check if hub is already running"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{hub_url}/stats", timeout=2.0)
                return response.status_code == 200
        except Exception:
            return False
    
    async def ensure_hub_running(self, host: str = "127.0.0.1", port: int = 8001, 
                                 log_level: str = "INFO") -> bool:
        """Ensure hub is running, start it if needed"""
        hub_url = f"http://{host}:{port}"
        
        if await self.check_hub_running(hub_url):
            return True
        
        self._print_info(f"Hub not detected, starting automatically on {host}:{port}")
        success = await self.start_hub(host, port, log_level, background=True)
        if success:
            self.hub_auto_started = True
            # Wait a bit more for hub to be ready
            await asyncio.sleep(3)
            return await self.check_hub_running(hub_url)
        return False
    
    async def start_hub(self, host: str = "127.0.0.1", port: int = 8001, 
                        log_level: str = "INFO", background: bool = False):
        """Start the central hub"""
        if self.hub and self.running:
            self._print_error("Hub is already running")
            return False
        
        config = ComponentConfig()
        config.log_level = log_level
        
        self._print_info(f"Starting Gleitzeit Hub on {host}:{port}")
        
        self.hub = CentralHub(host=host, port=port, config=config)
        
        if background:
            # Start hub in background
            asyncio.create_task(self.hub.start())
            await asyncio.sleep(2)  # Give it time to start
            self.running = True
            self._print_success(f"Hub started in background on http://{host}:{port}")
            return True
        else:
            # Run hub in foreground
            try:
                self.running = True
                await self.hub.start()
            except KeyboardInterrupt:
                self._print_info("Shutting down hub...")
                await self.hub.shutdown()
                self.running = False
        
        return True
    
    async def start_components(self, hub_url: str = "http://localhost:8001",
                             components: List[str] = None, auto_start_hub: bool = True):
        """Start core components"""
        if components is None:
            components = ["queue", "deps", "engine"]
        
        # Auto-start hub if needed
        if auto_start_hub:
            from urllib.parse import urlparse
            parsed = urlparse(hub_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8001
            
            if not await self.ensure_hub_running(host, port):
                self._print_error("Failed to start or connect to hub")
                return False
        
        config = ComponentConfig()
        config.hub_url = hub_url
        
        started = []
        
        try:
            if "queue" in components:
                self._print_info("Starting Queue Manager...")
                queue = QueueManagerClient(
                    component_id="cli-queue",
                    config=config,
                    hub_url=hub_url
                )
                asyncio.create_task(queue.start())
                self.components["queue"] = queue
                started.append("Queue Manager")
            
            if "deps" in components:
                self._print_info("Starting Dependency Resolver...")
                deps = DependencyResolverClient(
                    component_id="cli-deps",
                    config=config,
                    hub_url=hub_url
                )
                asyncio.create_task(deps.start())
                self.components["deps"] = deps
                started.append("Dependency Resolver")
            
            if "engine" in components:
                self._print_info("Starting Execution Engine...")
                engine = ExecutionEngineClient(
                    component_id="cli-engine",
                    config=config,
                    hub_url=hub_url
                )
                asyncio.create_task(engine.start())
                self.components["engine"] = engine
                started.append("Execution Engine")
            
            await asyncio.sleep(2)  # Give components time to connect
            
            self._print_success(f"Started components: {', '.join(started)}")
            return True
            
        except Exception as e:
            self._print_error(f"Failed to start components: {e}")
            return False
    
    async def status(self, hub_url: str = "http://localhost:8001", auto_start_hub: bool = False):
        """Show status of hub and components"""
        # Check if hub is running, optionally start it
        if auto_start_hub:
            from urllib.parse import urlparse
            parsed = urlparse(hub_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8001
            
            if not await self.ensure_hub_running(host, port):
                self._print_error("Hub is not running and failed to start")
                return
        
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{hub_url}/stats", timeout=2.0)
                if response.status_code == 200:
                    stats = response.json()
                    self._display_status(stats)
                else:
                    self._print_error(f"Hub returned status {response.status_code}")
        except Exception as e:
            self._print_error(f"Cannot connect to hub at {hub_url}")
            self._print_info("Tip: Use 'gleitzeit5 start --all' to start everything automatically")
    
    async def submit_workflow(self, workflow_file: str, hub_url: str = "http://localhost:8001", 
                             auto_start_hub: bool = True):
        """Submit a workflow from a YAML/JSON file"""
        path = Path(workflow_file)
        if not path.exists():
            self._print_error(f"Workflow file not found: {workflow_file}")
            return False
        
        # Auto-start hub if needed
        if auto_start_hub:
            from urllib.parse import urlparse
            parsed = urlparse(hub_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8001
            
            if not await self.ensure_hub_running(host, port):
                self._print_error("Failed to start or connect to hub")
                return False
        
        try:
            # Load workflow definition
            with open(path) as f:
                if path.suffix in ['.yaml', '.yml']:
                    workflow = yaml.safe_load(f)
                else:
                    workflow = json.load(f)
            
            # Connect to hub and submit
            import socketio
            sio = socketio.AsyncClient()
            
            workflow_id = f"cli-workflow-{int(time.time())}"
            results = {}
            
            @sio.on('task_completed')
            async def handle_task_completed(data):
                task_id = data['task_id']
                results[task_id] = data['result']
                self._print_info(f"Task {task_id} completed")
            
            await sio.connect(hub_url)
            
            # Submit tasks from workflow
            for task in workflow.get('tasks', []):
                await sio.emit('route_event', {
                    'target_component_type': 'queue_manager',
                    'event_name': 'queue_task',
                    'event_data': {
                        'task_id': task['id'],
                        'workflow_id': workflow_id,
                        'method': task['method'],
                        'parameters': task.get('parameters', {}),
                        'dependencies': task.get('dependencies', []),
                        'priority': task.get('priority', 2)
                    }
                })
                self._print_info(f"Submitted task: {task['id']}")
            
            self._print_success(f"Workflow {workflow_id} submitted successfully")
            
            # Wait for completion if requested
            if workflow.get('wait_for_completion', False):
                self._print_info("Waiting for workflow completion...")
                await asyncio.sleep(workflow.get('timeout', 30))
            
            await sio.disconnect()
            return True
            
        except Exception as e:
            self._print_error(f"Failed to submit workflow: {e}")
            return False
    
    async def list_providers(self, hub_url: str = "http://localhost:8001", auto_start_hub: bool = False):
        """List available providers"""
        # Auto-start hub if requested
        if auto_start_hub:
            from urllib.parse import urlparse
            parsed = urlparse(hub_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8001
            
            if not await self.ensure_hub_running(host, port):
                self._print_error("Hub is not running and failed to start")
                return
        
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{hub_url}/stats", timeout=2.0)
                if response.status_code == 200:
                    stats = response.json()
                    components = stats.get('components', {})
                    
                    providers = [c for c in components.values() 
                                if c.get('component_type') == 'provider']
                    
                    if providers:
                        self._display_providers(providers)
                    else:
                        self._print_info("No providers currently connected")
                        self._print_info("Tip: Start some providers to see them here")
                else:
                    self._print_error(f"Hub returned status {response.status_code}")
        except Exception as e:
            self._print_error(f"Cannot connect to hub at {hub_url}")
            self._print_info("Tip: Use 'gleitzeit5 start --all' to start everything automatically")
    
    async def monitor(self, hub_url: str = "http://localhost:8001", interval: int = 2, 
                     auto_start_hub: bool = False):
        """Monitor hub activity in real-time"""
        # Auto-start hub if requested
        if auto_start_hub:
            from urllib.parse import urlparse
            parsed = urlparse(hub_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8001
            
            if not await self.ensure_hub_running(host, port):
                self._print_error("Hub is not running and failed to start")
                return
        
        self._print_info(f"Monitoring hub at {hub_url} (Ctrl+C to stop)")
        
        try:
            while True:
                await self.status(hub_url)
                await asyncio.sleep(interval)
        except KeyboardInterrupt:
            self._print_info("Monitoring stopped")
    
    async def quick_start(self, host: str = "127.0.0.1", port: int = 8001, 
                         start_components: bool = True, keep_running: bool = False):
        """Quick start: Hub + components in one command"""
        self._print_info("🚀 Quick starting Gleitzeit...")
        
        # Start hub
        if not await self.ensure_hub_running(host, port):
            self._print_error("Failed to start hub")
            return False
        
        # Start components if requested
        if start_components:
            hub_url = f"http://{host}:{port}"
            success = await self.start_components(hub_url, auto_start_hub=False)
            if not success:
                self._print_error("Failed to start some components")
                return False
        
        self._print_success(f"✅ Gleitzeit is ready at http://{host}:{port}")
        self._print_info("💡 Try: gleitzeit5 status")
        self._print_info("💡 Try: gleitzeit5 submit examples/simple_llm_workflow.yaml")
        
        if keep_running:
            try:
                self._print_info("Press Ctrl+C to stop")
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                self._print_info("Shutting down...")
                if self.hub_auto_started and self.hub:
                    await self.hub.shutdown()
        
        return True
    
    async def run_workflow(self, workflow_file: str, host: str = "127.0.0.1", port: int = 8001):
        """Run a workflow from start to finish - one command does everything"""
        self._print_info(f"🚀 Running workflow: {workflow_file}")
        
        # Start everything
        if not await self.quick_start(host, port, start_components=True, keep_running=False):
            return False
        
        # Submit workflow
        hub_url = f"http://{host}:{port}"
        success = await self.submit_workflow(workflow_file, hub_url, auto_start_hub=False)
        
        if success:
            self._print_success("✅ Workflow submitted successfully!")
            self._print_info("💡 Use 'gleitzeit5 monitor' to watch progress")
        
        return success
    
    # Display helper methods
    def _display_status(self, stats: Dict[str, Any]):
        """Display hub status in a nice format"""
        if RICH_AVAILABLE and self.console:
            # Create status table
            table = Table(title="Gleitzeit Hub Status", show_header=True)
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="green")
            
            hub_stats = stats.get('hub_stats', {})
            table.add_row("Hub Version", hub_stats.get('version', 'Unknown'))
            table.add_row("Uptime", self._format_uptime(hub_stats.get('uptime_seconds', 0)))
            table.add_row("Connected Components", str(hub_stats.get('connected_components', 0)))
            table.add_row("Total Events", str(hub_stats.get('total_events_routed', 0)))
            
            self.console.print(table)
            
            # Show components
            components = stats.get('components', {})
            if components:
                comp_table = Table(title="Connected Components", show_header=True)
                comp_table.add_column("ID", style="yellow")
                comp_table.add_column("Type", style="cyan")
                comp_table.add_column("Status", style="green")
                
                for comp_id, comp_data in components.items():
                    comp_table.add_row(
                        comp_id,
                        comp_data.get('component_type', 'unknown'),
                        comp_data.get('status', 'unknown')
                    )
                
                self.console.print(comp_table)
        else:
            # Plain text output
            print("\n=== Gleitzeit Hub Status ===")
            hub_stats = stats.get('hub_stats', {})
            print(f"Version: {hub_stats.get('version', 'Unknown')}")
            print(f"Uptime: {self._format_uptime(hub_stats.get('uptime_seconds', 0))}")
            print(f"Connected Components: {hub_stats.get('connected_components', 0)}")
            print(f"Total Events: {hub_stats.get('total_events_routed', 0)}")
            
            components = stats.get('components', {})
            if components:
                print("\n=== Connected Components ===")
                for comp_id, comp_data in components.items():
                    print(f"  {comp_id}: {comp_data.get('component_type')} - {comp_data.get('status')}")
    
    def _display_providers(self, providers: List[Dict[str, Any]]):
        """Display provider list in a nice format"""
        if RICH_AVAILABLE and self.console:
            table = Table(title="Available Providers", show_header=True)
            table.add_column("ID", style="yellow")
            table.add_column("Protocol", style="cyan")
            table.add_column("Capabilities", style="green")
            table.add_column("Status", style="blue")
            
            for provider in providers:
                table.add_row(
                    provider.get('component_id', 'unknown'),
                    provider.get('protocol', 'generic'),
                    ', '.join(provider.get('capabilities', [])),
                    provider.get('status', 'unknown')
                )
            
            self.console.print(table)
        else:
            print("\n=== Available Providers ===")
            for provider in providers:
                print(f"  {provider.get('component_id')}: {provider.get('protocol')} - {provider.get('capabilities')}")
    
    def _format_uptime(self, seconds: float) -> str:
        """Format uptime seconds to human readable"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def _print_info(self, message: str):
        """Print info message"""
        if RICH_AVAILABLE and self.console:
            self.console.print(f"[blue]ℹ️  {message}[/blue]")
        else:
            print(f"ℹ️  {message}")
    
    def _print_success(self, message: str):
        """Print success message"""
        if RICH_AVAILABLE and self.console:
            self.console.print(f"[green]✅ {message}[/green]")
        else:
            print(f"✅ {message}")
    
    def _print_error(self, message: str):
        """Print error message"""
        if RICH_AVAILABLE and self.console:
            self.console.print(f"[red]❌ {message}[/red]")
        else:
            print(f"❌ {message}")


async def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Gleitzeit - Modern workflow orchestration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick start: Everything automatically (recommended)
  gleitzeit5 start
  
  # One command to run a workflow (starts everything needed)
  gleitzeit5 run examples/simple_llm_workflow.yaml
  
  # Submit workflow (auto-starts hub if needed)
  gleitzeit5 submit workflow.yaml
  
  # Monitor in real-time (auto-starts hub if needed)
  gleitzeit5 monitor
  
  # Start just the hub
  gleitzeit5 hub --port 8001
  
  # Check status
  gleitzeit5 status
"""
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Start command - quick start everything
    start_parser = subparsers.add_parser('start', help='Quick start hub and components')
    start_parser.add_argument('--all', action='store_true', help='Start hub and all core components')
    start_parser.add_argument('--hub-only', action='store_true', help='Start only the hub')
    start_parser.add_argument('--components', nargs='+', choices=['queue', 'deps', 'engine'],
                            help='Start specific components')
    start_parser.add_argument('--host', default='127.0.0.1', help='Hub host')
    start_parser.add_argument('--port', type=int, default=8001, help='Hub port')
    start_parser.add_argument('--background', action='store_true', help='Run in background')
    
    # Hub command
    hub_parser = subparsers.add_parser('hub', help='Start the central hub')
    hub_parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    hub_parser.add_argument('--port', type=int, default=8001, help='Port to bind to')
    hub_parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                          default='INFO', help='Logging level')
    hub_parser.add_argument('--background', action='store_true', help='Run in background')
    
    # Components command
    comp_parser = subparsers.add_parser('components', help='Start components')
    comp_parser.add_argument('names', nargs='+', choices=['queue', 'deps', 'engine', 'all'],
                           help='Components to start')
    comp_parser.add_argument('--hub-url', default='http://localhost:8001',
                           help='Hub URL to connect to')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show hub and component status')
    status_parser.add_argument('--hub-url', default='http://localhost:8001',
                             help='Hub URL to check')
    
    # Submit command
    submit_parser = subparsers.add_parser('submit', help='Submit a workflow')
    submit_parser.add_argument('workflow', help='Workflow file (YAML or JSON)')
    submit_parser.add_argument('--hub-url', default='http://localhost:8001',
                             help='Hub URL to submit to')
    
    # Monitor command
    monitor_parser = subparsers.add_parser('monitor', help='Monitor hub in real-time')
    monitor_parser.add_argument('--hub-url', default='http://localhost:8001',
                              help='Hub URL to monitor')
    monitor_parser.add_argument('--interval', type=int, default=2,
                              help='Update interval in seconds')
    
    # Providers command
    providers_parser = subparsers.add_parser('providers', help='List available providers')
    providers_parser.add_argument('--hub-url', default='http://localhost:8001',
                                help='Hub URL to query')
    
    # Run command - one-shot workflow execution
    run_parser = subparsers.add_parser('run', help='Start everything and run a workflow (one command)')
    run_parser.add_argument('workflow', help='Workflow file to run')
    run_parser.add_argument('--host', default='127.0.0.1', help='Hub host')
    run_parser.add_argument('--port', type=int, default=8001, help='Hub port')
    
    # Version command
    version_parser = subparsers.add_parser('version', help='Show version information')
    
    args = parser.parse_args()
    
    # Initialize CLI
    cli = GleitzeitCLI()
    
    # Handle commands
    if args.command == 'start':
        if args.all:
            # Quick start everything
            await cli.quick_start(args.host, args.port, start_components=True, keep_running=not args.background)
        elif args.hub_only:
            await cli.start_hub(args.host, args.port, background=args.background)
        elif args.components:
            await cli.start_components(f"http://{args.host}:{args.port}", args.components)
        else:
            # Default: quick start everything
            await cli.quick_start(args.host, args.port, start_components=True, keep_running=not args.background)
    
    elif args.command == 'hub':
        await cli.start_hub(args.host, args.port, args.log_level, args.background)
    
    elif args.command == 'components':
        components = ['queue', 'deps', 'engine'] if 'all' in args.names else args.names
        await cli.start_components(args.hub_url, components, auto_start_hub=True)
    
    elif args.command == 'status':
        await cli.status(args.hub_url, auto_start_hub=False)
    
    elif args.command == 'submit':
        await cli.submit_workflow(args.workflow, args.hub_url, auto_start_hub=True)
    
    elif args.command == 'monitor':
        await cli.monitor(args.hub_url, args.interval, auto_start_hub=True)
    
    elif args.command == 'providers':
        await cli.list_providers(args.hub_url, auto_start_hub=False)
    
    elif args.command == 'run':
        await cli.run_workflow(args.workflow, args.host, args.port)
    
    elif args.command == 'version':
        print("Gleitzeit - Version 0.0.1")
        print("Modern workflow orchestration with Socket.IO")
    
    else:
        parser.print_help()


def run():
    """Entry point for the CLI"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"💥 Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run()