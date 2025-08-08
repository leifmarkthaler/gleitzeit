# Gleitzeit Cluster

**Distributed Workflow Orchestration System**

Local first LLM-Orchestration for LLM-Tasks and Workflows 

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
