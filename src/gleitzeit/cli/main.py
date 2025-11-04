#!/usr/bin/env python
"""
Gleitzeit 0.0.7 CLI - Worker-based Architecture

Main command-line interface for managing workers and workflows.
"""

import sys
import os
from pathlib import Path

# Check if running in proper uv environment (optional warning, not required)
if not sys.prefix.endswith('.venv'):
    print("", file=sys.stderr)
    print("⚠️  Gleitzeit is running outside a virtual environment", file=sys.stderr)
    print("", file=sys.stderr)
    print("💡 Recommendation: Use UV for better dependency management:", file=sys.stderr)
    print("   uv venv && uv sync && uv run gleitzeit <command>", file=sys.stderr)
    print("", file=sys.stderr)
    print("   Learn more: https://docs.astral.sh/uv/", file=sys.stderr)
    print("", file=sys.stderr)
    # Continue execution - don't exit!

import click
import asyncio
import json
import subprocess
import logging
import uuid
from typing import Optional
from datetime import datetime
import redis.asyncio as aioredis
import yaml
from ..core.sharding import default_sharding
from .serve import serve
from .serve_v3 import serve_v3
from .serve_unified import serve_unified
from .serve_docker import serve_with_docker, DockerOrchestrator
from .process_commands import add_process_commands
from .logs_command import logs
from .scale_command import scale
from .stop_command import stop
from .clean_command import clean
from .ps_command import ps as ps_new

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@click.group()
@click.option('--redis-url', default='redis://localhost:6379', help='Redis connection URL')
@click.pass_context
def cli(ctx, redis_url):
    """Gleitzeit 0.0.7 - Distributed Workflow Orchestration"""
    ctx.ensure_object(dict)
    ctx.obj['redis_url'] = redis_url


# ============= Orchestrator Commands =============

# Removed: Use 'gleitzeit serve' instead
# Start command removed in favor of unified 'serve' command


@cli.command('status')
@click.pass_context
def status(ctx):
    """Check system status (shortcut for orchestrator status)"""
    ctx.forward(orchestrator_status)


