# Gleitzeit Documentation

Gleitzeit is a workflow orchestration system for running LLM operations, Python scripts, and other tasks in sequence or parallel.

## Documentation

- [Installation](installation.md) - How to install Gleitzeit
- [Quick Start](quickstart.md) - Get started in 5 minutes
- [Core Concepts](concepts.md) - Understand the basics
- [Workflows](workflows.md) - Creating and running workflows
- [CLI Reference](cli.md) - Command-line interface
- [Python API](api.md) - Using Gleitzeit from Python
- [Providers](providers.md) - Available providers and protocols
- [Configuration](configuration.md) - Configuration options
- [Troubleshooting](troubleshooting.md) - Common issues and solutions

## Quick Example

Create a workflow file `example.yaml`:

```yaml
name: "Example"
tasks:
  - id: "greet"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Say hello"
```

Run it:

```bash
gleitzeit run example.yaml
```

## Requirements

- Python 3.8 or higher
- Ollama (for LLM operations)
- Redis or SQLite (optional, for persistence)

## License

MIT