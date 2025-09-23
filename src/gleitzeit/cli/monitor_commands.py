"""
CLI commands for system-wide event monitoring
"""

import click
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional

from ..core.event_monitor import EventMonitor
from ..core.events import EventType


@click.group()
def monitor():
    """System-wide event monitoring commands"""
    pass


@monitor.command()
@click.option('--event-type', '-e', multiple=True,
              help='Event types to show (can specify multiple)')
@click.option('--limit', '-n', default=50, help='Number of events to show')
@click.option('--hours', '-h', default=1, type=float,
              help='Time window in hours')
@click.option('--redis-url', default='redis://localhost:6379',
              help='Redis connection URL')
async def events(event_type: tuple, limit: int, hours: float, redis_url: str):
    """View event-centric timeline across all workflows"""
    import aioredis

    redis = await aioredis.create_redis_pool(redis_url)

    try:
        monitor = EventMonitor(redis)

        # Parse event types
        if event_type:
            event_types = []
            for et in event_type:
                try:
                    event_types.append(EventType(f"task:{et}") if ':' not in et else EventType(et))
                except:
                    click.echo(f"Warning: Unknown event type '{et}'")
        else:
            # Default to all critical events
            event_types = [
                EventType.TASK_FAILED,
                EventType.TASK_COMPLETED,
                EventType.WORKFLOW_COMPLETED,
                EventType.WORKFLOW_FAILED
            ]

        # Get events
        time_window = timedelta(hours=hours) if hours else None
        events = await monitor.get_event_centric_timeline(
            event_types=event_types,
            limit=limit,
            time_window=time_window
        )

        if not events:
            click.echo(f"No events found in the last {hours} hour(s)")
            return

        # Display events
        click.echo(f"\nSystem-Wide Event Timeline (last {hours} hour(s)):")
        click.echo("=" * 80)

        for event in events:
            timestamp = event.timestamp
            workflow = event.workflow_id[:12] + "..." if len(event.workflow_id) > 15 else event.workflow_id
            task = event.task_id or "N/A"
            event_type_str = event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type)

            # Format based on event type
            if 'failed' in event_type_str.lower():
                icon = "❌"
                color = "red"
            elif 'completed' in event_type_str.lower():
                icon = "✅"
                color = "green"
            elif 'skipped' in event_type_str.lower():
                icon = "⏭️"
                color = "yellow"
            else:
                icon = "📍"
                color = None

            line = f"[{timestamp}] {icon} {event_type_str}"
            if color:
                line = click.style(line, fg=color)

            click.echo(line)
            click.echo(f"    Workflow: {workflow} | Task: {task}")

            if event.data:
                if event.data.get('error'):
                    click.echo(f"    Error: {event.data['error']}")
                if event.data.get('reason'):
                    click.echo(f"    Reason: {event.data['reason']}")

    finally:
        redis.close()
        await redis.wait_closed()


@monitor.command()
@click.option('--hours', '-h', default=1, type=float,
              help='Time window in hours')
@click.option('--redis-url', default='redis://localhost:6379',
              help='Redis connection URL')
async def failures(hours: float, redis_url: str):
    """Show all failures across the system"""
    import aioredis

    redis = await aioredis.create_redis_pool(redis_url)

    try:
        monitor = EventMonitor(redis)

        # Get failures
        time_window = timedelta(hours=hours)
        failures = await monitor.get_failure_timeline(limit=100, time_window=time_window)

        if not failures:
            click.echo(f"✅ No failures in the last {hours} hour(s)")
            return

        click.echo(f"\n❌ System Failures (last {hours} hour(s)):")
        click.echo("=" * 80)

        # Group by workflow
        by_workflow = {}
        for event in failures:
            wf = event.workflow_id
            if wf not in by_workflow:
                by_workflow[wf] = []
            by_workflow[wf].append(event)

        for workflow_id, wf_failures in by_workflow.items():
            click.echo(f"\nWorkflow: {workflow_id}")
            for event in wf_failures:
                timestamp = event.timestamp
                task = event.task_id or "workflow"
                error = event.data.get('error', 'Unknown error')
                click.echo(f"  [{timestamp}] Task {task}: {error}")

        # Summary
        click.echo(f"\n📊 Summary:")
        click.echo(f"  Total failures: {len(failures)}")
        click.echo(f"  Affected workflows: {len(by_workflow)}")

        # Find correlated failures
        correlated = await monitor.find_correlated_failures(time_window)
        if correlated:
            click.echo(f"\n⚠️  Correlated Failures (tasks failing in multiple workflows):")
            for task, failures_list in correlated.items():
                click.echo(f"  Task '{task}': {len(failures_list)} failures")

    finally:
        redis.close()
        await redis.wait_closed()


@monitor.command()
@click.option('--hours', '-h', default=1, type=float,
              help='Time window in hours')
@click.option('--redis-url', default='redis://localhost:6379',
              help='Redis connection URL')
