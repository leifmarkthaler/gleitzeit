# Gleitzeit - Modern Workflow Orchestration

Gleitzeit is a modern, Socket.IO-based workflow orchestration system designed for real-time distributed task execution. It features a clean component-based architecture with beautiful CLI tooling.

## ✨ Features

- **Real-time Communication**: Socket.IO-based event system for instant updates
- **Component-Based Architecture**: Modular design with hub, queue manager, dependency resolver, and execution engine
- **Protocol Support**: Extensible protocol system (LLM, Python execution, etc.)
- **YAML Configuration**: Easy provider and protocol configuration
- **Beautiful CLI**: Rich terminal interface with status monitoring
- **Dependency Resolution**: Smart parameter substitution between tasks
- **Parallel Execution**: Automatic parallel execution of independent tasks

## 🚀 Quick Start

### Installation

```bash
cd gleitzeit
pip install -e .
```

### Super Simple (Recommended)

```bash
# One command to start everything
gleitzeit start

# One command to run a complete workflow  
gleitzeit run examples/simple_llm_workflow.yaml
```

### Auto-Start Features

The CLI automatically starts the hub when needed:

```bash
# These commands auto-start the hub if it's not running
gleitzeit submit examples/simple_llm_workflow.yaml  # ← Hub starts automatically
gleitzeit monitor                                   # ← Hub starts automatically  
gleitzeit components all                           # ← Hub starts automatically
```

### Manual Control (If Preferred)

```bash
# 1. Start the hub manually
gleitzeit hub --port 8001

# 2. In another terminal, start components
gleitzeit components all

# 3. Check status
gleitzeit status

# 4. Submit a workflow
gleitzeit submit examples/simple_llm_workflow.yaml
```

## 📋 CLI Commands

### Core Commands

- `gleitzeit start` - Quick start everything (hub + components)
- `gleitzeit run <workflow.yaml>` - One command: start + submit workflow
- `gleitzeit status` - Show system status
- `gleitzeit monitor` - Real-time monitoring (auto-starts hub)

### Workflow Commands

- `gleitzeit submit <workflow.yaml>` - Submit workflow (auto-starts hub)
- `gleitzeit providers` - List available providers

### Component Commands

- `gleitzeit hub` - Start just the central hub
- `gleitzeit components <names>` - Start specific components (auto-starts hub)

### Management Commands

- `gleitzeit version` - Show version info

## 📁 Workflow Examples

The `examples/` directory contains sample workflows:

- `simple_llm_workflow.yaml` - Basic LLM tasks
- `dependent_workflow.yaml` - Tasks with dependencies
- `mixed_workflow.yaml` - LLM + Python execution
- `parallel_workflow.yaml` - Parallel task execution

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Central Hub   │◄───┤  Queue Manager   │◄───┤     Client      │
│   (Socket.IO)   │    │   (Tasks)        │    │  (Submit Work)  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐    ┌──────────────────┐
│ Execution Engine│    │ Dependency       │
│   (Providers)   │    │ Resolver         │
└─────────────────┘    └──────────────────┘
         │
         ▼
┌─────────────────┐
│   Providers     │
│ (Ollama, Python)│
└─────────────────┘
```

## 🔧 Component Details

### Central Hub
- Socket.IO server for real-time communication
- Event routing between components
- Health monitoring and statistics

### Queue Manager
- Task queuing with priority support
- Workflow coordination
- Task lifecycle management

### Dependency Resolver
- Parameter substitution (`${task-id.field}`)
- Task dependency resolution
- Result caching

### Execution Engine
- Provider coordination
- Load balancing
- Retry logic and error handling

### Providers
- Pluggable execution backends
- Protocol-based validation
- YAML configuration support

## 📝 Workflow Format

Workflows are defined in YAML:

```yaml
name: "My Workflow"
description: "Workflow description"
timeout: 120
wait_for_completion: true

tasks:
  - id: "task1"
    method: "llm/chat"
    priority: 2
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Hello, world!"
  
  - id: "task2"
    method: "python/execute"
    dependencies: ["task1"]
    parameters:
      code: "print('Result:', '${task1.response}')"
```

## 🛠️ Development

### Running Tests

```bash
# Install development dependencies
pip install -e .[dev]

# Run tests
pytest gleitzeit/
```

### Available Providers

Currently supported providers:
- **Ollama LLM**: Local LLM execution via Ollama
- **Python**: Safe Python code execution
- **Custom**: Extend with your own providers

### Adding New Providers

1. Create YAML configuration in `providers/yaml/`
2. Implement executor in `core/executor_base.py`
3. Register with the system

## 🔍 Monitoring

Real-time monitoring with beautiful terminal output:

```bash
# Monitor system status
gleitzeit monitor

# Check component health
gleitzeit status
```

## 🚨 Prerequisites

- Python 3.9+
- Ollama (for LLM workflows): `ollama serve`
- Rich library for beautiful output: Included in requirements

## 📖 Examples Usage

### Simple LLM Task
```bash
# One command does everything
gleitzeit run examples/simple_llm_workflow.yaml
```

### Dependent Tasks
```bash
# Auto-starts hub and components, then submits workflow
gleitzeit run examples/dependent_workflow.yaml
```

### Mixed Providers
```bash
# Starts entire system and runs complex workflow
gleitzeit run examples/mixed_workflow.yaml
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details.

---

**Gleitzeit** - Modern workflow orchestration made simple! 🚀