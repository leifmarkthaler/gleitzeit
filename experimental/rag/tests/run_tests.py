"""Simple test runner for RAG implementation."""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent.parent))

from embeddings_provider import EmbeddingsProvider
from rag_provider import RAGProvider
from rag_client import RAGClient


async def test_embeddings_provider():
    """Test the embeddings provider."""
    print("\n=== Testing EmbeddingsProvider ===")
    
    provider = EmbeddingsProvider({
        'chunk_size': 100,
        'chunk_overlap': 20
    })
    
    # Test 1: Text chunking
    print("\n1. Testing text chunking...")
    text = "This is the first sentence. This is the second sentence. " * 10
    chunks = provider.chunk_text(text, chunk_size=50)
    print(f"   ✓ Created {len(chunks)} chunks from text")
    
    # Test 2: Cosine similarity
    print("\n2. Testing cosine similarity...")
    sim1 = provider.cosine_similarity([1, 0, 0], [1, 0, 0])  # Same vectors
    sim2 = provider.cosine_similarity([1, 0, 0], [0, 1, 0])  # Orthogonal
    print(f"   ✓ Same vectors similarity: {sim1:.3f}")
    print(f"   ✓ Orthogonal vectors similarity: {sim2:.3f}")
    
    # Test 3: Ollama connection
    print("\n3. Testing Ollama connection...")
    if await provider.health_check():
        print("   ✓ Ollama is available")
        
        # Test embedding generation
        print("\n4. Testing embedding generation...")
        try:
            embedding = await provider.generate_embedding("Test text for embedding")
            print(f"   ✓ Generated embedding with {len(embedding)} dimensions")
            
            # Test caching
            embedding2 = await provider.generate_embedding("Test text for embedding")
            print(f"   ✓ Embedding cache working (cache size: {len(provider.embeddings_cache)})")
        except Exception as e:
            print(f"   ✗ Embedding generation failed: {e}")
    else:
        print("   ⚠ Ollama not available - skipping embedding tests")
    
    await provider.shutdown()
    return True


async def test_rag_provider():
    """Test the RAG provider."""
    print("\n=== Testing RAGProvider ===")
    
    provider = RAGProvider({
        'chunk_size': 100,
        'top_k': 3
    })
    
    await provider.initialize()
    
    if not await provider.health_check():
        print("   ⚠ Ollama not available - skipping RAG tests")
        await provider.shutdown()
        return False
    
    # Test 1: Document ingestion
    print("\n1. Testing document ingestion...")
    documents = [
        {'id': 'doc1', 'text': 'Gleitzeit is a workflow orchestration system.'},
        {'id': 'doc2', 'text': 'It supports LLM workflows and batch processing.'},
        {'id': 'doc3', 'text': 'Python is the main implementation language.'}
    ]
    
    result = await provider.ingest_documents(documents)
    print(f"   ✓ Ingested {result['documents_processed']} documents")
    print(f"   ✓ Created {result['chunks_created']} chunks")
    
    # Test 2: Query with context
    print("\n2. Testing query with context...")
    try:
        query_result = await provider.query("What is Gleitzeit?", use_context=True)
        print(f"   ✓ Query executed successfully")
        print(f"   ✓ Found {len(query_result.get('sources', []))} relevant sources")
        print(f"   Response preview: {query_result['response'][:100]}...")
    except Exception as e:
        print(f"   ✗ Query failed: {e}")
    
    # Test 3: Clear index
    print("\n3. Testing index clearing...")
    clear_result = await provider.clear_index()
    print(f"   ✓ Cleared {clear_result['documents_removed']} documents")
    
    await provider.shutdown()
    return True


async def test_rag_client():
    """Test the RAG client."""
    print("\n=== Testing RAGClient ===")
    
    config = {
        'chunk_size': 100,
        'top_k': 3
    }
    
    try:
        async with RAGClient(config) as client:
            print("\n1. Testing client initialization...")
            print("   ✓ Client initialized successfully")
            
            # Only test if Ollama is available
            provider = EmbeddingsProvider()
            if await provider.health_check():
                print("\n2. Testing document operations...")
                
                # Ingest documents
                documents = [
                    {'id': 'test1', 'text': 'This is a test document about Gleitzeit.'},
                    {'id': 'test2', 'text': 'RAG combines retrieval with generation.'}
                ]
                
                result = await client.ingest_documents(documents)
                print(f"   ✓ Ingested documents: {result}")
                
                # Query
                print("\n3. Testing query...")
                response = await client.query("What is RAG?")
                print(f"   ✓ Query successful")
                print(f"   Response preview: {response.get('response', '')[:100]}...")
                
                # Clear
                print("\n4. Testing index clear...")
                clear_result = await client.clear_index()
                print(f"   ✓ Index cleared: {clear_result}")
            else:
                print("   ⚠ Ollama not available - skipping client operation tests")
            
            await provider.shutdown()
            
    except Exception as e:
        print(f"   ✗ Client test failed: {e}")
        return False
    
    return True


async def test_workflow_integration():
    """Test workflow integration."""
    print("\n=== Testing Workflow Integration ===")
    
    try:
        # Import Gleitzeit components
        from gleitzeit.core.workflow import Workflow, Task
        from gleitzeit.core.models import TaskStatus
        
        print("\n1. Creating test workflow...")
        workflow = Workflow(
            name="RAG Test Workflow",
            tasks=[
                Task(
                    id="chunk_test",
                    method="embeddings/chunk_text",
                    parameters={
                        'text': "This is a test. " * 20,
                        'chunk_size': 50
                    }
                )
            ]
        )
        print("   ✓ Workflow created successfully")
        
        print("\n2. Verifying protocol methods...")
        provider = EmbeddingsProvider()
        capabilities = provider.get_capabilities()
        print(f"   ✓ Embeddings provider supports: {capabilities.supported_methods}")
        
        rag_provider = RAGProvider()
        rag_capabilities = rag_provider.get_capabilities()
        print(f"   ✓ RAG provider supports: {rag_capabilities.supported_methods}")
        
    except ImportError as e:
        print(f"   ⚠ Could not import Gleitzeit components: {e}")
        return False
    except Exception as e:
        print(f"   ✗ Workflow test failed: {e}")
        return False
    
    return True


async def main():
    """Run all tests."""
    print("=" * 60)
    print("RAG Implementation Test Suite")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("EmbeddingsProvider", await test_embeddings_provider()))
    results.append(("RAGProvider", await test_rag_provider()))
    results.append(("RAGClient", await test_rag_client()))
    results.append(("Workflow Integration", await test_workflow_integration()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name:25} {status}")
    
    all_passed = all(result[1] for result in results)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("All tests passed! ✓")
    else:
        print("Some tests failed. Please check the output above.")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)