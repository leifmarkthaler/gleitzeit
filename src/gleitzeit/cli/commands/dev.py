"""
Dev Commands - Local development environment management
"""

import click
import asyncio
import subprocess
import signal
import os
import json
from pathlib import Path
from typing import Optional

from gleitzeit.cli.client import GleitzeitClient
from gleitzeit.server.central_server import CentralServer
from gleitzeit.core.errors import SystemError

# Store process info for cleanup
_local_processes = {}

async def start_local(ctx: click.Context, port: int, redis: bool) -> None:
    """Start local development environment"""
    config = ctx.obj['config']
    
    click.echo("🚀 Starting Gleitzeit local development environment...")
    
    # Start Redis if needed
    if redis:
        click.echo("🔄 Starting Redis server...")
        await _start_redis()
    
    # Start local central server
    click.echo(f"🎯 Starting central server on port {port}...")
    server = CentralServer("localhost", port)
    
    # Store server reference for cleanup
    _local_processes['central_server'] = server
    
    try:
        # Update config to use local server
        config.mode = "cluster"
        config.cluster.endpoint = f"localhost:{port}"
        
        click.echo(f"✅ Local environment ready!")
        click.echo(f"   Central Server: http://localhost:{port}")
        click.echo(f"   Persistence: {'Redis' if redis else 'SQLite'}")
        click.echo(f"\n💡 Use Ctrl+C to stop, or run 'gleitzeit dev stop'")
        
        # Start server (this will block)
        await server.start()
        
    except KeyboardInterrupt:
        click.echo("\n⏹️  Stopping local environment...")
        await stop_local(ctx)
    except Exception as e:
        click.echo(f"❌ Failed to start local environment: {e}", err=True)
        await stop_local(ctx)


async def stop_local(ctx: click.Context) -> None:
    """Stop local development environment"""
    click.echo("⏹️  Stopping local development environment...")
    
    # Stop central server
    if 'central_server' in _local_processes:
        server = _local_processes['central_server']
        try:
            await server.stop()
            del _local_processes['central_server']
            click.echo("   ✅ Central server stopped")
        except Exception as e:
            click.echo(f"   ⚠️  Error stopping central server: {e}")
    
    # Stop Redis if we started it
    if 'redis' in _local_processes:
        try:
            _local_processes['redis'].terminate()
            del _local_processes['redis']
            click.echo("   ✅ Redis server stopped")
        except Exception as e:
            click.echo(f"   ⚠️  Error stopping Redis: {e}")
    
    # Stop MCP servers
    for name, process in list(_local_processes.items()):
        if name.startswith('mcp_'):
            try:
                process.terminate()
                del _local_processes[name]
                click.echo(f"   ✅ {name} stopped")
            except Exception:
                pass
    
    click.echo("✅ Local environment stopped")


async def start_mcp_server(ctx: click.Context, mcp_server: Optional[str], 
                          path: Optional[str]) -> None:
    """Start MCP server for development"""
    
    if mcp_server == "filesystem" or not mcp_server:
        await _start_filesystem_mcp(path or os.getcwd())
    elif mcp_server == "brave-search":
        await _start_brave_search_mcp()
    elif mcp_server == "memory":
        await _start_memory_mcp()
    else:
        click.echo(f"❌ Unknown MCP server: {mcp_server}", err=True)
        click.echo("Available MCP servers: filesystem, brave-search, memory")


async def _start_redis() -> None:
    """Start Redis server if not running"""
    try:
        # Check if Redis is already running
        result = subprocess.run(['redis-cli', 'ping'], 
                              capture_output=True, text=True, timeout=2)
        if result.returncode == 0 and result.stdout.strip() == 'PONG':
            click.echo("   ✅ Redis already running")
            return
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    try:
        # Start Redis server
        process = subprocess.Popen([
            'redis-server', 
            '--daemonize', 'no',
            '--port', '6379',
            '--bind', '127.0.0.1'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Give Redis time to start
        await asyncio.sleep(2)
        
        # Verify it started
        result = subprocess.run(['redis-cli', 'ping'], 
                              capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            _local_processes['redis'] = process
            click.echo("   ✅ Redis server started")
        else:
            process.terminate()
            raise SystemError("Redis failed to start properly")
            
    except FileNotFoundError:
        click.echo("   ⚠️  Redis not found. Install with: brew install redis (macOS) or apt install redis-server (Ubuntu)")
        raise
    except Exception as e:
        click.echo(f"   ❌ Failed to start Redis: {e}")
        raise


async def _start_filesystem_mcp(path: str) -> None:
    """Start filesystem MCP server"""
    click.echo(f"🗂️  Starting filesystem MCP server (path: {path})...")
    
    try:
        # Start MCP filesystem server
        process = subprocess.Popen([
            'npx', '-y', '@modelcontextprotocol/server-filesystem', path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Give it time to start
        await asyncio.sleep(2)
        
        if process.poll() is None:  # Still running
            _local_processes['mcp_filesystem'] = process
            click.echo(f"   ✅ Filesystem MCP server started")
            click.echo(f"   📁 Serving files from: {path}")
        else:
            stdout, stderr = process.communicate()
            raise SystemError(f"MCP server failed: {stderr.decode()}")
            
    except FileNotFoundError:
        click.echo("   ⚠️  Node.js/npm not found. Install Node.js to use MCP servers.")
        click.echo("   💡 Alternative: Install MCP tools with 'uv pip install mcp'")
        raise
    except Exception as e:
        click.echo(f"   ❌ Failed to start filesystem MCP server: {e}")
        raise


async def _start_brave_search_mcp() -> None:
    """Start Brave Search MCP server"""
    click.echo("🔍 Starting Brave Search MCP server...")
    
    # Check for API key
    api_key = os.getenv('BRAVE_API_KEY')
    if not api_key:
        click.echo("   ⚠️  BRAVE_API_KEY environment variable required")
        click.echo("   🔗 Get API key from: https://brave.com/search/api/")
        return
    
    try:
        process = subprocess.Popen([
            'npx', '-y', '@modelcontextprotocol/server-brave-search'
        ], env={**os.environ, 'BRAVE_API_KEY': api_key},
           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        await asyncio.sleep(2)
        
        if process.poll() is None:
            _local_processes['mcp_brave_search'] = process
            click.echo("   ✅ Brave Search MCP server started")
        else:
            stdout, stderr = process.communicate()
            raise SystemError(f"MCP server failed: {stderr.decode()}")
            
    except Exception as e:
        click.echo(f"   ❌ Failed to start Brave Search MCP server: {e}")
        raise


async def _start_memory_mcp() -> None:
    """Start Memory MCP server"""
    click.echo("🧠 Starting Memory MCP server...")
    
    try:
        process = subprocess.Popen([
            'npx', '-y', '@modelcontextprotocol/server-memory'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        await asyncio.sleep(2)
        
        if process.poll() is None:
            _local_processes['mcp_memory'] = process
            click.echo("   ✅ Memory MCP server started")
        else:
            stdout, stderr = process.communicate()
            raise SystemError(f"MCP server failed: {stderr.decode()}")
            
    except Exception as e:
        click.echo(f"   ❌ Failed to start Memory MCP server: {e}")
        raise