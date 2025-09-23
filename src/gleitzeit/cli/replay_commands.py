"""
CLI commands for workflow replay functionality
"""

import click
import asyncio
import json
from typing import Optional
from datetime import datetime

from ..core.event_store import EventStore
from ..workers.replay_worker import ReplayMode


@click.group()
def replay():
    """Workflow replay commands"""
    pass


@replay.command()
@click.argument('workflow_id')
@click.option('--mode', '-m', type=click.Choice(['full', 'from_task', 'failed_only', 'deterministic', 're_evaluate', 'debug']),
              default='full', help='Replay mode')
@click.option('--from-task', help='Task ID to start replay from (for from_task mode)')
@click.option('--use-cache/--no-cache', default=True, help='Use cached results where possible')
@click.option('--replay-validations/--keep-validations', default=False,
              help='Whether to re-evaluate validation tasks')
@click.option('--redis-url', default='redis://localhost:6379', help='Redis connection URL')
async def start(workflow_id: str, mode: str, from_task: Optional[str], use_cache: bool,
                replay_validations: bool, redis_url: str):
    """Start a workflow replay"""
    import aioredis

    # Connect to Redis
    redis = await aioredis.create_redis_pool(redis_url)

    try:
        # Submit replay request
        import uuid
        replay_id = f"replay_{uuid.uuid4().hex[:12]}"

        await redis.xadd(
            b"replay:request",
            {
                b"workflow_id": workflow_id.encode(),
                b"mode": mode.encode(),
                b"start_from": (from_task or '').encode(),
                b"use_cached_results": str(use_cache).encode(),
                b"replay_validations": str(replay_validations).encode(),
                b"replay_id": replay_id.encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        click.echo(f"Replay request submitted: {replay_id}")
        click.echo(f"  Workflow: {workflow_id}")
        click.echo(f"  Mode: {mode}")
        if from_task:
            click.echo(f"  Starting from: {from_task}")
        click.echo(f"  Use cache: {use_cache}")
        click.echo(f"  Replay validations: {replay_validations}")

    finally:
        redis.close()
        await redis.wait_closed()


@replay.command()
@click.argument('workflow_id')
@click.option('--task', '-t', help='Show timeline for specific task only')
@click.option('--level', '-l', type=click.Choice(['debug', 'detail', 'important', 'critical']),
              default='important', help='Minimum event level to show')
@click.option('--redis-url', default='redis://localhost:6379', help='Redis connection URL')
async def timeline(workflow_id: str, task: Optional[str], level: str, redis_url: str):
    """Show workflow or task execution timeline"""
    import aioredis

    # Connect to Redis
    redis = await aioredis.create_redis_pool(redis_url)

    try:
        # Get event store
        from ..core.event_store import EventLevel
        event_store = EventStore(redis)

        # Get timeline - either full workflow or specific task
        if task:
            events = await event_store.get_task_timeline(workflow_id, task)
            if not events:
                click.echo(f"No events found for task {task} in workflow {workflow_id}")
                return
            click.echo(f"\nTimeline for task {task} in workflow {workflow_id}:")
        else:
            min_level = EventLevel(level)
            events = await event_store.get_timeline(workflow_id, min_level=min_level)
            if not events:
                click.echo(f"No events found for workflow {workflow_id}")
                return
            click.echo(f"\nTimeline for workflow {workflow_id}:")

        click.echo("=" * 80)

        for event in events:
            timestamp = event.timestamp
            task_id = event.task_id or "N/A"
            event_type = event.event_type.value if hasattr(event.event_type, 'value') else event.event_type

            # Format based on event type
            if 'task:ready' in event_type:
                click.echo(f"[{timestamp}] ⏳ Task {task_id} READY")
                if event.data.get('is_initial'):
                    click.echo(f"    Initial task (no dependencies)")
                elif event.data.get('triggered_by'):
                    click.echo(f"    Triggered by: {event.data['triggered_by']}")

            elif 'task:started' in event_type:
                click.echo(f"[{timestamp}] 🚀 Task {task_id} STARTED")
                if event.data.get('protocol'):
                    click.echo(f"    Protocol: {event.data['protocol']}")
                if event.data.get('execution_id'):
                    click.echo(f"    Execution ID: {event.data['execution_id']}")

            elif 'task:completed' in event_type:
                click.echo(f"[{timestamp}] ✅ Task {task_id} COMPLETED")
                if event.data.get('result'):
                    result_str = json.dumps(event.data['result'], indent=2)
                    if len(result_str) > 200:
                        result_str = result_str[:200] + "..."
                    click.echo(f"    Result: {result_str}")

            elif 'task:failed' in event_type:
                click.echo(f"[{timestamp}] ❌ Task {task_id} FAILED")
                if event.data.get('error'):
                    click.echo(f"    Error: {event.data['error']}")

            elif 'task:skipped' in event_type:
                click.echo(f"[{timestamp}] ⏭️  Task {task_id} SKIPPED")
                if event.data.get('reason'):
                    click.echo(f"    Reason: {event.data['reason']}")
                if event.data.get('validation_task'):
                    click.echo(f"    Validation: {event.data['validation_task']}")

            elif 'task:cancelled' in event_type:
                if event.data.get('status') == 'blocked':
                    click.echo(f"[{timestamp}] 🚫 Task {task_id} BLOCKED")
                    if event.data.get('reason'):
                        click.echo(f"    Reason: {event.data['reason']}")
                else:
                    click.echo(f"[{timestamp}] ❌ Task {task_id} CANCELLED")

            elif 'workflow:started' in event_type:
                click.echo(f"[{timestamp}] 🏁 Workflow STARTED")

            elif 'workflow:completed' in event_type:
                click.echo(f"[{timestamp}] 🎉 Workflow COMPLETED")
                if event.data.get('completed_tasks'):
                    click.echo(f"    Completed: {event.data['completed_tasks']} tasks")
                if event.data.get('skipped_tasks', 0) > 0:
                    click.echo(f"    Skipped: {event.data['skipped_tasks']} tasks")
                if event.data.get('blocked_tasks', 0) > 0:
                    click.echo(f"    Blocked: {event.data['blocked_tasks']} tasks")

            elif 'workflow:failed' in event_type:
                click.echo(f"[{timestamp}] 💥 Workflow FAILED")
                if event.data.get('failed_tasks', 0) > 0:
                    click.echo(f"    Failed: {event.data['failed_tasks']} tasks")
                if event.data.get('blocked_tasks', 0) > 0:
                    click.echo(f"    Blocked: {event.data['blocked_tasks']} tasks")

            elif 'workflow:resumed' in event_type:
                click.echo(f"[{timestamp}] 🔄 Workflow REPLAYING")
                if event.data.get('replay_id'):
                    click.echo(f"    Replay ID: {event.data['replay_id']}")

            else:
                click.echo(f"[{timestamp}] {event_type}: Task {task_id}")

            if event.is_replay:
                click.echo(f"    [REPLAY: {event.replay_id}]")

        # Get summary
        summary = await event_store.get_execution_summary(workflow_id)
        click.echo("\n" + "=" * 80)
        click.echo("Summary:")
        click.echo(f"  Total events: {summary.get('total_events', 0)}")
        click.echo(f"  Tasks started: {summary.get('tasks_started', 0)}")
        click.echo(f"  Tasks completed: {summary.get('tasks_completed', 0)}")
        click.echo(f"  Tasks failed: {summary.get('tasks_failed', 0)}")
        click.echo(f"  Tasks skipped: {summary.get('tasks_skipped', 0)}")
        if summary.get('validation_tasks'):
            click.echo(f"  Validation tasks: {summary['validation_tasks']}")
        if summary.get('replay_events'):
            click.echo(f"  Replay events: {summary['replay_events']}")

    finally:
        redis.close()
        await redis.wait_closed()


@replay.command()
@click.argument('workflow_id')
@click.argument('task_id')
@click.option('--redis-url', default='redis://localhost:6379', help='Redis connection URL')
async def task_details(workflow_id: str, task_id: str, redis_url: str):
    """Show detailed execution info for a specific task"""
    import aioredis

    # Connect to Redis
    redis = await aioredis.create_redis_pool(redis_url)

    try:
        event_store = EventStore(redis)

        # Get task execution details
        details = await event_store.get_task_execution_details(workflow_id, task_id)

        if details['status'] == 'unknown':
            click.echo(f"No execution found for task {task_id} in workflow {workflow_id}")
            return

        # Display task details
        click.echo(f"\n📊 Task Execution Details")
        click.echo("=" * 60)
        click.echo(f"Task ID: {task_id}")
        click.echo(f"Workflow ID: {workflow_id}")
        click.echo(f"Status: {details['status'].upper()}")

        if details['is_validation']:
            click.echo("Type: Validation Task")

        if details['protocol']:
            click.echo(f"Protocol: {details['protocol']}")

        if details['execution_id']:
            click.echo(f"Execution ID: {details['execution_id']}")

        # Timing information
        if details['start_time']:
            click.echo(f"\n⏱️  Timing:")
            click.echo(f"  Started: {details['start_time']}")
            if details['end_time']:
                click.echo(f"  Ended: {details['end_time']}")
                if details['duration_ms']:
                    click.echo(f"  Duration: {details['duration_ms']}ms")

        # Result or error
        if details['status'] == 'completed' and details['result'] is not None:
            click.echo(f"\n✅ Result:")
            result_str = json.dumps(details['result'], indent=2)
            if len(result_str) > 500:
                result_str = result_str[:500] + "\n..."
            click.echo(f"  {result_str}")

        elif details['status'] == 'failed' and details['error']:
            click.echo(f"\n❌ Error:")
            click.echo(f"  {details['error']}")

        elif details['status'] in ['skipped', 'blocked']:
            click.echo(f"\n⏭️  Skip Reason:")
            click.echo(f"  {details['skip_reason']}")
            if details['validation_task']:
                click.echo(f"  Validation Task: {details['validation_task']}")

        # Retry information
        if details['retry_count'] > 0:
            click.echo(f"\n🔄 Retries: {details['retry_count']}")

        # Event history
        if details['events']:
            click.echo(f"\n📜 Event History ({len(details['events'])} events):")
            for event in details['events']:
                event_type = event['type']
                timestamp = event['timestamp']

                # Format event type for display
                if 'started' in event_type.lower():
                    icon = "🚀"
                elif 'completed' in event_type.lower():
                    icon = "✅"
                elif 'failed' in event_type.lower():
                    icon = "❌"
                elif 'skipped' in event_type.lower():
                    icon = "⏭️"
                elif 'ready' in event_type.lower():
                    icon = "⏳"
                else:
                    icon = "📍"

                click.echo(f"  [{timestamp}] {icon} {event_type}")

    finally:
        redis.close()
        await redis.wait_closed()


@replay.command()
@click.argument('workflow_id')
@click.option('--redis-url', default='redis://localhost:6379', help='Redis connection URL')
async def status(workflow_id: str, redis_url: str):
    """Show replay status for a workflow"""
    import aioredis

    # Connect to Redis
    redis = await aioredis.create_redis_pool(redis_url)

    try:
        # Get replay metadata
        from ..core.sharding import default_sharding
        replay_data = await redis.hgetall(
            default_sharding.get_workflow_key("replay", workflow_id).encode()
        )

        if not replay_data:
            click.echo(f"No replay information found for workflow {workflow_id}")
            return

        click.echo(f"\nReplay status for workflow {workflow_id}:")
        click.echo("=" * 60)

        if b"replay_id" in replay_data:
            click.echo(f"Replay ID: {replay_data[b'replay_id'].decode()}")
        if b"mode" in replay_data:
            click.echo(f"Mode: {replay_data[b'mode'].decode()}")
        if b"started_at" in replay_data:
            click.echo(f"Started at: {replay_data[b'started_at'].decode()}")
        if b"tasks_cleared" in replay_data:
            tasks_cleared = json.loads(replay_data[b'tasks_cleared'].decode())
            click.echo(f"Tasks cleared for replay: {len(tasks_cleared)}")
            for task_id in tasks_cleared[:10]:  # Show first 10
                click.echo(f"  - {task_id}")
            if len(tasks_cleared) > 10:
                click.echo(f"  ... and {len(tasks_cleared) - 10} more")

    finally:
        redis.close()
        await redis.wait_closed()


@replay.command()
@click.argument('workflow_id1')
@click.argument('workflow_id2')
@click.option('--redis-url', default='redis://localhost:6379', help='Redis connection URL')
async def diff(workflow_id1: str, workflow_id2: str, redis_url: str):
    """Compare two workflow executions"""
    import aioredis

    # Connect to Redis
    redis = await aioredis.create_redis_pool(redis_url)

    try:
        event_store = EventStore(redis)

        # Get timelines for both workflows
        timeline1 = await event_store.get_timeline(workflow_id1)
        timeline2 = await event_store.get_timeline(workflow_id2)

        # Get task execution orders
        tasks1 = await event_store.get_task_execution_order(workflow_id1)
        tasks2 = await event_store.get_task_execution_order(workflow_id2)

        click.echo(f"\nComparing workflows:")
        click.echo(f"  Workflow 1: {workflow_id1}")
        click.echo(f"  Workflow 2: {workflow_id2}")
        click.echo("=" * 60)

        # Compare execution order
        click.echo("\nExecution Order:")
        max_len = max(len(tasks1), len(tasks2))
        for i in range(max_len):
            task1 = tasks1[i] if i < len(tasks1) else "---"
            task2 = tasks2[i] if i < len(tasks2) else "---"

            if task1 == task2:
                click.echo(f"  [{i+1}] ✅ {task1}")
            else:
                click.echo(f"  [{i+1}] ❌ {task1} != {task2}")

        # Compare summaries
        summary1 = await event_store.get_execution_summary(workflow_id1)
        summary2 = await event_store.get_execution_summary(workflow_id2)

        click.echo("\nExecution Summary:")
        click.echo(f"  Tasks completed: {summary1.get('tasks_completed', 0)} vs {summary2.get('tasks_completed', 0)}")
        click.echo(f"  Tasks failed: {summary1.get('tasks_failed', 0)} vs {summary2.get('tasks_failed', 0)}")
        click.echo(f"  Tasks skipped: {summary1.get('tasks_skipped', 0)} vs {summary2.get('tasks_skipped', 0)}")

        # Check if one is a replay of the other
        replay_events1 = summary1.get('replay_events', 0)
        replay_events2 = summary2.get('replay_events', 0)
        if replay_events2 > 0:
            click.echo(f"\n📌 Workflow 2 appears to be a replay ({replay_events2} replay events)")
        if replay_events1 > 0:
            click.echo(f"\n📌 Workflow 1 appears to be a replay ({replay_events1} replay events)")

    finally:
        redis.close()
        await redis.wait_closed()


def add_replay_commands(cli):
    """Add replay commands to main CLI"""
    cli.add_command(replay)