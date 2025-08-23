"""
UI command for Gleitzeit CLI

Starts the web UI server connected to the running Gleitzeit system.
"""

import asyncio
import click
import logging
import sys
import os
from typing import Optional
import uvicorn
from pathlib import Path

logger = logging.getLogger(__name__)


async def start_ui(ctx: click.Context, port: int = 8004, host: str = "127.0.0.1", 
                   reload: bool = False):
    """
    Start the Gleitzeit Web UI server
    
    The UI will connect to the Gleitzeit API for monitoring workflows and tasks.
    Make sure the Gleitzeit API is running (gleitzeit serve).
    """
    config = ctx.obj.get('config')
    
    click.echo(f"Starting Gleitzeit Web UI on http://{host}:{port}")
    
    # Check if API is running
    import aiohttp
    api_url = os.getenv('GLEITZEIT_API_URL', 'http://localhost:8000')
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{api_url}/health", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status == 200:
                    click.echo(f"✅ Connected to Gleitzeit API at {api_url}")
                else:
                    click.echo(f"⚠️  Gleitzeit API at {api_url} returned status {resp.status}", err=True)
                    click.echo("Make sure to run 'gleitzeit serve' first", err=True)
    except:
        click.echo(f"⚠️  Cannot connect to Gleitzeit API at {api_url}", err=True)
        click.echo("Make sure to run 'gleitzeit serve' first to start the API", err=True)
    
    # Get the UI app path
    ui_path = Path(__file__).parent.parent.parent.parent / "ui"
    if not ui_path.exists():
        click.echo(f"Error: UI directory not found at {ui_path}", err=True)
        sys.exit(1)
    
    # Add UI path to Python path so imports work
    sys.path.insert(0, str(ui_path))
    
    try:
        # Import the UI app - it's now a thin client that proxies to the API
        from api.app import app
        
        # Run the UI server
        config = uvicorn.Config(
            app=app,
            host=host,
            port=port,
            reload=reload,
            log_level="info"
        )
        server = uvicorn.Server(config)
        
        click.echo(f"✅ Gleitzeit UI started at http://{host}:{port}")
        click.echo("Press Ctrl+C to stop the server")
        
        await server.serve()
        
    except ImportError as e:
        click.echo(f"Error importing UI app: {e}", err=True)
        click.echo("Make sure the UI is properly installed", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error starting UI server: {e}", err=True)
        sys.exit(1)


async def stop_ui(ctx: click.Context):
    """Stop the UI server if running"""
    click.echo("Stopping Gleitzeit Web UI...")
    # In practice, the UI is stopped with Ctrl+C
    # This could be extended to track and stop background UI processes
    click.echo("UI stopped")