"""RAG API Blueprint — AI 智能出题后端。

端点：
  GET    /api/rag/docs                  列出已摄入文档
  GET    /api/rag/docs/<doc_id>/meta    获取文档章节/节名
  DELETE /api/rag/docs/<doc_id>         删除文档
  POST   /api/rag/ingest                上传并摄入文档
  GET    /api/rag/tasks/<task_id>       轮询 OCR 后台任务状态
  POST   /api/rag/generate              RAG 检索 + DeepSeek 出题
"""
from __future__ import annotations

import os
import sys
import uuid
import sqlite3
import threading
from pathlib import Path

from flask import Blueprint, request, jsonify

rag_bp = Blueprint('rag', __name__)

# ── 单例组件（懒加载）─────────────────────────────────────────────────────────
_lock = threading.Lock()
_components = None  # (Embedder, VectorStore, BM25Index) — 全局共享，避免双 QdrantClient 锁冲突
_ingestor = None    # rag_pipeline.ingest.Ingestor
_retriever = None   # rag_pipeline.retriever.HybridRetriever

# OCR 后台任务状态表  {task_id: {status, message, doc_id}}
_ocr_tasks: dict = {}

# RAG 文档上传目录
_UPLOAD_DIR = Path(__file__).parent.parent / "rag_uploads"


# ── 路径工具 ──────────────────────────────────────────────────────────────────

def _project_root() -> Path:
    return Path(__file__).parent.parent


def _rag_pipeline_dir() -> Path:
    return _project_root() / "rag_pipeline"


def _rag_db_path() -> Path:
    return _rag_pipeline_dir() / "kg.db"


def _ensure_upload_dir():
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _add_to_path():
    """将项目根目录加入 sys.path，使 rag_pipeline / pptx_ocr 可直接导入。"""
    root = str(_project_root())
    if root not in sys.path:
        sys.path.insert(0, root)


# ── 单例懒加载 ────────────────────────────────────────────────────────────────

def _get_components():
    """
    初始化并返回共享的 (Embedder, VectorStore, BM25Index)。

    Qdrant 本地文件模式同一时间只允许一个 QdrantClient 持有锁，
    因此 Ingestor 和 HybridRetriever 必须共用同一个 VectorStore 实例。
    本函数保证全局只创建一次，只在已持有 _lock 的情况下调用。
    """
    global _components
    if _components is not None:
        return _components
    _add_to_path()
    from rag_pipeline.config import EMBEDDING_MODEL, QDRANT_PATH, BM25_PATH
    from rag_pipeline.embedder import Embedder
    from rag_pipeline.vector_store import VectorStore
    from rag_pipeline.bm25_index import BM25Index

    emb = Embedder(model_name=EMBEDDING_MODEL)
    vs = VectorStore(QDRANT_PATH)
    vs.ensure_collection(emb.dim)
    bm25 = BM25Index(BM25_PATH)
    _components = (emb, vs, bm25)
    return _components


def _get_ingestor():
    global _ingestor
    if _ingestor is not None:
        return _ingestor
    with _lock:
        if _ingestor is not None:
            return _ingestor
        emb, vs, bm25 = _get_components()
        from rag_pipeline.ingest import Ingestor
        _ingestor = Ingestor(emb=emb, vs=vs, bm25=bm25)
    return _ingestor


def _get_retriever():
    global _retriever
    if _retriever is not None:
        return _retriever
    with _lock:
        if _retriever is not None:
            return _retriever
        emb, vs, bm25 = _get_components()
        from rag_pipeline.retriever import HybridRetriever
        _retriever = HybridRetriever(vector_store=vs, bm25_index=bm25, embedder=emb)
    return _retriever


# ── SQLite 帮助函数 ───────────────────────────────────────────────────────────

