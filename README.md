# Gleitzeit

A workflow orchestration system for coordinating LLM tasks, Python code execution, and tool integrations. Supports parallel task execution, dependency management, and batch file processing.

## Features

- Execute workflows combining LLMs, Python scripts, and MCP tools
- Parallel task execution with configurable concurrency limits
- Task dependencies with parameter substitution between steps
- Persistence with fallback: Redis → SQLite → Memory
- Hub-Provider architecture for resource management
- Batch processing with glob patterns for file operations
- Docker container support for isolated Python execution

## Version: 0.0.5 (Beta)

## 📚 Documentation Structure

### Getting Started
- [Quick Start Guide](docs/QUICK_START.md) - Get up and running in 5 minutes
- [Installation Guide](docs/INSTALLATION.md) - Detailed installation instructions
- [CLI Reference](docs/CLI_REFERENCE.md) - Command-line interface documentation

### Architecture
- [Architecture Overview](docs/ARCHITECTURE.md) - Complete system architecture
- [Hub-Provider Separation](docs/HUB_PROVIDER_ARCHITECTURE.md) - Clean separation of concerns
- [Unified Persistence](docs/UNIFIED_PERSISTENCE.md) - Single persistence layer with fallback
- [Resource Management](docs/RESOURCE_MANAGEMENT.md) - Hub and ResourceManager system

### Core Concepts
- [Workflow Execution](docs/WORKFLOW_EXECUTION.md) - How workflows are processed
- [Task Management](docs/TASK_MANAGEMENT.md) - Task lifecycle and dependencies
- [Parameter Substitution](docs/PARAMETER_SUBSTITUTION.md) - Using results across tasks
- [Batch Processing](docs/BATCH_PROCESSING.md) - Parallel file processing

### Providers & Protocols
- [Provider Development](docs/PROVIDER_DEVELOPMENT.md) - Creating custom providers
- [Protocol Specification](docs/PROTOCOL_SPECIFICATION.md) - Protocol definitions
- [Built-in Providers](docs/BUILTIN_PROVIDERS.md) - Ollama, Python, MCP providers

### Hubs & Resources
- [Hub Development](docs/HUB_DEVELOPMENT.md) - Creating resource hubs
- [OllamaHub Guide](docs/OLLAMA_HUB.md) - Managing Ollama instances
- [DockerHub Guide](docs/DOCKER_HUB.md) - Container management
- [Health Monitoring](docs/HEALTH_MONITORING.md) - Metrics and monitoring

### API Documentation
- [Python API](docs/PYTHON_API.md) - GleitzeitClient reference
- [REST API](docs/REST_API.md) - HTTP endpoints (if applicable)
- [Configuration](docs/CONFIGURATION.md) - System configuration

### Advanced Topics
- [Security Model](docs/SECURITY.md) - Security architecture and best practices
- [Performance Tuning](docs/PERFORMANCE.md) - Optimization guide
- [Troubleshooting](docs/TROUBLESHOOTING.md) - Common issues and solutions
- [Migration Guide](docs/MIGRATION.md) - Upgrading from v0.0.4

## 🚀 Quick Navigation

### For Users
Start with the [Quick Start Guide](docs/QUICK_START.md) to run your first workflow, then explore [Workflow Execution](docs/WORKFLOW_EXECUTION.md) and [CLI Reference](docs/CLI_REFERENCE.md).

### For Developers
Read the [Architecture Overview](docs/ARCHITECTURE.md), then dive into [Provider Development](docs/PROVIDER_DEVELOPMENT.md) or [Hub Development](docs/HUB_DEVELOPMENT.md) based on your needs.

### For System Administrators
Focus on [Installation Guide](docs/INSTALLATION.md), [Configuration](docs/CONFIGURATION.md), and [Health Monitoring](docs/HEALTH_MONITORING.md).

## 📋 Version Information

- **Version**: 0.0.5
- **Status**: Beta / Development
- **Released**: August 2024
- **Python**: 3.9+
- **License**: MIT

## 🔄 What's New in v0.0.5

### Major Changes
- **Hub-Provider Architecture**: Clean separation between resource management (hubs) and protocol execution (providers)
- **Unified Persistence**: Single persistence interface with automatic Redis → SQLite → Memory fallback
- **Resource Management**: Comprehensive ResourceManager for orchestrating multiple hubs
- **Security Improvements**: Python execution restricted to Docker containers
- **Health Monitoring**: Automatic health checks and metrics collection

### Breaking Changes
- Python arbitrary script execution removed (security)
- OllamaPoolProvider replaced with OllamaHub
- Task persistence API changed to unified interface

See [Migration Guide](MIGRATION.md) for upgrade instructions.

## Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/yourusername/gleitzeit/issues)
- **Documentation Issues**: [Report documentation problems](https://github.com/yourusername/gleitzeit/issues/new?labels=documentation)

## 🏗️ Architecture at a Glance

```
┌──────────────────────────────────────────────┐
│              Workflow Layer                   │
│         (YAML definitions, CLI)               │
└────────────────┬─────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────┐
│           ExecutionEngine                     │
│    (Orchestration, Dependencies, Queue)       │
└────────────────┬─────────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
┌───────▼──────┐ ┌────────▼────────┐
│   Providers  │ │  ResourceManager │
│  (Protocols) │ │     (Hubs)       │
└───────┬──────┘ └────────┬────────┘
        │                 │
┌───────▼──────────────────▼────────┐
│      Unified Persistence          │
│   (Redis → SQLite → Memory)       │
└────────────────────────────────────┘
```

## 📚 Complete Documentation Index

All documentation files are in `/docs` directory.
