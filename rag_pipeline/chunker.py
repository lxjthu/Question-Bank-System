"""
文档分块模块（Chunker）

两种策略，区分对待：
  TextbookChunker — 教材 MD（来自 PDF OCR）：文档→章→节→段落
  SlidesChunker   — 幻灯片 MD（来自 PPTX OCR）：文档→页→段落

两者都输出同结构的 Chunk 对象，供 Embedder / VectorStore 统一处理。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import CHUNK_MIN_CHARS, CHUNK_MAX_CHARS


# ── Chunk 数据结构 ────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    doc_id:         str          # 文档唯一标识，如 "农业经济学1"
    source_type:    str          # "textbook" | "slides"
    chunk_id:       str          # 全局唯一 ID
    level:          str          # "paragraph"（主索引级别）
    chapter_num:    int          # 教材：章号；幻灯片：0
    chapter_name:   str          # 章名或文档标题
    section_num:    int          # 教材：节号；幻灯片：页号
    section_name:   str          # 节名或 "Slide N"
    text:           str          # 块内容（用于检索和生成）
    context_header: str          # 面包屑，嵌入时拼接在 text 前
    prev_id:        Optional[str] = None
    next_id:        Optional[str] = None


# ── 公共文本处理工具 ──────────────────────────────────────────────────────────

def _split_by_sentence(text: str) -> list[str]:
    """按中英文句子边界切分过长文本。"""
    parts = re.split(r'(?<=[。！？；\.\!\?])', text)
    chunks, cur = [], ''
    for s in parts:
        if len(cur) + len(s) > CHUNK_MAX_CHARS and cur:
            chunks.append(cur)
            cur = s
        else:
            cur += s
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c.strip()]


def _split_paragraphs(text: str) -> list[str]:
    """按空行切段，过长段落再按句子切。"""
    raw = re.split(r'\n{2,}', text.strip())
    result = []
    for p in raw:
        p = p.strip()
        if not p:
            continue
        if len(p) > CHUNK_MAX_CHARS:
            result.extend(_split_by_sentence(p))
        else:
            result.append(p)
    return result


def _merge_short(paras: list[str]) -> list[str]:
    """将过短的段落合并到下一段。"""
    merged, buf = [], ''
    for p in paras:
        if len(buf) + len(p) < CHUNK_MIN_CHARS:
            buf = (buf + ' ' + p).strip() if buf else p
        else:
            if buf:
                merged.append(buf)
            buf = p
    if buf:
        merged.append(buf)
    return merged


def _link(chunks: list[Chunk]) -> list[Chunk]:
    """设置 prev_id / next_id 双向链表。"""
    for i, c in enumerate(chunks):
        c.prev_id = chunks[i - 1].chunk_id if i > 0 else None
        c.next_id = chunks[i + 1].chunk_id if i < len(chunks) - 1 else None
    return chunks


# ── TextbookChunker ───────────────────────────────────────────────────────────

# 匹配 ## 第X节 / ## 一、 / ### 1. 等节标题
_SECTION_RE = re.compile(
    r'^#{2,3}\s*(?:第[一二三四五六七八九十百]+节'
    r'|[一二三四五六七八九十]+、|\d+[\.\、])\s*(.+)$',
    re.MULTILINE,
)


class TextbookChunker:
    """
    教材分块器。
    输入：parser.parse_md() 返回的章节列表
    输出：Chunk 列表（source_type="textbook"）

    层级：文档 → 章 → 节 → 段落
    检索单元：段落（level="paragraph"）
    上下文扩展：通过 prev_id / next_id 取相邻段落
    """

    def __init__(self, doc_id: str):
        self.doc_id = doc_id

    def chunk_all(self, chapters: list[dict]) -> list[Chunk]:
        """对所有章节分块，返回全局链表。"""
        all_chunks: list[Chunk] = []
        for ch in chapters:
            all_chunks.extend(self._chunk_chapter(ch))
        return _link(all_chunks)

    def _chunk_chapter(self, chapter: dict) -> list[Chunk]:
        sections = self._split_sections(chapter['content'])
        chunks: list[Chunk] = []
        for s_idx, (s_name, s_text) in enumerate(sections):
            paras = _merge_short(_split_paragraphs(s_text))
            for p_idx, para in enumerate(paras):
                chunk_id = f"{self.doc_id}_ch{chapter['id']}_s{s_idx}_p{p_idx}"
                header = f"{chapter['number']} {chapter['name']} > {s_name}"
                chunks.append(Chunk(
                    doc_id=self.doc_id,
                    source_type="textbook",
                    chunk_id=chunk_id,
                    level="paragraph",
                    chapter_num=chapter['id'],
                    chapter_name=chapter['name'],
                    section_num=s_idx,
                    section_name=s_name,
                    text=para,
                    context_header=header,
                ))
        return chunks

    def _split_sections(self, text: str) -> list[tuple[str, str]]:
        matches = list(_SECTION_RE.finditer(text))
        if not matches:
            return [("正文", text)]
        sections = []
        for i, m in enumerate(matches):
            s_name = m.group(1).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections.append((s_name, text[start:end].strip()))
        return sections


# ── SlidesChunker ─────────────────────────────────────────────────────────────

# 匹配 pptx_ocr 输出的 ## Page N 标记
_PAGE_RE = re.compile(r'^## Page (\d+)\s*$', re.MULTILINE)
# 去掉 HTML 标签和 Markdown 图片（幻灯片里的图片占位符）
_MARKUP_RE = re.compile(r'<[^>]+>|!\[.*?\]\(.*?\)')


class SlidesChunker:
    """
    幻灯片分块器。
    输入：pptx_ocr pipeline 生成的 result.md 文件
    输出：Chunk 列表（source_type="slides"）

    层级：文档 → 页（Slide N）→ 段落
    与教材的区别：
      - chapter_num 固定为 0（幻灯片没有教材意义上的"章"）
      - section_num = 页号，section_name = "Slide N"
      - 纯图片页（无文字）自动跳过
    """

    def __init__(self, doc_id: str, doc_title: str = ""):
        self.doc_id = doc_id
        self.doc_title = doc_title or doc_id

    def chunk_file(self, result_md: Path) -> list[Chunk]:
        text = Path(result_md).read_text(encoding="utf-8")
        pages = self._split_pages(text)
        all_chunks: list[Chunk] = []
        for page_num, page_text in pages:
            all_chunks.extend(self._chunk_page(page_num, page_text))
        return _link(all_chunks)

    def _split_pages(self, text: str) -> list[tuple[int, str]]:
        matches = list(_PAGE_RE.finditer(text))
        if not matches:
            body = re.sub(r'^[#>].*$', '', text, flags=re.MULTILINE)
            return [(1, body)]
        pages = []
        for i, m in enumerate(matches):
            num = int(m.group(1))
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            pages.append((num, text[start:end].strip()))
        return pages

    def _chunk_page(self, page_num: int, page_text: str) -> list[Chunk]:
        clean = _MARKUP_RE.sub('', page_text).strip()
        paras = _merge_short(_split_paragraphs(clean))
        # 跳过纯图片页（清理后无实质文字）
        paras = [p for p in paras if len(p.strip()) > 5]
        if not paras:
            return []

        slide_name = f"Slide {page_num}"
        header = f"{self.doc_title} > {slide_name}"
        chunks = []
        for p_idx, para in enumerate(paras):
            chunk_id = f"{self.doc_id}_p{page_num}_t{p_idx}"
            chunks.append(Chunk(
                doc_id=self.doc_id,
                source_type="slides",
                chunk_id=chunk_id,
                level="paragraph",
                chapter_num=0,
                chapter_name=self.doc_title,
                section_num=page_num,
                section_name=slide_name,
                text=para,
                context_header=header,
            ))
        return chunks
