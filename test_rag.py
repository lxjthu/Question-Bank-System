"""
RAG Pipeline 测试脚本

步骤：
  1. 初始化 DB（创建 chunks 表）
  2. 摄入教材（农业经济学1.pdf_by_PaddleOCR.md）
  3. 摄入幻灯片（第三讲 OCR 结果）
  4. 测试混合检索
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rag_pipeline import db
from rag_pipeline.ingest import Ingestor
from rag_pipeline.retriever import HybridRetriever

SEP = "=" * 60

# ── Step 1: 初始化数据库 ────────────────────────────────────────
print(SEP)
print("Step 1: Init DB")
db.init_db()
print("  OK")

# ── Step 2 & 3: 摄入文档 ────────────────────────────────────────
print(SEP)
print("Step 2: Ingest documents (BGE model downloads on first run ~1.3GB)")
print()

ing = Ingestor()

# 教材
ing.ingest_textbook("农业经济学1")

# 第三讲幻灯片（已 OCR 完成）
slides_md = Path("test/林业经济学（双语）第三讲-木材价格与无市场价格的森林价值-2024_ocr/result.md")
if slides_md.exists():
    ing.ingest_slides(
        doc_id="林业经济学_第三讲",
        result_md=slides_md,
        doc_title="林业经济学（双语）第三讲",
    )
else:
    print(f"  [SKIP] {slides_md} not found")

# ── Step 4: 测试检索 ────────────────────────────────────────────
print()
print(SEP)
print("Step 3: Test retrieval")
print()

# 复用 Ingestor 已打开的组件，避免 Qdrant 锁冲突
emb      = ing._emb
vs       = ing._vs
bm25     = ing._bm25
retriever = HybridRetriever(vs, bm25, emb)

QUERIES = [
    ("木材价格的供求关系",        None,          None),           # 跨文档
    ("家庭承包经营的含义",        "农业经济学1",  "textbook"),     # 限教材
    ("林产品供给和需求模型",      "林业经济学_第三讲", "slides"),  # 限幻灯片
]

for query, doc_id, src_type in QUERIES:
    print(f"Query: 「{query}」")
    if doc_id:
        print(f"  Filter: doc_id={doc_id}  source_type={src_type}")

    results = retriever.search(
        query,
        top_n=3,
        doc_ids=[doc_id] if doc_id else None,
        source_type=src_type,
        expand_context=False,
    )

    if not results:
        print("  (no results)")
    for i, r in enumerate(results, 1):
        print(f"  [{i}] [{r['source_type']}] {r['section_name']}  score={r['score']:.4f}")
        print(f"       {r['text'][:120].replace(chr(10), ' ')}...")
    print()

print(SEP)
print("Done.")
