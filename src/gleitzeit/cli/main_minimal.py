#!/usr/bin/env python3
"""
Gleitzeit V4 CLI - Minimal Working Version for Testing

Event-native command line interface for distributed task execution.
"""

import asyncio
import click
import logging
import sys
from pathlib import Path
from typing import Optional

from gleitzeit.cli.config import CLIConfig, load_config
from gleitzeit.cli.client import GleitzeitClient
from gleitzeit.cli.commands import submit, status, dev

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@click.group(invoke_without_command=True)
@click.option('--config', '-c', type=click.Path(), help='Configuration file path')
@click.option('--profile', '-p', default='default', help='Configuration profile to use')
@click.option('--mode', type=click.Choice(['auto', 'local', 'cluster']), help='Override execution mode')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.pass_context
def cli(ctx, config: Optional[str], profile: str, mode: Optional[str], verbose: bool):
    """
    Gleitzeit V4 - Distributed Task Execution Platform
    
    Event-native workflow execution with Socket.IO coordination,
    MCP protocol integration, and persistent retry logic.
    """
    
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Load configuration
        cli_config = load_config(config, profile)
        
        # Override mode if specified
        if mode:
            cli_config.mode = mode
        
        # Auto-detect mode based on cluster endpoint if not specified
        if cli_config.mode == 'auto':
            if cli_config.cluster.endpoint:
                cli_config.mode = 'cluster'
            else:
                cli_config.mode = 'local'
        
        # Force cluster mode if endpoint provided
        if cli_config.cluster.endpoint and cli_config.mode != 'cluster':
            cli_config.mode = 'cluster'
        
        # Store config in context for subcommands
        ctx.ensure_object(dict)
        ctx.obj['config'] = cli_config
        ctx.obj['profile'] = profile
        
        logger.debug(f"Using profile: {profile}, mode: {cli_config.mode}")
        
    except Exception as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)
    
    # Show help if no command provided
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# Core workflow commands
@cli.command('submit')
@click.argument('workflow', type=click.Path(exists=True))
@click.option('--watch', '-w', is_flag=True, help='Stream execution events')
@click.option('--dry-run', is_flag=True, help='Validate workflow without execution')
@click.option('--priority', type=click.Choice(['low', 'normal', 'high', 'urgent']),
              default='normal', help='Workflow execution priority')
@click.pass_context
def submit_cmd(ctx, workflow: str, watch: bool, dry_run: bool, priority: str):
    """Submit a workflow for execution"""
    return asyncio.run(submit.execute(ctx, workflow, watch, dry_run, priority))


@cli.command('status')
@click.argument('workflow_id')
@click.option('--detailed', '-d', is_flag=True, help='Show detailed task status')
@click.pass_context
def status_cmd(ctx, workflow_id: str, detailed: bool):
    """Get workflow or task status"""
    return asyncio.run(status.execute(ctx, workflow_id, detailed))


# Development commands
@cli.group()
def dev():
    """Local development commands"""
    pass


@dev.command()
@click.option('--port', default=8000, help='Local server port')
@click.option('--redis', is_flag=True, help='Use Redis instead of SQLite')
@click.pass_context
def start(ctx, port: int, redis: bool):
    """Start local development environment"""
    return asyncio.run(dev.start_local(ctx, port, redis))


@dev.command()
@click.pass_context 
def stop(ctx):
    """Stop local development environment"""
    return asyncio.run(dev.stop_local(ctx))


# Provider management (placeholder)
@cli.group()
def providers():
    """Manage protocol providers"""
    pass


@providers.command('list')
@click.option('--format', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def list_providers(ctx, format: str):
    """List registered providers"""
    click.echo("Provider listing not yet implemented")


# Config management
@cli.group('config')
def config_group():
    """Configuration management"""
    pass


@config_group.command('show')
@click.pass_context
def show_config(ctx):
    """Show current configuration"""
    config = ctx.obj['config']
    click.echo(f"Profile: {ctx.obj['profile']}")
    click.echo(f"Mode: {config.mode}")
    click.echo(f"Local Engine Port: {config.local_engine.port}")
    if config.cluster.endpoint:
        click.echo(f"Cluster Endpoint: {config.cluster.endpoint}")


if __name__ == '__main__':
    cli()