"""RAG API Blueprint — AI 智能出题后端（简化版：仅 DeepSeek 直出模式）。

支持文件格式：.md / .txt / .docx
不依赖向量库、嵌入模型、OCR 服务。

端点：
  GET    /api/rag/ds-docs                    列出所有 DS 文档
  DELETE /api/rag/ds-docs/<doc_id>           删除文档
  POST   /api/rag/ds-upload                  上传并解析章节（.md/.txt/.docx）
  POST   /api/rag/ds-extract/<doc_id>        异步提取知识点（DeepSeek）
  GET    /api/rag/ds-tasks/<task_id>         轮询提取任务状态
  POST   /api/rag/ds-tasks/<task_id>/pause   暂停提取任务
  GET    /api/rag/ds-docs/<doc_id>/kps       获取章节+知识点列表
  GET    /api/rag/ds-graph                   知识图谱数据（D3 可视化）
  POST   /api/rag/ds-generate                基于知识图谱出题（DeepSeek）
  GET    /api/rag/config                     读取 DeepSeek API 配置
  PUT    /api/rag/config                     写入 DeepSeek API 配置
"""
from __future__ import annotations

import os
import uuid
import sqlite3
import threading
import json as _json_mod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from flask import Blueprint, request, jsonify

rag_bp = Blueprint('rag', __name__)

# DS 直出模式后台任务状态表  {task_id: {...}}
_ds_tasks: dict = {}


# ── 路径工具 ──────────────────────────────────────────────────────────────────

def _project_root() -> Path:
    return Path(__file__).parent.parent


def _data_root() -> Path:
    """返回用户可写数据根目录。
    打包版（PyInstaller）由 launcher.py 预先写入 EXAM_DATA_DIR；
    普通运行时退回项目根目录。
    """
    env_dir = os.environ.get('EXAM_DATA_DIR')
    return Path(env_dir) if env_dir else _project_root()


def _upload_dir() -> Path:
    return _data_root() / 'rag_uploads'


def _ensure_upload_dir():
    _upload_dir().mkdir(parents=True, exist_ok=True)


# ── .env 读写工具 ─────────────────────────────────────────────────────────────

def _env_path() -> Path:
    return _data_root() / ".env"


def _read_env_vars(*keys) -> dict:
    """从 .env 文件读取指定 key，不影响进程环境变量。"""
    try:
        from dotenv import dotenv_values
        vals = dotenv_values(str(_env_path())) if _env_path().exists() else {}
    except ImportError:
        vals = {}
    return {k: vals.get(k, '') for k in keys}


def _write_env_vars(updates: dict) -> None:
    """原地更新 .env 文件中的 key=value 行；不存在的 key 追加到末尾。"""
    env_file = _env_path()
    if env_file.exists():
        lines = env_file.read_text(encoding='utf-8').splitlines(keepends=True)
    else:
        lines = []

    updated_keys: set = set()
    new_lines = []
    for line in lines:
        stripped = line.rstrip('\r\n')
        if not stripped or stripped.startswith('#'):
            new_lines.append(line if line.endswith('\n') else line + '\n')
            continue
        if '=' in stripped:
            key = stripped.split('=', 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line if line.endswith('\n') else line + '\n')

    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}\n")

    env_file.write_text(''.join(new_lines), encoding='utf-8')


def _get_deepseek_key() -> str:
    """从 .env 或环境变量读取 DeepSeek API Key。"""
    try:
        from dotenv import dotenv_values
        env_file = _env_path()
        env_vals = dotenv_values(env_file) if env_file.exists() else {}
    except ImportError:
        env_vals = {}
    return (
        env_vals.get('DEEPSEEK_API_KEY')
        or env_vals.get('DEEPSEEK_TOKEN')
        or os.environ.get('DEEPSEEK_API_KEY', '')
        or os.environ.get('DEEPSEEK_TOKEN', '')
    )


# ── DS 数据库 ─────────────────────────────────────────────────────────────────

def _ds_db_path() -> Path:
    return _data_root() / "ds_knowledge.db"


