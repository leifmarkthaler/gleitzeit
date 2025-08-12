# 🚀 Gleitzeit Out-of-the-Box Guide

Your unified Gleitzeit architecture with Ollama integration is now ready to use with simple commands!

## 🔧 Prerequisites (One-time setup)

```bash
# 1. Start Ollama server
ollama serve

# 2. Download a model (optional - Gleitzeit will show available models)
ollama pull phi3:mini      # Fast, lightweight model
ollama pull llama3.2       # Larger, more capable model

# 3. Start Redis server
redis-server
```

## ⚡ Quick Start

### 1. Start Gleitzeit (in terminal 1)
```bash
gleitzeit serve
```

You'll see:
```
🚀 Starting Gleitzeit with Ollama Integration
==================================================
   Host: localhost
   Port: 8000
   Redis: ✅ Enabled

🤖 Auto-connecting Ollama provider...
   ✅ Ollama connected (9 models)
   📋 Available models: llama3.2:latest, phi3:mini, nomic-embed-text...

🌐 Gleitzeit is running at http://localhost:8000
   Press Ctrl+C to stop
```

### 2. Ask questions (in terminal 2)
```bash
# Simple question
gleitzeit ask "What is Python?"

# Use specific model
gleitzeit ask "Explain machine learning" --model llama3.2

# Control response length
gleitzeit ask "Write a hello world function" --max-tokens 100
```

## 🎯 Example Session

```bash
Terminal 1:
$ gleitzeit serve
🚀 Starting Gleitzeit with Ollama Integration
✅ Ollama connected (9 models)
🌐 Gleitzeit is running at http://localhost:8000

Terminal 2:
$ gleitzeit ask "What is bread?"
🤖 Asking: What is bread?

⏳ Processing...
==================================================
🤖 phi3:mini: Bread is a staple food prepared from a dough 
of flour and water, typically by baking. It has been made 
for thousands of years across various cultures as one of 
the oldest types of leavened products known to humanity.
==================================================
```

## 🛠️ Advanced Usage

### Custom Configuration
```bash
# Run on different port
gleitzeit serve --port 9000

# Use different Redis
gleitzeit serve --redis-url redis://remote:6379

# Run without Redis (memory only)
gleitzeit serve --no-redis
```

### Model Selection
```bash
# List all available commands
gleitzeit --help

# Use specific model with custom parameters
gleitzeit ask "Write Python code" \
  --model llama3.2 \
  --temperature 0.1 \
  --max-tokens 300
```

### Programming Integration
```python
# Direct Python usage (if Gleitzeit is running)
from gleitzeit_cluster.core.task import Task, TaskType, TaskParameters
from gleitzeit_cluster.core.cluster_client import GleitzeitClusterClient

async def ask_gleitzeit(question):
    client = GleitzeitClusterClient(socketio_url="http://localhost:8000")
    await client.start()
    
    task = Task(
        name="my_question",
        task_type=TaskType.EXTERNAL_CUSTOM,
        parameters=TaskParameters(
            prompt=question,
            model="phi3:mini",
            service_name="ollama"
        )
    )
    
    result = await client.cluster.task_executor.execute_task(task)
    await client.stop()
    
    return result.get('response', result)
```

## 🎉 What You Get

✅ **Unified Architecture**: Single command starts everything  
✅ **Local LLM Orchestration**: Direct access to your Ollama models  
✅ **Scalable**: Same interface works for local and distributed execution  
✅ **Real-time**: Socket.IO coordination for responsive interaction  
✅ **Extensible**: Add more providers (OpenAI, Anthropic, etc.) easily  
✅ **Production Ready**: Redis persistence, error handling, monitoring  

## 🔍 Troubleshooting

**"Cannot connect to Ollama"**
- Make sure `ollama serve` is running
- Check if models are available: `ollama list`

**"Cannot connect to Gleitzeit service"**
- Start the service first: `gleitzeit serve`
- Check if port 8000 is free: `lsof -i :8000`

**"Redis connection failed"**
- Start Redis: `redis-server`
- Or use: `gleitzeit serve --no-redis`

## 🚀 Next Steps

Now that you have the basic system running:

1. **Explore Models**: Try different Ollama models
2. **Build Workflows**: Chain multiple LLM tasks together  
3. **Add Providers**: Integrate external APIs (OpenAI, etc.)
4. **Scale Up**: Add more executor nodes for distributed processing
5. **Monitor**: Use the built-in monitoring tools

Your unified Gleitzeit + Ollama system is ready for both local development and production scaling!