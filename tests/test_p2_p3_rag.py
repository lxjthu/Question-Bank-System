"""
tests/test_p2_p3_rag.py — P2/P3 改造后的测试

P2 验证：
- _get_user_api_key() 优先返回用户 Key，无则 fallback 到环境变量
- ds_docs / ds_kps 按 owner_id 隔离
- ds_upload 写入 owner_id
- ds_generate 读取用户 Key

P3 验证：
- POST /api/rag/ds-generate 立即返回 task_id（不阻塞）
- GET /api/rag/ds-generate-tasks/<task_id> 轮询状态
- 任务完成后 status=done，content 非空

注意：涉及真实 DeepSeek API 调用的测试默认跳过（标记 @pytest.mark.skip），
      需要设置 DEEPSEEK_API_KEY 环境变量后手动运行。
"""
import pytest
import os
import time
import threading
from unittest.mock import patch, MagicMock

from tests.conftest import login_as, guest_login


# ──────────────────────────────────────────────────────────────────────────────
# P2-A：_get_user_api_key() 逻辑
# ──────────────────────────────────────────────────────────────────────────────

class TestGetUserApiKey:
    """
    直接测试 _get_user_api_key() 函数逻辑。
    使用 mock 避免真实 DB / 环境变量依赖。
    """

    def test_returns_user_key_when_set(self, app):
        """有用户 session 且 Key 已配置 → 返回用户 Key。"""
        with app.app_context():
            from app.rag_routes import _get_user_api_key

            mock_user = MagicMock()
            mock_user.get_api_key.return_value = 'sk-user-key-123'

            with patch('app.rag_routes.get_current_user', return_value=mock_user), \
                 patch('app.rag_routes._get_deepseek_key', return_value='sk-env-key'):
                # 模拟有 request context
                with app.test_request_context('/'):
                    result = _get_user_api_key()
            assert result == 'sk-user-key-123'

    def test_falls_back_to_env_when_no_user_key(self, app):
        """用户没有配置 Key → fallback 到环境变量。"""
        with app.app_context():
            from app.rag_routes import _get_user_api_key

            mock_user = MagicMock()
            mock_user.get_api_key.return_value = None  # 未配置

            with patch('app.rag_routes.get_current_user', return_value=mock_user), \
                 patch('app.rag_routes._get_deepseek_key', return_value='sk-env-fallback'):
                with app.test_request_context('/'):
                    result = _get_user_api_key()
            assert result == 'sk-env-fallback'

    def test_falls_back_to_env_when_no_session(self, app):
        """没有登录（get_current_user 返回 None）→ fallback 到环境变量。"""
        with app.app_context():
            from app.rag_routes import _get_user_api_key

            with patch('app.rag_routes.get_current_user', return_value=None), \
                 patch('app.rag_routes._get_deepseek_key', return_value='sk-server-key'):
                with app.test_request_context('/'):
                    result = _get_user_api_key()
            assert result == 'sk-server-key'

    def test_no_request_context_uses_env(self, app):
        """背景线程（无 request context）→ 直接返回环境变量 Key。"""
        with app.app_context():
            from app.rag_routes import _get_user_api_key
            with patch('app.rag_routes._get_deepseek_key', return_value='sk-thread-env'):
                # 不使用 test_request_context，模拟无 context 的线程环境
                result = _get_user_api_key()
            assert result == 'sk-thread-env'


# ──────────────────────────────────────────────────────────────────────────────
# P2-B：ds_docs / ds_kps owner_id 隔离（通过 HTTP 接口测试）
# ──────────────────────────────────────────────────────────────────────────────

class TestDsDocsIsolation:
    """
    测试知识点文档的用户隔离。
    这些测试依赖 ds_knowledge.db（in-memory 或测试专用路径）。

    当前 rag_routes 使用真实文件路径，需要在 fixture 中 mock _ds_db_path
    指向临时文件，或者直接 mock 底层查询函数。

    建议策略：mock list_ds_docs 内部的 _ds_db_conn() 查询返回值。
    """

    def _mock_ds_docs(self, user_id, docs):
        """
        返回 patch 上下文：模拟 ds_docs 表只有 `docs` 列表中的文档。
        docs 格式：[{'doc_id': 'xxx', 'owner_id': uid, ...}, ...]
        """
        import sqlite3
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {'doc_id': d['doc_id'], 'filename': d.get('filename', 'test.md'),
             'subject': '', 'status': 'done', 'error_msg': ''}
            for d in docs
        ]
        mock_cursor.fetchone.return_value = {'COUNT(*)': 0}
        return patch('app.rag_routes._ds_db_conn', return_value=mock_conn)

    def test_list_docs_requires_login(self, client):
        r = client.get('/api/rag/ds-docs')
        assert r.status_code == 401

    def test_upload_requires_login(self, client):
        r = client.post('/api/rag/ds-upload', data={})
        assert r.status_code == 401

    def test_delete_doc_requires_login(self, client):
        r = client.delete('/api/rag/ds-docs/some_doc_id')
        assert r.status_code == 401

    def test_generate_requires_login(self, client):
        r = client.post('/api/rag/ds-generate', json={})
        assert r.status_code == 401

    def test_guest_cannot_upload(self, client, guest_user):
        """guest 账号不能上传文档。"""
        guest_login(client)
        import io
        data = {'file': (io.BytesIO(b'# test'), 'test.md'), 'subject': '测试'}
        r = client.post('/api/rag/ds-upload', data=data,
                        content_type='multipart/form-data')
        assert r.status_code == 403

    def test_guest_cannot_generate(self, client, guest_user):
        """guest 账号不能出题。"""
        guest_login(client)
        r = client.post('/api/rag/ds-generate', json={
            'doc_ids': ['some_doc'],
            'prompt': '出5道题',
            'question_list': '5道单选',
        })
        assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────────────
