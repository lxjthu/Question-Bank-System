"""知识图谱可视化 Blueprint

端点：
  GET  /kg                     — 知识图谱可视化页面（HTML）
  GET  /api/kg/graph           — 图谱节点 + 边数据（供 D3.js 使用）
  GET  /api/kg/chunks          — 指定节点的原文 chunk 列表
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Blueprint, request, jsonify, render_template

kg_bp = Blueprint('kg', __name__)

# ── 路径工具 ──────────────────────────────────────────────────────────────────

def _project_root() -> Path:
    return Path(__file__).parent.parent


def _rag_db_path() -> Path:
    return _project_root() / "rag_pipeline" / "kg.db"


def _db_conn():
    conn = sqlite3.connect(str(_rag_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════════════════════
# 页面端点
# ═══════════════════════════════════════════════════════════════════════════════

@kg_bp.route('/kg')
def kg_page():
    """知识图谱可视化页面。"""
    return render_template('kg.html')


# ═══════════════════════════════════════════════════════════════════════════════
# 数据端点
# ═══════════════════════════════════════════════════════════════════════════════

@kg_bp.route('/api/kg/graph')
def kg_graph():
    """
    返回用于 D3.js 力导向图的节点和边数据。

    Query params:
      doc_id  — 可多次传，过滤文档范围（不传则返回全部）
    """
    if not _rag_db_path().exists():
        return jsonify({'nodes': [], 'links': [], 'docs': [], 'has_kg': False})

    filter_docs = request.args.getlist('doc_id')  # [] 表示不过滤

    try:
        with _db_conn() as conn:
            # ── 1. 从 chunks 构建文档/章节/节 层级 ─────────────────────────
            doc_filter_sql = ''
            params: list = []
            if filter_docs:
                placeholders = ','.join('?' * len(filter_docs))
                doc_filter_sql = f'WHERE doc_id IN ({placeholders})'
                params = list(filter_docs)

            # 获取所有文档
            doc_rows = conn.execute(
                f"SELECT DISTINCT doc_id, source_type FROM chunks {doc_filter_sql} ORDER BY doc_id",
                params,
            ).fetchall()

            # 获取章节
            chapter_rows = conn.execute(
                f"SELECT DISTINCT doc_id, chapter_num, chapter_name, COUNT(*) as chunk_count "
                f"FROM chunks {doc_filter_sql} GROUP BY doc_id, chapter_num ORDER BY doc_id, chapter_num",
                params,
            ).fetchall()

            # 获取节/页
            section_rows = conn.execute(
                f"SELECT DISTINCT doc_id, chapter_num, chapter_name, section_num, section_name, "
                f"COUNT(*) as chunk_count FROM chunks {doc_filter_sql} "
                f"GROUP BY doc_id, chapter_num, section_num ORDER BY doc_id, chapter_num, section_num",
                params,
            ).fetchall()

            # ── 2. 从 KG 表获取概念和关系（若存在） ─────────────────────────
            concepts = []
            relations = []
            kg_chapters: dict = {}  # chapter_id → {name, number}
            has_kg = False

            try:
                # 检查 concepts 表是否存在且有数据
                tbl = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='concepts'"
                ).fetchone()
                if tbl:
                    concepts = conn.execute(
                        "SELECT c.id, c.chapter_id, c.name, c.description, "
                        "c.is_key_point, c.is_difficult_point, ch.name as chapter_name, "
                        "ch.number as chapter_number, ch.doc_id as chapter_doc_id "
                        "FROM concepts c JOIN chapters ch ON c.chapter_id = ch.id"
                    ).fetchall()
                    relations = conn.execute(
                        "SELECT r.id, r.from_concept_id, r.to_concept_id, r.relation_type "
                        "FROM relations r"
                    ).fetchall()
                    kg_chapters_rows = conn.execute(
                        "SELECT id, number, name, doc_id FROM chapters"
                    ).fetchall()
                    kg_chapters = {r['id']: dict(r) for r in kg_chapters_rows}
                    has_kg = len(concepts) > 0
            except Exception:
                pass  # KG 表不存在则跳过

            # ── 3. 构建节点列表 ───────────────────────────────────────────────
            nodes: list[dict] = []
            links: list[dict] = []
            node_ids: set = set()

            def add_node(node: dict):
                if node['id'] not in node_ids:
                    nodes.append(node)
                    node_ids.add(node['id'])

            # 文档节点
            docs_info = []
            for dr in doc_rows:
                nid = f"doc::{dr['doc_id']}"
                add_node({
                    'id': nid,
                    'type': 'doc',
                    'label': dr['doc_id'],
                    'doc_id': dr['doc_id'],
                    'source_type': dr['source_type'],
                })
                docs_info.append({
                    'doc_id': dr['doc_id'],
                    'source_type': dr['source_type'],
                    'has_kg': False,  # 更新在下面
                })

            # 章节节点 + 文档→章节边
            for cr in chapter_rows:
                if cr['chapter_name'] == '' and cr['chapter_num'] == 0:
                    continue  # slides 的 chapter_num=0，用 doc 作父节点
                nid = f"ch::{cr['doc_id']}::{cr['chapter_num']}"
                add_node({
                    'id': nid,
                    'type': 'chapter',
                    'label': cr['chapter_name'] or f"第{cr['chapter_num']}章",
                    'doc_id': cr['doc_id'],
                    'chapter_num': cr['chapter_num'],
                    'chunk_count': cr['chunk_count'],
                })
                links.append({
                    'source': f"doc::{cr['doc_id']}",
                    'target': nid,
                    'rel': 'structural',
                })

            # 节/页节点 + 章节→节边
            for sr in section_rows:
                sec_nid = f"sec::{sr['doc_id']}::{sr['chapter_num']}::{sr['section_num']}"
                # 决定父节点：有章节就用章节，否则用文档
                if sr['chapter_name'] and sr['chapter_num'] != 0:
                    parent_nid = f"ch::{sr['doc_id']}::{sr['chapter_num']}"
                else:
                    parent_nid = f"doc::{sr['doc_id']}"

                # 为 slides 构建展示名（首行截断）
                label = sr['section_name']
                if 'Slide' in label or 'slide' in label:
                    # 尝试从 chunks 取首行
                    first_chunk = conn.execute(
                        "SELECT text FROM chunks WHERE doc_id=? AND section_num=? ORDER BY rowid LIMIT 1",
                        (sr['doc_id'], sr['section_num']),
                    ).fetchone()
                    if first_chunk and first_chunk['text']:
                        first_line = first_chunk['text'].strip().split('\n')[0].strip()[:40]
                        if first_line:
                            label = f"P{sr['section_num']}: {first_line}"

                add_node({
                    'id': sec_nid,
                    'type': 'section',
                    'label': label,
                    'doc_id': sr['doc_id'],
                    'chapter_num': sr['chapter_num'],
                    'section_num': sr['section_num'],
                    'section_name': sr['section_name'],
                    'chunk_count': sr['chunk_count'],
                })
                links.append({
                    'source': parent_nid,
                    'target': sec_nid,
                    'rel': 'structural',
                })

            # ── 4. 概念节点 + 概念→章节边 ────────────────────────────────────
            if has_kg:
                # 建立 chapter_name → 节点ID 的映射（供概念→章节连边使用）
                # 1. 先从 chunks 章节节点构建（教材）
                ch_name_to_nid: dict[str, str] = {}
                for cr in chapter_rows:
                    if cr['chapter_name']:
                        ch_name_to_nid[cr['chapter_name']] = f"ch::{cr['doc_id']}::{cr['chapter_num']}"

                # 2. 再为幻灯片 KG 章节补充节点（chapters.doc_id != ''）
                for kc in kg_chapters_rows:
                    kc_doc_id = kc['doc_id'] if kc['doc_id'] else ''
                    if not kc_doc_id:
                        continue  # 教材章节已由 chunks 章节节点覆盖
                    kg_ch_nid = f"kgch::{kc['id']}"
                    add_node({
                        'id': kg_ch_nid,
                        'type': 'chapter',
                        'label': kc['name'] or kc['number'],
                        'doc_id': kc_doc_id,
                        'chapter_num': kc['id'],   # 以 chapter_id 作为唯一编号
                        'chunk_count': 0,
                    })
                    links.append({
                        'source': f"doc::{kc_doc_id}",
                        'target': kg_ch_nid,
                        'rel': 'structural',
                    })
                    # 覆盖写入，优先用 KG 章节节点（以免教材同名章节干扰）
                    ch_name_to_nid[kc['name']] = kg_ch_nid

                for con in concepts:
                    cnid = f"concept::{con['id']}"
                    # 优先使用 chapters.doc_id（幻灯片 KG 有值）
                    con_doc_id = con['chapter_doc_id'] or None
                    if not con_doc_id:
                        # 教材回退：通过章节名从 chunks 章节映射推断 doc_id
                        parent = ch_name_to_nid.get(con['chapter_name'])
                        if parent:
                            parts = parent.split('::')
                            con_doc_id = parts[1] if len(parts) >= 2 else None
                        if not con_doc_id and docs_info:
                            con_doc_id = docs_info[0]['doc_id']
                    add_node({
                        'id': cnid,
                        'type': 'concept',
                        'label': con['name'],
                        'description': con['description'] or '',
                        'is_key': bool(con['is_key_point']),
                        'is_difficult': bool(con['is_difficult_point']),
                        'chapter_id': con['chapter_id'],
                        'chapter_name': con['chapter_name'],
                        'doc_id': con_doc_id,
                    })
                    # 连接到对应章节节点（按章名模糊匹配）
                    if parent:
                        links.append({
                            'source': parent,
                            'target': cnid,
                            'rel': 'has_concept',
                        })
                    else:
                        # 找不到章节节点：连到该概念所属文档节点（优先），再兜底第一个文档
                        fallback_doc = con_doc_id or (docs_info[0]['doc_id'] if docs_info else None)
                        if fallback_doc:
                            links.append({
                                'source': f"doc::{fallback_doc}",
                                'target': cnid,
                                'rel': 'has_concept',
                            })

                # 标记哪些文档有 KG
                for d in docs_info:
                    d['has_kg'] = has_kg

                # 概念间语义关系
                concept_nids = {con['id']: f"concept::{con['id']}" for con in concepts}
                for rel in relations:
                    src = concept_nids.get(rel['from_concept_id'])
                    tgt = concept_nids.get(rel['to_concept_id'])
                    if src and tgt:
                        links.append({
                            'source': src,
                            'target': tgt,
                            'rel': rel['relation_type'],
                        })

        return jsonify({
            'nodes': nodes,
            'links': links,
            'docs': docs_info,
            'has_kg': has_kg,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@kg_bp.route('/api/kg/chunks')
def kg_chunks():
    """
    懒加载指定节点的原文 chunk 列表。

    Query params:
      doc_id       — 文档 ID（必须）
      chapter_num  — 章节编号（可选）
      section_num  — 节/页编号（可选）
      concept_name — 概念名，匹配所属章节的 chunks（可选）
      limit        — 最多返回条数（默认 10）
      offset       — 跳过前 N 条（用于分页加载，默认 0）
    """
    if not _rag_db_path().exists():
        return jsonify({'chunks': []})

    doc_id       = request.args.get('doc_id', '')
    chapter_num  = request.args.get('chapter_num', type=int)
    section_num  = request.args.get('section_num', type=int)
    concept_name = request.args.get('concept_name', '')
    limit        = request.args.get('limit', 10, type=int)
    offset       = request.args.get('offset', 0, type=int)

    if not doc_id:
        return jsonify({'error': 'doc_id 必须提供'}), 400

    try:
        with _db_conn() as conn:
            # 若提供 concept_name，先查出它所属章节再过滤
            if concept_name:
                con_row = conn.execute(
                    "SELECT c.id, ch.name as chapter_name FROM concepts c "
                    "JOIN chapters ch ON c.chapter_id = ch.id WHERE c.name = ? LIMIT 1",
                    (concept_name,),
                ).fetchone()
                if con_row:
                    chapter_name_filter = con_row['chapter_name']
                    rows = conn.execute(
                        "SELECT chunk_id, text, context_header, chapter_num, section_num, section_name "
                        "FROM chunks WHERE doc_id=? AND chapter_name=? ORDER BY chapter_num, section_num, rowid LIMIT ? OFFSET ?",
                        (doc_id, chapter_name_filter, limit, offset),
                    ).fetchall()
                else:
                    rows = []
            elif section_num is not None and chapter_num is not None:
                rows = conn.execute(
                    "SELECT chunk_id, text, context_header, chapter_num, section_num, section_name "
                    "FROM chunks WHERE doc_id=? AND chapter_num=? AND section_num=? ORDER BY rowid LIMIT ? OFFSET ?",
                    (doc_id, chapter_num, section_num, limit, offset),
                ).fetchall()
            elif chapter_num is not None:
                rows = conn.execute(
                    "SELECT chunk_id, text, context_header, chapter_num, section_num, section_name "
                    "FROM chunks WHERE doc_id=? AND chapter_num=? ORDER BY section_num, rowid LIMIT ? OFFSET ?",
                    (doc_id, chapter_num, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT chunk_id, text, context_header, chapter_num, section_num, section_name "
                    "FROM chunks WHERE doc_id=? ORDER BY chapter_num, section_num, rowid LIMIT ? OFFSET ?",
                    (doc_id, limit, offset),
                ).fetchall()

            return jsonify({
                'chunks': [
                    {
                        'chunk_id': r['chunk_id'],
                        'text': r['text'],
                        'context_header': r['context_header'],
                        'chapter_num': r['chapter_num'],
                        'section_num': r['section_num'],
                        'section_name': r['section_name'],
                    }
                    for r in rows
                ]
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
