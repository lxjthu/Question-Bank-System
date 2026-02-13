# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

林业经济学（双语）试题管理系统 — A Flask-based bilingual (Chinese/English) exam question management system for Forestry Economics. Supports question bank CRUD, automatic exam generation, Word document import/export, dynamic question type management, batch operations, and bilingual preview modes.

## Commands

### Run the server
```bash
python server.py
# Starts on http://localhost:5000 (debug mode)
# Port configurable via PORT env var
```

### Install dependencies
```bash
pip install flask flask-sqlalchemy python-docx pytest
```

### Run tests
```bash
python -m pytest tests/ -v
# 89 tests, all using in-memory SQLite for isolation
```

## Architecture

**Pattern:** MVC with Flask app factory + Blueprint, SQLAlchemy ORM (SQLite), single-page frontend.

```
server.py              → Entry point, calls create_app('development')
app/factory.py         → Flask app factory, initializes DB, seeds built-in question types
app/db_models.py       → SQLAlchemy ORM models (QuestionModel, ExamModel, QuestionTypeModel, exam_questions)
app/routes.py          → All API routes (Blueprint 'main'), business logic
app/utils.py           → Word template generation (dynamic from DB), exam-to-docx export, file parsing
app/models.py          → Legacy data classes (Question/Exam, kept for reference)
app/templates/index.html → Entire frontend SPA (4-tab: 题库管理, 试卷生成, 模板下载, 题型管理)
config.py              → Config classes (Development/Production/Testing)
exam_system.db         → SQLite database file (auto-created on first run)
```

### Key Design Decisions

- **SQLAlchemy ORM**: All data persisted via SQLAlchemy models to SQLite. No JSON file storage.
- **QuestionTypeModel**: Dynamic question types stored in DB. 7 built-in types seeded on first run; custom types can be added/edited/deleted via API.
- **Seed data**: `factory.py` seeds built-in question types (单选, 多选, 是非, 简答, 简答>计算, 简答>论述, 简答>材料分析) when the `question_types` table is empty.
- **Monolithic frontend**: `index.html` contains all HTML, CSS, and JavaScript for the SPA. Four tabs: question bank, exam generation, template download, type management.
- **Bilingual support**: Questions have a `language` field (`zh`, `en`, or `both`). Preview modes include Chinese-only, English-only, and bilingual side-by-side.
- **Usage tracking**: Questions track `is_used` and `used_date` to prevent reuse across exam years. Finalization marks questions as used; undo reverts this.
- **Dynamic templates**: Word import template generated from DB question types, so custom types automatically appear.

### API Routes (all in `app/routes.py`)

- `GET/POST /api/questions` — List/search and add questions
- `GET/PUT/DELETE /api/questions/<id>` — Single question CRUD
- `POST /api/questions/batch-delete` — Batch delete with exam association cleanup
- `POST /api/questions/import` — Import from Word/TXT document
- `GET /api/questions/export` — Export question bank (JSON/CSV)
- `GET/POST /api/exams` — List and create exams
- `GET/PUT/DELETE /api/exams/<id>` — Single exam CRUD
- `POST /api/exams/generate` — Auto-generate exam
- `POST /api/exams/<id>/add_question` — Add question to exam
- `DELETE /api/exams/<id>/remove_question/<qid>` — Remove question from exam
- `POST /api/exams/<id>/replace_question` — Replace question in exam
- `POST /api/exams/<id>/confirm` — Confirm exam (mark questions used)
- `POST /api/exams/<id>/revert_confirmation` — Revert confirmation
- `GET /api/exams/<id>/export` — Export exam to Word
- `GET /api/templates/download` — Download import template
- `GET/POST /api/question-types` — List and create question types
- `PUT/DELETE /api/question-types/<id>` — Update and delete question types

### Data Flow

1. Frontend makes fetch requests to `/api/*` endpoints
2. Routes in `routes.py` use SQLAlchemy ORM to query/modify data
3. Data persisted to `exam_system.db` (SQLite)
4. Word import parses `.docx`/`.txt` files using generic type detection (not hardcoded types)
5. Word export uses `utils.export_exam_to_word()` to generate `.docx` via `python-docx`
6. Question types loaded from DB → cached in frontend `questionTypesCache` → used for all dropdowns and type checks

### Test Structure

```
tests/
├── conftest.py             # Shared fixtures (app, client, db, helpers)
├── test_models.py          # ORM model unit tests (13)
├── test_question_api.py    # Question API tests (22)
├── test_exam_api.py        # Exam API tests (20)
├── test_business_logic.py  # Business logic tests (10)
├── test_edge_cases.py      # Edge case tests (9)
├── test_question_types.py  # Question type CRUD tests (10)
└── test_batch_delete.py    # Batch delete tests (5)
```

## Important Context

- The parent directory `D:\code\试卷\` contains an older version of the project (single-file `web_server.py`, `exam_system.html`). This subdirectory `试卷生成` is the refactored, current version.
- Question types are dynamic (stored in `question_types` table). Built-in types: 单选, 多选, 是非, 简答, 简答>计算, 简答>论述, 简答>材料分析.
- `isChoiceType(name)` in frontend checks `has_options` from the question type cache, not hardcoded names.
- Word import template uses a specific format: `[题型]` headers, `[A]`/`[B]` option markers, `<解析>...</解析>` for explanations, `<参考答案>...</参考答案>` for reference answers, `（中文）`/`（英文）` for language markers.
