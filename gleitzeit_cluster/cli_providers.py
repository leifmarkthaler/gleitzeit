#!/usr/bin/env python3
"""
Gleitzeit CLI - Provider Management

Commands for managing Socket.IO providers (LLM, tools, extensions)
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from .core.errors import GleitzeitError
from .communication.provider_client import ProviderSocketClient
from .communication.service_discovery import get_socketio_url


logger = logging.getLogger(__name__)


async def providers_command_handler(args) -> None:
    """Handle provider management commands"""
    
    if args.provider_command == 'list':
        await list_providers(args)
    elif args.provider_command == 'status':
        await provider_status(args)
    elif args.provider_command == 'models':
        await list_models(args)
    elif args.provider_command == 'capabilities':
        await list_capabilities(args)
    elif args.provider_command == 'health':
        await provider_health(args)
    elif args.provider_command == 'invoke':
        await invoke_provider(args)
    else:
        print(f"Unknown provider command: {args.provider_command}")
        return


async def list_providers(args) -> None:
    """List all connected providers"""
    
    try:
        # Use service discovery if no explicit URL provided
        socketio_url = getattr(args, 'socketio_url', None) or get_socketio_url()
        async with ProviderSocketClient(socketio_url) as client:
            # Get all providers
            providers = await client.get_all_providers()
            
            if not providers:
                print("📭 No providers connected")
                return
            
            print(f"📡 Connected Providers ({len(providers)}):")
            print("=" * 60)
            
            for name, info in providers.items():
                status_icon = "🟢" if info.get('connected') else "🔴"
                provider_type = info.get('type', 'unknown').upper()
                
                print(f"\n{status_icon} {name} ({provider_type})")
                print(f"   Description: {info.get('description', 'No description')}")
                
                models = info.get('models', [])
                if models:
                    model_list = ', '.join(models[:3])
                    if len(models) > 3:
                        model_list += f" (+{len(models) - 3} more)"
                    print(f"   Models: {model_list}")
                
                capabilities = info.get('capabilities', [])
                if capabilities:
                    cap_list = ', '.join(capabilities[:5])
                    if len(capabilities) > 5:
                        cap_list += f" (+{len(capabilities) - 5} more)"
                    print(f"   Capabilities: {cap_list}")
                
                print(f"   Connected: {'✅ Yes' if info.get('connected') else '❌ No'}")
                
    except ConnectionError as e:
        print(f"❌ Connection error: {e}")
        print("💡 Make sure the server is running with provider support.")
        print("   Start with: python examples/socketio_provider_demo.py")
    except Exception as e:
        logger.error(f"Failed to list providers: {e}")
        print(f"❌ Error listing providers: {e}")


async def provider_status(args) -> None:
    """Get detailed status of a specific provider"""
    
    if not args.name:
        print("❌ Provider name required for status command")
        return
    
    try:
        # Use service discovery if no explicit URL provided
        socketio_url = getattr(args, 'socketio_url', None) or get_socketio_url()
        async with ProviderSocketClient(socketio_url) as client:
            # Get all providers to find the specific one
            providers = await client.get_all_providers()
            
            if args.name not in providers:
                print(f"❌ Provider '{args.name}' not found")
                print(f"💡 Available providers: {', '.join(providers.keys()) if providers else 'None'}")
                return
            
            provider_info = providers[args.name]
            
            print(f"📊 Provider Status: {args.name}")
            print("=" * 50)
            
            # Basic info
            status_icon = "🟢" if provider_info.get('connected') else "🔴"
            print(f"Status: {status_icon} {'Connected' if provider_info.get('connected') else 'Disconnected'}")
            print(f"Type: {provider_info.get('type', 'unknown').upper()}")
            print(f"Description: {provider_info.get('description', 'No description')}")
            
            # Models
            models = provider_info.get('models', [])
            if models:
                print(f"\n🤖 Models ({len(models)}):")
                for model in sorted(models):
                    print(f"  • {model}")
            
            # Capabilities
            capabilities = provider_info.get('capabilities', [])
            if capabilities:
                print(f"\n⚡ Capabilities ({len(capabilities)}):")
                for capability in sorted(capabilities):
                    print(f"  • {capability}")
            
            # Try to get tools if available
            try:
                tools = await client.get_provider_tools(args.name)
                if tools:
                    print(f"\n🔧 Tools ({len(tools)}):")
                    for tool in tools[:5]:  # Show first 5
                        tool_name = tool.get('name', 'unknown')
                        tool_desc = tool.get('description', 'No description')
                        print(f"  • {tool_name}: {tool_desc}")
                    if len(tools) > 5:
                        print(f"  ... and {len(tools) - 5} more")
            except Exception:
                # Tools not available for this provider
                pass
                
    except ConnectionError as e:
        print(f"❌ Connection error: {e}")
        print("💡 Make sure the server is running with provider support.")
        print("   Start with: python examples/socketio_provider_demo.py")
    except Exception as e:
        logger.error(f"Failed to get provider status: {e}")
        print(f"❌ Error getting provider status: {e}")


async def list_models(args) -> None:
    """List all available models from all providers"""
    
    try:
        # Use service discovery if no explicit URL provided
        socketio_url = getattr(args, 'socketio_url', None) or get_socketio_url()
        async with ProviderSocketClient(socketio_url) as client:
            models = await client.get_all_models()
            
            if not models:
                print("📭 No models available")
                return
            
            print(f"🤖 Available Models ({len(models)}):")
            print("=" * 50)
            
            # Group by provider
            by_provider = {}
            for model, provider_name in models.items():
                if provider_name not in by_provider:
                    by_provider[provider_name] = []
                by_provider[provider_name].append(model)
            
            for provider_name, provider_models in sorted(by_provider.items()):
                print(f"\n📡 {provider_name}:")
                for model in sorted(provider_models):
                    print(f"  • {model}")
                    
    except ConnectionError as e:
        print(f"❌ Connection error: {e}")
        print("💡 Make sure the server is running with provider support.")
        print("   Start with: python examples/socketio_provider_demo.py")
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        print(f"❌ Error listing models: {e}")


async def list_capabilities(args) -> None:
    """List all available capabilities"""
    
    try:
        # Use service discovery if no explicit URL provided
        socketio_url = getattr(args, 'socketio_url', None) or get_socketio_url()
        async with ProviderSocketClient(socketio_url) as client:
            capabilities = await client.get_all_capabilities()
            
            if not capabilities:
                print("📭 No capabilities available")
                return
            
            print(f"⚡ Available Capabilities ({len(capabilities)}):")
            print("=" * 50)
            
            for capability in sorted(capabilities):
                try:
                    # Get providers for this capability
                    providers = await client.get_providers_by_capability(capability)
                    provider_names = [p.get('name', 'unknown') for p in providers]
                    
                    if provider_names:
                        providers_str = f" ({', '.join(provider_names)})"
                    else:
                        providers_str = ""
                    
                    print(f"  • {capability}{providers_str}")
                    
                except Exception as e:
                    # If we can't get providers for this capability, still show it
                    print(f"  • {capability}")
                    logger.debug(f"Failed to get providers for capability {capability}: {e}")
                    
    except ConnectionError as e:
        print(f"❌ Connection error: {e}")
        print("💡 Make sure the server is running with provider support.")
        print("   Start with: python examples/socketio_provider_demo.py")
    except Exception as e:
        logger.error(f"Failed to list capabilities: {e}")
        print(f"❌ Error listing capabilities: {e}")


async def provider_health(args) -> None:
    """Check health of all providers or specific provider"""
    
    try:
        # Use service discovery if no explicit URL provided
        socketio_url = getattr(args, 'socketio_url', None) or get_socketio_url()
        async with ProviderSocketClient(socketio_url) as client:
            if args.name:
                # Check specific provider health
                print(f"🏥 Health Check: {args.name}")
                print("=" * 40)
                
                # Get provider info first
                providers = await client.get_all_providers()
                if args.name not in providers:
                    print(f"❌ Provider '{args.name}' not found")
                    return
                
                provider_info = providers[args.name]
                connected = provider_info.get('connected', False)
                
                if connected:
                    print(f"✅ {args.name}: Connected and healthy")
                    
                    # Try to get additional health info by calling a simple method
                    try:
                        models = await client.get_all_models()
                        provider_models = [m for m, p in models.items() if p == args.name]
                        if provider_models:
                            print(f"🤖 Available models: {len(provider_models)}")
                            print(f"   {', '.join(provider_models[:3])}{'...' if len(provider_models) > 3 else ''}")
                        
                        print(f"🔄 Response time: OK")
                        print(f"📊 Status: Operational")
                    except Exception as e:
                        print(f"⚠️  Warning: Provider connected but not fully responsive: {e}")
                else:
                    print(f"❌ {args.name}: Disconnected or unhealthy")
                    
            else:
                # Check all providers health
                print("🏥 Health Check Summary:")
                print("=" * 50)
                
                providers = await client.get_all_providers()
                
                if not providers:
                    print("📭 No providers connected")
                    return
                
                healthy_count = 0
                total_count = len(providers)
                
                for name, info in providers.items():
                    connected = info.get('connected', False)
                    status_icon = "✅" if connected else "❌"
                    status_text = "Healthy" if connected else "Unhealthy"
                    
                    if connected:
                        healthy_count += 1
                    
                    provider_type = info.get('type', 'unknown').upper()
                    model_count = len(info.get('models', []))
                    
                    print(f"{status_icon} {name} ({provider_type}): {status_text}")
                    if connected:
                        print(f"   Models: {model_count}, Capabilities: {len(info.get('capabilities', []))}")
                
                # Summary
                print(f"\n📊 Overall Health: {healthy_count}/{total_count} providers healthy")
                if healthy_count == total_count:
                    print("🎉 All providers are operational!")
                elif healthy_count == 0:
                    print("🚨 All providers are down!")
                else:
                    print(f"⚠️  {total_count - healthy_count} provider(s) need attention")
                    
    except ConnectionError as e:
        print(f"❌ Connection error: {e}")
        print("💡 Make sure the server is running with provider support.")
        print("   Start with: python examples/socketio_provider_demo.py")
    except Exception as e:
        logger.error(f"Failed to check provider health: {e}")
        print(f"❌ Error checking provider health: {e}")


async def invoke_provider(args) -> None:
    """Invoke a method on a provider"""
    
    if not args.name:
        print("❌ Provider name required for invoke command")
        return
    
    if not args.method:
        print("❌ Method name required for invoke command")
        return
    
    print(f"🔄 Invoking: {args.method} on {args.name}")
    print("=" * 50)
    
    try:
        # Use service discovery if no explicit URL provided
        socketio_url = getattr(args, 'socketio_url', None) or get_socketio_url()
        async with ProviderSocketClient(socketio_url) as client:
            # Verify provider exists
            providers = await client.get_all_providers()
            if args.name not in providers:
                print(f"❌ Provider '{args.name}' not found")
                print(f"💡 Available providers: {', '.join(providers.keys()) if providers else 'None'}")
                return
            
            # Parse arguments
            method_args = {}
            if args.args:
                try:
                    method_args = json.loads(args.args)
                    if not isinstance(method_args, dict):
                        print("❌ Arguments must be a JSON object (dictionary)")
                        return
                except json.JSONDecodeError as e:
                    print(f"❌ Invalid JSON in arguments: {e}")
                    return
            
            print(f"📤 Method: {args.method}")
            print(f"📦 Arguments: {json.dumps(method_args, indent=2) if method_args else 'None'}")
            print(f"⏱️  Timeout: {args.timeout}s")
            print()
            
            # Invoke the method
            print("🚀 Invoking method...")
            start_time = datetime.now()
            
            try:
                result = await client.invoke_provider(
                    provider_name=args.name,
                    method=args.method,
                    arguments=method_args,
                    timeout=args.timeout
                )
                
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                print(f"✅ Invocation successful! (took {duration:.2f}s)")
                print("\n📥 Result:")
                print("=" * 30)
                
                if args.format == 'json':
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    # Pretty print for text format
                    if isinstance(result, dict):
                        for key, value in result.items():
                            if isinstance(value, (str, int, float, bool)):
                                print(f"{key}: {value}")
                            else:
                                print(f"{key}: {json.dumps(value, ensure_ascii=False)}")
                    elif isinstance(result, list):
                        for i, item in enumerate(result):
                            print(f"[{i}]: {item}")
                    else:
                        print(str(result))
                        
            except Exception as invoke_error:
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                print(f"❌ Invocation failed after {duration:.2f}s")
                print(f"Error: {invoke_error}")
                
                # Try to provide helpful suggestions
                if "timeout" in str(invoke_error).lower():
                    print(f"💡 Try increasing timeout with --timeout {args.timeout + 30}")
                elif "method" in str(invoke_error).lower():
                    print(f"💡 Check if method '{args.method}' is supported by provider '{args.name}'")
                    
                    # Try to get available tools/methods
                    try:
                        tools = await client.get_provider_tools(args.name)
                        if tools:
                            print(f"Available methods: {', '.join([t.get('name', 'unknown') for t in tools[:5]])}")
                    except:
                        pass
                        
    except ConnectionError as e:
        print(f"❌ Connection error: {e}")
        print("💡 Make sure the server is running with provider support.")
        print("   Start with: python examples/socketio_provider_demo.py")
    except Exception as e:
        logger.error(f"Failed to invoke provider: {e}")
        print(f"❌ Error invoking provider: {e}")


def add_providers_parser(subparsers):
    """Add provider management commands to CLI"""
    
    providers = subparsers.add_parser(
        'providers', 
        help='Manage Socket.IO providers (LLM, tools, extensions)'
    )
    
    provider_subparsers = providers.add_subparsers(
        dest='provider_command',
        help='Provider commands'
    )
    
    # List providers
    list_cmd = provider_subparsers.add_parser(
        'list',
        help='List all connected providers'
    )
    list_cmd.add_argument('--socketio-url', default='http://localhost:8000',
                         help='Socket.IO server URL')
    
    # Provider status
    status_cmd = provider_subparsers.add_parser(
        'status',
        help='Get detailed status of a specific provider'
    )
    status_cmd.add_argument('name', help='Provider name')
    status_cmd.add_argument('--socketio-url', default='http://localhost:8000',
                           help='Socket.IO server URL')
    status_cmd.add_argument('-v', '--verbose', action='store_true',
                           help='Show detailed information')
    
    # List models
    models_cmd = provider_subparsers.add_parser(
        'models',
        help='List all available models'
    )
    models_cmd.add_argument('--socketio-url', default='http://localhost:8000',
                           help='Socket.IO server URL')
    
    # List capabilities
    capabilities_cmd = provider_subparsers.add_parser(
        'capabilities',
        help='List all available capabilities'
    )
    capabilities_cmd.add_argument('--socketio-url', default='http://localhost:8000',
                                 help='Socket.IO server URL')
    
    # Provider health
    health_cmd = provider_subparsers.add_parser(
        'health',
        help='Check provider health'
    )
    health_cmd.add_argument('name', nargs='?', help='Provider name (optional)')
    health_cmd.add_argument('--socketio-url', default='http://localhost:8000',
                           help='Socket.IO server URL')
    
    # Invoke provider
    invoke_cmd = provider_subparsers.add_parser(
        'invoke',
        help='Invoke a method on a provider'
    )
    invoke_cmd.add_argument('name', help='Provider name')
    invoke_cmd.add_argument('method', help='Method name')
    invoke_cmd.add_argument('--args', help='Method arguments as JSON string')
    invoke_cmd.add_argument('--timeout', type=int, default=30,
                           help='Timeout in seconds')
    invoke_cmd.add_argument('--format', choices=['json', 'text'], default='text',
                           help='Output format')
    invoke_cmd.add_argument('--socketio-url', default='http://localhost:8000',
                           help='Socket.IO server URL')