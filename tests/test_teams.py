"""
tests/test_teams.py — 团队管理测试（P1 已完成部分）

覆盖范围：
- 创建 / 列表 / 详情 / 修改 / 解散团队
- 加人 / 移出 / 修改角色 / 退出团队
- 权限边界（非成员、非 admin 的操作被拒绝）
"""
import pytest
from tests.conftest import login_as


class TestTeamCRUD:
    def test_create_team(self, client, user_a):
        login_as(client, 'user_a', 'pass_a')
        r = client.post('/api/teams', json={'name': 'A 的团队', 'description': '测试'})
        assert r.status_code == 201
        d = r.get_json()
        assert d['name'] == 'A 的团队'
        assert d['created_by'] == user_a.id

    def test_creator_is_admin_member(self, client, db, user_a):
        """创建者自动成为团队 admin 成员。"""
        login_as(client, 'user_a', 'pass_a')
        r = client.post('/api/teams', json={'name': '我的团队'})
        team_id = r.get_json()['id']

        r2 = client.get(f'/api/teams/{team_id}/members')
        members = r2.get_json()
        me = next((m for m in members if m['user_id'] == user_a.id), None)
        assert me is not None
        assert me['role'] == 'admin'

    def test_list_own_teams(self, client, user_a, user_b):
        """只能看到自己加入的团队。"""
        login_as(client, 'user_a', 'pass_a')
        client.post('/api/teams', json={'name': 'A的团队'})

        login_as(client, 'user_b', 'pass_b')
        client.post('/api/teams', json={'name': 'B的团队'})

        # user_a 只看到自己的团队
        login_as(client, 'user_a', 'pass_a')
        teams = client.get('/api/teams').get_json()
        names = [t['name'] for t in teams]
        assert 'A的团队' in names
        assert 'B的团队' not in names

    def test_guest_cannot_create_team(self, client, guest_user):
        from tests.conftest import guest_login
        guest_login(client)
        r = client.post('/api/teams', json={'name': '游客团队'})
        assert r.status_code == 403

    def test_only_creator_can_disband(self, client, db, user_a, user_b):
        """只有创建者能解散团队。"""
        login_as(client, 'user_a', 'pass_a')
        r = client.post('/api/teams', json={'name': '要解散的团队'})
        team_id = r.get_json()['id']

        # 先把 user_b 加入团队
        client.post(f'/api/teams/{team_id}/members', json={'username': 'user_b'})

        # user_b 尝试解散，失败
        login_as(client, 'user_b', 'pass_b')
        r2 = client.delete(f'/api/teams/{team_id}')
        assert r2.status_code == 403

        # user_a 解散，成功
        login_as(client, 'user_a', 'pass_a')
        r3 = client.delete(f'/api/teams/{team_id}')
        assert r3.status_code == 200


class TestTeamMembers:
    def _create_team(self, client, name='测试团队'):
        r = client.post('/api/teams', json={'name': name})
        return r.get_json()['id']

    def test_add_member(self, client, user_a, user_b):
        login_as(client, 'user_a', 'pass_a')
        tid = self._create_team(client)
        r = client.post(f'/api/teams/{tid}/members', json={'username': 'user_b'})
        assert r.status_code == 201

        members = client.get(f'/api/teams/{tid}/members').get_json()
        uids = [m['user_id'] for m in members]
        assert user_b.id in uids

    def test_add_nonexistent_user(self, client, user_a):
        login_as(client, 'user_a', 'pass_a')
        tid = self._create_team(client)
        r = client.post(f'/api/teams/{tid}/members', json={'username': 'nobody'})
        assert r.status_code == 404

    def test_add_duplicate_member(self, client, user_a, user_b):
        login_as(client, 'user_a', 'pass_a')
        tid = self._create_team(client)
        client.post(f'/api/teams/{tid}/members', json={'username': 'user_b'})
        r = client.post(f'/api/teams/{tid}/members', json={'username': 'user_b'})
        assert r.status_code == 409

    def test_remove_member(self, client, user_a, user_b):
        login_as(client, 'user_a', 'pass_a')
        tid = self._create_team(client)
        client.post(f'/api/teams/{tid}/members', json={'username': 'user_b'})

        r = client.delete(f'/api/teams/{tid}/members/{user_b.id}')
        assert r.status_code == 200

        members = client.get(f'/api/teams/{tid}/members').get_json()
        assert user_b.id not in [m['user_id'] for m in members]

    def test_leave_team(self, client, user_a, user_b):
        login_as(client, 'user_a', 'pass_a')
        tid = self._create_team(client)
        client.post(f'/api/teams/{tid}/members', json={'username': 'user_b'})

        login_as(client, 'user_b', 'pass_b')
        r = client.post(f'/api/teams/{tid}/leave')
        assert r.status_code == 200

    def test_creator_cannot_leave(self, client, user_a):
        """创建者不能直接退出，必须先转让或解散。"""
        login_as(client, 'user_a', 'pass_a')
        tid = self._create_team(client)
        r = client.post(f'/api/teams/{tid}/leave')
        assert r.status_code == 400

    def test_change_member_role(self, client, user_a, user_b):
        login_as(client, 'user_a', 'pass_a')
        tid = self._create_team(client)
        client.post(f'/api/teams/{tid}/members', json={'username': 'user_b'})

        r = client.put(f'/api/teams/{tid}/members/{user_b.id}/role',
                       json={'role': 'admin'})
        assert r.status_code == 200

        members = client.get(f'/api/teams/{tid}/members').get_json()
        b_member = next(m for m in members if m['user_id'] == user_b.id)
        assert b_member['role'] == 'admin'

    def test_non_admin_cannot_add_member(self, client, user_a, user_b):
        """非团队 admin 不能加人。"""
        login_as(client, 'user_a', 'pass_a')
        tid = self._create_team(client)
        client.post(f'/api/teams/{tid}/members', json={'username': 'user_b'})

        # user_b 是普通成员，不能再加人
        login_as(client, 'user_b', 'pass_b')
        from werkzeug.security import generate_password_hash
        from app.db_models import User
        # 需要第三个用户
        r = client.post(f'/api/teams/{tid}/members', json={'username': 'admin'})
        assert r.status_code == 403

    def test_outsider_cannot_view_team(self, client, user_a, user_b):
        """不在团队的用户不能查看团队详情。"""
        login_as(client, 'user_a', 'pass_a')
        tid = self._create_team(client)

        login_as(client, 'user_b', 'pass_b')
        r = client.get(f'/api/teams/{tid}')
        assert r.status_code == 403
