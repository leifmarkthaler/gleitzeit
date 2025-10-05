"""
Enhanced ps command for Gleitzeit CLI

Shows running services using Redis service registry as single source of truth.
"""

import click
import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any
import redis.asyncio as aioredis
from ..core.config_manager import ConfigurationManager


@click.command(name='ps')
@click.option('--all', '-a', is_flag=True, help='Show all registered services including stale')
@click.option('--format', type=click.Choice(['table', 'json', 'simple']), default='table',
              help='Output format')
@click.option('--services', is_flag=True, help='Group by service type')
@click.option('--redis-url', default=None, help='Redis connection URL (uses gleitzeit.yaml if not provided)')
def ps(all: bool, format: str, services: bool, redis_url: str):
    """
    List running Gleitzeit services using Redis service registry.

    Uses Redis as single source of truth for service discovery across all deployment modes.

    Examples:
        gleitzeit ps              # Show healthy services
        gleitzeit ps --all        # Show all registered services including stale
        gleitzeit ps --format json  # Output as JSON
        gleitzeit ps --services   # Group by service type
    """
    # Get Redis URL from ConfigurationManager if not provided
    if not redis_url:
        config_manager = ConfigurationManager(os.environ.get('GLEITZEIT_CONFIG', 'gleitzeit.yaml'), {})
        redis_url = config_manager.get_redis_url()

    try:
        asyncio.run(show_redis_services(all, format, services, redis_url))
    except Exception as e:
        click.echo(f"❌ Error connecting to Redis: {e}")
        click.echo("   Make sure Redis is running and accessible")


async def show_redis_services(all: bool, output_format: str, group_services: bool, redis_url: str):
    """Show services from Redis registry"""
    try:
        redis = await aioredis.from_url(redis_url)
        await redis.ping()
    except Exception as e:
        click.echo(f"❌ Failed to connect to Redis at {redis_url}: {e}")
        return

    try:
        # Discover all registered services and workers
        services = []
        service_count = 0
        healthy_services = 0

        # Scan for service registry entries
        async for key in redis.scan_iter(match=b"service:registry:*"):
            service_type = key.decode().split(":")[-1]
            service_data = await redis.hgetall(key)

            if service_data:
                service_count += 1

                # Decode service information
                service_info = {}
                for field, value in service_data.items():
                    service_info[field.decode()] = value.decode()

                # Determine service health based on registration time
                try:
                    started_at = datetime.fromisoformat(service_info.get('started_at', ''))
                    time_since_start = datetime.now() - started_at

                    # Consider service healthy if registered recently (within 30 minutes)
                    is_healthy = time_since_start < timedelta(minutes=30)
                    if is_healthy:
                        healthy_services += 1

                    service_info['health_status'] = 'healthy' if is_healthy else 'stale'
                    service_info['uptime_seconds'] = int(time_since_start.total_seconds())
                    service_info['service_type'] = service_type
                except:
                    service_info['health_status'] = 'unknown'
                    service_info['uptime_seconds'] = 0
                    service_info['service_type'] = service_type

                # Only show healthy services unless --all is specified
                if all or service_info['health_status'] == 'healthy':
                    services.append(service_info)

        # Scan for worker registry entries (they're in shard:0)
        async for key in redis.scan_iter(match=b"{shard:0}:worker:registry:*:*"):
            # Parse key: {shard:0}:worker:registry:{type}:{id}
            key_parts = key.decode().split(":")
            if len(key_parts) >= 6:
                worker_type = key_parts[4]
                worker_id = key_parts[5]
            else:
                continue

            worker_data = await redis.hgetall(key)

            if worker_data:
                service_count += 1

                # Decode worker information
                worker_info = {}
                for field, value in worker_data.items():
                    worker_info[field.decode()] = value.decode()

                # Workers have TTL-based health (60s TTL from heartbeat)
                # Check if key has TTL (healthy) or no TTL (stale)
                ttl = await redis.ttl(key)
                is_healthy = ttl > 0 if ttl != -2 else False

                # Also check started_at for consistency
                try:
                    started_at = datetime.fromisoformat(worker_info.get('started_at', ''))
                    time_since_start = datetime.now() - started_at
                    worker_info['uptime_seconds'] = int(time_since_start.total_seconds())
                except:
                    worker_info['uptime_seconds'] = 0

                if is_healthy:
                    healthy_services += 1

                # Add consistent fields for display
                worker_info['health_status'] = 'healthy' if is_healthy else 'stale'
                worker_info['service_type'] = f"worker-{worker_type}"
                worker_info['worker_type'] = worker_type
                worker_info['mode'] = 'docker'  # Workers are typically Docker-based

                # Workers don't have port field, set to N/A
                if 'port' not in worker_info:
                    worker_info['port'] = 'N/A'

                # Only show healthy workers unless --all is specified
                if all or worker_info['health_status'] == 'healthy':
                    services.append(worker_info)

        if not services:
            if all:
                click.echo("📭 No services registered in Redis")
            else:
                click.echo("📭 No healthy services found")
                click.echo("   Use --all to see stale registrations")
            return

        # Display services based on format
        if output_format == "json":
            if group_services:
                grouped = group_services_by_type(services)
                click.echo(json.dumps(grouped, indent=2))
            else:
                click.echo(json.dumps(services, indent=2))
        else:
            show_services_table(services, output_format, group_services, healthy_services, service_count)

    finally:
        await redis.aclose()