@cli.command('submit')
@click.argument('workflow_files', nargs=-1, type=click.Path(exists=True))
@click.option('--format', 'file_format', type=click.Choice(['yaml', 'json', 'python']), help='Workflow format')
@click.option('--auto-start/--no-auto-start', default=True, help='Auto-start orchestrator if not running')
@click.option('--pattern', help='Glob pattern for batch submission (e.g., "*.yaml")')
@click.pass_context
def submit(ctx, workflow_files, file_format, auto_start, pattern):
    """Submit one or more workflows (auto-starts orchestrator if needed)

    Examples:
        gleitzeit submit workflow.yaml
        gleitzeit submit workflow1.yaml workflow2.yaml workflow3.yaml
        gleitzeit submit --pattern "*.yaml"
        gleitzeit submit workflows/*.yaml
    """

    async def check_and_submit():
        # Check if orchestrator is running
        redis = await aioredis.from_url(ctx.obj['redis_url'])

        orchestrator_running = False
        try:
            # Check for orchestrator PID
            pid_data = await redis.get(b"orchestrator:pid")
            if pid_data:
                pid = int(pid_data)
                # Check if process is actually running
                try:
                    import psutil
                    if psutil.pid_exists(pid):
                        orchestrator_running = True
                        click.echo(f"✅ Orchestrator is running (PID: {pid})")
                    else:
                        # Clean up stale PID
                        await redis.delete(b"orchestrator:pid")
                except ImportError:
                    # psutil not installed, try basic OS check
                    try:
                        os.kill(pid, 0)  # Signal 0 = check if process exists
                        orchestrator_running = True
                        click.echo(f"✅ Orchestrator is running (PID: {pid})")
                    except (OSError, ProcessLookupError):
                        # Process doesn't exist, clean up stale PID
                        await redis.delete(b"orchestrator:pid")

            # Also check for recent worker activity
            if not orchestrator_running:
                metrics = await redis.hget(b"orchestrator:metrics", b"latest")
                if metrics:
                    import json
                    from datetime import datetime
                    data = json.loads(metrics)
                    # Check if metrics are recent (within last 60 seconds)
                    if 'timestamp' in data:
                        last_update = datetime.fromisoformat(data['timestamp'])
                        age = (datetime.utcnow() - last_update).total_seconds()
                        if age < 60:
                            orchestrator_running = True
                            click.echo("✅ Orchestrator appears to be running (recent activity)")

        except Exception as e:
            click.echo(f"⚠️  Error checking orchestrator status: {e}")

        await redis.aclose()

        # Start orchestrator if needed and auto-start is enabled
        if not orchestrator_running:
            if auto_start:
                click.echo("🔄 Orchestrator not running, starting it now...")

                # Start orchestrator in background
                import subprocess
                import sys

                # Find config file
                config_paths = [
                    'gleitzeit.yaml',
                    'config/gleitzeit.yaml',
                    '/etc/gleitzeit/gleitzeit.yaml',
                    os.path.expanduser('~/.gleitzeit/config.yaml')
                ]

                config_file = None
                for path in config_paths:
                    if os.path.exists(path):
                        config_file = path
                        break

                # Start orchestrator as subprocess
                cmd = [sys.executable, "-m", "gleitzeit.cli.main", "orchestrator", "start"]
                if config_file:
                    cmd.extend(["--config", config_file])
                    click.echo(f"   Using config: {config_file}")

                # Get current PYTHONPATH
                import sys
                current_pythonpath = os.environ.get('PYTHONPATH', '')
                gleitzeit_src = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

                # Create environment with proper PYTHONPATH
                env = os.environ.copy()
                if current_pythonpath:
                    env['PYTHONPATH'] = f"{gleitzeit_src}:{current_pythonpath}"
                else:
                    env['PYTHONPATH'] = gleitzeit_src

                # Create log file for debugging
                from datetime import datetime
                log_file = "gleitzeit_orchestrator.log"
                with open(log_file, 'a') as log:
                    log.write(f"\n{'='*60}\n")
                    log.write(f"Starting orchestrator at {datetime.utcnow().isoformat()}\n")
                    log.write(f"Command: {' '.join(cmd)}\n")
                    log.write(f"PYTHONPATH: {env.get('PYTHONPATH', 'Not set')}\n")
                    log.write(f"{'='*60}\n")

                # Start in background (detached)
                with open(log_file, 'a') as log_out:
                    if sys.platform == "win32":
                        # Windows
                        process = subprocess.Popen(
                            cmd,
                            stdout=log_out,
                            stderr=subprocess.STDOUT,
                            env=env,
                            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                        )
                    else:
                        # Unix/Linux/Mac
                        process = subprocess.Popen(
                            cmd,
                            stdout=log_out,
                            stderr=subprocess.STDOUT,
                            env=env,
                            start_new_session=True
                        )

                click.echo(f"📦 Started orchestrator in background (PID: {process.pid})")
                click.echo("⏳ Waiting for orchestrator to initialize...")

                # Wait for orchestrator to be ready
                redis_check = await aioredis.from_url(ctx.obj['redis_url'])
                ready = False
                for i in range(10):  # Wait up to 10 seconds
                    await asyncio.sleep(1)
                    # Check if orchestrator has stored its PID
                    pid_check = await redis_check.get(b"orchestrator:pid")
                    if pid_check:
                        ready = True
                        click.echo("✅ Orchestrator is ready!")
                        break
                    if i == 2:
                        click.echo("   Still initializing...")

                await redis_check.aclose()

                if not ready:
                    click.echo("⚠️  Orchestrator is taking longer than expected to start")
                    click.echo("   Check logs for any issues")
            else:
                click.echo("❌ Orchestrator is not running. Start it with:")
                click.echo("   gleitzeit start")
                click.echo("\nOr use --auto-start flag to start automatically")
                return

        # Collect files to submit
        files_to_submit = []

        # If pattern is provided, use glob
        if pattern:
            import glob
            files_to_submit.extend(glob.glob(pattern))
            if not files_to_submit:
                click.echo(f"❌ No files found matching pattern: {pattern}")
                return
        else:
            # Use provided files
            files_to_submit = list(workflow_files)

        if not files_to_submit:
            click.echo("❌ No workflow files specified")
            click.echo("   Use: gleitzeit submit <files> or --pattern '<pattern>'")
            return

        # Now submit the workflows
        if len(files_to_submit) == 1:
            click.echo(f"\n📤 Submitting workflow: {files_to_submit[0]}")
        else:
            click.echo(f"\n📤 Submitting {len(files_to_submit)} workflows...")

        # Submit workflows inline (to avoid nested asyncio.run)
        redis = await aioredis.from_url(ctx.obj['redis_url'])

        submitted = []
        from ..core.sharding import default_sharding

        for workflow_file in files_to_submit:
            # Detect format
            fmt = file_format
            if not fmt:
                if workflow_file.endswith('.yaml') or workflow_file.endswith('.yml'):
                    fmt = 'yaml'
                elif workflow_file.endswith('.json'):
                    fmt = 'json'
                elif workflow_file.endswith('.py'):
                    fmt = 'python'
                else:
                    fmt = 'yaml'

            # Generate workflow ID
            workflow_id = f"workflow_{uuid.uuid4().hex[:12]}"

            # Get shard
            shard = default_sharding.get_shard(workflow_id)

            # Submit to workflow:load stream
            await redis.xadd(
                default_sharding.get_stream_key("workflow:load", workflow_id=workflow_id).encode(),
                {
                    b"workflow_id": workflow_id.encode(),
                    b"path": workflow_file.encode(),
                    b"format": fmt.encode()
                }
            )

            submitted.append((workflow_id, shard, workflow_file))

            if len(files_to_submit) <= 5:
                # Show details for small batches
                click.echo(f"  ✅ {workflow_id} -> shard {shard} ({os.path.basename(workflow_file)})")

        # Show summary
        if len(submitted) > 5:
            click.echo(f"\n✅ Submitted {len(submitted)} workflows")
            # Show shard distribution
            shard_counts = {}
            for _, shard, _ in submitted:
                shard_counts[shard] = shard_counts.get(shard, 0) + 1
            click.echo("   Shard distribution:")
            for shard in sorted(shard_counts.keys()):
                click.echo(f"     Shard {shard}: {shard_counts[shard]} workflows")
        elif len(submitted) == 1:
            wf_id, shard, _ = submitted[0]
            click.echo(f"✅ Workflow submitted: {wf_id}")
            click.echo(f"   Assigned to shard: {shard}")

        await redis.aclose()

    asyncio.run(check_and_submit())