def _ds_db_conn():
    conn = sqlite3.connect(str(_ds_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def _init_ds_db():
    with _ds_db_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ds_docs (
                doc_id            TEXT PRIMARY KEY,
                filename          TEXT,
                subject           TEXT,
                status            TEXT DEFAULT 'uploaded',
                error_msg         TEXT,
                created_at        TEXT,
                architecture_json TEXT DEFAULT '{}'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ds_chapters (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id               TEXT,
                chapter_num          INTEGER,
                chapter_name         TEXT,
                parent_chapter_num   INTEGER DEFAULT 0,
                parent_chapter_name  TEXT DEFAULT '',
                raw_text             TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ds_kps (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id         TEXT,
                chapter_name   TEXT,
                chapter_num    INTEGER,
                kp_name        TEXT,
                kp_content     TEXT,
                relations_json TEXT DEFAULT '[]'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ds_doc_refs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id      TEXT NOT NULL,
                chapter_num INTEGER,
                ref_text    TEXT
            )
        """)
        conn.commit()
        # 迁移：旧库自动补充缺失列
        for migration_sql in [
            "ALTER TABLE ds_docs ADD COLUMN architecture_json TEXT DEFAULT '{}'",
            "ALTER TABLE ds_chapters ADD COLUMN parent_chapter_num INTEGER DEFAULT 0",
            "ALTER TABLE ds_chapters ADD COLUMN parent_chapter_name TEXT DEFAULT ''",
            "ALTER TABLE ds_kps ADD COLUMN teaching_focus TEXT DEFAULT ''",
            "ALTER TABLE ds_kps ADD COLUMN knowledge_type TEXT DEFAULT ''",
            "ALTER TABLE ds_kps ADD COLUMN cognitive_dimension TEXT DEFAULT ''",
            "ALTER TABLE ds_chapters ADD COLUMN section_name TEXT DEFAULT ''",
            "ALTER TABLE ds_kps ADD COLUMN section_name TEXT DEFAULT ''",
        ]:
            try:
                conn.execute(migration_sql)
                conn.commit()
            except Exception:
                pass  # 列已存在，忽略
        # 迁移：将旧库中已有的主要参考文献章节迁移到 ds_doc_refs
        try:
            ref_rows = conn.execute(
                "SELECT doc_id, chapter_num, raw_text FROM ds_chapters "
                "WHERE chapter_name LIKE '%参考文献%'"
            ).fetchall()
            for r in ref_rows:
                exists = conn.execute(
                    "SELECT 1 FROM ds_doc_refs WHERE doc_id=? AND chapter_num=?",
                    (r['doc_id'], r['chapter_num']),
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO ds_doc_refs (doc_id, chapter_num, ref_text) VALUES (?,?,?)",
                        (r['doc_id'], r['chapter_num'], r['raw_text']),
                    )
            conn.commit()
        except Exception:
            pass


# ── 非内容章节过滤 ────────────────────────────────────────────────────────────
# 教材中常见的结构性章节——不是实质知识内容，不导出到知识点 Excel
# 这些章节保留在 ds_chapters 中供 DeepSeek 提取时参考
_NON_CONTENT_KEYWORDS = ('学习目标', '小结', '关键词', '复习思考题', '思考题', '参考文献', '练习题')


def _is_non_content(name: str) -> bool:
    """判断章节名称是否为非内容性结构节（学习目标/小结/关键词/复习思考题/参考文献等）。"""
    if not name:
        return False
    cleaned = name.strip().strip('【】').strip()
    return any(kw in cleaned for kw in _NON_CONTENT_KEYWORDS)


# ── 文档解析工具 ──────────────────────────────────────────────────────────────

def _clean_ocr_md(text: str) -> tuple:
    """清理 Markdown 文本中的 OCR 产物（对普通文档无副作用）。

    返回 (cleaned_text: str, had_page_markers: bool)
    """
    import re

    # 去掉 pipeline 文件头（# 文件名 + > Source/Generated/Chunks 元信息 + ---）
    header_match = re.search(r'^---[ \t]*\n', text, re.MULTILINE)
    if header_match:
        before_sep = text[:header_match.start()]
        if re.search(r'^>\s*(?:Source|Generated|Chunks)', before_sep, re.MULTILINE):
            text = text[header_match.end():]

    # 去掉页码标记行（## Page N、## 第N页 等）
    page_pattern = re.compile(
        r'^##\s+(?:Page\s+\d+|第\s*\d+\s*[页面])\s*$',
        re.MULTILINE | re.IGNORECASE,
    )
    cleaned, n_markers = page_pattern.subn('', text)

    if n_markers > 0:
        cleaned = re.sub(r'\n[ \t]*---[ \t]*\n', '\n', cleaned)

    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip(), n_markers > 0


def _analyze_doc_structure(text: str) -> tuple:
    """扫描文档所有标题（#/##/###/####），分析层级结构。

    返回 (chapter_level: int, section_level: int | None)

    规则：
    - chapter_level：出现次数 >= 2 的最高级别（数字最小）标题
      仅出现 1 次的最顶层标题视为文档总标题，跳过继续往下找
    - section_level：比 chapter_level 更深的第一个存在的标题级别
      若无更深级别则为 None
    """
    import re
    level_counts: dict = {}
    for level in (1, 2, 3, 4):
        pat = re.compile(r'^#{' + str(level) + r'}(?!#)\s+\S', re.MULTILINE)
        count = len(pat.findall(text))
        if count > 0:
            level_counts[level] = count

    if not level_counts:
        return 1, None

    sorted_levels = sorted(level_counts.keys())

    # 章级别：找第一个出现 >= 2 次的最高级别
    chapter_level = sorted_levels[-1]  # 兜底：用最深的
    for lv in sorted_levels:
        if level_counts[lv] >= 2:
            chapter_level = lv
            break

    # 节级别：比章更深的下一个存在的级别
    section_level = None
    for lv in sorted_levels:
        if lv > chapter_level:
            section_level = lv
            break

    return chapter_level, section_level


def _extract_all_headings(text: str) -> list:
    """从文档文本中提取所有 h1-h6 标题，返回列表。

    返回: [{'level': int, 'text': str}, ...]  按出现顺序排列
    """
    import re
    headings = []
    for level in range(1, 7):
        pat = re.compile(r'^#{' + str(level) + r'}(?!#)\s+(.+)', re.MULTILINE)
        for m in pat.finditer(text):
            headings.append({'level': level, 'text': m.group(1).strip(), 'pos': m.start()})
    # 按文档位置排序
    headings.sort(key=lambda h: h['pos'])
    return headings


def _detect_doc_type(headings: list) -> str:
    """根据标题层级分布启发式判断文档类型。

    返回: 'ppt'（演示文稿型）或 'textbook'（教材/讲义型）

    PPT 型特征：
    - H1 出现 >= 3 次（多张幻灯片标题），且 H1 数量占所有标题的 >= 20%
    - 总层级数 <= 3 且最深层级 <= 3（通常只有 H1+H2，最多 H1+H2+H3）
    教材型：其余所有情况。
    """
    if not headings:
        return 'textbook'
    from collections import Counter as _C
    level_counts = _C(h['level'] for h in headings)
    total = len(headings)
    h1_count = level_counts.get(1, 0)
    max_level = max(level_counts.keys())
    distinct_levels = len(level_counts)
    is_ppt = (
        h1_count >= 3
        and h1_count / total >= 0.20
        and distinct_levels <= 3
        and max_level <= 3
    )
    return 'ppt' if is_ppt else 'textbook'


def _clean_headings_with_ai(headings: list, subject: str, ds_client) -> dict:
    """调用 DeepSeek 对标题列表进行清洗，返回层级映射、无效标题集合和提取节点列表。

    返回:
    {
        'chapter_level': int,          # 代表"章"的 h 级别 (1-4)
        'section_level': int | None,   # 代表"节"的 h 级别
        'non_content_texts': set,      # 应排除的标题文本（模糊匹配）
        'extraction_nodes': list,      # 适合提取知识点的标题文本列表（有序）
    }
    失败时返回 None（调用方降级到本地分析）。
    """
    import json as _json

    if not headings:
        return None

    # 只用前 60 个标题（防止 prompt 过长）
    sample = headings[:60]
    heading_list = '\n'.join(f"H{h['level']}: {h['text']}" for h in sample)

    # 自动检测文档类型，生成差异化 prompt
    doc_type = _detect_doc_type(headings)

    if doc_type == 'ppt':
        prompt = (
            '你是演示文稿结构分析专家。以下是一份 PPT 课件转换后的 Markdown 文件的所有标题：\n\n'
            f'【学科/科目】：{subject or "（未指定）"}\n\n'
            '【文档类型】：演示文稿（PPT）转换文档，H1 为幻灯片主标题，H2 为幻灯片内子项。\n\n'
            '【标题列表】：\n'
            f'{heading_list}\n\n'
            '请完成以下分析，直接输出纯 JSON（不加代码块）：\n'
            '{\n'
            '  "chapter_level": 1,\n'
            '  "section_level": 2,\n'
            '  "non_content_texts": ["仅限H1级别的过渡/封面幻灯片标题"],\n'
            '  "extraction_nodes": ["有实质知识内容的H1幻灯片标题，按文档顺序"]\n'
            '}\n\n'
            '【重要规则】：non_content_texts 和 extraction_nodes 中，只放 H1 级别的标题。\n'
            'H2 级别子项无论内容如何，都不放入这两个列表。\n\n'
            'non_content_texts（仅限H1）判断标准——将以下类型的H1标题放入此列表：\n'
            '- 课程封面/总标题页：课程名称本身（无任何实质讲授内容的总封面幻灯片）\n'
            '- 固定过渡套语：目录/引言/学习目标/本章小结/本章回顾/谢谢/再见/'
            '思考与讨论/课堂讨论/课程结束 等\n'
            '- 以 ? 或 ？ 结尾的 H1 标题（纯引导性提问页，该幻灯片本身不讲授知识）\n'
            '- 与学科完全无关的网络内容/新闻标题/生活故事\n'
            '- 完全重复的 H1 标题（某H1文本与前面已出现的H1完全相同，则将重复的放入此列表）\n\n'
            '【注意】：凡是描述课程内容、阶段工作、分析方法、知识点的H1标题，\n'
            '哪怕带有疑问词（如"为什么...""什么是...但不以?结尾"），只要本身是知识点描述，\n'
            '就应放入 extraction_nodes 而非 non_content_texts。\n\n'
            'extraction_nodes（仅限H1）选取原则：\n'
            '- 选取有实质学科知识内容的H1幻灯片标题（有H2子项说明，或标题本身描述知识点）\n'
            '- non_content_texts 中的H1不放入此列表\n'
            '- 标题文本请原样复制，不要修改'
        )
    else:
        prompt = (
            '你是教材文档结构分析专家。以下是一份教材的所有 Markdown 标题（含层级）：\n\n'
            f'【学科/科目】：{subject or "（未指定）"}\n\n'
            '【标题列表】：\n'
            f'{heading_list}\n\n'
            '请完成以下分析，直接输出纯 JSON（不加代码块）：\n'
            '{\n'
            '  "chapter_level": 章标题的H级别数字,\n'
            '  "section_level": 节标题的H级别数字（若无节则与chapter_level相同）,\n'
            '  "non_content_texts": ["不是章节内容的标题：页码/结构性标题/正文误标/正文句子等"],\n'
            '  "extraction_nodes": ["适合提取知识点的标题文本，按文档顺序"]\n'
            '}\n\n'
            'extraction_nodes 选取原则：\n'
            '- 粒度目标：每个节点对应1-3个知识点的内容（通常100-500字）\n'
            '- 若某节（H3）包含多个子节（H4），应以H4子节为节点，而非选整个H3节\n'
            '- H5/H6 的细碎列表项（如"1. 完善土地流转..."）通常太细，不单独列为节点\n'
            '- 若某节没有子节，该节标题本身就是节点\n'
            '- non_content_texts 中的标题不放入 extraction_nodes\n'
            '- 标题文本请原样复制，不要修改\n\n'
            'non_content_texts 包含：\n'
            '- 结构性标题：小结/关键词/复习思考题/参考文献/学习目标/章/编 等\n'
            '- 误标的正文句子：明显是句子、定义引导语（如"这一框架的内涵是："）\n'
            '- 页码、图表编号等非章节标题'
        )

    try:
        resp = ds_client.chat.completions.create(
            model='deepseek-chat',
            messages=[
                {'role': 'system', 'content': '你是文档结构分析专家，善于识别章节层级与无效标题。'},
                {'role': 'user', 'content': prompt},
            ],
            max_tokens=1200 if doc_type == 'ppt' else 800,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith('```'):
            raw = '\n'.join(raw.split('\n')[1:])
        if raw.endswith('```'):
            raw = '\n'.join(raw.split('\n')[:-1])
        parsed = _json.loads(raw.strip())

        chapter_level = int(parsed.get('chapter_level', 2))
        section_level_val = parsed.get('section_level')
        section_level = int(section_level_val) if section_level_val else chapter_level
        if section_level < chapter_level:
            section_level = chapter_level

        # PPT 文档：强制覆盖层级（防止 AI 未遵循 prompt 中的约定）
        if doc_type == 'ppt':
            chapter_level = 1
            section_level = 2

        non_texts = set(str(t).strip() for t in parsed.get('non_content_texts', []) if t)
        extraction_nodes = [str(n).strip() for n in parsed.get('extraction_nodes', []) if n]

        # extraction_nodes 不能为空（否则降级）
        if not extraction_nodes:
            return None

        # 合法性校验
        if chapter_level not in range(1, 5):
            chapter_level = 2

        # 后处理：收集被展开/归并时遗漏的节点，确保完整性
        heading_level_map = {h['text']: h['level'] for h in headings}
        child_level = section_level + 1  # H4（若 section=H3）

        def _collect_children(node_text):
            """返回某 section_level 节点的所有 child_level 子节点文本列表。
            跳过 non_content_texts 标题（不视其为边界），直到遇到真正的同级或更高级标题。"""
            pos = next((i for i, h in enumerate(headings) if h['text'] == node_text), None)
            if pos is None:
                return []
            kids = []
            for j in range(pos + 1, len(headings)):
                h = headings[j]
                if h['text'] in non_texts:
                    continue  # 非内容标题不形成边界
                if h['level'] <= section_level:
                    break
                if h['level'] == child_level:
                    kids.append(h['text'])
            return kids

        # 1) 若所有节点均在 section_level，展开为 child_level 子节点
        node_levels = [heading_level_map.get(n, 0) for n in extraction_nodes]
        all_at_section = all(lv == section_level for lv in node_levels if lv > 0)
        if all_at_section and child_level <= 6:
            expanded = []
            for node in extraction_nodes:
                kids = _collect_children(node)
                expanded.extend(kids) if kids else expanded.append(node)
            extraction_nodes = expanded

        # 2) 去除父子重复：若某 section_level 父节点的子节点也在列表中，删除父节点
        node_set_final = set(extraction_nodes)
        filtered = []
        removed_parents = []  # 记录被删除的 H3 父节点，用于完整性补充
        for node in extraction_nodes:
            nlv = heading_level_map.get(node, 0)
            if nlv == section_level:
                kids = _collect_children(node)
                if any(k in node_set_final for k in kids):
                    removed_parents.append(node)
                    continue  # 跳过父节点
            filtered.append(node)
        extraction_nodes = filtered

        # 3) 完整性补充：对每个被删除的父节点，补上其在文档中但未被 DeepSeek 返回的子节点
        existing_set = set(extraction_nodes)
        extras = []
        for parent in removed_parents:
            for kid in _collect_children(parent):
                if kid not in existing_set and kid not in non_texts:
                    extras.append((parent, kid))
        # 按文档顺序将缺失子节点插入正确位置
        if extras:
            # 重建有序列表（按 headings 中的顺序）
            all_valid = set(extraction_nodes) | {kid for _, kid in extras}
            ordered = []
            for h in headings:
                if h['text'] in all_valid:
                    ordered.append(h['text'])
                    all_valid.discard(h['text'])
            extraction_nodes = ordered

        if not extraction_nodes:
            return None

        return {
            'chapter_level':     chapter_level,
            'section_level':     section_level,
            'non_content_texts': non_texts,
            'extraction_nodes':  extraction_nodes,  # 有序列表
        }
    except Exception:
        return None


def _parse_md_multilevel(text: str, hierarchy: dict) -> list:
    """将 Markdown 文本按最多3层（章/节/小节）切分，返回叶子级别条目列表。

    hierarchy 来自 _clean_headings_with_ai 或本地分析结果：
    {
        'chapter_level': int,
        'section_level': int | None,
        'leaf_level': int,             # 提取单元级别
        'non_content_texts': set,      # 要过滤掉的标题文本
    }

    返回格式（与 _parse_md_to_sections 兼容 + 新增 section_name）：
    [
        {
            'parent_chapter_num':  int,   # L1 章序号
            'parent_chapter_name': str,   # L1 章名
            'chapter_name':        str,   # L2 节名（若无节则等于章名）
            'section_name':        str,   # L3 小节名（叶子；2级文档为空）
            'num':                 int,   # 全局叶子序号
            'text':                str,   # 叶子原文
        }, ...
    ]
    """
    import re

    chapter_level = hierarchy.get('chapter_level', 2)
    section_level = hierarchy.get('section_level')
    leaf_level = hierarchy.get('leaf_level', section_level or chapter_level)
    non_content = hierarchy.get('non_content_texts', set())

    # 过滤非内容标题：
    #   - 章级别（<= chapter_level）的假标题：只删除标题行，保留其后内容
    #     （正文句子被误标为章标题，删标题行即可，其下内容仍属前面的章节）
    #   - 节级别（> chapter_level）的结构性标题（小结/关键词等）：删除标题行 + 内容
    if non_content:
        lines_out = []
        skip_until_level = None
        for line in text.split('\n'):
            m = re.match(r'^(#{1,6})(?!#)\s+(.+)', line)
            if m:
                lvl = len(m.group(1))
                heading_text = m.group(2).strip()
                is_non = heading_text in non_content or any(
                    kw in heading_text for kw in _NON_CONTENT_KEYWORDS
                )
                if is_non:
                    if lvl <= chapter_level:
                        # 章级别的假标题：只跳过这一行，不跳过后续内容
                        continue
                    else:
                        # 节级别的结构性标题：跳过标题行 + 其后内容
                        skip_until_level = lvl
                        continue
                else:
                    if skip_until_level is not None and lvl <= skip_until_level:
                        skip_until_level = None
            if skip_until_level is not None:
                continue
            lines_out.append(line)
        text = '\n'.join(lines_out)

    ch_pat = re.compile(r'^#{' + str(chapter_level) + r'}(?!#)\s+(.+)', re.MULTILINE)
    sec_pat = (
        re.compile(r'^#{' + str(section_level) + r'}(?!#)\s+(.+)', re.MULTILINE)
        if section_level and section_level > chapter_level else None
    )
    leaf_pat = (
        re.compile(r'^#{' + str(leaf_level) + r'}(?!#)\s+(.+)', re.MULTILINE)
        if leaf_level and leaf_level > (section_level or chapter_level) else None
    )

    ch_matches = list(ch_pat.finditer(text))
    if not ch_matches:
        body = text.strip()
        return [
            {'parent_chapter_num': 1, 'parent_chapter_name': '全文',
             'chapter_name': '全文', 'section_name': '',
             'num': 1, 'text': body}
        ] if body else []

    result = []
    global_num = 0

    def _add_leaf(parent_ch_num, parent_ch_name, sec_name, leaf_name, body):
        nonlocal global_num
        body = body.strip()
        if not body:
            return
        global_num += 1
        result.append({
            'parent_chapter_num':  parent_ch_num,
            'parent_chapter_name': parent_ch_name,
            'chapter_name':        sec_name,    # L2 节名（存入 ds_chapters.chapter_name）
            'section_name':        leaf_name,   # L3 小节名（存入 ds_chapters.section_name）
            'num':                 global_num,
            'text':                body,
        })

    for ch_idx, ch_m in enumerate(ch_matches):
        ch_name = ch_m.group(1).strip()
        ch_num = ch_idx + 1
        ch_start = ch_m.end()
        ch_end = ch_matches[ch_idx + 1].start() if ch_idx + 1 < len(ch_matches) else len(text)
        ch_body = text[ch_start:ch_end]

        if sec_pat is None:
            # 单级文档：章即叶子
            _add_leaf(ch_num, ch_name, ch_name, '', ch_body)
            continue

        sec_matches = list(sec_pat.finditer(ch_body))
        if not sec_matches:
            # 章内无节 → 章整体作为叶子
            _add_leaf(ch_num, ch_name, ch_name, '', ch_body)
            continue

        # 章导言（第一个节之前的内容）
        intro = ch_body[:sec_matches[0].start()].strip()
        if intro:
            _add_leaf(ch_num, ch_name, ch_name, '', intro)

        for s_idx, sm in enumerate(sec_matches):
            sec_name = sm.group(1).strip()
            s_start = sm.end()
            s_end = sec_matches[s_idx + 1].start() if s_idx + 1 < len(sec_matches) else len(ch_body)
            sec_body = ch_body[s_start:s_end]

            if leaf_pat is None:
                # 两级文档：节即叶子
                _add_leaf(ch_num, ch_name, sec_name, '', sec_body)
                continue

            leaf_matches = list(leaf_pat.finditer(sec_body))
            if not leaf_matches:
                # 节内无小节 → 节整体作为叶子
                _add_leaf(ch_num, ch_name, sec_name, '', sec_body)
                continue

            # 节导言
            node_intro = sec_body[:leaf_matches[0].start()].strip()
            if node_intro:
                _add_leaf(ch_num, ch_name, sec_name, '', node_intro)

            for l_idx, lm in enumerate(leaf_matches):
                leaf_name = lm.group(1).strip()
                l_start = lm.end()
                l_end = leaf_matches[l_idx + 1].start() if l_idx + 1 < len(leaf_matches) else len(sec_body)
                leaf_body = sec_body[l_start:l_end]
                _add_leaf(ch_num, ch_name, sec_name, leaf_name, leaf_body)

    return result


def _parse_md_by_nodes(text: str, hierarchy: dict) -> list:
    """按 extraction_nodes 列表切分文档，返回叶子节点列表。

    hierarchy 必须包含 extraction_nodes 字段（来自 Layer 0）。
    若不含该字段，自动降级到 _parse_md_multilevel。

    返回格式与 _parse_md_multilevel 相同：
    [
        {
            'parent_chapter_num':  int,
            'parent_chapter_name': str,
            'chapter_name':        str,
            'section_name':        str,
            'num':                 int,
            'text':                str,
        }, ...
    ]
    """
    import re

    extraction_nodes = hierarchy.get('extraction_nodes')
    if not extraction_nodes:
        return _parse_md_multilevel(text, hierarchy)

    chapter_level = hierarchy.get('chapter_level', 2)
    section_level = hierarchy.get('section_level') or chapter_level
    non_content = hierarchy.get('non_content_texts', set())

    # Step 1: 过滤 non_content_texts（复用 _parse_md_multilevel 相同逻辑）
    if non_content:
        lines_out = []
        skip_until_level = None
        for line in text.split('\n'):
            m = re.match(r'^(#{1,6})(?!#)\s+(.+)', line)
            if m:
                lvl = len(m.group(1))
                heading_text = m.group(2).strip()
                is_non = heading_text in non_content or any(
                    kw in heading_text for kw in _NON_CONTENT_KEYWORDS
                )
                if is_non:
                    if lvl <= chapter_level:
                        continue
                    else:
                        skip_until_level = lvl
                        continue
                else:
                    if skip_until_level is not None and lvl <= skip_until_level:
                        skip_until_level = None
            if skip_until_level is not None:
                continue
            lines_out.append(line)
        text = '\n'.join(lines_out)

    # Step 2: 提取所有标题及其在文本中的位置
    all_headings = []
    for m in re.finditer(r'^(#{1,6})(?!#)\s+(.+)', text, re.MULTILINE):
        all_headings.append({
            'level': len(m.group(1)),
            'text':  m.group(2).strip(),
            'start': m.start(),
            'end':   m.end(),
        })

    if not all_headings:
        body = text.strip()
        return [
            {'parent_chapter_num': 1, 'parent_chapter_name': '全文',
             'chapter_name': '全文', 'section_name': '',
             'num': 1, 'text': body}
        ] if body else []

    # Step 3: 建立节点集合
    node_set = set(extraction_nodes)

    # Step 4: 按文档顺序追踪当前章/节
    result = []
    global_num = 0
    current_chapter_name = ''
    current_chapter_num = 0
    current_section_name = ''

    # 标记每个标题是否为提取节点
    for h in all_headings:
        h['is_node'] = h['text'] in node_set

    # 找出所有节点标题（保持文档顺序）
    node_headings = [h for h in all_headings if h['is_node']]

    # 预先更新章/节上下文：遍历一次记录每个 node 对应的章/节
    def _get_context_at(node_idx_in_all):
        """返回该标题之前最近的章名和节名"""
        ch_name = ''
        ch_num = 0
        sec_name = ''
        for i in range(node_idx_in_all):
            h = all_headings[i]
            if h['level'] == chapter_level:
                ch_name = h['text']
                ch_num += 1
                sec_name = ''
            elif section_level > chapter_level and h['level'] == section_level:
                sec_name = h['text']
        return ch_name, ch_num, sec_name

    # 重新统计章序号（只计非 non_content 的章标题）
    ch_counter = 0
    ch_map = {}  # heading start → chapter_num
    for h in all_headings:
        if h['level'] == chapter_level and h['text'] not in non_content:
            ch_counter += 1
            ch_map[h['start']] = ch_counter

    # Step 5: 对每个 is_node=True 的标题提取内容
    for ni, node_h in enumerate(node_headings):
        # 找该标题在 all_headings 中的索引，用于上下文追踪
        node_all_idx = next(i for i, h in enumerate(all_headings) if h['start'] == node_h['start'])

        # 更新章/节上下文（跳过 non_content 标题，避免误标标题污染章名）
        # 注意：节点本身若在 section_level 不更新 current_section_name，
        # 避免 chapter_name = section_name = 节点自身（层级关系丢失）
        for i in range(node_all_idx + 1):
            h = all_headings[i]
            if h['text'] in non_content:
                continue
            if h['level'] == chapter_level:
                current_chapter_name = h['text']
                current_chapter_num = ch_map.get(h['start'], current_chapter_num)
                current_section_name = ''
            elif section_level > chapter_level and h['level'] == section_level and i < node_all_idx:
                # 若当前节点(node_h)与 h 处于相同 level 且 h 也是提取节点
                # 则二者为同级兄弟节点，h 不应作为 node_h 的节父
                is_sibling_node = (node_h['level'] == section_level and h['text'] in node_set)
                if not is_sibling_node:
                    current_section_name = h['text']

        # 计算内容边界
        content_start = node_h['end']

        # end 候选：下一个 is_node 标题 OR 下一个 level <= section_level 的标题 OR 文档末尾
        end_candidates = [len(text)]

        # 下一个 node 标题
        if ni + 1 < len(node_headings):
            end_candidates.append(node_headings[ni + 1]['start'])

        # 下一个 level <= node_h['level'] 的非节点标题（同级或更高层级才作为边界）
        # 用 node_h['level'] 而非 section_level，确保 PPT H1 节点的内容包含其下所有 H2 子项，
        # 同时对教材 H4 节点仍正确地在非节点 H3/H4 处截止
        for h in all_headings:
            if h['start'] > node_h['start'] and h['level'] <= node_h['level'] and not h['is_node']:
                end_candidates.append(h['start'])
                break

        content_end = min(end_candidates)
        body = text[content_start:content_end].strip()
        if not body:
            continue

        global_num += 1
        result.append({
            'parent_chapter_num':  current_chapter_num,
            'parent_chapter_name': current_chapter_name,
            'chapter_name':        current_section_name or current_chapter_name,
            'section_name':        node_h['text'],
            'num':                 global_num,
            'text':                body,
        })

    # Step 6: 节内导言处理（section 第一个 extraction_node 之前有实质文本）
    # 在每个节（section_level）下，若第一个节点前有 >50 字的内容，作为额外叶子
    # 此逻辑已通过上方的 end 候选边界隐式处理；若需要显式导言可在此扩展

    return result


def _parse_md_to_sections(text: str, chapter_level: int, section_level) -> list:
    """将 Markdown 文本按章/节两级切分，返回节级别条目列表。

    若无节级别（section_level is None），则每章整体作为一个条目。

    返回:
    [
        {
            'parent_chapter_num':  int,   # 父章序号（1-based）
            'parent_chapter_name': str,   # 父章标题（用于分组与知识图谱）
            'num':                 int,   # 全局节序号（1-based，存入 chapter_num）
            'name':                str,   # 节标题（或章标题，若无子节）
            'text':                str,   # 节内容文本
        }, ...
    ]
    过滤掉无实质内容的条目。
    """
    import re
    ch_pat = re.compile(r'^#{' + str(chapter_level) + r'}(?!#)\s+(.+)', re.MULTILINE)
    sec_pat = (
        re.compile(r'^#{' + str(section_level) + r'}(?!#)\s+(.+)', re.MULTILINE)
        if section_level else None
    )

    ch_matches = list(ch_pat.finditer(text))

    if not ch_matches:
        body = text.strip()
        return [
            {'parent_chapter_num': 1, 'parent_chapter_name': '全文',
             'num': 1, 'name': '全文', 'text': body}
        ] if body else []

    result = []
    global_num = 0

    for ch_idx, ch_m in enumerate(ch_matches):
        ch_name = ch_m.group(1).strip()
        ch_num = ch_idx + 1
        ch_content_start = ch_m.end()  # 章标题行结束位置（内容从此开始）
        ch_end = ch_matches[ch_idx + 1].start() if ch_idx + 1 < len(ch_matches) else len(text)
        ch_body = text[ch_content_start:ch_end]

        sec_matches = list(sec_pat.finditer(ch_body)) if sec_pat else []

        if sec_matches:
            # 章导言（第一个节标题之前的内容）
            intro = ch_body[:sec_matches[0].start()].strip()
            if intro:
                global_num += 1
                result.append({
                    'parent_chapter_num': ch_num,
                    'parent_chapter_name': ch_name,
                    'num': global_num,
                    'name': ch_name,  # 导言归入章名
                    'text': intro,
                })
            # 各子节
            for s_idx, sm in enumerate(sec_matches):
                sec_name = sm.group(1).strip()
                s_content_start = sm.end()
                s_end = sec_matches[s_idx + 1].start() if s_idx + 1 < len(sec_matches) else len(ch_body)
                sec_body = ch_body[s_content_start:s_end].strip()
                if sec_body:
                    global_num += 1
                    result.append({
                        'parent_chapter_num': ch_num,
                        'parent_chapter_name': ch_name,
                        'num': global_num,
                        'name': sec_name,
                        'text': sec_body,
                    })
        else:
            # 无子节，整章作为一个提取单元
            body = ch_body.strip()
            if body:
                global_num += 1
                result.append({
                    'parent_chapter_num': ch_num,
                    'parent_chapter_name': ch_name,
                    'num': global_num,
                    'name': ch_name,
                    'text': body,
                })

    return [r for r in result if r['text'].strip()]


def _detect_chapter_level(text_sample: str, subject: str, ds_client) -> int:
    """调用 DeepSeek 判断 Markdown 文档中哪个标题级别代表"章"。

    返回 1、2 或 3，失败时默认返回 1。
    """
    import json as _json

    prompt = (
        '请分析以下教材文档的部分内容，判断哪个 Markdown 标题级别代表"章"。\n\n'
        f'【学科/科目】：{subject or "（未指定）"}\n\n'
        '【说明】\n'
        '- 章是文档最高层的内容组织单元，通常含"第X章""Chapter X"或同等表述\n'
        '- 标题级别：# = 1级，## = 2级，### = 3级\n'
        '- 若文档无明显章级别，选择最接近章粒度的标题级别\n\n'
        f'【文档样本】：\n{text_sample[:2000]}\n\n'
        '请直接输出 JSON（不加代码块标记或其他文字）：\n'
        '{"chapter_level": 1, "reason": "简要说明（20字以内）"}'
    )
    try:
        resp = ds_client.chat.completions.create(
            model='deepseek-chat',
            messages=[
                {'role': 'system', 'content': '你是一位文档结构分析专家，善于识别教材的章节层级。'},
                {'role': 'user', 'content': prompt},
            ],
            max_tokens=120,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith('```'):
            raw = '\n'.join(raw.split('\n')[1:])
        if raw.endswith('```'):
            raw = '\n'.join(raw.split('\n')[:-1])
        parsed = _json.loads(raw.strip())
        level = int(parsed.get('chapter_level', 1))
        if level in (1, 2, 3):
            return level
    except Exception:
        pass
    return 1


def _parse_file_to_sections(filepath: Path, suffix: str) -> list:
    """从文件解析节级别列表，支持 .md / .txt / .docx。

    先分析标题层级结构，再按章/节两级切分。
    返回格式与 _parse_md_to_sections 一致。
    """
    if suffix in ('.md', '.txt'):
        text = filepath.read_text(encoding='utf-8', errors='replace')
        cleaned, _ = _clean_ocr_md(text)
        chapter_level, section_level = _analyze_doc_structure(cleaned)
        return _parse_md_to_sections(cleaned, chapter_level, section_level)
    if suffix == '.docx':
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(str(filepath))
            md_lines: list = []
            for para in doc.paragraphs:
                t = para.text.strip()
                if not t:
                    continue
                style = para.style.name if para.style else ''
                if 'Heading 1' in style or 'heading 1' in style.lower():
                    md_lines.append(f'# {t}')
                elif 'Heading 2' in style or 'heading 2' in style.lower():
                    md_lines.append(f'## {t}')
                elif 'Heading 3' in style or 'heading 3' in style.lower():
                    md_lines.append(f'### {t}')
                else:
                    md_lines.append(t)
            combined = '\n'.join(md_lines)
            cleaned, _ = _clean_ocr_md(combined)
            chapter_level, section_level = _analyze_doc_structure(cleaned)
            return _parse_md_to_sections(cleaned, chapter_level, section_level)
        except Exception:
            return []
    return []


# ── 提示词 ────────────────────────────────────────────────────────────────────

_DS_EXTRACT_SYSTEM = '你是一位专业的教材分析专家，擅长从教材中提取结构化知识图谱。'

# Layer 1：整体架构分析
_DS_ARCH_SYSTEM = '你是一位教材结构分析专家，善于从章节目录中提炼学科知识框架。'

_DS_ARCH_PROMPT = """请根据以下教材章节目录，分析文档的整体知识架构。

【学科/科目】：{subject}
【章节目录】：
{chapter_list}

请直接输出纯 JSON（不加代码块标记或任何其他文字）：
{{
  "document_summary": "整体内容概述（50字以内）",
  "core_framework": "核心知识框架描述，说明各章之间的逻辑关系（100字以内）",
  "chapters": [
    {{
      "num": 章节编号（整数）,
      "name": "章节名称",
      "themes": ["核心主题1", "核心主题2", "核心主题3"]
    }}
  ]
}}"""

# Layer 2：带架构上下文的知识点提取
_DS_EXTRACT_PROMPT = """请分析以下教材章节内容，提取该章节的核心知识点及其关系，构建知识图谱。

【学科/科目】：{subject}

【文档整体概述】：{document_summary}
【核心知识框架】：{core_framework}

【各章主题速览】：
{chapters_overview}

【当前提取章节】：{chapter_name}
【本章核心主题】：{chapter_themes}

【章节原文】：
{chapter_text}

---
**任务要求：**
1. 提取 3-8 个核心知识点
2. 每个知识点的 content 字段应尽量引用原文关键表述，包含：定义/概念、特征/特点、分类/类型、示例/案例等
3. relations 中可以引用其他章节的概念（使用"章节名+概念名"格式），也可引用本章节内的概念
4. 直接输出纯 JSON，不要添加代码块标记（```）或任何其他文字

**输出格式（严格遵守，直接输出 JSON）：**
{{
  "chapter": "章节名称",
  "knowledge_points": [
    {{
      "name": "知识点名称（5-20 字）",
      "content": "详细说明（引用原文，200-500 字，包含定义、特征、分类、示例）",
      "relations": [
        {{"type": "从属", "target": "上位知识点名称"}},
        {{"type": "比较", "target": "对比知识点名称"}},
        {{"type": "并列", "target": "同级知识点名称"}}
      ]
    }}
  ]
}}

关系类型（可组合使用，无关系则填 []）：从属、比较、并列、交叉、前提"""


def _parse_json_response(raw: str) -> dict:
    """清理 DeepSeek 响应中可能的代码块标记，解析为 dict。"""
    text = raw.strip()
    if text.startswith('```'):
        text = '\n'.join(text.split('\n')[1:])
    if text.endswith('```'):
        text = '\n'.join(text.split('\n')[:-1])
    return _json_mod.loads(text.strip())


def _extract_architecture(all_chapters: list, subject: str, client) -> dict:
    """Layer 1：单次调用 DeepSeek，分析文档整体架构。

    失败时返回空架构（降级处理），不中断后续提取。
    """
    chapter_list = '\n'.join(
        f"{ch['chapter_num']}. {ch['chapter_name']}"
        for ch in all_chapters
    )
    prompt = _DS_ARCH_PROMPT.format(
        subject=subject or '（未指定）',
        chapter_list=chapter_list,
    )
    try:
        resp = client.chat.completions.create(
            model='deepseek-chat',
            messages=[
                {'role': 'system', 'content': _DS_ARCH_SYSTEM},
                {'role': 'user', 'content': prompt},
            ],
            max_tokens=800,
            temperature=0,
        )
        return _parse_json_response(resp.choices[0].message.content)
    except Exception:
        return {'document_summary': '', 'core_framework': '', 'chapters': []}


def _build_chapters_overview(architecture: dict) -> str:
    """将架构中的章节主题列表格式化为紧凑的速览字符串。"""
    lines = []
    for ch in architecture.get('chapters', []):
        themes = ' / '.join(ch.get('themes', []))
        lines.append(f"- {ch['name']}：{themes}")
    return '\n'.join(lines) if lines else '（无）'


def _get_chapter_themes(architecture: dict, chapter_num: int) -> str:
    """从架构数据中取指定章节的主题列表，格式化为字符串。"""
    for ch in architecture.get('chapters', []):
        if ch.get('num') == chapter_num:
            return '、'.join(ch.get('themes', []))
    return '（未分析）'


# ═══════════════════════════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════════════════════════

@rag_bp.route('/api/rag/config', methods=['GET'])
def rag_get_config():
    """读取 .env 中的 DeepSeek API 配置。"""
    vals = _read_env_vars('DEEPSEEK_API_KEY', 'DEEPSEEK_TOKEN')
    return jsonify({
        'deepseek_api_key': vals.get('DEEPSEEK_API_KEY') or vals.get('DEEPSEEK_TOKEN') or '',
    })


@rag_bp.route('/api/rag/config', methods=['PUT'])
def rag_set_config():
    """将前端提交的 DeepSeek API 配置写入 .env 文件。"""
    data = request.json or {}
    updates: dict = {}
    if 'deepseek_api_key' in data:
        updates['DEEPSEEK_API_KEY'] = data['deepseek_api_key'].strip()
        updates['DEEPSEEK_TOKEN'] = ''  # 清除旧版 key 名
    if not updates:
        return jsonify({'error': '未提供任何配置'}), 400
    try:
        _write_env_vars(updates)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@rag_bp.route('/api/rag/ds-docs', methods=['GET'])
def list_ds_docs():
    """列出所有 DS 模式文档及其状态。"""
    _init_ds_db()
    with _ds_db_conn() as conn:
        rows = conn.execute(
            "SELECT doc_id, filename, subject, status, error_msg FROM ds_docs "
            "ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        with _ds_db_conn() as conn:
            kp_count = conn.execute(
                "SELECT COUNT(*) FROM ds_kps WHERE doc_id=?", (r['doc_id'],)
            ).fetchone()[0]
            ch_count = conn.execute(
                "SELECT COUNT(*) FROM ds_chapters WHERE doc_id=?", (r['doc_id'],)
            ).fetchone()[0]
            ch_with_kps = conn.execute(
                "SELECT COUNT(DISTINCT chapter_num) FROM ds_kps WHERE doc_id=?",
                (r['doc_id'],),
            ).fetchone()[0]
        result.append({
            'doc_id': r['doc_id'],
            'filename': r['filename'] or '',
            'subject': r['subject'] or '',
            'status': r['status'],
            'error_msg': r['error_msg'] or '',
            'kp_count': kp_count,
            'chapter_count': ch_count,
            'ch_with_kps': ch_with_kps,
        })
    return jsonify(result)


@rag_bp.route('/api/rag/ds-docs/<path:doc_id>', methods=['DELETE'])
def ds_delete_doc(doc_id):
    """删除 DS 文档及其所有章节和知识点数据。"""
    _init_ds_db()
    with _ds_db_conn() as conn:
        conn.execute("DELETE FROM ds_docs WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM ds_chapters WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM ds_kps WHERE doc_id=?", (doc_id,))
        conn.commit()
    return jsonify({'success': True})


@rag_bp.route('/api/rag/ds-upload', methods=['POST'])
def ds_upload():
    """上传文件并解析章节结构（仅支持 .md / .txt / .docx）。"""
    _ensure_upload_dir()
    _init_ds_db()

    if 'file' not in request.files:
        return jsonify({'error': '未提供文件'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': '文件名为空'}), 400

    subject = request.form.get('subject', '')
    filename = file.filename
    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem
    doc_id = stem[:40]

    if suffix not in ('.md', '.txt', '.docx'):
        return jsonify({'error': f'不支持的文件格式：{suffix}，仅支持 .md / .txt / .docx'}), 400

    save_path = _upload_dir() / filename
    file.save(str(save_path))

    try:
        # 读取并清理文本
        # ── 1. 读取并清理文本 ──────────────────────────────────────────────────
        if suffix in ('.md', '.txt'):
            raw_text = save_path.read_text(encoding='utf-8', errors='replace')
            cleaned_text, _ = _clean_ocr_md(raw_text)
        elif suffix == '.docx':
            try:
                from docx import Document as DocxDocument
                doc = DocxDocument(str(save_path))
                md_lines: list = []
                for para in doc.paragraphs:
                    t = para.text.strip()
                    if not t:
                        continue
                    style = para.style.name if para.style else ''
                    sl = style.lower()
                    if 'heading 1' in sl:
                        md_lines.append(f'# {t}')
                    elif 'heading 2' in sl:
                        md_lines.append(f'## {t}')
                    elif 'heading 3' in sl:
                        md_lines.append(f'### {t}')
                    elif 'heading 4' in sl:
                        md_lines.append(f'#### {t}')
                    else:
                        md_lines.append(t)
                cleaned_text, _ = _clean_ocr_md('\n'.join(md_lines))
            except Exception:
                cleaned_text = None
        else:
            cleaned_text = None

        if not cleaned_text:
            return jsonify({'error': '未能从文件中提取文本内容'}), 400

        # ── 2. 提取所有标题 + Layer 0 AI 清洗 ────────────────────────────────
        all_headings = _extract_all_headings(cleaned_text)

        # 默认降级方案：使用本地分析
        chapter_level_local, section_level_local = _analyze_doc_structure(cleaned_text)
        fallback_hierarchy = {
            'chapter_level': chapter_level_local,
            'section_level': section_level_local,
            'non_content_texts': set(),
        }

        hierarchy = None
        api_key = _get_deepseek_key()
        if api_key and all_headings:
            try:
                from openai import OpenAI as _OAI
                _ds_client = _OAI(api_key=api_key, base_url='https://api.deepseek.com', timeout=60)
                hierarchy = _clean_headings_with_ai(all_headings, subject, _ds_client)
            except Exception as _e:
                import logging
                logging.warning('Layer 0 heading clean failed, fallback to local: %s', _e)
                hierarchy = None

        if hierarchy is None:
            hierarchy = fallback_hierarchy

        # ── 3. 按节点列表切分（有 extraction_nodes）或降级到多层级切分 ──────────
        if hierarchy.get('extraction_nodes'):
            sections = _parse_md_by_nodes(cleaned_text, hierarchy)
        else:
            sections = _parse_md_multilevel(cleaned_text, hierarchy)

        if not sections:
            return jsonify({'error': '未能从文件中解析出章节内容，请确认文件含有标题结构（如 # 第一章）'}), 400

        import datetime
        with _ds_db_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ds_docs "
                "(doc_id, filename, subject, status, error_msg, created_at) "
                "VALUES (?,?,?,'uploaded','',?)",
                (doc_id, filename, subject, datetime.datetime.now().isoformat()),
            )
            conn.execute("DELETE FROM ds_chapters WHERE doc_id=?", (doc_id,))
            conn.execute("DELETE FROM ds_kps WHERE doc_id=?", (doc_id,))
            for sec in sections:
                conn.execute(
                    "INSERT INTO ds_chapters "
                    "(doc_id, chapter_num, chapter_name, parent_chapter_num, parent_chapter_name, "
                    "section_name, raw_text) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (doc_id, sec['num'], sec['chapter_name'],
                     sec['parent_chapter_num'], sec['parent_chapter_name'],
                     sec.get('section_name', ''),
                     sec['text']),
                )
            conn.commit()

        # 返回父章列表（去重）供前端展示
        seen = {}
        for sec in sections:
            if sec['parent_chapter_num'] not in seen:
                seen[sec['parent_chapter_num']] = sec['parent_chapter_name']
        parent_chapters = [{'num': n, 'name': nm} for n, nm in sorted(seen.items())]

        return jsonify({
            'success': True,
            'doc_id': doc_id,
            'chapter_count': len(parent_chapters),
            'section_count': len(sections),
            'chapters': parent_chapters,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@rag_bp.route('/api/rag/ds-extract/<path:doc_id>', methods=['POST'])
def ds_extract(doc_id):
    """异步：两层并行提取知识点，构建知识图谱。

    Layer 1：单次调用 DeepSeek 分析整体架构（章节目录 → 结构 JSON）。
    Layer 2：ThreadPoolExecutor 并发逐章提取知识点（架构作为上下文）。
    resume=True 时跳过已提取章节，Layer 1 若已有架构也跳过。
    """
    _init_ds_db()
    data = request.json or {}
    subject = data.get('subject', '')
    resume = bool(data.get('resume', False))
    concurrency = max(1, min(5, int(data.get('concurrency', 3))))

    with _ds_db_conn() as conn:
        conn.execute("UPDATE ds_docs SET subject=? WHERE doc_id=?", (subject, doc_id))
        if not resume:
            conn.execute(
                "UPDATE ds_docs SET status='analyzing', error_msg='', architecture_json='{}' WHERE doc_id=?",
                (doc_id,),
            )
            conn.execute("DELETE FROM ds_kps WHERE doc_id=?", (doc_id,))
        else:
            conn.execute(
                "UPDATE ds_docs SET status='analyzing', error_msg='' WHERE doc_id=?",
                (doc_id,),
            )
        conn.commit()

        # all_sections：知识点提取单元（节级别），包含父章信息
        all_sections = conn.execute(
            "SELECT chapter_num, chapter_name, parent_chapter_num, parent_chapter_name, "
            "COALESCE(section_name, '') as section_name, raw_text "
            "FROM ds_chapters WHERE doc_id=? ORDER BY chapter_num",
            (doc_id,),
        ).fetchall()

        # arch_chapters：用于架构分析的父章去重列表
        arch_chapters = conn.execute(
            "SELECT DISTINCT parent_chapter_num as chapter_num, parent_chapter_name as chapter_name "
            "FROM ds_chapters WHERE doc_id=? GROUP BY parent_chapter_num ORDER BY parent_chapter_num",
            (doc_id,),
        ).fetchall()

        existing_arch = conn.execute(
            "SELECT architecture_json FROM ds_docs WHERE doc_id=?", (doc_id,)
        ).fetchone()
        arch_json_str = (existing_arch['architecture_json'] if existing_arch else '') or '{}'

        if resume:
            extracted_nums = {
                r[0] for r in conn.execute(
                    "SELECT DISTINCT chapter_num FROM ds_kps WHERE doc_id=?", (doc_id,),
                ).fetchall()
            }
            chapters = [sec for sec in all_sections if sec['chapter_num'] not in extracted_nums]
        else:
            chapters = list(all_sections)

        all_chapters = list(arch_chapters)  # 供架构分析用

    if not all_chapters:
        return jsonify({'error': '文档未上传或章节解析失败，请先上传文档'}), 404

    if not chapters:
        with _ds_db_conn() as conn:
            kp_count = conn.execute(
                "SELECT COUNT(*) FROM ds_kps WHERE doc_id=?", (doc_id,)
            ).fetchone()[0]
            conn.execute("UPDATE ds_docs SET status='done' WHERE doc_id=?", (doc_id,))
            conn.commit()
        return jsonify({
            'success': True, 'task_id': None,
            'total': 0, 'already_done': True, 'kp_count': kp_count,
        })

    task_id = str(uuid.uuid4())[:8]
    _ds_tasks[task_id] = {
        'status': 'analyzing',
        'phase': 'layer1',
        'message': '正在分析文档整体架构...',
        'doc_id': doc_id,
        'progress': 0,
        'total': len(chapters),
        'total_chapters': len(all_chapters),
        'kp_count': 0,
        'failed_chapters': [],
        'pause_requested': False,
        'architecture': {},
    }

    def _worker(task_id, doc_id, subject, all_chapters, chapters,
                arch_json_str, concurrency):
        try:
            api_key = _get_deepseek_key()
            if not api_key:
                with _ds_db_conn() as conn:
                    conn.execute(
                        "UPDATE ds_docs SET status='error', error_msg=? WHERE doc_id=?",
                        ('未设置 DEEPSEEK_API_KEY', doc_id),
                    )
                    conn.commit()
                _ds_tasks[task_id].update({
                    'status': 'error',
                    'message': '未设置 DEEPSEEK_API_KEY，请在 API 配置中填写',
                })
                return

            from openai import OpenAI
            import openai as _openai_mod
            client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com')

            # ── Layer 1：架构分析 ─────────────────────────────────────────────
            try:
                existing = _json_mod.loads(arch_json_str)
            except Exception:
                existing = {}

            if existing.get('chapters'):
                # resume 且已有架构，跳过 L1
                architecture = existing
            else:
                architecture = _extract_architecture(list(all_chapters), subject, client)
                arch_str = _json_mod.dumps(architecture, ensure_ascii=False)
                with _ds_db_conn() as conn:
                    conn.execute(
                        "UPDATE ds_docs SET architecture_json=? WHERE doc_id=?",
                        (arch_str, doc_id),
                    )
                    conn.commit()

            _ds_tasks[task_id].update({
                'architecture': {
                    'document_summary': architecture.get('document_summary', ''),
                    'core_framework': architecture.get('core_framework', ''),
                },
            })

            # ── Layer 2：并行知识点提取 ───────────────────────────────────────
            with _ds_db_conn() as conn:
                conn.execute(
                    "UPDATE ds_docs SET status='extracting' WHERE doc_id=?", (doc_id,)
                )
                conn.commit()

            _ds_tasks[task_id].update({
                'status': 'extracting',
                'phase': 'layer2',
                'message': f'架构分析完成，开始并行提取知识点（{concurrency} 并发）...',
            })

            total = len(chapters)
            completed = 0
            failed_chapters = []
            db_lock = threading.Lock()

            chapters_overview = _build_chapters_overview(architecture)

            def _extract_one(ch):
                """单节提取，只返回结果，不写 DB。
                ch 包含 chapter_name（节名）、parent_chapter_num（父章序号）。
                """
                ch_text = ch['raw_text']
                if len(ch_text) > 8000:
                    ch_text = ch_text[:8000] + '\n\n[（内容过长，已截断）]'
                # 用父章序号查找架构主题（架构按父章组织）
                chapter_themes = _get_chapter_themes(architecture, ch['parent_chapter_num'])
                # 提示词中的 chapter_name 展示完整路径，让 DS 知道当前处理的是哪一节
                sec_name = ch['section_name'] if ch['section_name'] else ''
                if sec_name and sec_name != ch['chapter_name']:
                    display_name = (
                        f"{ch['parent_chapter_name']} > {ch['chapter_name']} > {sec_name}"
                    )
                elif ch['chapter_name'] != ch['parent_chapter_name']:
                    display_name = f"{ch['parent_chapter_name']} > {ch['chapter_name']}"
                else:
                    display_name = ch['chapter_name']
                prompt = _DS_EXTRACT_PROMPT.format(
                    subject=subject or '（未指定）',
                    document_summary=architecture.get('document_summary', ''),
                    core_framework=architecture.get('core_framework', ''),
                    chapters_overview=chapters_overview,
                    chapter_name=display_name,
                    chapter_themes=chapter_themes,
                    chapter_text=ch_text,
                )
                resp = client.chat.completions.create(
                    model='deepseek-chat',
                    messages=[
                        {'role': 'system', 'content': _DS_EXTRACT_SYSTEM},
                        {'role': 'user', 'content': prompt},
                    ],
                    max_tokens=3000,
                    temperature=0.3,
                )
                parsed = _parse_json_response(resp.choices[0].message.content)
                return parsed.get('knowledge_points', [])

            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                future_to_ch = {}
                for ch in chapters:
                    if _ds_tasks.get(task_id, {}).get('pause_requested'):
                        break
                    future_to_ch[executor.submit(_extract_one, ch)] = ch

                for future in as_completed(future_to_ch):
                    ch = future_to_ch[future]
                    try:
                        kps = future.result()
                        if kps:
                            with db_lock:
                                with _ds_db_conn() as conn:
                                    for kp in kps:
                                        conn.execute(
                                            "INSERT INTO ds_kps "
                                            "(doc_id, chapter_name, chapter_num, section_name, "
                                            "kp_name, kp_content, relations_json) "
                                            "VALUES (?,?,?,?,?,?,?)",
                                            (
                                                doc_id,
                                                # chapter_name 存父章名（L1），供 UI 分组
                                                ch['parent_chapter_name'],
                                                ch['parent_chapter_num'],
                                                # section_name 存节名（L2），供更细粒度展示
                                                ch['chapter_name'],
                                                kp.get('name', ''),
                                                kp.get('content', ''),
                                                _json_mod.dumps(
                                                    kp.get('relations', []),
                                                    ensure_ascii=False,
                                                ),
                                            ),
                                        )
                                    conn.commit()
                    except _openai_mod.AuthenticationError:
                        # API Key 无效，立即中止
                        raise
                    except Exception as ch_err:
                        failed_chapters.append({
                            'name': ch['chapter_name'],
                            'error': str(ch_err),
                        })

                    completed += 1
                    with _ds_db_conn() as conn:
                        kp_count_now = conn.execute(
                            "SELECT COUNT(*) FROM ds_kps WHERE doc_id=?", (doc_id,)
                        ).fetchone()[0]
                    _ds_tasks[task_id].update({
                        'progress': completed,
                        'total': total,
                        'kp_count': kp_count_now,
                        'failed_chapters': failed_chapters,
                        'message': (
                            f'已完成 {completed}/{total} 章，'
                            f'共 {kp_count_now} 个知识点'
                            + (f'（{len(failed_chapters)} 章失败）' if failed_chapters else '')
                        ),
                    })

            # ── 收尾 ──────────────────────────────────────────────────────────
            # 检查是否触发了暂停
            if _ds_tasks.get(task_id, {}).get('pause_requested'):
                with _ds_db_conn() as conn:
                    kp_count = conn.execute(
                        "SELECT COUNT(*) FROM ds_kps WHERE doc_id=?", (doc_id,)
                    ).fetchone()[0]
                    conn.execute(
                        "UPDATE ds_docs SET status='paused' WHERE doc_id=?", (doc_id,)
                    )
                    conn.commit()
                _ds_tasks[task_id].update({
                    'status': 'paused',
                    'phase': 'layer2',
                    'message': (
                        f'已暂停。已完成 {completed}/{total} 章，共 {kp_count} 个知识点'
                    ),
                    'kp_count': kp_count,
                    'failed_chapters': failed_chapters,
                })
                return

            with _ds_db_conn() as conn:
                kp_count = conn.execute(
                    "SELECT COUNT(*) FROM ds_kps WHERE doc_id=?", (doc_id,)
                ).fetchone()[0]
                conn.execute("UPDATE ds_docs SET status='done' WHERE doc_id=?", (doc_id,))
                conn.commit()

            fail_msg = f'，{len(failed_chapters)} 章失败' if failed_chapters else ''
            _ds_tasks[task_id].update({
                'status': 'done',
                'phase': 'done',
                'message': f'提取完成！共 {kp_count} 个知识点（{total} 章{fail_msg}）',
                'kp_count': kp_count,
                'failed_chapters': failed_chapters,
            })

        except Exception as e:
            with _ds_db_conn() as conn:
                conn.execute(
                    "UPDATE ds_docs SET status='error', error_msg=? WHERE doc_id=?",
                    (str(e), doc_id),
                )
                conn.commit()
            _ds_tasks[task_id].update({
                'status': 'error',
                'message': str(e),
            })

    t = threading.Thread(
        target=_worker,
        args=(task_id, doc_id, subject, list(all_chapters),
              list(chapters), arch_json_str, concurrency),
        daemon=True,
    )
    t.start()
    return jsonify({'success': True, 'task_id': task_id, 'total': len(chapters)})


@rag_bp.route('/api/rag/ds-kps/<int:kp_id>', methods=['GET'])
def ds_kp_get(kp_id):
    """获取单个知识点的完整信息（name、content、relations）。"""
    _init_ds_db()
    with _ds_db_conn() as conn:
        row = conn.execute(
            "SELECT id, doc_id, chapter_name, chapter_num, kp_name, kp_content, relations_json, "
            "teaching_focus, knowledge_type, cognitive_dimension "
            "FROM ds_kps WHERE id=?",
            (kp_id,),
        ).fetchone()
    if row is None:
        return jsonify({'error': f'知识点 {kp_id} 不存在'}), 404
    try:
        relations = _json_mod.loads(row['relations_json'] or '[]')
    except Exception:
        relations = []
    return jsonify({
        'id': row['id'],
        'doc_id': row['doc_id'],
        'chapter_name': row['chapter_name'],
        'chapter_num': row['chapter_num'],
        'name': row['kp_name'],
        'content': row['kp_content'],
        'relations': relations,
        'teaching_focus': row['teaching_focus'] or '',
        'knowledge_type': row['knowledge_type'] or '',
        'cognitive_dimension': row['cognitive_dimension'] or '',
    })


@rag_bp.route('/api/rag/ds-kps/<int:kp_id>', methods=['PUT'])
def ds_kp_update(kp_id):
    """更新单个知识点（支持部分更新，未传入的字段保持原值）。"""
    _init_ds_db()
    data = request.json or {}

    with _ds_db_conn() as conn:
        old = conn.execute("SELECT * FROM ds_kps WHERE id=?", (kp_id,)).fetchone()
        if not old:
            return jsonify({'error': f'知识点 {kp_id} 不存在'}), 404

        name = data['name'].strip() if 'name' in data else old['kp_name']
        content = data['content'].strip() if 'content' in data else (old['kp_content'] or '')
        teaching_focus = data['teaching_focus'].strip() if 'teaching_focus' in data else (old['teaching_focus'] or '')
        knowledge_type = data['knowledge_type'].strip() if 'knowledge_type' in data else (old['knowledge_type'] or '')
        cognitive_dimension = data['cognitive_dimension'].strip() if 'cognitive_dimension' in data else (old['cognitive_dimension'] or '')

        if not name:
            return jsonify({'error': '知识点名称不能为空'}), 400

        if 'relations' in data:
            relations = data['relations']
            if not isinstance(relations, list):
                return jsonify({'error': 'relations 必须为列表'}), 400
            relations_json = _json_mod.dumps(
                [r for r in relations if isinstance(r, dict) and r.get('target', '').strip()],
                ensure_ascii=False
            )
        else:
            relations_json = old['relations_json'] or '[]'

        conn.execute(
            "UPDATE ds_kps SET kp_name=?, kp_content=?, relations_json=?, "
            "teaching_focus=?, knowledge_type=?, cognitive_dimension=? WHERE id=?",
            (name, content, relations_json, teaching_focus, knowledge_type, cognitive_dimension, kp_id),
        )
        conn.commit()

    return jsonify({'success': True, 'id': kp_id})


@rag_bp.route('/api/rag/ds-chapters', methods=['PUT'])
def update_ds_chapter():
    """修改章节名称，级联更新 ds_chapters 和 ds_kps 中的所有相关记录。"""
    _init_ds_db()
    data = request.json or {}
    doc_id = data.get('doc_id', '').strip()
    chapter_num = data.get('chapter_num')
    new_name = data.get('new_name', '').strip()

    if not doc_id or chapter_num is None or not new_name:
        return jsonify({'error': '缺少必要参数 doc_id / chapter_num / new_name'}), 400

    with _ds_db_conn() as conn:
        row = conn.execute(
            "SELECT chapter_name, parent_chapter_num FROM ds_chapters "
            "WHERE doc_id=? AND chapter_num=?",
            (doc_id, chapter_num)
        ).fetchone()

        if not row:
            # ds_chapters 中可能没有该章节记录（仅在 ds_kps 中存在），
            # 此时只更新 ds_kps
            conn.execute(
                "UPDATE ds_kps SET chapter_name=? WHERE doc_id=? AND chapter_num=?",
                (new_name, doc_id, chapter_num)
            )
            conn.commit()
            return jsonify({'success': True, 'new_name': new_name})

        # 1. 更新 ds_chapters 主记录
        conn.execute(
            "UPDATE ds_chapters SET chapter_name=? WHERE doc_id=? AND chapter_num=?",
            (new_name, doc_id, chapter_num)
        )
        # 2. 若为 L1 章（parent_chapter_num == 0），同步更新子章节的 parent_chapter_name
        if row['parent_chapter_num'] == 0:
            conn.execute(
                "UPDATE ds_chapters SET parent_chapter_name=? "
                "WHERE doc_id=? AND parent_chapter_num=?",
                (new_name, doc_id, chapter_num)
            )
        # 3. 同步更新 ds_kps 中所有该章节知识点的 chapter_name
        conn.execute(
            "UPDATE ds_kps SET chapter_name=? WHERE doc_id=? AND chapter_num=?",
            (new_name, doc_id, chapter_num)
        )
        conn.commit()

    return jsonify({'success': True, 'new_name': new_name})


# ── 批量分类：知识类型 + 认知维度 ──────────────────────────────────────────────

_CLASSIFY_SYSTEM = "你是一名教育学专家，熟悉布鲁姆教育目标分类理论。"

_CLASSIFY_PROMPT = """\
请根据布鲁姆分类法，对下列知识点逐一判断其【知识类型】和【认知维度】。

## 知识类型（四选一）
- 事实性：指客观存在的事实、数据、事件等，不涉及推理或解释。
- 概念性：涉及定义、原理、理论等，是对事物本质和规律的描述。
- 程序性：关于如何做事的知识，包括方法、步骤、算法等。
- 元认知：关于认知的认知，涉及对思维过程、学习策略、自我监控等的理解和运用。

## 认知维度（六选一，由低到高）
- 记忆：最低层次，认识和记忆名词、事实、规则、原理。行动动词：指出、写出、界定、说明、举例、命名。
- 理解：把握知识或概念的意义，包括转译、解释、推论。行动动词：解释、说明、区别、摘要、归纳。
- 应用：将规则、方法、步骤应用到新情境。行动动词：预测、证明、解决、修改、应用。
- 分析：将概念分析为各构成部分，找出相互关系。行动动词：选出、分析、判断、区分、指出关系。
- 评价：依据标准做价值的判断。行动动词：评鉴、判断、评论、比较、批判。
- 创造：将各元素组装形成完整且具功能的整体。行动动词：设计、创造、发展、建立、提出假设。

## 待分类知识点
{kp_list}

## 输出要求
直接输出纯 JSON 数组，不要加代码块标记，格式如下：
[
  {{"seq": 1, "knowledge_type": "概念性", "cognitive_dimension": "理解"}},
  ...
]
"""

_CLASSIFY_PROMPT_WITH_FOCUS = """\
请根据布鲁姆分类法，对下列知识点逐一判断其【知识类型】、【认知维度】和【教学属性】。

## 知识类型（四选一）
- 事实性：指客观存在的事实、数据、事件等，不涉及推理或解释。
- 概念性：涉及定义、原理、理论等，是对事物本质和规律的描述。
- 程序性：关于如何做事的知识，包括方法、步骤、算法等。
- 元认知：关于认知的认知，涉及对思维过程、学习策略、自我监控等的理解和运用。

## 认知维度（六选一，由低到高）
- 记忆：最低层次，认识和记忆名词、事实、规则、原理。行动动词：指出、写出、界定、说明、举例、命名。
- 理解：把握知识或概念的意义，包括转译、解释、推论。行动动词：解释、说明、区别、摘要、归纳。
- 应用：将规则、方法、步骤应用到新情境。行动动词：预测、证明、解决、修改、应用。
- 分析：将概念分析为各构成部分，找出相互关系。行动动词：选出、分析、判断、区分、指出关系。
- 评价：依据标准做价值的判断。行动动词：评鉴、判断、评论、比较、批判。
- 创造：将各元素组装形成完整且具功能的整体。行动动词：设计、创造、发展、建立、提出假设。

## 教学属性（可多选，用逗号分隔，也可为空）
- 重点：本课程重点掌握的核心概念或方法
- 难点：学生普遍感到理解困难的内容
- 考点：历年考试频繁出现的内容

{focus_section}## 待分类知识点
{kp_list}

## 输出要求
直接输出纯 JSON 数组，不要加代码块标记，格式如下：
[
  {{"seq": 1, "knowledge_type": "概念性", "cognitive_dimension": "理解", "teaching_focus": "重点,考点"}},
  ...
]
"""


def _classify_batch(
    client,
    kps_batch: list,
    system_prompt: str = None,
    user_prompt: str = None,
    classify_focus: bool = False,
) -> list:
    """调用 DeepSeek 对一批知识点分类，返回与输入等长的结果列表。

    kps_batch: [{"seq": 1, "kp_name": "...", "kp_content": "..."}, ...]
    返回: [{"seq": 1, "knowledge_type": "...", "cognitive_dimension": "...", "teaching_focus": "..."}, ...]

    system_prompt / user_prompt 为 None 时使用模块级默认常量。
    user_prompt 须含 {kp_list} 占位符。
    classify_focus=True 时输出中包含 teaching_focus 字段并写回。
    """
    lines = []
    for kp in kps_batch:
        content_preview = (kp.get('kp_content') or '')[:200]
        lines.append(f"序号{kp['seq']}. 名称：{kp['kp_name']}\n   内容：{content_preview}")
    kp_list_text = '\n'.join(lines)

    sys_msg = system_prompt if system_prompt else _CLASSIFY_SYSTEM

    if user_prompt:
        # 前端传来的提示词，{focus_section} 已被替换，只需填 {kp_list}
        if '{kp_list}' in user_prompt:
            user_msg = user_prompt.replace('{kp_list}', kp_list_text)
        else:
            user_msg = user_prompt + '\n\n## 待分类知识点\n' + kp_list_text
    else:
        if classify_focus:
            user_msg = _CLASSIFY_PROMPT_WITH_FOCUS.format(kp_list=kp_list_text, focus_section='')
        else:
            user_msg = _CLASSIFY_PROMPT.format(kp_list=kp_list_text)

    max_tokens = 1200 if classify_focus else 1000

    resp = client.chat.completions.create(
        model='deepseek-chat',
        messages=[
            {'role': 'system', 'content': sys_msg},
            {'role': 'user', 'content': user_msg},
        ],
        max_tokens=max_tokens,
        temperature=0.1,
    )
    raw = resp.choices[0].message.content or ''
    # 去掉可能的代码块包裹
    raw = raw.strip()
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    try:
        results = _json_mod.loads(raw)
        if isinstance(results, list):
            return results
    except Exception:
        pass
    return []


_classify_tasks: dict = {}
_VALID_KT = {'事实性', '概念性', '程序性', '元认知'}
_VALID_CD = {'记忆', '理解', '应用', '分析', '评价', '创造'}
_VALID_TF = {'重点', '难点', '考点'}


def _parse_focus_topics(content: str) -> list[str]:
    """解析重难点文件，提取清洁主题字符串列表。

    支持多级缩进的 txt/md 格式：去掉 #/- 等标记后返回非空行。
    """
    import re
    topics = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r'^#+\s*', '', line)                   # 去掉 # 标题符
        line = re.sub(r'^[-*·•●]\s*', '', line)              # 去掉列表符
        line = re.sub(r'^[（(]?\d+[）).、]\s*', '', line)    # 去掉序号
        line = line.strip()
        if len(line) >= 2:
            topics.append(line)
    return topics


def _match_kp_to_topics(kp_name: str, kp_content: str, topics: list[str]) -> tuple[bool, str]:
    """判断知识点是否匹配重难点列表中的某个主题。

    匹配策略（优先级递减）：
    1. KP 名称直接出现在某条目文本中
    2. 某条目冒号前的标题出现在 KP 名称或内容中
    3. 某条目中提取的 ≥2 个中文关键词均出现在 KP 文本中（或 1 个 ≥4 字长词）
    """
    import re
    kp_text = (kp_name or '') + ' ' + (kp_content or '')[:300]
    _STOPWORDS = {'的', '是', '在', '和', '与', '及', '等', '了', '其', '该', '各', '此', '为', '以', '有'}

    for topic in topics:
        # 策略 1：KP 名称直接出现在主题行中
        if kp_name and len(kp_name) >= 2 and kp_name in topic:
            return True, topic

        # 策略 2：主题冒号前的标题出现在 KP 文本中
        colon_match = re.match(r'^([^：:]{2,12})[：:]', topic)
        if colon_match:
            title = colon_match.group(1).strip()
            if title and len(title) >= 2 and title in kp_text:
                return True, topic

        # 策略 3：关键词匹配
        keywords = list({kw for kw in re.findall(r'[\u4e00-\u9fff]{2,6}', topic)
                         if kw not in _STOPWORDS})
        if not keywords:
            continue
        match_count = sum(1 for kw in keywords if kw in kp_text)
        if match_count >= 2:
            return True, topic
        if match_count == 1 and any(len(kw) >= 4 and kw in kp_text for kw in keywords):
            return True, topic

    return False, ''


@rag_bp.route('/api/rag/ds-match-focus', methods=['POST'])
def ds_match_focus():
    """智能解析重难点列表并直接匹配知识点，写入 teaching_focus。

    请求体：
      {
        "doc_id": "...",          # 必须
        "topics": ["...", ...],   # 主题字符串列表（前端解析后传入）
        "tag": "重点",            # 打标签：重点 / 难点 / 考点，默认"重点"
        "overwrite": false        # false=仅补全，true=覆盖已有
      }
    """
    _init_ds_db()
    data     = request.json or {}
    doc_id   = data.get('doc_id', '').strip()
    topics   = data.get('topics', [])
    tag      = data.get('tag', '重点')
    overwrite = bool(data.get('overwrite', False))

    if not doc_id:
        return jsonify({'error': 'doc_id 必须提供'}), 400
    if not isinstance(topics, list) or not topics:
        return jsonify({'error': 'topics 列表为空'}), 400
    if tag not in _VALID_TF:
        tag = '重点'

    with _ds_db_conn() as conn:
        rows = conn.execute(
            "SELECT id, kp_name, kp_content, teaching_focus FROM ds_kps WHERE doc_id=?",
            (doc_id,)
        ).fetchall()

    matched = []
    for row in rows:
        current_tf = row['teaching_focus'] or ''
        existing = [p.strip() for p in current_tf.split(',') if p.strip()]
        if not overwrite and tag in existing:
            continue
        is_match, _ = _match_kp_to_topics(row['kp_name'], row['kp_content'], topics)
        if is_match:
            matched.append((row['id'], existing))

    with _ds_db_conn() as conn:
        for kp_id, existing in matched:
            parts = [p for p in existing if p in _VALID_TF]
            if tag not in parts:
                parts.append(tag)
            conn.execute(
                "UPDATE ds_kps SET teaching_focus=? WHERE id=?",
                (','.join(parts), kp_id),
            )
        conn.commit()

    return jsonify({
        'success': True,
        'topics_count': len(topics),
        'matched_count': len(matched),
        'total_kps': len(rows),
        'matched_kp_ids': [x[0] for x in matched],
    })


@rag_bp.route('/api/rag/ds-batch-classify', methods=['POST'])
def ds_batch_classify():
    """异步批量提取知识点的知识类型、认知维度，可选标注教学属性。

    请求体：
      {
        "doc_id": "...",          # 可选，不传则 kp_ids 必须提供
        "kp_ids": [1, 2, 3],     # 可选，不传则处理 doc_id 下所有知识点
        "overwrite": false,       # false=仅补全空白, true=全部覆盖
        "system_prompt": "...",   # 可选，覆盖默认系统提示
        "user_prompt": "...",     # 可选，须含 {kp_list} 占位符；覆盖默认用户提示
        "classify_focus": false   # true=同时标注 teaching_focus
      }
    """
    _init_ds_db()
    data = request.json or {}
    doc_id          = data.get('doc_id', '').strip()
    kp_ids          = data.get('kp_ids')
    overwrite       = bool(data.get('overwrite', False))
    system_prompt   = data.get('system_prompt') or None
    user_prompt     = data.get('user_prompt') or None
    classify_focus  = bool(data.get('classify_focus', False))

    if not doc_id and not kp_ids:
        return jsonify({'error': 'doc_id 或 kp_ids 至少提供一项'}), 400

    api_key = _get_deepseek_key()
    if not api_key:
        return jsonify({'error': '未配置 DeepSeek API Key'}), 400

    # 查询要处理的知识点
    with _ds_db_conn() as conn:
        if kp_ids:
            ph = ','.join('?' * len(kp_ids))
            rows = conn.execute(
                f"SELECT id, kp_name, kp_content, knowledge_type, cognitive_dimension "
                f"FROM ds_kps WHERE id IN ({ph})",
                list(kp_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, kp_name, kp_content, knowledge_type, cognitive_dimension "
                "FROM ds_kps WHERE doc_id=?",
                (doc_id,),
            ).fetchall()

    if not overwrite:
        rows = [r for r in rows if not (r['knowledge_type'] and r['cognitive_dimension'])]

    if not rows:
        return jsonify({'success': True, 'task_id': None, 'message': '没有需要处理的知识点', 'total': 0})

    import uuid, threading
    task_id = uuid.uuid4().hex[:8]
    _classify_tasks[task_id] = {
        'status': 'running',
        'progress': 0,
        'total': len(rows),
        'done_ids': [],
        'error': None,
    }

    def _run():
        try:
            from openai import OpenAI as _OAI
            client = _OAI(api_key=api_key, base_url='https://api.deepseek.com')
            batch_size = 15
            kp_list = [dict(r) for r in rows]
            done = 0

            for start in range(0, len(kp_list), batch_size):
                batch = kp_list[start:start + batch_size]
                # 给每个加序号（1-based）
                for i, kp in enumerate(batch):
                    kp['seq'] = i + 1

                results = _classify_batch(
                    client, batch,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    classify_focus=classify_focus,
                )

                # 将结果写回 DB（按 seq 对齐）
                seq_map = {kp['seq']: kp for kp in batch}
                with _ds_db_conn() as conn:
                    for res in results:
                        seq = res.get('seq')
                        kt  = res.get('knowledge_type', '')
                        cd  = res.get('cognitive_dimension', '')
                        if seq not in seq_map:
                            continue
                        kp = seq_map[seq]
                        # 校验合法值
                        kt = kt if kt in _VALID_KT else ''
                        cd = cd if cd in _VALID_CD else ''
                        if classify_focus:
                            raw_tf = res.get('teaching_focus', '')
                            # 支持逗号分隔多值，过滤非法项
                            tf_parts = [p.strip() for p in raw_tf.split(',') if p.strip() in _VALID_TF]
                            tf = ','.join(tf_parts)
                            conn.execute(
                                "UPDATE ds_kps SET knowledge_type=?, cognitive_dimension=?, teaching_focus=? WHERE id=?",
                                (kt, cd, tf, kp['id']),
                            )
                        else:
                            conn.execute(
                                "UPDATE ds_kps SET knowledge_type=?, cognitive_dimension=? WHERE id=?",
                                (kt, cd, kp['id']),
                            )
                        _classify_tasks[task_id]['done_ids'].append(kp['id'])
                        done += 1
                    conn.commit()

                _classify_tasks[task_id]['progress'] = done

            _classify_tasks[task_id].update({'status': 'done', 'progress': done})

        except Exception as e:
            _classify_tasks[task_id].update({'status': 'error', 'error': str(e)})

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'success': True, 'task_id': task_id, 'total': len(rows)})


@rag_bp.route('/api/rag/ds-classify-tasks/<task_id>', methods=['GET'])
def ds_classify_task_status(task_id):
    """轮询批量分类任务状态。"""
    task = _classify_tasks.get(task_id)
    if task is None:
        return jsonify({'error': '任务不存在'}), 404
    return jsonify(task)


@rag_bp.route('/api/rag/ds-export-xlsx', methods=['GET'])
def ds_export_xlsx():
    """将指定文档的知识图谱导出为《批量导入知识点模板》格式的 Excel 文件。

    Query params:
        doc_id  — 文档 ID（必填）
    """
    import io
    try:
        import openpyxl
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        return jsonify({'error': '请先安装 openpyxl：pip install openpyxl'}), 500

    _init_ds_db()
    doc_id = request.args.get('doc_id', '').strip()
    if not doc_id:
        return jsonify({'error': 'doc_id 不能为空'}), 400

    with _ds_db_conn() as conn:
        # 校验文档存在
        doc_row = conn.execute(
            "SELECT doc_id FROM ds_docs WHERE doc_id=?", (doc_id,)
        ).fetchone()
        if doc_row is None:
            return jsonify({'error': f'文档 {doc_id} 不存在'}), 404

        # 获取章节层级
        chapters = conn.execute(
            "SELECT chapter_num, chapter_name, parent_chapter_num, parent_chapter_name "
            "FROM ds_chapters WHERE doc_id=? ORDER BY chapter_num",
            (doc_id,),
        ).fetchall()

        # 获取知识点（含 section_name）
        kps = conn.execute(
            "SELECT id, chapter_num, chapter_name, "
            "COALESCE(section_name, '') as section_name, "
            "kp_name, teaching_focus, knowledge_type, cognitive_dimension, relations_json "
            "FROM ds_kps WHERE doc_id=? ORDER BY chapter_num, id",
            (doc_id,),
        ).fetchall()

    # ── 1. 从 ds_kps 重建层级（按出现顺序去重） ──────────────────────────────
    import re as _re
    doc_label = _re.sub(r'^\d+_', '', doc_id).replace('_', ' ')

    # 遍历 kps，按 (chapter_name, section_name) 分组并保持出现顺序
    chapter_order: list = []          # [chapter_name]
    chapter_seen: dict = {}           # chapter_name → chapter_num
    chapter_sections: dict = {}       # chapter_name → [section_name, ...]（有序去重）
    section_seen: dict = {}           # chapter_name → set(section_name)
    section_kps: dict = {}            # (chapter_name, section_name) → [kp, ...]

    for kp in kps:
        ch  = kp['chapter_name'] or ''
        sec = kp['section_name'] or ''
        if _is_non_content(ch):
            continue
        if ch not in chapter_seen:
            chapter_seen[ch] = kp['chapter_num']
            chapter_order.append(ch)
            chapter_sections[ch] = []
            section_seen[ch] = set()
        if sec not in section_seen[ch]:
            if not _is_non_content(sec):
                section_seen[ch].add(sec)
                chapter_sections[ch].append(sec)
        key = (ch, sec)
        section_kps.setdefault(key, []).append(kp)

    # 按顺序构建 rows_data
    rows_data = []

    def _add_row(level, name, node_type, tf='', kt='', cd='', db_id=None):
        rows_data.append({
            'level': level, 'name': name, 'node_type': node_type,
            'teaching_focus': tf, 'knowledge_type': kt,
            'cognitive_dimension': cd, 'db_id': db_id,
        })

    # L1: 文档
    _add_row(1, doc_label, '知识单元')

    # L2（章） → L3（节 or KP直接） → L4（KP，若有节）
    for ch_name in chapter_order:
        _add_row(2, ch_name, '知识单元')
        for sec_name in chapter_sections[ch_name]:
            kp_list = section_kps.get((ch_name, sec_name), [])
            if sec_name:
                # 有节名：L3=节（知识单元），L4=KP
                _add_row(3, sec_name, '知识单元')
                for kp in kp_list:
                    _add_row(4, kp['kp_name'], '知识点',
                             tf=kp['teaching_focus'] or '',
                             kt=kp['knowledge_type'] or '',
                             cd=kp['cognitive_dimension'] or '',
                             db_id=kp['id'])
            else:
                # 无节名：KP 直接挂在章下，放 L3
                for kp in kp_list:
                    _add_row(3, kp['kp_name'], '知识点',
                             tf=kp['teaching_focus'] or '',
                             kt=kp['knowledge_type'] or '',
                             cd=kp['cognitive_dimension'] or '',
                             db_id=kp['id'])

    # 分配导出 ID（1-based）
    for i, r in enumerate(rows_data):
        r['export_id'] = i + 1

    # ── 2. 解析关系，建立 name→export_id 映射 ─────────────────────────────
    # 合并：所有节点名 → export_id
    all_name_to_id: dict = {}
    for r in rows_data:
        all_name_to_id[r['name']] = r['export_id']

    def resolve_ids(names_str: str) -> str:
        """将分号分隔的名称解析为分号分隔的 export_id。"""
        parts = [p.strip() for p in names_str.split(';') if p.strip()]
        ids = []
        for p in parts:
            # 支持 "章节名>kp名" 格式
            kp_name = p.split('>')[-1].strip() if '>' in p else p
            eid = all_name_to_id.get(kp_name)
            if eid:
                ids.append(str(eid))
        return ';'.join(ids)

    # 为每个知识点建立前序/关联 ID
    kp_prereqs: dict[int, str] = {}   # export_id → 前序IDs字符串
    kp_related: dict[int, str] = {}   # export_id → 关联IDs字符串

    kp_export_id_map = {kp['id']: all_name_to_id.get(kp['kp_name'], '') for kp in kps}

    for kp in kps:
        eid = all_name_to_id.get(kp['kp_name'])
        if not eid:
            continue
        try:
            relations = _json_mod.loads(kp['relations_json'] or '[]')
        except Exception:
            relations = []
        prereq_names = []
        related_names = []
        for rel in relations:
            rtype = rel.get('type', '')
            target = rel.get('target', '')
            if rtype == '前提':
                prereq_names.append(target)
            elif rtype in ('并列', '交叉', '比较'):
                related_names.append(target)
        kp_prereqs[eid] = resolve_ids(';'.join(prereq_names))
        kp_related[eid] = resolve_ids(';'.join(related_names))

    # ── 3. 生成 Excel（在模板基础上写入，保留前两行不变） ────────────────────
    template_path = _project_root() / '批量导入知识点模板.xlsx'
    if template_path.exists():
        wb = openpyxl.load_workbook(str(template_path))
        ws = wb['知识点'] if '知识点' in wb.sheetnames else wb.active
        # 清空第3行及以后的旧数据（保留第1行说明、第2行表头）
        if ws.max_row >= 3:
            ws.delete_rows(3, ws.max_row - 2)
    else:
        # 模板不存在时降级：自建表头（保证格式兼容）
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '知识点'
        HEADERS = ['ID', '一级知识点', '二级知识点', '三级知识点',
                   '四级知识点', '五级知识点', '六级知识点',
                   '节点类型', '教学要点', '知识类型', '认知维度',
                   '前序知识点ID', '关联知识点ID']
        header_fill = PatternFill('solid', start_color='4472C4')
        header_font = Font(bold=True, color='FFFFFF', name='微软雅黑', size=10)
        header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        thin = Side(style='thin', color='FFFFFF')
        header_border = Border(left=thin, right=thin, top=thin, bottom=thin)
        ws.row_dimensions[2].height = 20
        for col_idx, header in enumerate(HEADERS, 1):
            cell = ws.cell(row=2, column=col_idx, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_align
            cell.border = header_border

    # 数据从第3行开始写入（第1行=说明，第2行=表头）
    data_align = Alignment(vertical='center', wrap_text=False)
    for r in rows_data:
        row_idx = r['export_id'] + 2  # +2：跳过说明行+表头行
        level = r['level']
        eid   = r['export_id']

        ws.cell(row=row_idx, column=1, value=eid).alignment = data_align

        # 填写对应级别列（B=level1, C=level2, ...）
        level_col = level  # 1→col2(B), 2→col3(C)...
        ws.cell(row=row_idx, column=level_col + 1, value=r['name']).alignment = data_align

        ws.cell(row=row_idx, column=8, value=r['node_type']).alignment = data_align

        if r['teaching_focus']:
            ws.cell(row=row_idx, column=9, value=r['teaching_focus']).alignment = data_align
        if r['knowledge_type']:
            ws.cell(row=row_idx, column=10, value=r['knowledge_type']).alignment = data_align
        if r['cognitive_dimension']:
            ws.cell(row=row_idx, column=11, value=r['cognitive_dimension']).alignment = data_align

        if eid in kp_prereqs and kp_prereqs[eid]:
            ws.cell(row=row_idx, column=12, value=kp_prereqs[eid]).alignment = data_align
        if eid in kp_related and kp_related[eid]:
            ws.cell(row=row_idx, column=13, value=kp_related[eid]).alignment = data_align

    # 列宽
    col_widths = [8, 20, 22, 22, 22, 22, 22, 12, 16, 14, 14, 14, 14]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # 字典 sheet（模板中已有则跳过，仅在自建模式下补充）
    if '字典' not in wb.sheetnames:
        ws2 = wb.create_sheet('字典')
    else:
        ws2 = None  # 模板自带字典，不覆盖
    if ws2 is not None:
        dict_data = [
        (None, '知识类型', None),
        (None, '事实性', '指客观存在的事实、数据、事件等，不涉及推理或解释。'),
        (None, '概念性', '涉及定义、原理、理论等，是对事物本质和规律的描述。'),
        (None, '程序性', '关于如何做事的知识，包括方法、步骤、算法等。'),
        (None, '元认知', '关于认知的认知，涉及对思维过程、学习策略、自我监控等的理解和运用。'),
        (None, '认知维度', None),
        (None, '记忆', '在认知目标中知识是最低层次的能力，包括名词、事实、规则和原理原则等的认识和记忆。'),
        (None, '理解', '理解是指能把握所学过知识或概念的意义，包括转译、解释、推论等能力。'),
        (None, '应用', '应用是指将所学到的规则、方法、步骤、原理、原则和概念，应用到新情境的能力。'),
        (None, '分析', '分析是指将学到的概念或原则，分析为各个构成的部分，找出各部分之间的相互关系。'),
        (None, '评价', '指依据某项标准做价值的判断的能力。'),
        (None, '创造', '涉及将各个元素组装在一起，形成一个完整且具功能的整体。'),
        ]
        for row in dict_data:
            ws2.append(row)

    # ── 4. 返回文件 ───────────────────────────────────────────────────────
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    from flask import send_file
    import urllib.parse
    safe_name = urllib.parse.quote(f'{doc_label}_知识点导出.xlsx')
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'{doc_label}_知识点导出.xlsx',
    )


@rag_bp.route('/api/rag/ds-tasks/<task_id>', methods=['GET'])
def ds_task_status(task_id):
    """轮询 DS 知识点提取任务状态。"""
    task = _ds_tasks.get(task_id)
    if task is None:
        return jsonify({'error': '任务不存在'}), 404
    return jsonify(task)


@rag_bp.route('/api/rag/ds-tasks/<task_id>/pause', methods=['POST'])
def ds_pause_task(task_id):
    """请求暂停正在进行的知识点提取任务（将在当前章节完成后生效）。"""
    task = _ds_tasks.get(task_id)
    if task is None:
        return jsonify({'error': '任务不存在'}), 404
    if task.get('status') != 'running':
        return jsonify({'error': f'任务当前状态为 {task.get("status")}，无法暂停'}), 400
    _ds_tasks[task_id]['pause_requested'] = True
    return jsonify({'success': True, 'message': '暂停请求已发送，将在当前章节完成后暂停'})


@rag_bp.route('/api/rag/ds-docs/<path:doc_id>/kps', methods=['GET'])
def ds_doc_kps(doc_id):
    """获取文档的章节列表和知识点列表（用于前端三级联动筛选）。"""
    _init_ds_db()
    with _ds_db_conn() as conn:
        # 返回 (章, 节) 两级去重列表（从 ds_kps 按 chapter_name + section_name 分组）
        chapters_raw = conn.execute(
            "SELECT chapter_name, chapter_num, COALESCE(section_name,'') as section_name "
            "FROM ds_kps WHERE doc_id=? ORDER BY chapter_num, id",
            (doc_id,),
        ).fetchall()
        seen_ch: dict = {}
        for r in chapters_raw:
            key = (r['chapter_name'], r['section_name'])
            if key not in seen_ch:
                seen_ch[key] = r['chapter_num']
        chapters_list = sorted(
            [{'name': ch, 'section_name': sec, 'num': num, 'doc_id': doc_id}
             for (ch, sec), num in seen_ch.items()],
            key=lambda x: (x['num'], x['section_name'])
        )
        kps = conn.execute(
            "SELECT id, chapter_name, chapter_num, COALESCE(section_name,'') as section_name, "
            "kp_name, kp_content, relations_json, "
            "teaching_focus, knowledge_type, cognitive_dimension "
            "FROM ds_kps WHERE doc_id=? ORDER BY chapter_num, id",
            (doc_id,),
        ).fetchall()
        doc_row = conn.execute(
            "SELECT architecture_json FROM ds_docs WHERE doc_id=?", (doc_id,)
        ).fetchone()

    try:
        architecture = _json_mod.loads(
            (doc_row['architecture_json'] if doc_row else '') or '{}'
        )
    except Exception:
        architecture = {}

    return jsonify({
        'architecture': architecture,
        'chapters': chapters_list,
        'kps': [
            {
                'id': k['id'],
                'chapter_name': k['chapter_name'],
                'chapter_num': k['chapter_num'],
                'section_name': k['section_name'],
                'name': k['kp_name'],
                'content': k['kp_content'],
                'relations': k['relations_json'],
                'teaching_focus': k['teaching_focus'] or '',
                'knowledge_type': k['knowledge_type'] or '',
                'cognitive_dimension': k['cognitive_dimension'] or '',
            }
            for k in kps
        ],
    })


@rag_bp.route('/api/rag/ds-graph', methods=['GET'])
def ds_graph():
    """返回 DS 知识图谱数据（节点 + 边），供前端 D3 力导向图可视化。

    Query params:
        doc_id  (可重复): 限定文档，不传则返回所有已完成文档
        chapter (可重复): 章节名称过滤
    """
    import json as _json
    _init_ds_db()

    doc_ids = request.args.getlist('doc_id')
    chapters_filter = request.args.getlist('chapter')

    with _ds_db_conn() as conn:
        if not doc_ids:
            rows_d = conn.execute(
                "SELECT doc_id FROM ds_docs WHERE status='done'"
            ).fetchall()
            doc_ids = [r['doc_id'] for r in rows_d]

        if not doc_ids:
            return jsonify({'nodes': [], 'links': [], 'chapters': []})

        ph = ','.join('?' for _ in doc_ids)
        query = (
            "SELECT id, doc_id, chapter_name, chapter_num, "
            "COALESCE(section_name, '') as section_name, "
            "kp_name, kp_content, relations_json "
            f"FROM ds_kps WHERE doc_id IN ({ph})"
        )
        params: list = list(doc_ids)
        if chapters_filter:
            cp = ','.join('?' for _ in chapters_filter)
            query += f" AND chapter_name IN ({cp})"
            params.extend(chapters_filter)
        query += " ORDER BY doc_id, chapter_num, id"
        rows = conn.execute(query, params).fetchall()

    if not rows:
        return jsonify({'nodes': [], 'links': [], 'chapters': []})

    nodes: list = []
    name_to_id: dict = {}
    # 用 (chapter_name, section_name) 元组去重，保留 chapter_num
    sections_seen: dict = {}  # (chapter_name, section_name) -> chapter_num

    for row in rows:
        nid = f"kp_{row['id']}"
        name_to_id[(row['doc_id'], row['kp_name'])] = nid
        name_to_id.setdefault(row['kp_name'], nid)
        sec_name = row['section_name'] or ''
        nodes.append({
            'id': nid,
            'name': row['kp_name'],
            'chapter': row['chapter_name'],
            'chapter_num': row['chapter_num'],
            'section_name': sec_name,
            'doc_id': row['doc_id'],
            'content': row['kp_content'],
        })
        key = (row['chapter_name'], sec_name)
        if key not in sections_seen:
            sections_seen[key] = row['chapter_num']

    links: list = []
    for row in rows:
        try:
            rels = _json.loads(row['relations_json'] or '[]')
            src = f"kp_{row['id']}"
            for rel in rels:
                tgt_name = (rel.get('target') or '').strip()
                rel_type = rel.get('type', '')
                tgt = (
                    name_to_id.get((row['doc_id'], tgt_name))
                    or name_to_id.get(tgt_name)
                )
                if tgt and tgt != src:
                    links.append({'source': src, 'target': tgt, 'type': rel_type})
        except Exception:
            pass

    # 按 chapter_num 排序，section_name 空字符在前（章级别条目先显示）
    chapters = sorted(
        [{'name': ch, 'num': num, 'section_name': sec}
         for (ch, sec), num in sections_seen.items()],
        key=lambda c: (c['num'], c['section_name']),
    )
    return jsonify({
        'nodes': nodes,
        'links': links,
        'chapters': chapters,
        'total_nodes': len(nodes),
        'total_links': len(links),
    })


@rag_bp.route('/api/rag/ds-generate', methods=['POST'])
def ds_generate():
    """基于 DS 提取的知识图谱生成题目（DeepSeek 直出，无向量检索）。"""
    import json as _json
    _init_ds_db()
    data = request.json or {}
    doc_ids                  = data.get('doc_ids', [])
    chapters                 = data.get('chapters', [])
    kp_names                 = data.get('kp_names', [])
    teaching_focus_filter    = data.get('teaching_focus_filter', [])   # ['重点','难点','考点'] 子集
    knowledge_type_filter    = data.get('knowledge_type_filter', [])   # ['概念性', ...] 子集
    cognitive_dimension_filter = data.get('cognitive_dimension_filter', [])  # ['理解', ...] 子集
    prompt_template          = data.get('prompt', '')
    question_list            = data.get('question_list', '')

    if not prompt_template:
        return jsonify({'error': '未提供提示词模板'}), 400

    if not doc_ids:
        return jsonify({'error': '请先勾选文档'}), 400

    # ── 从 DS 数据库读取相关知识点 ────────────────────────────────────────────
    kps_data = []
    try:
        with _ds_db_conn() as conn:
            for doc_id in doc_ids:
                query = (
                    "SELECT chapter_name, chapter_num, kp_name, kp_content, relations_json "
                    "FROM ds_kps WHERE doc_id=?"
                )
                params: list = [doc_id]
                if chapters:
                    # 解析 chapters 参数，支持 "章名|||节名" 和纯 "章名" 两种格式
                    chapter_filters = []
                    for ch_val in chapters:
                        if '|||' in ch_val:
                            ch_name, sec_name = ch_val.split('|||', 1)
                            chapter_filters.append((ch_name.strip(), sec_name.strip()))
                        else:
                            chapter_filters.append((ch_val.strip(), None))
                    parts = []
                    for ch_name, sec_name in chapter_filters:
                        if sec_name:
                            parts.append("(chapter_name=? AND COALESCE(section_name,'')=?)")
                            params.extend([ch_name, sec_name])
                        else:
                            parts.append("chapter_name=?")
                            params.append(ch_name)
                    query += " AND (" + " OR ".join(parts) + ")"
                if kp_names:
                    placeholders = ','.join(['?' for _ in kp_names])
                    query += f" AND kp_name IN ({placeholders})"
                    params.extend(kp_names)
                # 教学属性过滤：teaching_focus 可能是逗号分隔多值，用 INSTR 匹配
                if teaching_focus_filter:
                    tf_parts = [
                        "INSTR(COALESCE(teaching_focus,''), ?) > 0"
                        for _ in teaching_focus_filter
                    ]
                    query += " AND (" + " OR ".join(tf_parts) + ")"
                    params.extend(teaching_focus_filter)
                if knowledge_type_filter:
                    ph = ','.join('?' * len(knowledge_type_filter))
                    query += f" AND knowledge_type IN ({ph})"
                    params.extend(knowledge_type_filter)
                if cognitive_dimension_filter:
                    ph = ','.join('?' * len(cognitive_dimension_filter))
                    query += f" AND cognitive_dimension IN ({ph})"
                    params.extend(cognitive_dimension_filter)
                query += " ORDER BY chapter_num, id"
                rows = conn.execute(query, params).fetchall()
                kps_data.extend(rows)
    except Exception:
        kps_data = []

    if not kps_data:
        return jsonify({'error': '未找到知识点数据，请先完成知识点提取'}), 400

    # ── 构建知识图谱 context ──────────────────────────────────────────────────
    context_parts: list = []
    current_chapter = None
    total_chars = 0
    for kp in kps_data:
        if total_chars > 7000:
            context_parts.append('\n（已达上下文长度上限，后续知识点省略）')
            break
        if kp['chapter_name'] != current_chapter:
            current_chapter = kp['chapter_name']
            context_parts.append(f'\n## {current_chapter}\n')
        context_parts.append(f'### 知识点：{kp["kp_name"]}')
        context_parts.append(kp['kp_content'])
        try:
            rels = _json.loads(kp['relations_json'] or '[]')
            if rels:
                rel_str = '；'.join(
                    f"{r.get('type', '')} → {r.get('target', '')}"
                    for r in rels
                    if r.get('target')
                )
                if rel_str:
                    context_parts.append(f'关联关系：{rel_str}')
        except Exception:
            pass
        context_parts.append('')
        total_chars += len(kp['kp_content'])
    context = '\n'.join(context_parts)

    # ── 替换占位符并调用 DeepSeek ─────────────────────────────────────────────
    final_prompt = (
        prompt_template
        .replace('{context}', context)
        .replace('{question_list}', question_list)
    )

    try:
        api_key = _get_deepseek_key()
        if not api_key:
            return jsonify({
                'error': '未设置 DEEPSEEK_API_KEY，请在 API 配置中填写'
            }), 400

        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com')
        response = client.chat.completions.create(
            model='deepseek-chat',
            messages=[
                {
                    'role': 'system',
                    'content': '你是一位专业的教学内容设计专家，擅长根据课程知识图谱设计题库。',
                },
                {'role': 'user', 'content': final_prompt},
            ],
            max_tokens=8000,
            temperature=0.7,
        )
        content = response.choices[0].message.content
        return jsonify({
            'success': True,
            'content': content,
            'stats': {
                'kps_used': len(kps_data),
                'context_chars': len(context),
            },
        })
    except Exception as e:
        return jsonify({'error': f'DeepSeek API 调用失败：{str(e)}'}), 500
