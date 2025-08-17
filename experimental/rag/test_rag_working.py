#!/usr/bin/env python3
"""Working RAG test with Redis Stack on port 6380."""

import asyncio
import sys
import time
import numpy as np
from pathlib import Path
from typing import List, Dict, Any

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

import redis
from redis.commands.search.field import VectorField, TextField, TagField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from embeddings_provider import EmbeddingsProvider


class SimpleRAG:
    """Simple RAG implementation using Redis Stack."""
    
    def __init__(self, redis_port: int = 6380):
        """Initialize RAG with Redis Stack on specified port."""
        self.redis_port = redis_port
        self.redis_client = None
        self.embeddings_provider = None
        self.index_name = "rag_docs"
        self.embedding_dim = 768
        
    async def initialize(self) -> bool:
        """Initialize Redis and embeddings provider."""
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
                'chunk_size': 200,
                'chunk_overlap': 50
            })
            await self.embeddings_provider.initialize()
            
            # Check if Ollama is available
            self.use_real_embeddings = await self.embeddings_provider.health_check()
            if self.use_real_embeddings:
                print("✅ Ollama available - using real embeddings")
            else:
                print("⚠️  Ollama not available - using mock embeddings")
            
            # Create vector index
            await self.create_index()
            
            return True
            
        except Exception as e:
            print(f"❌ Initialization failed: {e}")
            return False
    
    async def create_index(self):
        """Create vector search index."""
        try:
            # Check if index exists (don't drop for persistence test)
            try:
                info = self.redis_client.ft(self.index_name).info()
                print(f"   Using existing index '{self.index_name}' with {info['num_docs']} docs")
                return  # Index already exists, don't recreate
            except:
                pass  # Index doesn't exist, create it
            
            # Create new index
            schema = [
                TextField("text", weight=1.0),
                TextField("chunk_id"),
                TagField("doc_id"),
                TagField("category"),
                VectorField(
                    "embedding",
                    "HNSW",  # Use HNSW for better performance
                    {
                        "TYPE": "FLOAT32",
                        "DIM": self.embedding_dim,
                        "DISTANCE_METRIC": "COSINE",
                        "INITIAL_CAP": 1000,
                        "M": 16,
                        "EF_CONSTRUCTION": 200,
                        "EF_RUNTIME": 10
                    }
                )
            ]
            
            self.redis_client.ft(self.index_name).create_index(
                fields=schema,
                definition=IndexDefinition(
                    prefix=["rag:"],
                    index_type=IndexType.HASH
                )
            )
            
            print(f"✅ Created vector index '{self.index_name}'")
            
        except Exception as e:
            print(f"❌ Failed to create index: {e}")
            raise
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text."""
        if self.use_real_embeddings:
            try:
                return await self.embeddings_provider.generate_embedding(text)
            except:
                # Fallback to mock
                pass
        
        # Mock embedding based on text hash for consistency
        np.random.seed(hash(text) % 2**32)
        return np.random.randn(self.embedding_dim).tolist()
    
    async def ingest_documents(self, documents: List[Dict[str, Any]]) -> int:
        """Ingest documents into the RAG system."""
        print(f"\n📚 Ingesting {len(documents)} documents...")
        
        total_chunks = 0
        
        for doc in documents:
            doc_id = doc['id']
            text = doc['text']
            category = doc.get('category', 'general')
            
            # Chunk the document
            chunks = self.embeddings_provider.chunk_text(text)
            print(f"   Document '{doc_id}': {len(chunks)} chunks")
            
            # Store each chunk with embedding
            for i, chunk in enumerate(chunks):
                chunk_id = f"{doc_id}_chunk_{i}"
                
                # Generate embedding
                embedding = await self.generate_embedding(chunk)
                embedding_bytes = np.array(embedding, dtype=np.float32).tobytes()
                
                # Store in Redis
                key = f"rag:{chunk_id}"
                self.redis_client.hset(
                    key,
                    mapping={
                        "text": chunk,
                        "chunk_id": chunk_id,
                        "doc_id": doc_id,
                        "category": category,
                        "embedding": embedding_bytes
                    }
                )
                
                total_chunks += 1
        
        print(f"✅ Ingested {total_chunks} chunks total")
        return total_chunks
    
    async def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant documents."""
        print(f"\n🔍 Searching for: '{query}'")
        
        # Generate query embedding
        query_embedding = await self.generate_embedding(query)
        query_bytes = np.array(query_embedding, dtype=np.float32).tobytes()
        
        # Perform vector search
        q = Query(
            "*=>[KNN $k @embedding $vec AS score]"
        ).return_fields(
            "text", "chunk_id", "doc_id", "category", "score"
        ).sort_by("score").dialect(2)
        
        results = self.redis_client.ft(self.index_name).search(
            q,
            query_params={
                "k": top_k,
                "vec": query_bytes
            }
        )
        
        # Format results
        formatted_results = []
        for doc in results.docs:
            formatted_results.append({
                'text': doc.text,
                'chunk_id': doc.chunk_id,
                'doc_id': doc.doc_id,
                'category': doc.category,
                'score': float(doc.score)
            })
        
        print(f"   Found {len(formatted_results)} relevant chunks")
        return formatted_results
    
    async def test_persistence(self):
        """Test that data persists."""
        print("\n" + "="*60)
        print("Testing Persistence")
        print("="*60)
        
        # Check if index already has data
        try:
            info = self.redis_client.ft(self.index_name).info()
            existing_docs = info['num_docs']
            print(f"📊 Existing documents in index: {existing_docs}")
            
            if existing_docs > 0:
                # Test search on existing data
                results = await self.search("workflow orchestration", top_k=3)
                if results:
                    print("✅ Found existing documents - persistence verified!")
                    for r in results[:2]:
                        print(f"   - {r['doc_id']}: {r['text'][:100]}...")
                    return True
        except:
            pass
        
        return False
    
    async def cleanup(self):
        """Clean up resources."""
        if self.embeddings_provider:
            await self.embeddings_provider.shutdown()
        if self.redis_client:
            self.redis_client.close()


