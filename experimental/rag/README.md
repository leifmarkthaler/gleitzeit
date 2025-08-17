# RAG (Retrieval-Augmented Generation) for Gleitzeit

A production-ready RAG implementation for Gleitzeit that provides document ingestion, vector search, and intelligent question answering using Redis Stack for persistent vector storage.

## 🚀 Quick Start

```bash
# 1. Start Redis Stack with vector support
./start_redis_vector_alt.sh

# 2. Run Q&A test
python test_qa_system.py

# 3. Try interactive Q&A
python test_qa_interactive.py
```

## 📚 Documentation

- **[QUICK_START.md](QUICK_START.md)** - Get started in 5 minutes
- **[DOCUMENTATION.md](DOCUMENTATION.md)** - Complete API reference and guides
- **[RAG_BACKEND_DESIGN.md](RAG_BACKEND_DESIGN.md)** - Architecture and design decisions
- **[TEST_RESULTS.md](TEST_RESULTS.md)** - Performance benchmarks and test results

## Architecture

### Core Components

1. **EmbeddingsProvider** (`embeddings_provider.py`)
   - Document chunking with configurable overlap (default: 300/75 tokens)
   - Embedding generation using Ollama's nomic-embed-text (768 dimensions)
   - Fallback to mock embeddings when Ollama unavailable
   - Efficient caching and batch processing

2. **RAGProvider** (`rag_provider.py`)
   - Complete RAG pipeline orchestration
   - Document ingestion with metadata preservation
   - Context-aware query processing
   - Multi-document search and retrieval

3. **RedisVectorAdapter** (`redis_vector_adapter.py`)
   - Persistent vector storage using Redis Stack
   - HNSW indexing for fast similarity search
   - Hybrid search combining text and vector similarity
   - Support for metadata filtering

4. **QASystem** (`test_qa_system.py`)
   - Interactive question-answering interface
   - Knowledge base management
   - Context retrieval and answer generation
   - Performance monitoring and statistics

## Key Features

✅ **Production-Ready Vector Storage**
- Redis Stack with RediSearch module
- HNSW indexing for sub-30ms search
- Persistent storage across restarts
- Supports millions of vectors

✅ **Intelligent Document Processing**
- Smart chunking with overlap
- Metadata preservation
- Batch processing support
- Multiple file format support

✅ **Advanced Search Capabilities**
- Semantic similarity search
- Hybrid text + vector search
- Metadata filtering
- Top-k retrieval with scoring

✅ **Q&A System**
- Context-aware answer generation
- Source attribution
- Interactive and batch modes
- Performance monitoring

## Installation

```bash
# Install Python dependencies
uv pip install redis numpy aiohttp

# Install Ollama (optional but recommended)
brew install ollama  # macOS
ollama pull nomic-embed-text  # For embeddings
ollama pull llama3.2          # For generation

# Start Redis Stack
docker-compose -f docker-compose-alt-port.yml up -d
```

## Usage Examples

### Basic Q&A System

```python
import asyncio
from test_qa_system import QASystem

async def main():
    # Initialize Q&A system
    qa = QASystem(redis_port=6380)
    await qa.initialize()
    
    # Load documents
    docs = [{
        'id': 'doc1',
        'title': 'Gleitzeit Guide',
        'content': 'Gleitzeit is a workflow orchestration system...',
        'category': 'documentation'
    }]
    await qa.load_knowledge_base(docs)
    
    # Ask questions
    result = await qa.ask_question(
        "What is Gleitzeit?",
        verbose=True
    )
    print(f"Answer: {result['answer']}")
    print(f"Response time: {result['timing']['total_ms']:.1f}ms")
    
    await qa.cleanup()

asyncio.run(main())
```

### Document Ingestion with Embeddings

```python
from embeddings_provider import EmbeddingsProvider
from redis_vector_adapter import RedisVectorAdapter
import redis

async def ingest():
    # Setup
    r = redis.Redis(port=6380, decode_responses=True)
    embeddings = EmbeddingsProvider({'chunk_size': 300})
    vector_store = RedisVectorAdapter(
        redis_client=r,
        index_name="my_docs",
        embedding_dim=768
    )
    
    await embeddings.initialize()
    await vector_store.initialize()
    
    # Process document
    text = "Your document content here..."
    chunks = embeddings.chunk_text(text)
    
    for i, chunk in enumerate(chunks):
        embedding = await embeddings.generate_embedding(chunk)
        await vector_store.store_embedding(
            doc_id=f"chunk_{i}",
            text=chunk,
            embedding=embedding,
            metadata={'source': 'manual'}
        )

asyncio.run(ingest())
```

### Workflow YAML

```yaml
name: "RAG Q&A"
tasks:
  - id: "ingest"
    method: "rag/ingest_directory"
    parameters:
      directory: "./docs"
      pattern: "*.md"
  
  - id: "query"
    method: "rag/query"
    dependencies: ["ingest"]
    parameters:
      query: "Explain the main concepts"
      use_context: true
```

### CLI Usage

```bash
# Run RAG workflow
gleitzeit run experimental/rag/rag_workflow.yaml

# Batch process documents
gleitzeit run experimental/rag/rag_batch_workflow.yaml
```

## Protocol Methods

### embeddings/v1

- `chunk_text`: Split text into overlapping chunks
- `generate_embedding`: Create vector embedding for text
- `index_documents`: Store documents with embeddings
- `search_similar`: Find similar documents by vector similarity
- `retrieve_context`: Get relevant context for a query

