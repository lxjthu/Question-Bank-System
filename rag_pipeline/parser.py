"""MD 文档解析：按章节切分，提取学习目标。"""
import re
from pathlib import Path
from .config import MD_FILE, MAX_CHAPTER_CHARS

# 匹配 # 或 ## 第X章 标题（第十五章 OCR 为单个 #）
_CHAPTER_RE = re.compile(
    r'^#{1,2} (第[一二三四五六七八九十百]+章)\s*(.+)$',
    re.MULTILINE,
)
# 匹配导论（## 导论）
_INTRO_RE = re.compile(r'^## 导论\s*$', re.MULTILINE)
# 匹配学习目标段落（OCR 可能在【前多一个字符）
_GOAL_RE = re.compile(
    r'^## [^\n【]*【学习目标】[^\n]*\n(.*?)(?=\n## |\n# |\Z)',
    re.MULTILINE | re.DOTALL,
)


def _truncate(content: str, max_chars: int) -> str:
    """超长时保留首尾，中间省略。"""
    if len(content) <= max_chars:
        return content
    half = max_chars // 2
    return (
        content[:half]
        + "\n\n[...内容过长，中间部分已省略以控制 token 用量...]\n\n"
        + content[-half:]
    )


def _extract_goals(text: str) -> str:
    m = _GOAL_RE.search(text)
    return m.group(1).strip() if m else ""


def parse_md(md_file=None) -> list[dict]:
    """
    解析 MD 文件，返回章节列表：
    [
        {
            'id': int,          # 0=导论, 1=第一章, ...
            'number': str,      # '导论' / '第一章'
            'name': str,        # '农业经营制度'
            'content': str,     # 截断后的文本（用于 API）
            'learning_goals': str,
            'full_length': int, # 原始字符数
        },
        ...
    ]
    """
    path = Path(md_file or MD_FILE)
    text = path.read_text(encoding="utf-8")

    # 收集所有章节起始位置：(number, name, start)
    starts: list[tuple[str, str, int]] = []

    intro_m = _INTRO_RE.search(text)
    if intro_m:
        starts.append(("导论", "导论", intro_m.start()))

    for m in _CHAPTER_RE.finditer(text):
        starts.append((m.group(1), m.group(2).strip(), m.start()))

    chapters = []
    for i, (number, name, start) in enumerate(starts):
        end = starts[i + 1][2] if i + 1 < len(starts) else len(text)
        raw = text[start:end]
        chapters.append(
            {
                "id": i,
                "number": number,
                "name": name,
                "content": _truncate(raw, MAX_CHAPTER_CHARS),
                "learning_goals": _extract_goals(raw),
                "full_length": len(raw),
            }
        )

    return chapters


def preview_chapters(chapters: list[dict]) -> None:
    print(f"\n共解析出 {len(chapters)} 个章节：\n")
    for ch in chapters:
        goal_preview = (
            ch["learning_goals"][:60].replace("\n", " ") + "..."
            if ch["learning_goals"]
            else "（无）"
        )
        trunc_mark = " [截断]" if ch["full_length"] > MAX_CHAPTER_CHARS else ""
        print(
            f"  [{ch['id']:2d}] {ch['number']} {ch['name'][:22]:<22}"
            f" | {ch['full_length']:>6,} 字{trunc_mark}"
        )
        print(f"       学习目标: {goal_preview}")
    print()
