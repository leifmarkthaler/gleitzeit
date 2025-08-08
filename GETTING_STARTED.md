# Getting Started with Gleitzeit

Gleitzeit is a distributed workflow orchestration system that allows you to execute tasks across multiple machines with real-time monitoring. This guide will get you up and running in minutes.

## Quick Install

```bash
# One-line installer (recommended)
curl -sSL https://raw.githubusercontent.com/leifmarkthaler/gleitzeit/main/install.sh | bash

# Or install with UV
uv pip install "gleitzeit-cluster[monitor]" && ~/.venv/bin/gleitzeit-setup

# Or install with pip
pip install "gleitzeit-cluster[monitor]" && python -m gleitzeit_cluster.post_install
```

After installation, restart your terminal or run `source ~/.zshrc` to use the `gleitzeit` command.

## Your First Workflow

### Start the Development Environment

```bash
# Terminal 1: Start cluster + executor + scheduler
gleitzeit dev
```

This starts all components in development mode. You'll see:
- Cluster server running on http://localhost:8000
- Executor node ready to process tasks
- Scheduler distributing work

### Launch Monitoring Dashboard

```bash
# Terminal 2: Professional monitoring interface
gleitzeit pro
```

This opens a real-time terminal dashboard showing:
- System performance metrics
- Active tasks and workflows
- Node status and health
- Alert notifications

### Execute Your First Task

```bash
# Terminal 3: Run a simple function
gleitzeit run --function fibonacci --args n=10

# Or analyze text
gleitzeit run --text "Explain quantum computing" --model llama3

# Or process an image
gleitzeit run --vision image.jpg --prompt "Describe this image"
```

## Core Concepts

### Tasks
Individual work units that can be:
- **Function calls**: Execute pre-registered Python functions
- **Text generation**: Use LLM models for text processing
- **Vision analysis**: Process images with vision models
- **HTTP requests**: Make external API calls

### Workflows
Collections of dependent tasks that can:
- Run tasks in parallel or sequence
- Pass data between tasks
- Handle errors and retries
- Cache results for efficiency

### Nodes
Execution environments that can:
- **Executors**: Process tasks with different capabilities (CPU/GPU)
- **Schedulers**: Distribute tasks across executors
- **Cluster**: Coordinate the entire system

## Available Functions

View all built-in functions:

```bash
# List all functions
gleitzeit functions list

# Search for specific functions
gleitzeit functions search "data"

# Get details about a function
gleitzeit functions show fibonacci_sequence

# Show function statistics
gleitzeit functions stats
```

Gleitzeit includes 30+ secure, audited functions across categories:
- **Core**: Math, text processing, utilities
- **Data**: CSV processing, aggregation, analysis

## Python API

For programmatic use:

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster, Task, TaskType, TaskParameters

async def main():
    # Start cluster
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Create a simple task
    task = Task(
        name="Calculate Fibonacci",
        task_type=TaskType.FUNCTION,
        parameters=TaskParameters(
            function_name="fibonacci_sequence",
            kwargs={"n": 10}
        )
    )
    
    # Execute task
    result = await cluster.execute_task(task)
    print(f"Result: {result}")
    
    # Create a workflow with multiple tasks
    workflow = cluster.create_workflow("data-analysis")
    
    # Add tasks to workflow
    workflow.add_task("generate_data", 
                     function_name="generate_sample_data",
                     kwargs={"size": 100})
                     
    workflow.add_task("analyze_data",
                     function_name="analyze_numbers", 
                     depends_on=["generate_data"])
    
    # Execute workflow
    result = await cluster.execute_workflow(workflow)
    print(f"Workflow result: {result}")
    
    await cluster.stop()

# Run the example
asyncio.run(main())
```

## Configuration

### Basic Configuration

Create a configuration file `gleitzeit.yaml`:

```yaml
cluster:
  host: localhost
  port: 8000
  redis_url: redis://localhost:6379

executors:
  - name: cpu-worker
    max_tasks: 4
    capabilities: [text, function]
  
  - name: gpu-worker  
    max_tasks: 2
    capabilities: [vision, text]
    gpu_only: true

scheduler:
  policy: least_loaded
  queue_size: 1000
  heartbeat_interval: 30
```

### Environment Variables

```bash
export GLEITZEIT_REDIS_URL="redis://localhost:6379"
export GLEITZEIT_LOG_LEVEL="INFO"
export GLEITZEIT_MAX_WORKERS="4"
```

## Distributed Setup

### Start Components Separately

```bash
# Terminal 1: Start cluster server
gleitzeit serve --host 0.0.0.0 --port 8000

# Terminal 2: Start scheduler
gleitzeit scheduler --cluster http://localhost:8000

# Terminal 3: Start CPU executor
gleitzeit executor --name cpu-1 --cluster http://localhost:8000 --cpu-only

# Terminal 4: Start GPU executor (if available)
gleitzeit executor --name gpu-1 --cluster http://localhost:8000 --gpu-only
```

### Multi-Machine Setup

On the main machine:
```bash
# Start cluster server
gleitzeit serve --host 0.0.0.0 --port 8000
```

On worker machines:
```bash
# Connect executors to main machine
gleitzeit executor --cluster http://MAIN_MACHINE_IP:8000 --name worker-1
```

## Monitoring and Management

### System Status

```bash
# Quick system status
gleitzeit status

# Watch status continuously
gleitzeit status --watch

# Check specific cluster
gleitzeit status --cluster http://localhost:8000
```

### Results Management

```bash
# List recent results
gleitzeit results list

# Show specific result
gleitzeit results show WORKFLOW_ID

# Export results
gleitzeit results export results.json

# Clear old results
gleitzeit results clear --days 7
```

### Authentication

```bash
# Login with API key
gleitzeit auth login

# Check current auth status
gleitzeit auth status

# Logout
gleitzeit auth logout
```

## Docker Setup

Using the included Docker configuration:

```bash
# Start Redis and supporting services
docker-compose up -d

# Run Gleitzeit in Docker
docker build -t gleitzeit .
docker run -d --name gleitzeit-cluster \
  --network host \
  gleitzeit gleitzeit serve
```

## Troubleshooting

### Common Issues

**Command not found:**
```bash
# Reload shell configuration
source ~/.zshrc

# Or use full path
~/.venv/bin/gleitzeit --help
```

**Connection errors:**
```bash
# Check if Redis is running
redis-cli ping

# Check cluster status
curl http://localhost:8000/health
```

**Permission errors:**
```bash
# Re-run setup
gleitzeit-setup

# Or manually set PATH
export PATH="$HOME/.venv/bin:$PATH"
```

### Getting Help

```bash
# Command help
gleitzeit --help
gleitzeit COMMAND --help

# Function documentation
gleitzeit functions show FUNCTION_NAME

# System diagnostics
gleitzeit status --cluster http://localhost:8000
```

### Performance Tips

1. **Use appropriate node types**: CPU vs GPU tasks
2. **Batch related tasks**: Group similar operations
3. **Enable caching**: Reuse results with `--cache`
4. **Monitor resources**: Use `gleitzeit pro` dashboard
5. **Scale horizontally**: Add more executor nodes

## Next Steps

- Explore the `examples/` directory for more complex workflows
- Read the API documentation for advanced usage
- Check out the monitoring guide for production deployments
- Join the community for support and contributions

## Resources

- **Repository**: https://github.com/leifmarkthaler/gleitzeit
- **Issues**: https://github.com/leifmarkthaler/gleitzeit/issues
- **Documentation**: See other `.md` files in this repository
- **Examples**: Check the `examples/` directory

Happy orchestrating! 🚀