@cli.command('stop-legacy')
@click.option('--graceful/--force', default=True, help='Graceful or forced shutdown')
@click.pass_context
def stop_legacy(ctx, graceful):
    """Stop Gleitzeit"""
    async def shutdown():
        import os
        import signal as sig

        redis = await aioredis.from_url(ctx.obj['redis_url'])

        # Find orchestrator PID from Redis or file
        pid_data = await redis.get(b"orchestrator:pid")
        if pid_data:
            pid = int(pid_data)
            click.echo(f"🛑 Stopping Gleitzeit orchestrator (PID: {pid})")

            try:
                if graceful:
                    os.kill(pid, sig.SIGTERM)
                    click.echo("Sent graceful shutdown signal")
                else:
                    os.kill(pid, sig.SIGKILL)
                    click.echo("Sent force shutdown signal")
            except ProcessLookupError:
                click.echo("Process not found - may already be stopped")
        else:
            click.echo("No running orchestrator found")

        await redis.aclose()

    asyncio.run(shutdown())


@cli.group()
@click.pass_context
def orchestrator(ctx):
    """Manage the component orchestrator"""
    pass


@orchestrator.command('start')
@click.option('--config', type=click.Path(exists=True), default='gleitzeit.yaml', help='Configuration file (default: gleitzeit.yaml)')
@click.option('--workers', default='default', help='Worker configuration preset')
@click.pass_context
def orchestrator_start(ctx, config, workers):
    """Start the component orchestrator"""
    async def run():
        from ..orchestrator.component_orchestrator import ComponentOrchestrator
        import os

        # Load config - try default locations if not specified
        config_data = {}
        config_paths = []

        if config and os.path.exists(config):
            config_paths = [config]
        else:
            # Try multiple default locations
            config_paths = [
                'gleitzeit.yaml',
                'config/gleitzeit.yaml',
                '/etc/gleitzeit/gleitzeit.yaml',
                os.path.expanduser('~/.gleitzeit/config.yaml')
            ]

        config_loaded = False
        for path in config_paths:
            if os.path.exists(path):
                click.echo(f"📄 Loading configuration from: {path}")
                with open(path) as f:
                    config_data = yaml.safe_load(f)
                config_loaded = True
                break

        if not config_loaded:
            click.echo("⚠️  No configuration file found, using defaults")
            click.echo("   Create gleitzeit.yaml for custom configuration")

        # Create and start orchestrator
        orch = ComponentOrchestrator(
            redis_url=ctx.obj['redis_url'],
            config=config_data
        )

        await orch.initialize()
        click.echo("🚀 Component Orchestrator started")
        click.echo(f"Managing workers: {', '.join(orch.worker_specs.keys())}")

        await orch.start()

    asyncio.run(run())


