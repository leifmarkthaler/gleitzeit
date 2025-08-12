#!/usr/bin/env python3
"""
Gleitzeit V3 CLI - Modern Distributed Architecture

This is the new CLI that uses the V3 centralized server architecture
while maintaining compatibility with existing command patterns.
"""

import argparse
import asyncio
import logging
import signal
import sys
import json
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any
import time

from .server.central_server import CentralServer
from .core.workflow_engine_client import WorkflowEngineClient
from .core.models import Workflow, Task, TaskParameters
from .providers.ollama_provider import OllamaProvider
from .providers.web_search_provider import WebSearchProvider
# Queue is now integrated into the central server

try:
    from ..test_gleitzeit_v3_mcp import RealMCPProvider
except ImportError:
    # Fallback if MCP provider not available
    RealMCPProvider = None

logger = logging.getLogger(__name__)


class GleitzeitV3Service:
    """V3 Service - uses centralized Socket.IO server architecture"""
    
    def __init__(
        self,
        host: str = "localhost", 
        port: int = 8000,
        enable_ollama: bool = True,
        enable_mcp: bool = True,
        enable_web_search: bool = True,
        auto_open_browser: bool = False,
        log_level: str = "INFO"
    ):
        self.host = host
        self.port = port
        self.enable_ollama = enable_ollama
        self.enable_mcp = enable_mcp
        self.enable_web_search = enable_web_search
        self.auto_open_browser = auto_open_browser
        self.log_level = log_level
        
        # V3 Components
        self.server: Optional[CentralServer] = None
        self.server_task: Optional[asyncio.Task] = None
        self.workflow_engine: Optional[WorkflowEngineClient] = None
        self.providers = []
        self.running = False
        
        # Setup logging
        level = getattr(logging, log_level.upper())
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        logging.getLogger('socketio').setLevel(logging.WARNING)
        logging.getLogger('aiohttp').setLevel(logging.WARNING)
        logging.getLogger('engineio').setLevel(logging.WARNING)
    
    async def start(self):
        """Start the V3 service"""
        print("🚀 Starting Gleitzeit V3 Service")
        print("=" * 50)
        print(f"   Architecture: Centralized Socket.IO Server")
        print(f"   Host: {self.host}")
        print(f"   Port: {self.port}")
        print(f"   Ollama: {'✅ Enabled' if self.enable_ollama else '❌ Disabled'}")
        print(f"   MCP: {'✅ Enabled' if self.enable_mcp else '❌ Disabled'}")
        print(f"   Web Search: {'✅ Enabled' if self.enable_web_search else '❌ Disabled'}")
        print()
        
        try:
            # 1. Start central server
            print("📡 Starting central server...")
            self.server = CentralServer(host=self.host, port=self.port)
            self.server_task = asyncio.create_task(self.server.start())
            await asyncio.sleep(2)
            print("   ✅ Central server running")
            
            # 2. Start providers
            provider_count = 0
            
            if self.enable_mcp and RealMCPProvider:
                print("🔧 Starting MCP provider...")
                try:
                    mcp_provider = RealMCPProvider(server_url=f"http://{self.host}:{self.port}")
                    await mcp_provider.start()
                    self.providers.append(mcp_provider)
                    provider_count += 1
                    print(f"   ✅ MCP provider ready")
                except Exception as e:
                    print(f"   ⚠️ MCP provider failed: {e}")
            
            if self.enable_ollama:
                print("🤖 Starting Ollama provider...")
                try:
                    ollama_provider = OllamaProvider(
                        provider_id="main_ollama_provider",
                        server_url=f"http://{self.host}:{self.port}"
                    )
                    await ollama_provider.start()
                    self.providers.append(ollama_provider)
                    provider_count += 1
                    models = len(ollama_provider.available_models)
                    print(f"   ✅ Ollama provider ready ({models} models)")
                except Exception as e:
                    print(f"   ⚠️ Ollama provider failed: {e}")
            
            if self.enable_web_search:
                print("🌐 Starting Web Search provider...")
                try:
                    web_search_provider = WebSearchProvider(
                        provider_id="main_web_search_provider",
                        server_url=f"http://{self.host}:{self.port}"
                    )
                    await web_search_provider.start()
                    self.providers.append(web_search_provider)
                    provider_count += 1
                    print(f"   ✅ Web Search provider ready")
                except Exception as e:
                    print(f"   ⚠️ Web Search provider failed: {e}")
            
            # 3. Start workflow engine
            print("⚙️ Starting workflow engine...")
            self.workflow_engine = WorkflowEngineClient(
                engine_id="main_workflow_engine",
                server_url=f"http://{self.host}:{self.port}"
            )
            await self.workflow_engine.start()
            print("   ✅ Workflow engine ready")
            
            self.running = True
            
            print("\n" + "=" * 50)
            print("✅ Gleitzeit V3 is ready!")
            print(f"   Server URL: http://{self.host}:{self.port}")
            print(f"   Providers: {provider_count} connected")
            print(f"   Functions available:")
            
            # Show available functions
            stats = self.server.get_stats()
            for provider_info in stats['provider_details']:
                print(f"     - {provider_info['name']}: {provider_info['status']}")
            
            print("\n📝 Usage examples:")
            print('   gleitzeit ask "What files are in the current directory?"')
            print('   gleitzeit ask "Write a haiku about distributed systems"')
            print('   gleitzeit ask "Analyze this image" --vision /path/to/image.png')
            print()
            
            if self.auto_open_browser:
                try:
                    webbrowser.open(f"http://{self.host}:{self.port}")
                except:
                    pass
            
        except Exception as e:
            logger.error(f"Failed to start V3 service: {e}")
            await self.stop()
            raise
    
    async def stop(self):
        """Stop the V3 service"""
        print("\n🛑 Stopping Gleitzeit V3 Service...")
        
        if self.workflow_engine:
            await self.workflow_engine.stop()
        
        for provider in self.providers:
            if hasattr(provider, '_running') and provider._running:
                await provider.stop()
        
        if self.server_task:
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass
        
        self.running = False
        print("✅ Service stopped")
    
    async def ask_task(self, question: str, function: str = None, image_path: str = None) -> str:
        """Execute a task and return the result"""
        if not self.running:
            raise RuntimeError("Service not running")
        
        # Determine function from question if not specified
        if not function:
            q_lower = question.lower()
            if image_path or any(word in q_lower for word in ['image', 'picture', 'photo', 'see', 'analyze', 'describe']):
                function = "vision"
            elif any(word in q_lower for word in ['list', 'file', 'directory', 'folder']):
                function = "list_files"
            elif any(word in q_lower for word in ['search', 'find', 'lookup', 'web', 'internet', 'google']):
                function = "web_search"
            else:
                function = "generate"
        
        # Build parameters
        if function == "vision":
            if not image_path:
                # Create a test image or use default
                image_path = "/tmp/gleitzeit_test_diagram.png"
            params = {
                "function": "vision",
                "prompt": question,
                "model": "llava:latest",
                "image_path": image_path
            }
        elif function == "list_files":
            params = {
                "function": "list_files", 
                "arguments": {"path": "."}
            }
        elif function == "web_search":
            params = {
                "function": "web_search",
                "query": question,
                "max_results": 5
            }
        else:
            params = {
                "function": "generate",
                "prompt": question,
                "model": "llama3.2:latest",
                "temperature": 0.7,
                "max_tokens": 500
            }
        
        # Create and execute task
        task = Task(
            name=question[:50],
            parameters=TaskParameters(data=params)
        )
        
        workflow = Workflow(
            name=f"Ask: {question[:30]}",
            description=question
        )
        workflow.add_task(task)
        
        # Submit and wait for result
        workflow_id = await self.workflow_engine.submit_workflow(workflow)
        
        # Wait for completion
        for _ in range(60):  # 60 second timeout
            await asyncio.sleep(1)
            
            if workflow_id in self.workflow_engine.workflows:
                wf = self.workflow_engine.workflows[workflow_id]
                if wf.status.value == "completed":
                    if task.id in wf.task_results:
                        return wf.task_results[task.id]
                    else:
                        return "Task completed but no result available"
                elif wf.status.value == "failed":
                    return f"Task failed: {wf.status.value}"
        
        return "Task timed out"
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        if not self.running or not self.server:
            return {"running": False}
        
        server_stats = self.server.get_stats()
        engine_stats = self.workflow_engine.get_stats() if self.workflow_engine else {}
        
        return {
            "running": True,
            "server": server_stats,
            "engine": engine_stats,
            "providers": len(self.providers)
        }


