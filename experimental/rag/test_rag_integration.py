#!/usr/bin/env python
"""Integration test for RAG with Gleitzeit."""

import asyncio
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

from embeddings_provider import EmbeddingsProvider
from rag_provider import RAGProvider
from gleitzeit.registry import ProtocolProviderRegistry


async def test_rag_with_gleitzeit():
    """Test RAG providers with Gleitzeit registry."""
    print("=" * 60)
    print("Testing RAG Integration with Gleitzeit")
    print("=" * 60)
    
    # Create protocol registry
    registry = ProtocolProviderRegistry()
    
    # Create and register providers
    print("\n1. Creating providers...")
    config = {
        'ollama_endpoint': 'http://localhost:11434',
        'embedding_model': 'nomic-embed-text',
        'chat_model': 'llama3.2:latest',
        'chunk_size': 200,
        'top_k': 3
    }
    
    embeddings_provider = EmbeddingsProvider(config)
    rag_provider = RAGProvider(config)
    
    print("   ✓ Providers created")
    
    # Initialize providers
    print("\n2. Initializing providers...")
    await embeddings_provider.start()
    await rag_provider.start()
    print("   ✓ Providers initialized")
    
    # Register with registry
    print("\n3. Registering providers...")
    registry.register_provider(
        provider_id="embeddings_provider",
        protocol_id="embeddings/v1",
        provider_instance=embeddings_provider,
        supported_methods=set(embeddings_provider.get_supported_methods())
    )
    registry.register_provider(
        provider_id="rag_provider",
        protocol_id="rag/v1",
        provider_instance=rag_provider,
        supported_methods=set(rag_provider.get_supported_methods())
    )
    print(f"   ✓ Registered providers")
    
    # Test embeddings provider through registry
    print("\n4. Testing embeddings provider...")
    result = await registry.handle_request(
        protocol_id="embeddings/v1",
        method="chunk_text",
        params={
            "text": "This is a test document. It contains multiple sentences. We will chunk it to test the provider.",
            "chunk_size": 30
        }
    )
    print(f"   ✓ Chunked text into {result['count']} chunks")
    
    # Test RAG provider through registry
    print("\n5. Testing RAG provider...")
    
    # Ingest documents
    ingest_result = await registry.handle_request(
        protocol_id="rag/v1",
        method="ingest_documents",
        params={
            "documents": [
                {
                    "id": "doc1",
                    "text": "Gleitzeit is a workflow orchestration system for LLMs.",
                    "metadata": {"category": "intro"}
                },
                {
                    "id": "doc2",
                    "text": "RAG combines retrieval with generation for better responses.",
                    "metadata": {"category": "rag"}
                },
                {
                    "id": "doc3",
                    "text": "The system uses protocol-based providers for extensibility.",
                    "metadata": {"category": "architecture"}
                }
            ]
        }
    )
    print(f"   ✓ Ingested {ingest_result['documents_processed']} documents")
    print(f"   ✓ Created {ingest_result['chunks_created']} chunks")
    
    # Query the system
    print("\n6. Testing RAG query...")
    query_result = await registry.handle_request(
        protocol_id="rag/v1",
        method="query",
        params={
            "query": "What is Gleitzeit?",
            "use_context": True
        }
    )
    print(f"   ✓ Query executed")
    print(f"   Response: {query_result['response'][:100]}...")
    print(f"   Sources: {len(query_result.get('sources', []))} documents used")
    
    # Test workflow-style execution
    print("\n7. Testing workflow-style execution...")
    
    # Create a simple workflow simulation
    tasks = [
        {
            "id": "clear",
            "protocol": "rag/v1",
            "method": "clear_index",
            "params": {}
        },
        {
            "id": "ingest",
            "protocol": "rag/v1",
            "method": "ingest_documents",
            "params": {
                "documents": [
                    {"id": "workflow_doc", "text": "This document was added via workflow execution."}
                ]
            }
        },
        {
            "id": "query",
            "protocol": "rag/v1",
            "method": "query",
            "params": {
                "query": "What was added via workflow?",
                "use_context": True
            }
        }
    ]
    
    for task in tasks:
        result = await registry.handle_request(
            protocol_id=task["protocol"],
            method=task["method"],
            params=task["params"]
        )
        print(f"   ✓ Task '{task['id']}' completed")
    
    # Cleanup
    print("\n8. Cleaning up...")
    await embeddings_provider.stop()
    await rag_provider.stop()
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
        
        # Run the integration test
        success = await test_rag_with_gleitzeit()
        return 0 if success else 1
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)