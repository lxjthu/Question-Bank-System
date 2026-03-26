"""
team_routes.py — 团队 Blueprint
- GET  /api/teams               我的团队列表
- POST /api/teams               创建团队
- GET  /api/teams/<id>          团队详情（含成员）
- PUT  /api/teams/<id>          修改团队信息（仅创建者/团队admin）
- DELETE /api/teams/<id>        解散团队（仅创建者）
- GET  /api/teams/<id>/members  成员列表
- POST /api/teams/<id>/members  邀请成员（用用户名）
- DELETE /api/teams/<id>/members/<uid>  移出成员
- PUT  /api/teams/<id>/members/<uid>/role  修改成员角色
- POST /api/teams/<id>/leave    主动退出团队
"""
from flask import Blueprint, request, jsonify, session

from app.db_models import db, Team, TeamMember, User
from app.auth_routes import login_required, guest_readonly, get_current_user

team_bp = Blueprint('team', __name__)


def _is_team_admin(team: Team, user: User) -> bool:
    """判断 user 是否是该团队的 admin 或创建者。"""
    if team.created_by == user.id or user.role == 'admin':
        return True
    m = TeamMember.query.filter_by(team_id=team.id, user_id=user.id).first()
    return m is not None and m.role == 'admin'


def _my_team_ids(user_id: int) -> list[int]:
    """返回用户所在的所有团队 id 列表。"""
    rows = TeamMember.query.filter_by(user_id=user_id).all()
    return [r.team_id for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# 团队 CRUD
# ──────────────────────────────────────────────────────────────────────────────

@team_bp.route('/api/teams', methods=['GET'])
@login_required
def list_teams():
    user = get_current_user()
    team_ids = _my_team_ids(user.id)
    teams = Team.query.filter(Team.id.in_(team_ids)).order_by(Team.created_at.desc()).all()
    result = []
    for t in teams:
        d = t.to_dict()
        m = TeamMember.query.filter_by(team_id=t.id, user_id=user.id).first()
        d['my_role'] = m.role if m else ('admin' if t.created_by == user.id else 'member')
        d['member_count'] = TeamMember.query.filter_by(team_id=t.id).count()
        result.append(d)
    return jsonify(result)


@team_bp.route('/api/teams', methods=['POST'])
@login_required
@guest_readonly
def create_team():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': '团队名称不能为空'}), 400
    user = get_current_user()
    team = Team(name=name, description=data.get('description', ''), created_by=user.id)
    db.session.add(team)
    db.session.flush()
    # 创建者自动成为 admin 成员
    db.session.add(TeamMember(team_id=team.id, user_id=user.id, role='admin'))
    db.session.commit()
    return jsonify(team.to_dict()), 201


@team_bp.route('/api/teams/<int:team_id>', methods=['GET'])
@login_required
def get_team(team_id):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)
    if not TeamMember.query.filter_by(team_id=team_id, user_id=user.id).first() and user.role != 'admin':
        return jsonify({'error': '无权查看此团队'}), 403
    return jsonify(team.to_dict(include_members=True))


@team_bp.route('/api/teams/<int:team_id>', methods=['PUT'])
@login_required
@guest_readonly
def update_team(team_id):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)
    if not _is_team_admin(team, user):
        return jsonify({'error': '需要团队管理员权限'}), 403
    data = request.get_json() or {}
    if 'name' in data:
        team.name = (data['name'] or '').strip() or team.name
    if 'description' in data:
        team.description = data['description']
    db.session.commit()
    return jsonify(team.to_dict())


@team_bp.route('/api/teams/<int:team_id>', methods=['DELETE'])
@login_required
@guest_readonly
def delete_team(team_id):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)
    if team.created_by != user.id and user.role != 'admin':
        return jsonify({'error': '只有创建者可以解散团队'}), 403
    TeamMember.query.filter_by(team_id=team_id).delete()
    db.session.delete(team)
    db.session.commit()
    return jsonify({'ok': True})


# ──────────────────────────────────────────────────────────────────────────────
# 成员管理
# ──────────────────────────────────────────────────────────────────────────────

@team_bp.route('/api/teams/<int:team_id>/members', methods=['GET'])
@login_required
def list_members(team_id):
    user = get_current_user()
    if not TeamMember.query.filter_by(team_id=team_id, user_id=user.id).first() and user.role != 'admin':
        return jsonify({'error': '无权查看此团队'}), 403
    members = TeamMember.query.filter_by(team_id=team_id).all()
    result = []
    for m in members:
        u = User.query.get(m.user_id)
        result.append({
            'user_id': m.user_id,
            'username': u.username if u else '未知',
            'role': m.role,
            'joined_at': m.joined_at.isoformat() if m.joined_at else None,
        })
    return jsonify(result)


@team_bp.route('/api/teams/<int:team_id>/members', methods=['POST'])
@login_required
@guest_readonly
def add_member(team_id):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)
    if not _is_team_admin(team, user):
        return jsonify({'error': '需要团队管理员权限'}), 403
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    if not username:
        return jsonify({'error': '用户名不能为空'}), 400
    target = User.query.filter_by(username=username).first()
    if not target:
        return jsonify({'error': f'用户 "{username}" 不存在'}), 404
    if TeamMember.query.filter_by(team_id=team_id, user_id=target.id).first():
        return jsonify({'error': '该用户已在团队中'}), 409
    db.session.add(TeamMember(team_id=team_id, user_id=target.id, role='member'))
    db.session.commit()
    return jsonify({'ok': True}), 201


@team_bp.route('/api/teams/<int:team_id>/members/<int:uid>', methods=['DELETE'])
@login_required
@guest_readonly
def remove_member(team_id, uid):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)
    if uid == user.id:
        return jsonify({'error': '请使用「退出团队」接口'}), 400
    if not _is_team_admin(team, user):
        return jsonify({'error': '需要团队管理员权限'}), 403
    m = TeamMember.query.filter_by(team_id=team_id, user_id=uid).first_or_404()
    db.session.delete(m)
    db.session.commit()
    return jsonify({'ok': True})


@team_bp.route('/api/teams/<int:team_id>/members/<int:uid>/role', methods=['PUT'])
@login_required
@guest_readonly
def change_role(team_id, uid):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)
    if not _is_team_admin(team, user):
        return jsonify({'error': '需要团队管理员权限'}), 403
    data = request.get_json() or {}
    new_role = data.get('role')
    if new_role not in ('admin', 'member'):
        return jsonify({'error': 'role 只能是 admin 或 member'}), 400
    m = TeamMember.query.filter_by(team_id=team_id, user_id=uid).first_or_404()
    m.role = new_role
    db.session.commit()
    return jsonify({'ok': True})


@team_bp.route('/api/teams/<int:team_id>/leave', methods=['POST'])
@login_required
def leave_team(team_id):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)
    if team.created_by == user.id:
        return jsonify({'error': '创建者不能退出，请先转让或解散团队'}), 400
    m = TeamMember.query.filter_by(team_id=team_id, user_id=user.id).first_or_404()
    db.session.delete(m)
    db.session.commit()
    return jsonify({'ok': True})
