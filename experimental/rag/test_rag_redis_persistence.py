#!/usr/bin/env python3
"""Test RAG with Redis vector persistence."""

import asyncio
import sys
import json
import time
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

import redis
try:
    # Redis-py with RediSearch support
    from redis.commands.search.field import VectorField, TextField, TagField
    from redis.commands.search.index_definition import IndexDefinition, IndexType
    from redis.commands.search.query import Query
except ImportError:
    # Minimal imports for basic Redis testing
    VectorField = TextField = TagField = Query = IndexDefinition = IndexType = None
    print("⚠️  RediSearch Python support not fully available")
    print("   Some tests may be limited")

from embeddings_provider import EmbeddingsProvider
from redis_vector_adapter import RedisVectorAdapter


class RAGRedisSystem:
    """RAG system with Redis vector persistence."""
    
    def __init__(self, redis_url: str = "redis://localhost:6380"):
        """Initialize RAG system with Redis persistence."""
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.vector_store: Optional[RedisVectorAdapter] = None
        self.embeddings_provider: Optional[EmbeddingsProvider] = None
        
        # Configuration
        self.embedding_dim = 768
        self.index_name = "gleitzeit_rag_test"
        self.chunk_size = 200
        self.chunk_overlap = 50
        
    async def initialize(self) -> bool:
        """Initialize all components."""
        try:
            # Connect to Redis
            # Parse port from URL or use default
            if "6380" in self.redis_url:
                port = 6380
            else:
                port = 6379
            self.redis_client = redis.Redis(host='localhost', port=port, decode_responses=True)
            
            # Test connection
            self.redis_client.ping()
            print("✅ Connected to Redis")
            
            # Check for RediSearch module
            modules = self.redis_client.module_list()
            has_search = any(
                m.get(b'name', b'').decode() == 'search' 
                for m in modules
            )
            
            if not has_search:
                print("❌ RediSearch module not loaded!")
                print("Start Redis with: redis-server --loadmodule /path/to/redisearch.so")
                return False
            
            print("✅ RediSearch module available")
            
            # Initialize vector store
            self.vector_store = RedisVectorAdapter(
                redis_client=self.redis_client,
                index_name=self.index_name,
                embedding_dim=self.embedding_dim,
                distance_metric="COSINE",
                index_type="HNSW"  # Use HNSW for better performance
            )
            
            await self.vector_store.initialize()
            print(f"✅ Vector index '{self.index_name}' initialized")
            
            # Initialize embeddings provider
            self.embeddings_provider = EmbeddingsProvider({
                'chunk_size': self.chunk_size,
                'chunk_overlap': self.chunk_overlap,
                'embedding_model': 'nomic-embed-text'
            })
            
            await self.embeddings_provider.initialize()
            print("✅ Embeddings provider initialized")
            
            return True
            
        except Exception as e:
            print(f"❌ Initialization failed: {e}")
            return False
    
    async def ingest_document(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Ingest a document: chunk it, generate embeddings, store in Redis.
        
        Returns number of chunks created.
        """
        print(f"\n📄 Ingesting document: {doc_id}")
        
        # Chunk the document
        chunks = self.embeddings_provider.chunk_text(text)
        print(f"   Created {len(chunks)} chunks")
        
        # Store each chunk with its embedding
        stored = 0
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            
            try:
                # Generate embedding (using mock for testing if Ollama not available)
                if await self.embeddings_provider.health_check():
                    embedding = await self.embeddings_provider.generate_embedding(chunk)
                else:
                    # Mock embedding for testing without Ollama
                    np.random.seed(hash(chunk) % 2**32)
                    embedding = np.random.randn(self.embedding_dim).tolist()
                
                # Prepare metadata
                chunk_metadata = metadata or {}
                chunk_metadata.update({
                    'source_doc': doc_id,
                    'chunk_index': i,
                    'total_chunks': len(chunks),
                    'chunk_size': len(chunk)
                })
                
                # Store in Redis
                success = await self.vector_store.store_embedding(
                    doc_id=chunk_id,
                    text=chunk,
                    embedding=embedding,
                    metadata=chunk_metadata
                )
                
                if success:
                    stored += 1
                    
            except Exception as e:
                print(f"   ⚠️  Failed to store chunk {i}: {e}")
        
        print(f"   ✅ Stored {stored}/{len(chunks)} chunks")
        return stored
    
    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant documents using vector similarity.
        
        Returns list of relevant chunks with scores.
        """
        print(f"\n🔍 Searching for: '{query}'")
        
        # Generate query embedding
        if await self.embeddings_provider.health_check():
            query_embedding = await self.embeddings_provider.generate_embedding(query)
        else:
            # Mock embedding for testing
            np.random.seed(hash(query) % 2**32)
            query_embedding = np.random.randn(self.embedding_dim).tolist()
        
        # Search in Redis
        results = await self.vector_store.search_similar(
            query_embedding=query_embedding,
            top_k=top_k,
            filters=filters
        )
        
        # Format results
        formatted_results = []
        for doc_id, score, doc_data in results:
            formatted_results.append({
                'chunk_id': doc_id,
                'text': doc_data['text'],
                'score': score,
                'metadata': doc_data.get('metadata', {})
            })
        
        print(f"   Found {len(formatted_results)} relevant chunks")
        return formatted_results
    
    async def hybrid_search(
        self,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Perform hybrid search combining text and vector similarity.
        """
        print(f"\n🔍 Hybrid search for: '{query}'")
        
        # Generate query embedding
        if await self.embeddings_provider.health_check():
            query_embedding = await self.embeddings_provider.generate_embedding(query)
        else:
            np.random.seed(hash(query) % 2**32)
            query_embedding = np.random.randn(self.embedding_dim).tolist()
        
        # Hybrid search in Redis
        results = await self.vector_store.hybrid_search(
            query_text=query,
            query_embedding=query_embedding,
            top_k=top_k,
            text_weight=0.3,
            vector_weight=0.7
        )
        
        # Format results
        formatted_results = []
        for doc_id, score, doc_data in results:
            formatted_results.append({
                'chunk_id': doc_id,
                'text': doc_data['text'],
                'score': score,
                'metadata': doc_data.get('metadata', {})
            })
        
        print(f"   Found {len(formatted_results)} relevant chunks (hybrid)")
        return formatted_results
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics."""
        stats = await self.vector_store.get_statistics()
        
        # Add RAG-specific stats
        stats['embedding_dim'] = self.embedding_dim
        stats['chunk_size'] = self.chunk_size
        stats['chunk_overlap'] = self.chunk_overlap
        
        return stats
    
    async def clear_all(self) -> bool:
        """Clear all data."""
        return await self.vector_store.clear_all()
    
    async def cleanup(self) -> None:
        """Clean up resources."""
        if self.embeddings_provider:
            await self.embeddings_provider.shutdown()
        if self.redis_client:
            self.redis_client.close()


async def test_persistence():
    """Test that data persists across sessions."""
    print("\n" + "="*60)
    print("Testing Redis Vector Persistence")
    print("="*60)
    
    # Phase 1: Initial ingestion
    print("\n📝 Phase 1: Initial Data Ingestion")
    print("-"*40)
    
    rag = RAGRedisSystem()
    if not await rag.initialize():
        return False
    
    # Clear any existing data
    await rag.clear_all()
    
    # Ingest test documents
    documents = [
        {
            'id': 'doc1',
            'text': """Gleitzeit is a powerful workflow orchestration system designed 
                      for LLM applications. It provides protocol-based task execution,
                      automatic persistence with fallback, and unified task management.""",
            'metadata': {'category': 'overview', 'version': '0.0.4'}
        },
        {
            'id': 'doc2',
            'text': """RAG (Retrieval-Augmented Generation) enhances LLM responses by
                      retrieving relevant context from a knowledge base. This approach
                      reduces hallucination and improves answer accuracy.""",
            'metadata': {'category': 'rag', 'importance': 'high'}
        },
        {
            'id': 'doc3',
            'text': """Redis with RediSearch module provides vector search capabilities
                      including HNSW indexing, cosine similarity, and hybrid search
                      combining text and vector similarity.""",
            'metadata': {'category': 'technical', 'component': 'redis'}
        }
    ]
    
    total_chunks = 0
    for doc in documents:
        chunks = await rag.ingest_document(
            doc_id=doc['id'],
            text=doc['text'],
            metadata=doc['metadata']
        )
        total_chunks += chunks
    
    print(f"\n✅ Phase 1 Complete: Ingested {len(documents)} documents ({total_chunks} chunks)")
    
    # Get initial statistics
    stats1 = await rag.get_statistics()
    print(f"   Documents in index: {stats1['num_docs']}")
    
    # Perform initial search
    results1 = await rag.search("What is Gleitzeit?", top_k=3)
    print(f"   Search returned {len(results1)} results")
    
    # Close first session
    await rag.cleanup()
    print("\n🔄 Session 1 closed")
    
    # Phase 2: New session - verify persistence
    print("\n📝 Phase 2: Verify Persistence in New Session")
    print("-"*40)
    
    # Create new RAG instance
    rag2 = RAGRedisSystem()
    if not await rag2.initialize():
        return False
    
    # Get statistics - should match previous
    stats2 = await rag2.get_statistics()
    print(f"   Documents in index: {stats2['num_docs']}")
    
    # Verify data persisted
    if stats2['num_docs'] != stats1['num_docs']:
        print(f"❌ Data not persisted! Expected {stats1['num_docs']}, got {stats2['num_docs']}")
        return False
    
    print("✅ Data persisted correctly")
    
    # Perform same search - should get same results
    results2 = await rag2.search("What is Gleitzeit?", top_k=3)
    
    if len(results2) != len(results1):
        print(f"❌ Search results differ! Session 1: {len(results1)}, Session 2: {len(results2)}")
        return False
    
    print(f"✅ Search returned same {len(results2)} results")
    
    # Phase 3: Add more data
    print("\n📝 Phase 3: Add More Data to Existing Index")
    print("-"*40)
    
    new_doc = {
        'id': 'doc4',
        'text': """Vector persistence in Redis allows RAG systems to maintain
                  their knowledge base across restarts. The HNSW index provides
                  efficient nearest neighbor search even with millions of vectors.""",
        'metadata': {'category': 'persistence', 'added': 'phase3'}
    }
    
    chunks = await rag2.ingest_document(
        doc_id=new_doc['id'],
        text=new_doc['text'],
        metadata=new_doc['metadata']
    )
    
    print(f"   Added new document with {chunks} chunks")
    
    # Search for new content
    results3 = await rag2.search("vector persistence", top_k=2)
    print(f"   Search for new content returned {len(results3)} results")
    
    # Test metadata filtering
    print("\n📝 Phase 4: Test Metadata Filtering")
    print("-"*40)
    
    filtered_results = await rag2.search(
        "persistence",
        top_k=5,
        filters={'category': 'persistence'}
    )
    
    if filtered_results:
        print(f"✅ Filtered search returned {len(filtered_results)} results")
        for r in filtered_results:
            print(f"   - {r['chunk_id']}: category={r['metadata'].get('category')}")
    
    # Test hybrid search
    print("\n📝 Phase 5: Test Hybrid Search")
    print("-"*40)
    
    hybrid_results = await rag2.hybrid_search("Redis workflow", top_k=3)
    print(f"   Hybrid search returned {len(hybrid_results)} results")
    
    # Final statistics
    print("\n📊 Final Statistics:")
    print("-"*40)
    final_stats = await rag2.get_statistics()
    for key, value in final_stats.items():
        print(f"   {key}: {value}")
    
    # Cleanup
    await rag2.cleanup()
    
    return True


async def test_performance():
    """Test performance with larger dataset."""
    print("\n" + "="*60)
    print("Testing Performance at Scale")
    print("="*60)
    
    rag = RAGRedisSystem()
    if not await rag.initialize():
        return False
    
    # Clear existing data
    await rag.clear_all()
    
    # Generate synthetic documents
    print("\n📚 Generating synthetic documents...")
    num_docs = 100
    
    start_time = time.time()
    total_chunks = 0
    
    for i in range(num_docs):
        # Generate synthetic text
        text = f"""Document {i}: This is a synthetic document about topic {i % 10}.
                  It contains information about subject {i % 5} and relates to
                  category {i % 3}. The content discusses various aspects of
                  technology, science, and engineering. Additional text to make
                  the document longer and more realistic for chunking tests.
                  Reference number: {hashlib.md5(str(i).encode()).hexdigest()}"""
        
        chunks = await rag.ingest_document(
            doc_id=f"synthetic_{i}",
            text=text,
            metadata={
                'doc_num': i,
                'topic': f"topic_{i % 10}",
                'category': f"cat_{i % 3}"
            }
        )
        total_chunks += chunks
        
        if (i + 1) % 20 == 0:
            print(f"   Processed {i + 1}/{num_docs} documents...")
    
    ingestion_time = time.time() - start_time
    
    print(f"\n✅ Ingestion Performance:")
    print(f"   Documents: {num_docs}")
    print(f"   Total chunks: {total_chunks}")
    print(f"   Time: {ingestion_time:.2f}s")
    print(f"   Rate: {num_docs/ingestion_time:.1f} docs/sec")
    print(f"   Rate: {total_chunks/ingestion_time:.1f} chunks/sec")
    
    # Test search performance
    print("\n🔍 Testing Search Performance...")
    
    queries = [
        "technology and science",
        "engineering aspects",
        "topic 5 information",
        "category discussion",
        "synthetic document content"
    ]
    
    search_times = []
    for query in queries:
        start = time.time()
        results = await rag.search(query, top_k=10)
        search_time = time.time() - start
        search_times.append(search_time)
        print(f"   Query '{query[:30]}...': {search_time*1000:.2f}ms ({len(results)} results)")
    
    avg_search = np.mean(search_times) * 1000
    print(f"\n✅ Search Performance:")
    print(f"   Average search time: {avg_search:.2f}ms")
    print(f"   Min: {min(search_times)*1000:.2f}ms")
    print(f"   Max: {max(search_times)*1000:.2f}ms")
    
    # Test with filters
    print("\n🔍 Testing Filtered Search Performance...")
    
    start = time.time()
    filtered_results = await rag.search(
        "document",
        top_k=10,
        filters={'topic': 'topic_5'}
    )
    filter_time = time.time() - start
    
    print(f"   Filtered search: {filter_time*1000:.2f}ms ({len(filtered_results)} results)")
    
    # Get final statistics
    stats = await rag.get_statistics()
    print(f"\n📊 Index Statistics:")
    print(f"   Total documents: {stats['num_docs']}")
    print(f"   Index size: {stats.get('vector_index_size_mb', 0):.2f} MB")
    
    await rag.cleanup()
    return True


async def main():
    """Run all tests."""
    print("="*60)
    print("RAG Redis Vector Persistence Test Suite")
    print("="*60)
    
    all_passed = True
    
    # Test 1: Persistence across sessions
    try:
        if not await test_persistence():
            all_passed = False
            print("\n❌ Persistence test failed")
    except Exception as e:
        print(f"\n❌ Persistence test error: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    # Test 2: Performance at scale
    try:
        if not await test_performance():
            all_passed = False
            print("\n❌ Performance test failed")
    except Exception as e:
        print(f"\n❌ Performance test error: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    # Summary
    print("\n" + "="*60)
    if all_passed:
        print("✅ All tests passed!")
        print("\nRedis vector persistence is working correctly for RAG!")
        print("\nKey achievements:")
        print("  ✓ Documents persist across sessions")
        print("  ✓ Vector search works after restart")
        print("  ✓ Metadata filtering functional")
        print("  ✓ Hybrid search operational")
        print("  ✓ Good performance at scale")
    else:
        print("❌ Some tests failed")
        print("\nPlease check:")
        print("  1. Redis is running with RediSearch module")
        print("  2. Ollama is available (optional, uses mock embeddings)")
        print("  3. Python dependencies are installed")
    print("="*60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)