"""Embeddings provider for RAG implementation."""

import asyncio
import hashlib
import json
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
from dataclasses import dataclass, field
import aiohttp

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core.errors import ProviderError


@dataclass
class Document:
    """Represents a document chunk with its embedding."""
    id: str
    text: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


class EmbeddingsProvider(ProtocolProvider):
    """Provider for document embeddings and vector operations."""
    
    def __init__(
        self, 
        config: Optional[Dict[str, Any]] = None,
        resource_manager=None,
        hub=None,
        **kwargs
    ) -> None:
        """Initialize embeddings provider."""
        config = config or {}
        super().__init__(
            provider_id="embeddings_provider",
            protocol_id="embeddings/v1",
            name="Embeddings Provider",
            description="Provider for document embeddings and vector operations",
            resource_manager=resource_manager,
            hub=hub
        )
        self.config = config
        self.ollama_endpoint = config.get('ollama_endpoint', 'http://localhost:11434')
        self.embedding_model = config.get('embedding_model', 'nomic-embed-text')
        self.chunk_size = config.get('chunk_size', 512)
        self.chunk_overlap = config.get('chunk_overlap', 50)
        
        # In-memory vector store (can be replaced with Chroma, Pinecone, etc.)
        self.documents: Dict[str, Document] = {}
        self.embeddings_cache: Dict[str, List[float]] = {}
    
    async def initialize(self) -> None:
        """Initialize provider resources."""
        pass
    
    async def shutdown(self) -> None:
        """Clean up provider resources."""
        self.documents.clear()
        self.embeddings_cache.clear()
    
    async def health_check(self) -> bool:
        """Validate provider configuration."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_endpoint}/api/tags") as response:
                    return response.status == 200
        except Exception:
            return False
    
    def get_supported_methods(self) -> List[str]:
        """Get provider capabilities."""
        return [
            'chunk_text',
            'generate_embedding',
            'index_documents',
            'search_similar',
            'retrieve_context'
        ]
    
    def chunk_text(self, text: str, chunk_size: Optional[int] = None, overlap: Optional[int] = None) -> List[str]:
        """Split text into overlapping chunks."""
        size = chunk_size or self.chunk_size
        overlap = overlap or self.chunk_overlap
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + size
            chunk = text[start:end]
            
            # Try to break at sentence boundary
            if end < len(text):
                last_period = chunk.rfind('. ')
                if last_period > size * 0.5:  # Only if we're past halfway
                    chunk = chunk[:last_period + 1]
                    end = start + last_period + 1
            
            chunks.append(chunk.strip())
            start = end - overlap if end < len(text) else end
        
        return chunks
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text using Ollama."""
        # Check cache first
        text_hash = hashlib.md5(text.encode()).hexdigest()
        if text_hash in self.embeddings_cache:
            return self.embeddings_cache[text_hash]
        
        async with aiohttp.ClientSession() as session:
            payload = {
                'model': self.embedding_model,
                'prompt': text
            }
            
            async with session.post(
                f"{self.ollama_endpoint}/api/embeddings",
                json=payload
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    embedding = data.get('embedding', [])
                    
                    # Cache the embedding
                    self.embeddings_cache[text_hash] = embedding
                    return embedding
                else:
                    raise Exception(f"Failed to generate embedding: {response.status}")
    
    async def index_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Index multiple documents with their embeddings."""
        indexed_docs = []
        
        for doc in documents:
            doc_id = doc.get('id', hashlib.md5(doc['text'].encode()).hexdigest())
            text = doc['text']
            metadata = doc.get('metadata', {})
            
            # Generate embedding
            embedding = await self.generate_embedding(text)
            
            # Store document
            document = Document(
                id=doc_id,
                text=text,
                embedding=embedding,
                metadata=metadata
            )
            self.documents[doc_id] = document
            indexed_docs.append(doc_id)
        
        return {
            'indexed_count': len(indexed_docs),
            'document_ids': indexed_docs,
            'total_documents': len(self.documents)
        }
    
    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        
        dot_product = np.dot(v1, v2)
        norm_v1 = np.linalg.norm(v1)
        norm_v2 = np.linalg.norm(v2)
        
        if norm_v1 == 0 or norm_v2 == 0:
            return 0.0
        
        return float(dot_product / (norm_v1 * norm_v2))
    
    async def search_similar(self, query: str, top_k: int = 5, threshold: float = 0.0) -> List[Document]:
        """Search for similar documents using vector similarity."""
        # Generate query embedding
        query_embedding = await self.generate_embedding(query)
        
        # Calculate similarities
        similarities: List[Tuple[str, float]] = []
        
        for doc_id, document in self.documents.items():
            if document.embedding:
                similarity = self.cosine_similarity(query_embedding, document.embedding)
                if similarity >= threshold:
                    similarities.append((doc_id, similarity))
        
        # Sort by similarity score
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Return top-k documents
        results = []
        for doc_id, score in similarities[:top_k]:
            doc = self.documents[doc_id]
            doc.score = score
            results.append(doc)
        
        return results
    
    async def retrieve_context(self, query: str, top_k: int = 5, max_tokens: int = 2000) -> str:
        """Retrieve relevant context for a query."""
        similar_docs = await self.search_similar(query, top_k=top_k)
        
        context_parts = []
        total_tokens = 0
        
        for doc in similar_docs:
            # Rough token estimation (1 token ≈ 4 chars)
            doc_tokens = len(doc.text) // 4
            
            if total_tokens + doc_tokens <= max_tokens:
                context_parts.append(f"[Document {doc.id} (score: {doc.score:.3f})]")
                context_parts.append(doc.text)
                context_parts.append("")
                total_tokens += doc_tokens
            else:
                break
        
        return "\n".join(context_parts)
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle a JSON-RPC method call."""
        try:
            if method == 'chunk_text':
                text = params['text']
                chunks = self.chunk_text(
                    text,
                    params.get('chunk_size'),
                    params.get('overlap')
                )
                return {'chunks': chunks, 'count': len(chunks)}
            
            elif method == 'generate_embedding':
                text = params['text']
                embedding = await self.generate_embedding(text)
                return {'embedding': embedding, 'dimension': len(embedding)}
            
            elif method == 'index_documents':
                documents = params['documents']
                result = await self.index_documents(documents)
                return result
            
            elif method == 'search_similar':
                query = params['query']
                top_k = params.get('top_k', 5)
                threshold = params.get('threshold', 0.0)
                
                results = await self.search_similar(query, top_k, threshold)
                
                return {
                    'documents': [
                        {
                            'id': doc.id,
                            'text': doc.text,
                            'score': doc.score,
                            'metadata': doc.metadata
                        }
                        for doc in results
                    ],
                    'count': len(results)
                }
            
            elif method == 'retrieve_context':
                query = params['query']
                top_k = params.get('top_k', 5)
                max_tokens = params.get('max_tokens', 2000)
                
                context = await self.retrieve_context(query, top_k, max_tokens)
                
                return {'context': context, 'query': query}
            
            else:
                raise ValueError(f"Unsupported method: {method}")
        
        except Exception as e:
            raise ProviderError(
                message=f"Method {method} failed: {str(e)}",
                provider_id=self.provider_id,
                cause=e
            )