@orchestrator.command('status')
@click.pass_context
def orchestrator_status(ctx):
    """Check orchestrator and worker status"""
    async def check_status():
        redis = await aioredis.from_url(ctx.obj['redis_url'])

        # Get orchestrator metrics
        metrics = await redis.hget(b"orchestrator:metrics", b"latest")
        if metrics:
            data = json.loads(metrics)
            click.echo("\n📊 Orchestrator Status:")
            click.echo(f"  System CPU: {data['system']['cpu_percent']}%")
            click.echo(f"  System Memory: {data['system']['memory_percent']}%")
            click.echo(f"  Redis: {'✅ Healthy' if data['system']['redis_healthy'] else '❌ Unhealthy'}")

            click.echo("\n👷 Workers:")
            for worker_id, worker_metrics in data['workers'].items():
                click.echo(f"  {worker_id}:")
                click.echo(f"    Processed: {worker_metrics.get('processed', 0)}")
                click.echo(f"    Failed: {worker_metrics.get('failed', 0)}")

            click.echo("\n📦 Queue Depths:")
            for worker_type, queue_data in data['queues'].items():
                click.echo(f"  {worker_type}: {queue_data['total_pending']} pending")
        else:
            click.echo("❌ No orchestrator metrics found. Is it running?")

        await redis.aclose()

    asyncio.run(check_status())


# ============= Worker Commands =============

@cli.group()
@click.pass_context
def worker(ctx):
    """Manage individual workers"""
    pass


@worker.command('start')
@click.option('--type', 'worker_type', required=True,
              type=click.Choice(['task_execution', 'dependency', 'workflow_loader']),
              help='Type of worker to start')
@click.option('--id', 'worker_id', help='Worker ID (auto-generated if not provided)')
@click.option('--shards', help='Comma-separated shard numbers')
@click.option('--count', default=1, help='Number of workers to start')
@click.pass_context
def worker_start(ctx, worker_type, worker_id, shards, count):
    """Start worker instances directly"""
    async def run():
        from ..workers.runner import run_worker
        import uuid

        # Map worker types to classes
        worker_classes = {
            'task_execution': 'gleitzeit.workers.task_execution_worker.TaskExecutionWorker',
            'dependency': 'gleitzeit.workers.dependency_worker.DependencyWorker',
            'workflow_loader': 'gleitzeit.workers.workflow_loader_worker.WorkflowLoaderWorker'
        }

        worker_class = worker_classes[worker_type]

        if count > 1:
            # Start multiple workers
            tasks = []
            for i in range(count):
                wid = f"{worker_type}-{i}"
                args = type('Args', (), {
                    'worker_class': worker_class,
                    'worker_id': wid,
                    'worker_type': worker_type,
                    'redis_url': ctx.obj['redis_url'],
                    'shards': shards,
                    'consumer_group': f"{worker_type}-group",
                    'max_concurrent': 10,
                    'batch_size': 10,
                    'block_timeout': 5000,
                    'heartbeat_interval': 30
                })()
                tasks.append(run_worker(args))

            click.echo(f"🚀 Starting {count} {worker_type} workers...")
            await asyncio.gather(*tasks)
        else:
            # Start single worker
            wid = worker_id or f"{worker_type}-{uuid.uuid4().hex[:8]}"
            args = type('Args', (), {
                'worker_class': worker_class,
                'worker_id': wid,
                'worker_type': worker_type,
                'redis_url': ctx.obj['redis_url'],
                'shards': shards,
                'consumer_group': f"{worker_type}-group",
                'max_concurrent': 10,
                'batch_size': 10,
                'block_timeout': 5000,
                'heartbeat_interval': 30
            })()

            click.echo(f"🚀 Starting {worker_type} worker: {wid}")
            await run_worker(args)

    asyncio.run(run())