async def main():
    """Run RAG tests."""
    print("="*60)
    print("RAG System Test with Redis Stack")
    print("="*60)
    
    # Initialize RAG
    rag = SimpleRAG(redis_port=6380)  # Using Redis Stack on port 6380
    
    if not await rag.initialize():
        print("❌ Failed to initialize RAG system")
        return 1
    
    # Check for existing data
    has_existing = await rag.test_persistence()
    
    if not has_existing:
        # Ingest test documents
        print("\n📝 No existing data - ingesting new documents...")
        
        documents = [
            {
                'id': 'gleitzeit_intro',
                'text': """Gleitzeit is a powerful workflow orchestration system designed 
                          specifically for LLM applications. It provides protocol-based 
                          task execution with automatic persistence and fallback mechanisms.
                          The system supports YAML workflows, batch processing, and 
                          parameter substitution between tasks.""",
                'category': 'documentation'
            },
            {
                'id': 'rag_overview',
                'text': """RAG (Retrieval-Augmented Generation) enhances LLM responses by 
                          retrieving relevant context from a knowledge base. This approach 
                          reduces hallucination and improves accuracy. The process involves 
                          document chunking, embedding generation, similarity search, and 
                          context-aware response generation.""",
                'category': 'concepts'
            },
            {
                'id': 'redis_vectors',
                'text': """Redis with RediSearch module provides vector search capabilities 
                          including HNSW indexing for efficient similarity search. It supports 
                          cosine, L2, and inner product distance metrics. The system can 
                          handle millions of vectors with sub-millisecond query times.""",
                'category': 'technical'
            }
        ]
        
        chunks = await rag.ingest_documents(documents)
        print(f"✅ Ingested {len(documents)} documents as {chunks} chunks")
    
    # Test searches
    print("\n" + "="*60)
    print("Testing Search Functionality")
    print("="*60)
    
    queries = [
        "What is Gleitzeit?",
        "How does RAG work?",
        "vector search Redis",
        "workflow orchestration for LLMs"
    ]
    
    for query in queries:
        results = await rag.search(query, top_k=3)
        
        if results:
            print(f"\n✅ Query: '{query}'")
            print(f"   Top result ({results[0]['score']:.3f}): {results[0]['text'][:100]}...")
            print(f"   From: {results[0]['doc_id']} / {results[0]['chunk_id']}")
        else:
            print(f"\n❌ No results for: '{query}'")
    
    # Test persistence by getting index stats
    print("\n" + "="*60)
    print("Final Statistics")
    print("="*60)
    
    info = rag.redis_client.ft(rag.index_name).info()
    print(f"📊 Index Statistics:")
    print(f"   Total documents: {info['num_docs']}")
    print(f"   Index size: {float(info.get('inverted_sz_mb', 0)):.2f} MB")
    print(f"   Vector index size: {float(info.get('vector_index_sz_mb', 0)):.2f} MB")
    
    # Cleanup
    await rag.cleanup()
    
    print("\n" + "="*60)
    print("✅ RAG System Test Complete!")
    print("="*60)
    print("\nData persists in Redis Stack - run again to test retrieval!")
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)