# Installation Guide

## Install with uv (Recommended)

[uv](https://github.com/astral-sh/uv) is the fastest Python package manager.

### Basic Installation
```bash
# Install gleitzeit-cluster
uv pip install gleitzeit-cluster

# Or install directly from source
uv pip install git+https://github.com/leifmarkthaler/gleitzeit.git
```

### With Professional Monitoring
```bash
# Install with monitoring dependencies
uv pip install "gleitzeit-cluster[monitor]"

# Install with all features
uv pip install "gleitzeit-cluster[all]"
```

### Development Installation
```bash
# Clone and install in development mode
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit
uv pip install -e ".[dev,monitor]"
```

## Install with pip

```bash
# Basic installation
pip install gleitzeit-cluster

# With monitoring
pip install "gleitzeit-cluster[monitor]"

# With all features
pip install "gleitzeit-cluster[all]"

# Development installation
pip install -e ".[dev,monitor]"
```

## Quick Start

After installation, verify it works:

```bash
# Check version
gleitzeit version

# Start development environment
gleitzeit dev

# In another terminal, launch monitoring
gleitzeit pro
```

## System Requirements

- **Python**: 3.9 or higher
- **Operating System**: Linux, macOS, Windows
- **Memory**: 512MB minimum, 2GB recommended
- **Terminal**: Support for Unicode and 256 colors (for professional monitoring)

## Optional Dependencies

### For LLM Tasks
```bash
# Install Ollama for local LLM execution
curl -fsSL https://ollama.ai/install.sh | sh

# Pull models
ollama pull llama3
ollama pull llava
```

### For Redis Caching
```bash
# Install Redis server
# Ubuntu/Debian
sudo apt-get install redis-server

# macOS
brew install redis

# Docker
docker run -d -p 6379:6379 redis:alpine
```

## Feature Sets

### Core Features (Always Included)
- Distributed workflow orchestration  
- Secure function execution
- Multi-node cluster management
- CLI-first interface
- Authentication system

### Monitor Features (`[monitor]`)
- Professional terminal GUI
- Real-time performance metrics
- Intelligent alerting
- Performance charts
- Keyboard shortcuts

### Development Features (`[dev]`)
- Testing framework
- Code quality tools  
- Type checking
- Code formatting

### All Features (`[all]`)
- Everything above
- Documentation tools
- Development utilities

## Installation Examples

### Data Science Workflow
```bash
# Install with monitoring for data pipeline tracking
uv pip install "gleitzeit-cluster[monitor]"

# Start cluster with monitoring
gleitzeit dev --executors 3
gleitzeit pro  # In new terminal
```

### Production Deployment
```bash
# Install minimal version for production
uv pip install gleitzeit-cluster

# Start cluster components separately
gleitzeit serve --host 0.0.0.0 --port 8000
gleitzeit executor --cluster http://localhost:8000
gleitzeit scheduler --cluster http://localhost:8000
```

### Development Setup
```bash
# Full development installation
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit
uv pip install -e ".[all]"

# Run tests
pytest

# Start development environment
gleitzeit dev
```

## Troubleshooting

### Common Issues

**Import Error:**
```bash
# Make sure package is installed
uv pip list | grep gleitzeit

# Reinstall if needed
uv pip install --force-reinstall gleitzeit-cluster
```

**Command Not Found:**
```bash
# Check if CLI is in PATH
which gleitzeit

# Or run via Python module
python -m gleitzeit_cluster.cli --help
```

**Rich Display Issues:**
```bash
# Install monitoring dependencies
uv pip install "gleitzeit-cluster[monitor]"

# Check terminal capabilities
python -c "import rich.console; rich.console.Console().print('Test')"
```

### Version Check
```bash
# Check installed version
gleitzeit version
python -c "import gleitzeit_cluster; print(gleitzeit_cluster.__version__)"
```

## Next Steps

1. **Quick Start**: Run `gleitzeit dev` to start everything
2. **Monitoring**: Launch `gleitzeit pro` for professional interface  
3. **Examples**: Check the `examples/` directory
4. **Documentation**: Read `MONITORING.md` for monitoring features

---

**Ready to orchestrate your workflows!** 🚀