# RAG System Quick Start Guide

## 🚀 Get Started in 5 Minutes

### Step 1: Install Dependencies

```bash
# Install Python packages
uv pip install redis numpy aiohttp

# Install Ollama (optional but recommended)
brew install ollama  # macOS
ollama pull nomic-embed-text
ollama pull llama3.2
```

### Step 2: Start Redis Stack

```bash
# Start Redis Stack with vector support on port 6380
./start_redis_vector_alt.sh

# Verify it's working
python test_redis_vectors_port.py --port 6380
```

### Step 3: Run Your First Q&A

```bash
# Load knowledge base and test Q&A
python test_qa_system.py

# Try interactive mode
python test_qa_interactive.py
```

## 📝 Basic Usage Examples

### Load Documents and Ask Questions

```python
import asyncio
from test_qa_system import QASystem

async def quick_qa():
    # Initialize
    qa = QASystem(redis_port=6380)
    await qa.initialize()
    
    # Load a document
    docs = [{
        'id': 'doc1',
        'title': 'Python Guide',
        'content': 'Python is a versatile programming language...',
        'category': 'tutorial'
    }]
    await qa.load_knowledge_base(docs)
    
    # Ask a question
    result = await qa.ask_question("What is Python?")
    print(result['answer'])
    
    await qa.cleanup()

asyncio.run(quick_qa())
```

### Process Multiple Files

```python
async def process_folder():
    qa = QASystem()
    await qa.initialize()
    
    import glob
    for file in glob.glob("docs/*.txt"):
        with open(file) as f:
            await qa.load_knowledge_base([{
                'id': file,
                'title': file.split('/')[-1],
                'content': f.read()
            }])
    
    # Now ask questions about any document
    result = await qa.ask_question("What are the main topics?")
    print(result['answer'])

asyncio.run(process_folder())
```

## 🎯 Common Commands

### Testing
```bash
# Test everything is working
python test_rag_working.py

# Test Q&A system
python test_qa_system.py

# Interactive Q&A
python test_qa_interactive.py

# Test Redis vectors
python test_redis_vectors_port.py --test-both
```

### Docker Management
```bash
# Start Redis Stack
docker-compose -f docker-compose-alt-port.yml up -d

# Stop Redis Stack
docker-compose -f docker-compose-alt-port.yml down

# View logs
docker logs redis-vector -f

# Access Redis CLI
redis-cli -p 6380
```

### Ollama Management
```bash
# Start Ollama
ollama serve

# List models
ollama list

# Pull models
ollama pull nomic-embed-text
ollama pull llama3.2

# Test embedding
curl -X POST http://localhost:11434/api/embeddings \
  -d '{"model": "nomic-embed-text", "prompt": "test"}'
```

## 🔧 Configuration

### Quick Config (`rag_config.yaml`)
```yaml
redis:
  port: 6380
  
embeddings:
  model: nomic-embed-text
  dimensions: 768
  
chunking:
  size: 300
  overlap: 75
```

### Environment Variables
```bash
export REDIS_PORT=6380
export OLLAMA_HOST=http://localhost:11434
export RAG_CHUNK_SIZE=300
```

## 📊 Performance Tips

1. **Faster Search**: Use HNSW indexing (default)
2. **Better Quality**: Increase chunk overlap
3. **Lower Latency**: Cache frequent queries
4. **Higher Throughput**: Batch document processing

## 🆘 Troubleshooting

### Redis not connecting?
```bash
# Check if running
docker ps | grep redis-vector

# Test connection
redis-cli -p 6380 ping
```

### Ollama not working?
```bash
# Start service
ollama serve

# Check status
curl http://localhost:11434/api/tags
```

### Slow performance?
```python
# Use fewer chunks
qa = QASystem()
qa.chunk_size = 500  # Larger chunks

# Reduce search scope
result = await qa.ask_question(question, top_k=3)  # Fewer results
```

## 📚 Next Steps

1. Read full [DOCUMENTATION.md](DOCUMENTATION.md)
2. Explore [API Reference](#api-reference)
3. Check [TEST_RESULTS.md](TEST_RESULTS.md)
4. Review [RAG_BACKEND_DESIGN.md](RAG_BACKEND_DESIGN.md)

## 💡 Pro Tips

- **Mock Mode**: System works without Ollama (uses mock embeddings)
- **Persistence**: Data survives Redis restarts
- **Filtering**: Use metadata to narrow searches
- **Batch Loading**: Process multiple documents at once
- **Interactive Mode**: Great for testing and debugging

## 🎉 Success Checklist

- [ ] Redis Stack running on port 6380
- [ ] Python dependencies installed
- [ ] Ollama installed (optional)
- [ ] Test scripts passing
- [ ] Q&A system responding

Ready to build your RAG application! 🚀