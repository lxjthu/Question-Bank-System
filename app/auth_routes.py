"""
auth_routes.py — 用户认证 Blueprint
- POST /api/auth/login         登录
- POST /api/auth/logout        登出
- POST /api/auth/register      用邀请码注册
- GET  /api/auth/me            当前用户信息
- GET  /api/auth/guest         游客一键登录
- POST /api/auth/apikey        保存/更新 API Key
- GET  /api/auth/apikey        查询 API Key 状态（不返回明文）
- GET  /api/admin/invites       (admin) 查看邀请码列表
- POST /api/admin/invites       (admin) 生成邀请码
- DELETE /api/admin/invites/<id>  (admin) 删除邀请码
- GET  /api/admin/users         (admin) 用户列表
- POST /api/admin/users/<id>/toggle  (admin) 启用/禁用用户
"""
from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import secrets

from app.db_models import db, User, InviteCode

auth_bp = Blueprint('auth', __name__)

GUEST_USERNAME = 'guest'


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数 & 装饰器
# ──────────────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': '请先登录'}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': '请先登录'}), 401
        user = User.query.get(session['user_id'])
        if not user or user.role != 'admin':
            return jsonify({'error': '需要管理员权限'}), 403
        return f(*args, **kwargs)
    return decorated


def get_current_user() -> User | None:
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None


def guest_readonly(f):
    """游客只读限制：如果是 guest，拒绝写操作。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if user and user.role == 'guest':
            return jsonify({'error': '游客账号仅供浏览，请注册正式账号'}), 403
        return f(*args, **kwargs)
    return decorated


def ai_required(f):
    """AI 功能限制：需要 vip 或 admin 角色。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': '请先登录'}), 401
        user = User.query.get(session['user_id'])
        if not user or user.role not in ('admin', 'vip'):
            return jsonify({
                'error': 'AI 功能需要邀请账号，请发邮件至 langxiaojuan@zuel.edu.cn 申请邀请码',
                'code': 'AI_REQUIRED',
            }), 403
        return f(*args, **kwargs)
    return decorated


# ──────────────────────────────────────────────────────────────────────────────
# 认证接口
# ──────────────────────────────────────────────────────────────────────────────

