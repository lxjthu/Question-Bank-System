"""
BM25 稀疏检索索引

使用 rank_bm25 + jieba 中文分词。
索引序列化到 bm25.pkl，支持从磁盘加载，无需重新构建。

BM25 弥补向量检索的盲区：
  - 精确术语匹配（专有名词、法规编号、年份）
  - 低频词召回（高频上下文不会淹没低频专有名词）
"""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .chunker import Chunk

_INDEX_FILE = "bm25.pkl"


class BM25Index:
    def __init__(self, index_dir: Path):
        self._dir = Path(index_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._bm25 = None
        self._ids: list[str] = []
        self._payloads: dict[str, dict] = {}

    # ── 构建 ────────────────────────────────────────────────────

    def build(self, chunks: list[Chunk]) -> None:
        """从 Chunk 列表构建并持久化索引。"""
        import jieba
        from rank_bm25 import BM25Okapi

        print(f"[BM25] Building index for {len(chunks)} chunks ...")
        # 分词：context_header + text 拼接后用 jieba 切词
        corpus = [
            list(jieba.cut(f"{c.context_header} {c.text}"))
            for c in chunks
        ]
        self._bm25 = BM25Okapi(corpus)
        self._ids = [c.chunk_id for c in chunks]
        self._payloads = {c.chunk_id: _to_payload(c) for c in chunks}
        self._save()
        print(f"[BM25] Index saved to {self._dir / _INDEX_FILE}")

    # ── 检索 ────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 20,
        doc_ids: Optional[list[str]] = None,
        source_type: Optional[str] = None,
    ) -> list[dict]:
        """
        BM25 关键词检索。

        Args:
            query: 检索查询字符串
            top_k: 返回候选数量
            doc_ids: 限定文档范围（None = 全部）
            source_type: "textbook" | "slides" | None

        Returns:
            list of payload dicts, each with a "score" key.
        """
        import jieba

        if self._bm25 is None:
            self._load()

        tokens = list(jieba.cut(query))
        raw_scores = self._bm25.get_scores(tokens)

        # 带过滤的排序
        results = []
        for idx, score in enumerate(raw_scores):
            if score <= 0:
                continue
            chunk_id = self._ids[idx]
            payload = self._payloads.get(chunk_id, {})
            if doc_ids and payload.get("doc_id") not in doc_ids:
                continue
            if source_type and payload.get("source_type") != source_type:
                continue
            results.append({"score": float(score), **payload})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    # ── 持久化 ──────────────────────────────────────────────────

    def _save(self) -> None:
        with open(self._dir / _INDEX_FILE, "wb") as f:
            pickle.dump({
                "bm25":     self._bm25,
                "ids":      self._ids,
                "payloads": self._payloads,
            }, f)

    def _load(self) -> None:
        path = self._dir / _INDEX_FILE
        if not path.exists():
            raise FileNotFoundError(
                f"BM25 index not found at {path}. Run ingest first."
            )
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._bm25    = data["bm25"]
        self._ids     = data["ids"]
        self._payloads = data["payloads"]
        print(f"[BM25] Loaded index ({len(self._ids)} chunks)")

    @property
    def is_built(self) -> bool:
        return (self._dir / _INDEX_FILE).exists()


def _to_payload(c: Chunk) -> dict:
    return {
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
    }