@worker.command('list')
@click.pass_context
def worker_list(ctx):
    """List all registered workers"""
    async def list_workers():
        redis = await aioredis.from_url(ctx.obj['redis_url'])

        # Find all worker registry keys
        # Worker registry is on shard 0
        pattern = b"{shard:0}:worker:registry:*"
        keys = []
        cursor = b"0"
        while cursor != b"0" or not keys:
            cursor, batch = await redis.scan(cursor, match=pattern)
            keys.extend(batch)
            if cursor == b"0":
                break

        if not keys:
            click.echo("No workers found")
            return

        click.echo("\n🔧 Registered Workers:")
        click.echo("-" * 70)

        for key in keys:
            data = await redis.hgetall(key)
            if data:
                worker_type = data.get(b"worker_type", b"unknown").decode()
                worker_id = data.get(b"worker_id", b"unknown").decode()
                state = data.get(b"state", b"unknown").decode()
                shards = data.get(b"shards", b"[]").decode()
                started = data.get(b"started_at", b"").decode()

                click.echo(f"\n  Worker: {worker_id}")
                click.echo(f"    Type: {worker_type}")
                click.echo(f"    State: {state}")
                click.echo(f"    Shards: {shards}")
                click.echo(f"    Started: {started}")

        await redis.aclose()

    asyncio.run(list_workers())


