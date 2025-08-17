#!/usr/bin/env python3
"""Simple test to check if Redis vector operations actually work."""

import redis
import numpy as np
import json

def test_basic_redis():
    """Test basic Redis operations."""
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    # Test connection
    print("Testing Redis connection...")
    try:
        r.ping()
        print("✅ Redis is connected")
    except:
        print("❌ Redis connection failed")
        return False
    
    # Check modules
    print("\nChecking loaded modules...")
    modules = r.module_list()
    for mod in modules:
        name = mod.get(b'name', b'').decode() if isinstance(mod.get(b'name'), bytes) else mod.get('name', '')
        ver = mod.get(b'ver', 0)
        print(f"  - Module: {name} (version: {ver})")
    
    return True

def test_redisearch_vector():
    """Test RediSearch vector operations if available."""
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    print("\n" + "="*50)
    print("Testing RediSearch Vector Operations")
    print("="*50)
    
    try:
        # Try to import RediSearch commands
        from redis.commands.search.field import VectorField, TextField
        from redis.commands.search.index_definition import IndexDefinition, IndexType
        from redis.commands.search.query import Query
        
        print("✅ RediSearch Python imports successful")
        
        # Try to create a simple index
        INDEX = "test_idx"
        
        # Drop if exists
        try:
            r.ft(INDEX).dropindex()
            print(f"  Dropped existing index '{INDEX}'")
        except:
            pass
        
        # Create index with vector field
        schema = [
            TextField("text"),
            VectorField("vec", "FLAT", {
                "TYPE": "FLOAT32",
                "DIM": 10,
                "DISTANCE_METRIC": "COSINE"
            })
        ]
        
        r.ft(INDEX).create_index(
            fields=schema,
            definition=IndexDefinition(prefix=["doc:"], index_type=IndexType.HASH)
        )
        
        print(f"✅ Created vector index '{INDEX}'")
        
        # Add a document with vector
        vec = np.random.randn(10).astype(np.float32)
        r.hset("doc:1", mapping={
            "text": "Test document",
            "vec": vec.tobytes()
        })
        
        print("✅ Added document with vector")
        
        # Search
        query_vec = np.random.randn(10).astype(np.float32)
        q = Query("*=>[KNN 1 @vec $v AS score]").dialect(2)
        results = r.ft(INDEX).search(q, query_params={"v": query_vec.tobytes()})
        
        print(f"✅ Vector search returned {len(results.docs)} results")
        
        # Cleanup
        r.ft(INDEX).dropindex(delete_documents=True)
        print("✅ Cleaned up test index")
        
        return True
        
    except ImportError as e:
        print(f"⚠️  RediSearch Python imports not available: {e}")
        return False
    except Exception as e:
        print(f"❌ RediSearch vector test failed: {e}")
        print(f"   Error type: {type(e).__name__}")
        return False

def test_manual_vector_storage():
    """Test manual vector storage without RediSearch."""
    r = redis.Redis(host='localhost', port=6379)
    
    print("\n" + "="*50)
    print("Testing Manual Vector Storage")
    print("="*50)
    
    try:
        # Store vectors as JSON
        vec1 = np.random.randn(10).tolist()
        vec2 = np.random.randn(10).tolist()
        
        # Store documents with vectors
        doc1 = {
            "text": "First document",
            "vector": vec1
        }
        doc2 = {
            "text": "Second document", 
            "vector": vec2
        }
        
        r.set("manual:doc:1", json.dumps(doc1))
        r.set("manual:doc:2", json.dumps(doc2))
        print("✅ Stored 2 documents with vectors using JSON")
        
        # Retrieve and compute similarity manually
        retrieved = json.loads(r.get("manual:doc:1"))
        print(f"✅ Retrieved document: {retrieved['text']}")
        print(f"   Vector dimensions: {len(retrieved['vector'])}")
        
        # Compute cosine similarity
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        similarity = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
        print(f"✅ Computed cosine similarity: {similarity:.3f}")
        
        # Store vectors as byte arrays (more efficient)
        vec_bytes = np.array(vec1, dtype=np.float32).tobytes()
        r.set("manual:vec:1", vec_bytes)
        
        retrieved_bytes = r.get("manual:vec:1")
        vec_recovered = np.frombuffer(retrieved_bytes, dtype=np.float32)
        print(f"✅ Stored and retrieved vector as bytes")
        print(f"   Original shape: {len(vec1)}, Retrieved shape: {len(vec_recovered)}")
        
        # Clean up
        r.delete("manual:doc:1", "manual:doc:2", "manual:vec:1")
        print("✅ Cleaned up manual storage")
        
        return True
        
    except Exception as e:
        print(f"❌ Manual vector storage failed: {e}")
        return False

def test_redis_json():
    """Test RedisJSON if available."""
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    print("\n" + "="*50)
    print("Testing RedisJSON for Vector Storage")
    print("="*50)
    
    try:
        # Try to use RedisJSON commands
        vec = np.random.randn(10).tolist()
        doc = {
            "text": "Test document",
            "vector": vec,
            "metadata": {"category": "test"}
        }
        
        # Try JSON.SET
        r.execute_command('JSON.SET', 'json:doc:1', '$', json.dumps(doc))
        print("✅ Stored document with JSON.SET")
        
        # Try JSON.GET
        result = r.execute_command('JSON.GET', 'json:doc:1', '$')
        retrieved = json.loads(result)[0]
        print(f"✅ Retrieved with JSON.GET: {retrieved['text']}")
        print(f"   Vector length: {len(retrieved['vector'])}")
        
        # Clean up
        r.delete('json:doc:1')
        print("✅ RedisJSON operations work")
        
        return True
        
    except Exception as e:
        print(f"⚠️  RedisJSON not available: {e}")
        return False

def main():
    """Run all tests."""
    print("="*60)
    print("Redis Vector Capability Test")
    print("="*60)
    
    # Test basic Redis
    if not test_basic_redis():
        print("\n❌ Basic Redis test failed!")
        return
    
    # Test different vector storage methods
    results = []
    
    # Test RediSearch vectors
    rs_result = test_redisearch_vector()
    results.append(("RediSearch Vectors", rs_result))
    
    # Test manual storage (always works with basic Redis)
    manual_result = test_manual_vector_storage()
    results.append(("Manual Vector Storage", manual_result))
    
    # Test RedisJSON
    json_result = test_redis_json()
    results.append(("RedisJSON", json_result))
    
    # Summary
    print("\n" + "="*60)
    print("Summary")
    print("="*60)
    
    for method, success in results:
        status = "✅" if success else "❌"
        print(f"{status} {method}: {'Working' if success else 'Not Available'}")
    
    print("\n" + "="*60)
    
    if results[0][1]:  # RediSearch works
        print("✅ Vector search is FULLY FUNCTIONAL with RediSearch!")
        print("   You can use all advanced vector features.")
    elif results[1][1]:  # Manual storage works
        print("⚠️  Vector search partially functional")
        print("   RediSearch not available, but manual vector storage works.")
        print("   You can store vectors and compute similarities manually.")
        print("\nTo enable full vector search, install RediSearch:")
        print("  1. Use Redis Stack: docker run -d -p 6379:6379 redis/redis-stack")
        print("  2. Or build RediSearch: ./install_redis_vectors.sh")
    else:
        print("❌ No vector capabilities detected")

if __name__ == "__main__":
    main()