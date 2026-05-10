"""
Vector Store Service — Manages Qdrant collections for RAG.
Handles embedding generation, indexing, and similarity search
for coding guidelines, payer policies, and appeal templates.
"""

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)
from typing import Any
from uuid import uuid4

from src.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


# ── Collection Definitions ───────────────────────────────────────

COLLECTIONS = {
    "icd10_guidelines": {
        "description": "ICD-10-CM/PCS Official Guidelines for Coding and Reporting",
        "dimension": 1024,
        "distance": Distance.COSINE,
    },
    "cpt_guidelines": {
        "description": "CPT coding guidelines, conventions, and instructions",
        "dimension": 1024,
        "distance": Distance.COSINE,
    },
    "lcd_ncd_policies": {
        "description": "CMS Local and National Coverage Determinations",
        "dimension": 1024,
        "distance": Distance.COSINE,
    },
    "payer_policies": {
        "description": "Commercial payer billing and medical policies",
        "dimension": 1024,
        "distance": Distance.COSINE,
    },
    "appeal_templates": {
        "description": "Successful appeal letter templates by denial type",
        "dimension": 1024,
        "distance": Distance.COSINE,
    },
    "coding_clinics": {
        "description": "AHA Coding Clinic references and Q&A",
        "dimension": 1024,
        "distance": Distance.COSINE,
    },
}


class EmbeddingService:
    """Generate embeddings using Voyage AI or OpenAI."""

    def __init__(self):
        self.provider = settings.embedding_provider
        if self.provider == "voyageai":
            import voyageai
            self.client = voyageai.Client(api_key=settings.voyageai_api_key)
        else:
            import openai
            self.client = openai.OpenAI(api_key=settings.openai_api_key if hasattr(settings, 'openai_api_key') else "")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        if self.provider == "voyageai":
            result = self.client.embed(texts, model="voyage-large-2", input_type="document")
            return result.embeddings
        else:
            result = self.client.embeddings.create(input=texts, model="text-embedding-3-large")
            return [item.embedding for item in result.data]

    async def embed_query(self, text: str) -> list[float]:
        """Generate embedding for a search query."""
        if self.provider == "voyageai":
            result = self.client.embed([text], model="voyage-large-2", input_type="query")
            return result.embeddings[0]
        else:
            result = self.client.embeddings.create(input=[text], model="text-embedding-3-large")
            return result.data[0].embedding


class VectorStoreService:
    """Manages all vector store operations."""

    def __init__(self):
        self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
        self.embedder = EmbeddingService()

    async def initialize_collections(self):
        """Create all collections if they don't exist."""
        existing = {c.name for c in self.client.get_collections().collections}
        for name, config in COLLECTIONS.items():
            if name not in existing:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=config["dimension"],
                        distance=config["distance"],
                    ),
                )
                logger.info("collection_created", name=name)

    async def index_documents(
        self,
        collection: str,
        documents: list[dict],
        batch_size: int = 50,
    ):
        """
        Index documents into a collection.
        Each document should have: content, metadata (dict), and optional id.
        """
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            texts = [doc["content"] for doc in batch]
            embeddings = await self.embedder.embed(texts)

            points = [
                PointStruct(
                    id=doc.get("id", str(uuid4())),
                    vector=embedding,
                    payload={
                        "content": doc["content"],
                        **doc.get("metadata", {}),
                    },
                )
                for doc, embedding in zip(batch, embeddings)
            ]

            self.client.upsert(collection_name=collection, points=points)
            logger.info("documents_indexed", collection=collection, count=len(points), batch=i // batch_size + 1)

    async def search(
        self,
        collection: str,
        query: str,
        limit: int = 5,
        filters: dict | None = None,
        score_threshold: float = 0.5,
    ) -> list[dict]:
        """
        Semantic search over a collection.
        Returns matching documents with content and metadata.
        """
        query_embedding = await self.embedder.embed_query(query)

        # Build filter if provided
        qdrant_filter = None
        if filters:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filters.items()
            ]
            qdrant_filter = Filter(must=conditions)

        results = self.client.search(
            collection_name=collection,
            query_vector=query_embedding,
            limit=limit,
            query_filter=qdrant_filter,
            score_threshold=score_threshold,
        )

        return [
            {
                "id": str(hit.id),
                "content": hit.payload.get("content", ""),
                "score": hit.score,
                **{k: v for k, v in hit.payload.items() if k != "content"},
            }
            for hit in results
        ]

    async def delete_collection(self, collection: str):
        """Delete an entire collection."""
        self.client.delete_collection(collection_name=collection)
        logger.info("collection_deleted", name=collection)
