"""Redis vector storage adapter for Gleitzeit RAG."""

import json
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
import hashlib
import logging

from redis import Redis
from redis.commands.search.field import VectorField, TextField, TagField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

logger = logging.getLogger(__name__)


class RedisVectorAdapter:
    """
    Vector storage adapter using Redis with RediSearch module.
    
    Requires Redis Stack or Redis with RediSearch module installed.
    """
    
    def __init__(
        self,
        redis_client: Redis,
        index_name: str = "gleitzeit_vectors",
        embedding_dim: int = 768,
        distance_metric: str = "COSINE",
        index_type: str = "HNSW"
    ):
        """
        Initialize Redis vector adapter.
        
        Args:
            redis_client: Redis client instance
            index_name: Name for the vector index
            embedding_dim: Dimension of embeddings
            distance_metric: COSINE, L2, or IP (inner product)
            index_type: HNSW or FLAT
        """
        self.redis = redis_client
        self.index_name = index_name
        self.embedding_dim = embedding_dim
        self.distance_metric = distance_metric
        self.index_type = index_type
        self.doc_prefix = f"{index_name}:doc:"
        
    async def initialize(self) -> None:
        """Create vector index in Redis."""
        try:
            # Check if index exists
            self.redis.ft(self.index_name).info()
            logger.info(f"Index {self.index_name} already exists")
        except:
            # Create new index
            logger.info(f"Creating index {self.index_name}")
            
            # Define schema
            schema = [
                TextField("text"),
                TextField("chunk_id"),
                TagField("source"),
                TagField("doc_type"),
                VectorField(
                    "embedding",
                    self.index_type,
                    {
                        "TYPE": "FLOAT32",
                        "DIM": self.embedding_dim,
                        "DISTANCE_METRIC": self.distance_metric,
                        # HNSW specific parameters
                        "INITIAL_CAP": 10000,
                        "M": 16,  # Number of neighbors
                        "EF_CONSTRUCTION": 200,  # Build-time accuracy
                        "EF_RUNTIME": 10,  # Query-time accuracy
                    } if self.index_type == "HNSW" else {
                        "TYPE": "FLOAT32",
                        "DIM": self.embedding_dim,
                        "DISTANCE_METRIC": self.distance_metric,
                    }
                ),
                TextField("metadata", weight=0.1),  # JSON metadata
            ]
            
            # Create index
            self.redis.ft(self.index_name).create_index(
                fields=schema,
                definition=IndexDefinition(
                    prefix=[self.doc_prefix],
                    index_type=IndexType.HASH
                )
            )
            
            logger.info(f"Index {self.index_name} created successfully")
    
    async def store_embedding(
        self,
        doc_id: str,
        text: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Store document with embedding in Redis.
        
        Args:
            doc_id: Unique document identifier
            text: Document text
            embedding: Vector embedding
            metadata: Additional metadata
            
        Returns:
            Success status
        """
        try:
            # Prepare embedding as bytes
            embedding_bytes = np.array(embedding, dtype=np.float32).tobytes()
            
            # Prepare metadata
            meta = metadata or {}
            chunk_id = meta.get("chunk_id", doc_id)
            source = meta.get("source", "unknown")
            doc_type = meta.get("doc_type", "text")
            
            # Store in Redis
            key = f"{self.doc_prefix}{doc_id}"
            self.redis.hset(
                key,
                mapping={
                    "text": text,
                    "chunk_id": chunk_id,
                    "source": source,
                    "doc_type": doc_type,
                    "embedding": embedding_bytes,
                    "metadata": json.dumps(meta)
                }
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to store embedding: {e}")
            return False
    
    async def search_similar(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        Search for similar documents using vector similarity.
        
        Args:
            query_embedding: Query vector
            top_k: Number of results to return
            filters: Optional filters (source, doc_type, etc.)
            
        Returns:
            List of (doc_id, score, document) tuples
        """
        try:
            # Prepare query embedding
            query_bytes = np.array(query_embedding, dtype=np.float32).tobytes()
            
            # Build filter string if filters provided
            filter_str = ""
            if filters:
                filter_parts = []
                if "source" in filters:
                    filter_parts.append(f"@source:{{{filters['source']}}}")
                if "doc_type" in filters:
                    filter_parts.append(f"@doc_type:{{{filters['doc_type']}}}")
                filter_str = " ".join(filter_parts)
            
            # Build query
            base_query = f"{filter_str} *" if filter_str else "*"
            query = (
                Query(f"{base_query}=>[KNN {top_k} @embedding $vec AS score]")
                .sort_by("score")
                .return_fields("text", "chunk_id", "source", "metadata", "score")
                .dialect(2)
            )
            
            # Execute search
            results = self.redis.ft(self.index_name).search(
                query,
                query_params={"vec": query_bytes}
            )
            
            # Parse results
            output = []
            for doc in results.docs:
                doc_id = doc.id.replace(self.doc_prefix, "")
                score = float(doc.score)
                
                # Parse document fields
                document = {
                    "text": doc.text,
                    "chunk_id": doc.chunk_id,
                    "source": doc.source,
                    "metadata": json.loads(doc.metadata) if hasattr(doc, 'metadata') else {}
                }
                
                output.append((doc_id, score, document))
            
            return output
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: List[float],
        top_k: int = 5,
        text_weight: float = 0.3,
        vector_weight: float = 0.7
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        Hybrid search combining text and vector similarity.
        
        Args:
            query_text: Text query
            query_embedding: Query vector
            top_k: Number of results
            text_weight: Weight for text search (0-1)
            vector_weight: Weight for vector search (0-1)
            
        Returns:
            List of (doc_id, score, document) tuples
        """
        # Vector search
        vector_results = await self.search_similar(query_embedding, top_k * 2)
        
        # Text search
        text_query = Query(query_text).return_fields("text", "chunk_id", "metadata")
        text_results = self.redis.ft(self.index_name).search(text_query)
        
        # Combine and re-rank results
        combined_scores = {}
        all_docs = {}
        
        # Add vector results
        for doc_id, score, doc in vector_results:
            combined_scores[doc_id] = vector_weight * (1 - score)  # Convert distance to similarity
            all_docs[doc_id] = doc
        
        # Add text results
        for doc in text_results.docs:
            doc_id = doc.id.replace(self.doc_prefix, "")
            text_score = float(doc.score) if hasattr(doc, 'score') else 0.5
            
            if doc_id in combined_scores:
                combined_scores[doc_id] += text_weight * text_score
            else:
                combined_scores[doc_id] = text_weight * text_score
                all_docs[doc_id] = {
                    "text": doc.text,
                    "chunk_id": doc.chunk_id if hasattr(doc, 'chunk_id') else doc_id,
                    "metadata": json.loads(doc.metadata) if hasattr(doc, 'metadata') else {}
                }
        
        # Sort by combined score
        sorted_results = sorted(
            combined_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_k]
        
        return [(doc_id, score, all_docs[doc_id]) for doc_id, score in sorted_results]
    
    async def delete_embedding(self, doc_id: str) -> bool:
        """Delete a document and its embedding."""
        try:
            key = f"{self.doc_prefix}{doc_id}"
            return bool(self.redis.delete(key))
        except Exception as e:
            logger.error(f"Failed to delete embedding: {e}")
            return False
    
    async def update_metadata(
        self,
        doc_id: str,
        metadata_updates: Dict[str, Any]
    ) -> bool:
        """Update metadata for a document."""
        try:
            key = f"{self.doc_prefix}{doc_id}"
            
            # Get existing metadata
            existing = self.redis.hget(key, "metadata")
            if not existing:
                return False
            
            # Update metadata
            meta = json.loads(existing)
            meta.update(metadata_updates)
            
            # Store updated metadata
            self.redis.hset(key, "metadata", json.dumps(meta))
            return True
            
        except Exception as e:
            logger.error(f"Failed to update metadata: {e}")
            return False
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get index statistics."""
        try:
            info = self.redis.ft(self.index_name).info()
            
            return {
                "index_name": self.index_name,
                "num_docs": info["num_docs"],
                "num_terms": info["num_terms"],
                "max_doc_id": info["max_doc_id"],
                "num_records": info["num_records"],
                "inverted_size_mb": info["inverted_sz_mb"],
                "vector_index_size_mb": info.get("vector_index_sz_mb", 0),
                "total_indexing_time": info["total_indexing_time"],
                "indexing": info["indexing"],
                "percent_indexed": info["percent_indexed"]
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
    
    async def clear_all(self) -> bool:
        """Drop the entire index."""
        try:
            self.redis.ft(self.index_name).dropindex(delete_documents=True)
            logger.info(f"Index {self.index_name} dropped")
            return True
        except Exception as e:
            logger.error(f"Failed to clear index: {e}")
            return False


# Example usage
async def example_usage():
    """Example of using Redis vector adapter."""
    import redis.asyncio as redis
    
    # Connect to Redis
    client = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    # Create adapter
    adapter = RedisVectorAdapter(
        redis_client=client,
        index_name="rag_documents",
        embedding_dim=768,
        distance_metric="COSINE"
    )
    
    # Initialize index
    await adapter.initialize()
    
    # Store document with embedding
    await adapter.store_embedding(
        doc_id="doc1",
        text="Gleitzeit is a workflow orchestration system.",
        embedding=[0.1] * 768,  # Dummy embedding
        metadata={"source": "docs", "doc_type": "text"}
    )
    
    # Search similar documents
    results = await adapter.search_similar(
        query_embedding=[0.1] * 768,
        top_k=5,
        filters={"source": "docs"}
    )
    
    # Hybrid search
    hybrid_results = await adapter.hybrid_search(
        query_text="workflow orchestration",
        query_embedding=[0.1] * 768,
        top_k=5
    )
    
    # Get statistics
    stats = await adapter.get_statistics()
    print(f"Index stats: {stats}")
    
    await client.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())