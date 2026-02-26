# 多文档真正 RAG 方案设计

> 版本：v1.0 | 日期：2026-02-22
> 前置文档：`技术文档.md`（当前 v1.0 Pipeline 说明）

---

## 目录

1. [与当前方案的本质区别](#1-与当前方案的本质区别)
2. [整体架构](#2-整体架构)
3. [分块策略（最关键的决策）](#3-分块策略最关键的决策)
4. [向量化层](#4-向量化层)
5. [向量库选型](#5-向量库选型)
6. [检索策略](#6-检索策略)
7. [知识图谱与向量检索的融合（GraphRAG）](#7-知识图谱与向量检索的融合graphrag)
8. [生成层的变化](#8-生成层的变化)
9. [评估体系](#9-评估体系)
10. [实施路线图](#10-实施路线图)
11. [关键设计权衡总结](#11-关键设计权衡总结)

---

## 1. 与当前方案的本质区别

先把概念厘清：

```
当前方案（结构化 Prompt 增强）：
  文档 → 按章切分 → 全文塞进 Prompt → LLM 生成
  问题：不能扩展（10本书 × 每章3万字 = 300万字，根本塞不进去）

真正的 RAG：
  文档 → 分块 → 向量化 → 存入向量库
  出题时 → 查询向量库 → 检索最相关的块 → 只把相关块塞进 Prompt
  优势：文档量无上限，检索精度决定生成质量
```

多文档让四件事变得关键：

1. **分块粒度**：块太大→检索不精准；块太小→缺失上下文
2. **向量模型**：中文学术文本的语义捕捉能力
3. **混合检索**：向量检索 + 关键词检索，弥补各自盲区
4. **跨文档关联**：同一知识点在不同教材的表述差异本身就是出题素材

---

## 2. 整体架构

```
离线阶段（一次性构建）：

多个 MD 文档
    │
    ▼
┌─────────────────────────────────┐
│   文档摄入 & 预处理层            │
│  清洗 OCR 噪音 / 统一格式        │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│   分块层（Chunking）             │
│  三级层次：章 → 节 → 段落        │
│  每块附带完整元数据              │
└────────────┬────────────────────┘
             │
             ├──────────────────┐
             ▼                  ▼
    ┌──────────────┐    ┌──────────────┐
    │  向量化层    │    │  知识图谱层  │
    │ BGE-zh 嵌入  │    │ 概念+关系    │
    └──────┬───────┘    └──────┬───────┘
           │                   │
           ▼                   ▼
    ┌──────────────┐    ┌──────────────┐
    │  向量库      │    │  图数据库    │
    │  (Qdrant)    │    │  (SQLite /   │
    │  密集检索    │    │   NetworkX)  │
    └──────────────┘    └──────────────┘
           │ BM25 索引同步构建
           ▼
    ┌──────────────┐
    │  BM25 索引   │  (Whoosh / Elasticsearch)
    │  稀疏检索    │
    └──────────────┘


在线阶段（每次出题调用）：

出题请求（指定文档集 + 章节 + 知识点）
    │
    ▼
┌─────────────────────────────────┐
│   查询构造层                    │
│  原始查询 → 多路查询扩展         │
└────────────┬────────────────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
稠密检索          稀疏检索
(向量余弦)        (BM25 关键词)
    │                 │
    └────────┬────────┘
             ▼
     ┌───────────────┐
     │  混合融合     │  RRF 倒数排名融合
     │  + KG 扩展    │  + 图谱邻居节点
     └───────┬───────┘
             ▼
     ┌───────────────┐
     │  重排序层     │  BGE-Reranker
     └───────┬───────┘
             ▼
     ┌───────────────┐
     │  上下文组装   │  按层次结构拼接
     └───────┬───────┘
             ▼
     ┌───────────────┐
     │  LLM 出题     │  DeepSeek / Qwen
     └───────────────┘
```

---

## 3. 分块策略（最关键的决策）

这是 RAG 系统质量的最大影响因素，没有之一。

### 3.1 为什么教材不能用简单固定分块

固定 512 token 分块的问题：

```
【原文】
第三节 农业合作经济组织的发展

一、中国农业合作经济组织的发展历程
...（500字）...

二、合作经济的主要特征
...（300字）...  ← 被截断！
[chunk 边界]
（第一条特征的后半段）
三、运行机制
...
```

块 A 包含"发展历程"，块 B 包含"特征的后半段 + 运行机制"——两块都残缺，检索到任一块都无法独立理解。

### 3.2 三级层次分块方案

```python
# 分块结构示意
{
    "doc_id":      "农业经济学1",
    "chunk_id":    "农经1_ch3_s2_p4",
    "level":       "paragraph",      # chapter / section / paragraph
    "chapter_num": 3,
    "chapter_name":"农业合作经济",
    "section_num": 2,
    "section_name":"农业合作经济组织的特征与运行机制",
    "text":        "合作经济以劳动者联合为基础...",  # 实际内容
    "context":     "第三章 农业合作经济 > 第二节 特征与运行机制",  # 面包屑
    "char_count":  420,
    "prev_chunk":  "农经1_ch3_s2_p3",   # 双向链表，用于上下文扩展
    "next_chunk":  "农经1_ch3_s2_p5",
    "keywords":    ["合作经济", "劳动者联合", "民主管理"],
    "is_definition": true,   # 是否是定义段落
    "is_example":    false,  # 是否是案例段落
}
```

**三级粒度各自的用途：**

| 级别 | 块大小 | 检索时机 | 用途 |
|------|-------|---------|------|
| 章级 | ~500 token | 跨章综合题 | 了解整章核心脉络 |
| 节级 | ~200 token | 知识点对比题 | 同一节的完整论述 |
| 段级 | ~80 token | 概念定义题 | 精准定义和特征列举 |

**实际检索策略：** 以段落级向量库为主索引；检索命中后，**自动上下文扩展**：取命中段落的 `prev_chunk` 和 `next_chunk`，拼接后送入 LLM——这样 LLM 看到的是完整的上下文，而向量检索的精度仍在段落级。

### 3.3 中文教材分块的具体实现

```python
import re
from dataclasses import dataclass

@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    level: str          # 'chapter' / 'section' / 'paragraph'
    chapter_num: int
    chapter_name: str
    section_num: int
    section_name: str
    text: str
    context_header: str  # "第X章 > 第Y节" 前缀，嵌入时拼接
    prev_id: str | None
    next_id: str | None

class HierarchicalChunker:
    # 段落最小字数（低于此值合并到下一段）
    MIN_PARA_CHARS = 80
    # 段落最大字数（超过此值按句子再切）
    MAX_PARA_CHARS = 600

    def chunk_chapter(self, chapter: dict, doc_id: str) -> list[Chunk]:
        chunks = []
        sections = self._split_sections(chapter['content'])

        for s_idx, (s_name, s_text) in enumerate(sections):
            paragraphs = self._split_paragraphs(s_text)
            paragraphs = self._merge_short(paragraphs)

            for p_idx, para in enumerate(paragraphs):
                chunk_id = f"{doc_id}_ch{chapter['id']}_s{s_idx}_p{p_idx}"
                context = f"{chapter['number']} {chapter['name']} > {s_name}"

                chunks.append(Chunk(
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                    level='paragraph',
                    chapter_num=chapter['id'],
                    chapter_name=chapter['name'],
                    section_num=s_idx,
                    section_name=s_name,
                    text=para,
                    context_header=context,
                    prev_id=None,  # 后面补全
                    next_id=None,
                ))

        # 补全双向链表
        for i in range(len(chunks)):
            if i > 0:
                chunks[i].prev_id = chunks[i-1].chunk_id
            if i < len(chunks) - 1:
                chunks[i].next_id = chunks[i+1].chunk_id

        return chunks

    def _split_sections(self, text: str) -> list[tuple[str, str]]:
        # 匹配 ## 第X节 / ## 一、 / ### 1. 等
        SECTION_RE = re.compile(
            r'^#{2,3}\s*(?:第[一二三四五六七八九十]+节'
            r'|[一二三四五六七八九十]+、|\d+\.)\s*(.+)$',
            re.MULTILINE
        )
        # 找到所有节标题的位置
        matches = list(SECTION_RE.finditer(text))
        if not matches:
            return [("全节", text)]

        sections = []
        for i, m in enumerate(matches):
            s_name = m.group(1).strip()
            start = m.end()
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            sections.append((s_name, text[start:end].strip()))
        return sections

    def _split_paragraphs(self, text: str) -> list[str]:
        # 按连续空行切分，单个换行不切
        paras = re.split(r'\n{2,}', text.strip())
        result = []
        for p in paras:
            if len(p) > self.MAX_PARA_CHARS:
                result.extend(self._split_by_sentence(p))
            else:
                result.append(p)
        return [p.strip() for p in result if p.strip()]

    def _merge_short(self, paras: list[str]) -> list[str]:
        """将过短的段落合并到下一段。"""
        merged, buf = [], ''
        for p in paras:
            if len(buf) + len(p) < self.MIN_PARA_CHARS:
                buf = (buf + ' ' + p).strip()
            else:
                if buf:
                    merged.append(buf)
                buf = p
        if buf:
            merged.append(buf)
        return merged

    def _split_by_sentence(self, text: str) -> list[str]:
        # 中文句子边界：。！？；
        sentences = re.split(r'(?<=[。！？；])', text)
        chunks, current = [], ''
        for s in sentences:
            if len(current) + len(s) > self.MAX_PARA_CHARS and current:
                chunks.append(current)
                current = s
            else:
                current += s
        if current:
            chunks.append(current)
        return chunks
```

---

## 4. 向量化层

### 4.1 嵌入模型选型（中文学术文本）

| 模型 | 维度 | 推理方式 | 中文效果 | 说明 |
|------|------|---------|---------|------|
| `BAAI/bge-large-zh-v1.5` | 1024 | 本地 | ★★★★★ | **首选**，MTEB 中文榜最强之一 |
| `BAAI/bge-m3` | 1024 | 本地 | ★★★★★ | 多语言，支持 8192 token 长文本 |
| `text-embedding-3-small` | 1536 | OpenAI API | ★★★★ | 效果好，但需付费，中文略弱 |
| DashScope `text-embedding-v3` | 1024 | 阿里 API | ★★★★ | 中文优化，按量计费 |
| `m3e-base` | 768 | 本地 | ★★★ | 轻量，效果一般 |

**推荐：`BAAI/bge-large-zh-v1.5`（本地运行）**

理由：
- 专为中文优化，农业经济学术语处理好
- 本地推理，不消耗 API 额度
- 有配套 reranker（`bge-reranker-v2-m3`），形成完整检索链

### 4.2 嵌入时的关键技巧——Context Header 拼接

```python
# 不要只嵌入段落本身，要拼接位置前缀
def embed_chunk(chunk: Chunk) -> list[float]:
    # BGE 官方建议：查询加前缀以提升检索精度
    text_to_embed = f"{chunk.context_header}\n\n{chunk.text}"
    return embedding_model.encode(text_to_embed)

# 查询时加前缀
def embed_query(query: str) -> list[float]:
    prefixed = f"为这个句子生成表示以用于检索相关文章：{query}"
    return embedding_model.encode(prefixed)
```

孤立的段落"合作经济以劳动者联合为基础"在向量空间里可能与很多其他文本相似，
但加上"第三章 农业合作经济 > 第二节 特征与运行机制"后，语义空间定位就精确多了。
（Anthropic 将此技巧称为 Contextual Retrieval，实测可将检索失败率降低 35-50%。）

### 4.3 向量化性能估算

以本教材为例（可推广到多文档）：

```
全书 ~255,000 字 ÷ 平均 200 字/段 ≈ 1,275 个段落
10 本教材 ≈ 12,750 个向量

bge-large-zh 推理速度（CPU）：约 50 段/秒
全部向量化耗时：12,750 ÷ 50 ≈ 255 秒（约 4 分钟）
向量维度 1024，float32 = 4 bytes
存储占用：12,750 × 1024 × 4 ≈ 50MB（可忽略不计）
```

---

## 5. 向量库选型

### 5.1 详细对比

| 特性 | **Chroma** | **Qdrant** | FAISS | Weaviate |
|------|-----------|-----------|-------|---------|
| 部署 | 本地进程 | 本地/Docker/云 | 本地库 | Docker |
| 持久化 | SQLite | 自有存储 | 需手动 | 自有存储 |
| 混合检索 | 需自己实现 | **原生支持** | 否 | 原生支持 |
| 元数据过滤 | 支持 | **支持，很快** | 否 | 支持 |
| Python SDK | 简单 | **简单** | 简单 | 复杂 |
| 适合规模 | <100万向量 | 千万级 | 亿级 | 百万级 |
| 学习成本 | 低 | **低** | 低 | 高 |

**推荐：Qdrant（本地文件模式）**

- 原生支持混合检索（稠密 + 稀疏），不需要额外搭 BM25 索引
- 元数据过滤性能极佳（按 `doc_id` / `chapter_num` 过滤后再检索）
- 从本地迁移到 Qdrant Cloud 几乎不改代码

### 5.2 Qdrant 核心操作示例

```python
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
    SparseVectorParams, SparseVector,
)

# 初始化（本地文件模式，持久化）
client = QdrantClient(path="./qdrant_storage")

# 建立集合（支持稠密 + 稀疏双向量）
client.create_collection(
    collection_name="textbook_chunks",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE),
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams(),  # 用于 BM25
    }
)

# 插入向量
client.upsert(
    collection_name="textbook_chunks",
    points=[
        PointStruct(
            id=chunk_index,
            vector={
                "dense": dense_embedding,
                "sparse": SparseVector(indices=bm25_indices, values=bm25_values),
            },
            payload={
                "doc_id":       "农业经济学1",
                "chunk_id":     "农经1_ch3_s2_p4",
                "chapter_num":  3,
                "chapter_name": "农业合作经济",
                "section_name": "特征与运行机制",
                "level":        "paragraph",
                "text":         "合作经济以劳动者联合为基础...",
                "prev_id":      "农经1_ch3_s2_p3",
                "next_id":      "农经1_ch3_s2_p5",
            }
        )
    ]
)

# 带元数据过滤的检索（只在指定文档的指定章内检索）
results = client.query_points(
    collection_name="textbook_chunks",
    query=query_dense_vector,
    using="dense",
    query_filter=Filter(
        must=[
            FieldCondition(key="doc_id", match=MatchValue(value="农业经济学1")),
            FieldCondition(key="chapter_num", match=MatchValue(value=3)),
        ]
    ),
    limit=10,
)
```

---

## 6. 检索策略

### 6.1 为什么需要混合检索

**纯向量检索的盲区：**
- 精确术语匹配差：查"罗虚戴尔原则"时，向量可能返回语义相关但未精确提及该词的段落
- 数字和专有名词效果差：年份、法规编号、人名
- 低频词被高频上下文淹没

**纯 BM25 的盲区：**
- 同义词：查"农业互助"找不到写着"农业协作"的段落
- 语义理解：查"土地和农民的关系"找不到"土地是农业生产最为基本的生产资料"

**混合检索（Hybrid Search）：** 两者各出若干候选，用 RRF 合并排名。

### 6.2 RRF 倒数排名融合

```python
def reciprocal_rank_fusion(
    dense_results: list,
    sparse_results: list,
    k: int = 60,
    dense_weight: float = 0.7,
    sparse_weight: float = 0.3,
) -> list:
    """
    RRF 公式：score(d) = Σ weight_i / (k + rank_i(d))
    k=60 是经验值，防止排名靠前的文档得分过高。
    """
    scores: dict[str, float] = {}
    chunk_map: dict[str, object] = {}

    for rank, point in enumerate(dense_results, 1):
        cid = point.payload["chunk_id"]
        scores[cid] = scores.get(cid, 0) + dense_weight / (k + rank)
        chunk_map[cid] = point

    for rank, point in enumerate(sparse_results, 1):
        cid = point.payload["chunk_id"]
        scores[cid] = scores.get(cid, 0) + sparse_weight / (k + rank)
        chunk_map[cid] = point

    sorted_ids = sorted(scores, key=scores.__getitem__, reverse=True)
    return [chunk_map[cid] for cid in sorted_ids]
```

### 6.3 查询扩展（多路检索）

```python
def expand_query(concept: str, relation_type: str) -> list[str]:
    """根据知识图谱的关系类型生成多个检索查询。"""
    queries = [concept]

    if relation_type == "contrasts_with":
        queries += [
            f"{concept}的特点",
            f"{concept}与其他形式的区别",
            f"{concept}的优缺点",
        ]
    elif relation_type == "leads_to":
        queries += [
            f"{concept}的影响",
            f"{concept}的历史作用",
            f"{concept}产生的原因和结果",
        ]
    elif relation_type == "is_a":
        queries += [
            f"{concept}的定义",
            f"{concept}是什么",
            f"{concept}的分类",
        ]

    return queries
```

每个查询独立检索，结果用 RRF 再次合并，最终取 Top-K。

### 6.4 重排序（Cross-Encoder Reranker）

双塔模型（Bi-encoder）用于高效检索，但相似度计算比较粗糙。
重排序用 Cross-Encoder 对 query 和每个候选 chunk 一起编码，精度更高：

```python
from FlagEmbedding import FlagReranker

reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=True)

def rerank(query: str, chunks: list[dict], top_n: int = 5) -> list[dict]:
    pairs = [(query, c["text"]) for c in chunks]
    scores = reranker.compute_score(pairs, normalize=True)
    ranked = sorted(zip(scores, chunks), reverse=True)
    return [chunk for _, chunk in ranked[:top_n]]
```

**典型检索流程：**

```
向量库粗检索：Top 20 候选
    ↓
BM25 粗检索：Top 20 候选
    ↓
RRF 合并去重：Top 20
    ↓
Cross-Encoder 精排：Top 5
    ↓
上下文扩展（取 prev/next 块）：5 段 × 3 = 15 段文本
    ↓
送入 LLM
```

---

## 7. 知识图谱与向量检索的融合（GraphRAG）

### 7.1 两种索引互补的定位

```
向量库：语义空间的地图
    → "找到所有和'家庭承包经营'语义相关的段落"

知识图谱：概念关系的地图
    → "找到'家庭承包经营'形成对比的概念，
       以及依赖它为前提的其他概念"
```

两者检索结果合并，形成**语义相关 + 逻辑关联**的双重覆盖。

### 7.2 图谱引导的检索扩展

```python
def graph_guided_retrieval(
    concept: str,
    vector_store,
    kg,
    doc_filter: list[str] | None = None,
) -> list[dict]:
    """以概念为起点，沿图谱边扩展检索范围。"""
    results = []

    # 1. 直接检索该概念
    results += vector_search(concept, doc_filter)

    # 2. 查图谱，找一跳邻居
    neighbors = kg.get_neighbors(concept)
    # 示例结果：
    # [{"concept": "双层经营体制", "relation": "is_a"},
    #  {"concept": "产权制度",     "relation": "depends_on"}]

    for neighbor in neighbors:
        if neighbor["relation"] in ("is_a", "contrasts_with"):
            # 对比关系：邻居概念全量检索
            results += vector_search(neighbor["concept"], doc_filter)
        elif neighbor["relation"] == "leads_to":
            # 因果关系：检索涉及两者关系的段落
            results += vector_search(
                f"{concept}导致{neighbor['concept']}", doc_filter
            )

    # 3. 去重 + RRF 排序
    return deduplicate_and_rank(results)
```

### 7.3 跨文档知识对齐

多本教材的核心价值：同一概念在不同教材的表述差异本身就是考察理解深度的素材。

```python
def cross_doc_comparison_query(
    concept: str,
    doc_ids: list[str],
) -> dict[str, list]:
    """检索同一概念在多本教材中的不同表述。"""
    per_doc_results = {}
    for doc_id in doc_ids:
        per_doc_results[doc_id] = vector_search(
            concept,
            filter={"doc_id": doc_id},
            top_k=2,
        )
    return per_doc_results
    # 返回格式：{"农业经济学1": [...], "林业经济学": [...]}
    # 可以让 LLM 基于多本书的表述出"比较分析"题
```

---

## 8. 生成层的变化

### 8.1 上下文组装策略

```python
def build_generation_context(
    target_concept: str,
    relation_type: str,
    retrieved_chunks: list[dict],
    kg_context: dict,
) -> str:
    """将检索结果组装为结构化的生成上下文。"""
    by_doc = group_by_doc(retrieved_chunks)
    context_parts = []

    # 注入 KG 摘要
    context_parts.append(f"""
【知识图谱信息】
目标概念：{target_concept}
关系类型：{relation_type}
相关概念：{', '.join(kg_context['neighbors'])}
重点标记：{'是' if kg_context['is_key'] else '否'}
难点标记：{'是' if kg_context['is_difficult'] else '否'}
""")

    # 注入检索到的段落（按文档来源标注）
    for doc_id, chunks in by_doc.items():
        context_parts.append(f"【来源：{doc_id}】")
        for chunk in chunks:
            context_parts.append(
                f"[{chunk['chapter_name']} > {chunk['section_name']}]\n"
                f"{chunk['text']}"
            )

    return "\n\n".join(context_parts)
```

### 8.2 Prompt 结构对比

```
旧（全文注入）：
  [KG摘要] + [15000字章节全文] + [出题要求] + [格式]
  输入约 9,500 token

新（RAG检索注入）：
  [KG摘要] + [检索到的5-8段，共约1500字] + [出题要求] + [格式]
  + [可选：跨文档对比段落]
  输入约 2,500 token
```

上下文从 15,000 字降到 1,500 字，质量反而更高——因为段落都是精准相关的，
没有无关内容干扰 LLM 的注意力，同时 API 费用降低约 75%。

---

## 9. 评估体系

RAG 系统最大的问题是不知道检索结果是否真的好，必须有量化指标。

### 9.1 检索质量评估

```python
# 构建评估集：人工标注哪些段落和哪些知识点相关
eval_set = [
    {
        "query": "家庭承包经营的含义",
        "relevant_chunk_ids": ["农经1_ch1_s1_p2", "农经1_ch2_s1_p1"],
    },
    ...
]

def evaluate_retrieval(eval_set, retriever, top_k=5):
    metrics = {"recall@5": [], "precision@5": [], "mrr": []}

    for item in eval_set:
        retrieved = retriever.search(item["query"], top_k=top_k)
        retrieved_ids = [r["chunk_id"] for r in retrieved]
        relevant = set(item["relevant_chunk_ids"])

        # Recall@K：相关文档被检索到的比例
        hit = len(set(retrieved_ids) & relevant)
        metrics["recall@5"].append(hit / len(relevant))

        # Precision@K：检索结果中相关文档的比例
        metrics["precision@5"].append(hit / top_k)

        # MRR：第一个相关结果的排名倒数
        for rank, rid in enumerate(retrieved_ids, 1):
            if rid in relevant:
                metrics["mrr"].append(1.0 / rank)
                break
        else:
            metrics["mrr"].append(0.0)

    return {k: sum(v)/len(v) for k, v in metrics.items()}
```

### 9.2 生成质量评估（RAGAS 框架）

```python
# pip install ragas
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision

# faithfulness：生成的题目是否忠实于检索到的段落（不编造）
# answer_relevancy：参考答案与检索内容的相关性
# context_precision：检索结果中有多少真正被 LLM 使用了
```

### 9.3 题目质量人工评估维度

| 维度 | 评分标准 |
|------|---------|
| 事实准确性 | 题目内容是否与教材原文一致 |
| 检索覆盖率 | 重难点知识点是否都有对应题目 |
| 题型匹配度 | 关系类型是否正确映射到题型 |
| 干扰项合理性 | 单选错误选项是否合理（不能太明显） |
| 跨文档利用率 | 是否有效利用了多本教材的不同表述 |

---

## 10. 实施路线图

### Phase 1：向量化基础设施（约 3 天）

```
安装依赖：
  pip install qdrant-client sentence-transformers FlagEmbedding whoosh

新增文件：
  rag_pipeline/
  ├── chunker.py         # 三级层次分块（本文档 3.3 节实现）
  ├── embedder.py        # BGE 嵌入封装 + Context Header 拼接
  ├── vector_store.py    # Qdrant CRUD 封装
  ├── bm25_index.py      # Whoosh BM25 索引构建与查询
  └── retriever.py       # 混合检索 + RRF + 重排序

验收标准：
  对"家庭承包经营"检索，人工核查 Top-5 全部相关
```

### Phase 2：检索质量优化（约 2 天）

```
任务：
  - 实现 RRF 融合（本文档 6.2 节）
  - 接入 BGE-Reranker
  - 实现上下文扩展（prev/next chunk）
  - 构建小型评估集（50条 query-chunk 标注对）
  - 调参：dense/sparse 权重、RRF k 值、rerank top_n

目标指标：
  Recall@5 > 0.8，MRR > 0.7
```

### Phase 3：与 KG 融合（约 2 天）

```
任务：
  - 实现 graph_guided_retrieval（本文档 7.2 节）
  - 实现 cross_doc_comparison_query（本文档 7.3 节）
  - 修改 question_generator.py：
      原：全文注入（15K token）
      改：RAG 检索注入（~2.5K token）
  - A/B 实验：同一知识点，RAG 版 vs 全文版质量对比
```

### Phase 4：多文档管理（约 1 天）

```
任务：
  - 用 doc_id 字段在 Qdrant 里隔离不同文档
  - 实现文档级别的增删（删除指定 doc_id 的所有向量）
  - 支持跨文档出题（query 时不加 doc_id 过滤）
  - 在交互菜单中新增"文档管理"选项
```

### Phase 5：评估与调优（持续）

```
任务：
  - 扩充评估集到 200 条
  - 接入 RAGAS 自动化评估生成质量
  - A/B 测试不同分块参数（MIN/MAX_PARA_CHARS）
  - 建立监控：每次出题记录检索命中率
```

**总工期估算：约 8-9 个工作日**

---

## 11. 关键设计权衡总结

| 决策点 | 选择 | 核心理由 |
|-------|------|---------|
| 分块策略 | 层次分块（段级检索 + 上下文扩展） | 精度和完整性兼顾；最影响系统质量的单一因素 |
| 嵌入模型 | BGE-large-zh（本地） | 中文学术文本最强，免费，有配套 reranker |
| 向量库 | Qdrant（本地文件模式） | 混合检索原生支持，元数据过滤快 |
| 检索策略 | RRF（稠密 + 稀疏）+ 重排序 | 弥补各自盲区，精确率显著高于单一策略 |
| KG 角色 | 查询扩展 + 题型路由（保留） | 和向量检索互补，不是替代关系 |
| 上下文组装 | 精准段落 × 3（命中 + 前后块） | ~1,500 字代替 ~15,000 字，费用降 75% |
| 跨文档检索 | 同概念多源对比 | 多文档独特价值的体现，生成比较分析题 |

---

## 附：新增依赖清单

```
# rag_pipeline/requirements_rag.txt

# 向量库
qdrant-client>=1.9

# 嵌入模型（本地推理）
sentence-transformers>=3.0
FlagEmbedding>=1.2        # bge-large-zh + bge-reranker

# BM25 稀疏索引
whoosh>=2.7

# 评估框架（可选）
ragas>=0.1

# 已有依赖（保留）
python-dotenv>=1.0
openai>=1.0
```

**首次运行时模型下载（自动，需要网络）：**

```python
# BGE 模型约 1.3GB，reranker 约 1.1GB，合计约 2.4GB
# 下载后缓存在 ~/.cache/huggingface/，后续离线可用
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("BAAI/bge-large-zh-v1.5")  # 首次自动下载
```

---

*文档完 | 真正 RAG 方案 v1.0*
