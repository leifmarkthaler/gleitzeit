#!/usr/bin/env python3
"""Test Redis vector functionality with configurable port."""

import sys
import argparse
import redis
import numpy as np
import json

def test_redis_vectors(port=6379):
    """Test Redis vector operations on specified port."""
    print(f"Testing Redis on port {port}...")
    
    try:
        r = redis.Redis(host='localhost', port=port, decode_responses=True)
        r.ping()
        print(f"✅ Connected to Redis on port {port}")
    except redis.ConnectionError:
        print(f"❌ Cannot connect to Redis on port {port}")
        return False
    
    # Check modules
    print("\nChecking modules...")
    modules = r.module_list()
    has_search = False
    
    for mod in modules:
        name = mod.get(b'name', b'').decode() if isinstance(mod.get(b'name'), bytes) else mod.get('name', '')
        if name == 'search':
            has_search = True
            print(f"✅ RediSearch module found")
            break
    
    if not has_search:
        print("❌ RediSearch module not loaded on this Redis instance")
        return False
    
    # Test vector operations
    try:
        from redis.commands.search.field import VectorField, TextField
        from redis.commands.search.index_definition import IndexDefinition, IndexType
        from redis.commands.search.query import Query
        
        INDEX = f"test_idx_port_{port}"
        
        # Drop if exists
        try:
            r.ft(INDEX).dropindex(delete_documents=True)
        except:
            pass
        
        # Create index
        print(f"\nCreating vector index '{INDEX}'...")
        schema = [
            TextField("text"),
            VectorField("vec", "FLAT", {
                "TYPE": "FLOAT32",
                "DIM": 768,  # Standard embedding dimension
                "DISTANCE_METRIC": "COSINE"
            })
        ]
        
        r.ft(INDEX).create_index(
            fields=schema,
            definition=IndexDefinition(
                prefix=[f"doc{port}:"],
                index_type=IndexType.HASH
            )
        )
        print("✅ Vector index created")
        
        # Add test documents
        print("\nAdding test documents...")
        for i in range(3):
            vec = np.random.randn(768).astype(np.float32)
            r.hset(f"doc{port}:{i}", mapping={
                "text": f"Test document {i} on port {port}",
                "vec": vec.tobytes()
            })
        print("✅ Added 3 documents with 768-dim vectors")
        
        # Test search
        print("\nTesting vector search...")
        query_vec = np.random.randn(768).astype(np.float32)
        q = Query("*=>[KNN 2 @vec $v AS score]").return_fields("text", "score").dialect(2)
        results = r.ft(INDEX).search(q, query_params={"v": query_vec.tobytes()})
        
        print(f"✅ Vector search returned {len(results.docs)} results:")
        for doc in results.docs:
            print(f"   - {doc.text} (score: {doc.score})")
        
        # Get index info
        info = r.ft(INDEX).info()
        print(f"\n📊 Index statistics:")
        print(f"   Documents: {info['num_docs']}")
        print(f"   Index size: {info.get('inverted_sz_mb', 0)} MB")
        
        # Cleanup
        r.ft(INDEX).dropindex(delete_documents=True)
        print("\n✅ Test completed successfully!")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Test Redis vector functionality')
    parser.add_argument('--port', type=int, default=6379,
                        help='Redis port (default: 6379, Redis Stack: 6380)')
    parser.add_argument('--test-both', action='store_true',
                        help='Test both local Redis (6379) and Redis Stack (6380)')
    
    args = parser.parse_args()
    
    print("="*60)
    print("Redis Vector Test")
    print("="*60)
    
    if args.test_both:
        print("\n🔍 Testing both Redis instances...")
        
        # Test local Redis
        print("\n" + "-"*40)
        print("Testing LOCAL Redis (port 6379)")
        print("-"*40)
        local_result = test_redis_vectors(6379)
        
        # Test Redis Stack
        print("\n" + "-"*40)
        print("Testing REDIS STACK (port 6380)")
        print("-"*40)
        stack_result = test_redis_vectors(6380)
        
        # Summary
        print("\n" + "="*60)
        print("Summary")
        print("="*60)
        print(f"Local Redis (6379): {'✅ Vectors work' if local_result else '❌ No vector support'}")
        print(f"Redis Stack (6380): {'✅ Vectors work' if stack_result else '❌ Not available'}")
        
        if stack_result:
            print("\n✅ Use port 6380 for vector operations!")
        
    else:
        success = test_redis_vectors(args.port)
        
        print("\n" + "="*60)
        if success:
            print(f"✅ Redis on port {args.port} has vector support!")
        else:
            print(f"❌ Redis on port {args.port} does not have vector support")
            
            if args.port == 6379:
                print("\n💡 Tip: Try Redis Stack on port 6380:")
                print("   ./start_redis_vector_alt.sh")
                print("   python test_redis_vectors_port.py --port 6380")

if __name__ == "__main__":
    main()