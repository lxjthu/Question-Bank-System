# RAG 开发进度与待办事项

> 更新时间：2026-02-25（Flask 集成已完成，更新于 2026-02-25）

---

## 当前状态

### ✅ 已完成

#### 1. OCR 模块（pptx_ocr/）
- PPTX → PDF（win32com）→ 分 10 页 chunk → Layout Parsing API → Markdown
- API: `https://28eav445b8dbxdo2.aistudio-app.com/layout-parsing`（token 在 .env）
- 自动重试（3次，503/超时均可恢复）
- 输出：`test/<文件名>_ocr/result.md` + `images/`
- 测试脚本：`test_pptx_ocr.py`

#### 2. RAG 基础模块（rag_pipeline/ 下新增）

| 文件 | 内容 |
|------|------|
| `chunker.py` | `TextbookChunker`（教材，章→节→段）+ `SlidesChunker`（幻灯片，页→段） |
| `embedder.py` | BGE-large-zh-v1.5，优先从 `models/` 本地加载 |
| `vector_store.py` | Qdrant 本地文件模式，支持 doc_id/source_type 过滤 |
| `bm25_index.py` | rank_bm25 + jieba，序列化到 `rag_pipeline/bm25_index/bm25.pkl` |
| `retriever.py` | 混合检索（稠密+稀疏）→ RRF 融合 → 上下文扩展 → BGEReranker（可选） |
| `ingest.py` | 摄入流水线，教材/幻灯片区分处理，写入 Qdrant + SQLite + 重建 BM25 |

#### 3. 数据库扩展（db.py）
- 新增 `chunks` 表（chunk_id, doc_id, source_type, text, context_header 等）
- 新增 `save_chunks()` / `load_all_chunks()` / `delete_chunks()` 函数

#### 4. 配置（config.py）
```python
QDRANT_PATH     = BASE_DIR / "qdrant_storage"
BM25_PATH       = BASE_DIR / "bm25_index"
EMBEDDING_MODEL = "BAAI/bge-large-zh-v1.5"
RERANKER_MODEL  = "BAAI/bge-reranker-v2-m3"
CHUNK_MIN_CHARS = 80
CHUNK_MAX_CHARS = 600
DENSE_TOP_K  = 20
SPARSE_TOP_K = 20
RRF_K        = 60
RERANK_TOP_N = 5
```

---

## 🔄 进行中（后台任务，新会话开始时检查状态）

### 1. BGE 模型下载
```bash
# 检查是否完成
dir models\BAAI\bge-large-zh-v1.5\pytorch_model.bin
# 完成标志：文件大小约 1.21 GB（1,299,xxx KB）
```
- 下载目标：`models/BAAI/bge-large-zh-v1.5/`（ModelScope 镜像）
- 完成后 embedder.py 自动从本地加载，无需联网

### 2. 批量 OCR（test_pptx_ocr.py --all）
```bash
# 检查哪些已完成
dir test\*_ocr\result.md
```
- 6 个 PPTX 文件，第 1 个（第三讲）已完成
- 第 2 个（第二讲，166页）正在处理中
- 完成后所有幻灯片的 result.md 在 `test/*_ocr/` 下

---

## 📋 下一步要做的事

### Step 1：确认后台任务完成
```bash
# 确认 BGE 模型
python -c "from rag_pipeline.embedder import Embedder; Embedder()"

# 确认 OCR 完成
dir test\*_ocr\result.md
```

### Step 2：运行摄入测试
```bash
venv\Scripts\python test_rag.py
```
`test_rag.py` 会：
1. 初始化 DB（chunks 表）
2. 摄入教材（农业经济学1.pdf_by_PaddleOCR.md）
3. 摄入第三讲幻灯片
4. 跑 3 个测试查询，验证混合检索结果

### Step 3：批量摄入所有幻灯片
OCR 全部完成后运行：
```python
from rag_pipeline.ingest import Ingestor
ing = Ingestor()
ing.ingest_textbook("农业经济学1")
ing.ingest_slides_dir("test/")   # 自动扫描所有 *_ocr/result.md
```

