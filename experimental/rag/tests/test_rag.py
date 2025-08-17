"""Tests for RAG implementation in Gleitzeit."""

import asyncio
import pytest
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List
import sys
import os

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from embeddings_provider import EmbeddingsProvider, Document
from rag_provider import RAGProvider
from rag_client import RAGClient


class TestEmbeddingsProvider:
    """Test embeddings provider functionality."""
    
    @pytest.fixture
    async def provider(self) -> EmbeddingsProvider:
        """Create embeddings provider instance."""
        provider = EmbeddingsProvider({
            'ollama_endpoint': 'http://localhost:11434',
            'embedding_model': 'nomic-embed-text',
            'chunk_size': 100,
            'chunk_overlap': 20
        })
        await provider.initialize()
        yield provider
        await provider.shutdown()
    
    def test_chunk_text(self) -> None:
        """Test text chunking functionality."""
        provider = EmbeddingsProvider()
        
        text = "This is a test. " * 50  # Create long text
        chunks = provider.chunk_text(text, chunk_size=100, overlap=20)
        
        assert len(chunks) > 1
        assert all(len(chunk) <= 100 for chunk in chunks)
        
        # Check overlap exists
        for i in range(len(chunks) - 1):
            # Some content should overlap
            assert any(word in chunks[i+1] for word in chunks[i].split()[-5:])
    
    def test_chunk_text_sentence_boundary(self) -> None:
        """Test that chunking respects sentence boundaries."""
        provider = EmbeddingsProvider()
        
        text = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence."
        chunks = provider.chunk_text(text, chunk_size=30, overlap=5)
        
        # Should break at sentence boundaries
        for chunk in chunks:
            # Each chunk should end with a period or be the last chunk
            assert chunk.endswith('.') or chunk == chunks[-1]
    
    @pytest.mark.asyncio
    async def test_generate_embedding(self, provider: EmbeddingsProvider) -> None:
        """Test embedding generation."""
        # Skip if Ollama is not available
        if not await provider.health_check():
            pytest.skip("Ollama not available")
        
        text = "This is a test document for embedding generation."
        embedding = await provider.generate_embedding(text)
        
        assert isinstance(embedding, list)
        assert len(embedding) > 0
        assert all(isinstance(x, (int, float)) for x in embedding)
    
    @pytest.mark.asyncio
    async def test_embedding_cache(self, provider: EmbeddingsProvider) -> None:
        """Test that embeddings are cached."""
        if not await provider.health_check():
            pytest.skip("Ollama not available")
        
        text = "Test caching behavior"
        
        # First call - generates embedding
        embedding1 = await provider.generate_embedding(text)
        
        # Second call - should use cache
        embedding2 = await provider.generate_embedding(text)
        
        assert embedding1 == embedding2
        assert len(provider.embeddings_cache) == 1
    
    def test_cosine_similarity(self) -> None:
        """Test cosine similarity calculation."""
        provider = EmbeddingsProvider()
        
        # Identical vectors
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [1.0, 2.0, 3.0]
        similarity = provider.cosine_similarity(vec1, vec2)
        assert abs(similarity - 1.0) < 0.001
        
        # Orthogonal vectors
        vec3 = [1.0, 0.0]
        vec4 = [0.0, 1.0]
        similarity = provider.cosine_similarity(vec3, vec4)
        assert abs(similarity) < 0.001
        
        # Opposite vectors
        vec5 = [1.0, 1.0]
        vec6 = [-1.0, -1.0]
        similarity = provider.cosine_similarity(vec5, vec6)
        assert abs(similarity + 1.0) < 0.001
    
    @pytest.mark.asyncio
    async def test_index_documents(self, provider: EmbeddingsProvider) -> None:
        """Test document indexing."""
        if not await provider.health_check():
            pytest.skip("Ollama not available")
        
        documents = [
            {'id': 'doc1', 'text': 'First document about Python programming.'},
            {'id': 'doc2', 'text': 'Second document about machine learning.'},
            {'id': 'doc3', 'text': 'Third document about data science.'}
        ]
        
        result = await provider.index_documents(documents)
        
        assert result['indexed_count'] == 3
        assert result['total_documents'] == 3
        assert len(result['document_ids']) == 3
        assert all(doc_id in provider.documents for doc_id in ['doc1', 'doc2', 'doc3'])
    
    @pytest.mark.asyncio
    async def test_search_similar(self, provider: EmbeddingsProvider) -> None:
        """Test similarity search."""
        if not await provider.health_check():
            pytest.skip("Ollama not available")
        
        # Index test documents
        documents = [
            {'id': 'python_doc', 'text': 'Python is a programming language used for web development.'},
            {'id': 'ml_doc', 'text': 'Machine learning is a subset of artificial intelligence.'},
            {'id': 'cooking_doc', 'text': 'Cooking pasta requires boiling water and salt.'}
        ]
        await provider.index_documents(documents)
        
        # Search for Python-related content
        results = await provider.search_similar("Python programming", top_k=2)
        
        assert len(results) <= 2
        assert results[0].id == 'python_doc'  # Most relevant should be first
        assert all(hasattr(doc, 'score') for doc in results)
        assert all(0 <= doc.score <= 1 for doc in results)


