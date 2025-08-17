#!/usr/bin/env python
"""Simple test for RAG providers."""

import asyncio
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

from embeddings_provider import EmbeddingsProvider
from rag_provider import RAGProvider


async def test_rag_providers():
    """Test RAG providers directly."""
    print("=" * 60)
    print("Testing RAG Providers")
    print("=" * 60)
    
    # Configuration
    config = {
        'ollama_endpoint': 'http://localhost:11434',
        'embedding_model': 'nomic-embed-text',
        'chat_model': 'llama3.2:latest',
        'chunk_size': 200,
        'top_k': 3
    }
    
    # Create providers
    print("\n1. Creating providers...")
    embeddings = EmbeddingsProvider(config)
    rag = RAGProvider(config)
    print("   ✓ Providers created")
    
    # Initialize
    print("\n2. Initializing providers...")
    await embeddings.start()
    await rag.start()
    print("   ✓ Providers started")
    
    # Test embeddings provider
    print("\n3. Testing embeddings provider...")
    
    # Test chunking
    result = await embeddings.handle_request(
        "chunk_text",
        {
            "text": "This is a test document. It contains multiple sentences. We will chunk it.",
            "chunk_size": 30
        }
    )
    print(f"   ✓ Chunked text into {result['count']} chunks")
    
    # Test embedding generation
    if await embeddings.health_check():
        result = await embeddings.handle_request(
            "generate_embedding",
            {"text": "Test embedding"}
        )
        print(f"   ✓ Generated embedding with {result['dimension']} dimensions")
    
    # Test RAG provider
    print("\n4. Testing RAG provider...")
    
    # Ingest documents
    result = await rag.handle_request(
        "ingest_documents",
        {
            "documents": [
                {
                    "id": "doc1",
                    "text": "Gleitzeit is a workflow orchestration system designed for LLM applications.",
                    "metadata": {"category": "intro"}
                },
                {
                    "id": "doc2",
                    "text": "RAG (Retrieval-Augmented Generation) enhances LLM responses with relevant context.",
                    "metadata": {"category": "rag"}
                },
                {
                    "id": "doc3",
                    "text": "The system uses protocol-based providers for extensibility and modularity.",
                    "metadata": {"category": "architecture"}
                }
            ]
        }
    )
    print(f"   ✓ Ingested {result['documents_processed']} documents")
    print(f"   ✓ Created {result['chunks_created']} chunks")
    
    # Query with context
    result = await rag.handle_request(
        "query",
        {
            "query": "What is Gleitzeit and how does it relate to RAG?",
            "use_context": True
        }
    )
    print(f"\n5. Query result:")
    print(f"   Question: {result['query']}")
    print(f"   Response: {result['response'][:200]}...")
    print(f"   Sources used: {len(result.get('sources', []))}")
    
    if result.get('sources'):
        print("\n   Source documents:")
        for i, source in enumerate(result['sources'][:3], 1):
            print(f"   {i}. {source['id']} (score: {source['score']:.3f})")
    
    # Query without context for comparison
    result_no_context = await rag.handle_request(
        "query",
        {
            "query": "What is Gleitzeit and how does it relate to RAG?",
            "use_context": False
        }
    )
    print(f"\n6. Query without context:")
    print(f"   Response: {result_no_context['response'][:200]}...")
    
    # Clear index
    result = await rag.handle_request("clear_index", {})
    print(f"\n7. Cleanup:")
    print(f"   ✓ Cleared {result['documents_removed']} documents")
    
    # Shutdown
    await embeddings.stop()
    await rag.stop()
    print("   ✓ Providers stopped")
    
    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)
    
    return True


async def main():
    """Main entry point."""
    try:
        # Check if Ollama is available
        provider = EmbeddingsProvider()
        if not await provider.health_check():
            print("⚠️  Ollama is not available!")
            print("Please ensure Ollama is running:")
            print("  1. Start Ollama: ollama serve")
            print("  2. Pull models:")
            print("     ollama pull nomic-embed-text")
            print("     ollama pull llama3.2")
            return 1
        
        # Run the test
        success = await test_rag_providers()
        return 0 if success else 1
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)