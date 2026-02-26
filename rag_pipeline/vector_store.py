"""
Qdrant 向量库封装（本地文件模式，无需 Docker）

集合名：textbook_chunks
向量维度：1024（BGE-large-zh）
距离度量：COSINE

支持按 doc_id / source_type / chapter_num 过滤检索。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .chunker import Chunk

_COLLECTION = "textbook_chunks"


class VectorStore:
    def __init__(self, storage_path: Path):
        from qdrant_client import QdrantClient

        storage_path = Path(storage_path)
        storage_path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=str(storage_path))

    def ensure_collection(self, dim: int) -> None:
        """如果集合不存在则创建。"""
        from qdrant_client.models import Distance, VectorParams

        existing = {c.name for c in self.client.get_collections().collections}
        if _COLLECTION not in existing:
            self.client.create_collection(
                collection_name=_COLLECTION,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            print(f"[VectorStore] Created collection '{_COLLECTION}' (dim={dim})")
        else:
            print(f"[VectorStore] Collection '{_COLLECTION}' exists "
                  f"({self.count()} vectors)")

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """批量写入（已存在则覆盖）。"""
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(
                id=_chunk_hash(c.chunk_id),
                vector=vec,
                payload={
                    "doc_id":         c.doc_id,
                    "source_type":    c.source_type,
                    "chunk_id":       c.chunk_id,
                    "level":          c.level,
                    "chapter_num":    c.chapter_num,
                    "chapter_name":   c.chapter_name,
                    "section_num":    c.section_num,
                    "section_name":   c.section_name,
                    "text":           c.text,
                    "context_header": c.context_header,
                    "prev_id":        c.prev_id,
                    "next_id":        c.next_id,
                },
            )
            for c, vec in zip(chunks, vectors)
        ]
        # 分批写入，避免单次请求过大
        batch = 256
        for i in range(0, len(points), batch):
            self.client.upsert(collection_name=_COLLECTION, points=points[i:i+batch])

    def search(
        self,
        query_vector: list[float],
        top_k: int = 20,
        doc_ids: Optional[list[str]] = None,
        source_type: Optional[str] = None,
        chapter_num: Optional[int] = None,
    ) -> list[dict]:
        """
        近似最近邻检索，支持元数据过滤。

        Returns:
            list of payload dicts, each with an extra "score" key.
        """
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

        must: list = []
        if doc_ids:
            must.append(FieldCondition(
                key="doc_id",
                match=MatchAny(any=doc_ids) if len(doc_ids) > 1
                      else MatchValue(value=doc_ids[0]),
            ))
        if source_type:
            must.append(FieldCondition(
                key="source_type", match=MatchValue(value=source_type)
            ))
        if chapter_num is not None:
            must.append(FieldCondition(
                key="chapter_num", match=MatchValue(value=chapter_num)
            ))

        query_filter = Filter(must=must) if must else None
        results = self.client.query_points(
            collection_name=_COLLECTION,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        return [{"score": r.score, **r.payload} for r in results.points]

    def get_by_chunk_id(self, chunk_id: str) -> Optional[dict]:
        """按 chunk_id 精确取回 payload（用于上下文扩展）。"""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        res, _ = self.client.scroll(
            collection_name=_COLLECTION,
            scroll_filter=Filter(must=[
                FieldCondition(key="chunk_id", match=MatchValue(value=chunk_id))
            ]),
            limit=1,
            with_payload=True,
        )
        return res[0].payload if res else None

    def delete_doc(self, doc_id: str) -> None:
        """删除某文档的全部向量。"""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        self.client.delete(
            collection_name=_COLLECTION,
            points_selector=Filter(must=[
                FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
            ]),
        )
        print(f"[VectorStore] Deleted vectors for doc_id='{doc_id}'")

    def count(self) -> int:
        return self.client.count(collection_name=_COLLECTION).count


def _chunk_hash(chunk_id: str) -> int:
    """将 chunk_id 字符串映射为 Qdrant 需要的正整数 ID。"""
    return abs(hash(chunk_id)) % (2 ** 53)