def show_services_table(services: List[Dict[str, Any]], output_format: str, group_services: bool, healthy_count: int, total_count: int):
    """Display services in table format"""
    click.echo("📊 Service Registry Status:")
    click.echo("-" * 80)

    if group_services:
        # Group by service type
        grouped = group_services_by_type(services)

        for service_type, service_list in grouped.items():
            click.echo(f"\n🔧 {service_type.upper()} Services:")
            click.echo(f"   {'Service':<15} {'Host':<20} {'Port':<8} {'Mode':<10} {'Status':<10} {'Uptime':<15}")
            click.echo(f"   {'-'*84}")

            for service in service_list:
                uptime = format_uptime(service.get('uptime_seconds', 0))
                status_icon = "✅" if service.get('health_status') == 'healthy' else "⚠️"

                click.echo(
                    f"   {service.get('service_type', 'unknown'):<15} "
                    f"{service.get('host', 'unknown'):<20} "
                    f"{service.get('port', 'N/A'):<8} "
                    f"{service.get('mode', 'unknown'):<10} "
                    f"{status_icon} {service.get('health_status', 'unknown'):<8} "
                    f"{uptime:<15}"
                )
    else:
        # Regular table
        if output_format == "simple":
            for service in services:
                status_icon = "✅" if service.get('health_status') == 'healthy' else "⚠️"
                click.echo(f"   {service.get('service_type')}: {status_icon} {service.get('health_status')} on {service.get('host')}:{service.get('port')} ({service.get('mode')})")
        else:
            click.echo(f"   {'Service':<15} {'Host':<20} {'Port':<8} {'Mode':<10} {'Status':<10} {'Uptime':<15}")
            click.echo(f"   {'-'*84}")

            for service in services:
                uptime = format_uptime(service.get('uptime_seconds', 0))
                status_icon = "✅" if service.get('health_status') == 'healthy' else "⚠️"

                click.echo(
                    f"   {service.get('service_type', 'unknown'):<15} "
                    f"{service.get('host', 'unknown'):<20} "
                    f"{service.get('port', 'N/A'):<8} "
                    f"{service.get('mode', 'unknown'):<10} "
                    f"{status_icon} {service.get('health_status', 'unknown'):<8} "
                    f"{uptime:<15}"
                )

    # Show summary
    stale_count = total_count - healthy_count if total_count > len(services) else 0
    click.echo()
    click.echo(f"   Summary: {healthy_count} healthy, {stale_count} stale | Total registered: {total_count}")

    # Show deployment modes
    modes = list(set(s.get('mode', 'unknown') for s in services))
    if modes:
        click.echo(f"   Deployment modes: {', '.join(modes)}")


def group_services_by_type(services: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group services by type"""
    grouped = {}

    for service in services:
        service_type = service.get('service_type', 'unknown')

        # Group workers by type
        if service_type.startswith('worker-'):
            worker_type = service.get('worker_type', 'unknown')
            key = f"workers-{worker_type}"
        else:
            key = service_type

        if key not in grouped:
            grouped[key] = []
        grouped[key].append(service)

    return grouped


def format_uptime(seconds: int) -> str:
    """Format uptime in human readable format"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds//60}m {seconds%60}s"
    elif seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days}d {hours}h"