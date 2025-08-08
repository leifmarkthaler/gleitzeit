# 🚀 Gleitzeit CLI Service

**Similar to `jupyter lab`** - start Gleitzeit as a persistent service with web dashboard.

## 📋 Quick Start

### Start the Service
```bash
# Basic startup (like 'jupyter lab')
python gleitzeit.py serve

# Custom port
python gleitzeit.py serve --port 8080

# Disable Redis (in-memory only)
python gleitzeit.py serve --no-redis

# Don't auto-open browser
python gleitzeit.py serve --no-browser
```

### Use the Service
1. **Dashboard**: Open http://localhost:8000 in your browser
2. **Start executors**: `PYTHONPATH=. python examples/start_executor.py`
3. **Submit workflows**: `PYTHONPATH=. python examples/minimal_example.py`
4. **Stop service**: Press `Ctrl+C`

## 🌐 Service Features

When you run `python gleitzeit.py serve`, you get:

- ✅ **Web Dashboard** - Real-time monitoring at http://localhost:8000
- ✅ **API Endpoints** - REST API for workflow submission
- ✅ **Executor Coordination** - Connect multiple worker nodes
- ✅ **Persistent Storage** - Redis-based workflow persistence
- ✅ **Auto-browser** - Automatically opens dashboard
- ✅ **Graceful Shutdown** - Ctrl+C stops cleanly

## 🔧 CLI Commands

### `gleitzeit serve`
Start the Gleitzeit service (main command)

**Options:**
- `--host localhost` - Host to bind to
- `--port 8000` - Port to bind to  
- `--redis-url redis://localhost:6379` - Redis connection
- `--no-redis` - Disable Redis (use in-memory)
- `--no-browser` - Don't auto-open browser
- `--log-level INFO` - Logging level (DEBUG/INFO/WARNING/ERROR)

### `gleitzeit version`
Show version information

## 📊 Usage Patterns

### Development Setup
```bash
# Terminal 1: Start service
python gleitzeit.py serve

# Terminal 2: Start executor nodes
PYTHONPATH=. python examples/start_executor.py --name worker-1
PYTHONPATH=. python examples/start_executor.py --name worker-2 --gpu

# Terminal 3: Submit workflows
PYTHONPATH=. python examples/minimal_example.py
```

### Production Setup
```bash
# Start on specific host/port
python gleitzeit.py serve --host 0.0.0.0 --port 9000

# No browser auto-open for servers
python gleitzeit.py serve --no-browser --log-level WARNING
```

### Minimal Setup (No Redis)
```bash
# In-memory only (no persistence)
python gleitzeit.py serve --no-redis
```

## 🌐 Web Dashboard

Once started, the dashboard shows:
- **Cluster Overview** - Active workflows, tasks, nodes
- **Live Workflows** - Progress bars, status, completion
- **Executor Nodes** - Connected workers, capabilities, health
- **Activity Feed** - Real-time event log
- **System Stats** - Resource usage, performance metrics

## 🔄 Executor Nodes

Start executor nodes to process workflows:

```bash
# Simple executor
PYTHONPATH=. python examples/start_executor.py

# Custom executor
PYTHONPATH=. python examples/start_executor.py --name gpu-worker --tasks 5 --gpu

# Multiple executors
PYTHONPATH=. python examples/start_executor.py --name worker-1 &
PYTHONPATH=. python examples/start_executor.py --name worker-2 &
```

## 📡 API Usage

Submit workflows programmatically:

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster

async def main():
    # Connect to running service
    cluster = GleitzeitCluster(
        socketio_url="http://localhost:8000",
        enable_socketio=True
    )
    
    await cluster.start()
    
    # Submit workflow
    workflow = cluster.create_workflow("my_task", "Description")
    workflow.add_text_task("analyze", "Analyze this data", "llama3")
    
    result = await cluster.execute_workflow(workflow)
    print(f"Result: {result.status}")
    
    await cluster.stop()

asyncio.run(main())
```

## 🛑 Stopping the Service

- **Graceful**: Press `Ctrl+C` in the terminal
- **Force**: `Ctrl+C` twice for immediate stop
- **Check Status**: Visit http://localhost:8000/health

## ⚡ Examples

See the `examples/` directory for:
- `minimal_example.py` - Basic workflow submission
- `start_executor.py` - Start executor nodes
- `dashboard_demo.py` - Dashboard with sample data
- `executor_test.py` - Full system testing

The CLI makes Gleitzeit as easy to use as Jupyter Lab!