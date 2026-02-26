import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 精简版题量配置（约25题/章）
QUESTION_CONFIG = {
    "单选": 10,
    "多选": 3,
    "是非": 5,
    "简答": 3,
    "简答>论述": 2,
    "简答>材料分析": 2,
}

# 路径配置
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = BASE_DIR / "kg.db"
PROGRESS_FILE = BASE_DIR / "progress.json"
MD_FILE = Path(__file__).parent.parent / "农业经济学1.pdf_by_PaddleOCR.md"

# 章节内容最大字符数（约15K token），超出则智能截断
MAX_CHAPTER_CHARS = 30000

# ── RAG 向量检索配置 ────────────────────────────────────────────
QDRANT_PATH     = BASE_DIR / "qdrant_storage"   # Qdrant 本地文件目录
BM25_PATH       = BASE_DIR / "bm25_index"        # BM25 索引目录

EMBEDDING_MODEL = "BAAI/bge-large-zh-v1.5"      # 1.3 GB，首次自动下载
RERANKER_MODEL  = "BAAI/bge-reranker-v2-m3"     # 1.1 GB，可选

# 分块参数
CHUNK_MIN_CHARS = 80    # 小于此值合并到相邻段落
CHUNK_MAX_CHARS = 600   # 大于此值按句子再切

# 检索参数
DENSE_TOP_K  = 20   # 向量粗检索数量
SPARSE_TOP_K = 20   # BM25 粗检索数量
RRF_K        = 60   # RRF 公式中的 k 值
RERANK_TOP_N = 5    # Reranker 精排后保留数量
