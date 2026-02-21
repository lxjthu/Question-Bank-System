"""Tests for bilingual fields, metadata, and display modes."""
import json
import os
from tests.conftest import create_question_in_db, create_exam_in_db
from app.db_models import QuestionModel


class TestBilingualFields:
    """Test new bilingual columns on QuestionModel."""

    def test_question_bilingual_fields(self, db):
        """New fields are stored and serialized correctly."""
        q = create_question_in_db(
            db,
            question_id='bi_001',
            content='什么是林业经济学？',
            content_en='What is forestry economics?',
            options_en=['Option A', 'Option B', 'Option C', 'Option D'],
            knowledge_point='林业经济基础',
            tags='基础,概念',
            difficulty='easy',
        )
        d = q.to_dict()
        assert d['content_en'] == 'What is forestry economics?'
        assert d['options_en'] == ['Option A', 'Option B', 'Option C', 'Option D']
        assert d['knowledge_point'] == '林业经济基础'
        assert d['tags'] == '基础,概念'
        assert d['difficulty'] == 'easy'

    def test_question_bilingual_fields_nullable(self, db):
        """New fields default to None / empty list."""
        q = create_question_in_db(db, question_id='bi_002')
        d = q.to_dict()
        assert d['content_en'] is None
        assert d['options_en'] == []
        assert d['knowledge_point'] is None
        assert d['tags'] is None
        assert d['difficulty'] is None


class TestBilingualAPI:
    """Test API endpoints with bilingual data."""

    def test_add_question_with_bilingual(self, client):
        """POST with bilingual fields auto-detects language='both'."""
        resp = client.post('/api/questions', json={
            'question_id': 'bi_add_001',
            'question_type': '单选',
            'content': '中文题目',
            'options': ['A', 'B', 'C', 'D'],
            'answer': 'A',
            'content_en': 'English question',
            'options_en': ['Opt A', 'Opt B', 'Opt C', 'Opt D'],
            'knowledge_point': '测试知识点',
            'tags': 'tag1,tag2',
            'difficulty': 'medium',
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['language'] == 'both'
        assert data['content_en'] == 'English question'
        assert data['options_en'] == ['Opt A', 'Opt B', 'Opt C', 'Opt D']
        assert data['knowledge_point'] == '测试知识点'
        assert data['difficulty'] == 'medium'

    def test_update_question_bilingual(self, client, db):
        """PUT updates bilingual fields and auto-upgrades language."""
        create_question_in_db(db, question_id='bi_upd_001', language='zh')
        resp = client.put('/api/questions/bi_upd_001', json={
            'content_en': 'New English content',
            'difficulty': 'hard',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['content_en'] == 'New English content'
        assert data['difficulty'] == 'hard'
        assert data['language'] == 'both'

    def test_search_by_difficulty(self, client, db):
        """GET /api/questions?difficulty= filters correctly."""
        create_question_in_db(db, question_id='bi_d_easy', difficulty='easy')
        create_question_in_db(db, question_id='bi_d_hard', difficulty='hard')
        resp = client.get('/api/questions?difficulty=easy')
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['question_id'] == 'bi_d_easy'


class TestBilingualParsing:
    """Test template/converter parsing of bilingual data."""

    def test_parse_template_bilingual(self):
        """parse_question_template extracts [X_en] and metadata from explanation."""
        from app.utils import parse_question_template
        content = """[单选][A]
中文题目？
[A]选项A
[B]选项B
[C]选项C
[D]选项D
[A_en]Option A
[B_en]Option B
[C_en]Option C
[D_en]Option D
<解析>
这是解析内容
知识点:林业经济
标签:基础,概念
英文题目:English question?
难度:medium
</解析>"""
        questions = parse_question_template(content)
        assert len(questions) == 1
        q = questions[0]
        assert q['options_en'] == ['Option A', 'Option B', 'Option C', 'Option D']
        assert q['content_en'] == 'English question?'
        assert q['knowledge_point'] == '林业经济'
        assert q['tags'] == '基础,概念'
        assert q['difficulty'] == 'medium'
        assert '知识点' not in q['explanation']


class TestBilingualExport:
    """Test Word export with different language modes."""

    def test_export_exam_bilingual_modes(self, db):
        """Export in zh/en/both modes doesn't raise errors."""
        from app.utils import export_exam_to_word
        q = create_question_in_db(
            db,
            question_id='exp_bi_001',
            content='中文题目',
            content_en='English Q',
            options_en=['A en', 'B en', 'C en', 'D en'],
        )
        exam = create_exam_in_db(db, exam_id='exp_exam_bi',
                                  name='双语试卷',
                                  config={'单选': {'count': 1, 'points': 5}},
                                  question_ids=['exp_bi_001'])

        os.makedirs('temp', exist_ok=True)
        for mode in ('zh', 'en', 'both'):
            path = f'temp/test_export_{mode}.docx'
            export_exam_to_word(exam, path, mode=mode)
            assert os.path.exists(path)
            os.remove(path)


class TestBilingualImport:
    """Test that import preserves bilingual fields."""

    def test_import_preserves_bilingual(self, client, db):
        """Import via .txt preserves bilingual fields."""
        import tempfile
        content = (
            "[单选][B]\n"
            "什么是可持续发展？\n"
            "[A]选项1\n"
            "[B]选项2\n"
            "[C]选项3\n"
            "[D]选项4\n"
            "[A_en]Option 1\n"
            "[B_en]Option 2\n"
            "[C_en]Option 3\n"
            "[D_en]Option 4\n"
            "<解析>\n"
            "可持续发展解析\n"
            "英文题目:What is sustainable development?\n"
            "知识点:可持续发展\n"
            "难度:easy\n"
            "</解析>\n"
        )
        os.makedirs('temp', exist_ok=True)
        tmp_path = os.path.join('temp', 'test_import_bi.txt')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(content)

        with open(tmp_path, 'rb') as f:
            resp = client.post('/api/questions/import',
                             data={'file': (f, 'test_import_bi.txt')},
                             content_type='multipart/form-data')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 1

        # Check persisted data
        questions = client.get('/api/questions').get_json()
        imported = [q for q in questions if '什么是可持续发展' in q['content']]
        assert len(imported) == 1
        q = imported[0]
        assert q['content_en'] == 'What is sustainable development?'
        assert q['knowledge_point'] == '可持续发展'
        assert q['difficulty'] == 'easy'
        assert q['language'] == 'both'

        if os.path.exists(tmp_path):
            os.remove(tmp_path)