@worker.command('stop')
@click.argument('worker_name', required=True)
@click.option('--force', is_flag=True, help='Force kill immediately (SIGKILL) instead of graceful shutdown')
@click.option('--timeout', type=int, default=10, help='Timeout for graceful shutdown in seconds')
@click.pass_context
def worker_stop(ctx, worker_name: str, force: bool, timeout: int):
    """
    Stop a specific worker by name or type.

    Works for both Docker and native workers.

    \b
    Examples:
        gleitzeit worker stop worker_api              # Stop API worker
        gleitzeit worker stop task_execution          # Stop all task_execution workers
        gleitzeit worker stop worker_task_execution-1 # Stop specific worker instance
        gleitzeit worker stop api --force             # Force kill API worker

    \b
    Arguments:
        WORKER_NAME: Worker name (e.g., 'api', 'worker_api') or type (e.g., 'task_execution')
    """
    import subprocess
    import psutil
    from pathlib import Path

    stopped_count = 0

    # Normalize worker name (handle both 'api' and 'worker_api' formats)
    if not worker_name.startswith('worker_'):
        worker_search = f"worker_{worker_name}"
    else:
        worker_search = worker_name

    # Also search for the base name without 'worker_' prefix
    base_name = worker_name.replace('worker_', '')

    click.echo(f"🔍 Searching for workers matching: {worker_name}")

    # 1. Check for Docker containers
    docker_stopped = 0
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            containers = [c for c in result.stdout.strip().split('\n') if c]
            matching_containers = [
                c for c in containers
                if worker_search.lower() in c.lower() or base_name.lower() in c.lower()
            ]

            if matching_containers:
                click.echo(f"\n🐳 Found {len(matching_containers)} Docker container(s):")
                for container in matching_containers:
                    click.echo(f"   - {container}")
                    try:
                        if force:
                            click.echo(f"   Force killing: {container}")
                            subprocess.run(["docker", "kill", container],
                                         capture_output=True, timeout=5)
                        else:
                            click.echo(f"   Stopping: {container}")
                            subprocess.run(["docker", "stop", "-t", str(timeout), container],
                                         capture_output=True, timeout=timeout + 5)
                        docker_stopped += 1
                    except Exception as e:
                        click.echo(f"   ⚠️  Error: {e}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # Docker not available

    # 2. Check for native processes
    native_stopped = 0
    processes_to_stop = []

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if not cmdline:
                continue

            cmdline_str = ' '.join(cmdline)

            # Check if it's a matching gleitzeit worker process
            if 'python' in cmdline_str and 'gleitzeit.workers.runner' in cmdline_str:
                # Check if worker name matches in the command line
                if (worker_search.lower() in cmdline_str.lower() or
                    base_name.lower() in cmdline_str.lower()):
                    processes_to_stop.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if processes_to_stop:
        click.echo(f"\n🔧 Found {len(processes_to_stop)} native process(es):")
        for proc in processes_to_stop:
            click.echo(f"   - PID {proc.pid}")
            try:
                if force:
                    click.echo(f"   Force killing PID {proc.pid}")
                    proc.kill()
                else:
                    click.echo(f"   Terminating PID {proc.pid}")
                    proc.terminate()
                native_stopped += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                click.echo(f"   ⚠️  Error: {e}")

        # Wait for graceful shutdown if not forcing
        if not force and processes_to_stop:
            click.echo(f"\n⏳ Waiting up to {timeout}s for graceful shutdown...")
            gone, alive = psutil.wait_procs(processes_to_stop, timeout=timeout)

            if alive:
                click.echo(f"   {len(alive)} process(es) still running, force killing...")
                for proc in alive:
                    try:
                        proc.kill()
                        click.echo(f"   Force killed PID {proc.pid}")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

    # 3. Clean up Redis registry for stopped workers
    if native_stopped > 0 or docker_stopped > 0:
        try:
            import redis
            r = redis.Redis(host='localhost', port=6379, decode_responses=True)

            cleaned = 0
            # Scan for all worker registry keys
            for key in r.scan_iter(match="{shard:0}:worker:registry:*"):
                try:
                    # Get worker info
                    worker_data = r.hgetall(key)
                    if not worker_data:
                        continue

                    worker_id = worker_data.get('worker_id', '')
                    worker_type = worker_data.get('worker_type', '')
                    pid_str = worker_data.get('pid', '')

                    # Check if this worker matches our search
                    matches = (worker_search.lower() in worker_id.lower() or
                              worker_search.lower() in worker_type.lower() or
                              base_name.lower() in worker_type.lower())

                    if not matches:
                        continue

                    # Check if the process is still running
                    process_dead = True
                    if pid_str:
                        try:
                            pid = int(pid_str)
                            psutil.Process(pid)  # Will raise NoSuchProcess if dead
                            process_dead = False  # Process still alive
                        except (psutil.NoSuchProcess, ValueError, OverflowError):
                            process_dead = True

                    # Only clean up if process is confirmed dead
                    if process_dead:
                        r.delete(key)
                        cleaned += 1
                        click.echo(f"   Cleaned registry: {worker_id}")

                except Exception as e:
                    # Skip individual key errors but continue cleanup
                    continue

            if cleaned > 0:
                click.echo(f"✅ Cleaned {cleaned} registry entry(ies)")

        except Exception as e:
            click.echo(f"⚠️  Registry cleanup failed: {e}")

    # Summary
    stopped_count = docker_stopped + native_stopped
    if stopped_count > 0:
        click.echo(f"\n✅ Stopped {stopped_count} worker(s)")
        if docker_stopped > 0:
            click.echo(f"   - Docker: {docker_stopped}")
        if native_stopped > 0:
            click.echo(f"   - Native: {native_stopped}")
    else:
        click.echo(f"\n⚠️  No workers found matching: {worker_name}")
        click.echo("   Use 'gleitzeit worker list' to see available workers")
        click.echo("   Use 'gleitzeit ps' to see all services")


# ============= Workflow Commands =============

@cli.group()
@click.pass_context
def workflow(ctx):
    """Manage workflows"""
    pass


@workflow.command('submit')
@click.argument('workflow_file', type=click.Path(exists=True))
@click.option('--file-format', type=click.Choice(['yaml', 'json', 'python']), help='Workflow format')
@click.pass_context
def workflow_submit(ctx, workflow_file, file_format):
    """Submit a workflow for execution"""
    async def submit():
        redis = await aioredis.from_url(ctx.obj['redis_url'])

        # Detect format
        fmt = file_format
        if not fmt:
            if workflow_file.endswith('.yaml') or workflow_file.endswith('.yml'):
                fmt = 'yaml'
            elif workflow_file.endswith('.json'):
                fmt = 'json'
            elif workflow_file.endswith('.py'):
                fmt = 'python'
            else:
                fmt = 'yaml'

        # Generate workflow ID
        workflow_id = f"workflow_{uuid.uuid4().hex[:12]}"

        # Submit to workflow:load stream
        from gleitzeit.core.sharding import default_sharding
        shard = default_sharding.get_shard(workflow_id)

        await redis.xadd(
            default_sharding.get_stream_key("workflow:load", workflow_id=workflow_id).encode(),
            {
                b"workflow_id": workflow_id.encode(),
                b"path": workflow_file.encode(),
                b"format": fmt.encode()
            }
        )

        click.echo(f"✅ Workflow submitted: {workflow_id}")
        click.echo(f"   Assigned to shard: {shard}")

        await redis.aclose()

    asyncio.run(submit())


@workflow.command('status')
@click.argument('workflow_id')
@click.pass_context
def workflow_status(ctx, workflow_id):
    """Check workflow status"""
    async def check():
        redis = await aioredis.from_url(ctx.obj['redis_url'])

        # Get workflow data first to check if workflow exists
        workflow_data = await redis.hget(
            default_sharding.get_workflow_key("data", workflow_id).encode(),
            b"workflow"
        )

        if not workflow_data:
            click.echo(f"❌ Workflow not found: {workflow_id}")
            await redis.aclose()
            return

        # Parse workflow data
        data = json.loads(workflow_data)

        # Get workflow status
        status_data = await redis.hgetall(default_sharding.get_workflow_key("status", workflow_id).encode())

        # Display workflow info
        click.echo(f"\n📋 Workflow: {workflow_id}")
        click.echo("-" * 50)
        click.echo(f"  Name: {data.get('name', 'N/A')}")
        click.echo(f"  Tasks: {len(data.get('tasks', []))}")

        # Display status if available
        if status_data:
            click.echo("\n  Status:")
            for key, value in status_data.items():
                k = key.decode()
                v = value.decode()
                click.echo(f"    {k}: {v}")
        else:
            click.echo("\n  Status: No status data available (workflow may be completed)")

        await redis.aclose()

    asyncio.run(check())


@workflow.command('list')
@click.option('--limit', default=10, help='Number of workflows to show')
@click.pass_context
def workflow_list(ctx, limit):
    """List recent workflows"""
    async def list_workflows():
        redis = await aioredis.from_url(ctx.obj['redis_url'])

        # Find workflow state keys (consolidated)
        # For listing workflows, we need to scan all shards
        pattern = b"*:workflow:state:*"
        keys = []
        cursor = b"0"
        while cursor != b"0" or not keys:
            cursor, batch = await redis.scan(cursor, match=pattern, count=limit)
            keys.extend(batch)
            if len(keys) >= limit or cursor == b"0":
                break

        if not keys:
            click.echo("No workflows found")
            return

        click.echo("\n📚 Recent Workflows:")
        click.echo("-" * 70)

        for key in keys[:limit]:
            workflow_id = key.decode().split(':')[-1]
            status_data = await redis.hgetall(key)

            if status_data:
                status = status_data.get(b"status", b"unknown").decode()
                total = status_data.get(b"total_tasks", b"0").decode()
                completed = status_data.get(b"completed_tasks", b"0").decode()

                # Get workflow name
                workflow_data = await redis.hget(
                    default_sharding.get_workflow_key("data", workflow_id).encode(),
                    b"workflow"
                )
                name = "N/A"
                if workflow_data:
                    data = json.loads(workflow_data)
                    name = data.get('name', 'N/A')

                click.echo(f"\n  {workflow_id}")
                click.echo(f"    Name: {name}")
                click.echo(f"    Status: {status}")
                click.echo(f"    Progress: {completed}/{total} tasks")

        await redis.aclose()

    asyncio.run(list_workflows())


# ============= Admin Commands =============

@cli.group()
@click.pass_context
def admin(ctx):
    """Administrative commands"""
    pass


@admin.command('clear-streams')
@click.option('--confirm', is_flag=True, help='Confirm stream clearing')
@click.pass_context
def clear_streams(ctx, confirm):
    """Clear all Redis streams (WARNING: destructive)"""
    if not confirm:
        click.echo("⚠️  This will clear all streams! Use --confirm to proceed")
        return

    async def clear():
        redis = await aioredis.from_url(ctx.obj['redis_url'])

        # Find all stream keys
        patterns = [
            b"task:*",
            b"workflow:*",
            b"dependency:*"
        ]

        total_deleted = 0
        for pattern in patterns:
            cursor = b"0"
            while True:
                cursor, keys = await redis.scan(cursor, match=pattern)
                if keys:
                    await redis.delete(*keys)
                    total_deleted += len(keys)
                if cursor == b"0":
                    break

        click.echo(f"✅ Cleared {total_deleted} stream keys")
        await redis.aclose()

    asyncio.run(clear())


@admin.command('metrics')
@click.pass_context
def show_metrics(ctx):
    """Show system metrics"""
    async def metrics():
        redis = await aioredis.from_url(ctx.obj['redis_url'])

        # Count streams by type
        stream_counts = {}
        for base in ['task:ready', 'task:completed', 'workflow:submitted']:
            total = 0
            for shard in range(16):
                length = await redis.xlen(f"{base}:{shard}".encode())
                total += length
            stream_counts[base] = total

        click.echo("\n📊 System Metrics:")
        click.echo("-" * 50)
        click.echo("\nStream Depths:")
        for stream, count in stream_counts.items():
            click.echo(f"  {stream}: {count}")

        # Worker metrics
        pattern = b"worker:metrics:*"
        cursor = b"0"
        keys = []
        while cursor != b"0" or not keys:
            cursor, batch = await redis.scan(cursor, match=pattern)
            keys.extend(batch)
            if cursor == b"0":
                break

        total_processed = 0
        total_failed = 0
        for key in keys:
            metrics = await redis.hgetall(key)
            if metrics:
                processed = int(metrics.get(b"processed", b"0").decode())
                failed = int(metrics.get(b"failed", b"0").decode())
                total_processed += processed
                total_failed += failed

        click.echo("\nWorker Totals:")
        click.echo(f"  Tasks Processed: {total_processed}")
        click.echo(f"  Tasks Failed: {total_failed}")

        if total_processed > 0:
            success_rate = ((total_processed - total_failed) / total_processed) * 100
            click.echo(f"  Success Rate: {success_rate:.1f}%")

        await redis.aclose()

    asyncio.run(metrics())


# Add the serve command to the CLI group (using v3 with Layered Architecture)
cli.add_command(serve_unified, name='serve')
cli.add_command(logs)
cli.add_command(scale)
cli.add_command(stop)
cli.add_command(clean)
cli.add_command(ps_new, name='ps')

# Add process monitoring commands
add_process_commands(cli)

# The new ps command from ps_command.py replaces this old one
# It provides better mode detection and unified Docker/native support


def main():
    """Main entry point"""
    cli(obj={})


if __name__ == '__main__':
    main()