@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username:
        return jsonify({'error': '用户名不能为空'}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.is_active:
        return jsonify({'error': '用户名或密码错误'}), 401
    if not check_password_hash(user.password_hash, password):
        return jsonify({'error': '用户名或密码错误'}), 401

    session['user_id'] = user.id
    session.permanent = True
    user.last_login = datetime.now()
    db.session.commit()
    return jsonify({'ok': True, 'user': user.to_dict()})


@auth_bp.route('/api/auth/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'ok': True})


@auth_bp.route('/api/auth/guest', methods=['POST'])
def guest_login():
    """游客一键登录（无需密码）。"""
    user = User.query.filter_by(username=GUEST_USERNAME, role='guest').first()
    if not user:
        return jsonify({'error': '游客账号未配置，请联系管理员'}), 404
    session['user_id'] = user.id
    session.permanent = True
    return jsonify({'ok': True, 'user': user.to_dict()})


@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    """注册账号。邀请码可选：有则注册为 vip（开通 AI），无则注册为普通 user。"""
    data = request.get_json() or {}
    username    = (data.get('username') or '').strip()
    password    = data.get('password') or ''
    invite_code = (data.get('invite_code') or '').strip()

    if not username or not password:
        return jsonify({'error': '用户名、密码不能为空'}), 400
    if len(username) < 2 or len(username) > 32:
        return jsonify({'error': '用户名长度需在 2~32 个字符'}), 400
    if len(password) < 6:
        return jsonify({'error': '密码至少 6 位'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': '用户名已被占用'}), 409

    role = 'user'
    invited_by = None
    code_obj = None

    if invite_code:
        code_obj = InviteCode.query.filter_by(code=invite_code).first()
        if not code_obj or not code_obj.is_valid():
            return jsonify({'error': '邀请码无效或已过期'}), 400
        role = 'vip'
        invited_by = code_obj.created_by

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        role=role,
        invited_by=invited_by,
    )
    db.session.add(user)
    db.session.flush()

    if code_obj:
        code_obj.use_count += 1
        if code_obj.use_count >= code_obj.max_uses:
            code_obj.used_by = user.id
            code_obj.used_at = datetime.now()

    db.session.commit()
    session['user_id'] = user.id
    session.permanent = True
    return jsonify({'ok': True, 'user': user.to_dict()}), 201


@auth_bp.route('/api/auth/upgrade', methods=['POST'])
@login_required
def upgrade_with_invite():
    """普通用户使用邀请码升级为 vip，开通 AI 功能。"""
    data = request.get_json() or {}
    invite_code = (data.get('invite_code') or '').strip()
    if not invite_code:
        return jsonify({'error': '请输入邀请码'}), 400

    user = get_current_user()
    if user.role in ('admin', 'vip'):
        return jsonify({'error': 'AI 功能已开通，无需重复激活'}), 400

    code_obj = InviteCode.query.filter_by(code=invite_code).first()
    if not code_obj or not code_obj.is_valid():
        return jsonify({'error': '邀请码无效或已过期'}), 400

    user.role = 'vip'
    code_obj.use_count += 1
    if code_obj.use_count >= code_obj.max_uses:
        code_obj.used_by = user.id
        code_obj.used_at = datetime.now()
    db.session.commit()
    return jsonify({'ok': True, 'user': user.to_dict()})


@auth_bp.route('/api/auth/me', methods=['GET'])
@login_required
def me():
    user = get_current_user()
    return jsonify(user.to_dict())


# ──────────────────────────────────────────────────────────────────────────────
# API Key 管理
# ──────────────────────────────────────────────────────────────────────────────

@auth_bp.route('/api/auth/apikey', methods=['GET'])
@login_required
def get_apikey_status():
    user = get_current_user()
    key = user.get_api_key()
    if key:
        preview = key[:6] + '…' + key[-4:]
    else:
        preview = None
    return jsonify({'configured': bool(key), 'preview': preview})


@auth_bp.route('/api/auth/apikey', methods=['POST'])
@login_required
@guest_readonly
@ai_required
def set_apikey():
    data = request.get_json() or {}
    key = (data.get('key') or '').strip()
    if not key:
        return jsonify({'error': 'API Key 不能为空'}), 400
    user = get_current_user()
    user.set_api_key(key)
    db.session.commit()
    return jsonify({'ok': True})


# ──────────────────────────────────────────────────────────────────────────────
# 管理员接口
# ──────────────────────────────────────────────────────────────────────────────

@auth_bp.route('/api/admin/invites', methods=['GET'])
@admin_required
def list_invites():
    codes = InviteCode.query.order_by(InviteCode.created_at.desc()).all()
    return jsonify([c.to_dict() for c in codes])


@auth_bp.route('/api/admin/invites', methods=['POST'])
@admin_required
def create_invite():
    data = request.get_json() or {}
    count    = min(int(data.get('count', 1)), 50)       # 最多一次生成 50 个
    max_uses = int(data.get('max_uses', 1))
    note     = (data.get('note') or '').strip()
    days     = int(data.get('expires_days', 7))
    expires  = datetime.now() + timedelta(days=days)
    admin_id = session['user_id']

    created = []
    for _ in range(count):
        code = InviteCode(
            code=secrets.token_urlsafe(16),
            created_by=admin_id,
            max_uses=max_uses,
            expires_at=expires,
            note=note,
        )
        db.session.add(code)
        created.append(code)
    db.session.commit()
    return jsonify([c.to_dict() for c in created]), 201


@auth_bp.route('/api/admin/invites/<int:invite_id>', methods=['DELETE'])
@admin_required
def delete_invite(invite_id):
    code = InviteCode.query.get_or_404(invite_id)
    db.session.delete(code)
    db.session.commit()
    return jsonify({'ok': True})


@auth_bp.route('/api/admin/users', methods=['GET'])
@admin_required
def list_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([u.to_dict() for u in users])


@auth_bp.route('/api/admin/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        return jsonify({'error': '不能禁用管理员账号'}), 400
    user.is_active = not user.is_active
    db.session.commit()
    return jsonify({'ok': True, 'is_active': user.is_active})


@auth_bp.route('/api/auth/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.get_json() or {}
    old_password = data.get('old_password') or ''
    new_password = data.get('new_password') or ''
    if not old_password or not new_password:
        return jsonify({'error': '请提供当前密码和新密码'}), 400
    if len(new_password) < 6:
        return jsonify({'error': '新密码至少 6 位'}), 400
    user = get_current_user()
    if not check_password_hash(user.password_hash, old_password):
        return jsonify({'error': '当前密码错误'}), 400
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    return jsonify({'ok': True})
