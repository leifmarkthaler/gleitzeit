# Gleitzeit v0.0.4 Overview

## Introduction

Gleitzeit v0.0.4 is a protocol-based workflow orchestration system designed for coordinating LLM workflows, batch processing, and multi-task execution patterns. It provides a simple yet powerful framework for creating and executing complex workflows with support for multiple providers and protocols.

## Core Architecture

### Key Components

1. **ExecutionEngine** - The central orchestrator that manages workflow execution
2. **ProtocolProviderRegistry** - Manages protocol definitions and provider instances
3. **TaskQueue & QueueManager** - Handles task scheduling and execution order
4. **DependencyResolver** - Manages task dependencies and parameter substitution
5. **Persistence Backends** - SQLite, Redis, or in-memory storage for tasks and results

### Design Philosophy

Gleitzeit v0.0.4 follows a simplified, direct execution model:
- Protocol-based provider abstraction for extensibility
- Direct task execution without distributed coordination
- YAML-based workflow definitions for ease of use
- Built-in batch processing for file operations
- Parameter substitution for task chaining

## Supported Protocols

### 1. LLM Protocol (`llm/v1`)
- **Methods**: `chat`, `vision`
- **Provider**: OllamaProvider
- **Use Cases**: Text generation, image analysis, conversational AI

### 2. Python Protocol (`python/v1`)
- **Methods**: `execute`, `register`, `list`
- **Provider**: PythonFunctionProvider, CustomFunctionProvider
- **Use Cases**: Data processing, custom logic, integration tasks

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

## Batch Processing

Gleitzeit v0.0.4 includes powerful batch processing capabilities:

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

# Check status
gleitzeit system status

# View results
gleitzeit workflow status WORKFLOW_ID
```

## Persistence

Three backend options for storing tasks and results:

1. **SQLite** (default) - File-based persistence
2. **Redis** - For shared state across instances
3. **In-Memory** - For testing and temporary workflows

## Parameter Substitution

Tasks can use results from previous tasks:

```yaml
parameters:
  value: "${previous_task.response}"
  count: ${data_task.count}
  nested: "${config_task.settings.timeout}"
```

## Current Limitations

- No distributed coordination (single instance only)
- No real-time event streaming
- Limited provider pooling/scaling
- Basic error handling and retry logic

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

- **Current Version**: 0.0.4
- **Status**: Beta
- **Focus**: Core workflow orchestration with LLM and batch processing support

## Next Steps

For more detailed information, see:
- [Architecture Details](GLEITZEIT_V4_ARCHITECTURE.md)
- [Batch Processing Guide](BATCH_PROCESSING_DESIGN.md)
- [Provider Implementation Guide](PROVIDER_IMPLEMENTATION_GUIDE.md)
- [Workflow Parameter Substitution](WORKFLOW_PARAMETER_SUBSTITUTION.md)