### rag/v1

- `ingest_documents`: Process and index document list
- `ingest_directory`: Index all files matching pattern
- `query`: Answer questions using RAG
- `query_with_context`: Query with additional context
- `clear_index`: Clear the document index

## Configuration

### Environment Variables

```bash
# Ollama configuration
GLEITZEIT_OLLAMA_ENDPOINT=http://localhost:11434
GLEITZEIT_EMBEDDING_MODEL=nomic-embed-text
GLEITZEIT_CHAT_MODEL=llama3.2:latest

# RAG parameters
GLEITZEIT_CHUNK_SIZE=512
GLEITZEIT_CHUNK_OVERLAP=50
GLEITZEIT_TOP_K=5
GLEITZEIT_SIMILARITY_THRESHOLD=0.3
```

### Config File

```yaml
# ~/.gleitzeit/config.yaml
rag:
  ollama_endpoint: http://localhost:11434
  embedding_model: nomic-embed-text
  chat_model: llama3.2:latest
  chunk_size: 512
  chunk_overlap: 50
  top_k: 5
  context_max_tokens: 2000
  similarity_threshold: 0.3
```

## Features

### Document Chunking
- Smart chunking with sentence boundary detection
- Configurable chunk size and overlap
- Metadata preservation for source tracking

### Embedding Generation
- Uses Ollama's embedding models
- Caching for performance optimization
- Support for batch processing

### Similarity Search
- Cosine similarity for vector comparison
- Top-k retrieval with score threshold
- Metadata filtering support

### Context-Aware Generation
- Automatic context injection into prompts
- Source attribution in responses
- Fallback to non-contextual generation

## Example Workflows

### 1. Knowledge Base Q&A

```python
async with RAGClient() as rag:
    # Build knowledge base
    await rag.ingest_directory('./knowledge_base', '*.md')
    
    # Ask questions
    response = await rag.query("How does the system handle errors?")
    print(f"Answer: {response['response']}")
    print(f"Based on {len(response['sources'])} sources")
```

### 2. Document Comparison

```python
# Ingest two documents
docs = [
    {'id': 'v1', 'text': 'Version 1 documentation...'},
    {'id': 'v2', 'text': 'Version 2 documentation...'}
]
await rag.ingest_documents(docs)

# Query about differences
response = await rag.query("What changed between versions?")
```

### 3. Contextual Search

```python
# Search with additional context
response = await rag.query_with_context(
    query="How do I implement this feature?",
    additional_context="I'm using Python 3.11 with async/await"
)
```

## Performance

### Benchmarks (Tested Configuration)

| Metric | Result |
|--------|--------|
| Average query response time | 28.6ms |
| Document ingestion | 20 chunks/sec |
| Vector search (HNSW) | 35 queries/sec |
| Knowledge base size tested | 30 chunks |
| Embedding dimensions | 768 |
| Success rate | 100% |

### Optimization Tips

1. **Chunk Size**: Default 300 tokens with 75 overlap
2. **HNSW Parameters**: M=16, EF=200 for optimal speed/quality
3. **Batch Processing**: Process multiple documents in parallel
4. **Caching**: Embeddings cached for repeated queries
5. **Persistence**: Redis AOF for durability

## Test Results

✅ **All 15 Q&A tests passed**
- Questions about architecture, RAG concepts, workflows
- Consistent retrieval accuracy
- Persistent storage verified
- Performance within targets

See [TEST_RESULTS.md](TEST_RESULTS.md) for detailed benchmarks.

## Project Structure

```
experimental/rag/
├── DOCUMENTATION.md          # Complete API reference
├── QUICK_START.md           # 5-minute setup guide
├── RAG_BACKEND_DESIGN.md    # Architecture design
├── TEST_RESULTS.md          # Performance benchmarks
├── embeddings_provider.py   # Embedding generation
├── rag_provider.py          # RAG orchestration
├── redis_vector_adapter.py  # Vector storage
├── test_qa_system.py        # Q&A implementation
├── test_qa_interactive.py   # Interactive mode
├── test_rag_working.py      # Basic tests
├── docker-compose-alt-port.yml  # Redis Stack config
└── start_redis_vector_alt.sh    # Launch script
```

## Testing

```bash
# Test Redis vector support
python test_redis_vectors_port.py --test-both

# Run comprehensive Q&A tests
python test_qa_system.py

# Test persistence
python test_rag_redis_persistence.py

# Interactive testing
python test_qa_interactive.py
```

## Integration with Gleitzeit

The RAG system seamlessly integrates with Gleitzeit's architecture:

✅ **Protocol Compliance**: Full ProtocolProvider implementation
✅ **Workflow Support**: Works with YAML workflows and task dependencies
✅ **Parameter Substitution**: Supports ${task_id.field} references
✅ **Unified Persistence**: Uses Gleitzeit's storage patterns
✅ **Error Handling**: Automatic retries and fallbacks

## Roadmap

- [ ] Web UI for document management
- [ ] Additional embedding models support
- [ ] Multi-modal RAG (images, PDFs)
- [ ] Distributed vector search
- [ ] Real-time document updates
- [ ] Analytics dashboard

## Support

- **Issues**: [GitHub Issues](https://github.com/leifmarkthaler/gleitzeit/issues)
- **Documentation**: See [DOCUMENTATION.md](DOCUMENTATION.md)
- **Quick Start**: See [QUICK_START.md](QUICK_START.md)

## License

This experimental RAG implementation follows Gleitzeit's MIT license.