# Global service instance
_service: Optional[GleitzeitV3Service] = None


async def ensure_service_running(**kwargs):
    """Ensure the V3 service is running"""
    global _service
    
    if _service is None or not _service.running:
        _service = GleitzeitV3Service(**kwargs)
        await _service.start()
    
    return _service


# Command Handlers - New queue-based interface

async def run_command_handler(args):
    """Handle run command - process the queue continuously"""
    service = GleitzeitV3Service(
        host=args.host,
        port=args.port,
        enable_ollama=not args.no_ollama,
        enable_mcp=not args.no_mcp,
        enable_web_search=not args.no_web_search,
        log_level=args.log_level
    )
    
    try:
        await service.start()
        
        print("🔄 Running queue processor. Press Ctrl+C to stop.")
        print("Add tasks with: gleitzeit add \"task description\"")
        print()
        
        # Keep running and process queue
        while True:
            await asyncio.sleep(10)
            
            # Could add periodic queue status updates here
            # stats = service.get_stats()
            # print(f"Queue: {stats.get('queued', 0)} waiting")
    
    except KeyboardInterrupt:
        print("\nStopping queue processor...")
    finally:
        await service.stop()


async def add_command_handler(args):
    """Handle add command - add tasks to queue"""
    # Connect to existing server to add to queue
    import socketio
    
    sio = socketio.AsyncClient()
    connected = False
    
    try:
        await sio.connect(f"http://{args.host}:{args.port}")
        connected = True
        
        # Create task data
        task_data = {
            'name': args.description[:50],
            'description': args.description,
            'priority': args.priority,
            'parameters': {
                'function': args.function or _infer_function(args.description),
                'prompt': args.description if not args.function or args.function == 'generate' else None
            }
        }
        
        # Create simple workflow with one task
        workflow_data = {
            'name': f"Task: {args.description[:30]}",
            'description': args.description,
            'priority': args.priority,
            'tasks': [task_data]
        }
        
        # Set up response handler
        response_received = asyncio.Event()
        response_data = {}
        
        @sio.on('workflow:queued')
        async def workflow_queued(data):
            response_data.update(data)
            response_received.set()
        
        # Submit to queue
        await sio.emit('workflow:submit', {'workflow': workflow_data})
        
        # Wait for confirmation
        try:
            await asyncio.wait_for(response_received.wait(), timeout=10)
            confirmation = response_data
        except asyncio.TimeoutError:
            confirmation = {}
        
        print(f"✅ Task added to queue")
        print(f"   Description: {args.description}")
        print(f"   Priority: {args.priority}")
        if 'queue_position' in confirmation:
            print(f"   Queue position: {confirmation['queue_position']}")
        
    except Exception as e:
        print(f"❌ Failed to add task: {e}")
        print("Make sure the server is running with: gleitzeit run")
        sys.exit(1)
    
    finally:
        if connected:
            await sio.disconnect()


