# Quick Start Guide

Get up and running with Gleitzeit in 5 minutes!

## Prerequisites

- Python 3.9 or higher
- Ollama installed (for LLM features)
- Docker installed (optional, for Python execution)
- Redis (optional, for production persistence)

## Installation

### Using uv (Recommended)
```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/yourusername/gleitzeit.git
cd gleitzeit

# Install Gleitzeit
uv pip install -e .
```

### Using pip
```bash
# Clone the repository
git clone https://github.com/yourusername/gleitzeit.git
cd gleitzeit

# Install Gleitzeit
pip install -e .
```

## Step 1: Start Ollama

First, ensure Ollama is running:

```bash
# Start Ollama server
ollama serve

# In another terminal, pull a model
ollama pull llama3.2
```

## Step 2: Create Your First Workflow

Create a file called `hello_workflow.yaml`:

```yaml
name: "Hello World Workflow"
description: "My first Gleitzeit workflow"

tasks:
  - id: "greeting"
    protocol: "llm/v1"
    method: "chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Say hello and tell me an interesting fact!"

  - id: "followup"
    protocol: "llm/v1" 
    method: "chat"
    dependencies: ["greeting"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "That's interesting! Now tell me more about: ${greeting.response}"
```

## Step 3: Run the Workflow

### Using the CLI

```bash
# Submit and run the workflow
gleitzeit workflow submit hello_workflow.yaml

# Check status
gleitzeit workflow status <workflow-id>

# View results
gleitzeit workflow result <workflow-id>
```

### Using Python API

Create a file called `run_workflow.py`:

```python
import asyncio
from gleitzeit import GleitzeitClient

async def main():
    # Create client
    async with GleitzeitClient() as client:
        # Run workflow from file
        results = await client.run_workflow("hello_workflow.yaml")
        
        # Print results
        for task_id, result in results.items():
            print(f"\n{task_id}:")
            print(result.get("response", result))

if __name__ == "__main__":
    asyncio.run(main())
```

Run it:
```bash
python run_workflow.py
```

## Step 4: Try Batch Processing

Process multiple files in parallel:

### Create Test Files
```bash
mkdir documents
echo "Python is a great language" > documents/python.txt
echo "JavaScript powers the web" > documents/javascript.txt
echo "Rust is fast and safe" > documents/rust.txt
```

### Run Batch Processing
```bash
# Process all text files
gleitzeit batch documents \
  --pattern "*.txt" \
  --prompt "Summarize this file and rate the programming language mentioned from 1-10"
```

### Or use a batch workflow:

Create `batch_workflow.yaml`:

```yaml
name: "Batch Document Analysis"
type: "batch"

batch:
  directory: "documents"
  pattern: "*.txt"

template:
  protocol: "llm/v1"
  method: "chat"
  model: "llama3.2"
  messages:
    - role: "user"
      content: "Analyze this document and provide a summary"
```

Run it:
```bash
gleitzeit workflow submit batch_workflow.yaml
```

## Step 5: Chain Task Results

Create `chain_workflow.yaml`:

```yaml
name: "Story Chain"
description: "Create a story by chaining responses"

tasks:
  - id: "character"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Create a unique character for a story in one sentence"

  - id: "setting"
    method: "llm/chat"
    dependencies: ["character"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Create a setting for this character: ${character.response}"

  - id: "plot"
    method: "llm/chat"
    dependencies: ["character", "setting"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: |
            Write a short story plot with:
            Character: ${character.response}
            Setting: ${setting.response}
```

## Advanced Examples

### Multi-Model Workflow

```yaml
name: "Multi-Model Analysis"

tasks:
  - id: "fast_response"
    method: "llm/chat"
    parameters:
      model: "llama3.2:1b"  # Fast small model
      messages:
        - role: "user"
          content: "Quick summary of quantum computing"

  - id: "detailed_response"
    method: "llm/chat"
    parameters:
      model: "llama3.2:7b"  # Larger model for detail
      messages:
        - role: "user"
          content: "Explain quantum computing in detail with examples"

  - id: "combine"
    method: "llm/chat"
    dependencies: ["fast_response", "detailed_response"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: |
            Combine these two explanations into one comprehensive summary:
            Quick: ${fast_response.response}
            Detailed: ${detailed_response.response}
```

