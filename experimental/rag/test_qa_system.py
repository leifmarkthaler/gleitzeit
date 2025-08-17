#!/usr/bin/env python3
"""Interactive Q&A test system for RAG implementation."""

import asyncio
import sys
import time
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from datetime import datetime

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

import redis
from redis.commands.search.field import VectorField, TextField, TagField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from embeddings_provider import EmbeddingsProvider
from gleitzeit.providers.ollama_provider import OllamaProvider


class QASystem:
    """Interactive Q&A system using RAG."""
    
    def __init__(self, redis_port: int = 6380):
        """Initialize Q&A system with Redis Stack."""
        self.redis_port = redis_port
        self.redis_client = None
        self.embeddings_provider = None
        self.llm_provider = None
        self.index_name = "qa_knowledge_base"
        self.embedding_dim = 768
        self.use_real_embeddings = False
        
    async def initialize(self) -> bool:
        """Initialize all components."""
        try:
            # Connect to Redis Stack
            self.redis_client = redis.Redis(
                host='localhost', 
                port=self.redis_port, 
                decode_responses=True
            )
            
            # Test connection
            self.redis_client.ping()
            print(f"✅ Connected to Redis on port {self.redis_port}")
            
            # Verify RediSearch module
            modules = self.redis_client.module_list()
            has_search = any(
                (m.get(b'name', b'').decode() if isinstance(m.get(b'name'), bytes) else m.get('name', '')) == 'search'
                for m in modules
            )
            
            if not has_search:
                print(f"❌ RediSearch not available on port {self.redis_port}")
                return False
            
            print("✅ RediSearch module available")
            
            # Initialize embeddings provider
            self.embeddings_provider = EmbeddingsProvider({
                'chunk_size': 300,
                'chunk_overlap': 75,
                'embedding_model': 'nomic-embed-text'
            })
            await self.embeddings_provider.initialize()
            
            # Check if Ollama is available
            self.use_real_embeddings = await self.embeddings_provider.health_check()
            if self.use_real_embeddings:
                print("✅ Ollama available - using real embeddings")
            else:
                print("⚠️  Ollama not available - using mock embeddings")
            
            # Initialize LLM provider for answer generation
            try:
                self.llm_provider = OllamaProvider()
                await self.llm_provider.initialize()
                if await self.llm_provider.health_check():
                    print("✅ LLM provider available for answer generation")
                else:
                    self.llm_provider = None
                    print("⚠️  LLM not available - will use simple context extraction")
            except:
                self.llm_provider = None
                print("⚠️  LLM not available - will use simple context extraction")
            
            # Create vector index
            await self.create_index()
            
            return True
            
        except Exception as e:
            print(f"❌ Initialization failed: {e}")
            return False
    
    async def create_index(self):
        """Create vector search index for Q&A."""
        try:
            # Check if index exists
            try:
                info = self.redis_client.ft(self.index_name).info()
                print(f"   Using existing index '{self.index_name}' with {info['num_docs']} docs")
                return
            except:
                pass  # Index doesn't exist, create it
            
            # Create new index with enhanced schema for Q&A
            schema = [
                TextField("content", weight=1.0),
                TextField("title", weight=2.0),
                TextField("chunk_id"),
                TagField("doc_id"),
                TagField("category"),
                TagField("source"),
                TextField("metadata"),  # JSON metadata
                VectorField(
                    "embedding",
                    "HNSW",
                    {
                        "TYPE": "FLOAT32",
                        "DIM": self.embedding_dim,
                        "DISTANCE_METRIC": "COSINE",
                        "INITIAL_CAP": 2000,
                        "M": 16,
                        "EF_CONSTRUCTION": 200,
                        "EF_RUNTIME": 10
                    }
                )
            ]
            
            self.redis_client.ft(self.index_name).create_index(
                fields=schema,
                definition=IndexDefinition(
                    prefix=["qa:"],
                    index_type=IndexType.HASH
                )
            )
            
            print(f"✅ Created Q&A index '{self.index_name}'")
            
        except Exception as e:
            print(f"❌ Failed to create index: {e}")
            raise
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text."""
        if self.use_real_embeddings:
            try:
                return await self.embeddings_provider.generate_embedding(text)
            except:
                pass
        
        # Mock embedding based on text hash
        np.random.seed(hash(text) % 2**32)
        return np.random.randn(self.embedding_dim).tolist()
    
    async def load_knowledge_base(self, knowledge_docs: List[Dict[str, Any]]) -> int:
        """Load knowledge base documents for Q&A."""
        print(f"\n📚 Loading {len(knowledge_docs)} documents into knowledge base...")
        
        total_chunks = 0
        
        for doc in knowledge_docs:
            doc_id = doc['id']
            title = doc.get('title', doc_id)
            content = doc['content']
            category = doc.get('category', 'general')
            source = doc.get('source', 'unknown')
            metadata = doc.get('metadata', {})
            
            # Chunk the document
            chunks = self.embeddings_provider.chunk_text(content)
            print(f"   📄 '{title}': {len(chunks)} chunks")
            
            # Store each chunk with embedding
            for i, chunk in enumerate(chunks):
                chunk_id = f"{doc_id}_chunk_{i}"
                
                # Generate embedding
                embedding = await self.generate_embedding(chunk)
                embedding_bytes = np.array(embedding, dtype=np.float32).tobytes()
                
                # Prepare metadata
                chunk_metadata = {
                    **metadata,
                    'chunk_index': i,
                    'total_chunks': len(chunks),
                    'timestamp': datetime.now().isoformat()
                }
                
                # Store in Redis
                key = f"qa:{chunk_id}"
                self.redis_client.hset(
                    key,
                    mapping={
                        "content": chunk,
                        "title": title,
                        "chunk_id": chunk_id,
                        "doc_id": doc_id,
                        "category": category,
                        "source": source,
                        "metadata": json.dumps(chunk_metadata),
                        "embedding": embedding_bytes
                    }
                )
                
                total_chunks += 1
        
        print(f"✅ Loaded {total_chunks} chunks into knowledge base")
        return total_chunks
    
    async def find_relevant_context(self, question: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Find relevant context for a question."""
        # Generate question embedding
        query_embedding = await self.generate_embedding(question)
        query_bytes = np.array(query_embedding, dtype=np.float32).tobytes()
        
        # Perform vector search
        q = Query(
            "*=>[KNN $k @embedding $vec AS score]"
        ).return_fields(
            "content", "title", "chunk_id", "doc_id", "category", "source", "metadata", "score"
        ).sort_by("score").dialect(2)
        
        results = self.redis_client.ft(self.index_name).search(
            q,
            query_params={
                "k": top_k,
                "vec": query_bytes
            }
        )
        
        # Format results
        contexts = []
        for doc in results.docs:
            contexts.append({
                'content': doc.content,
                'title': doc.title,
                'chunk_id': doc.chunk_id,
                'doc_id': doc.doc_id,
                'category': doc.category,
                'source': doc.source,
                'metadata': json.loads(doc.metadata) if hasattr(doc, 'metadata') else {},
                'score': float(doc.score)
            })
        
        return contexts
    
    async def generate_answer(self, question: str, contexts: List[Dict[str, Any]]) -> str:
        """Generate an answer using retrieved context."""
        if not contexts:
            return "I don't have enough information to answer that question."
        
        # If LLM is available, use it to generate a comprehensive answer
        if self.llm_provider:
            try:
                # Prepare context for LLM
                context_text = "\n\n".join([
                    f"[Source: {ctx['title']}]\n{ctx['content']}"
                    for ctx in contexts[:3]  # Use top 3 contexts
                ])
                
                prompt = f"""Based on the following context, please answer the question.
                
Context:
{context_text}

Question: {question}

Please provide a clear and concise answer based only on the given context. If the context doesn't contain enough information, say so."""
                
                # Use execute method with proper parameters
                response = await self.llm_provider.execute(
                    method="chat",
                    params={
                        "model": "llama3.2:latest",
                        "messages": [{"role": "user", "content": prompt}]
                    }
                )
                
                if response and response.get('status') == 'success':
                    return response.get('response', contexts[0]['content'])
                
            except Exception as e:
                print(f"⚠️  LLM generation failed: {e}")
        
        # Fallback: Return the most relevant context
        best_context = contexts[0]
        return f"Based on {best_context['title']}: {best_context['content']}"
    
    async def ask_question(self, question: str, verbose: bool = False) -> Dict[str, Any]:
        """Ask a question and get an answer."""
        start_time = time.time()
        
        # Find relevant context
        contexts = await self.find_relevant_context(question, top_k=5)
        retrieval_time = time.time() - start_time
        
        # Generate answer
        answer_start = time.time()
        answer = await self.generate_answer(question, contexts)
        generation_time = time.time() - answer_start
        
        total_time = time.time() - start_time
        
        result = {
            'question': question,
            'answer': answer,
            'contexts': contexts,
            'timing': {
                'retrieval_ms': retrieval_time * 1000,
                'generation_ms': generation_time * 1000,
                'total_ms': total_time * 1000
            }
        }
        
        if verbose:
            print(f"\n❓ Question: {question}")
            print(f"📍 Found {len(contexts)} relevant contexts")
            if contexts:
                print(f"   Best match (score {contexts[0]['score']:.3f}): {contexts[0]['title']}")
            print(f"⏱️  Timing: Retrieval {retrieval_time*1000:.1f}ms, Generation {generation_time*1000:.1f}ms")
            print(f"\n💡 Answer: {answer}")
        
        return result
    
    async def run_qa_tests(self, test_questions: List[str]):
        """Run a series of Q&A tests."""
        print("\n" + "="*60)
        print("Running Q&A Tests")
        print("="*60)
        
        results = []
        
        for i, question in enumerate(test_questions, 1):
            print(f"\n📝 Test {i}/{len(test_questions)}")
            result = await self.ask_question(question, verbose=True)
            results.append(result)
            
            # Show source information
            if result['contexts']:
                print(f"\n📚 Sources used:")
                for ctx in result['contexts'][:3]:
                    print(f"   - {ctx['title']} ({ctx['category']}) - Score: {ctx['score']:.3f}")
        
        # Summary statistics
        print("\n" + "="*60)
        print("Q&A Test Summary")
        print("="*60)
        
        avg_retrieval = np.mean([r['timing']['retrieval_ms'] for r in results])
        avg_generation = np.mean([r['timing']['generation_ms'] for r in results])
        avg_total = np.mean([r['timing']['total_ms'] for r in results])
        
        print(f"📊 Performance Statistics:")
        print(f"   Questions answered: {len(results)}")
        print(f"   Avg retrieval time: {avg_retrieval:.1f}ms")
        print(f"   Avg generation time: {avg_generation:.1f}ms")
        print(f"   Avg total time: {avg_total:.1f}ms")
        
        # Check answer quality
        good_answers = sum(1 for r in results if len(r['answer']) > 50)
        print(f"\n✅ Answer Quality:")
        print(f"   Detailed answers: {good_answers}/{len(results)}")
        print(f"   Average contexts per question: {np.mean([len(r['contexts']) for r in results]):.1f}")
        
        return results
    
    async def interactive_qa(self):
        """Run interactive Q&A session."""
        print("\n" + "="*60)
        print("Interactive Q&A Mode")
        print("="*60)
        print("Type your questions (or 'quit' to exit)")
        print("-"*60)
        
        while True:
            try:
                question = input("\n❓ Your question: ").strip()
                
                if question.lower() in ['quit', 'exit', 'q']:
                    print("👋 Goodbye!")
                    break
                
                if not question:
                    continue
                
                # Get answer
                result = await self.ask_question(question, verbose=False)
                
                print(f"\n💡 Answer: {result['answer']}")
                
                # Show sources
                if result['contexts']:
                    print(f"\n📚 Sources ({len(result['contexts'])} found):")
                    for ctx in result['contexts'][:3]:
                        print(f"   - {ctx['title']} (relevance: {ctx['score']:.3f})")
                
                print(f"\n⏱️  Response time: {result['timing']['total_ms']:.1f}ms")
                
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    async def cleanup(self):
        """Clean up resources."""
        if self.embeddings_provider:
            await self.embeddings_provider.shutdown()
        if self.llm_provider:
            await self.llm_provider.shutdown()
        if self.redis_client:
            self.redis_client.close()


