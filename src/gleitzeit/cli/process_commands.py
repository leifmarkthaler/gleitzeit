"""
Process monitoring commands for Gleitzeit CLI

Provides Docker-style commands for process monitoring and management.
"""

import asyncio
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import click
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

import redis.asyncio as aioredis

from ..core.instance import get_current_instance
from ..core.sharding import default_sharding

console = Console()


@click.group()
def process():
    """Process management commands"""
    pass


@process.command('ps')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON')
@click.option('--watch', is_flag=True, help='Auto-refresh display')
@click.option('--interval', default=2, help='Refresh interval in seconds')
@click.option('--instance', help='Filter by instance name or ID')
@click.option('--machine', help='Filter by machine ID or hostname')
@click.option('--all-machines', is_flag=True, help='Show processes from all machines')
@click.option('--redis-url', default='redis://localhost:6379',
              envvar='REDIS_URL', help='Redis connection URL')
def ps(output_json: bool, watch: bool, interval: int, instance: Optional[str],
       machine: Optional[str], all_machines: bool, redis_url: str):
    """List all Gleitzeit processes across machines (like docker ps)"""
    asyncio.run(_ps_async(output_json, watch, interval, instance, machine, all_machines, redis_url))


async def _ps_async(output_json: bool, watch: bool, interval: int,
                     instance: Optional[str], machine: Optional[str],
                     all_machines: bool, redis_url: str):
    """Async implementation of ps command"""
    redis = aioredis.from_url(redis_url, decode_responses=False)

    try:
        if watch:
            # Live updating display
            with Live(refresh_per_second=1/interval) as live:
                while True:
                    processes = await _get_processes(redis, instance, machine, all_machines)
                    if output_json:
                        live.update(json.dumps(processes, indent=2, default=str))
                    else:
                        table = _create_process_table(processes)
                        live.update(table)
                    await asyncio.sleep(interval)
        else:
            # Single display
            processes = await _get_processes(redis, instance, machine, all_machines)
            if output_json:
                console.print(json.dumps(processes, indent=2, default=str))
            else:
                table = _create_process_table(processes)
                console.print(table)

    finally:
        await redis.close()


