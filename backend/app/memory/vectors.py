"""Qdrant wrapper. Payloads only hold ids + filters (never the memory text), so the vector DB
contains no readable personal data — text lives in Postgres (encrypted when sensitive)."""
from __future__ import annotations

from pathlib import Path

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from app.core.config import settings

MEMORIES = "astra_memories"
DOCUMENTS = "astra_documents"
CONVERSATIONS = "astra_conversations"
ALL = (MEMORIES, DOCUMENTS, CONVERSATIONS)


class VectorStore:
    def __init__(self):
        self.client: AsyncQdrantClient | None = None

    async def init(self, location: str | None = None) -> None:
        if location:  # e.g. ":memory:" for tests
            self.client = AsyncQdrantClient(location=location)
        elif settings.QDRANT_URL:
            self.client = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
        else:
            Path(settings.qdrant_path).mkdir(parents=True, exist_ok=True)
            self.client = AsyncQdrantClient(path=settings.qdrant_path)
        for name in ALL:
            if not await self.client.collection_exists(name):
                await self.client.create_collection(
                    name, vectors_config=qm.VectorParams(size=settings.EMBEDDING_DIM, distance=qm.Distance.COSINE)
                )
                if settings.QDRANT_URL:
                    await self.client.create_payload_index(name, "user_id", qm.PayloadSchemaType.KEYWORD)

    async def close(self) -> None:
        if self.client:
            await self.client.close()

    async def upsert(self, collection: str, point_id: str, vector: list[float], payload: dict) -> None:
        await self.client.upsert(collection, points=[qm.PointStruct(id=point_id, vector=vector, payload=payload)])

    async def upsert_many(self, collection: str, items: list[tuple[str, list[float], dict]]) -> None:
        if items:
            await self.client.upsert(collection, points=[qm.PointStruct(id=i, vector=v, payload=p) for i, v, p in items])

    async def search(self, collection: str, vector: list[float], user_id: str, limit: int = 10, must: dict | None = None):
        conds = [qm.FieldCondition(key="user_id", match=qm.MatchValue(value=user_id))]
        for k, v in (must or {}).items():
            conds.append(qm.FieldCondition(key=k, match=qm.MatchValue(value=v)))
        res = await self.client.query_points(
            collection, query=vector, query_filter=qm.Filter(must=conds), limit=limit, with_payload=True
        )
        return [(str(p.id), p.score, p.payload or {}) for p in res.points]

    async def delete(self, collection: str, ids: list[str]) -> None:
        if ids:
            await self.client.delete(collection, points_selector=qm.PointIdsList(points=ids))

    async def delete_where(self, collection: str, user_id: str, key: str | None = None, value: str | None = None) -> None:
        conds = [qm.FieldCondition(key="user_id", match=qm.MatchValue(value=user_id))]
        if key:
            conds.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=value)))
        await self.client.delete(collection, points_selector=qm.FilterSelector(filter=qm.Filter(must=conds)))


vectors = VectorStore()
