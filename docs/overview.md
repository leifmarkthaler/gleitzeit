# Gleitzeit v0.0.5 Overview

## Introduction

Gleitzeit v0.0.5 is a protocol-based workflow orchestration system designed for coordinating LLM workflows, batch processing, and multi-task execution patterns. It features a clean hub-provider architecture, unified persistence system, and comprehensive resource management capabilities.

## Core Architecture

### Key Components

1. **ExecutionEngine** - The central orchestrator that manages workflow execution
2. **ProtocolProviderRegistry** - Manages protocol definitions and provider instances
3. **ResourceManager & Hubs** - Manages compute resources (Ollama servers, Docker containers)
4. **QueueManager & DependencyResolver** - Handles task scheduling and parameter substitution
5. **Unified Persistence** - Single adapter interface with Redis → SQL → Memory fallback chain

### Hub-Provider Architecture

Gleitzeit v0.0.5 introduces a clean separation of concerns:

- **Providers** focus exclusively on protocol execution (LLM operations, code execution)
- **Hubs** manage resource lifecycle (health monitoring, metrics, allocation)
- **ResourceManager** orchestrates multiple hubs for global resource management

```
┌──────────────────────────────────────────────┐
│            ResourceManager                    │
│  (Global resource orchestration)              │
└────────────────┬─────────────────────────────┘
                 │
      ┌──────────┴──────────┐
      │                     │
┌─────▼──────┐     ┌────────▼────────┐
│ OllamaHub  │     │   DockerHub     │
│            │     │                 │
└─────┬──────┘     └────────┬────────┘
      │                     │
┌─────▼──────────────────────▼────────┐
│         Providers                   │
│  (OllamaProvider, PythonProvider)   │
└──────────────────────────────────────┘
```

## Unified Persistence Architecture

The new unified persistence system consolidates all storage needs:

- **Single Interface**: One `UnifiedPersistenceAdapter` for all persistence operations
- **Automatic Fallback**: Redis → SQLite → Memory fallback ensures reliability
- **Cross-Domain**: Seamlessly handles tasks, workflows, and resource instances
- **Zero Configuration**: Works out of the box with sensible defaults

## Supported Protocols

### 1. LLM Protocol (`llm/v1`)
- **Methods**: `chat`, `vision`
- **Provider**: OllamaProvider (uses OllamaHub for resources)
- **Use Cases**: Text generation, image analysis, conversational AI

### 2. Python Protocol (`python/v1`)
- **Methods**: `execute` (containers only for security)
- **Provider**: PythonProvider (uses DockerHub for secure execution)
- **Use Cases**: Data processing, custom logic in isolated environments

### 3. MCP Protocol (`mcp/v1`)
- **Methods**: `tool.*` (echo, add, multiply, concat)
- **Provider**: SimpleMCPProvider
- **Use Cases**: Tool execution, simple computations

## Workflow Execution

### Execution Modes

1. **Direct Execution** - Tasks execute immediately when submitted
2. **Workflow Mode** - Complete workflows execute with dependency management
3. **Batch Mode** - Dynamic file discovery and parallel processing

### Workflow Definition

Workflows are defined in YAML format:

```yaml
name: "Example Workflow"
tasks:
  - id: "task1"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Generate a topic"
  
  - id: "task2"
    method: "llm/chat"
    dependencies: ["task1"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Expand on: ${task1.response}"
```

## Resource Management

### OllamaHub
Manages multiple Ollama server instances with:
- Automatic health monitoring
- Performance metrics collection
- Instance lifecycle management
- Auto-discovery of running servers

### DockerHub
Manages Docker containers as compute resources with:
- Container lifecycle management
- Resource limit enforcement
- Container pooling for reuse
- Secure Python code execution

### ResourceManager
Orchestrates multiple hubs providing:
- Global resource allocation
- Cross-hub metrics aggregation
- Unified resource view
- Allocation tracking

## Batch Processing

Gleitzeit includes powerful batch processing capabilities:

```yaml
name: "Batch Analysis"
type: "batch"
batch:
  directory: "documents"
  pattern: "*.txt"
template:
  method: "llm/chat"
  model: "llama3.2"
  messages:
    - role: "user"
      content: "Summarize this document"
```

## CLI Interface

The `gleitzeit` CLI provides comprehensive workflow management:

```bash
# Submit workflows
gleitzeit workflow submit workflow.yaml

# Run batch processing
gleitzeit batch documents --pattern "*.txt" --prompt "Summarize"

# Check system status
gleitzeit system status

# View results
gleitzeit workflow status WORKFLOW_ID
```

## Python API

```python
from gleitzeit import GleitzeitClient

async def main():
    async with GleitzeitClient() as client:
        # Client automatically manages hubs, providers, and persistence
        result = await client.execute_task({
            "method": "llm/chat",
            "params": {
                "model": "llama3.2",
                "messages": [
                    {"role": "user", "content": "Hello!"}
                ]
            }
        })
        print(result["response"])
```

## Parameter Substitution

Tasks can use results from previous tasks:

```yaml
parameters:
  value: "${previous_task.response}"
  count: ${data_task.count}
  nested: "${config_task.settings.timeout}"
```

## Key Improvements in v0.0.5

- **Hub-Provider Separation**: Clean architecture with separated concerns
- **Unified Persistence**: Single, robust persistence layer with automatic fallback
- **Resource Management**: Comprehensive resource lifecycle and health monitoring
- **Security**: Python execution restricted to Docker containers
- **Reliability**: Automatic health checks and recovery mechanisms
- **Testing**: 193+ unit tests with 100% pass rate

## Installation

```bash
# Using uv (recommended)
uv pip install -e .

# Using pip
pip install -e .
```

## Quick Start

1. Install Gleitzeit
2. Start Ollama (for LLM provider): `ollama serve`
3. Create a workflow YAML file
4. Run: `gleitzeit workflow submit workflow.yaml`

## Version Information

- **Current Version**: 0.0.5
- **Status**: Beta / Development
- **Architecture**: Hub-Provider separation with unified persistence
- **Testing**: Comprehensive test suite with 100% pass rate
- **Note**: Not yet production ready - additional testing and stabilization needed

## Documentation

For more detailed information, see:
- [Unified Persistence Architecture](UNIFIED_PERSISTENCE_ARCHITECTURE.md)
- [Multi-Instance Ollama Guide](MULTI_INSTANCE_OLLAMA_GUIDE.md)
- [Provider Implementation Guide](PROVIDER_IMPLEMENTATION_GUIDE.md)
- [Batch Processing Guide](BATCH_PROCESSING_DESIGN.md)
- [Workflow Parameter Substitution](WORKFLOW_PARAMETER_SUBSTITUTION.md)

## Migration Notes

If upgrading from v0.0.4:
- The persistence system has been unified - see [Unified Persistence Architecture](UNIFIED_PERSISTENCE_ARCHITECTURE.md)
- Multi-instance Ollama uses hub architecture - see [Multi-Instance Ollama Guide](MULTI_INSTANCE_OLLAMA_GUIDE.md)
- Providers now use hubs for resource management - see [Provider Implementation Guide](PROVIDER_IMPLEMENTATION_GUIDE.md)