### Step 4：评估检索质量
- 目标：Recall@5 > 0.8，MRR > 0.7
- 手动构造 10~20 个 query-chunk 标注对
- 调参：dense/sparse 权重、RRF k 值

### Step 5：接入 BGE Reranker（可选，精度更高）
```bash
# 同样用 ModelScope 下载
python -c "
from modelscope import snapshot_download
snapshot_download('BAAI/bge-reranker-v2-m3', cache_dir='models')
"
```
然后在 retriever 里启用：
```python
from rag_pipeline.retriever import HybridRetriever, BGEReranker
reranker = BGEReranker()
retriever = HybridRetriever(vs, bm25, emb, reranker=reranker)
```

### Step 6：接入出题（修改 question_generator.py）
将现有的"全文注入"改为"RAG 检索注入"：
```python
# 旧方式（每章全文 ~15000 字）
context = chapter['content']

# 新方式（检索相关段落 ~1500 字）
chunks = retriever.search(concept_name, top_n=5, doc_ids=[doc_id])
context = build_context(chunks)   # 拼接成结构化 prompt
```

### Step 7：菜单集成（main.py）
在现有菜单中新增：
- `[8] 摄入文档到向量库`
- `[9] 检索测试`
- `[10] RAG 模式出题`

---

## 文件结构速查

```
试卷生成/
├── pptx_ocr/              # OCR 模块
│   ├── api_client.py      # Layout Parsing API 客户端
│   ├── converter.py       # PPTX → PDF（win32com）
│   ├── pdf_splitter.py    # PDF → 10页 chunks（pymupdf）
│   └── pipeline.py        # 主流程
├── rag_pipeline/          # RAG 模块
│   ├── chunker.py         # 教材/幻灯片分块（新增）
│   ├── embedder.py        # BGE 嵌入（新增）
│   ├── vector_store.py    # Qdrant（新增）
│   ├── bm25_index.py      # BM25（新增）
│   ├── retriever.py       # 混合检索（新增）
│   ├── ingest.py          # 摄入流水线（新增）
│   ├── db.py              # 含 chunks 表（已更新）
│   ├── config.py          # 含 RAG 配置（已更新）
│   ├── qdrant_storage/    # Qdrant 数据（运行后生成）
│   ├── bm25_index/        # BM25 索引（运行后生成）
│   └── requirements_rag.txt
├── models/
│   └── BAAI/bge-large-zh-v1.5/   # BGE 模型（下载中）
├── test/
│   ├── *.pptx             # 林业经济学讲义
│   └── *_ocr/result.md   # OCR 输出（陆续生成）
├── test_rag.py            # RAG 测试脚本
├── test_pptx_ocr.py       # OCR 测试脚本
└── .env                   # API keys（DEEPSEEK_TOKEN、PADDLEOCR_TOKEN）
```

---

## 依赖安装状态

```bash
# 全部已安装（venv）
qdrant-client==1.17.0    ✅
sentence-transformers==5.2.3  ✅
torch==2.10.0            ✅
rank_bm25==0.2.2         ✅
jieba==0.42.1            ✅
pymupdf==1.27.1          ✅
pywin32==311             ✅
modelscope==1.34.0       ✅

# 可选（Reranker）
FlagEmbedding            ❌ 未装（需要时再装）
```

---

## 注意事项

1. **教材 vs 幻灯片分块区别**：
   - 教材：`source_type="textbook"`，`chapter_num` 为实际章号，节标题来自 MD 标题
   - 幻灯片：`source_type="slides"`，`chapter_num=0`，`section_name="Slide N"`

2. **Qdrant 点 ID**：由 `chunk_id` 字符串 hash 生成，同一 chunk 重复摄入会覆盖

3. **BM25 无增量更新**：每次摄入新文档后会从 SQLite 全量重建，文档多时稍慢但可接受

4. **ingest_slides_dir() 的 doc_id 生成规则**：
   - 目录名去掉 `_ocr` 后缀 → `_normalize_doc_id()` 提取讲次
   - 例：`林业经济学（双语）第三讲-木材价格..._ocr` → `林业经济学_第三讲`
