"""RAG client for Gleitzeit - High-level API for RAG operations."""

import asyncio
from typing import Dict, Any, List, Optional
from pathlib import Path

from gleitzeit import GleitzeitClient
from gleitzeit.core.workflow import Workflow, Task


class RAGClient:
    """High-level client for RAG operations in Gleitzeit."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Initialize RAG client."""
        self.config = config or {}
        self.client: Optional[GleitzeitClient] = None
    
    async def __aenter__(self) -> 'RAGClient':
        """Async context manager entry."""
        self.client = GleitzeitClient(self.config)
        await self.client.__aenter__()
        
        # Register RAG providers
        await self._register_providers()
        
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self.client:
            await self.client.__aexit__(exc_type, exc_val, exc_tb)
    
    async def _register_providers(self) -> None:
        """Register RAG and embeddings providers."""
        # Import providers
        from .embeddings_provider import EmbeddingsProvider
        from .rag_provider import RAGProvider
        
        # Register with the client's engine
        if self.client and self.client.engine:
            registry = self.client.engine.provider_registry
            
            # Register embeddings provider
            embeddings_provider = EmbeddingsProvider(self.config)
            await embeddings_provider.initialize()
            registry.register_provider('embeddings/v1', embeddings_provider)
            
            # Register RAG provider
            rag_provider = RAGProvider(self.config)
            await rag_provider.initialize()
            registry.register_provider('rag/v1', rag_provider)
    
    async def ingest_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ingest documents into the RAG system.
        
        Args:
            documents: List of documents with 'text' and optional 'id', 'metadata'
        
        Returns:
            Ingestion results
        """
        if not self.client:
            raise RuntimeError("Client not initialized")
        
        workflow = Workflow(
            name="Ingest Documents",
            tasks=[
                Task(
                    id="ingest",
                    method="rag/ingest_documents",
                    parameters={'documents': documents}
                )
            ]
        )
        
        results = await self.client.engine.execute_workflow(workflow)
        return results.get('ingest', {}).get('result', {})
    
    async def ingest_directory(self, directory: str, pattern: str = "*.txt") -> Dict[str, Any]:
        """Ingest all matching files from a directory.
        
        Args:
            directory: Directory path
            pattern: File pattern to match
        
        Returns:
            Ingestion results
        """
        if not self.client:
            raise RuntimeError("Client not initialized")
        
        workflow = Workflow(
            name="Ingest Directory",
            tasks=[
                Task(
                    id="ingest",
                    method="rag/ingest_directory",
                    parameters={'directory': directory, 'pattern': pattern}
                )
            ]
        )
        
        results = await self.client.engine.execute_workflow(workflow)
        return results.get('ingest', {}).get('result', {})
    
    async def query(self, query: str, use_context: bool = True, top_k: int = 5) -> Dict[str, Any]:
        """Query the RAG system.
        
        Args:
            query: Question to ask
            use_context: Whether to use retrieved context
            top_k: Number of documents to retrieve
        
        Returns:
            Query response with sources
        """
        if not self.client:
            raise RuntimeError("Client not initialized")
        
        # Update config for this query
        if self.client.engine and self.client.engine.provider_registry:
            provider = self.client.engine.provider_registry.get_provider('rag/v1')
            if provider:
                provider.top_k = top_k
        
        workflow = Workflow(
            name="RAG Query",
            tasks=[
                Task(
                    id="query",
                    method="rag/query",
                    parameters={'query': query, 'use_context': use_context}
                )
            ]
        )
        
        results = await self.client.engine.execute_workflow(workflow)
        return results.get('query', {}).get('result', {})
    
    async def query_with_context(self, query: str, additional_context: str) -> Dict[str, Any]:
        """Query with additional user-provided context.
        
        Args:
            query: Question to ask
            additional_context: Additional context to consider
        
        Returns:
            Query response
        """
        if not self.client:
            raise RuntimeError("Client not initialized")
        
        workflow = Workflow(
            name="RAG Query with Context",
            tasks=[
                Task(
                    id="query",
                    method="rag/query_with_context",
                    parameters={
                        'query': query,
                        'additional_context': additional_context
                    }
                )
            ]
        )
        
        results = await self.client.engine.execute_workflow(workflow)
        return results.get('query', {}).get('result', {})
    
    async def clear_index(self) -> Dict[str, Any]:
        """Clear the document index."""
        if not self.client:
            raise RuntimeError("Client not initialized")
        
        workflow = Workflow(
            name="Clear Index",
            tasks=[
                Task(
                    id="clear",
                    method="rag/clear_index",
                    parameters={}
                )
            ]
        )
        
        results = await self.client.engine.execute_workflow(workflow)
        return results.get('clear', {}).get('result', {})
    
    async def build_knowledge_base(self, directory: str, pattern: str = "*.txt") -> Dict[str, Any]:
        """Build a knowledge base from a directory of documents.
        
        Args:
            directory: Directory containing documents
            pattern: File pattern to match
        
        Returns:
            Knowledge base statistics
        """
        # First, clear existing index
        await self.clear_index()
        
        # Ingest directory
        ingest_result = await self.ingest_directory(directory, pattern)
        
        # Test with a sample query
        test_query = await self.query("What are the main topics in this knowledge base?")
        
        return {
            'ingestion': ingest_result,
            'test_query': test_query.get('response', '')[:500],
            'sources_count': len(test_query.get('sources', []))
        }


async def main():
    """Example usage of RAG client."""
    
    # Configuration
    config = {
        'ollama_endpoint': 'http://localhost:11434',
        'embedding_model': 'nomic-embed-text',
        'chat_model': 'llama3.2:latest',
        'chunk_size': 512,
        'chunk_overlap': 50,
        'top_k': 5
    }
    
    async with RAGClient(config) as rag:
        # Example 1: Ingest individual documents
        documents = [
            {
                'id': 'doc1',
                'text': 'Gleitzeit is a workflow orchestration system for LLMs.',
                'metadata': {'category': 'intro'}
            },
            {
                'id': 'doc2',
                'text': 'RAG combines retrieval with generation for better responses.',
                'metadata': {'category': 'rag'}
            }
        ]
        
        print("Ingesting documents...")
        ingest_result = await rag.ingest_documents(documents)
        print(f"Ingested: {ingest_result}")
        
        # Example 2: Query the system
        print("\nQuerying RAG system...")
        response = await rag.query("What is Gleitzeit?")
        print(f"Response: {response['response']}")
        print(f"Sources used: {len(response.get('sources', []))}")
        
        # Example 3: Query without context
        print("\nQuerying without context...")
        response_no_context = await rag.query("What is Gleitzeit?", use_context=False)
        print(f"Response (no context): {response_no_context['response']}")
        
        # Example 4: Build knowledge base from directory
        # print("\nBuilding knowledge base from directory...")
        # kb_result = await rag.build_knowledge_base("./documents", "*.md")
        # print(f"Knowledge base built: {kb_result['ingestion']}")


if __name__ == "__main__":
    asyncio.run(main())