async def queue_command_handler(args):
    """Handle queue command - show queue status"""
    import socketio
    
    sio = socketio.AsyncClient()
    connected = False
    
    try:
        await sio.connect(f"http://{args.host}:{args.port}")
        connected = True
        
        if args.stats:
            # Get queue statistics - use emit and wait for response
            response_received = asyncio.Event()
            response_data = {}
            
            @sio.on('queue:stats_response')
            async def stats_response(data):
                response_data.update(data)
                response_received.set()
            
            await sio.emit('queue:stats', {})
            await asyncio.wait_for(response_received.wait(), timeout=10)
            response = response_data
            
            print("📊 Queue Statistics")
            print("=" * 30)
            print(f"Queued: {response.get('queued', 0)}")
            print(f"Active: {response.get('active', 0)}")
            print(f"Completed: {response.get('completed', 0)}")
            
            if response.get('queue_by_priority'):
                print("\nBy Priority:")
                for priority, count in response['queue_by_priority'].items():
                    print(f"  {priority}: {count}")
        
        else:
            # List queue contents - use emit and wait for response
            response_received = asyncio.Event()
            response_data = {}
            
            @sio.on('queue:list_response')
            async def list_response(data):
                response_data.update(data)
                response_received.set()
            
            await sio.emit('queue:list', {
                'limit': args.limit,
                'include_completed': args.completed
            })
            await asyncio.wait_for(response_received.wait(), timeout=10)
            response = response_data
            
            workflows = response.get('workflows', [])
            
            print("📋 Workflow Queue")
            print("=" * 50)
            
            if not workflows:
                print("Queue is empty")
            else:
                for workflow in workflows:
                    status_icon = {
                        'queued': '⏳',
                        'running': '▶️',
                        'completed': '✅',
                        'failed': '❌'
                    }.get(workflow.get('status'), '❓')
                    
                    print(f"{status_icon} {workflow.get('name', 'Unknown')}")
                    print(f"   Status: {workflow.get('status')}")
                    print(f"   Priority: {workflow.get('priority')}")
                    print(f"   Tasks: {workflow.get('task_count', 0)}")
                    if workflow.get('completed_tasks'):
                        print(f"   Progress: {workflow['completed_tasks']}/{workflow['task_count']} tasks")
                    
                    # Show task results if available
                    if workflow.get('task_results'):
                        print(f"   📄 Results:")
                        for task_id, result in workflow['task_results'].items():
                            if isinstance(result, str):
                                # Limit result display to first 200 chars
                                display_result = result[:200] + "..." if len(result) > 200 else result
                                print(f"      {display_result}")
                            else:
                                print(f"      {str(result)[:200]}...")
                    print()
            
            print(f"Total - Queued: {response.get('total_queued', 0)}, "
                  f"Active: {response.get('total_active', 0)}, "
                  f"Completed: {response.get('total_completed', 0)}")
    
    except Exception as e:
        print(f"❌ Failed to get queue info: {e}")
        print("Make sure the server is running with: gleitzeit run")
        sys.exit(1)
    
    finally:
        if connected:
            await sio.disconnect()


