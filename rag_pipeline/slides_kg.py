"""
幻灯片 OCR → 知识图谱提取流程

流程：
  1. 解析 OCR result.md，按"标题页"自动检测主题分组（伪章节）
  2. 对每组调用 DeepSeek 提取 KG（复用 kg_extractor.extract_kg_for_chapter）
  3. 存入 chapters / concepts / relations 表（复用 db.save_chapter / db.save_kg）

主题分组规则（按优先级）：
  a. 页面文本去空格后 ≤ 60 字符 → 强判定为标题页
  b. 页面文本去空格后 ≤ 120 字符，且首行匹配常见章节标题模式 → 标题页
  c. 若全文检测不到任何标题页，按 MAX_PAGES_PER_GROUP 页强制分组
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from openai import OpenAI

from . import db
from .config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MAX_CHAPTER_CHARS
from .kg_extractor import extract_kg_for_chapter

# ── 参数常量 ──────────────────────────────────────────────────────────────────

# 强制分组时每组最大页数（无法识别标题时的兜底策略）
MAX_PAGES_PER_GROUP = 15

# 主题组最小有效字符数（去空格后），低于此值则跳过（封面/分隔幻灯片）
MIN_GROUP_CHARS = 40

# 标题页判定阈值（去空格后的字符数）
TITLE_THRESHOLD_HARD = 30    # ≤ 此值 + ≤2行 + 无子弹点 → 强判标题页
TITLE_THRESHOLD_SOFT = 80    # ≤ 此值 + 首行匹配章节模式 → 判标题页

# 子弹点正则（内容页的典型标志）
_RE_BULLET = re.compile(r'^[\-•\*·▪▸►→]')

# 章节标题正则（中英文）
_RE_CHAPTER = re.compile(
    r'第\s*[零一二三四五六七八九十百\d]+\s*[章节讲部分]'
    r'|Chapter\s*\d+'
    r'|Unit\s*\d+'
    r'|CHAPTER\s*\d+',
    re.IGNORECASE,
)

# OCR result.md 的页面分隔行（## Page N / ## Slide N）
_RE_PAGE_HEADER = re.compile(r'^##\s+(?:Page|Slide|幻灯片)\s+(\d+)', re.IGNORECASE)

# 中文数字
_CN_DIGITS = '零一二三四五六七八九'


# ── 页面解析 ──────────────────────────────────────────────────────────────────

def _parse_pages(result_md: Path) -> list[dict]:
    """
    将 OCR result.md 解析为页面列表。
    返回：[{page_num: int, text: str}, ...]
    """
    pages: list[dict] = []
    current_page: int | None = None
    current_lines: list[str] = []

    def _flush():
        if current_page is not None:
            pages.append({
                'page_num': current_page,
                'text': '\n'.join(current_lines).strip(),
            })

    with open(result_md, encoding='utf-8') as f:
        for raw_line in f:
            line = raw_line.rstrip('\n')
            m = _RE_PAGE_HEADER.match(line)
            if m:
                _flush()
                current_page = int(m.group(1))
                current_lines = []
            elif current_page is not None:
                # 清理图片引用（OCR 产生的 ![...](...)）
                clean = re.sub(r'!\[.*?\]\([^)]*\)', '', line).strip()
                if clean:
                    current_lines.append(clean)
    _flush()
    return pages


# ── 标题页检测 ────────────────────────────────────────────────────────────────

def _is_title_page(page: dict) -> bool:
    """
    判断某页是否为章节标题页。

    判定逻辑：
      1. 字符数极少（≤HARD阈值）且行数≤2且无子弹点 → 强判标题页（单行大标题）
      2. 字符数中等（≤SOFT阈值）且首行精确匹配章节模式 → 标题页
      3. 其余均为内容页
    """
    text = page['text']
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return False

    char_count = len(re.sub(r'\s+', '', text))
    has_bullets = any(_RE_BULLET.match(l) for l in lines)

    # 条件 1：超短、行数少、无子弹点 → 纯标题
    if char_count <= TITLE_THRESHOLD_HARD and len(lines) <= 2 and not has_bullets:
        return True

    # 条件 2：中等长度，首行精确匹配章节模式
    if char_count <= TITLE_THRESHOLD_SOFT and _RE_CHAPTER.match(lines[0]):
        return True

    return False


def _extract_topic_name(page: dict) -> str:
    """从标题页提取主题名称（取第一行非空、非纯数字文字）。"""
    for line in page['text'].splitlines():
        line = line.strip()
        if line and not re.fullmatch(r'[\d\s]+', line):
            return line[:60]
    return f"主题 {page['page_num']}"


# ── 主题分组 ──────────────────────────────────────────────────────────────────

def detect_topics(result_md: Path) -> list[dict]:
    """
    检测 OCR result.md 中的主题分组（伪章节）。

    Returns:
        list of {number, name, content, page_start, page_end}
    """
    pages = _parse_pages(result_md)
    if not pages:
        return []

    # 找出所有标题页的下标
    title_indices = [i for i, p in enumerate(pages) if _is_title_page(p)]

    # 没有识别到任何标题页 → 按固定页数强制分组
    if not title_indices:
        groups: list[dict] = []
        for gi, start in enumerate(range(0, len(pages), MAX_PAGES_PER_GROUP)):
            chunk_pages = pages[start: start + MAX_PAGES_PER_GROUP]
            content = '\n\n'.join(p['text'] for p in chunk_pages if p['text'])
            if not content.strip():
                continue
            groups.append({
                'number': f"第{_int_to_cn(gi + 1)}组",
                'name': f"内容组 {gi + 1}（第 {chunk_pages[0]['page_num']}–{chunk_pages[-1]['page_num']} 页）",
                'content': content[:MAX_CHAPTER_CHARS],
                'page_start': chunk_pages[0]['page_num'],
                'page_end': chunk_pages[-1]['page_num'],
            })
        return groups

    groups = []

    # 封面/前言页（第一个标题页之前）
    if title_indices[0] > 0:
        preamble_pages = pages[:title_indices[0]]
        preamble_text = '\n\n'.join(p['text'] for p in preamble_pages if p['text'])
        if preamble_text.strip():
            groups.append({
                'number': '前言',
                'name': '课程概述',
                'content': preamble_text[:MAX_CHAPTER_CHARS],
                'page_start': pages[0]['page_num'],
                'page_end': pages[title_indices[0] - 1]['page_num'],
            })

    # 每个标题页 → 一个主题组
    for i, ti in enumerate(title_indices):
        title_page = pages[ti]
        end_idx = title_indices[i + 1] if i + 1 < len(title_indices) else len(pages)
        group_pages = pages[ti:end_idx]

        # 内容 = 标题页之后的页（标题信息已提取到 name 字段）
        content_pages = group_pages[1:] if len(group_pages) > 1 else group_pages
        content = '\n\n'.join(p['text'] for p in content_pages if p['text'])
        if len(re.sub(r'\s+', '', content)) < MIN_GROUP_CHARS:
            continue  # 内容太少（封面/纯分隔幻灯片）跳过

        topic_name = _extract_topic_name(title_page)

        # 编号：若标题页本身含"第X章/讲"则直接用，否则自动生成
        ch_match = _RE_CHAPTER.search(topic_name)
        number = ch_match.group() if ch_match else f"第{_int_to_cn(i + 1)}讲"

        groups.append({
            'number': number,
            'name': topic_name,
            'content': content[:MAX_CHAPTER_CHARS],
            'page_start': title_page['page_num'],
            'page_end': group_pages[-1]['page_num'],
        })

    return groups


# ── 核心入口 ──────────────────────────────────────────────────────────────────

def build_kg_for_slides(
    doc_id: str,
    result_md: Path,
    subject_hint: str = '',
    progress_callback=None,
) -> int:
    """
    对幻灯片 OCR 结果构建知识图谱，存入 chapters/concepts/relations 表。

    Args:
        doc_id:            文档标识（与 chunks 表的 doc_id 一致）
        result_md:         OCR 输出的 result.md 路径
        subject_hint:      学科提示，如"林业经济学"（写入 DeepSeek prompt）
        progress_callback: 可选回调 fn(current, total, topic_name)

    Returns:
        成功处理的主题组数量
    """
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == 'sk-your-key-here':
        raise RuntimeError("未设置 DEEPSEEK_API_KEY，无法提取知识图谱")

    result_md = Path(result_md)
    if not result_md.exists():
        raise FileNotFoundError(f"result.md 不存在：{result_md}")

    topics = detect_topics(result_md)
    if not topics:
        raise ValueError(f"未能从 {result_md.name} 中识别出任何主题分组，请检查 OCR 输出格式")

    print(f"\n[SlidesKG] doc_id={doc_id}  识别到 {len(topics)} 个主题组")
    for t in topics:
        print(f"  • {t['number']} {t['name']}  (p{t['page_start']}–p{t['page_end']}, {len(t['content'])} chars)")

    # 删除该文档已有的 KG 数据（幂等）
    db.delete_kg_by_doc(doc_id)

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    success = 0

    for idx, topic in enumerate(topics):
        print(f"\n  [{idx + 1}/{len(topics)}] {topic['number']} {topic['name']}")
        if progress_callback:
            progress_callback(idx + 1, len(topics), topic['name'])

        chapter_id = _make_chapter_id(doc_id, idx)
        try:
            chapter = {
                'id': chapter_id,
                'number': topic['number'],
                'name': topic['name'],
                'content': topic['content'],
                'learning_goals': '',
            }
            kg_data = extract_kg_for_chapter(chapter, client, subject_hint=subject_hint)

            db.save_chapter(
                chapter_id,
                topic['number'],
                topic['name'],
                topic['content'],
                '',
                doc_id=doc_id,
            )
            db.save_kg(chapter_id, kg_data)

            n_c = len(kg_data.get('concepts', []))
            n_r = len(kg_data.get('relations', []))
            n_k = len(kg_data.get('key_points', []))
            print(f"  [OK] {n_c} 个概念 | {n_r} 条关系 | {n_k} 个重点")
            success += 1

            if idx < len(topics) - 1:
                time.sleep(0.8)   # 避免触发限速

        except Exception as exc:
            print(f"  [FAIL] {exc}")

    print(f"\n[SlidesKG] 完成: {success}/{len(topics)} 个主题组已提取 KG\n")
    return success


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _make_chapter_id(doc_id: str, topic_idx: int) -> int:
    """
    根据 doc_id + topic_idx 生成稳定正整数 chapter_id。
    使用 SHA-256 哈希确保不与教材小整数 ID 冲突（偏移到 10_000_000+）。
    """
    raw = f"slides::{doc_id}::{topic_idx}"
    h = int(hashlib.sha256(raw.encode()).hexdigest()[:12], 16)
    return (h % 90_000_000_000) + 10_000_000


def _int_to_cn(n: int) -> str:
    """1-19 转中文数字（仅供编号标注）。"""
    if 1 <= n <= 9:
        return _CN_DIGITS[n]
    if n == 10:
        return '十'
    if 11 <= n <= 19:
        return '十' + _CN_DIGITS[n - 10]
    return str(n)