async def metrics(hours: float, redis_url: str):
    """Show system-wide metrics"""
    import aioredis

    redis = await aioredis.create_redis_pool(redis_url)

    try:
        monitor = EventMonitor(redis)

        # Get metrics
        time_window = timedelta(hours=hours)
        metrics = await monitor.get_system_metrics(time_window)

        click.echo(f"\n📊 System Metrics (last {hours} hour(s)):")
        click.echo("=" * 80)

        click.echo(f"Total workflows: {metrics['total_workflows']}")
        click.echo("")

        # Event metrics table
        click.echo("Event Type                     | Count | Workflows | Rate/min")
        click.echo("-------------------------------|-------|-----------|----------")

        for event_type, data in sorted(metrics['metrics_by_event'].items()):
            event_name = event_type.ljust(30)[:30]
            count = str(data['count']).rjust(5)
            workflows = str(data['workflows_affected']).rjust(9)
            rate = f"{data['avg_per_minute']:.1f}".rjust(8)
            click.echo(f"{event_name} | {count} | {workflows} | {rate}")

        # Health summary
        health = await monitor.get_workflow_health_summary(time_window)
        click.echo(f"\n🏥 Health Summary:")
        click.echo(f"  Healthy workflows: {health['healthy']}")
        click.echo(f"  Failed workflows: {health['failed']}")
        click.echo(f"  In progress: {health['in_progress']}")
        click.echo(f"  With skips: {health['completed_with_skips']}")
        click.echo(f"  Success rate: {health['success_rate']:.1f}%")

    finally:
        redis.close()
        await redis.wait_closed()


@monitor.command()
@click.option('--hours', '-h', default=1, type=float,
              help='Time window in hours')
@click.option('--redis-url', default='redis://localhost:6379',
              help='Redis connection URL')
async def validations(hours: float, redis_url: str):
    """Show validation decisions (skips/blocks) across system"""
    import aioredis

    redis = await aioredis.create_redis_pool(redis_url)

    try:
        monitor = EventMonitor(redis)

        # Get validation timeline
        time_window = timedelta(hours=hours)
        events = await monitor.get_validation_timeline(limit=100, time_window=time_window)

        if not events:
            click.echo(f"No validation decisions in the last {hours} hour(s)")
            return

        click.echo(f"\n🔍 Validation Decisions (last {hours} hour(s)):")
        click.echo("=" * 80)

        skips = 0
        blocks = 0

        for event in events:
            timestamp = event.timestamp
            workflow = event.workflow_id[:20] + "..." if len(event.workflow_id) > 23 else event.workflow_id
            task = event.task_id or "N/A"

            if event.event_type == EventType.TASK_SKIPPED:
                icon = "⏭️"
                action = "SKIPPED"
                skips += 1
            else:
                icon = "🚫"
                action = "BLOCKED"
                blocks += 1

            click.echo(f"[{timestamp}] {icon} Task {task} {action}")
            click.echo(f"    Workflow: {workflow}")

            if event.data:
                if event.data.get('reason'):
                    click.echo(f"    Reason: {event.data['reason']}")
                if event.data.get('validation_task'):
                    click.echo(f"    Validation: {event.data['validation_task']}")

        # Summary
        click.echo(f"\n📊 Summary:")
        click.echo(f"  Tasks skipped: {skips}")
        click.echo(f"  Tasks blocked: {blocks}")

    finally:
        redis.close()
        await redis.wait_closed()


@monitor.command()
@click.option('--hours', '-h', default=1, type=float,
              help='Time window in hours')
@click.option('--min-count', '-m', default=5,
              help='Minimum executions to show')
@click.option('--redis-url', default='redis://localhost:6379',
              help='Redis connection URL')
async def hotpaths(hours: float, min_count: int, redis_url: str):
    """Show most frequently executed task paths"""
    import aioredis

    redis = await aioredis.create_redis_pool(redis_url)

    try:
        monitor = EventMonitor(redis)

        # Get hot paths
        time_window = timedelta(hours=hours)
        paths = await monitor.get_hot_paths(
            time_window=time_window,
            min_executions=min_count
        )

        if not paths:
            click.echo(f"No paths with {min_count}+ executions in the last {hours} hour(s)")
            return

        click.echo(f"\n🔥 Hot Paths (last {hours} hour(s), {min_count}+ executions):")
        click.echo("=" * 80)

        # Sort by count
        sorted_paths = sorted(paths.items(), key=lambda x: x[1], reverse=True)

        for path, count in sorted_paths[:10]:  # Top 10
            click.echo(f"\n{count} executions:")
            click.echo(f"  {path}")

    finally:
        redis.close()
        await redis.wait_closed()


@monitor.command()
@click.option('--event-type', '-e', required=True,
              help='Event type to monitor')
@click.option('--threshold', '-t', default=100,
              help='Alert threshold (events per minute)')
@click.option('--interval', '-i', default=5,
              help='Check interval in seconds')
@click.option('--redis-url', default='redis://localhost:6379',
              help='Redis connection URL')
async def watch(event_type: str, threshold: int, interval: int, redis_url: str):
    """Watch for event rate anomalies in real-time"""
    import aioredis

    redis = await aioredis.create_redis_pool(redis_url)

    try:
        monitor = EventMonitor(redis)

        # Parse event type
        try:
            et = EventType(f"task:{event_type}") if ':' not in event_type else EventType(event_type)
        except:
            click.echo(f"Unknown event type: {event_type}")
            return

        click.echo(f"👁️  Watching {event_type} (threshold: {threshold}/min)")
        click.echo("Press Ctrl+C to stop")
        click.echo("")

        while True:
            # Check rate
            exceeds = await monitor.monitor_event_rate(
                event_type=et,
                threshold=threshold,
                window=timedelta(minutes=1)
            )

            timestamp = datetime.utcnow().strftime("%H:%M:%S")

            if exceeds:
                click.echo(f"[{timestamp}] ⚠️  ALERT: {event_type} rate exceeded {threshold}/min")
            else:
                click.echo(f"[{timestamp}] ✅ {event_type} rate normal")

            await asyncio.sleep(interval)

    except KeyboardInterrupt:
        click.echo("\nStopped watching")
    finally:
        redis.close()
        await redis.wait_closed()


def add_monitor_commands(cli):
    """Add monitor commands to main CLI"""
    cli.add_command(monitor)