async def _get_processes(redis: aioredis.Redis, instance_filter: Optional[str],
                         machine_filter: Optional[str], all_machines: bool) -> List[Dict]:
    """Get all processes from Redis using hybrid pattern with multi-machine support"""
    processes = []
    instances = {}
    machines = {}  # Store machine info

    # Get machine registry first
    machine_ids = await redis.smembers(b"machine:registry")
    for machine_id_bytes in machine_ids:
        machine_id = machine_id_bytes.decode()
        machine_info = await redis.hgetall(f"machine:{machine_id}:info".encode())
        if machine_info:
            machines[machine_id] = {
                'hostname': machine_info.get(b'hostname', b'unknown').decode(),
                'primary_ip': machine_info.get(b'primary_ip', b'').decode(),
                'datacenter': machine_info.get(b'datacenter', b'default').decode(),
            }

    # Method 1: Find instances from ownership keys
    async for key in redis.scan_iter(match=b"service:ownership:*", count=100):
        owner_data = await redis.get(key)
        if owner_data:
            owner_info = json.loads(owner_data.decode())
            instance_id = owner_info['instance_id']
            instance_name = owner_info.get('instance_name', instance_id[:8])
            instances[instance_id] = {'name': instance_name}

    # Method 2: Find instances from registry
    instance_ids = await redis.smembers(b"instance:registry")
    for instance_id_bytes in instance_ids:
        instance_id = instance_id_bytes.decode()
        if instance_id not in instances:
            # Get instance info
            info_data = await redis.hgetall(f"instance:{instance_id}:info".encode())
            if info_data:
                instance_name = info_data.get(b'name', instance_id[:8].encode()).decode()
                instances[instance_id] = {'name': instance_name}

        # Get machine info for instance
        if instance_id in instances:
            info_data = await redis.hgetall(f"instance:{instance_id}:info".encode())
            if info_data:
                machine_id = info_data.get(b'machine_id', b'').decode()
                if machine_id:
                    instances[instance_id]['machine_id'] = machine_id
                    instances[instance_id]['machine_info'] = machines.get(machine_id, {})

    # Now get processes for all discovered instances
    for instance_id, instance_data in instances.items():
        instance_name = instance_data.get('name', instance_id[:8])
        machine_id = instance_data.get('machine_id', '')
        machine_info = instance_data.get('machine_info', {})

        # Apply filters
        if instance_filter:
            if (instance_filter not in instance_id and
                instance_filter not in instance_name):
                continue

        if machine_filter:
            hostname = machine_info.get('hostname', '')
            if (machine_filter not in machine_id and
                machine_filter not in hostname):
                continue

        # Get all process keys for this instance
        pattern = f"instance:{instance_id}:process:*"
        async for key in redis.scan_iter(match=pattern.encode(), count=100):
            process_name = key.decode().split(":")[-1]
            process_data = await redis.hgetall(key)

            if process_data:
                # Format machine display
                machine_display = machine_info.get('hostname', machine_id[:8] if machine_id else 'local')
                if machine_info.get('datacenter') and machine_info.get('datacenter') != 'default':
                    machine_display = f"{machine_display}@{machine_info['datacenter']}"

                process_info = {
                    'name': process_name,
                    'instance': instance_name,
                    'instance_id': instance_id,
                    'machine': machine_display,
                    'machine_id': machine_id,
                    'pid': int(process_data.get(b'pid', b'0').decode()),
                    'port': int(process_data.get(b'port', b'0').decode()) if process_data.get(b'port') and process_data.get(b'port') != b'' else None,
                    'status': process_data.get(b'status', b'unknown').decode(),
                    'started_at': process_data.get(b'started_at', b'').decode(),
                    'restart_count': int(process_data.get(b'restart_count', b'0').decode()),
                    'type': process_data.get(b'type', b'SERVICE').decode(),
                }

                # Calculate uptime
                if process_info['started_at']:
                    started = datetime.fromisoformat(process_info['started_at'])
                    uptime = datetime.utcnow() - started
                    process_info['uptime'] = _format_uptime(uptime)
                else:
                    process_info['uptime'] = 'N/A'

                processes.append(process_info)

    # Sort by machine, instance and name
    processes.sort(key=lambda x: (x.get('machine', ''), x['instance'], x['name']))
    return processes


def _create_process_table(processes: List[Dict]) -> Table:
    """Create a Rich table for process display"""
    table = Table(title="Gleitzeit Processes (Multi-Machine)", show_lines=True)

    table.add_column("NAME", style="cyan", width=20)
    table.add_column("INSTANCE", style="green", width=15)
    table.add_column("MACHINE", style="magenta", width=20)
    table.add_column("TYPE", style="yellow", width=8)
    table.add_column("PID", justify="right", width=8)
    table.add_column("PORT", justify="right", width=8)
    table.add_column("STATUS", width=10)
    table.add_column("UPTIME", width=12)
    table.add_column("RESTARTS", justify="right", width=8)

    for proc in processes:
        # Color code status
        status = proc['status']
        if status == 'running':
            status_text = Text(status, style="green")
        elif status == 'failed':
            status_text = Text(status, style="red")
        else:
            status_text = Text(status, style="yellow")

        table.add_row(
            proc['name'],
            proc['instance'],
            proc.get('machine', 'local'),
            proc['type'],
            str(proc['pid']) if proc['pid'] else '-',
            str(proc['port']) if proc['port'] else '-',
            status_text,
            proc['uptime'],
            str(proc['restart_count'])
        )

    return table


def _format_uptime(delta: timedelta) -> str:
    """Format timedelta as human-readable uptime"""
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"


@process.command('logs')
@click.argument('process_name')
@click.option('-f', '--follow', is_flag=True, help='Follow log output')
@click.option('-n', '--lines', default=100, help='Number of lines to show')
@click.option('--redis-url', default='redis://localhost:6379',
              envvar='REDIS_URL', help='Redis connection URL')
def logs(process_name: str, follow: bool, lines: int, redis_url: str):
    """View logs for a process"""
    asyncio.run(_logs_async(process_name, follow, lines, redis_url))


