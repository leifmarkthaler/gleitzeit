#!/usr/bin/env python3
"""
Gleitzeit CLI - Service Interface

Similar to 'jupyter lab', this provides a persistent service interface
for running Gleitzeit cluster with web dashboard.
"""

import argparse
import asyncio
import logging
import signal
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from .core.cluster import GleitzeitCluster
from .storage.result_cache import ResultCache
from .storage.redis_client import RedisClient
from .auth.cli_auth import CLIAuthenticator
from .auth.auth_manager import get_auth_manager, AuthenticationError, initialize_auth
from .auth.decorators import require_auth, require_permission
from .auth.models import Permission
from .execution.executor_node import GleitzeitExecutorNode
from .scheduler.scheduler_node import GleitzeitScheduler, SchedulingPolicy
from .core.node import NodeCapabilities
from .core.task import TaskType
from .functions.registry import get_function_registry
from .cli_run import run_command_handler
from .cli_dev import dev_command_handler
from .cli_monitor import monitor_command_handler
from .cli_monitor_pro import monitor_pro_command_handler  
from .cli_status import status_command_handler


class GleitzeitService:
    """Persistent Gleitzeit service similar to Jupyter Lab"""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        redis_url: str = "redis://localhost:6379",
        enable_redis: bool = True,
        auto_open_browser: bool = True,
        log_level: str = "INFO"
    ):
        self.host = host
        self.port = port
        self.redis_url = redis_url
        self.enable_redis = enable_redis
        self.auto_open_browser = auto_open_browser
        self.log_level = log_level
        
        self.cluster: Optional[GleitzeitCluster] = None
        self.running = False
        
        # Setup logging
        level = getattr(logging, log_level.upper())
        logging.basicConfig(level=level)
        logging.getLogger('socketio').setLevel(logging.WARNING)
        logging.getLogger('aiohttp').setLevel(logging.WARNING)
    
    async def start(self):
        """Start the Gleitzeit service"""
        print("🚀 Starting Gleitzeit Cluster Service")
        print("=" * 50)
        print(f"   Host: {self.host}")
        print(f"   Port: {self.port}")
        print(f"   Redis: {'✅ Enabled' if self.enable_redis else '❌ Disabled'}")
        print()
        
        try:
            # Initialize cluster
            self.cluster = GleitzeitCluster(
                redis_url=self.redis_url if self.enable_redis else None,
                enable_real_execution=False,
                enable_redis=self.enable_redis,
                enable_socketio=True,
                auto_start_socketio_server=True,
                socketio_host=self.host,
                socketio_port=self.port
            )
            
            # Start cluster
            await self.cluster.start()
            
            self.running = True
            
            # Show startup info
            base_url = f"http://{self.host}:{self.port}"
            print("✅ Gleitzeit service started successfully!")
            print()
            print("🌐 Service URLs:")
            print(f"   Dashboard: {base_url}")
            print(f"   Health: {base_url}/health")
            print(f"   Metrics: {base_url}/metrics")
            print()
            
            print("💡 Getting Started:")
            print("   1. Open dashboard in your browser")
            print("   2. Start executor: PYTHONPATH=. python examples/start_executor.py")
            print("   3. Submit workflows: PYTHONPATH=. python examples/minimal_example.py")
            print()
            
            # Auto-open browser
            if self.auto_open_browser:
                print("🌐 Opening dashboard in browser...")
                try:
                    webbrowser.open(base_url)
                except Exception as e:
                    print(f"   Could not auto-open: {e}")
            
            print("Press Ctrl+C to stop the service")
            print("=" * 50)
            
            # Keep service running
            await self._run_service()
            
        except Exception as e:
            print(f"❌ Failed to start service: {e}")
            raise
    
    async def _run_service(self):
        """Keep the service running with periodic status updates"""
        try:
            while self.running:
                await asyncio.sleep(60)  # Status every minute
                
                if self.cluster:
                    try:
                        nodes = await self.cluster.list_nodes()
                        workflows = await self.cluster.list_workflows()
                        active_workflows = len([w for w in workflows if w.get('status') == 'running'])
                        
                        print(f"💓 Status: {len(nodes)} nodes, {active_workflows} active workflows")
                        
                    except Exception:
                        pass  # Silent status check failures
                
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the service"""
        print("\n🛑 Stopping Gleitzeit service...")
        self.running = False
        
        if self.cluster:
            await self.cluster.stop()
        
        print("✅ Service stopped")
    
    def setup_signal_handlers(self):
        """Setup graceful shutdown"""
        def signal_handler(signum, frame):
            self.running = False
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def serve_command(args):
    """Start the service"""
    service = GleitzeitService(
        host=args.host,
        port=args.port,
        redis_url=args.redis_url,
        enable_redis=not args.no_redis,
        auto_open_browser=not args.no_browser,
        log_level=args.log_level
    )
    
    service.setup_signal_handlers()
    
    try:
        await service.start()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")


async def results_command(args):
    """Handle results commands"""
    
    if not args.results_command:
        print("❌ No results command specified. Use --help for options.")
        return
    
    # Initialize cache
    redis_client = RedisClient()
    try:
        await redis_client.connect()
        cache = ResultCache(redis_client=redis_client)
    except Exception:
        print("⚠️  Redis not available, using file-only cache")
        cache = ResultCache(redis_client=None)
    
    try:
        if args.results_command == 'list':
            await cmd_list_results(cache, args)
        elif args.results_command == 'show':
            await cmd_show_result(cache, args)
        elif args.results_command == 'export':
            await cmd_export_results(cache, args)
        elif args.results_command == 'clear':
            await cmd_clear_cache(cache, args)
        elif args.results_command == 'stats':
            await cmd_cache_stats(cache, args)
    except Exception as e:
        print(f"❌ Command failed: {e}")
    finally:
        if redis_client:
            await redis_client.disconnect()


async def cmd_list_results(cache: ResultCache, args):
    """List cached results"""
    
    print("📋 Listing cached workflow results...")
    print()
    
    # Get results with filters
    if args.tags:
        results = await cache.get_results_by_tags(args.tags)
        print(f"🏷️  Filtering by tags: {', '.join(args.tags)}")
    elif args.hours:
        results = await cache.get_recent_results(hours=args.hours)
        print(f"⏰ Showing results from last {args.hours} hours")
    else:
        results = await cache.list_cached_results()
        print("📄 Showing all cached results")
    
    if not results:
        print("   No results found")
        return
    
    # Limit results
    if len(results) > args.limit:
        results = results[:args.limit]
        print(f"   (Showing first {args.limit} of {len(results)} results)")
    
    print()
    print(f"{'ID':<12} {'Name':<20} {'Status':<12} {'Tasks':<6} {'Stored':<20} {'Tags'}")
    print("-" * 80)
    
    for result_data in results:
        workflow_result = result_data["result"]
        metadata = workflow_result.get("metadata", {})
        
        workflow_id = result_data["workflow_id"][:8]
        name = metadata.get("name", "Unknown")[:18]
        status = workflow_result.get("status", "unknown")[:10]
        tasks = workflow_result.get("completed_tasks", 0)
        stored = result_data["stored_at"][:19].replace("T", " ")
        tags = ", ".join(result_data.get("tags", []))[:15]
        
        print(f"{workflow_id:<12} {name:<20} {status:<12} {tasks:<6} {stored:<20} {tags}")


async def cmd_show_result(cache: ResultCache, args):
    """Show specific result details"""
    
    print(f"🔍 Showing result: {args.workflow_id}")
    print()
    
    result_data = await cache.get_workflow_result(args.workflow_id)
    
    if not result_data:
        print("❌ Result not found")
        return
    
    workflow_result = result_data["result"]
    metadata = workflow_result.get("metadata", {})
    
    print(f"📋 Workflow Details:")
    print(f"   ID: {result_data['workflow_id']}")
    print(f"   Name: {metadata.get('name', 'Unknown')}")
    print(f"   Description: {metadata.get('description', 'N/A')}")
    print(f"   Status: {workflow_result.get('status', 'unknown')}")
    print(f"   Completed Tasks: {workflow_result.get('completed_tasks', 0)}")
    print(f"   Stored: {result_data['stored_at']}")
    print(f"   Tags: {', '.join(result_data.get('tags', []))}")
    
    if args.tasks:
        print(f"\n📄 Task Results:")
        task_results = cache.get_task_results(result_data)
        if task_results:
            for task_id, task_result in task_results.items():
                print(f"   {task_id}:")
                # Show first 200 chars of result
                result_str = str(task_result)
                if len(result_str) > 200:
                    result_str = result_str[:200] + "..."
                print(f"      {result_str}")
        else:
            print("   No task results found")


async def cmd_export_results(cache: ResultCache, args):
    """Export results to file"""
    
    print(f"💾 Exporting results to: {args.output_file}")
    
    output_path = Path(args.output_file)
    
    success = await cache.export_results(
        output_file=output_path,
        format=args.format,
        tags=args.tags
    )
    
    if success:
        file_size = output_path.stat().st_size
        print(f"✅ Export completed: {file_size} bytes")
    else:
        print("❌ Export failed")


async def cmd_clear_cache(cache: ResultCache, args):
    """Clear result cache"""
    
    if args.days:
        print(f"🗑️  Clearing results older than {args.days} days...")
    else:
        print("🗑️  Clearing ALL cached results...")
    
    if not args.confirm:
        response = input("Are you sure? (y/N): ")
        if response.lower() != 'y':
            print("❌ Cancelled")
            return
    
    cleared = await cache.clear_cache(older_than_days=args.days)
    print(f"✅ Cleared {cleared} results")


async def cmd_cache_stats(cache: ResultCache, args):
    """Show cache statistics"""
    
    print("📊 Result Cache Statistics")
    print("=" * 40)
    
    all_results = await cache.list_cached_results()
    
    if not all_results:
        print("No cached results found")
        return
    
    print(f"Total Results: {len(all_results)}")
    
    # Status distribution
    status_counts = {}
    tag_counts = {}
    
    for result_data in all_results:
        status = result_data["result"].get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        
        for tag in result_data.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    
    print(f"\nStatus Distribution:")
    for status, count in status_counts.items():
        print(f"   {status}: {count}")
    
    if tag_counts:
        print(f"\nTag Distribution:")
        # Show top 10 tags
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        for tag, count in sorted_tags[:10]:
            print(f"   {tag}: {count}")
    
    # Time distribution (last 24 hours, last week, etc.)
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    
    last_hour = sum(1 for r in all_results 
                   if (now - datetime.fromisoformat(r["stored_at"])).total_seconds() < 3600)
    last_day = sum(1 for r in all_results 
                  if (now - datetime.fromisoformat(r["stored_at"])).days < 1)
    last_week = sum(1 for r in all_results 
                   if (now - datetime.fromisoformat(r["stored_at"])).days < 7)
    
    print(f"\nTime Distribution:")
    print(f"   Last hour: {last_hour}")
    print(f"   Last 24 hours: {last_day}")
    print(f"   Last week: {last_week}")
    
    # Storage info
    cache_dir = cache.cache_dir
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in cache_files)
        print(f"\nFile Cache:")
        print(f"   Directory: {cache_dir}")
        print(f"   Files: {len(cache_files)}")
        print(f"   Total Size: {total_size} bytes ({total_size/1024:.1f} KB)")


async def executor_command(args):
    """Handle executor command"""
    
    # Setup logging
    level = getattr(logging, args.log_level.upper())
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("🚀 Starting Gleitzeit Executor Node")
    print("=" * 50)
    print(f"   Name: {args.name}")
    print(f"   Cluster: {args.cluster}")
    print(f"   Max Tasks: {args.tasks}")
    print(f"   Heartbeat: {args.heartbeat}s")
    
    # Check authentication
    try:
        auth_manager = get_auth_manager()
        context = auth_manager.get_current_context()
        if context:
            print(f"   Auth: Authenticated as {context.user.username}")
        else:
            context = auth_manager.authenticate_from_environment()
            if context:
                print(f"   Auth: Using environment credentials ({context.user.username})")
            else:
                print("   Auth: ⚠️  No authentication found. Use 'gleitzeit auth login' or set GLEITZEIT_API_KEY")
                print("          Executor will use demo authentication")
    except Exception as e:
        print(f"   Auth: ⚠️  Authentication error: {e}")
        print("          Executor will use demo authentication")
    
    # Configure capabilities based on arguments
    capabilities = NodeCapabilities(
        supported_task_types=[
            TaskType.FUNCTION,
            TaskType.TEXT,
            TaskType.VISION,
        ],
        available_models=["llama3.1", "codellama", "llava"],
        max_concurrent_tasks=args.tasks,
        has_gpu=not args.cpu_only,
        memory_limit_gb=8.0
    )
    
    # Filter task types if GPU/CPU only specified
    if args.gpu_only:
        capabilities.supported_task_types = [TaskType.OLLAMA_VISION]
        capabilities.has_gpu = True
        print("   Mode: GPU tasks only")
    elif args.cpu_only:
        capabilities.supported_task_types = [TaskType.FUNCTION, TaskType.TEXT]
        capabilities.has_gpu = False
        print("   Mode: CPU tasks only")
    
    print()
    
    try:
        # Create executor node
        executor_node = GleitzeitExecutorNode(
            name=args.name,
            cluster_url=args.cluster,
            capabilities=capabilities,
            heartbeat_interval=args.heartbeat,
            max_concurrent_tasks=args.tasks
        )
        
        # Setup signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            print(f"\n🛑 Received signal {signum}, shutting down...")
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(executor_node.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Start the executor
        await executor_node.start()
        
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Executor failed: {e}")
        logging.exception("Executor failed")


async def scheduler_command(args):
    """Handle scheduler command"""
    
    # Setup logging
    level = getattr(logging, args.log_level.upper())
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("🗓️  Starting Gleitzeit Scheduler Node")
    print("=" * 50)
    print(f"   Name: {args.name}")
    print(f"   Cluster: {args.cluster}")
    print(f"   Policy: {args.policy}")
    print(f"   Queue Size: {args.queue_size}")
    print(f"   Heartbeat: {args.heartbeat}s")
    
    # Check authentication
    try:
        auth_manager = get_auth_manager()
        context = auth_manager.get_current_context()
        if context:
            print(f"   Auth: Authenticated as {context.user.username}")
        else:
            context = auth_manager.authenticate_from_environment()
            if context:
                print(f"   Auth: Using environment credentials ({context.user.username})")
            else:
                print("   Auth: ⚠️  No authentication found. Use 'gleitzeit auth login' or set GLEITZEIT_API_KEY")
                print("          Scheduler will use demo authentication")
    except Exception as e:
        print(f"   Auth: ⚠️  Authentication error: {e}")
        print("          Scheduler will use demo authentication")
    
    print()
    
    try:
        # Create scheduler
        scheduler = GleitzeitScheduler(
            name=args.name,
            cluster_url=args.cluster,
            policy=SchedulingPolicy(args.policy),
            max_queue_size=args.queue_size,
            heartbeat_interval=args.heartbeat
        )
        
        # Setup signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            print(f"\n🛑 Received signal {signum}, shutting down...")
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(scheduler.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Start the scheduler
        await scheduler.start()
        
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Scheduler failed: {e}")
        logging.exception("Scheduler failed")


async def functions_command(args):
    """Handle functions command"""
    
    if not args.functions_command:
        print("❌ No functions command specified. Use --help for options.")
        return
    
    # Get function registry
    registry = get_function_registry()
    
    try:
        if args.functions_command == 'list':
            await cmd_list_functions(registry, args)
        elif args.functions_command == 'show':
            await cmd_show_function(registry, args)
        elif args.functions_command == 'search':
            await cmd_search_functions(registry, args)
        elif args.functions_command == 'stats':
            await cmd_function_stats(registry, args)
        elif args.functions_command == 'export':
            await cmd_export_functions(registry, args)
    except Exception as e:
        print(f"❌ Command failed: {e}")


async def cmd_list_functions(registry, args):
    """List available functions"""
    
    print("📚 Available Functions")
    print("=" * 50)
    
    if args.category:
        functions = registry.list_functions(category=args.category)
        print(f"🏷️  Category: {args.category}")
    else:
        functions = registry.list_functions()
        print("📄 All functions")
    
    if not functions:
        print("   No functions found")
        return
    
    print()
    
    # Group by category if showing all
    if not args.category:
        categories = registry.list_categories()
        for category in sorted(categories):
            cat_functions = registry.list_functions(category=category)
            if cat_functions:
                print(f"📂 {category.upper()} ({len(cat_functions)} functions)")
                for func_name in sorted(cat_functions)[:args.limit]:
                    info = registry.get_function_info(func_name)
                    if info:
                        desc = info.get('description', 'No description')[:60]
                        async_marker = " (async)" if info.get('is_async') else ""
                        print(f"   {func_name}{async_marker} - {desc}")
                print()
    else:
        # Show functions in specified category
        for func_name in sorted(functions)[:args.limit]:
            info = registry.get_function_info(func_name)
            if info:
                desc = info.get('description', 'No description')[:60]
                async_marker = " (async)" if info.get('is_async') else ""
                print(f"   {func_name}{async_marker} - {desc}")


async def cmd_show_function(registry, args):
    """Show detailed function information"""
    
    print(f"🔍 Function Details: {args.function_name}")
    print("=" * 50)
    
    info = registry.get_function_info(args.function_name)
    
    if not info:
        print("❌ Function not found")
        
        # Suggest similar functions
        similar = registry.search_functions(args.function_name)
        if similar:
            print("\n💡 Similar functions:")
            for func in similar[:3]:
                print(f"   {func['name']} - {func.get('description', '')[:50]}")
        return
    
    print(f"📋 Name: {info['name']}")
    print(f"📂 Category: {info['category']}")
    print(f"⚡ Type: {'Async' if info.get('is_async') else 'Sync'}")
    
    if info.get('signature'):
        print(f"✍️  Signature: {info['signature']}")
    
    if info.get('description'):
        print(f"📄 Description:")
        # Format description with proper wrapping
        desc_lines = info['description'].split('\n')
        for line in desc_lines:
            print(f"   {line}")
    
    # Show parameters if available
    if info.get('parameters'):
        print(f"\n📥 Parameters:")
        for param in info['parameters']:
            required = "required" if param.get('required') else "optional"
            default = f" (default: {param['default']})" if param.get('default') is not None else ""
            print(f"   {param['name']}: {param['type']} - {required}{default}")
    
    # Show return type
    if info.get('return_type'):
        print(f"📤 Returns: {info['return_type']}")


async def cmd_search_functions(registry, args):
    """Search functions by query"""
    
    print(f"🔍 Searching functions: '{args.query}'")
    print("=" * 50)
    
    results = registry.search_functions(args.query)
    
    if not results:
        print("❌ No functions found matching query")
        return
    
    print(f"📋 Found {len(results)} functions:")
    print()
    
    for result in results[:args.limit]:
        match_type = result.get('match_type', 'unknown')
        match_icon = "📛" if match_type == "name" else "📄"
        async_marker = " (async)" if result.get('is_async') else ""
        
        print(f"{match_icon} {result['name']}{async_marker}")
        print(f"   Category: {result['category']}")
        if result.get('description'):
            desc = result['description'][:100] + ("..." if len(result['description']) > 100 else "")
            print(f"   Description: {desc}")
        print()


async def cmd_function_stats(registry, args):
    """Show function registry statistics"""
    
    print("📊 Function Registry Statistics")
    print("=" * 50)
    
    stats = registry.get_stats()
    
    print(f"Total Functions: {stats['total_functions']}")
    print(f"Categories: {stats['total_categories']}")
    print(f"Aliases: {stats['total_aliases']}")
    print(f"Async Functions: {stats['async_functions']}")
    
    print(f"\n📂 Functions by Category:")
    for category, count in stats['categories'].items():
        print(f"   {category}: {count} functions")


async def cmd_export_functions(registry, args):
    """Export function documentation"""
    
    print(f"💾 Exporting function docs to: {args.output_file}")
    
    try:
        docs = registry.export_function_list(format=args.format)
        
        output_path = Path(args.output_file)
        output_path.write_text(docs, encoding='utf-8')
        
        file_size = output_path.stat().st_size
        print(f"✅ Export completed: {file_size} bytes")
        
    except Exception as e:
        print(f"❌ Export failed: {e}")


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(prog="gleitzeit")
    subparsers = parser.add_subparsers(dest='command')
    
    # Dev command (NEW - for easy development)
    dev = subparsers.add_parser('dev', help='Start development environment (cluster + executor + scheduler)')
    dev.add_argument('--port', type=int, default=8000, help='Cluster port (default: 8000)')
    dev.add_argument('--executors', type=int, default=1, help='Number of executors (default: 1)')
    dev.add_argument('--no-redis', action='store_true', help='Disable Redis')
    dev.add_argument('--no-scheduler', action='store_true', help='Disable scheduler')
    dev.add_argument('--no-executor', action='store_true', help='Disable executors')
    
    # Monitor command (NEW - for monitoring dashboard)
    monitor = subparsers.add_parser('monitor', help='Terminal monitoring dashboard')
    monitor.add_argument('--cluster', default='http://localhost:8000', help='Cluster URL to monitor')
    monitor.add_argument('--refresh', type=float, default=1.0, help='Refresh rate in seconds')
    monitor.add_argument('--pro', action='store_true', help='Use professional monitoring interface')
    
    # Professional monitor (alias)
    monitor_pro = subparsers.add_parser('pro', help='Professional monitoring dashboard')
    monitor_pro.add_argument('--cluster', default='http://localhost:8000', help='Cluster URL to monitor')
    monitor_pro.add_argument('--refresh', type=float, default=0.5, help='Refresh rate in seconds')
    
    # Status command (NEW - simple status check)
    status = subparsers.add_parser('status', help='Show cluster status')
    status.add_argument('--cluster', default='http://localhost:8000', help='Cluster URL')
    status.add_argument('--watch', action='store_true', help='Continuously watch status')
    status.add_argument('--interval', type=int, default=5, help='Watch interval in seconds')
    
    # Serve command
    serve = subparsers.add_parser('serve', help='Start Gleitzeit service')
    serve.add_argument('--host', default='localhost', help='Host (default: localhost)')
    serve.add_argument('--port', type=int, default=8000, help='Port (default: 8000)')
    serve.add_argument('--redis-url', default='redis://localhost:6379', help='Redis URL')
    serve.add_argument('--no-redis', action='store_true', help='Disable Redis')
    serve.add_argument('--no-browser', action='store_true', help='No auto-open browser')
    serve.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    
    # Version
    subparsers.add_parser('version', help='Show version')
    
    # Authentication commands
    auth_parser = subparsers.add_parser('auth', help='Authentication management')
    auth_cli = CLIAuthenticator()
    auth_cli.setup_auth_commands(auth_parser)
    
    # Results commands
    results = subparsers.add_parser('results', help='Manage workflow results')
    results_sub = results.add_subparsers(dest='results_command', help='Result operations')
    
    # List results
    list_cmd = results_sub.add_parser('list', help='List cached results')
    list_cmd.add_argument('--tags', nargs='+', help='Filter by tags')
    list_cmd.add_argument('--hours', type=int, help='Only results from last N hours')
    list_cmd.add_argument('--limit', type=int, default=10, help='Limit number of results')
    
    # Show result
    show_cmd = results_sub.add_parser('show', help='Show specific result')
    show_cmd.add_argument('workflow_id', help='Workflow ID to show')
    show_cmd.add_argument('--tasks', action='store_true', help='Show individual task results')
    
    # Export results
    export_cmd = results_sub.add_parser('export', help='Export results')
    export_cmd.add_argument('output_file', help='Output file path')
    export_cmd.add_argument('--format', choices=['json', 'pickle'], default='json', help='Export format')
    export_cmd.add_argument('--tags', nargs='+', help='Filter by tags')
    
    # Clear cache
    clear_cmd = results_sub.add_parser('clear', help='Clear result cache')
    clear_cmd.add_argument('--days', type=int, help='Only clear results older than N days')
    clear_cmd.add_argument('--confirm', action='store_true', help='Skip confirmation prompt')
    
    # Stats
    stats_cmd = results_sub.add_parser('stats', help='Show cache statistics')
    
    # Executor command
    executor = subparsers.add_parser('executor', help='Start executor node')
    executor.add_argument('--name', default='executor-1', help='Executor node name')
    executor.add_argument('--cluster', default='http://localhost:8000', help='Cluster URL to connect to')
    executor.add_argument('--tasks', type=int, default=3, help='Max concurrent tasks')
    executor.add_argument('--heartbeat', type=int, default=30, help='Heartbeat interval (seconds)')
    executor.add_argument('--gpu-only', action='store_true', help='Only accept GPU tasks')
    executor.add_argument('--cpu-only', action='store_true', help='Only accept CPU tasks')
    executor.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    
    # Scheduler command
    scheduler = subparsers.add_parser('scheduler', help='Start scheduler node')
    scheduler.add_argument('--name', default='scheduler-1', help='Scheduler node name')
    scheduler.add_argument('--cluster', default='http://localhost:8000', help='Cluster URL to connect to')
    scheduler.add_argument('--policy', choices=[p.value for p in SchedulingPolicy], 
                          default=SchedulingPolicy.LEAST_LOADED.value, help='Scheduling policy')
    scheduler.add_argument('--queue-size', type=int, default=1000, help='Max queue size')
    scheduler.add_argument('--heartbeat', type=int, default=30, help='Heartbeat interval (seconds)')
    scheduler.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    
    # Run command (NEW - for quick execution)
    run = subparsers.add_parser('run', help='Quick task/workflow execution')
    run.add_argument('--function', '-f', help='Run a function by name')
    run.add_argument('--args', nargs='*', help='Function arguments (key=value format)')
    run.add_argument('--text', '-t', help='Generate text with prompt')
    run.add_argument('--vision', '-v', help='Analyze image (path to image)')
    run.add_argument('--prompt', '-p', help='Prompt for vision analysis')
    run.add_argument('--workflow', '-w', help='Run workflow from YAML/JSON file')
    run.add_argument('--model', '-m', help='Model to use (for text/vision)')
    run.add_argument('--output', '-o', help='Output file for results')
    
    # Functions commands
    functions = subparsers.add_parser('functions', help='Manage secure functions')
    functions_sub = functions.add_subparsers(dest='functions_command', help='Function operations')
    
    # List functions
    list_func_cmd = functions_sub.add_parser('list', help='List available functions')
    list_func_cmd.add_argument('--category', help='Filter by category')
    list_func_cmd.add_argument('--limit', type=int, default=50, help='Limit number of results')
    
    # Show function
    show_func_cmd = functions_sub.add_parser('show', help='Show function details')
    show_func_cmd.add_argument('function_name', help='Function name to show')
    
    # Search functions
    search_func_cmd = functions_sub.add_parser('search', help='Search functions')
    search_func_cmd.add_argument('query', help='Search query')
    search_func_cmd.add_argument('--limit', type=int, default=10, help='Limit number of results')
    
    # Function stats
    stats_func_cmd = functions_sub.add_parser('stats', help='Show function statistics')
    
    # Export functions
    export_func_cmd = functions_sub.add_parser('export', help='Export function documentation')
    export_func_cmd.add_argument('output_file', help='Output file path')
    export_func_cmd.add_argument('--format', choices=['json', 'markdown'], default='markdown', help='Export format')
    
    args = parser.parse_args()
    
    if args.command == 'dev':
        asyncio.run(dev_command_handler(args))
    elif args.command == 'monitor':
        if getattr(args, 'pro', False):
            asyncio.run(monitor_pro_command_handler(args))
        else:
            asyncio.run(monitor_command_handler(args))
    elif args.command == 'pro':
        asyncio.run(monitor_pro_command_handler(args))
    elif args.command == 'status':
        asyncio.run(status_command_handler(args))
    elif args.command == 'serve':
        asyncio.run(serve_command(args))
    elif args.command == 'version':
        print("Gleitzeit v0.0.1")
    elif args.command == 'auth':
        auth_cli = CLIAuthenticator()
        asyncio.run(auth_cli.handle_auth_command(args))
    elif args.command == 'results':
        asyncio.run(results_command(args))
    elif args.command == 'executor':
        asyncio.run(executor_command(args))
    elif args.command == 'scheduler':
        asyncio.run(scheduler_command(args))
    elif args.command == 'functions':
        asyncio.run(functions_command(args))
    elif args.command == 'run':
        asyncio.run(run_command_handler(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()