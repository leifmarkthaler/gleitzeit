# Gleitzeit Cluster

**Distributed Workflow Orchestration System**

A production-ready system for orchestrating complex workflows across multiple machines with real-time monitoring, secure function execution, and professional terminal interfaces.

## Key Features

### Terminal Interface
- Enterprise-grade monitoring dashboard with real-time charts
- Keyboard-driven workflow for efficient operations
- Configurable alerting with severity-based notifications  
- Multiple view modes: Overview, Nodes, Tasks, Workflows, Alerts

### Secure Execution
- Curated function library with 30+ audited functions
- No arbitrary code execution - only pre-registered functions
- Input validation and safety limits on all operations
- Authentication system with role-based access control

### Modern Architecture  
- Streamlined CLI with unified commands
- Multi-node cluster with Socket.IO real-time communication
- Intelligent scheduling with multiple policies
- Async-first design for high performance

### Enterprise Monitoring
- Real-time performance metrics with configurable refresh rates
- Professional visualizations with charts and graphs
- System health tracking (CPU, memory, throughput)
- Alert management with threshold monitoring

## Quick Start

### Installation

**With UV (Recommended):**
```bash
# Install UV package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Gleitzeit with monitoring
uv pip install "gleitzeit-cluster[monitor]" && ~/.venv/bin/gleitzeit-setup
```

**With pip:**
```bash
# Install with monitoring
pip install "gleitzeit-cluster[monitor]" && python -m gleitzeit_cluster.post_install
```

### Basic Usage

```bash
# Start development environment
gleitzeit dev

# Launch monitoring dashboard (in new terminal)
gleitzeit pro

# Run a function
gleitzeit run --function fibonacci --args n=10
```

### Available Commands

```bash
gleitzeit dev        # Start cluster + executor + scheduler  
gleitzeit pro        # Monitoring dashboard
gleitzeit run        # Execute tasks
gleitzeit status     # System status
gleitzeit functions  # Browse function library
```

## Architecture

```
┌─────────────────────────────────────────┐
│            Gleitzeit Cluster            │
├─────────────────────────────────────────┤
│  Control Plane: Scheduler + Machine Mgr │
├─────────────────────────────────────────┤
│  Communication: Redis + Socket.IO       │
├─────────────────────────────────────────┤
│  Execution Plane: Distributed Executors │
└─────────────────────────────────────────┘
```

## Python API

### Basic Usage

```python
from gleitzeit_cluster import GleitzeitCluster

# Start cluster
cluster = GleitzeitCluster()
await cluster.start()

# Submit workflow
workflow = cluster.create_workflow("analyze-documents")
workflow.add_task("text_analysis", prompt="Analyze this document", model="llama3")
workflow.add_task("vision_analysis", image_path="chart.png", model="llava")

# Execute and monitor
result = await cluster.execute_workflow(workflow)
print(f"Results: {result}")
```

### Distributed Components

```bash
# Start Redis and Socket.IO servers
docker-compose up -d

# Start scheduler
gleitzeit scheduler --name scheduler-1

# Start executor nodes
gleitzeit executor --name gpu-1 --gpu-only
gleitzeit executor --name cpu-1 --cpu-only
```

## Documentation

- [Architecture Overview](docs/architecture.md)
- [Getting Started Guide](docs/getting-started.md)  
- [API Reference](docs/api.md)
- [Deployment Guide](docs/deployment.md)

## Development

```bash
# Clone repository
git clone https://github.com/leifmarkthaler/gleitzeit
cd gleitzeit

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black gleitzeit_cluster/
isort gleitzeit_cluster/
```

## Status

- **Version**: 0.0.1
- **Python**: 3.9+
- **Status**: Early Development

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Quick Install

```bash
# One-line installer
curl -sSL https://raw.githubusercontent.com/leifmarkthaler/gleitzeit/main/install.sh | bash
```

## Contributing

Contributions welcome! Please open an issue or submit a pull request.