### Using Python API for Dynamic Workflows

```python
import asyncio
from gleitzeit import GleitzeitClient

async def dynamic_workflow():
    async with GleitzeitClient() as client:
        # Start with a question
        question = await client.execute_task({
            "method": "llm/chat",
            "params": {
                "model": "llama3.2",
                "messages": [
                    {"role": "user", "content": "Generate a random question about science"}
                ]
            }
        })
        
        # Answer the generated question
        answer = await client.execute_task({
            "method": "llm/chat",
            "params": {
                "model": "llama3.2",
                "messages": [
                    {"role": "user", "content": f"Answer this: {question['response']}"}
                ]
            }
        })
        
        # Fact-check the answer
        verification = await client.execute_task({
            "method": "llm/chat",
            "params": {
                "model": "llama3.2",
                "messages": [
                    {"role": "user", 
                     "content": f"Is this answer correct? {answer['response']}"}
                ]
            }
        })
        
        return {
            "question": question['response'],
            "answer": answer['response'],
            "verification": verification['response']
        }

# Run the dynamic workflow
result = asyncio.run(dynamic_workflow())
print(result)
```

## Configuration Options

### Persistence Configuration

```python
from gleitzeit import GleitzeitClient

# Use Redis for production
client = GleitzeitClient(
    persistence="redis",
    redis_url="redis://localhost:6379"
)

# Use SQLite for development
client = GleitzeitClient(
    persistence="sqlite",
    db_path="./gleitzeit.db"
)

# Use memory for testing
client = GleitzeitClient(
    persistence="memory"
)
```

### Multi-Instance Ollama

If you have multiple Ollama instances:

```python
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.configs import OllamaConfig

# Create hub with multiple instances
hub = OllamaHub()
await hub.initialize()

# Register multiple Ollama servers
configs = [
    OllamaConfig(host="127.0.0.1", port=11434),
    OllamaConfig(host="127.0.0.1", port=11435),
    OllamaConfig(host="192.168.1.100", port=11434)
]

for config in configs:
    await hub.start_instance(config)
```

## Common Commands

### Workflow Management
```bash
# Submit workflow
gleitzeit workflow submit workflow.yaml

# List workflows
gleitzeit workflow list

# Get workflow status
gleitzeit workflow status <workflow-id>

# Get workflow results
gleitzeit workflow result <workflow-id>

# Cancel workflow
gleitzeit workflow cancel <workflow-id>
```

### Batch Processing
```bash
# Process directory
gleitzeit batch <directory> --pattern "*.txt" --prompt "Analyze this"

# With specific model
gleitzeit batch <directory> --model "llama3.2:7b" --prompt "Summarize"
```

### System Management
```bash
# Check system status
gleitzeit system status

# View providers
gleitzeit provider list

# View available models
gleitzeit model list

# Clean up old workflows
gleitzeit system cleanup --older-than 7d
```

## Troubleshooting

### Ollama Connection Issues
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama
killall ollama
ollama serve
```

### Python Execution Not Working
Python execution requires Docker:
```bash
# Check Docker is running
docker ps

# Pull Python image
docker pull python:3.11-slim
```

### Workflow Fails
```bash
# Check detailed logs
gleitzeit workflow logs <workflow-id>

# Enable debug mode
gleitzeit --debug workflow submit workflow.yaml
```

## Next Steps

Now that you have Gleitzeit running:

1. **Learn about Workflows**: Read [Workflow Execution Guide](WORKFLOW_EXECUTION.md)
2. **Explore Batch Processing**: See [Batch Processing Guide](BATCH_PROCESSING.md)
3. **Create Custom Providers**: Check [Provider Development Guide](PROVIDER_DEVELOPMENT.md)
4. **Understand Architecture**: Review [Architecture Overview](ARCHITECTURE.md)

## Getting Help

- Check the [Troubleshooting Guide](TROUBLESHOOTING.md)
- Review [Common Issues](https://github.com/yourusername/gleitzeit/issues)
- Ask questions in [Discussions](https://github.com/yourusername/gleitzeit/discussions)

## Example Workflows Repository

Find more example workflows at:
https://github.com/yourusername/gleitzeit-examples

Happy orchestrating! 🚀