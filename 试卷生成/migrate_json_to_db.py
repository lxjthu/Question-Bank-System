"""将 question_bank.json 数据迁移到 SQLite 数据库"""
import json
import os
from app.factory import create_app
from app.db_models import db, QuestionModel, ExamModel, exam_questions
from datetime import datetime


def migrate():
    app = create_app('development')
    with app.app_context():
        json_path = os.path.join(os.path.dirname(__file__), 'question_bank.json')
        if not os.path.exists(json_path):
            print(f"未找到 {json_path}，跳过迁移")
            return

        # Drop and recreate all tables to start fresh
        db.drop_all()
        db.create_all()

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Deduplicate questions by question_id (keep last occurrence)
        question_map = {}
        for q in data.get('questions', []):
            question_map[q['question_id']] = q

        for q in question_map.values():
            model = QuestionModel(
                question_id=q['question_id'],
                question_type=q['question_type'],
                content=q['content'],
                options=json.dumps(q.get('options', []), ensure_ascii=False),
                answer=q.get('answer'),
                reference_answer=q.get('reference_answer'),
                explanation=q.get('explanation'),
                language=q.get('language', 'zh'),
                metadata_json=json.dumps(q.get('metadata', {}), ensure_ascii=False),
                is_used=q.get('is_used', False),
                used_date=datetime.fromisoformat(q['used_date']) if q.get('used_date') else None,
                created_at=datetime.fromisoformat(q['created_at']) if q.get('created_at') else datetime.now(),
                updated_at=datetime.fromisoformat(q['updated_at']) if q.get('updated_at') else datetime.now(),
            )
            db.session.add(model)

        db.session.flush()

        # Deduplicate exams by exam_id (keep last occurrence)
        exam_map = {}
        for e in data.get('exams', []):
            exam_map[e['exam_id']] = e

        for e in exam_map.values():
            exam = ExamModel(
                exam_id=e['exam_id'],
                name=e['name'],
                config=json.dumps(e.get('config', {}), ensure_ascii=False),
                created_at=datetime.fromisoformat(e['created_at']) if e.get('created_at') else datetime.now(),
                updated_at=datetime.fromisoformat(e['updated_at']) if e.get('updated_at') else datetime.now(),
            )
            db.session.add(exam)
            db.session.flush()

            seen_exam_qids = set()
            pos = 0
            for q_data in e.get('questions', []):
                qid = q_data['question_id']
                # Only add association if question exists and not already linked
                if qid in question_map and qid not in seen_exam_qids:
                    seen_exam_qids.add(qid)
                    db.session.execute(exam_questions.insert().values(
                        exam_id=exam.exam_id,
                        question_id=qid,
                        position=pos,
                    ))
                    pos += 1

        db.session.commit()
        q_count = len(question_map)
        e_count = len(exam_map)
        print(f"迁移完成：{q_count} 道题目（原始 {len(data.get('questions', []))} 条，去重后），{e_count} 份试卷")


if __name__ == '__main__':
    migrate()
