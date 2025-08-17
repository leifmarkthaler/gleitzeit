"""RAG (Retrieval-Augmented Generation) provider for Gleitzeit."""

import asyncio
from typing import Dict, Any, List, Optional
from pathlib import Path
import glob as glob_module

from gleitzeit.protocols.base import ProtocolProvider, ProviderCapabilities
from gleitzeit.core.models import TaskResult, TaskStatus
from .embeddings_provider import EmbeddingsProvider


class RAGProvider(ProtocolProvider):
    """Provider for RAG workflows combining retrieval and generation."""
    
    protocol_name = "rag"
    protocol_version = "v1"
    
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Initialize RAG provider."""
        super().__init__(config or {})
        
        # Initialize embeddings provider
        self.embeddings_provider = EmbeddingsProvider(config)
        
        # LLM configuration
        self.ollama_endpoint = self.config.get('ollama_endpoint', 'http://localhost:11434')
        self.chat_model = self.config.get('chat_model', 'llama3.2:latest')
        
        # RAG configuration
        self.top_k = self.config.get('top_k', 5)
        self.context_max_tokens = self.config.get('context_max_tokens', 2000)
        self.similarity_threshold = self.config.get('similarity_threshold', 0.3)
    
    async def initialize(self) -> None:
        """Initialize provider resources."""
        await self.embeddings_provider.initialize()
    
    async def cleanup(self) -> None:
        """Clean up provider resources."""
        await self.embeddings_provider.cleanup()
    
    async def validate(self) -> bool:
        """Validate provider configuration."""
        return await self.embeddings_provider.validate()
    
    def get_capabilities(self) -> ProviderCapabilities:
        """Get provider capabilities."""
        return ProviderCapabilities(
            supports_batch=True,
            supports_streaming=False,
            max_concurrent_tasks=5,
            supported_methods=[
                'ingest_documents',
                'ingest_directory',
                'query',
                'query_with_context',
                'clear_index'
            ]
        )
    
    async def ingest_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ingest documents into the RAG system."""
        all_chunks = []
        
        for doc in documents:
            text = doc.get('text', '')
            doc_id = doc.get('id', '')
            metadata = doc.get('metadata', {})
            
            # Chunk the document
            chunks = self.embeddings_provider.chunk_text(text)
            
            # Create chunk documents with metadata
            for i, chunk in enumerate(chunks):
                all_chunks.append({
                    'id': f"{doc_id}_chunk_{i}",
                    'text': chunk,
                    'metadata': {
                        **metadata,
                        'source_doc': doc_id,
                        'chunk_index': i,
                        'total_chunks': len(chunks)
                    }
                })
        
        # Index all chunks
        result = await self.embeddings_provider.index_documents(all_chunks)
        
        return {
            'documents_processed': len(documents),
            'chunks_created': len(all_chunks),
            'index_result': result
        }
    
    async def ingest_directory(self, directory: str, pattern: str = "*.txt") -> Dict[str, Any]:
        """Ingest all matching files from a directory."""
        path = Path(directory)
        
        if not path.exists():
            raise ValueError(f"Directory does not exist: {directory}")
        
        # Find matching files
        files = list(path.glob(pattern))
        
        documents = []
        for file_path in files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                documents.append({
                    'id': str(file_path),
                    'text': content,
                    'metadata': {
                        'filename': file_path.name,
                        'path': str(file_path),
                        'size': len(content)
                    }
                })
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
        
        if documents:
            return await self.ingest_documents(documents)
        else:
            return {
                'documents_processed': 0,
                'chunks_created': 0,
                'message': 'No matching files found'
            }
    
    async def generate_with_llm(self, prompt: str, context: Optional[str] = None) -> str:
        """Generate response using LLM with optional context."""
        import aiohttp
        
        messages = []
        
        if context:
            system_prompt = (
                "You are a helpful assistant. Use the following context to answer the user's question. "
                "If the context doesn't contain relevant information, say so and provide the best answer you can."
            )
            messages.append({'role': 'system', 'content': system_prompt})
            messages.append({'role': 'user', 'content': f"Context:\n{context}\n\nQuestion: {prompt}"})
        else:
            messages.append({'role': 'user', 'content': prompt})
        
        async with aiohttp.ClientSession() as session:
            payload = {
                'model': self.chat_model,
                'messages': messages,
                'stream': False
            }
            
            async with session.post(
                f"{self.ollama_endpoint}/api/chat",
                json=payload
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data['message']['content']
                else:
                    raise Exception(f"Failed to generate response: {response.status}")
    
    async def query(self, query: str, use_context: bool = True) -> Dict[str, Any]:
        """Query the RAG system."""
        if use_context:
            # Retrieve relevant context
            context = await self.embeddings_provider.retrieve_context(
                query,
                top_k=self.top_k,
                max_tokens=self.context_max_tokens
            )
            
            # Generate response with context
            response = await self.generate_with_llm(query, context)
            
            # Also get the similar documents for reference
            similar_docs = await self.embeddings_provider.search_similar(
                query,
                top_k=self.top_k,
                threshold=self.similarity_threshold
            )
            
            return {
                'query': query,
                'response': response,
                'context_used': context,
                'sources': [
                    {
                        'id': doc.id,
                        'text': doc.text[:200] + '...' if len(doc.text) > 200 else doc.text,
                        'score': doc.score,
                        'metadata': doc.metadata
                    }
                    for doc in similar_docs
                ]
            }
        else:
            # Generate without context
            response = await self.generate_with_llm(query)
            return {
                'query': query,
                'response': response,
                'context_used': None,
                'sources': []
            }
    
    async def query_with_context(self, query: str, additional_context: str) -> Dict[str, Any]:
        """Query with additional user-provided context."""
        # Retrieve relevant context from index
        retrieved_context = await self.embeddings_provider.retrieve_context(
            query,
            top_k=self.top_k,
            max_tokens=self.context_max_tokens // 2  # Leave room for additional context
        )
        
        # Combine contexts
        full_context = f"Retrieved Context:\n{retrieved_context}\n\nAdditional Context:\n{additional_context}"
        
        # Generate response
        response = await self.generate_with_llm(query, full_context)
        
        return {
            'query': query,
            'response': response,
            'retrieved_context': retrieved_context,
            'additional_context': additional_context
        }
    
    async def clear_index(self) -> Dict[str, Any]:
        """Clear the document index."""
        doc_count = len(self.embeddings_provider.documents)
        self.embeddings_provider.documents.clear()
        self.embeddings_provider.embeddings_cache.clear()
        
        return {
            'status': 'cleared',
            'documents_removed': doc_count
        }
    
    async def execute(self, method: str, parameters: Dict[str, Any]) -> TaskResult:
        """Execute a method on the provider."""
        try:
            if method == 'ingest_documents':
                documents = parameters['documents']
                result = await self.ingest_documents(documents)
                return TaskResult(
                    task_id=parameters.get('task_id', 'ingest_documents'),
                    status=TaskStatus.COMPLETED,
                    result=result
                )
            
            elif method == 'ingest_directory':
                directory = parameters['directory']
                pattern = parameters.get('pattern', '*.txt')
                result = await self.ingest_directory(directory, pattern)
                return TaskResult(
                    task_id=parameters.get('task_id', 'ingest_directory'),
                    status=TaskStatus.COMPLETED,
                    result=result
                )
            
            elif method == 'query':
                query = parameters['query']
                use_context = parameters.get('use_context', True)
                result = await self.query(query, use_context)
                return TaskResult(
                    task_id=parameters.get('task_id', 'query'),
                    status=TaskStatus.COMPLETED,
                    result=result
                )
            
            elif method == 'query_with_context':
                query = parameters['query']
                additional_context = parameters['additional_context']
                result = await self.query_with_context(query, additional_context)
                return TaskResult(
                    task_id=parameters.get('task_id', 'query_with_context'),
                    status=TaskStatus.COMPLETED,
                    result=result
                )
            
            elif method == 'clear_index':
                result = await self.clear_index()
                return TaskResult(
                    task_id=parameters.get('task_id', 'clear_index'),
                    status=TaskStatus.COMPLETED,
                    result=result
                )
            
            else:
                raise ValueError(f"Unsupported method: {method}")
        
        except Exception as e:
            return TaskResult(
                task_id=parameters.get('task_id', method),
                status=TaskStatus.FAILED,
                error=str(e)
            )