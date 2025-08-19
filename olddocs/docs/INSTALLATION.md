# Installation Guide

## Requirements

- Python 3.8 or higher
- Optional: Redis (for production persistence)
- Optional: Docker (for isolated Python execution)
- Optional: Ollama (for LLM support)

## Installation Methods

### Using uv (Recommended)

```bash
# Install from source
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit
uv pip install -e .

# Or install specific variants
uv pip install -e ".[dev]"     # Development tools
uv pip install -e ".[llm]"     # LLM providers
uv pip install -e ".[docker]"  # Docker support
uv pip install -e ".[all]"     # Everything
```

### Using pip

```bash
# Install from source
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit
pip install -e .

# Install with optional dependencies
pip install -e ".[dev,llm,docker]"
```

## Verify Installation

```bash
# Check CLI is available
gleitzeit --help
gz --help

# Run a simple workflow
gleitzeit run examples/simple_llm_workflow.yaml
```

## Optional Dependencies

### Redis (Production Persistence)

```bash
# macOS
brew install redis
redis-server

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# Configure connection
export GLEITZEIT_REDIS_URL=redis://localhost:6379/0
```

### Ollama (LLM Support)

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama service
ollama serve

# Pull a model
ollama pull llama3.2:latest
```

### Docker (Isolated Python Execution)

```bash
# Install Docker Desktop or Docker Engine
# Verify Docker is running
docker --version

# Test Docker integration
gleitzeit run examples/python_only_workflow.yaml
```

## Configuration

Create configuration file at `~/.gleitzeit/config.yaml`:

```yaml
persistence:
  type: auto  # auto|redis|sql|memory
  redis:
    url: redis://localhost:6379/0
  sql:
    db_path: ~/.gleitzeit/workflows.db

providers:
  ollama:
    endpoint: http://localhost:11434
    default_models:
      chat: llama3.2:latest
      vision: llava:latest

batch:
  max_file_size: 1048576  # 1MB
  max_concurrent: 5
```

## Troubleshooting

### Common Issues

1. **Command not found**: Ensure Python's bin directory is in PATH
2. **Redis connection failed**: Check Redis is running and URL is correct
3. **Ollama unavailable**: Verify Ollama service is running
4. **Permission denied**: Check file permissions and Docker access

### Development Setup

```bash
# Clone repository
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit

# Install development dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/ tests/
ruff check src/ tests/

# Type checking
mypy src/
```