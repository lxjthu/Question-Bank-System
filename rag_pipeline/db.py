"""SQLite 数据库操作（知识图谱 + RAG Chunks）"""
import sqlite3
from .config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS chapters (
            id            INTEGER PRIMARY KEY,
            number        TEXT NOT NULL,
            name          TEXT NOT NULL,
            content       TEXT NOT NULL,
            learning_goals TEXT DEFAULT '',
            doc_id        TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS concepts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id          INTEGER NOT NULL,
            name                TEXT NOT NULL,
            description         TEXT DEFAULT '',
            is_key_point        INTEGER DEFAULT 0,
            is_difficult_point  INTEGER DEFAULT 0,
            FOREIGN KEY (chapter_id) REFERENCES chapters(id)
        );

        CREATE TABLE IF NOT EXISTS relations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            from_concept_id  INTEGER NOT NULL,
            to_concept_id    INTEGER NOT NULL,
            relation_type    TEXT NOT NULL,
            FOREIGN KEY (from_concept_id) REFERENCES concepts(id),
            FOREIGN KEY (to_concept_id)   REFERENCES concepts(id)
        );

        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id       TEXT PRIMARY KEY,
            doc_id         TEXT NOT NULL,
            source_type    TEXT NOT NULL,
            level          TEXT NOT NULL,
            chapter_num    INTEGER NOT NULL,
            chapter_name   TEXT NOT NULL,
            section_num    INTEGER NOT NULL,
            section_name   TEXT NOT NULL,
            text           TEXT NOT NULL,
            context_header TEXT NOT NULL,
            prev_id        TEXT,
            next_id        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(source_type);
        """)
        # 向前兼容迁移：为旧版 chapters 表补充 doc_id 列
        try:
            conn.execute("ALTER TABLE chapters ADD COLUMN doc_id TEXT DEFAULT ''")
        except Exception:
            pass  # 列已存在则忽略


def save_chapter(chapter_id, number, name, content, learning_goals, doc_id: str = ''):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO chapters (id, number, name, content, learning_goals, doc_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chapter_id, number, name, content, learning_goals, doc_id),
        )


def save_kg(chapter_id, kg_data):
    """覆盖写入一章的知识图谱（概念 + 关系）。"""
    with get_conn() as conn:
        # 先删旧数据
        old_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM concepts WHERE chapter_id = ?", (chapter_id,)
            ).fetchall()
        ]
        if old_ids:
            ph = ",".join("?" * len(old_ids))
            conn.execute(
                f"DELETE FROM relations WHERE from_concept_id IN ({ph}) "
                f"OR to_concept_id IN ({ph})",
                old_ids + old_ids,
            )
        conn.execute("DELETE FROM concepts WHERE chapter_id = ?", (chapter_id,))

        # 写概念
        concept_map: dict[str, int] = {}
        all_key = set(kg_data.get("key_points", []))
        all_diff = set(kg_data.get("difficulty_points", []))

        for c in kg_data.get("concepts", []):
            name = c["name"]
            cur = conn.execute(
                "INSERT INTO concepts "
                "(chapter_id, name, description, is_key_point, is_difficult_point) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    chapter_id,
                    name,
                    c.get("description", ""),
                    1 if (c.get("is_key") or name in all_key) else 0,
                    1 if (c.get("is_difficult") or name in all_diff) else 0,
                ),
            )
            concept_map[name] = cur.lastrowid

        # key_points / difficulty_points 中若有未出现在 concepts 的条目，补充
        for name in all_key | all_diff:
            if name not in concept_map:
                cur = conn.execute(
                    "INSERT INTO concepts "
                    "(chapter_id, name, description, is_key_point, is_difficult_point) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        chapter_id,
                        name,
                        "",
                        1 if name in all_key else 0,
                        1 if name in all_diff else 0,
                    ),
                )
                concept_map[name] = cur.lastrowid

        # 写关系
        valid_types = {"is_a", "contrasts_with", "depends_on", "leads_to"}
        for rel in kg_data.get("relations", []):
            f_name = rel.get("from", "")
            t_name = rel.get("to", "")
            r_type = rel.get("type", "")
            if f_name in concept_map and t_name in concept_map and r_type in valid_types:
                conn.execute(
                    "INSERT INTO relations (from_concept_id, to_concept_id, relation_type) "
                    "VALUES (?, ?, ?)",
                    (concept_map[f_name], concept_map[t_name], r_type),
                )


def get_chapter_kg(chapter_id):
    """返回一章的知识图谱 dict，含 concepts 列表和 relations 列表。"""
    with get_conn() as conn:
        concepts = conn.execute(
            "SELECT * FROM concepts WHERE chapter_id = ?", (chapter_id,)
        ).fetchall()
        concept_map = {c["id"]: c["name"] for c in concepts}
        ids = [c["id"] for c in concepts]

        relations = []
        if ids:
            ph = ",".join("?" * len(ids))
            relations = conn.execute(
                f"SELECT * FROM relations WHERE from_concept_id IN ({ph})", ids
            ).fetchall()

    return {
        "concepts": [dict(c) for c in concepts],
        "relations": [
            {
                "from": concept_map.get(r["from_concept_id"], ""),
                "to": concept_map.get(r["to_concept_id"], ""),
                "type": r["relation_type"],
            }
            for r in relations
        ],
    }


def get_all_chapters():
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, number, name FROM chapters ORDER BY id"
        ).fetchall()


# ── Chunks 表操作（供 RAG ingest 使用） ─────────────────────────────────────

def save_chunks(chunks) -> None:
    """批量写入 Chunk 对象（已存在则覆盖）。"""
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (c.chunk_id, c.doc_id, c.source_type, c.level,
                 c.chapter_num, c.chapter_name, c.section_num, c.section_name,
                 c.text, c.context_header, c.prev_id, c.next_id)
                for c in chunks
            ],
        )


def load_all_chunks():
    """加载所有 chunks（供重建 BM25 使用）。"""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM chunks ORDER BY doc_id, section_num, chunk_id"
        ).fetchall()


def delete_chunks(doc_id: str) -> None:
    """删除指定文档的所有 chunks。"""
    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))


def delete_kg_by_doc(doc_id: str) -> None:
    """删除指定文档的全部 KG 数据（chapters / concepts / relations）。"""
    if not doc_id:
        return
    with get_conn() as conn:
        chapter_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM chapters WHERE doc_id=?", (doc_id,)
            ).fetchall()
        ]
        if chapter_ids:
            ph = ','.join('?' * len(chapter_ids))
            conn.execute(
                f"DELETE FROM relations WHERE from_concept_id IN "
                f"(SELECT id FROM concepts WHERE chapter_id IN ({ph})) "
                f"OR to_concept_id IN "
                f"(SELECT id FROM concepts WHERE chapter_id IN ({ph}))",
                chapter_ids + chapter_ids,
            )
            conn.execute(f"DELETE FROM concepts WHERE chapter_id IN ({ph})", chapter_ids)
            conn.execute(f"DELETE FROM chapters WHERE id IN ({ph})", chapter_ids)


def get_chapters_by_doc(doc_id: str) -> list:
    """返回指定文档的所有章节（按 id 排序）。"""
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, number, name FROM chapters WHERE doc_id=? ORDER BY id",
            (doc_id,),
        ).fetchall()