def _infer_function(description: str) -> str:
    """Infer function type from task description"""
    desc_lower = description.lower()
    
    if any(word in desc_lower for word in ['list', 'file', 'directory', 'folder']):
        return 'list_files'
    elif any(word in desc_lower for word in ['image', 'picture', 'photo', 'vision', 'see', 'analyze']):
        return 'vision'
    elif any(word in desc_lower for word in ['search', 'find', 'lookup', 'web', 'internet', 'google']):
        return 'web_search'
    else:
        return 'generate'


async def serve_command_handler(args):
    """Handle serve command - start the service"""
    service = GleitzeitV3Service(
        host=args.host,
        port=args.port,
        enable_ollama=not args.no_ollama,
        enable_mcp=not args.no_mcp,
        auto_open_browser=args.open_browser,
        log_level=args.log_level
    )
    
    try:
        await service.start()
        
        # Keep running until interrupted
        print("Service running. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(10)
    
    except KeyboardInterrupt:
        print("\nShutdown requested...")
    finally:
        await service.stop()


async def ask_command_handler(args):
    """Handle ask command - quick task execution"""
    service = await ensure_service_running(
        host=args.host,
        port=args.port,
        log_level=args.log_level
    )
    
    try:
        print(f"🤔 Processing: {args.question}")
        result = await service.ask_task(
            args.question, 
            function=args.function,
            image_path=args.image
        )
        
        print("\n📊 Result:")
        if isinstance(result, str):
            print(result)
        else:
            print(json.dumps(result, indent=2))
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


async def status_command_handler(args):
    """Handle status command"""
    try:
        service = await ensure_service_running(host=args.host, port=args.port)
        stats = service.get_stats()
        
        print("📊 Gleitzeit V3 Status")
        print("=" * 30)
        print(f"Running: {'✅' if stats['running'] else '❌'}")
        
        if stats['running']:
            server_stats = stats['server']
            print(f"Providers: {server_stats['providers']}")
            print(f"Workflow Engines: {server_stats['workflow_engines']}")
            print(f"Total Connections: {server_stats['total_connections']}")
            
            if server_stats['provider_details']:
                print("\nProviders:")
                for provider in server_stats['provider_details']:
                    status_icon = "✅" if provider['status'] == 'available' else "⚠️"
                    print(f"  {status_icon} {provider['name']}: {provider['status']}")
        
    except Exception as e:
        print(f"❌ Could not get status: {e}")
        sys.exit(1)


def add_run_parser(subparsers):
    """Add run command parser - main entry point"""
    run_parser = subparsers.add_parser('run', help='Start queue processor (main entry point)')
    run_parser.add_argument('--host', default='localhost', help='Host to bind to')
    run_parser.add_argument('--port', type=int, default=8000, help='Port to bind to')
    run_parser.add_argument('--no-ollama', action='store_true', help='Disable Ollama provider')
    run_parser.add_argument('--no-mcp', action='store_true', help='Disable MCP provider')
    run_parser.add_argument('--no-web-search', action='store_true', help='Disable Web Search provider')
    run_parser.set_defaults(func=run_command_handler)


def add_add_parser(subparsers):
    """Add add command parser - add tasks to queue"""
    add_parser = subparsers.add_parser('add', help='Add a task to the queue')
    add_parser.add_argument('description', help='Task description')
    add_parser.add_argument('--priority', choices=['low', 'normal', 'high', 'urgent'], 
                           default='normal', help='Task priority')
    add_parser.add_argument('--function', choices=['generate', 'list_files', 'vision', 'web_search', 'url_fetch', 'web_summarize'],
                           help='Specific function to use')
    add_parser.add_argument('--host', default='localhost', help='Server host')
    add_parser.add_argument('--port', type=int, default=8000, help='Server port')
    add_parser.set_defaults(func=add_command_handler)


def add_queue_parser(subparsers):
    """Add queue command parser - queue management"""
    queue_parser = subparsers.add_parser('queue', help='Show queue status')
    queue_parser.add_argument('--stats', action='store_true', help='Show statistics instead of list')
    queue_parser.add_argument('--completed', action='store_true', help='Include completed items')
    queue_parser.add_argument('--limit', type=int, default=20, help='Limit number of items shown')
    queue_parser.add_argument('--host', default='localhost', help='Server host')
    queue_parser.add_argument('--port', type=int, default=8000, help='Server port')
    queue_parser.set_defaults(func=queue_command_handler)


def add_serve_parser(subparsers):
    """Add serve command parser"""
    serve_parser = subparsers.add_parser('serve', help='Start Gleitzeit V3 service')
    serve_parser.add_argument('--host', default='localhost', help='Host to bind to')
    serve_parser.add_argument('--port', type=int, default=8000, help='Port to bind to')
    serve_parser.add_argument('--no-ollama', action='store_true', help='Disable Ollama provider')
    serve_parser.add_argument('--no-mcp', action='store_true', help='Disable MCP provider')
    serve_parser.add_argument('--open-browser', action='store_true', help='Open browser')
    serve_parser.set_defaults(func=serve_command_handler)


def add_ask_parser(subparsers):
    """Add ask command parser"""
    ask_parser = subparsers.add_parser('ask', help='Ask a question or run a task')
    ask_parser.add_argument('question', help='Question or task description')
    ask_parser.add_argument('--function', choices=['generate', 'list_files', 'vision'],
                           help='Specific function to use')
    ask_parser.add_argument('--image', help='Image path for vision tasks')
    ask_parser.add_argument('--host', default='localhost', help='Server host')
    ask_parser.add_argument('--port', type=int, default=8000, help='Server port')
    ask_parser.set_defaults(func=ask_command_handler)


def add_status_parser(subparsers):
    """Add status command parser"""
    status_parser = subparsers.add_parser('status', help='Show system status')
    status_parser.add_argument('--host', default='localhost', help='Server host')
    status_parser.add_argument('--port', type=int, default=8000, help='Server port')
    status_parser.set_defaults(func=status_command_handler)


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description='Gleitzeit V3 - Distributed Task Execution')
    
    # Global options
    parser.add_argument('--log-level', default='INFO', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Set logging level')
    
    # Commands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Add command parsers
    add_run_parser(subparsers)      # Main entry point
    add_add_parser(subparsers)      # Add tasks to queue
    add_queue_parser(subparsers)    # Queue management
    add_serve_parser(subparsers)    # Direct service start (legacy)
    add_ask_parser(subparsers)      # Quick ask (legacy)
    add_status_parser(subparsers)   # Status check
    
    # Legacy compatibility 
    dev_parser = subparsers.add_parser('dev', help='Start development environment (V3)')
    dev_parser.add_argument('--host', default='localhost')
    dev_parser.add_argument('--port', type=int, default=8000)
    dev_parser.add_argument('--no-ollama', action='store_true', help='Disable Ollama')
    dev_parser.add_argument('--no-mcp', action='store_true', help='Disable MCP')
    dev_parser.set_defaults(func=run_command_handler)  # Point to run instead of serve
    
    args = parser.parse_args()
    
    if not args.command:
        # Default to run (queue processor)
        args.command = 'run'
        args.func = run_command_handler
        args.host = 'localhost'
        args.port = 8000
        args.no_ollama = False
        args.no_mcp = False
    
    # Run the command
    try:
        asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Command failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()