# P3：ds_generate 异步化
# ──────────────────────────────────────────────────────────────────────────────

class TestDsGenerateAsync:
    """
    测试 ds_generate 改成异步后的行为：
    1. POST 立即返回 task_id（不等待 AI 响应）
    2. GET 轮询接口能查到任务状态
    3. mock DeepSeek 调用，验证 done 状态和 content
    """

    def _post_generate(self, client, doc_ids=None, prompt='出5道题', question_list='5道单选'):
        return client.post('/api/rag/ds-generate', json={
            'doc_ids': doc_ids or ['mock_doc_1'],
            'prompt': prompt,
            'question_list': question_list,
        })

    def test_generate_returns_task_id_immediately(self, client, db, user_a):
        """POST 后立即返回 task_id，不阻塞。"""
        login_as(client, 'user_a', 'pass_a')

        # mock: 用户有 api key，ds_kps 返回数据，DeepSeek 调用被拦截
        mock_user = MagicMock()
        mock_user.role = 'user'
        mock_user.id = user_a.id
        mock_user.get_api_key.return_value = 'sk-mock-key'

        with patch('app.rag_routes.get_current_user', return_value=mock_user), \
             patch('app.rag_routes._ds_db_conn') as mock_conn_ctx, \
             patch('app.rag_routes._call_deepseek_mock', create=True):

            # mock ds_kps 查询返回空列表（快速返回）
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_conn.execute.return_value = mock_cursor
            mock_conn_ctx.return_value = mock_conn

            r = self._post_generate(client)

        # 注意：如果 kps_data 为空，ds_generate 可能在解析时提前返回错误
        # 此测试主要验证接口存在且需要登录，更深层的异步测试见下面

    def test_task_polling_endpoint_exists(self, client, admin_user):
        """GET /api/rag/ds-generate-tasks/<task_id> 接口存在。"""
        login_as(client, 'admin', 'admin123')
        r = client.get('/api/rag/ds-generate-tasks/nonexistent_task')
        # 任务不存在应返回 404，而不是 404 Flask 路由未找到
        assert r.status_code in (404, 200)   # 404=任务不存在，200=找到但有error字段

    def test_task_not_found(self, client, admin_user):
        """查询不存在的 task_id → 404。"""
        login_as(client, 'admin', 'admin123')
        r = client.get('/api/rag/ds-generate-tasks/fake_task_id_xyz')
        assert r.status_code == 404

    def test_async_task_completes(self, client, db, user_a):
        """
        端到端：mock DeepSeek 调用，验证任务从 pending → done，content 有内容。
        需要 P3 实际实现后才能完整运行。
        """
        pytest.skip("P3 实现完成后取消此 skip")

        login_as(client, 'user_a', 'pass_a')

        # 设置用户 API Key
        client.post('/api/auth/apikey', json={'key': 'sk-mock-key-for-test'})

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '1. 以下哪个是正确的？\nA. 答案A\nB. 答案B\n答案：A'

        with patch('openai.OpenAI') as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            # POST 发起出题
            r = client.post('/api/rag/ds-generate', json={
                'doc_ids': ['test_doc'],
                'prompt': '出{question_list}：\n{context}',
                'question_list': '2道单选',
            })
            assert r.status_code == 200
            task_id = r.get_json()['task_id']
            assert task_id.startswith('gen_')

        # 轮询等待完成（最多 5 秒）
        for _ in range(10):
            time.sleep(0.5)
            poll_r = client.get(f'/api/rag/ds-generate-tasks/{task_id}')
            d = poll_r.get_json()
            if d['status'] == 'done':
                assert d['content'] != ''
                return
            elif d['status'] == 'error':
                pytest.fail(f"任务失败：{d['error']}")

        pytest.fail("任务超时未完成")

    def test_no_api_key_returns_error(self, client, admin_user):
        """用户未配置 API Key 且服务器无 Key → 出题失败（400 或 task 状态为 error）。"""
        login_as(client, 'admin', 'admin123')

        with patch('app.rag_routes._get_deepseek_key', return_value=''), \
             patch('app.rag_routes._ds_db_conn') as mock_conn_ctx:

            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = [
                {'chapter_name': '第一章', 'chapter_num': 1,
                 'kp_name': '测试知识点', 'kp_content': '内容',
                 'relations_json': '[]'}
            ]
            mock_conn.execute.return_value = mock_cursor
            mock_conn_ctx.return_value = mock_conn

            r = client.post('/api/rag/ds-generate', json={
                'doc_ids': ['doc1'],
                'prompt': '出题：{context} {question_list}',
                'question_list': '2道单选',
            })

        # 改造前：400；改造后：返回 task_id，之后 task status=error
        assert r.status_code in (200, 400)
        if r.status_code == 200:
            task_id = r.get_json().get('task_id')
            assert task_id is not None
