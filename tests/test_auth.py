"""
tests/test_auth.py — 认证系统测试

覆盖范围：
- 登录 / 登出 / 游客登录
- 邀请码注册
- API Key 加密存储与状态查询
- 权限守卫（login_required / guest_readonly / admin_required）
"""
import pytest
from tests.conftest import login_as, guest_login, make_question
from app.db_models import User, InviteCode
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import secrets


# ──────────────────────────────────────────────────────────────────────────────
# 登录 / 登出
# ──────────────────────────────────────────────────────────────────────────────

class TestLogin:
    def test_login_success(self, client, user_a):
        r = client.post('/api/auth/login', json={'username': 'user_a', 'password': 'pass_a'})
        assert r.status_code == 200
        d = r.get_json()
        assert d['ok'] is True
        assert d['user']['username'] == 'user_a'
        assert d['user']['role'] == 'user'

    def test_login_wrong_password(self, client, user_a):
        r = client.post('/api/auth/login', json={'username': 'user_a', 'password': 'wrong'})
        assert r.status_code == 401

    def test_login_nonexistent_user(self, client):
        r = client.post('/api/auth/login', json={'username': 'nobody', 'password': '123'})
        assert r.status_code == 401

    def test_login_disabled_user(self, client, db, user_a):
        user_a.is_active = False
        db.session.commit()
        r = client.post('/api/auth/login', json={'username': 'user_a', 'password': 'pass_a'})
        assert r.status_code == 401

    def test_logout(self, client, user_a):
        login_as(client, 'user_a', 'pass_a')
        r = client.post('/api/auth/logout')
        assert r.status_code == 200
        # 登出后 /api/auth/me 应返回 401
        r2 = client.get('/api/auth/me')
        assert r2.status_code == 401

    def test_me_without_login(self, client):
        r = client.get('/api/auth/me')
        assert r.status_code == 401

    def test_me_after_login(self, client, user_a):
        login_as(client, 'user_a', 'pass_a')
        r = client.get('/api/auth/me')
        assert r.status_code == 200
        assert r.get_json()['username'] == 'user_a'


class TestGuestLogin:
    def test_guest_login_success(self, client, guest_user):
        r = client.post('/api/auth/guest')
        assert r.status_code == 200
        assert r.get_json()['user']['role'] == 'guest'

    def test_guest_login_no_account(self, client, db):
        """没有 guest 账号时返回 404。"""
        # _seed_system_users() 会创建 guest 账号，先删掉再测
        guest = User.query.filter_by(username='guest', role='guest').first()
        if guest:
            db.session.delete(guest)
            db.session.commit()
        r = client.post('/api/auth/guest')
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# 邀请码注册
# ──────────────────────────────────────────────────────────────────────────────

class TestRegister:
    def _make_code(self, db, admin_user, note='test'):
        code = InviteCode(
            code=secrets.token_urlsafe(16),
            created_by=admin_user.id,
            max_uses=1,
            expires_at=datetime.now() + timedelta(days=7),
            note=note,
        )
        db.session.add(code)
        db.session.commit()
        return code

    def test_register_success(self, client, db, admin_user):
        code = self._make_code(db, admin_user)
        r = client.post('/api/auth/register', json={
            'username': 'new_user',
            'password': 'mypass123',
            'invite_code': code.code,
        })
        assert r.status_code == 201
        d = r.get_json()
        assert d['user']['username'] == 'new_user'
        # 邀请码已被消耗
        db.session.refresh(code)
        assert code.use_count == 1
        assert code.used_by is not None

    def test_register_duplicate_username(self, client, db, admin_user, user_a):
        code = self._make_code(db, admin_user)
        r = client.post('/api/auth/register', json={
            'username': 'user_a',
            'password': 'anypass',
            'invite_code': code.code,
        })
        assert r.status_code == 409

    def test_register_invalid_code(self, client):
        r = client.post('/api/auth/register', json={
            'username': 'someone',
            'password': 'pass1234',
            'invite_code': 'nonexistent-code',
        })
        assert r.status_code == 400

    def test_register_expired_code(self, client, db, admin_user):
        code = InviteCode(
            code='expired-code-xxx',
            created_by=admin_user.id,
            max_uses=1,
            expires_at=datetime.now() - timedelta(days=1),  # 已过期
        )
        db.session.add(code)
        db.session.commit()
        r = client.post('/api/auth/register', json={
            'username': 'latecomer',
            'password': 'pass1234',
            'invite_code': 'expired-code-xxx',
        })
        assert r.status_code == 400

    def test_register_used_code(self, client, db, admin_user):
        """单次使用邀请码用完后不能再注册。"""
        code = self._make_code(db, admin_user)
        # 第一次注册成功
        client.post('/api/auth/register', json={
            'username': 'first_user',
            'password': 'pass1234',
            'invite_code': code.code,
        })
        # 第二次失败
        r = client.post('/api/auth/register', json={
            'username': 'second_user',
            'password': 'pass1234',
            'invite_code': code.code,
        })
        assert r.status_code == 400

    def test_register_short_password(self, client, db, admin_user):
        code = self._make_code(db, admin_user)
        r = client.post('/api/auth/register', json={
            'username': 'short_pw_user',
            'password': '123',
            'invite_code': code.code,
        })
        assert r.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# API Key 存储