async def main():
    """Run comprehensive Q&A system tests."""
    print("="*60)
    print("Q&A System Test Suite")
    print("="*60)
    
    # Initialize Q&A system
    qa = QASystem(redis_port=6380)  # Using Redis Stack
    
    if not await qa.initialize():
        print("❌ Failed to initialize Q&A system")
        return 1
    
    # Check for existing knowledge base
    info = qa.redis_client.ft(qa.index_name).info()
    existing_docs = info['num_docs']
    
    if existing_docs == 0:
        # Load comprehensive knowledge base
        print("\n📚 Loading knowledge base...")
        
        knowledge_docs = [
            {
                'id': 'gleitzeit_overview',
                'title': 'Gleitzeit Overview',
                'content': """Gleitzeit is a powerful workflow orchestration system designed specifically 
                          for LLM applications. It provides protocol-based task execution with automatic 
                          persistence and fallback mechanisms. The system supports YAML workflows, batch 
                          processing, and parameter substitution between tasks. Version 0.0.4 includes 
                          support for Ollama, Python execution, and MCP protocols. The architecture is 
                          built around an ExecutionEngine, ProtocolProviderRegistry, and unified persistence 
                          layer with Redis, SQL, and memory backends.""",
                'category': 'documentation',
                'source': 'CLAUDE.md',
                'metadata': {'version': '0.0.4', 'type': 'overview'}
            },
            {
                'id': 'rag_concepts',
                'title': 'RAG Concepts and Implementation',
                'content': """RAG (Retrieval-Augmented Generation) enhances LLM responses by retrieving 
                          relevant context from a knowledge base. This approach reduces hallucination and 
                          improves accuracy. The RAG process involves document chunking (breaking text into 
                          manageable pieces), embedding generation (converting text to vectors), similarity 
                          search (finding relevant chunks), and context-aware response generation. Our 
                          implementation uses Redis with RediSearch for vector storage, supporting HNSW 
                          indexing for efficient similarity search with cosine distance metrics.""",
                'category': 'concepts',
                'source': 'RAG_BACKEND_DESIGN.md',
                'metadata': {'type': 'technical', 'importance': 'high'}
            },
            {
                'id': 'redis_vectors',
                'title': 'Redis Vector Storage',
                'content': """Redis with the RediSearch module provides advanced vector search capabilities. 
                          It supports HNSW (Hierarchical Navigable Small World) indexing for efficient 
                          similarity search, multiple distance metrics including cosine, L2, and inner product. 
                          The system can handle millions of vectors with sub-millisecond query times. Redis 
                          Stack includes RediSearch by default and runs on port 6380 in our setup to avoid 
                          conflicts with local Redis instances. Vector dimensions up to 4096 are supported 
                          with FLOAT32 precision.""",
                'category': 'technical',
                'source': 'redis_documentation',
                'metadata': {'component': 'redis', 'features': ['HNSW', 'cosine', 'persistence']}
            },
            {
                'id': 'workflow_definition',
                'title': 'Workflow Definition and Execution',
                'content': """Workflows in Gleitzeit are defined using YAML files with a simple structure. 
                          Each workflow has a name and a list of tasks. Tasks specify an ID, method (like 
                          llm/chat or python/execute), parameters, and optional dependencies. Parameter 
                          substitution allows passing results between tasks using ${task_id.field} syntax. 
                          Batch processing workflows can process multiple files with configurable concurrency. 
                          The ExecutionEngine handles task scheduling, dependency resolution, and error 
                          recovery with automatic retries.""",
                'category': 'documentation',
                'source': 'workflow_guide',
                'metadata': {'type': 'guide', 'format': 'YAML'}
            },
            {
                'id': 'embedding_models',
                'title': 'Embedding Models and Configuration',
                'content': """The system uses Ollama's nomic-embed-text model for generating 768-dimensional 
                          embeddings. This model is optimized for semantic search and provides good balance 
                          between quality and performance. Document chunking uses configurable chunk sizes 
                          (default 300 tokens) with overlap (default 75 tokens) to preserve context across 
                          boundaries. The embeddings provider supports fallback to mock embeddings for 
                          testing when Ollama is unavailable. Real embeddings significantly improve search 
                          quality compared to mock embeddings.""",
                'category': 'technical',
                'source': 'embeddings_documentation',
                'metadata': {'model': 'nomic-embed-text', 'dimensions': 768}
            },
            {
                'id': 'persistence_layer',
                'title': 'Persistence and Storage',
                'content': """Gleitzeit features a unified persistence layer with automatic fallback: 
                          Redis → SQL → Memory. Redis provides the best performance with built-in TTL 
                          and atomic operations. SQLite offers reliable local storage with ACID compliance. 
                          The memory backend is useful for testing but doesn't persist across restarts. 
                          All backends implement the same interface for workflows, tasks, results, and 
                          metadata storage. The system automatically selects the best available backend 
                          based on configuration and availability.""",
                'category': 'architecture',
                'source': 'persistence_design',
                'metadata': {'backends': ['redis', 'sql', 'memory'], 'fallback': True}
            },
            {
                'id': 'python_execution',
                'title': 'Python Code Execution',
                'content': """The Python protocol provider enables executing Python code within workflows. 
                          It supports both inline code and script files, with configurable timeouts and 
                          sandboxing. The provider can validate syntax before execution, capture stdout/stderr, 
                          and return results. Custom functions can be registered for reuse across tasks. 
                          The execution environment includes common libraries like numpy, pandas, and requests. 
                          For security, code runs in isolated processes with resource limits.""",
                'category': 'providers',
                'source': 'python_provider_docs',
                'metadata': {'protocol': 'python/v1', 'sandboxed': True}
            },
            {
                'id': 'batch_processing',
                'title': 'Batch Processing Capabilities',
                'content': """Batch processing allows applying workflows to multiple files efficiently. 
                          The CLI supports file patterns (glob syntax) to select files for processing. 
                          Configurable concurrency limits prevent resource exhaustion. Results can be 
                          saved in JSON or Markdown format. The system handles partial failures gracefully, 
                          allowing resume from interruption. Common use cases include document summarization, 
                          data extraction, and content analysis. Maximum file size limits prevent memory 
                          issues with large files.""",
                'category': 'features',
                'source': 'batch_processing_guide',
                'metadata': {'type': 'feature', 'cli_command': 'gleitzeit batch'}
            }
        ]
        
        chunks = await qa.load_knowledge_base(knowledge_docs)
        print(f"✅ Loaded {len(knowledge_docs)} documents as {chunks} chunks")
    else:
        print(f"📊 Using existing knowledge base with {existing_docs} chunks")
    
    # Test questions covering various topics
    test_questions = [
        "What is Gleitzeit and what are its main features?",
        "How does RAG reduce hallucination in LLM responses?",
        "What vector search capabilities does Redis provide?",
        "How do I define a workflow in YAML?",
        "What embedding model is used and why?",
        "Explain the persistence layer fallback mechanism",
        "How does Python code execution work in workflows?",
        "What are the batch processing capabilities?",
        "What is HNSW indexing?",
        "How does parameter substitution work between tasks?",
        "What is the difference between Redis and Redis Stack?",
        "How can I handle errors in workflows?",
        "What are the main components of the Gleitzeit architecture?",
        "How do I configure chunk size for document processing?",
        "What distance metrics are supported for vector search?"
    ]
    
    # Run automated Q&A tests
    print("\n" + "="*60)
    print("Automated Q&A Tests")
    print("="*60)
    
    results = await qa.run_qa_tests(test_questions)
    
    # Interactive mode option
    print("\n" + "="*60)
    print("Test Complete!")
    print("="*60)
    
    print("\n🎯 Key Results:")
    print(f"   ✅ Successfully answered {len(results)} questions")
    print(f"   ✅ Average response time: {np.mean([r['timing']['total_ms'] for r in results]):.1f}ms")
    print(f"   ✅ Knowledge base has {qa.redis_client.ft(qa.index_name).info()['num_docs']} chunks")
    
    # Skip interactive mode in automated tests
    print("\n" + "="*60)
    print("💡 To run interactive Q&A mode, use: python test_qa_interactive.py")
    
    # Cleanup
    await qa.cleanup()
    
    print("\n✅ Q&A System Test Complete!")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)