"""
Migration: Add 'subject' column to questions table.
Run once: python migrate_add_subject_column.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'exam_system.db')

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Check if column already exists
    cur.execute("PRAGMA table_info(questions)")
    cols = [row[1] for row in cur.fetchall()]

    if 'subject' in cols:
        print("Column 'subject' already exists — nothing to do.")
    else:
        cur.execute("ALTER TABLE questions ADD COLUMN subject VARCHAR(128)")
        conn.commit()
        print("Added 'subject' column to 'questions' table.")

    conn.close()

if __name__ == '__main__':
    migrate()
