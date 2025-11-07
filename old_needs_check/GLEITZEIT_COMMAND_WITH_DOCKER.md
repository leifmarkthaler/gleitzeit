# Using Gleitzeit Command with Docker

## Current Situation

The `gleitzeit serve` command uses the ProcessOrchestrator which has the subprocess deadlock bug. To use Gleitzeit properly, you have **three options**:

## Option 1: Use Docker Directly (Recommended)

Skip the `gleitzeit` command entirely and use Docker:

```bash
# Start everything
docker-compose -f docker-compose-proper.yml up -d

# Stop everything
docker-compose -f docker-compose-proper.yml down

# View logs
docker-compose -f docker-compose-proper.yml logs -f

# Submit workflows via API
curl -X POST http://localhost:8000/workflows/submit \
  -H "Content-Type: application/json" \
  -d @workflow.json
```

## Option 2: Create a Docker-Aware Gleitzeit Command

Create a wrapper script that uses Docker instead of ProcessOrchestrator:

### gleitzeit-docker.sh
```bash
#!/bin/bash

COMPOSE_FILE="docker-compose-proper.yml"

case "$1" in
  serve)
    echo "🚀 Starting Gleitzeit with Docker..."
    docker-compose -f $COMPOSE_FILE up -d
    echo "✅ Gleitzeit running!"
    echo "   API: http://localhost:8000"
    echo "   UI:  http://localhost:8004"
    ;;

  stop)
    echo "🛑 Stopping Gleitzeit..."
    docker-compose -f $COMPOSE_FILE down
    ;;

  status)
    docker-compose -f $COMPOSE_FILE ps
    ;;

  logs)
    docker-compose -f $COMPOSE_FILE logs -f "${@:2}"
    ;;

  submit)
    if [ -z "$2" ]; then
      echo "Usage: $0 submit <workflow.yaml>"
      exit 1
    fi
    # Convert YAML to JSON if needed, then submit
    curl -X POST http://localhost:8000/workflows/submit \
      -H "Content-Type: application/json" \
      -d @"$2"
    ;;

  workflow)
    if [ -z "$2" ]; then
      echo "Usage: $0 workflow <workflow-id>"
      exit 1
    fi
    curl http://localhost:8000/workflows/"$2" | python -m json.tool
    ;;

  *)
    echo "Usage: $0 {serve|stop|status|logs|submit|workflow}"
    echo ""
    echo "Commands:"
    echo "  serve           Start all services"
    echo "  stop            Stop all services"
    echo "  status          Show service status"
    echo "  logs [service]  View logs"
    echo "  submit <file>   Submit a workflow"
    echo "  workflow <id>   Check workflow status"
    ;;
esac
```

Make it executable:
```bash
chmod +x gleitzeit-docker.sh
```

Use it:
```bash
./gleitzeit-docker.sh serve
./gleitzeit-docker.sh submit my-workflow.json
./gleitzeit-docker.sh workflow my-workflow-001
./gleitzeit-docker.sh logs worker-task-execution
./gleitzeit-docker.sh stop
```

## Option 3: Modify gleitzeit CLI to Use Docker

You could modify the `gleitzeit serve` command to detect Docker and use docker-compose instead of ProcessOrchestrator:

```python
# In src/gleitzeit/cli/commands/serve.py

@click.command()
@click.option('--docker', is_flag=True, help='Use Docker instead of ProcessOrchestrator')
async def serve(docker):
    if docker:
        # Use docker-compose
        import subprocess
        result = subprocess.run(
            ['docker-compose', '-f', 'docker-compose-proper.yml', 'up', '-d'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            click.echo("✅ Started with Docker")
            click.echo("API: http://localhost:8000")
            click.echo("UI: http://localhost:8004")
        else:
            click.echo(f"❌ Failed: {result.stderr}")
    else:
        # Original ProcessOrchestrator code (has deadlock bug)
        # ...existing code...
```

## Option 4: Use Makefile (Already Created)

We already created a Makefile that provides gleitzeit-like commands:

```bash
# Start everything
make up

# Development mode with hot reload
make dev

# Stop everything
make down

# View logs
make logs
make logs-api
make logs-worker

# Check status
make status

# Clean everything
make clean
```

## Why Not Use `gleitzeit serve` Directly?

The native `gleitzeit serve` command:
1. Uses ProcessOrchestrator
2. Which uses ProcessManager
3. Which uses `subprocess.Popen` with `PIPE`
4. Which causes deadlock when buffer fills
5. Causing all processes to die

The Docker approach:
1. Each service runs in its own container
2. Docker handles all I/O and process management
3. No subprocess deadlock possible
4. Automatic restarts on failure
5. Proper health monitoring

## Recommended Workflow

### For Development:
```bash
# Start services
docker-compose -f docker-compose-proper.yml up -d

# Watch logs in another terminal
docker-compose -f docker-compose-proper.yml logs -f

# Submit workflows via API or curl
curl -X POST http://localhost:8000/workflows/submit \
  -H "Content-Type: application/json" \
  -d @workflow.json

# Stop when done
docker-compose -f docker-compose-proper.yml down
```

### For Production:
```bash
# Use production compose file
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Scale workers as needed
docker-compose up -d --scale worker-task-execution=10

# Monitor with proper tools
# - Prometheus for metrics
# - Grafana for dashboards
# - ELK stack for logs
```

## Summary

**Don't use `gleitzeit serve`** - it has the subprocess deadlock bug.

**Do use**:
- Docker Compose directly
- The Makefile commands
- A wrapper script
- The API directly

The Docker setup is the only way to run Gleitzeit 0.0.7 reliably without fixing the core subprocess management code.