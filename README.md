# Gleitzeit v0.0.5 Documentation

## 📚 Documentation Structure

### Getting Started
- [Quick Start Guide](QUICK_START.md) - Get up and running in 5 minutes
- [Installation Guide](INSTALLATION.md) - Detailed installation instructions
- [CLI Reference](CLI_REFERENCE.md) - Command-line interface documentation

### Architecture
- [Architecture Overview](ARCHITECTURE.md) - Complete system architecture
- [Hub-Provider Separation](HUB_PROVIDER_ARCHITECTURE.md) - Clean separation of concerns
- [Unified Persistence](UNIFIED_PERSISTENCE.md) - Single persistence layer with fallback
- [Resource Management](RESOURCE_MANAGEMENT.md) - Hub and ResourceManager system

### Core Concepts
- [Workflow Execution](WORKFLOW_EXECUTION.md) - How workflows are processed
- [Task Management](TASK_MANAGEMENT.md) - Task lifecycle and dependencies
- [Parameter Substitution](PARAMETER_SUBSTITUTION.md) - Using results across tasks
- [Batch Processing](BATCH_PROCESSING.md) - Parallel file processing

### Providers & Protocols
- [Provider Development](PROVIDER_DEVELOPMENT.md) - Creating custom providers
- [Protocol Specification](PROTOCOL_SPECIFICATION.md) - Protocol definitions
- [Built-in Providers](BUILTIN_PROVIDERS.md) - Ollama, Python, MCP providers

### Hubs & Resources
- [Hub Development](HUB_DEVELOPMENT.md) - Creating resource hubs
- [OllamaHub Guide](OLLAMA_HUB.md) - Managing Ollama instances
- [DockerHub Guide](DOCKER_HUB.md) - Container management
- [Health Monitoring](HEALTH_MONITORING.md) - Metrics and monitoring

### API Documentation
- [Python API](PYTHON_API.md) - GleitzeitClient reference
- [REST API](REST_API.md) - HTTP endpoints (if applicable)
- [Configuration](CONFIGURATION.md) - System configuration

### Advanced Topics
- [Security Model](SECURITY.md) - Security architecture and best practices
- [Performance Tuning](PERFORMANCE.md) - Optimization guide
- [Troubleshooting](TROUBLESHOOTING.md) - Common issues and solutions
- [Migration Guide](MIGRATION.md) - Upgrading from v0.0.4

## 🚀 Quick Navigation

### For Users
Start with the [Quick Start Guide](QUICK_START.md) to run your first workflow, then explore [Workflow Execution](WORKFLOW_EXECUTION.md) and [CLI Reference](CLI_REFERENCE.md).

### For Developers
Read the [Architecture Overview](ARCHITECTURE.md), then dive into [Provider Development](PROVIDER_DEVELOPMENT.md) or [Hub Development](HUB_DEVELOPMENT.md) based on your needs.

### For System Administrators
Focus on [Installation Guide](INSTALLATION.md), [Configuration](CONFIGURATION.md), and [Health Monitoring](HEALTH_MONITORING.md).

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

## 📞 Support

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

All documentation files are in this `/newdocs` directory. For the legacy documentation, see `/docs`.