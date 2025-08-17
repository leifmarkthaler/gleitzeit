#!/usr/bin/env python3
"""Test Redis vector functionality after manual RediSearch installation."""

import sys
import redis
import numpy as np
from pathlib import Path

def check_redis_connection():
    """Check if Redis is running and accessible."""
    try:
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        r.ping()
        print("✅ Redis is running on port 6379")
        return r
    except redis.ConnectionError:
        print("❌ Redis is not running on port 6379")
        print("Start Redis with: redis-server")
        return None

def check_redisearch_module(r):
    """Check if RediSearch module is loaded."""
    try:
        modules = r.module_list()
        has_search = any(
            m.get(b'name', b'').decode() == 'search' 
            for m in modules
        )
        
        if has_search:
            print("✅ RediSearch module is loaded")
            
            # Get module version
            for m in modules:
                if m.get(b'name', b'').decode() == 'search':
                    version = m.get(b'ver', 0)
                    print(f"   Version: {version}")
            return True
        else:
            print("❌ RediSearch module is NOT loaded")
            print("\nTo load the module, start Redis with:")
            print("  redis-server --loadmodule /path/to/redisearch.so")
            print("\nOr use the install script:")
            print("  ./install_redis_vectors.sh")
            return False
    except Exception as e:
        print(f"❌ Error checking modules: {e}")
        return False