async def _logs_async(process_name: str, follow: bool, lines: int, redis_url: str):
    """Async implementation of logs command"""
    redis = aioredis.from_url(redis_url, decode_responses=False)

    try:
        # Get process owner
        owner_key = f"service:ownership:{process_name}".encode()
        owner_data = await redis.get(owner_key)

        if not owner_data:
            console.print(f"[red]Process '{process_name}' not found[/red]")
            return

        owner_info = json.loads(owner_data.decode())
        instance_id = owner_info['instance_id']

        # Get log stream key
        log_key = f"instance:{instance_id}:logs:{process_name}"

        if follow:
            # Follow mode - stream logs
            console.print(f"[cyan]Following logs for {process_name}...[/cyan]")
            last_id = '$'  # Start from latest

            while True:
                # Read new entries from stream
                entries = await redis.xread({log_key.encode(): last_id}, block=1000)

                for stream_name, messages in entries:
                    for message_id, data in messages:
                        log_entry = json.loads(data.get(b'entry', b'{}').decode())
                        _print_log_entry(log_entry)
                        last_id = message_id

        else:
            # Static mode - show last N lines
            entries = await redis.xrevrange(log_key.encode(), count=lines)

            # Reverse to show in chronological order
            entries.reverse()

            for message_id, data in entries:
                log_entry = json.loads(data.get(b'entry', b'{}').decode())
                _print_log_entry(log_entry)

    finally:
        await redis.close()


def _print_log_entry(entry: Dict):
    """Print a single log entry"""
    timestamp = entry.get('timestamp', '')
    level = entry.get('level', 'INFO')
    message = entry.get('message', '')

    # Color code by level
    level_colors = {
        'DEBUG': 'dim',
        'INFO': 'white',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold red'
    }

    color = level_colors.get(level, 'white')
    console.print(f"[dim]{timestamp}[/dim] [{color}]{level:8}[/{color}] {message}")


@process.command('inspect')
@click.argument('process_name')
@click.option('--redis-url', default='redis://localhost:6379',
              envvar='REDIS_URL', help='Redis connection URL')
def inspect(process_name: str, redis_url: str):
    """Show detailed information about a process"""
    asyncio.run(_inspect_async(process_name, redis_url))


async def _inspect_async(process_name: str, redis_url: str):
    """Async implementation of inspect command"""
    redis = aioredis.from_url(redis_url, decode_responses=False)

    try:
        # Get process owner
        owner_key = f"service:ownership:{process_name}".encode()
        owner_data = await redis.get(owner_key)

        if not owner_data:
            console.print(f"[red]Process '{process_name}' not found[/red]")
            return

        owner_info = json.loads(owner_data.decode())
        instance_id = owner_info['instance_id']

        # Get detailed process info
        process_key = f"instance:{instance_id}:process:{process_name}"
        process_data = await redis.hgetall(process_key.encode())

        if not process_data:
            console.print(f"[red]Process data not found[/red]")
            return

        # Format process info
        info = {
            'Name': process_name,
            'Instance': owner_info.get('instance_name', 'unknown'),
            'Instance ID': instance_id,
            'PID': process_data.get(b'pid', b'').decode(),
            'Port': process_data.get(b'port', b'').decode() or 'N/A',
            'Status': process_data.get(b'status', b'').decode(),
            'Type': process_data.get(b'type', b'').decode(),
            'Started At': process_data.get(b'started_at', b'').decode(),
            'Restart Count': process_data.get(b'restart_count', b'0').decode(),
            'Last Restart': process_data.get(b'last_restart_at', b'').decode() or 'Never',
            'Exit Code': process_data.get(b'exit_code', b'').decode() or 'N/A',
            'Command': process_data.get(b'command', b'').decode(),
        }

        # Add worker-specific info if applicable
        if process_data.get(b'assigned_shards'):
            shards = json.loads(process_data.get(b'assigned_shards', b'[]').decode())
            info['Assigned Shards'] = ', '.join(map(str, shards))

        # Create panel for display
        content = '\n'.join([f"[cyan]{k}:[/cyan] {v}" for k, v in info.items()])
        panel = Panel(content, title=f"Process: {process_name}", border_style="green")
        console.print(panel)

        # Show recent restart history if available
        restart_key = f"instance:{instance_id}:restarts:{process_name}"
        restarts = await redis.lrange(restart_key.encode(), 0, 5)

        if restarts:
            console.print("\n[yellow]Recent Restart History:[/yellow]")
            for restart_data in restarts:
                restart_info = json.loads(restart_data.decode())
                console.print(f"  • {restart_info['timestamp']}: {restart_info['reason']}")

    finally:
        await redis.close()


