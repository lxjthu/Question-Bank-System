"""
文档摄入流水线（Ingestor）

职责：将 MD 文档 → 分块 → 向量化 → 存入 Qdrant + 重建 BM25 索引

支持：
  ingest_textbook(doc_id, md_file)   — 摄入教材 MD（来自 PDF OCR）
  ingest_slides(doc_id, result_md)   — 摄入单个幻灯片结果 MD
  ingest_slides_dir(ocr_root)        — 扫描目录，批量摄入所有 *_ocr/result.md
  delete_doc(doc_id)                 — 删除某文档的全部向量和 BM25 记录

每次摄入后自动重建 BM25（rank_bm25 不支持增量更新）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .chunker import Chunk, TextbookChunker, SlidesChunker
from .config import (
    BM25_PATH, EMBEDDING_MODEL, MD_FILE, QDRANT_PATH,
)
from . import db


def _get_components(embedding_model: str = EMBEDDING_MODEL):
    """懒加载重量级组件（首次调用时下载模型）。"""
    from .embedder import Embedder
    from .vector_store import VectorStore
    from .bm25_index import BM25Index

    emb = Embedder(model_name=embedding_model)
    vs  = VectorStore(QDRANT_PATH)
    vs.ensure_collection(emb.dim)
    bm25 = BM25Index(BM25_PATH)
    return emb, vs, bm25


class Ingestor:
    """
    统一摄入入口。
    懒加载模型，首次调用 ingest_* 时才初始化。

    支持传入外部共享组件（emb/vs/bm25），避免与 HybridRetriever
    同时持有两个 QdrantClient 导致本地文件锁冲突。
    """

    def __init__(self, embedding_model: str = EMBEDDING_MODEL, *,
                 emb=None, vs=None, bm25=None):
        self._model_name = embedding_model
        self._emb  = emb
        self._vs   = vs
        self._bm25 = bm25

    def _init(self):
        if self._emb is None:
            self._emb, self._vs, self._bm25 = _get_components(self._model_name)

    # ── 公开接口 ─────────────────────────────────────────────────────────────

    def ingest_textbook(
        self,
        doc_id: str,
        md_file: Optional[Path] = None,
    ) -> int:
        """
        摄入教材 MD 文件。

        Args:
            doc_id:  文档标识，如 "农业经济学1"
            md_file: MD 路径（默认使用 config.MD_FILE）

        Returns:
            摄入的 chunk 数量
        """
        self._init()
        from .parser import parse_md

        md_file = Path(md_file or MD_FILE)
        print(f"\n[Ingest] Textbook: {doc_id}  ({md_file.name})")

        chapters = parse_md(md_file)
        chunker  = TextbookChunker(doc_id)
        chunks   = chunker.chunk_all(chapters)
        print(f"  Chunks: {len(chunks)}")

        return self._store(doc_id, chunks)

    def ingest_slides(
        self,
        doc_id: str,
        result_md: Path,
        doc_title: str = "",
    ) -> int:
        """
        摄入单个幻灯片 OCR 结果（result.md）。

        Args:
            doc_id:     文档标识，如 "林业经济学_第三讲"
            result_md:  pptx_ocr 输出的 result.md 路径
            doc_title:  显示标题（默认使用 doc_id）

        Returns:
            摄入的 chunk 数量
        """
        self._init()
        result_md = Path(result_md)
        print(f"\n[Ingest] Slides: {doc_id}  ({result_md.name})")

        chunker = SlidesChunker(doc_id, doc_title=doc_title or doc_id)
        chunks  = chunker.chunk_file(result_md)
        print(f"  Chunks: {len(chunks)}")

        return self._store(doc_id, chunks)

    def ingest_slides_dir(self, ocr_root: Path) -> dict[str, int]:
        """
        扫描目录，批量摄入所有 *_ocr/result.md 文件。

        Args:
            ocr_root: 包含 *_ocr/ 子目录的根目录（通常是 test/）

        Returns:
            dict {doc_id: chunk_count}
        """
        self._init()
        ocr_root = Path(ocr_root)
        results: dict[str, int] = {}

        md_files = sorted(ocr_root.glob("*_ocr/result.md"))
        if not md_files:
            print(f"[Ingest] No *_ocr/result.md found in {ocr_root}")
            return results

        print(f"[Ingest] Found {len(md_files)} slide OCR result(s)")
        for md_path in md_files:
            # *_ocr 目录名去掉 _ocr 后缀作为 doc_id
            stem = md_path.parent.name[:-4]  # remove "_ocr"
            doc_id = _normalize_doc_id(stem)
            n = self.ingest_slides(doc_id, md_path, doc_title=stem)
            results[doc_id] = n

        return results

    def delete_doc(self, doc_id: str) -> None:
        """删除某文档的全部向量和 chunk 记录，并重建 BM25。"""
        self._init()
        print(f"\n[Ingest] Deleting doc_id='{doc_id}' ...")
        self._vs.delete_doc(doc_id)
        db.delete_chunks(doc_id)
        self._rebuild_bm25()
        print(f"[Ingest] Deleted '{doc_id}'")

    # ── 内部方法 ─────────────────────────────────────────────────────────────

    def _store(self, doc_id: str, chunks: list[Chunk]) -> int:
        if not chunks:
            print("  [WARN] No chunks generated, skipping.")
            return 0

        # 删除旧数据（幂等）
        self._vs.delete_doc(doc_id)
        db.delete_chunks(doc_id)

        # 向量化
        print("  Embedding ...")
        vecs = self._emb.embed_chunks(chunks)

        # 存入 Qdrant
        print("  Upserting to Qdrant ...")
        self._vs.upsert(chunks, vecs)

        # 存入 SQLite（供 BM25 重建使用）
        db.save_chunks(chunks)

        # 重建 BM25
        self._rebuild_bm25()

        n = len(chunks)
        print(f"  Done: {n} chunks stored  (total: {self._vs.count()} in Qdrant)")
        return n

    def _rebuild_bm25(self) -> None:
        """从 SQLite 加载全部 chunks，重建 BM25 索引。"""
        print("  Rebuilding BM25 index ...")
        rows = db.load_all_chunks()
        chunks = [_row_to_chunk(r) for r in rows]
        if chunks:
            self._bm25.build(chunks)
        else:
            print("  [WARN] No chunks in DB, BM25 index is empty.")


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _normalize_doc_id(stem: str) -> str:
    """
    将文件名 stem 转为简短的 doc_id。
    例：林业经济学（双语）第三讲-木材价格... → 林业经济学_第三讲
    保留讲次标识，去掉日期和过长的副标题。
    """
    import re
    # 提取"第X讲"或"第X章"等关键标识
    m = re.search(r'第[一二三四五六七八九十\d]+[讲章节]', stem)
    prefix = re.split(r'[（\-—_]', stem)[0].strip()  # 取第一个分隔符前的部分
    if m:
        return f"{prefix}_{m.group()}"
    # 截断过长名称
    return stem[:30] if len(stem) > 30 else stem


def _row_to_chunk(row) -> Chunk:
    from .chunker import Chunk
    return Chunk(
        doc_id=row["doc_id"],
        source_type=row["source_type"],
        chunk_id=row["chunk_id"],
        level=row["level"],
        chapter_num=row["chapter_num"],
        chapter_name=row["chapter_name"],
        section_num=row["section_num"],
        section_name=row["section_name"],
        text=row["text"],
        context_header=row["context_header"],
        prev_id=row["prev_id"],
        next_id=row["next_id"],
    )
