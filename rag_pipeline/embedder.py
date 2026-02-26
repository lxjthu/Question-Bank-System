"""
向量嵌入模块（Embedder）

模型：BAAI/bge-large-zh-v1.5
  - 专为中文优化，MTEB 中文榜最强之一
  - 维度 1024，本地推理，不消耗 API 额度
  - GPU 自动检测（有 CUDA 则使用 GPU）

关键技巧：Context Header 拼接
  - 嵌入时在文本前拼接位置面包屑（如"第三章 > 第二节"）
  - 查询时加 BGE 官方推荐的指令前缀
  - 实测可将检索失败率降低 35-50%（Contextual Retrieval）
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chunker import Chunk

# BGE 查询指令前缀（官方推荐）
_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


class Embedder:
    """
    文本嵌入器，封装 sentence-transformers + BGE 模型。

    Args:
        model_name: HuggingFace 模型名称
        device: "auto" | "cuda" | "cpu"
        hf_mirror: 国内镜像，"auto" 时自动设置 HF_ENDPOINT 环境变量
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-large-zh-v1.5",
        device: str = "auto",
        hf_mirror: bool = True,
    ):
        import os
        import torch
        from pathlib import Path
        from sentence_transformers import SentenceTransformer

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        # 优先从 ModelScope 本地缓存加载（models/ 目录）
        # ModelScope 将 . 替换为 ___，如 bge-large-zh-v1.5 → bge-large-zh-v1___5
        ms_name = model_name.split("/")[-1].replace(".", "___")
        models_root = Path(__file__).parent.parent / "models"
        local_path = models_root / model_name.split("/")[0] / ms_name
        if local_path.exists():
            load_from = str(local_path)
            print(f"[Embedder] Loading from local: {load_from}")
        else:
            # 回退到 HuggingFace（国内镜像）
            if hf_mirror and not os.environ.get("HF_ENDPOINT"):
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            load_from = model_name
            print(f"[Embedder] Loading {model_name} on {device} ...")

        print(f"[Embedder] Loading on {device} ...")
        self.model = SentenceTransformer(load_from, device=device)
        self._device = device
        self._dim = self.model.get_sentence_embedding_dimension()
        print(f"[Embedder] Ready  dim={self._dim}  device={device}")

    @property
    def dim(self) -> int:
        return self._dim

    def embed_chunks(self, chunks: list[Chunk], batch_size: int = 32) -> list[list[float]]:
        """
        对 Chunk 列表做批量嵌入。
        嵌入文本 = context_header + "\\n\\n" + text
        """
        texts = [f"{c.context_header}\n\n{c.text}" for c in chunks]
        vecs = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vecs.tolist()

    def embed_query(self, query: str) -> list[float]:
        """对检索查询做嵌入，自动加 BGE 指令前缀。"""
        vec = self.model.encode(
            _QUERY_PREFIX + query,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vec.tolist()