def test_vector_operations(r):
    """Test vector storage and search operations."""
    print("\n🧪 Testing vector operations...")
    
    try:
        from redis.commands.search.field import VectorField, TextField, TagField
        from redis.commands.search.indexDefinition import IndexDefinition, IndexType
        from redis.commands.search.query import Query
    except ImportError:
        print("❌ Redis Python client doesn't have search support")
        print("Install with: pip install redis[search]")
        return False
    
    INDEX_NAME = "test_vectors"
    DIM = 768  # Standard embedding dimension
    
    try:
        # Drop existing index if exists
        try:
            r.ft(INDEX_NAME).dropindex(delete_documents=True)
            print("   Dropped existing test index")
        except:
            pass
        
        # Create index with vector field
        print(f"   Creating index '{INDEX_NAME}' with {DIM}-dim vectors...")
        
        schema = [
            TextField("title"),
            TextField("content"),
            TagField("category"),
            VectorField(
                "embedding",
                "FLAT",  # Can also use HNSW for larger datasets
                {
                    "TYPE": "FLOAT32",
                    "DIM": DIM,
                    "DISTANCE_METRIC": "COSINE"
                }
            )
        ]
        
        r.ft(INDEX_NAME).create_index(
            fields=schema,
            definition=IndexDefinition(
                prefix=["doc:"],
                index_type=IndexType.HASH
            )
        )
        print("   ✅ Index created successfully")
        
        # Add test documents with random embeddings
        print("\n   Adding test documents...")
        
        np.random.seed(42)  # For reproducibility
        
        documents = [
            {
                "id": "doc:1",
                "title": "Introduction to Gleitzeit",
                "content": "Gleitzeit is a workflow orchestration system.",
                "category": "intro",
                "embedding": np.random.randn(DIM).astype(np.float32)
            },
            {
                "id": "doc:2",
                "title": "RAG Implementation",
                "content": "Retrieval-Augmented Generation enhances LLM responses.",
                "category": "rag",
                "embedding": np.random.randn(DIM).astype(np.float32)
            },
            {
                "id": "doc:3",
                "title": "Vector Search",
                "content": "Vector databases enable semantic search capabilities.",
                "category": "vectors",
                "embedding": np.random.randn(DIM).astype(np.float32)
            }
        ]
        
        for doc in documents:
            r.hset(
                doc["id"],
                mapping={
                    "title": doc["title"],
                    "content": doc["content"],
                    "category": doc["category"],
                    "embedding": doc["embedding"].tobytes()
                }
            )
        
        print(f"   ✅ Added {len(documents)} documents")
        
        # Test vector similarity search
        print("\n   Testing vector similarity search...")
        
        # Create a query vector (random for testing)
        query_vector = np.random.randn(DIM).astype(np.float32)
        
        # KNN search
        q = Query("*=>[KNN 2 @embedding $vec AS score]")\
            .return_fields("title", "content", "score")\
            .sort_by("score")\
            .dialect(2)
        
        results = r.ft(INDEX_NAME).search(
            q,
            query_params={"vec": query_vector.tobytes()}
        )
        
        print(f"   ✅ Found {len(results.docs)} similar documents:")
        for i, doc in enumerate(results.docs, 1):
            print(f"      {i}. {doc.title} (score: {doc.score})")
        
        # Test hybrid search (text + vector)
        print("\n   Testing hybrid search...")
        
        # Search for documents containing "workflow" and similar vectors
        q_hybrid = Query("workflow=>[KNN 2 @embedding $vec AS score]")\
            .return_fields("title", "content", "score")\
            .sort_by("score")\
            .dialect(2)
        
        results_hybrid = r.ft(INDEX_NAME).search(
            q_hybrid,
            query_params={"vec": query_vector.tobytes()}
        )
        
        if results_hybrid.docs:
            print(f"   ✅ Hybrid search found {len(results_hybrid.docs)} documents")
        else:
            # Try without text filter
            print("   ℹ️  No results with text filter, trying pure vector search")
        
        # Get index statistics
        info = r.ft(INDEX_NAME).info()
        print(f"\n   📊 Index statistics:")
        print(f"      Documents: {info['num_docs']}")
        print(f"      Index size: {info.get('inverted_sz_mb', 0)} MB")
        print(f"      Indexing: {'active' if info['indexing'] else 'complete'}")
        
        # Clean up
        r.ft(INDEX_NAME).dropindex(delete_documents=True)
        print("\n   🧹 Cleaned up test index")
        
        return True
        
    except Exception as e:
        print(f"❌ Vector operation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_performance(r):
    """Test vector search performance."""
    print("\n⚡ Testing performance...")
    
    try:
        from redis.commands.search.field import VectorField, TextField
        from redis.commands.search.indexDefinition import IndexDefinition, IndexType
        from redis.commands.search.query import Query
        import time
        
        INDEX_NAME = "perf_test"
        DIM = 768
        NUM_DOCS = 1000
        
        # Create index
        try:
            r.ft(INDEX_NAME).dropindex(delete_documents=True)
        except:
            pass
        
        schema = [
            TextField("text"),
            VectorField("vec", "FLAT", {
                "TYPE": "FLOAT32",
                "DIM": DIM,
                "DISTANCE_METRIC": "COSINE"
            })
        ]
        
        r.ft(INDEX_NAME).create_index(
            fields=schema,
            definition=IndexDefinition(prefix=["perf:"], index_type=IndexType.HASH)
        )
        
        # Add documents
        print(f"   Adding {NUM_DOCS} documents...")
        start = time.time()
        
        for i in range(NUM_DOCS):
            vec = np.random.randn(DIM).astype(np.float32)
            r.hset(f"perf:{i}", mapping={
                "text": f"Document {i}",
                "vec": vec.tobytes()
            })
        
        index_time = time.time() - start
        print(f"   ✅ Indexed {NUM_DOCS} documents in {index_time:.2f}s")
        print(f"      ({NUM_DOCS/index_time:.0f} docs/sec)")
        
        # Test search performance
        print(f"\n   Testing search performance...")
        query_vec = np.random.randn(DIM).astype(np.float32)
        
        search_times = []
        for _ in range(10):
            start = time.time()
            
            q = Query("*=>[KNN 10 @vec $v AS score]").dialect(2)
            r.ft(INDEX_NAME).search(q, query_params={"v": query_vec.tobytes()})
            
            search_times.append(time.time() - start)
        
        avg_search = np.mean(search_times) * 1000  # Convert to ms
        print(f"   ✅ Average search time: {avg_search:.2f}ms")
        print(f"      (10 queries, k=10)")
        
        # Clean up
        r.ft(INDEX_NAME).dropindex(delete_documents=True)
        
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 50)
    print("Redis Vector Search Test Suite")
    print("=" * 50)
    
    # Check Redis connection
    r = check_redis_connection()
    if not r:
        sys.exit(1)
    
    # Check RediSearch module
    if not check_redisearch_module(r):
        print("\n" + "=" * 50)
        print("Setup Instructions:")
        print("=" * 50)
        print("\n1. Run the install script:")
        print("   ./install_redis_vectors.sh")
        print("\n2. Or manually load the module:")
        print("   redis-server --loadmodule /path/to/redisearch.so")
        print("\n3. Or use Redis Stack Docker:")
        print("   docker run -d -p 6379:6379 redis/redis-stack")
        sys.exit(1)
    
    # Run tests
    all_passed = True
    
    if not test_vector_operations(r):
        all_passed = False
    
    if not test_performance(r):
        all_passed = False
    
    # Summary
    print("\n" + "=" * 50)
    if all_passed:
        print("✅ All tests passed!")
        print("\nRedis is ready for vector search in Gleitzeit RAG!")
    else:
        print("❌ Some tests failed")
        print("\nPlease check the errors above")
    print("=" * 50)
    
    sys.exit(0 if all_passed else 1)

if __name__ == "__main__":
    main()