# ──────────────────────────────────────────────────────────────────────────────

class TestApiKey:
    def test_apikey_not_set_by_default(self, client, user_a):
        login_as(client, 'user_a', 'pass_a')
        r = client.get('/api/auth/apikey')
        assert r.status_code == 200
        d = r.get_json()
        assert d['configured'] is False
        assert d['preview'] is None

    def test_set_apikey(self, client, db, user_a):
        login_as(client, 'user_a', 'pass_a')
        r = client.post('/api/auth/apikey', json={'key': 'sk-test1234567890abcdef'})
        assert r.status_code == 200
        # 验证数据库中加密存储（不是明文）
        db.session.refresh(user_a)
        assert user_a.api_key_encrypted is not None
        assert 'sk-test' not in user_a.api_key_encrypted  # 确认不是明文

    def test_apikey_encrypted_then_decryptable(self, client, db, user_a):
        login_as(client, 'user_a', 'pass_a')
        plaintext = 'sk-mykey-1234567890abcdefghij'
        client.post('/api/auth/apikey', json={'key': plaintext})
        db.session.refresh(user_a)
        # 用模型方法解密
        assert user_a.get_api_key() == plaintext

    def test_apikey_preview(self, client, user_a):
        login_as(client, 'user_a', 'pass_a')
        client.post('/api/auth/apikey', json={'key': 'sk-abcdefghij1234'})
        r = client.get('/api/auth/apikey')
        d = r.get_json()
        assert d['configured'] is True
        assert d['preview'] is not None
        # preview 格式：前6位...后4位
        assert '…' in d['preview']

    def test_guest_cannot_set_apikey(self, client, guest_user):
        guest_login(client)
        r = client.post('/api/auth/apikey', json={'key': 'sk-xxx'})
        assert r.status_code == 403

    def test_unauthenticated_cannot_get_apikey(self, client):
        r = client.get('/api/auth/apikey')
        assert r.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# 管理员接口
# ──────────────────────────────────────────────────────────────────────────────

class TestAdminInvites:
    def test_admin_create_invites(self, client, admin_user):
        login_as(client, 'admin', 'admin123')
        r = client.post('/api/admin/invites', json={'count': 3, 'expires_days': 7, 'note': '测试批次'})
        assert r.status_code == 201
        codes = r.get_json()
        assert len(codes) == 3
        assert all(c['note'] == '测试批次' for c in codes)

    def test_non_admin_cannot_create_invites(self, client, user_a):
        login_as(client, 'user_a', 'pass_a')
        r = client.post('/api/admin/invites', json={'count': 1})
        assert r.status_code == 403

    def test_admin_list_users(self, client, admin_user, user_a, user_b):
        login_as(client, 'admin', 'admin123')
        r = client.get('/api/admin/users')
        assert r.status_code == 200
        users = r.get_json()
        usernames = [u['username'] for u in users]
        assert 'user_a' in usernames
        assert 'user_b' in usernames

    def test_admin_toggle_user(self, client, db, admin_user, user_a):
        login_as(client, 'admin', 'admin123')
        r = client.post(f'/api/admin/users/{user_a.id}/toggle')
        assert r.status_code == 200
        db.session.refresh(user_a)
        assert user_a.is_active is False
        # 再次 toggle 恢复
        client.post(f'/api/admin/users/{user_a.id}/toggle')
        db.session.refresh(user_a)
        assert user_a.is_active is True

    def test_admin_cannot_toggle_admin(self, client, db, admin_user):
        login_as(client, 'admin', 'admin123')
        r = client.post(f'/api/admin/users/{admin_user.id}/toggle')
        assert r.status_code == 400
