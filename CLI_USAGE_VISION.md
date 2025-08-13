# CLI Usage for Vision Workflows

## Mixed Vision + Text Workflow

### Prerequisites

1. **Install Ollama models**:
```bash
ollama pull llava:latest    # For vision tasks
ollama pull llama3.2        # For text tasks
```

2. **Verify models are available**:
```bash
ollama list
```

### Quick Start

#### Option 1: One-Command Execution
```bash
# Start everything and run the mixed workflow
gleitzeit run examples/mixed_vision_text_workflow.yaml
```

#### Option 2: Step-by-Step
```bash
# 1. Start the hub and components
gleitzeit start

# 2. Submit the workflow (in another terminal)
gleitzeit submit examples/mixed_vision_text_workflow.yaml

# 3. Monitor progress
gleitzeit status
```

#### Option 3: With Custom Provider
```bash
# 1. Start hub only
gleitzeit hub --port 8001

# 2. Start your vision-enabled provider (custom script)
python test_vision_extension.py

# 3. Submit workflow
gleitzeit submit examples/mixed_vision_text_workflow.yaml --hub-url http://localhost:8001
```

### Available Vision Workflows

1. **Mixed Vision + Text** (`mixed_vision_text_workflow.yaml`):
   - Vision analysis → Creative story generation
   - 2 tasks: LLaVa + Ollama

2. **Full Vision Pipeline** (`vision_workflow.yaml`):
   - Vision analysis → Color extraction → Summary
   - 3 tasks: LLaVa + 2x Ollama

### CLI Commands Reference

#### Submit Workflow
```bash
gleitzeit submit examples/mixed_vision_text_workflow.yaml
```

#### Check Status
```bash
gleitzeit status
```

#### Monitor Real-time
```bash
gleitzeit monitor
```

#### List Available Providers
```bash
gleitzeit providers
```

### Expected Output

When you run the mixed workflow, you'll see:

```
📊 Task analyze-scene: The image is a colorful pattern with red, blue, green, yellow...
📊 Task write-story: As Luna's fingers danced across the ancient loom, the colorful threads...
```

### Troubleshooting

#### Issue: "No providers available"
**Solution**: Start a vision-enabled provider:
```bash
python test_vision_extension.py
```

#### Issue: "LLaVa model not found"
**Solution**: Pull the model:
```bash
ollama pull llava:latest
```

#### Issue: "Hub not running"
**Solution**: Start the hub:
```bash
gleitzeit start --hub-only
```

### Custom Usage

#### Create Your Own Vision Workflow

1. **Create YAML file**:
```yaml
name: "My Vision Workflow"
tasks:
  - id: analyze-image
    method: llm/vision
    parameters:
      model: llava:latest
      prompt: "What do you see?"
      images: ["<your-base64-image>"]
  
  - id: process-result
    method: llm/chat
    dependencies: ["analyze-image"]
    parameters:
      model: llama3.2
      messages:
        - role: user
          content: "Process this: ${analyze-image.response}"
```

2. **Submit it**:
```bash
gleitzeit submit my_workflow.yaml
```

### Integration Examples

#### With Python Script
```python
import subprocess
import json

# Submit workflow
result = subprocess.run([
    'gleitzeit', 'submit', 'examples/mixed_vision_text_workflow.yaml'
], capture_output=True, text=True)

print(f"Workflow submitted: {result.returncode == 0}")
```

#### With Shell Script
```bash
#!/bin/bash
echo "Starting vision workflow..."
gleitzeit start --background
sleep 5
gleitzeit submit examples/mixed_vision_text_workflow.yaml
gleitzeit status
```

### Performance Tips

1. **Use background mode** for faster iteration:
```bash
gleitzeit start --background
```

2. **Monitor with intervals**:
```bash
gleitzeit monitor --interval 1
```

3. **Use specific hub URL** for multiple instances:
```bash
gleitzeit submit workflow.yaml --hub-url http://localhost:8002
```