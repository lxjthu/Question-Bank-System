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
        conn.commit()
        # 迁移：旧库自动补充缺失列
        for migration_sql in [
            "ALTER TABLE ds_docs ADD COLUMN architecture_json TEXT DEFAULT '{}'",
            "ALTER TABLE ds_chapters ADD COLUMN parent_chapter_num INTEGER DEFAULT 0",
            "ALTER TABLE ds_chapters ADD COLUMN parent_chapter_name TEXT DEFAULT ''",
        ]:
            try:
                conn.execute(migration_sql)
                conn.commit()
            except Exception:
                pass  # 列已存在，忽略


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
        if suffix in ('.md', '.txt'):
            raw_text = save_path.read_text(encoding='utf-8', errors='replace')
            cleaned_text, had_markers = _clean_ocr_md(raw_text)
        else:
            cleaned_text, had_markers = None, False

        # 分析标题层级：先用本地扫描，OCR 文件额外用 DeepSeek 精确判断章级别
        if cleaned_text is not None:
            chapter_level, section_level = _analyze_doc_structure(cleaned_text)
            if had_markers:
                api_key = _get_deepseek_key()
                if api_key:
                    try:
                        from openai import OpenAI as _OAI
                        _ds_client = _OAI(api_key=api_key, base_url='https://api.deepseek.com')
                        ds_chapter_level = _detect_chapter_level(cleaned_text, subject, _ds_client)
                        if ds_chapter_level != chapter_level:
                            # DeepSeek 给出了不同的章级别，重新推断节级别
                            chapter_level = ds_chapter_level
                            _, section_level = _analyze_doc_structure(cleaned_text)
                            # 节级别必须比章级别深
                            if section_level is not None and section_level <= chapter_level:
                                section_level = None
                    except Exception:
                        pass  # 保留本地分析结果

            sections = _parse_md_to_sections(cleaned_text, chapter_level, section_level)
        else:
            sections = _parse_file_to_sections(save_path, suffix)

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
                    "(doc_id, chapter_num, chapter_name, parent_chapter_num, parent_chapter_name, raw_text) "
                    "VALUES (?,?,?,?,?,?)",
                    (doc_id, sec['num'], sec['name'],
                     sec['parent_chapter_num'], sec['parent_chapter_name'],
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
            "SELECT chapter_num, chapter_name, parent_chapter_num, parent_chapter_name, raw_text "
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
                # 提示词中的 chapter_name 展示节名，让 DS 知道当前处理的是哪一节
                display_name = (
                    f"{ch['parent_chapter_name']} > {ch['chapter_name']}"
                    if ch['chapter_name'] != ch['parent_chapter_name']
                    else ch['chapter_name']
                )
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
                                            "(doc_id, chapter_name, chapter_num, "
                                            "kp_name, kp_content, relations_json) "
                                            "VALUES (?,?,?,?,?,?)",
                                            (
                                                doc_id,
                                                # chapter_name 存父章名，供 UI 分组
                                                ch['parent_chapter_name'],
                                                ch['parent_chapter_num'],
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
            "SELECT id, doc_id, chapter_name, chapter_num, kp_name, kp_content, relations_json "
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
    })


@rag_bp.route('/api/rag/ds-kps/<int:kp_id>', methods=['PUT'])
def ds_kp_update(kp_id):
    """更新单个知识点（name、content、relations）。"""
    _init_ds_db()
    data = request.json or {}

    name = data.get('name', '').strip()
    content = data.get('content', '').strip()
    relations = data.get('relations', [])

    if not name:
        return jsonify({'error': '知识点名称不能为空'}), 400
    if not isinstance(relations, list):
        return jsonify({'error': 'relations 必须为列表'}), 400

    # 过滤掉无效条目
    clean_relations = [
        r for r in relations
        if isinstance(r, dict) and r.get('target', '').strip()
    ]

    with _ds_db_conn() as conn:
        cur = conn.execute(
            "UPDATE ds_kps SET kp_name=?, kp_content=?, relations_json=? WHERE id=?",
            (name, content, _json_mod.dumps(clean_relations, ensure_ascii=False), kp_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({'error': f'知识点 {kp_id} 不存在'}), 404

    return jsonify({'success': True, 'id': kp_id})


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
        # 返回父章去重列表（用于 UI 章节筛选）
        chapters = conn.execute(
            "SELECT DISTINCT parent_chapter_num as chapter_num, parent_chapter_name as chapter_name "
            "FROM ds_chapters WHERE doc_id=? GROUP BY parent_chapter_num ORDER BY parent_chapter_num",
            (doc_id,),
        ).fetchall()
        kps = conn.execute(
            "SELECT id, chapter_name, chapter_num, kp_name, kp_content, relations_json "
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
        'chapters': [{'num': c['chapter_num'], 'name': c['chapter_name']} for c in chapters],
        'kps': [
            {
                'id': k['id'],
                'chapter_name': k['chapter_name'],
                'chapter_num': k['chapter_num'],
                'name': k['kp_name'],
                'content': k['kp_content'],
                'relations': k['relations_json'],
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
    chapters_map: dict = {}

    for row in rows:
        nid = f"kp_{row['id']}"
        name_to_id[(row['doc_id'], row['kp_name'])] = nid
        name_to_id.setdefault(row['kp_name'], nid)
        nodes.append({
            'id': nid,
            'name': row['kp_name'],
            'chapter': row['chapter_name'],
            'chapter_num': row['chapter_num'],
            'doc_id': row['doc_id'],
            'content': row['kp_content'],
        })
        chapters_map.setdefault(row['chapter_name'], row['chapter_num'])

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

    chapters = sorted(
        [{'name': k, 'num': v} for k, v in chapters_map.items()],
        key=lambda c: c['num'],
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
    doc_ids = data.get('doc_ids', [])
    chapters = data.get('chapters', [])
    kp_names = data.get('kp_names', [])
    prompt_template = data.get('prompt', '')
    question_list = data.get('question_list', '')

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
                    placeholders = ','.join(['?' for _ in chapters])
                    query += f" AND chapter_name IN ({placeholders})"
                    params.extend(chapters)
                if kp_names:
                    placeholders = ','.join(['?' for _ in kp_names])
                    query += f" AND kp_name IN ({placeholders})"
                    params.extend(kp_names)
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
