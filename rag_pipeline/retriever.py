"""
混合检索器（HybridRetriever）

流程：
  稠密检索（向量）Top-20
      ↓
  稀疏检索（BM25）Top-20        ← 弥补向量检索的精确匹配盲区
      ↓
  RRF 倒数排名融合 → Top-20
      ↓
  上下文扩展（取 prev/next chunk）
      ↓
  BGE-Reranker 精排 → Top-N     ← 可选，精度更高但慢
      ↓
  返回最终 Top-N chunks

RRF 公式：score(d) = Σ weight_i / (k + rank_i(d))
  k=60 是经验值，防止排名靠前的文档得分过高。
"""
from __future__ import annotations

from typing import Optional

from .config import DENSE_TOP_K, SPARSE_TOP_K, RRF_K, RERANK_TOP_N


class HybridRetriever:
    """
    Args:
        vector_store: VectorStore 实例
        bm25_index:   BM25Index 实例
        embedder:     Embedder 实例
        reranker:     BGEReranker 实例（可选）
        dense_weight: RRF 中向量检索的权重（默认 0.7）
        sparse_weight: RRF 中 BM25 检索的权重（默认 0.3）
    """

    def __init__(
        self,
        vector_store,
        bm25_index,
        embedder,
        reranker=None,
        dense_weight: float = 0.7,
        sparse_weight: float = 0.3,
    ):
        self.vs     = vector_store
        self.bm25   = bm25_index
        self.emb    = embedder
        self.reranker = reranker
        self.dw     = dense_weight
        self.sw     = sparse_weight

    def search(
        self,
        query: str,
        top_n: int = RERANK_TOP_N,
        doc_ids: Optional[list[str]] = None,
        source_type: Optional[str] = None,
        chapter_num: Optional[int] = None,
        expand_context: bool = True,
    ) -> list[dict]:
        """
        执行混合检索，返回最终 Top-N chunks。

        Args:
            query:          检索查询
            top_n:          最终返回数量
            doc_ids:        限定文档范围
            source_type:    "textbook" | "slides" | None（不限）
            chapter_num:    限定章节（仅教材有意义）
            expand_context: 是否自动补充前后相邻 chunk

        Returns:
            list of chunk payload dicts，含 "score" 字段
        """
        # 1. 稠密检索
        q_vec = self.emb.embed_query(query)
        dense = self.vs.search(
            q_vec, top_k=DENSE_TOP_K,
            doc_ids=doc_ids, source_type=source_type, chapter_num=chapter_num,
        )

        # 2. 稀疏检索（BM25）
        sparse = self.bm25.search(
            query, top_k=SPARSE_TOP_K,
            doc_ids=doc_ids, source_type=source_type,
        )

        # 3. RRF 融合
        fused = _rrf(dense, sparse, k=RRF_K,
                     dw=self.dw, sw=self.sw)

        # 4. 上下文扩展：取 prev/next chunk 补全语义
        candidates = fused[:top_n * 3]  # 给 reranker 更多候选
        if expand_context:
            candidates = self._expand(candidates)

        # 5. Reranker 精排
        if self.reranker:
            return self.reranker.rerank(query, candidates, top_n=top_n)

        return candidates[:top_n]

    def _expand(self, chunks: list[dict]) -> list[dict]:
        """
        对每个命中 chunk，尝试获取其 prev/next 邻居，
        合并后去重，保持原始顺序在前。
        """
        seen = {c["chunk_id"] for c in chunks}
        extra = []
        for c in chunks:
            for neighbor_id in (c.get("prev_id"), c.get("next_id")):
                if neighbor_id and neighbor_id not in seen:
                    payload = self.vs.get_by_chunk_id(neighbor_id)
                    if payload:
                        payload["score"] = c["score"] * 0.9  # 邻居得分略低
                        extra.append(payload)
                        seen.add(neighbor_id)
        return chunks + extra


# ── RRF 融合 ──────────────────────────────────────────────────────────────────

def _rrf(
    dense: list[dict],
    sparse: list[dict],
    k: int = 60,
    dw: float = 0.7,
    sw: float = 0.3,
) -> list[dict]:
    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}

    for rank, item in enumerate(dense, 1):
        cid = item["chunk_id"]
        scores[cid]   = scores.get(cid, 0) + dw / (k + rank)
        payloads[cid] = item

    for rank, item in enumerate(sparse, 1):
        cid = item["chunk_id"]
        scores[cid]   = scores.get(cid, 0) + sw / (k + rank)
        if cid not in payloads:
            payloads[cid] = item

    ordered = sorted(scores, key=scores.__getitem__, reverse=True)
    return [{**payloads[cid], "score": scores[cid]} for cid in ordered]


# ── BGE Reranker（可选） ──────────────────────────────────────────────────────

class BGEReranker:
    """
    Cross-Encoder 精排，精度高但比 Bi-Encoder 慢。
    模型：BAAI/bge-reranker-v2-m3（约 1.1 GB）
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        use_fp16: bool = True,
        hf_mirror: bool = True,
    ):
        import os
        if hf_mirror and not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

        from FlagEmbedding import FlagReranker
        print(f"[Reranker] Loading {model_name} ...")
        self.model = FlagReranker(model_name, use_fp16=use_fp16)
        print("[Reranker] Ready")

    def rerank(self, query: str, chunks: list[dict], top_n: int = 5) -> list[dict]:
        if not chunks:
            return []
        pairs = [(query, c["text"]) for c in chunks]
        scores = self.model.compute_score(pairs, normalize=True)
        ranked = sorted(
            zip(scores, chunks),
            key=lambda x: x[0],
            reverse=True,
        )
        return [{**chunk, "score": float(score)} for score, chunk in ranked[:top_n]]
