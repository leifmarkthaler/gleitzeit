"""Interactive demo of the RAG system."""

import asyncio
import sys
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent.parent))

from rag_client import RAGClient


async def demo_rag():
    """Run an interactive RAG demo."""
    print("=" * 60)
    print("Gleitzeit RAG System Demo")
    print("=" * 60)
    
    config = {
        'ollama_endpoint': 'http://localhost:11434',
        'embedding_model': 'nomic-embed-text',
        'chat_model': 'llama3.2:latest',
        'chunk_size': 200,
        'chunk_overlap': 50,
        'top_k': 3
    }
    
    async with RAGClient(config) as rag:
        print("\n1. Checking system status...")
        
        # Check if Ollama is available
        from embeddings_provider import EmbeddingsProvider
        provider = EmbeddingsProvider(config)
        if not await provider.health_check():
            print("❌ Ollama is not available. Please ensure Ollama is running.")
            print("   Run: ollama serve")
            print("   Then: ollama pull nomic-embed-text")
            print("         ollama pull llama3.2")
            return
        
        print("✓ Ollama is available")
        
        # Clear existing index
        print("\n2. Clearing existing index...")
        await rag.clear_index()
        print("✓ Index cleared")
        
        # Ingest sample documents
        print("\n3. Ingesting sample documents...")
        sample_dir = Path(__file__).parent / "sample_docs"
        
        if sample_dir.exists():
            result = await rag.ingest_directory(str(sample_dir), "*.*")
            print(f"✓ Ingested {result['documents_processed']} documents")
            print(f"✓ Created {result['chunks_created']} chunks")
        else:
            print("⚠ No sample documents found. Creating test documents...")
            
            # Create test documents programmatically
            test_docs = [
                {
                    'id': 'gleitzeit_intro',
                    'text': '''Gleitzeit is a workflow orchestration system designed for LLM applications. 
                    It provides a unified framework for executing complex workflows combining LLM interactions, 
                    Python code execution, and MCP tools. The system uses YAML-based workflow definitions 
                    and supports batch processing, parameter substitution, and automatic persistence.'''
                },
                {
                    'id': 'rag_intro',
                    'text': '''RAG (Retrieval-Augmented Generation) enhances LLM responses by incorporating 
                    relevant information from a knowledge base. The process involves document ingestion, 
                    chunking, embedding generation, similarity search, and context-aware response generation. 
                    This approach reduces hallucination and improves accuracy.'''
                },
                {
                    'id': 'implementation',
                    'text': '''The RAG implementation consists of three main components: EmbeddingsProvider 
                    for vector operations, RAGProvider for orchestrating the RAG workflow, and RAGClient 
                    for providing a high-level Python API. The system uses Ollama for both embedding 
                    generation and LLM responses.'''
                }
            ]
            
            result = await rag.ingest_documents(test_docs)
            print(f"✓ Created and ingested {result['indexed_count']} test documents")
        
        # Interactive Q&A
        print("\n4. Starting interactive Q&A session...")
        print("-" * 60)
        print("You can now ask questions about the ingested documents.")
        print("Type 'quit' to exit, 'status' to see index info.")
        print("-" * 60)
        
        while True:
            print("\n")
            query = input("Your question: ").strip()
            
            if query.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if query.lower() == 'status':
                # Show index status (would need to add this method)
                print("Index contains documents about Gleitzeit, RAG, and implementation details.")
                continue
            
            if not query:
                continue
            
            print("\n🔍 Searching knowledge base...")
            
            try:
                # Query with context
                response = await rag.query(query, use_context=True)
                
                print("\n📝 Answer:")
                print("-" * 40)
                print(response['response'])
                print("-" * 40)
                
                # Show sources
                if response.get('sources'):
                    print("\n📚 Sources used:")
                    for i, source in enumerate(response['sources'][:3], 1):
                        print(f"\n{i}. Document: {source.get('id', 'Unknown')}")
                        print(f"   Relevance: {source.get('score', 0):.3f}")
                        preview = source.get('text', '')[:150]
                        if len(source.get('text', '')) > 150:
                            preview += "..."
                        print(f"   Preview: {preview}")
                
                # Optionally compare with no-context response
                print("\n💡 Tip: The response above used retrieved context from the knowledge base.")
                
            except Exception as e:
                print(f"❌ Error: {e}")
                print("Please try again with a different question.")


async def quick_test():
    """Run a quick non-interactive test."""
    print("Running quick RAG test...")
    
    config = {
        'chunk_size': 100,
        'top_k': 3
    }
    
    async with RAGClient(config) as rag:
        # Check if Ollama is available
        from embeddings_provider import EmbeddingsProvider
        provider = EmbeddingsProvider(config)
        
        if not await provider.health_check():
            print("⚠ Ollama not available - please start Ollama to run the full demo")
            print("  Run: ollama serve")
            print("  Then: ollama pull nomic-embed-text && ollama pull llama3.2")
            return
        
        # Quick test
        print("✓ System is ready")
        
        # Ingest a test document
        docs = [{'id': 'test', 'text': 'Gleitzeit is a workflow orchestration system.'}]
        await rag.ingest_documents(docs)
        print("✓ Document ingested")
        
        # Query
        response = await rag.query("What is Gleitzeit?")
        print("✓ Query executed")
        print(f"Response preview: {response['response'][:100]}...")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="RAG System Demo")
    parser.add_argument('--quick', action='store_true', help="Run quick test instead of interactive demo")
    args = parser.parse_args()
    
    if args.quick:
        asyncio.run(quick_test())
    else:
        try:
            asyncio.run(demo_rag())
        except KeyboardInterrupt:
            print("\nInterrupted by user")
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()