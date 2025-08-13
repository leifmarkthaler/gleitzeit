#!/usr/bin/env python3
"""
Modular CLI for Gleitzeit V3

This is a new, modular CLI that automatically discovers and manages providers
without requiring code changes for each new provider.
"""

import argparse
import asyncio
import logging
import signal
import sys
import json
from typing import Optional, Dict, Any, List
from pathlib import Path

from .server.central_server import CentralServer
from .core.workflow_engine_client import WorkflowEngineClient
from .core.models import Workflow, Task, TaskParameters
from .providers.registry import get_registry, discover_providers
from .providers.config import get_config

logger = logging.getLogger(__name__)


class ModularGleitzeitService:
    """
    Modular Gleitzeit V3 Service with automatic provider discovery.
    
    Features:
    - Automatic provider discovery and registration
    - Configuration-based provider management
    - Extensible without code changes
    - Backwards compatible with existing functionality
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        config_path: Optional[str] = None,
        log_level: str = "INFO"
    ):
        self.host = host
        self.port = port
        self.log_level = log_level
        
        # Configuration management
        self.config = get_config(config_path)
        self.registry = get_registry()
        
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
        """Start the modular Gleitzeit service."""
        print("🚀 Starting Gleitzeit V3 Service (Modular)")
        print("=" * 50)
        print(f"   Architecture: Modular Event-Driven")
        print(f"   Host: {self.host}")
        print(f"   Port: {self.port}")
        print()
        
        try:
            # 1. Discover available providers
            print("🔍 Discovering providers...")
            discover_providers()
            available_providers = self.registry.list_providers()
            print(f"   Available providers: {', '.join(available_providers)}")
            print()
            
            # 2. Start central server
            print("📡 Starting central server...")
            self.server = CentralServer(host=self.host, port=self.port)
            self.server_task = asyncio.create_task(self.server.start())
            await asyncio.sleep(2)
            print("   ✅ Central server running")
            
            # 3. Start enabled providers automatically
            provider_count = await self._start_providers()
            
            # 4. Start workflow engine
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
            
            # Show enabled provider functions
            await self._show_available_functions()
            
            print("\n📝 Usage examples:")
            print('   gleitzeit-modular add "Write a haiku about modular systems"')
            print('   gleitzeit-modular add "Search for Python tutorials"')
            print('   gleitzeit-modular queue --stats')
            print()
            
        except Exception as e:
            logger.error(f"Failed to start modular service: {e}")
            await self.stop()
            raise
    
    async def _start_providers(self) -> int:
        """Start all enabled providers automatically."""
        print("🔧 Starting providers...")
        provider_count = 0
        
        # Get all available providers
        available_providers = self.registry.list_providers()
        
        for provider_type in available_providers:
            if self.config.is_provider_enabled(provider_type):
                await self._start_provider(provider_type)
                provider_count += 1
            else:
                print(f"   ⏸️ {provider_type} provider disabled in config")
        
        if provider_count == 0:
            print("   ⚠️ No providers enabled. Enable providers in config or use command line flags.")
        
        return provider_count
    
    async def _start_provider(self, provider_type: str) -> bool:
        """
        Start a specific provider.
        
        Args:
            provider_type: Type of provider to start
            
        Returns:
            True if started successfully, False otherwise
        """
        try:
            # Get provider configuration
            provider_config = self.config.get_provider_config(provider_type)
            
            # Create provider instance
            provider_id = f"main_{provider_type}_provider"
            provider = self.registry.create_provider(
                provider_type=provider_type,
                provider_id=provider_id,
                server_url=f"http://{self.host}:{self.port}",
                config=provider_config
            )
            
            if provider is None:
                print(f"   ❌ Failed to create {provider_type} provider")
                return False
            
            # Start the provider
            await provider.start()
            self.providers.append(provider)
            
            # Get provider info for display
            provider_info = self.registry.get_provider_info(provider_type)
            functions = provider_info.get('supported_functions', ['unknown']) if provider_info else ['unknown']
            function_count = len([f for f in functions if f != 'unknown'])
            
            print(f"   ✅ {provider_type} provider ready ({function_count} functions)")
            return True
            
        except Exception as e:
            print(f"   ⚠️ {provider_type} provider failed: {e}")
            logger.debug(f"Provider {provider_type} startup error:", exc_info=True)
            return False
    
    async def _show_available_functions(self):
        """Display available functions from all providers."""
        print("\n🔧 Available functions:")
        
        stats = self.server.get_stats()
        if stats['provider_details']:
            for provider_info in stats['provider_details']:
                print(f"     - {provider_info['name']}: {provider_info['status']}")
        else:
            print("     No providers currently connected")
    
    async def stop(self):
        """Stop the modular service."""
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


class ModularCLI:
    """Modular command line interface."""
    
    def __init__(self):
        self.service: Optional[ModularGleitzeitService] = None
    
    async def run_command(self, args):
        """Start the service and process queue continuously."""
        self.service = ModularGleitzeitService(
            host=args.host,
            port=args.port,
            config_path=getattr(args, 'config', None),
            log_level=args.log_level
        )
        
        try:
            await self.service.start()
            
            print("🔄 Running queue processor. Press Ctrl+C to stop.")
            print("Add tasks with: gleitzeit-modular add \"task description\"")
            print()
            
            # Keep running and process queue
            while True:
                await asyncio.sleep(10)
        
        except KeyboardInterrupt:
            print("\nStopping queue processor...")
        finally:
            if self.service:
                await self.service.stop()
    
    async def providers_command(self, args):
        """Manage providers."""
        config = get_config(getattr(args, 'config', None))
        
        if args.action == 'list':
            # Discover and list all providers
            discover_providers()
            registry = get_registry()
            
            print("📦 Available Providers")
            print("=" * 50)
            
            for provider_type in registry.list_providers():
                enabled = "✅" if config.is_provider_enabled(provider_type) else "❌"
                provider_info = registry.get_provider_info(provider_type)
                
                print(f"{enabled} {provider_type}")
                if provider_info:
                    print(f"    Class: {provider_info['class_name']}")
                    print(f"    Functions: {', '.join(provider_info['supported_functions'])}")
                    if provider_info.get('doc'):
                        # First line of docstring
                        doc_line = provider_info['doc'].split('\\n')[0].strip()
                        if doc_line:
                            print(f"    Description: {doc_line}")
                print()
        
        elif args.action == 'enable':
            config.set_provider_enabled(args.provider_type, True)
            config.save_config()
            print(f"✅ Enabled {args.provider_type} provider")
        
        elif args.action == 'disable':
            config.set_provider_enabled(args.provider_type, False)
            config.save_config()
            print(f"❌ Disabled {args.provider_type} provider")
        
        elif args.action == 'config':
            if args.provider_type:
                # Show specific provider config
                provider_config = config.get_provider_config(args.provider_type)
                print(f"Configuration for {args.provider_type}:")
                print(json.dumps(provider_config, indent=2))
            else:
                # Show all config
                print("All Provider Configuration:")
                print(json.dumps(config.get_all_provider_configs(), indent=2))
    
    async def config_command(self, args):
        """Manage configuration."""
        config = get_config(args.config)
        
        if args.action == 'init':
            config.create_default_config_file()
        elif args.action == 'show':
            print(f"Configuration file: {config.config_path}")
            print("Current configuration:")
            print(json.dumps(config.config, indent=2))
        elif args.action == 'edit':
            import subprocess
            editor = os.environ.get('EDITOR', 'nano')
            subprocess.call([editor, config.config_path])


def create_parser():
    """Create the modular CLI argument parser."""
    parser = argparse.ArgumentParser(description='Gleitzeit V3 - Modular Distributed Task Execution')
    
    # Global options
    parser.add_argument('--log-level', default='INFO', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Set logging level')
    parser.add_argument('--config', help='Path to configuration file')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Run command (main entry point)
    run_parser = subparsers.add_parser('run', help='Start queue processor (main entry point)')
    run_parser.add_argument('--host', default='localhost', help='Host to bind to')
    run_parser.add_argument('--port', type=int, default=8000, help='Port to bind to')
    
    # Provider management
    providers_parser = subparsers.add_parser('providers', help='Manage providers')
    providers_subparsers = providers_parser.add_subparsers(dest='action')
    
    # List providers
    providers_subparsers.add_parser('list', help='List all available providers')
    
    # Enable/disable providers
    enable_parser = providers_subparsers.add_parser('enable', help='Enable a provider')
    enable_parser.add_argument('provider_type', help='Provider type to enable')
    
    disable_parser = providers_subparsers.add_parser('disable', help='Disable a provider')
    disable_parser.add_argument('provider_type', help='Provider type to disable')
    
    # Provider configuration
    config_parser = providers_subparsers.add_parser('config', help='Show provider configuration')
    config_parser.add_argument('provider_type', nargs='?', help='Specific provider type (optional)')
    
    # Configuration management
    config_parser = subparsers.add_parser('config', help='Manage configuration')
    config_subparsers = config_parser.add_subparsers(dest='action')
    config_subparsers.add_parser('init', help='Create default configuration file')
    config_subparsers.add_parser('show', help='Show current configuration')
    config_subparsers.add_parser('edit', help='Edit configuration file')
    
    # Add/queue commands (reuse from existing CLI with minor modifications)
    add_parser = subparsers.add_parser('add', help='Add a task to the queue')
    add_parser.add_argument('description', help='Task description')
    add_parser.add_argument('--priority', choices=['low', 'normal', 'high', 'urgent'], 
                           default='normal', help='Task priority')
    add_parser.add_argument('--function', help='Specific function to use (auto-detected if not specified)')
    add_parser.add_argument('--host', default='localhost', help='Server host')
    add_parser.add_argument('--port', type=int, default=8000, help='Server port')
    
    queue_parser = subparsers.add_parser('queue', help='Show queue status')
    queue_parser.add_argument('--stats', action='store_true', help='Show statistics instead of list')
    queue_parser.add_argument('--completed', action='store_true', help='Include completed items')
    queue_parser.add_argument('--limit', type=int, default=20, help='Limit number of items shown')
    queue_parser.add_argument('--host', default='localhost', help='Server host')
    queue_parser.add_argument('--port', type=int, default=8000, help='Server port')
    
    return parser


async def main():
    """Main modular CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        # Default to run command
        args.command = 'run'
        args.host = 'localhost'
        args.port = 8000
    
    cli = ModularCLI()
    
    try:
        if args.command == 'run':
            await cli.run_command(args)
        elif args.command == 'providers':
            await cli.providers_command(args)
        elif args.command == 'config':
            await cli.config_command(args)
        elif args.command == 'add':
            # Import and use existing add handler (would need minor adaptation)
            from .cli import add_command_handler
            await add_command_handler(args)
        elif args.command == 'queue':
            # Import and use existing queue handler (would need minor adaptation)  
            from .cli import queue_command_handler
            await queue_command_handler(args)
        else:
            parser.print_help()
            
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Command failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())