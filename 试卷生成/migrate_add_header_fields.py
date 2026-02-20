"""Migration: add institution_name, semester_info, exam_title, paper_label to course_settings table."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'exam_system.db')

COLUMNS = [
    ("institution_name", "VARCHAR(256) DEFAULT ''"),
    ("semester_info", "VARCHAR(256) DEFAULT ''"),
    ("exam_title", "VARCHAR(256) DEFAULT '期末考试试卷'"),
    ("paper_label", "VARCHAR(16) DEFAULT 'A'"),
]


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get existing columns
    cursor.execute("PRAGMA table_info(course_settings)")
    existing = {row[1] for row in cursor.fetchall()}

    added = []
    for col_name, col_def in COLUMNS:
        if col_name not in existing:
            cursor.execute(f"ALTER TABLE course_settings ADD COLUMN {col_name} {col_def}")
            added.append(col_name)

    conn.commit()
    conn.close()

    if added:
        print(f"Added columns: {', '.join(added)}")
    else:
        print("All columns already exist, nothing to do.")


if __name__ == '__main__':
    migrate()
