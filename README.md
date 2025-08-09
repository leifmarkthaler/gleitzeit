# Gleitzeit

**Distributed Workflow Orchestration System**

A local-first distributed computing platform for orchestrating tasks, workflows, and batch processing. Built for LLM tasks, data processing, and complex multi-step workflows.

## Quick Install

```bash
# Install from source
pip install -e .

# Or use the installer
curl -sSL https://raw.githubusercontent.com/leifmarkthaler/gleitzeit/main/install.sh | bash
```

## Core Concepts

### 🎯 Tasks
Individual units of work that can be executed independently.

- **Text Tasks**: LLM text generation and analysis
- **Vision Tasks**: Image analysis and processing  
- **Function Tasks**: Execute built-in or custom Python functions
- **HTTP Tasks**: Make API calls and process responses

### 🔄 Workflows
Orchestrate multiple tasks with dependencies and data flow.

- **Parallel execution**: Tasks run simultaneously when possible
- **Dependencies**: Control execution order with task dependencies
- **Data flow**: Pass results between tasks using `{{task_id.result}}`
- **Error handling**: Configure how workflows handle task failures

### 📦 Batch Processing
Process multiple items efficiently with parallel execution.

- **Parallel batching**: Process lists of items simultaneously
- **Staged processing**: Multi-stage batch pipelines
- **Auto-scaling**: Automatically scale processing based on load

### 🖥️ Cluster Management
Distributed execution across multiple nodes.

- **Auto-start**: Automatically start required services
- **Service management**: Redis and executor nodes managed automatically
- **Real-time monitoring**: Track progress across distributed execution

## CLI Usage

### Authentication & Setup

```bash
# Initialize authentication (creates admin user)
gleitzeit auth init
# Save the API key shown - it won't be displayed again!

# Login with API key
gleitzeit auth login --api-key gzt_xxxxx --save

# Or use environment variable
export GLEITZEIT_API_KEY=gzt_xxxxx

# Check authentication status
gleitzeit auth status
```

### User Management (Admin Only)

```bash
# Create users with different roles
gleitzeit auth user create john_doe --email john@example.com --role USER
gleitzeit auth user create jane_admin --role OPERATOR
gleitzeit auth user create api_service --role SERVICE

# Create API keys for users
gleitzeit auth key create "John's Key" --user john_doe --expires 30
gleitzeit auth key list --user john_doe

# List all users
gleitzeit auth user list

# Logout when done
gleitzeit auth logout
```

### Basic Task Execution

```bash
# Text generation
gleitzeit run --text "Explain quantum computing" --model llama3

# Image analysis
gleitzeit run --vision photo.jpg --prompt "Describe this image" --model llava

# Function execution
gleitzeit run --function fibonacci --args n=10

# List available functions
gleitzeit functions list
```

### Workflow Management

```bash
# Start development environment
gleitzeit dev

# Run workflow from file
gleitzeit run --workflow my_workflow.yaml

# Check cluster status
gleitzeit status

# Monitor with professional interface
gleitzeit pro
```

### Batch Processing

```bash
# Data analysis functions
gleitzeit run --function random_data --args data_type=numbers count=100 min=1 max=1000
gleitzeit run --function analyze_numbers --args numbers="[1,5,10,15,20]"

# Text processing functions  
gleitzeit run --function count_words --args text="Hello world from Gleitzeit"
gleitzeit run --function extract_keywords --args text="Machine learning and AI"

# CSV data processing
gleitzeit run --function csv_filter --args file=data.csv column=age min_value=18
```

### Folder Batch Processing

```bash
# Discover files in a folder
gleitzeit discover /path/to/images

# Process all images in a folder
gleitzeit run --batch-folder /path/to/images --prompt "Describe this image" --type vision

# Process specific file types
gleitzeit run --batch-folder /docs --type text --extensions .txt,.md
```

### Monitoring & Observability

```bash
# Real-time dashboard - clean terminal interface
gleitzeit monitor

# Stream logs with filtering and search
gleitzeit logs --follow --level INFO --search "workflow"
gleitzeit logs --type task --id task_123 --json

# Performance statistics and analytics
gleitzeit stats --format table
gleitzeit stats --format json --range 60  # Last 60 minutes

# Deep inspection of specific entities
gleitzeit inspect workflow wf_abc123
gleitzeit inspect task task_456 --json
gleitzeit inspect node executor_1

# Watch specific workflows/tasks until completion
gleitzeit watch workflow wf_abc123
gleitzeit watch task task_456
gleitzeit watch queue

# System health check (returns exit codes for scripting)
gleitzeit health --quiet  # Returns 0=healthy, 1=degraded, 2=unhealthy
gleitzeit health --format json

# Real-time event stream
gleitzeit events --types task_completed workflow_started --json
gleitzeit events --follow

# Simple status check
gleitzeit status
```