@process.command('machines')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON')
@click.option('--redis-url', default='redis://localhost:6379',
              envvar='REDIS_URL', help='Redis connection URL')
def machines(output_json: bool, redis_url: str):
    """Show machine topology and instance distribution"""
    asyncio.run(_machines_async(output_json, redis_url))


async def _machines_async(output_json: bool, redis_url: str):
    """Async implementation of machines command"""
    redis = aioredis.from_url(redis_url, decode_responses=False)

    try:
        machines = {}

        # Get machine registry
        machine_ids = await redis.smembers(b"machine:registry")
        for machine_id_bytes in machine_ids:
            machine_id = machine_id_bytes.decode()
            machine_info = await redis.hgetall(f"machine:{machine_id}:info".encode())

            if machine_info:
                machines[machine_id] = {
                    'hostname': machine_info.get(b'hostname', b'unknown').decode(),
                    'fqdn': machine_info.get(b'fqdn', b'').decode(),
                    'primary_ip': machine_info.get(b'primary_ip', b'').decode(),
                    'all_ips': machine_info.get(b'all_ips', b'[]').decode(),
                    'datacenter': machine_info.get(b'datacenter', b'default').decode(),
                    'rack': machine_info.get(b'rack', b'default').decode(),
                    'network_zone': machine_info.get(b'network_zone', b'default').decode(),
                    'instances': []
                }

                # Get instances on this machine
                instance_ids = await redis.smembers(f"machine:{machine_id}:instances".encode())
                for inst_id_bytes in instance_ids:
                    inst_id = inst_id_bytes.decode()
                    inst_info = await redis.hgetall(f"instance:{inst_id}:info".encode())
                    if inst_info:
                        machines[machine_id]['instances'].append({
                            'id': inst_id,
                            'name': inst_info.get(b'name', inst_id[:8].encode()).decode(),
                            'role': inst_info.get(b'role', b'unknown').decode()
                        })

        if output_json:
            console.print(json.dumps(machines, indent=2))
        else:
            _display_machine_topology(machines)

    finally:
        await redis.close()


def _display_machine_topology(machines: Dict):
    """Display machine topology in a hierarchical format"""
    if not machines:
        console.print("[yellow]No machines registered[/yellow]")
        return

    # Group by datacenter and rack
    topology = {}
    for machine_id, machine_info in machines.items():
        dc = machine_info['datacenter']
        rack = machine_info['rack']

        if dc not in topology:
            topology[dc] = {}
        if rack not in topology[dc]:
            topology[dc][rack] = []

        topology[dc][rack].append((machine_id, machine_info))

    # Create display
    from rich.tree import Tree

    root = Tree("[bold cyan]Machine Topology[/bold cyan]")

    for dc, racks in sorted(topology.items()):
        dc_node = root.add(f"📍 Datacenter: [green]{dc}[/green]")

        for rack, machines_list in sorted(racks.items()):
            rack_node = dc_node.add(f"🗄️  Rack: [yellow]{rack}[/yellow]")

            for machine_id, machine_info in machines_list:
                machine_display = f"{machine_info['hostname']} ({machine_info['primary_ip']})"
                machine_node = rack_node.add(f"💻 [cyan]{machine_display}[/cyan]")

                # Add instance count
                inst_count = len(machine_info['instances'])
                machine_node.add(f"📦 Instances: [white]{inst_count}[/white]")

                # List instances
                for inst in machine_info['instances']:
                    machine_node.add(f"  • {inst['name']} ({inst['role']})")

    console.print(root)

    # Summary
    total_machines = len(machines)
    total_instances = sum(len(m['instances']) for m in machines.values())
    console.print(f"\n[bold]Summary:[/bold] {total_machines} machines, {total_instances} instances")


def add_process_commands(cli):
    """Add process commands to CLI"""
    cli.add_command(process)