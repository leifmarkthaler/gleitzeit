#!/usr/bin/env python3
"""
Gleitzeit V4 CLI - Main Entry Point

Event-native command line interface for distributed task execution.
Supports both local development and distributed production modes.
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


@click.group()
@click.option('--config', '-c', type=click.Path(exists=True), 
              help='Path to configuration file')
@click.option('--profile', '-p', default='default',
              help='Configuration profile to use')
@click.option('--cluster', help='Cluster endpoint (overrides profile)')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.pass_context
def cli(ctx: click.Context, config: Optional[str], profile: str, 
        cluster: Optional[str], verbose: bool, debug: bool):
    """
    Gleitzeit V4 - Event-driven distributed task execution
    
    Submit workflows, manage providers, and monitor execution across
    distributed execution engines with real-time event streaming.
    """
    # Set up logging level
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
    elif verbose:
        logging.getLogger().setLevel(logging.INFO)
    else:
        logging.getLogger().setLevel(logging.WARNING)
    
    # Load configuration
    try:
        cli_config = load_config(config, profile)
        
        # Override cluster if provided
        if cluster:
            cli_config.cluster.endpoint = cluster
            cli_config.mode = 'cluster'
        
        # Store config in context for subcommands
        ctx.ensure_object(dict)
        ctx.obj['config'] = cli_config
        ctx.obj['profile'] = profile
        
        logger.debug(f"Using profile: {profile}, mode: {cli_config.mode}")
        
    except Exception as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)


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


@dev.command()
@click.option('--mcp-server', help='Start specific MCP server')
@click.option('--path', help='Path for filesystem MCP server')
@click.pass_context
def start_mcp(ctx, mcp_server: Optional[str], path: Optional[str]):
    """Start MCP server for development"""
    return asyncio.run(dev.start_mcp_server(ctx, mcp_server, path))


# Workflow management
@cli.command()
@click.argument('workflow', type=click.Path(exists=True))
@click.option('--schema', is_flag=True, help='Validate against schema only')
@click.pass_context
def validate(ctx, workflow: str, schema: bool):
    """Validate workflow definition"""
    return asyncio.run(validate.execute(ctx, workflow, schema))


@cli.command('init')
@click.argument('name')
@click.option('--template', help='Template to use (data-pipeline, api-workflow, etc.)')
@click.option('--interactive', '-i', is_flag=True, help='Interactive workflow builder')
@click.pass_context
def init_workflow_cmd(ctx, name: str, template: Optional[str], interactive: bool):
    """Create new workflow definition"""
    return asyncio.run(init_workflow.execute(ctx, name, template, interactive))


# Provider and protocol management
@cli.group()
def providers():
    """Manage protocol providers"""
    pass


@providers.command('list')
@click.option('--available', '-a', is_flag=True, help='Show available providers')
@click.option('--format', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def list_providers(ctx, available: bool, format: str):
    """List registered providers"""
    return asyncio.run(providers.list_providers(ctx, available, format))


@providers.command('discover')
@click.option('--mcp', is_flag=True, help='Discover MCP servers')
@click.option('--network', is_flag=True, help='Network discovery')
@click.pass_context
def discover_providers(ctx, mcp: bool, network: bool):
    """Discover available providers"""
    return asyncio.run(providers.discover(ctx, mcp, network))


@providers.command('inspect')
@click.argument('provider_id')
@click.pass_context
def inspect_provider(ctx, provider_id: str):
    """Inspect provider capabilities"""
    return asyncio.run(providers.inspect(ctx, provider_id))


@cli.group()
def protocols():
    """Manage protocols"""
    pass


@protocols.command('list')
@click.option('--format', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def list_protocols(ctx, format: str):
    """List available protocols"""
    return asyncio.run(protocols.list_protocols(ctx, format))


@protocols.command('show')
@click.argument('protocol_id')
@click.pass_context
def show_protocol(ctx, protocol_id: str):
    """Show protocol specification"""
    return asyncio.run(protocols.show(ctx, protocol_id))


@protocols.command('methods')
@click.argument('protocol_id')
@click.option('--filter', help='Filter methods by name pattern')
@click.pass_context
def list_methods(ctx, protocol_id: str, filter: Optional[str]):
    """List protocol methods"""
    return asyncio.run(protocols.methods(ctx, protocol_id, filter))


# Cluster management  
@cli.group()
def cluster():
    """Manage cluster connections"""
    pass


@cluster.command('connect')
@click.argument('endpoint')
@click.option('--auth', help='Authentication method')
@click.pass_context
def connect_cluster(ctx, endpoint: str, auth: Optional[str]):
    """Connect to cluster"""
    return asyncio.run(cluster.connect(ctx, endpoint, auth))


@cluster.command('status')
@click.pass_context
def cluster_status(ctx):
    """Show cluster status"""
    return asyncio.run(cluster.status(ctx))


@cluster.command('nodes')
@click.option('--detailed', '-d', is_flag=True)
@click.pass_context
def cluster_nodes(ctx, detailed: bool):
    """List cluster nodes"""
    return asyncio.run(cluster.nodes(ctx, detailed))


# Configuration management
@cli.group('config')
def config_group():
    """Manage CLI configuration"""
    pass


@config_group.command('set')
@click.argument('key')
@click.argument('value')
@click.option('--profile', help='Profile to modify')
@click.pass_context
def config_set(ctx, key: str, value: str, profile: Optional[str]):
    """Set configuration value"""
    return asyncio.run(config_cmd.set_config(ctx, key, value, profile))


@config_group.command('get')
@click.argument('key')
@click.option('--profile', help='Profile to query')
@click.pass_context
def config_get(ctx, key: str, profile: Optional[str]):
    """Get configuration value"""
    return asyncio.run(config_cmd.get_config(ctx, key, profile))


@config_group.command('profiles')
@click.pass_context
def config_profiles(ctx):
    """List configuration profiles"""
    return asyncio.run(config_cmd.list_profiles(ctx))


@config_group.command('init')
@click.option('--interactive', '-i', is_flag=True)
@click.pass_context
def config_init(ctx, interactive: bool):
    """Initialize configuration"""
    return asyncio.run(config_cmd.init_config(ctx, interactive))


def main():
    """Main CLI entry point"""
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\nInterrupted by user", err=True)
        sys.exit(130)
    except Exception as e:
        if logger.isEnabledFor(logging.DEBUG):
            import traceback
            traceback.print_exc()
        else:
            click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    main()