def _db_conn():
    conn = sqlite3.connect(str(_rag_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


# ── .env 读写工具 ─────────────────────────────────────────────────────────────

def _env_path() -> Path:
    return _project_root() / ".env"


def _read_env_vars(*keys) -> dict:
    """从 .env 文件读取指定 key，不影响进程环境变量。"""
    from dotenv import dotenv_values
    vals = dotenv_values(str(_env_path())) if _env_path().exists() else {}
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
        # 跳过注释和空行，直接保留
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

    # 追加尚未出现的 key
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}\n")

    env_file.write_text(''.join(new_lines), encoding='utf-8')


# ═══════════════════════════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════════════════════════

@rag_bp.route('/api/rag/docs', methods=['GET'])
def list_rag_docs():
    """列出所有已摄入文档及其 chunk 数量。"""
    try:
        if not _rag_db_path().exists():
            return jsonify([])
        with _db_conn() as conn:
            rows = conn.execute(
                "SELECT doc_id, source_type, COUNT(*) as chunk_count "
                "FROM chunks GROUP BY doc_id ORDER BY doc_id"
            ).fetchall()
        return jsonify([
            {
                'doc_id': r['doc_id'],
                'source_type': r['source_type'],
                'chunk_count': r['chunk_count'],
            }
            for r in rows
        ])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@rag_bp.route('/api/rag/docs/<path:doc_id>/meta', methods=['GET'])
def rag_doc_meta(doc_id):
    """获取文档的章节名和节名（用于前端筛选）。

    sections 响应字段：
      num          — section_num
      name         — section_name（原始内部名，如 "Slide 1"，用于生成 API 查询）
      chapter_num  — 所属章节编号
      chapter_name — 所属章节名称（用于前端按章节联动过滤知识点）
      display_name — 展示用名称（slides 类型取首行内容，textbook 同 name）
    """
    try:
        if not _rag_db_path().exists():
            return jsonify({'chapters': [], 'sections': []})
        with _db_conn() as conn:
            chapters = conn.execute(
                "SELECT DISTINCT chapter_num, chapter_name FROM chunks "
                "WHERE doc_id=? AND chapter_name != '' ORDER BY chapter_num",
                (doc_id,),
            ).fetchall()

            # 判断文档类型，用于决定 display_name 格式
            src_row = conn.execute(
                "SELECT source_type FROM chunks WHERE doc_id=? LIMIT 1", (doc_id,)
            ).fetchone()
            source_type = src_row['source_type'] if src_row else ''

            # 获取每节的去重信息（含所属章节）
            sections_raw = conn.execute(
                "SELECT DISTINCT section_num, section_name, chapter_num, chapter_name "
                "FROM chunks WHERE doc_id=? AND section_name != '' ORDER BY section_num",
                (doc_id,),
            ).fetchall()

            sections = []
            for r in sections_raw:
                display_name = r['section_name']
                if source_type == 'slides':
                    # 取该页第一个 chunk 的文本首行作为知识点描述
                    text_row = conn.execute(
                        "SELECT text FROM chunks WHERE doc_id=? AND section_num=? "
                        "ORDER BY rowid LIMIT 1",
                        (doc_id, r['section_num']),
                    ).fetchone()
                    if text_row and text_row['text']:
                        first_line = text_row['text'].strip().split('\n')[0].strip()[:60]
                        if first_line:
                            display_name = f"第{r['section_num']}页: {first_line}"
                sections.append({
                    'num': r['section_num'],
                    'name': r['section_name'],
                    'chapter_num': r['chapter_num'],
                    'chapter_name': r['chapter_name'],
                    'display_name': display_name,
                })

        return jsonify({
            'chapters': [
                {'num': r['chapter_num'], 'name': r['chapter_name']} for r in chapters
            ],
            'sections': sections,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@rag_bp.route('/api/rag/docs/<path:doc_id>', methods=['DELETE'])
def rag_delete_doc(doc_id):
    """从向量库、SQLite chunks 和知识图谱表中删除文档。"""
    try:
        _add_to_path()
        ingestor = _get_ingestor()
        ingestor.delete_doc(doc_id)
        # 同步删除该文档的幻灯片 KG（若有）
        from rag_pipeline import db as rag_db
        rag_db.delete_kg_by_doc(doc_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@rag_bp.route('/api/rag/ingest', methods=['POST'])
def rag_ingest():
    """上传文件并摄入知识库。"""
    _ensure_upload_dir()

    if 'file' not in request.files:
        return jsonify({'error': '未提供文件'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': '文件名为空'}), 400

    doc_type = request.form.get('doc_type', 'auto')  # auto / textbook / slides
    filename = file.filename
    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem
    doc_id = stem[:40]  # 截断过长名称

    save_path = _UPLOAD_DIR / filename
    file.save(str(save_path))

    # ── 文本格式：同步摄入 ─────────────────────────────────────────────────
    if suffix in ('.md', '.txt'):
        try:
            ingestor = _get_ingestor()
            if doc_type == 'slides':
                n = ingestor.ingest_slides(doc_id, save_path, doc_title=stem)
            else:
                n = ingestor.ingest_textbook(doc_id, save_path)
            return jsonify({'success': True, 'doc_id': doc_id, 'chunk_count': n})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── DOCX：提取段落 → 临时 MD → 摄入 ──────────────────────────────────
    if suffix == '.docx':
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(str(save_path))
            md_lines = [f'# {stem}', '']
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    md_lines.append(text)
                    md_lines.append('')
            tmp_md = _UPLOAD_DIR / (stem + '_converted.md')
            tmp_md.write_text('\n'.join(md_lines), encoding='utf-8')
            ingestor = _get_ingestor()
            n = ingestor.ingest_textbook(doc_id, tmp_md)
            return jsonify({'success': True, 'doc_id': doc_id, 'chunk_count': n})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── PPTX / PDF：异步 OCR ─────────────────────────────────────────────
    if suffix in ('.pptx', '.ppt', '.pdf'):
        task_id = str(uuid.uuid4())[:8]
        subject_hint = request.form.get('subject_hint', stem)  # 学科提示，默认取文件名
        _ocr_tasks[task_id] = {
            'status': 'running',
            'message': 'OCR 处理中，请稍候...',
            'doc_id': doc_id,
        }

        def _ocr_worker(task_id, suffix, save_path, doc_id, doc_type, stem, subject_hint):
            try:
                _add_to_path()
                # 每次 OCR 任务启动时从 .env 读取最新配置，确保界面保存后立即生效
                ocr_cfg = _read_env_vars('PADDLEOCR_API_URL', 'PADDLEOCR_TOKEN', 'PADDLEOCR_TIMEOUT')
                ocr_url     = ocr_cfg.get('PADDLEOCR_API_URL', '')
                ocr_token   = ocr_cfg.get('PADDLEOCR_TOKEN', '')
                ocr_timeout = int(ocr_cfg.get('PADDLEOCR_TIMEOUT') or 120)

                ocr_output = _UPLOAD_DIR / (stem + '_ocr')
                if suffix == '.pdf':
                    from pptx_ocr.pipeline import process_pdf
                    result_md = process_pdf(
                        save_path, output_dir=ocr_output,
                        api_url=ocr_url, api_token=ocr_token, api_timeout=ocr_timeout,
                    )
                else:
                    from pptx_ocr.pipeline import process_pptx
                    result_md = process_pptx(
                        save_path, output_dir=ocr_output,
                        api_url=ocr_url, api_token=ocr_token, api_timeout=ocr_timeout,
                    )

                ingestor = _get_ingestor()
                use_slides = (suffix in ('.pptx', '.ppt') or doc_type == 'slides')
                if use_slides:
                    n = ingestor.ingest_slides(doc_id, result_md, doc_title=stem)
                    # ── 幻灯片专属：调用 DeepSeek 构建知识图谱 ──────────────
                    _ocr_tasks[task_id]['message'] = (
                        f'文本块摄入完成（{n} 块），正在调用 DeepSeek 提取知识图谱...'
                    )
                    try:
                        from rag_pipeline.slides_kg import build_kg_for_slides

                        def _kg_progress(cur, total, name):
                            _ocr_tasks[task_id]['message'] = (
                                f'知识图谱提取中... [{cur}/{total}] {name}'
                            )

                        n_topics = build_kg_for_slides(
                            doc_id, result_md,
                            subject_hint=subject_hint,
                            progress_callback=_kg_progress,
                        )
                        _ocr_tasks[task_id] = {
                            'status': 'done',
                            'message': f'完成！{n} 个文本块，{n_topics} 个主题组的知识图谱已提取。',
                            'doc_id': doc_id,
                        }
                    except Exception as kg_err:
                        # KG 提取失败不影响 RAG 检索，降级处理
                        _ocr_tasks[task_id] = {
                            'status': 'done',
                            'message': (
                                f'文本块摄入成功（{n} 块）；'
                                f'知识图谱提取失败（{kg_err}），可手动重试。'
                            ),
                            'doc_id': doc_id,
                        }
                else:
                    n = ingestor.ingest_textbook(doc_id, result_md)
                    _ocr_tasks[task_id] = {
                        'status': 'done',
                        'message': f'完成！共摄入 {n} 个文本块。',
                        'doc_id': doc_id,
                    }
            except Exception as e:
                _ocr_tasks[task_id] = {
                    'status': 'error',
                    'message': str(e),
                    'doc_id': doc_id,
                }

        t = threading.Thread(
            target=_ocr_worker,
            args=(task_id, suffix, save_path, doc_id, doc_type, stem, subject_hint),
            daemon=True,
        )
        t.start()
        return jsonify({'success': True, 'task_id': task_id, 'doc_id': doc_id, 'async': True})

    return jsonify({'error': f'不支持的文件类型：{suffix}'}), 400


@rag_bp.route('/api/rag/tasks/<task_id>', methods=['GET'])
def rag_task_status(task_id):
    """轮询 OCR 后台任务状态。"""
    task = _ocr_tasks.get(task_id)
    if task is None:
        return jsonify({'error': '任务不存在'}), 404
    return jsonify(task)


@rag_bp.route('/api/rag/generate', methods=['POST'])
def rag_generate():
    """RAG 检索 → 拼提示词 → DeepSeek API → 返回题目文本。"""
    data = request.json or {}

    doc_ids = data.get('doc_ids', [])           # 限定文档范围
    chapters = data.get('chapters', [])          # 章节名（用于检索 query）
    knowledge_points = data.get('knowledge_points', [])  # 知识点/节名
    prompt_template = data.get('prompt', '')     # 含 {context} / {question_list}
    question_list = data.get('question_list', '')

    if not prompt_template:
        return jsonify({'error': '未提供提示词模板'}), 400

    # ── 构建检索 queries ──────────────────────────────────────────────────
    queries = []
    for ch in chapters[:6]:
        queries.append(ch)
    for kp in knowledge_points[:6]:
        queries.append(kp)
    if not queries:
        queries = ['课程核心知识点', '重要概念原理', '典型案例分析']

    # ── RAG 检索 context ──────────────────────────────────────────────────
    context = ''
    chunks_used = 0
    try:
        retriever = _get_retriever()
        seen_ids: set = set()
        chunks = []

        for query in queries[:12]:
            try:
                results = retriever.search(
                    query,
                    top_n=6,
                    doc_ids=doc_ids if doc_ids else None,
                )
                for r in results:
                    if r['chunk_id'] not in seen_ids:
                        chunks.append(r)
                        seen_ids.add(r['chunk_id'])
            except Exception:
                continue

        context_parts = []
        total_chars = 0
        for chunk in chunks:
            text = chunk.get('text', '')
            if total_chars + len(text) > 6000:
                break
            context_parts.append(text)
            total_chars += len(text)

        context = '\n\n---\n\n'.join(context_parts) if context_parts else ''
        chunks_used = len(context_parts)
    except Exception:
        # RAG 组件未就绪时退化为无上下文模式
        context = ''
        chunks_used = 0

    if not context:
        context = '（知识库暂无相关内容，请根据题目配置和科目知识直接出题）'

    # ── 替换提示词占位符 ──────────────────────────────────────────────────
    final_prompt = (
        prompt_template
        .replace('{context}', context)
        .replace('{question_list}', question_list)
    )

    # ── 调用 DeepSeek API ─────────────────────────────────────────────────
    try:
        _add_to_path()
        # 用 dotenv_values() 直接从文件读取，不受系统/进程环境变量干扰
        from dotenv import dotenv_values
        env_file = _project_root() / '.env'
        env_vals = dotenv_values(env_file) if env_file.exists() else {}
        api_key = (
            env_vals.get('DEEPSEEK_API_KEY')
            or env_vals.get('DEEPSEEK_TOKEN')
            or os.environ.get('DEEPSEEK_API_KEY', '')
            or os.environ.get('DEEPSEEK_TOKEN', '')
        )
        if not api_key:
            return jsonify({
                'error': '未设置 DEEPSEEK_API_KEY，请在项目根目录 .env 文件中添加：\nDEEPSEEK_API_KEY=your_key_here'
            }), 400

        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com')

        response = client.chat.completions.create(
            model='deepseek-chat',
            messages=[
                {
                    'role': 'system',
                    'content': '你是一位专业的教学内容设计专家，擅长根据课程材料设计题库。',
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
                'chunks_used': chunks_used,
                'context_chars': len(context),
            },
        })
    except Exception as e:
        return jsonify({'error': f'DeepSeek API 调用失败：{str(e)}'}), 500


@rag_bp.route('/api/rag/config', methods=['GET'])
def rag_get_config():
    """读取 .env 中的 API 配置（仅返回 RAG 相关字段）。"""
    vals = _read_env_vars(
        'PADDLEOCR_API_URL', 'PADDLEOCR_TOKEN',
        'DEEPSEEK_API_KEY', 'DEEPSEEK_TOKEN',
    )
    return jsonify({
        'paddleocr_url':   vals.get('PADDLEOCR_API_URL', ''),
        'paddleocr_token': vals.get('PADDLEOCR_TOKEN', ''),
        'deepseek_api_key': (
            vals.get('DEEPSEEK_API_KEY')
            or vals.get('DEEPSEEK_TOKEN')
            or ''
        ),
    })


@rag_bp.route('/api/rag/config', methods=['PUT'])
def rag_set_config():
    """将前端提交的 API 配置写入 .env 文件。"""
    data = request.json or {}
    updates: dict = {}
    if 'paddleocr_url' in data:
        updates['PADDLEOCR_API_URL'] = data['paddleocr_url'].strip()
    if 'paddleocr_token' in data:
        updates['PADDLEOCR_TOKEN'] = data['paddleocr_token'].strip()
    if 'deepseek_api_key' in data:
        updates['DEEPSEEK_API_KEY'] = data['deepseek_api_key'].strip()
        # 同时清除旧版 key 名（避免两个同时生效时歧义）
        updates.setdefault('DEEPSEEK_TOKEN', '')
    if not updates:
        return jsonify({'error': '未提供任何配置'}), 400
    try:
        _write_env_vars(updates)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
