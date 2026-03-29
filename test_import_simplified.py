#!/usr/bin/env python
"""测试简化版面试套题模板导入"""

import os
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['ADMIN_PASSWORD'] = 'test123'

from app.factory import create_app
app = create_app('testing')

with app.app_context():
    from app.db_models import db, User, QuestionModel, QuestionTypeModel
    from app.routes import _match_question_type, _ensure_question_type, _detect_language
    from werkzeug.security import generate_password_hash
    from datetime import datetime
    import openpyxl
    import json
    
    db.create_all()
    
    # 创建测试用户
    user = User(username='testuser6', password_hash=generate_password_hash('test123'), role='user')
    db.session.add(user)
    db.session.commit()
    
    # 模拟导入简化模板
    file_path = r'C:\Users\langx\Desktop\面试套题模板_简化.xlsx'
    
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb['套题列表']
    rows = list(ws.iter_rows(values_only=True))
    
    headers = rows[0]
    
    # 解析槽位
    slots = []
    for i, h in enumerate(headers[1:], 1):
        if h and '-' in str(h):
            parts = str(h).split('-', 1)
            qtype = parts[1].strip() if len(parts) > 1 else '简答'
            slots.append({'col': i, 'type': qtype})
    
    print('Slots:', [s['type'] for s in slots])
    
    # 获取已知题型
    query = QuestionTypeModel.query.filter(
        db.or_(QuestionTypeModel.owner_id.is_(None), QuestionTypeModel.owner_id == user.id)
    )
    known_types = {qt.name for qt in query.all()}
    
    # 处理每套题
    created_questions = 0
    created_types = []
    sets_data = []
    
    for row in rows[1:]:
        set_code = str(row[0]) if row[0] else None
        if not set_code:
            continue
        
        question_ids = []
        for slot in slots:
            content = row[slot['col']] if slot['col'] < len(row) else None
            if not content or not str(content).strip():
                question_ids.append(None)
                continue
            
            raw_type = slot['type']
            qtype, is_builtin, needs_create = _match_question_type(raw_type, known_types)
            
            if needs_create:
                final_type, error = _ensure_question_type(raw_type, user)
                qtype = final_type
                if qtype not in known_types:
                    known_types.add(qtype)
                    created_types.append(qtype)
            
            # 创建题目
            question_id = 'iv_q_' + datetime.now().strftime('%Y%m%d%H%M%S%f') + str(created_questions)
            q = QuestionModel(
                question_id=question_id,
                question_type=qtype,
                content=str(content).strip(),
                options=json.dumps([], ensure_ascii=False),
                answer='',
                reference_answer='',
                explanation='',
                subject='面试题库',
                difficulty='medium',
                language=_detect_language(str(content), None),
                owner_id=user.id,
                visibility='private',
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.session.add(q)
            question_ids.append(question_id)
            created_questions += 1
        
        sets_data.append({'set_code': set_code, 'question_ids': question_ids})
    
    db.session.commit()
    
    print('Import result:')
    print('  Questions created:', created_questions)
    print('  Types created:', list(set(created_types)))
    print('  Sets:', len(sets_data))
    for s in sets_data[:3]:
        valid_q = [q for q in s['question_ids'] if q]
        print('   ', s['set_code'], '-', len(valid_q), 'questions')