class TestRAGProvider:
    """Test RAG provider functionality."""
    
    @pytest.fixture
    async def provider(self) -> RAGProvider:
        """Create RAG provider instance."""
        provider = RAGProvider({
            'ollama_endpoint': 'http://localhost:11434',
            'embedding_model': 'nomic-embed-text',
            'chat_model': 'llama3.2:latest',
            'chunk_size': 100,
            'top_k': 3
        })
        await provider.initialize()
        yield provider
        await provider.shutdown()
    
    @pytest.fixture
    def temp_dir(self) -> Path:
        """Create temporary directory with test files."""
        temp_dir = Path(tempfile.mkdtemp())
        
        # Create test files
        (temp_dir / "doc1.txt").write_text("Gleitzeit is a workflow orchestration system.")
        (temp_dir / "doc2.txt").write_text("Python is used for implementing providers.")
        (temp_dir / "doc3.md").write_text("# Documentation\nThis is a test document.")
        
        yield temp_dir
        
        # Cleanup
        shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    async def test_ingest_documents(self, provider: RAGProvider) -> None:
        """Test document ingestion."""
        if not await provider.health_check():
            pytest.skip("Ollama not available")
        
        documents = [
            {'id': 'test1', 'text': 'Test document one.'},
            {'id': 'test2', 'text': 'Test document two.'}
        ]
        
        result = await provider.ingest_documents(documents)
        
        assert result['documents_processed'] == 2
        assert result['chunks_created'] > 0
        assert 'index_result' in result
    
    @pytest.mark.asyncio
    async def test_ingest_directory(self, provider: RAGProvider, temp_dir: Path) -> None:
        """Test directory ingestion."""
        if not await provider.health_check():
            pytest.skip("Ollama not available")
        
        result = await provider.ingest_directory(str(temp_dir), "*.txt")
        
        assert result['documents_processed'] == 2  # Only .txt files
        assert result['chunks_created'] > 0
    
    @pytest.mark.asyncio
    async def test_query_with_context(self, provider: RAGProvider) -> None:
        """Test querying with context."""
        if not await provider.health_check():
            pytest.skip("Ollama not available")
        
        # Ingest test documents
        documents = [
            {'id': 'gleitzeit', 'text': 'Gleitzeit is a workflow orchestration system for LLMs.'},
            {'id': 'python', 'text': 'Python is the primary language for Gleitzeit.'}
        ]
        await provider.ingest_documents(documents)
        
        # Query with context
        result = await provider.query("What is Gleitzeit?", use_context=True)
        
        assert 'response' in result
        assert 'sources' in result
        assert 'context_used' in result
        assert result['query'] == "What is Gleitzeit?"
        assert len(result['sources']) > 0
    
    @pytest.mark.asyncio
    async def test_query_without_context(self, provider: RAGProvider) -> None:
        """Test querying without context."""
        if not await provider.health_check():
            pytest.skip("Ollama not available")
        
        result = await provider.query("What is Python?", use_context=False)
        
        assert 'response' in result
        assert result['context_used'] is None
        assert len(result['sources']) == 0
    
    @pytest.mark.asyncio
    async def test_clear_index(self, provider: RAGProvider) -> None:
        """Test clearing the index."""
        if not await provider.health_check():
            pytest.skip("Ollama not available")
        
        # Add documents
        documents = [{'id': 'test', 'text': 'Test document.'}]
        await provider.ingest_documents(documents)
        
        # Clear index
        result = await provider.clear_index()
        
        assert result['status'] == 'cleared'
        assert result['documents_removed'] > 0
        assert len(provider.embeddings_provider.documents) == 0