## Requirements

- **Python 3.9+**
- **Ollama** (for LLM tasks): `curl -fsSL https://ollama.ai/install.sh | sh`
- **Models**: `ollama pull llama3` and `ollama pull llava` (for vision)

## Python API (Optional)

For programmatic workflows:

### Basic Workflow with Authentication

```python
import asyncio
import os
from gleitzeit_cluster import GleitzeitCluster, Workflow, Task, TaskType, TaskParameters
from gleitzeit_cluster.auth import AuthManager

async def main():
    # Authenticate using environment variable or saved credentials
    auth_manager = AuthManager()
    
    # Option 1: Use environment variable
    # export GLEITZEIT_API_KEY=gzt_xxxxx
    context = auth_manager.authenticate_from_environment()
    
    # Option 2: Use API key directly
    # context = auth_manager.authenticate_api_key("gzt_xxxxx")
    
    if context:
        print(f"Authenticated as: {context.user.username}")
    
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Create workflow
    workflow = Workflow(name="Data Processing Pipeline")
    
    # Task 1: Generate data
    generate_task = workflow.add_python_task(
        name="Generate Dataset",
        function_name="fibonacci",
        kwargs={"n": 10}
    )
    
    # Task 2: Analyze data (depends on Task 1)
    analyze_task = workflow.add_python_task(
        name="Analyze Numbers", 
        function_name="analyze_numbers",
        kwargs={"numbers": "{{Generate Dataset.result}}"},
        dependencies=["Generate Dataset"]
    )
    
    # Task 3: Summarize with LLM (depends on Task 2)
    summary_task = workflow.add_text_task(
        name="Generate Summary",
        prompt="Create a summary of this analysis: {{Analyze Numbers.result}}",
        model="llama3",
        dependencies=["Analyze Numbers"]
    )
    
    # Submit workflow and listen for events
    workflow_id = await cluster.submit_workflow(workflow)
    
    # Event-driven completion (much more efficient than polling!)
    completion_event = asyncio.Event()
    workflow_results = {}
    
    # Listen for workflow events
    async def on_workflow_progress(event):
        print(f"Progress: {event['completed_tasks']}/{event['total_tasks']}")
    
    async def on_workflow_completed(event):
        nonlocal workflow_results
        workflow_results = event['task_results']
        print("✅ Workflow completed!")
        completion_event.set()
    
    async def on_workflow_failed(event):
        print(f"❌ Workflow failed: {event.get('error')}")
        completion_event.set()
    
    # Register event handlers
    cluster.on('workflow_progress', on_workflow_progress)
    cluster.on('workflow_completed', on_workflow_completed) 
    cluster.on('workflow_failed', on_workflow_failed)
    
    # Wait for completion event (no polling!)
    await completion_event.wait()
    
    if workflow_results:
        print("Results:", workflow_results)
    
    await cluster.stop()

asyncio.run(main())
```

### Batch Processing

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster, Workflow, Task, TaskType, TaskParameters

async def batch_text_analysis():
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Batch processing workflow
    workflow = Workflow(name="Batch Text Analysis")
    
    texts = [
        "Artificial intelligence is transforming industries",
        "Climate change requires immediate action",  
        "Space exploration opens new frontiers"
    ]
    
    # Create parallel analysis tasks
    for i, text in enumerate(texts):
        workflow.add_python_task(
            name=f"Analyze Text {i+1}",
            function_name="count_words",
            kwargs={"text": text}
        )
        
        workflow.add_python_task(
            name=f"Extract Keywords {i+1}",
            function_name="extract_keywords", 
            kwargs={"text": text, "max_keywords": 3}
        )
    
    # Aggregation task
    workflow.add_text_task(
        name="Generate Report",
        prompt='''Create a report from these analyses:
        Text 1 words: {{Analyze Text 1.result}}, keywords: {{Extract Keywords 1.result}}
        Text 2 words: {{Analyze Text 2.result}}, keywords: {{Extract Keywords 2.result}}
        Text 3 words: {{Analyze Text 3.result}}, keywords: {{Extract Keywords 3.result}}''',
        model="llama3",
        dependencies=[f"Analyze Text {i+1}" for i in range(3)] + [f"Extract Keywords {i+1}" for i in range(3)]
    )
    
    # Execute batch workflow with real-time events
    workflow_id = await cluster.submit_workflow(workflow)
    
    # Event-driven monitoring - no polling needed!
    completion_event = asyncio.Event()
    results = {}
    
    async def on_task_completed(event):
        task_name = event['task_name']
        result = event['result']
        print(f"✅ Completed: {task_name} -> {result}")
    
    async def on_workflow_completed(event):
        nonlocal results
        results = event['task_results']
        completion_event.set()
    
    # Register event listeners
    cluster.on('task_completed', on_task_completed)
    cluster.on('workflow_completed', on_workflow_completed)
    
    # Wait for completion (event-driven, not polling)
    await completion_event.wait()
    
    print("\nBatch Results:")
    for task_name, result in results.items():
        print(f"  {task_name}: {result}")
    
    await cluster.stop()

