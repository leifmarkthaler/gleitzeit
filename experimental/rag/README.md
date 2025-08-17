# RAG (Retrieval-Augmented Generation) for Gleitzeit

This experimental implementation adds RAG capabilities to Gleitzeit, enabling document ingestion, embedding generation, similarity search, and context-aware question answering.

## Architecture

### Components

1. **EmbeddingsProvider** (`embeddings_provider.py`)
   - Document chunking with configurable overlap
   - Embedding generation using Ollama models (nomic-embed-text)
   - In-memory vector storage with cosine similarity search
   - Caching for efficient embedding reuse

2. **RAGProvider** (`rag_provider.py`)
   - Document ingestion from files or directories
   - Context retrieval based on similarity search
   - LLM generation with retrieved context
   - Query with or without context augmentation

3. **RAGClient** (`rag_client.py`)
   - High-level Python API for RAG operations
   - Async context manager for resource management
   - Simplified methods for common RAG tasks

## Installation

```bash
# Install required dependencies
pip install numpy aiohttp

# Ensure Ollama is running with required models
ollama pull nomic-embed-text  # For embeddings
ollama pull llama3.2          # For generation
```

## Usage

### Python API

```python
import asyncio
from experimental.rag.rag_client import RAGClient

async def main():
    config = {
        'ollama_endpoint': 'http://localhost:11434',
        'embedding_model': 'nomic-embed-text',
        'chat_model': 'llama3.2:latest',
        'chunk_size': 512,
        'chunk_overlap': 50
    }
    
    async with RAGClient(config) as rag:
        # Ingest documents
        await rag.ingest_directory('./documents', '*.txt')
        
        # Query with context
        response = await rag.query("What are the main topics?")
        print(response['response'])
        
        # View sources used
        for source in response['sources']:
            print(f"Source: {source['id']} (score: {source['score']:.3f})")
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

## Performance Considerations

### Embedding Cache
- Embeddings are cached in memory by content hash
- Reduces redundant API calls to Ollama
- Cache persists for session duration

### Chunk Size Optimization
- Smaller chunks (256-512): Better precision, more API calls
- Larger chunks (1024-2048): More context, fewer calls
- Overlap prevents information loss at boundaries

### Vector Storage
- Currently uses in-memory storage (fast but ephemeral)
- Can be extended to use persistent vector databases:
  - ChromaDB
  - Pinecone
  - Weaviate
  - Qdrant

## Limitations

1. **In-Memory Storage**: Document index is lost on restart
2. **Single Model**: Uses one embedding model for all content
3. **No Incremental Updates**: Documents must be re-indexed entirely
4. **Basic Ranking**: Simple cosine similarity without re-ranking

## Future Enhancements

1. **Persistent Storage**
   - Integration with vector databases
   - SQLite for metadata storage
   - Redis for embedding cache

2. **Advanced Retrieval**
   - Hybrid search (keyword + semantic)
   - Re-ranking with cross-encoders
   - Query expansion techniques

3. **Multi-Modal Support**
   - Image embeddings with CLIP
   - PDF and document parsing
   - Table and structured data handling

4. **Performance**
   - Batch embedding generation
   - Async parallel processing
   - GPU acceleration support

5. **Production Features**
   - Document versioning
   - Access control
   - Usage analytics
   - A/B testing for retrieval strategies

## Testing

```bash
# Run RAG tests
python experimental/rag/test_rag.py

# Test with sample documents
python experimental/rag/rag_client.py
```

## Integration with Gleitzeit

The RAG implementation follows Gleitzeit's protocol-based architecture:

1. **Protocol Compliance**: Implements ProtocolProvider interface
2. **Task Integration**: Works with workflow engine
3. **Parameter Substitution**: Supports ${task_id.field} references
4. **Persistence**: Compatible with Gleitzeit's storage backends
5. **Error Handling**: Follows Gleitzeit's retry and fallback patterns

## Example: Building a Documentation Assistant

```python
import asyncio
from experimental.rag.rag_client import RAGClient

async def build_docs_assistant():
    async with RAGClient() as rag:
        # Ingest all documentation
        await rag.ingest_directory('./docs', '*.md')
        await rag.ingest_directory('./examples', '*.yaml')
        
        # Create Q&A interface
        while True:
            question = input("\nAsk about Gleitzeit: ")
            if question.lower() in ['exit', 'quit']:
                break
            
            response = await rag.query(question)
            print(f"\nAnswer: {response['response']}")
            
            if response['sources']:
                print("\nSources:")
                for source in response['sources'][:3]:
                    print(f"  - {source['metadata'].get('filename', source['id'])}")

asyncio.run(build_docs_assistant())
```

## License

This experimental RAG implementation follows Gleitzeit's MIT license.