class TestRAGClient:
    """Test RAG client functionality."""
    
    @pytest.fixture
    async def client(self) -> RAGClient:
        """Create RAG client instance."""
        config = {
            'ollama_endpoint': 'http://localhost:11434',
            'embedding_model': 'nomic-embed-text',
            'chat_model': 'llama3.2:latest'
        }
        
        client = RAGClient(config)
        # Note: We're not using context manager to avoid full initialization
        return client
    
    @pytest.mark.asyncio
    async def test_client_context_manager(self) -> None:
        """Test client context manager."""
        config = {'ollama_endpoint': 'http://localhost:11434'}
        
        async with RAGClient(config) as client:
            assert client.client is not None
    
    @pytest.mark.asyncio
    async def test_client_methods_structure(self, client: RAGClient) -> None:
        """Test that client has all expected methods."""
        assert hasattr(client, 'ingest_documents')
        assert hasattr(client, 'ingest_directory')
        assert hasattr(client, 'query')
        assert hasattr(client, 'query_with_context')
        assert hasattr(client, 'clear_index')
        assert hasattr(client, 'build_knowledge_base')


class TestIntegration:
    """Integration tests for the complete RAG system."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_workflow(self) -> None:
        """Test complete RAG workflow."""
        # Skip if Ollama is not available
        provider = EmbeddingsProvider()
        if not await provider.health_check():
            pytest.skip("Ollama not available")
        
        config = {
            'ollama_endpoint': 'http://localhost:11434',
            'embedding_model': 'nomic-embed-text',
            'chat_model': 'llama3.2:latest',
            'chunk_size': 200,
            'top_k': 3
        }
        
        async with RAGClient(config) as client:
            # Clear any existing index
            await client.clear_index()
            
            # Ingest documents
            documents = [
                {
                    'id': 'intro',
                    'text': 'Gleitzeit is a powerful workflow orchestration system designed for LLM applications.'
                },
                {
                    'id': 'features',
                    'text': 'Key features include task scheduling, dependency management, and provider abstraction.'
                },
                {
                    'id': 'usage',
                    'text': 'You can use Gleitzeit via CLI, Python API, or YAML workflows.'
                }
            ]
            
            ingest_result = await client.ingest_documents(documents)
            assert ingest_result['indexed_count'] > 0
            
            # Query the system
            response = await client.query("What is Gleitzeit used for?")
            
            assert 'response' in response
            assert 'sources' in response
            assert len(response['sources']) > 0
            assert any('workflow' in source['text'].lower() for source in response['sources'])
            
            # Query with additional context
            response_with_context = await client.query_with_context(
                "How do I use it?",
                "I'm particularly interested in Python integration."
            )
            
            assert 'response' in response_with_context
            assert 'Python' in response_with_context.get('additional_context', '')


def run_tests():
    """Run all tests."""
    pytest.main([__file__, '-v', '--tb=short'])


if __name__ == '__main__':
    # For quick testing without pytest
    import asyncio
    
    async def quick_test():
        """Quick test to verify basic functionality."""
        print("Running quick RAG test...")
        
        # Test embeddings provider
        provider = EmbeddingsProvider()
        chunks = provider.chunk_text("This is a test. " * 20, chunk_size=50)
        print(f"✓ Text chunking works: {len(chunks)} chunks created")
        
        # Test cosine similarity
        similarity = provider.cosine_similarity([1, 2, 3], [1, 2, 3])
        print(f"✓ Cosine similarity works: {similarity:.3f}")
        
        # Check Ollama availability
        if await provider.health_check():
            print("✓ Ollama is available")
            
            # Test embedding generation
            embedding = await provider.generate_embedding("Test text")
            print(f"✓ Embedding generation works: {len(embedding)} dimensions")
        else:
            print("⚠ Ollama not available - skipping embedding tests")
        
        print("\nAll basic tests passed!")
    
    asyncio.run(quick_test())