# Installation

## Requirements

- Python 3.8 or higher
- Ollama for LLM operations (optional)
- Redis or SQLite for persistence (optional)

## Install from PyPI

```bash
pip install gleitzeit
```

## Install from Source

```bash
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit
pip install -e .
```

## Install with Optional Dependencies

```bash
# For LLM support
pip install gleitzeit[llm]

# For Docker support
pip install gleitzeit[docker]

# For development
pip install gleitzeit[dev]

# Everything
pip install gleitzeit[all]
```

## Install Ollama

Gleitzeit uses Ollama for LLM operations. Install it based on your platform:

### macOS
```bash
brew install ollama
ollama serve
```

### Linux
```bash
curl -fsSL https://ollama.ai/install.sh | sh
ollama serve
```

### Windows
Download from [ollama.ai](https://ollama.ai) and run the installer.

## Pull Models

After installing Ollama, pull the models you need:

```bash
# General purpose
ollama pull llama3.2

# Code generation
ollama pull codellama

# Vision/image analysis
ollama pull llava

# Smaller, faster model
ollama pull phi
```

## Verify Installation

```bash
# Check CLI
gleitzeit --version

# Test Ollama connection
gleitzeit status

# Run a simple workflow
echo 'name: "test"
tasks:
  - id: "hello"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Say hello"' > test.yaml

gleitzeit run test.yaml
```

## Python Client Verification

```python
import asyncio
from gleitzeit import GleitzeitClient

async def test():
    async with GleitzeitClient() as client:
        response = await client.chat("Hello", model="llama3.2")
        print(response)

asyncio.run(test())
```

## Optional: Redis Setup

For production use with persistence:

```bash
# Install Redis
brew install redis  # macOS
apt-get install redis-server  # Ubuntu

# Start Redis
redis-server

# Configure Gleitzeit to use Redis
export GLEITZEIT_REDIS_URL=redis://localhost:6379
```

## Next Steps

- Read the [Quick Start section](../README.md#quick-start) in the main documentation
- Learn about [Core Concepts](concepts.md)
- Explore [Workflows](workflows.md)