asyncio.run(batch_text_analysis())
```

### Multi-Endpoint Ollama (Advanced)

Distribute LLM workloads across multiple Ollama servers for scalability and reliability:

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster, Workflow
from gleitzeit_cluster.execution.ollama_endpoint_manager import EndpointConfig, LoadBalancingStrategy

async def multi_endpoint_setup():
    # Configure multiple Ollama endpoints
    endpoints = [
        EndpointConfig(
            name="local_cpu",
            url="http://localhost:11434",
            priority=1,  # Lower priority for CPU
            models=["llama3", "mistral"],
            tags={"cpu", "local"}
        ),
        EndpointConfig(
            name="gpu_server",
            url="http://gpu-server:11434",
            priority=5,  # Higher priority for GPU
            max_concurrent=10,
            models=["llama3", "llava", "codellama"],
            tags={"gpu", "vision", "fast"}
        ),
        EndpointConfig(
            name="cloud_backup",
            url="http://cloud.example.com:11434",
            priority=2,
            max_concurrent=20,
            tags={"cloud", "scalable"}
        )
    ]
    
    # Create cluster with multi-endpoint support
    cluster = GleitzeitCluster(
        ollama_endpoints=endpoints,
        ollama_strategy=LoadBalancingStrategy.LEAST_LOADED  # or ROUND_ROBIN, FASTEST_RESPONSE, MODEL_AFFINITY
    )
    await cluster.start()
    
    # Your existing code works unchanged!
    workflow = Workflow(name="Multi-Endpoint Demo")
    
    # Automatically routed to best available endpoint
    text_task = workflow.add_text_task(
        name="Generate Text",
        prompt="Explain distributed computing",
        model="llama3"
    )
    
    # Vision tasks automatically routed to GPU endpoint
    vision_task = workflow.add_vision_task(
        name="Analyze Image",
        prompt="Describe this image",
        model="llava",
        image_path="photo.jpg"
    )
    
    # Submit with event monitoring
    workflow_id = await cluster.submit_workflow(workflow)
    
    # Event-driven execution with endpoint awareness
    completion_event = asyncio.Event()
    
    async def on_task_started(event):
        endpoint = event.get('endpoint', 'unknown')
        print(f"🔄 Started: {event['task_name']} on endpoint '{endpoint}'")
    
    async def on_task_completed(event):
        endpoint = event.get('endpoint', 'unknown')
        duration = event.get('duration_seconds', 0)
        print(f"✅ Completed: {event['task_name']} on '{endpoint}' in {duration:.1f}s")
    
    async def on_workflow_completed(event):
        print("🎉 All tasks completed across endpoints!")
        completion_event.set()
    
    # Register handlers
    cluster.on('task_started', on_task_started)
    cluster.on('task_completed', on_task_completed)
    cluster.on('workflow_completed', on_workflow_completed)
    
    # Wait for completion
    await completion_event.wait()
    
    # Show final endpoint statistics
    stats = cluster.task_executor.ollama_manager.get_endpoint_stats()
    print("\nEndpoint Performance:")
    for endpoint, data in stats.items():
        load = data['stats']['current_load']
        success_rate = data['stats']['success_rate']
        print(f"  {endpoint}: Load={load}, Success={success_rate:.2%}")
    
    await cluster.stop()

asyncio.run(multi_endpoint_setup())
```

**Multi-Endpoint Features:**
- **Automatic Failover**: Seamlessly retry on healthy endpoints if one fails
- **Load Balancing**: Distribute requests using LEAST_LOADED, ROUND_ROBIN, FASTEST_RESPONSE, or MODEL_AFFINITY strategies
- **Model Routing**: Automatically route to endpoints with required models
- **Health Monitoring**: Continuous health checks with automatic recovery
- **Priority-based Selection**: Prefer high-performance endpoints
- **Tag-based Routing**: Route by capabilities (gpu, vision, fast)

### Monitoring Your Workflows

While your workflows run, use these CLI tools for real-time observability:

```bash
# In Terminal 1: Run your Python workflow
python my_workflow.py

# In Terminal 2: Monitor in real-time
gleitzeit monitor  # Live dashboard

# In Terminal 3: Watch specific workflow (get ID from your script)
gleitzeit watch workflow wf_abc123

# In Terminal 4: Stream events as JSON for analysis
gleitzeit events --json | jq '.data.task_name'

# After completion: Analyze performance
gleitzeit stats --format json --range 10 > workflow_stats.json
gleitzeit inspect workflow wf_abc123 --json > workflow_details.json
```

**Development Monitoring Workflow:**
1. **Health Check**: `gleitzeit health` to verify local setup
2. **Real-time Monitoring**: `gleitzeit monitor` while developing workflows  
3. **Debug Logging**: `gleitzeit logs --follow` for development debugging
4. **Performance Analysis**: `gleitzeit stats` to understand workflow behavior
5. **Deep Debugging**: `gleitzeit inspect` for detailed troubleshooting

⚠️ **Note**: Currently monitors development/mock execution. Production monitoring features are planned for future releases.

### Event-Driven Architecture

Gleitzeit uses **Socket.IO events** instead of polling for real-time updates:

```python
# Available events:
cluster.on('workflow_started', handler)     # Workflow begins
cluster.on('workflow_progress', handler)    # Progress updates
cluster.on('workflow_completed', handler)   # Workflow done
cluster.on('workflow_failed', handler)      # Workflow error

cluster.on('task_started', handler)         # Task begins
cluster.on('task_completed', handler)       # Task done  
cluster.on('task_failed', handler)          # Task error

cluster.on('node_joined', handler)          # New executor
cluster.on('node_left', handler)            # Executor offline
cluster.on('system_alert', handler)         # System issues
```

**Benefits over polling:**
- ⚡ **Instant updates** - no delay waiting for next poll
- 🔋 **Resource efficient** - no CPU waste on constant checking  
- 📡 **Real-time** - true event-driven architecture
- 🎯 **Precise** - only react to actual state changes
- 🔄 **Bidirectional** - cluster can push updates to clients

## What Makes This Different?

- **Local-first**: Everything runs on your machine
- **Event-Driven**: Real-time Socket.IO events instead of inefficient polling
- **Comprehensive Monitoring**: 7 focused CLI tools for observability
- **Secure Authentication**: File-based API key system with role-based access control
- **No cloud dependencies**: No external auth servers or API costs
- **Workflow orchestration**: Chain tasks with dependencies and data flow
- **Built-in functions**: 30+ secure functions for data processing
- **Privacy**: Your data never leaves your computer
- **Simple**: Just install and run commands
- **Extensible**: 30+ built-in functions + Python API
- **Multi-Endpoint Support**: Scale across multiple Ollama servers with automatic failover
- **Development Focus**: Rich monitoring and debugging tools for development
- **Developer Friendly**: Deep inspection, real-time watching, and JSON exports

## Status

- **Version**: 0.0.1 (Alpha) - **NOT PRODUCTION READY**
- **Stage**: Active Development - Core functionality being built
- **Use Case**: Development, prototyping, and local experimentation
- **License**: MIT  
- **Python**: 3.9+ required
- **Platform**: macOS, Linux (Windows support planned)

### Development Roadmap to Production:
- [ ] Replace mock execution with real task processing
- [ ] Comprehensive error handling and recovery
- [ ] Performance testing and optimization  
- [ ] Security hardening and audit
- [ ] Load testing and scalability validation
- [ ] Deployment automation and containerization
- [ ] Production monitoring and alerting

## Contributing

This project is in active development. Contributions welcome!

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

**Repository**: https://github.com/leifmarkthaler/gleitzeit

## CLI Reference

### Core Commands
- `gleitzeit run` - Execute tasks, workflows, and batch processing
- `gleitzeit dev` - Start development environment with cluster + executors
- `gleitzeit auth` - User management and API key authentication

### Monitoring & Observability
- `gleitzeit monitor` - Real-time dashboard with workflows and tasks
- `gleitzeit logs` - Stream and filter logs with search capabilities  
- `gleitzeit stats` - Performance metrics and analytics (table/JSON/CSV)
- `gleitzeit inspect` - Deep dive into workflows, tasks, and nodes
- `gleitzeit watch` - Follow specific workflows/tasks until completion
- `gleitzeit health` - System health check (scriptable exit codes)
- `gleitzeit events` - Real-time event stream (JSON output available)

### Utilities
- `gleitzeit status` - Quick cluster status check
- `gleitzeit discover` - Analyze folders for batch processing
- `gleitzeit functions` - Manage built-in secure functions