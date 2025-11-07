# Gleitzeit Quick Start

## 🚀 Simple Commands

Gleitzeit now has simplified commands for common operations:

### Start the System
```bash
# Start with default config (gleitzeit.yaml)
gleitzeit start

# Start with custom config
gleitzeit start --config my-config.yaml
```

### Check Status
```bash
# Quick system status
gleitzeit status
```

### Submit Workflows
```bash
# Submit a workflow (auto-starts orchestrator if needed!)
gleitzeit submit workflow.yaml

# Submit with specific format
gleitzeit submit workflow.py --format python

# Disable auto-start if you want manual control
gleitzeit submit workflow.yaml --no-auto-start
```

### Stop the System
```bash
# Graceful shutdown
gleitzeit stop

# Force shutdown
gleitzeit stop --force
```

## 📄 Configuration

Create a `gleitzeit.yaml` file in your project directory:

```yaml
# Minimal configuration
redis:
  mode: single
  single_node:
    host: localhost
    port: 6379

workers:
  - worker_type: task_execution
    count: 3
  - worker_type: dependency
    count: 2
  - worker_type: workflow_loader_v2
    count: 1
```

## 🔧 Full Commands

For more control, use the full command structure:

```bash
# Orchestrator management
gleitzeit orchestrator start
gleitzeit orchestrator status

# Worker management
gleitzeit worker start --type task_execution --count 3
gleitzeit worker list

# Workflow management
gleitzeit workflow submit workflow.yaml
gleitzeit workflow status <workflow-id>
gleitzeit workflow list

# Admin commands
gleitzeit admin metrics
gleitzeit admin clear-streams --confirm
```

## 🏃 Quick Example

1. **Create a workflow** (`hello.yaml`):
```yaml
name: hello-world
tasks:
  - id: greet
    type: python
    code: |
      result = {"message": "Hello, World!"}
```

2. **Just submit it!** (auto-starts if needed):
```bash
gleitzeit submit hello.yaml
```

3. **Check status**:
```bash
gleitzeit status
```

4. **Stop when done**:
```bash
gleitzeit stop
```

### 🎯 Even Simpler!
You don't need to manually start Gleitzeit anymore. Just submit your workflow and it will:
1. Check if orchestrator is running
2. Start it automatically if needed
3. Submit your workflow
4. Begin processing immediately

### Manual Control
If you prefer to manage the orchestrator yourself:
```bash
# Start manually
gleitzeit start

# Submit without auto-start
gleitzeit submit workflow.yaml --no-auto-start
```

## 🔍 Configuration Search Order

Gleitzeit looks for configuration in:
1. Current directory: `gleitzeit.yaml`
2. Config directory: `config/gleitzeit.yaml`
3. System: `/etc/gleitzeit/gleitzeit.yaml`
4. User home: `~/.gleitzeit/config.yaml`

## 🎯 That's It!

You're ready to orchestrate workflows with Gleitzeit. The system will automatically:
- Manage worker processes
- Handle task distribution across shards
- Scale workers based on load
- Monitor system health
- Process workflows efficiently