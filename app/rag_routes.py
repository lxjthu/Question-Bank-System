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
                doc_id     TEXT PRIMARY KEY,
                filename   TEXT,
                subject    TEXT,
                status     TEXT DEFAULT 'uploaded',
                error_msg  TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ds_chapters (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id       TEXT,
                chapter_num  INTEGER,
                chapter_name TEXT,
                raw_text     TEXT
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


def _parse_md_to_chapters(text: str, heading_level: int = 1) -> list:
    """将 Markdown/TXT 文本按指定标题级别切分为章节列表。

    返回 [{'num': int, 'name': str, 'text': str}, ...]，过滤空章节。
    """
    import re
    pattern = re.compile(
        r'^#{' + str(heading_level) + r'}(?!#)\s+(.+)',
        re.MULTILINE,
    )
    chapters: list = []
    current_title = '（前言/概述）'
    current_num = 0
    current_lines: list = []
    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            if current_lines:
                chapters.append({
                    'num': current_num,
                    'name': current_title,
                    'text': '\n'.join(current_lines).strip(),
                })
            current_num += 1
            current_title = m.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        chapters.append({
            'num': current_num,
            'name': current_title,
            'text': '\n'.join(current_lines).strip(),
        })
    return [c for c in chapters if c['text'].strip()]


def _parse_file_to_chapters(filepath: Path, suffix: str,
                             heading_level: int = 1) -> list:
    """从文件解析章节列表，支持 .md / .txt / .docx。"""
    if suffix in ('.md', '.txt'):
        text = filepath.read_text(encoding='utf-8', errors='replace')
        cleaned, _ = _clean_ocr_md(text)
        return _parse_md_to_chapters(cleaned, heading_level)
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
                else:
                    md_lines.append(t)
            combined = '\n'.join(md_lines)
            cleaned, _ = _clean_ocr_md(combined)
            return _parse_md_to_chapters(cleaned, heading_level)
        except Exception:
            return []
    return []


# ── 知识点提取提示词 ──────────────────────────────────────────────────────────

_DS_EXTRACT_SYSTEM = '你是一位专业的教材分析专家，擅长从教材中提取结构化知识图谱。'

_DS_EXTRACT_PROMPT = """请分析以下教材章节内容，提取该章节的核心知识点及其关系，构建知识图谱。

【学科/科目】：{subject}
【章节名称】：{chapter_name}

【章节原文】：
{chapter_text}

---
**任务要求：**
1. 提取 3-8 个核心知识点
2. 每个知识点的 content 字段应尽量引用原文关键表述，包含：定义/概念、特征/特点、分类/类型、示例/案例等
3. 仅标注同一章节内知识点之间的关系
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

        # 若发现页码标记，调用 DeepSeek 智能检测章节级别
        chapter_level = 1
        if had_markers:
            api_key = _get_deepseek_key()
            if api_key:
                try:
                    from openai import OpenAI as _OAI
                    _ds_client = _OAI(api_key=api_key, base_url='https://api.deepseek.com')
                    chapter_level = _detect_chapter_level(cleaned_text, subject, _ds_client)
                except Exception:
                    chapter_level = 1

        if cleaned_text is not None:
            chapters = _parse_md_to_chapters(cleaned_text, chapter_level)
        else:
            chapters = _parse_file_to_chapters(save_path, suffix, chapter_level)

        if not chapters:
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
            for ch in chapters:
                conn.execute(
                    "INSERT INTO ds_chapters (doc_id, chapter_num, chapter_name, raw_text) VALUES (?,?,?,?)",
                    (doc_id, ch['num'], ch['name'], ch['text']),
                )
            conn.commit()

        return jsonify({
            'success': True,
            'doc_id': doc_id,
            'chapter_count': len(chapters),
            'chapters': [{'num': c['num'], 'name': c['name']} for c in chapters],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@rag_bp.route('/api/rag/ds-extract/<path:doc_id>', methods=['POST'])
def ds_extract(doc_id):
    """异步：逐章调用 DeepSeek 提取知识点，构建知识图谱。

    resume=True 时跳过已提取的章节，实现断点续传。
    """
    _init_ds_db()
    data = request.json or {}
    subject = data.get('subject', '')
    resume = bool(data.get('resume', False))

    with _ds_db_conn() as conn:
        conn.execute("UPDATE ds_docs SET subject=? WHERE doc_id=?", (subject, doc_id))
        conn.execute(
            "UPDATE ds_docs SET status='extracting', error_msg='' WHERE doc_id=?",
            (doc_id,),
        )
        if not resume:
            conn.execute("DELETE FROM ds_kps WHERE doc_id=?", (doc_id,))
        conn.commit()
        all_chapters = conn.execute(
            "SELECT chapter_num, chapter_name, raw_text FROM ds_chapters "
            "WHERE doc_id=? ORDER BY chapter_num",
            (doc_id,),
        ).fetchall()
        if resume:
            extracted_nums = {
                r[0] for r in conn.execute(
                    "SELECT DISTINCT chapter_num FROM ds_kps WHERE doc_id=?",
                    (doc_id,),
                ).fetchall()
            }
            chapters = [ch for ch in all_chapters if ch['chapter_num'] not in extracted_nums]
        else:
            chapters = list(all_chapters)

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

    total_chapters = len(all_chapters)
    task_id = str(uuid.uuid4())[:8]
    _ds_tasks[task_id] = {
        'status': 'running',
        'message': '准备开始...',
        'doc_id': doc_id,
        'progress': 0,
        'total': len(chapters),
        'total_chapters': total_chapters,
        'pause_requested': False,
    }

    def _worker(task_id, doc_id, subject, chapters):
        import json as _json
        try:
            api_key = _get_deepseek_key()
            if not api_key:
                with _ds_db_conn() as conn:
                    conn.execute(
                        "UPDATE ds_docs SET status='error', error_msg=? WHERE doc_id=?",
                        ('未设置 DEEPSEEK_API_KEY', doc_id),
                    )
                    conn.commit()
                _ds_tasks[task_id] = {
                    'status': 'error',
                    'message': '未设置 DEEPSEEK_API_KEY，请在 API 配置中填写',
                    'doc_id': doc_id,
                }
                return

            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com')
            total = len(chapters)

            for i, ch in enumerate(chapters):
                if _ds_tasks.get(task_id, {}).get('pause_requested', False):
                    with _ds_db_conn() as conn:
                        kp_count = conn.execute(
                            "SELECT COUNT(*) FROM ds_kps WHERE doc_id=?", (doc_id,)
                        ).fetchone()[0]
                        ch_done = conn.execute(
                            "SELECT COUNT(DISTINCT chapter_num) FROM ds_kps WHERE doc_id=?",
                            (doc_id,),
                        ).fetchone()[0]
                        conn.execute(
                            "UPDATE ds_docs SET status='paused' WHERE doc_id=?", (doc_id,)
                        )
                        conn.commit()
                    _ds_tasks[task_id] = {
                        'status': 'paused',
                        'message': (
                            f'已暂停。已完成 {ch_done}/{_ds_tasks[task_id].get("total_chapters", total)} 章，'
                            f'共 {kp_count} 个知识点'
                        ),
                        'doc_id': doc_id,
                        'progress': i,
                        'total': total,
                        'total_chapters': _ds_tasks[task_id].get('total_chapters', total),
                        'kp_count': kp_count,
                    }
                    return

                _ds_tasks[task_id].update({
                    'message': f'正在提取第 {i + 1}/{total} 章：{ch["chapter_name"]}',
                    'progress': i,
                    'total': total,
                })
                ch_text = ch['raw_text']
                if len(ch_text) > 8000:
                    ch_text = ch_text[:8000] + '\n\n[（内容过长，已截断）]'

                prompt = _DS_EXTRACT_PROMPT.format(
                    subject=subject or '（未指定）',
                    chapter_name=ch['chapter_name'],
                    chapter_text=ch_text,
                )
                try:
                    resp = client.chat.completions.create(
                        model='deepseek-chat',
                        messages=[
                            {'role': 'system', 'content': _DS_EXTRACT_SYSTEM},
                            {'role': 'user', 'content': prompt},
                        ],
                        max_tokens=3000,
                        temperature=0.3,
                    )
                    raw = resp.choices[0].message.content.strip()
                    if raw.startswith('```'):
                        raw = '\n'.join(raw.split('\n')[1:])
                    if raw.endswith('```'):
                        raw = '\n'.join(raw.split('\n')[:-1])
                    raw = raw.strip()

                    parsed = _json.loads(raw)
                    kps = parsed.get('knowledge_points', [])
                    with _ds_db_conn() as conn:
                        for kp in kps:
                            conn.execute(
                                "INSERT INTO ds_kps "
                                "(doc_id, chapter_name, chapter_num, kp_name, kp_content, relations_json) "
                                "VALUES (?,?,?,?,?,?)",
                                (
                                    doc_id,
                                    ch['chapter_name'],
                                    ch['chapter_num'],
                                    kp.get('name', ''),
                                    kp.get('content', ''),
                                    _json.dumps(kp.get('relations', []), ensure_ascii=False),
                                ),
                            )
                        conn.commit()
                except Exception as ch_err:
                    _ds_tasks[task_id]['message'] = (
                        f'第 {i + 1} 章提取出错（{ch_err}），跳过，继续下一章...'
                    )

            with _ds_db_conn() as conn:
                kp_count = conn.execute(
                    "SELECT COUNT(*) FROM ds_kps WHERE doc_id=?", (doc_id,)
                ).fetchone()[0]
                conn.execute("UPDATE ds_docs SET status='done' WHERE doc_id=?", (doc_id,))
                conn.commit()
            _ds_tasks[task_id] = {
                'status': 'done',
                'message': f'提取完成！共提取 {kp_count} 个知识点（{total} 章）',
                'doc_id': doc_id,
                'kp_count': kp_count,
                'total': total,
            }
        except Exception as e:
            with _ds_db_conn() as conn:
                conn.execute(
                    "UPDATE ds_docs SET status='error', error_msg=? WHERE doc_id=?",
                    (str(e), doc_id),
                )
                conn.commit()
            _ds_tasks[task_id] = {
                'status': 'error',
                'message': str(e),
                'doc_id': doc_id,
            }

    t = threading.Thread(
        target=_worker, args=(task_id, doc_id, subject, list(chapters)), daemon=True
    )
    t.start()
    return jsonify({'success': True, 'task_id': task_id, 'total': len(chapters)})


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
        chapters = conn.execute(
            "SELECT DISTINCT chapter_num, chapter_name FROM ds_chapters "
            "WHERE doc_id=? ORDER BY chapter_num",
            (doc_id,),
        ).fetchall()
        kps = conn.execute(
            "SELECT id, chapter_name, chapter_num, kp_name, kp_content, relations_json "
            "FROM ds_kps WHERE doc_id=? ORDER BY chapter_num, id",
            (doc_id,),
        ).fetchall()
    return jsonify({
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
