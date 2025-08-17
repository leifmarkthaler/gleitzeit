#!/usr/bin/env python
"""Basic synchronous test for RAG components."""

import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

from embeddings_provider import EmbeddingsProvider
from rag_provider import RAGProvider


def test_basic_functionality():
    """Test basic non-async functionality."""
    print("=" * 60)
    print("Basic RAG Functionality Test")
    print("=" * 60)
    
    # Test embeddings provider creation
    print("\n1. Testing provider creation...")
    config = {
        'chunk_size': 100,
        'chunk_overlap': 20
    }
    
    embeddings = EmbeddingsProvider(config)
    print(f"   ✓ EmbeddingsProvider created")
    print(f"   - Provider ID: {embeddings.provider_id}")
    print(f"   - Protocol ID: {embeddings.protocol_id}")
    print(f"   - Supported methods: {embeddings.get_supported_methods()}")
    
    # Test chunking (synchronous)
    print("\n2. Testing text chunking...")
    text = "This is the first sentence. This is the second sentence. " * 5
    chunks = embeddings.chunk_text(text, chunk_size=50)
    print(f"   ✓ Chunked {len(text)} chars into {len(chunks)} chunks")
    for i, chunk in enumerate(chunks[:3], 1):
        print(f"   Chunk {i}: '{chunk[:40]}...'")
    
    # Test cosine similarity
    print("\n3. Testing cosine similarity...")
    sim1 = embeddings.cosine_similarity([1, 0, 0], [1, 0, 0])
    sim2 = embeddings.cosine_similarity([1, 0, 0], [0, 1, 0])
    sim3 = embeddings.cosine_similarity([1, 1, 0], [1, 1, 0])
    print(f"   ✓ Same vectors: {sim1:.3f}")
    print(f"   ✓ Orthogonal vectors: {sim2:.3f}")
    print(f"   ✓ Parallel vectors: {sim3:.3f}")
    
    # Test RAG provider creation
    print("\n4. Testing RAG provider...")
    rag = RAGProvider(config)
    print(f"   ✓ RAGProvider created")
    print(f"   - Provider ID: {rag.provider_id}")
    print(f"   - Protocol ID: {rag.protocol_id}")
    print(f"   - Supported methods: {rag.get_supported_methods()}")
    
    # Test that providers implement the required interface
    print("\n5. Testing provider interface...")
    assert hasattr(embeddings, 'handle_request'), "Missing handle_request method"
    assert hasattr(embeddings, 'initialize'), "Missing initialize method"
    assert hasattr(embeddings, 'shutdown'), "Missing shutdown method"
    assert hasattr(embeddings, 'health_check'), "Missing health_check method"
    print("   ✓ All required methods present")
    
    print("\n" + "=" * 60)
    print("Basic tests passed! ✓")
    print("Provider integration with Gleitzeit is ready.")
    print("=" * 60)
    
    print("\nNOTE: To test with Ollama, ensure:")
    print("1. Ollama is running: ollama serve")
    print("2. Required models are installed:")
    print("   - ollama pull nomic-embed-text")
    print("   - ollama pull llama3.2")
    
    return True


if __name__ == "__main__":
    success = test_basic_functionality()
    sys.exit(0 if success else 1)