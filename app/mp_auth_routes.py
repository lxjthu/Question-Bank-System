"""
app/mp_auth_routes.py
微信小程序认证 Blueprint
前缀 /api/mp/

接口列表：
  POST /api/mp/login          小程序 wx.login code → JWT（或临时 openid_token）
  POST /api/mp/bind           教师绑定已有 web 账号
  POST /api/mp/register       教师在小程序注册新账号
  POST /api/mp/student-login  学生自动注册并登录
  GET  /api/mp/me             获取当前用户信息（需 JWT）
"""
import os
import secrets
import datetime

import jwt
import requests
from flask import Blueprint, request, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text

from app.db_models import db, User

mp_bp = Blueprint('mp_auth', __name__)

MP_APPID = os.environ.get('WX_MP_APPID', '')
MP_SECRET = os.environ.get('WX_MP_SECRET', '')
JWT_EXPIRE_DAYS = int(os.environ.get('JWT_EXPIRE_DAYS', '30'))
# 临时 openid_token 有效期（分钟），仅用于绑定/注册流程
OPENID_TOKEN_MINUTES = 30


# ── JWT 工具 ──────────────────────────────────────────────────────────────────

def _secret():
    return current_app.config.get('SECRET_KEY', 'dev-secret')


def _issue_jwt(user_id: int, wx_user_id: int, role: str) -> str:
    payload = {
        'user_id': user_id,
        'wx_user_id': wx_user_id,
        'role': role,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, _secret(), algorithm='HS256')


def _issue_openid_token(openid: str) -> str:
    """签发仅含 openid 的临时 token，用于绑定/注册流程。"""
    payload = {
        'openid': openid,
        'type': 'openid_only',
        'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=OPENID_TOKEN_MINUTES),
    }
    return jwt.encode(payload, _secret(), algorithm='HS256')


def _decode_openid_token(token: str) -> str | None:
    """从临时 token 中提取 openid；失败返回 None。"""
    try:
        payload = jwt.decode(token, _secret(), algorithms=['HS256'])
        if payload.get('type') != 'openid_only':
            return None
        return payload.get('openid')
    except Exception:
        return None


def mp_jwt_required(f):
    """装饰器：从 Authorization: Bearer <token> 验证 JWT，注入 g.mp_user。"""
    from functools import wraps
    from flask import g

    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'error': '未登录'}), 401
        token = auth[7:]
        try:
            payload = jwt.decode(token, _secret(), algorithms=['HS256'])
            if payload.get('type') == 'openid_only':
                return jsonify({'error': '请完成账号绑定'}), 401
            g.mp_user_id = payload['user_id']
            g.mp_wx_user_id = payload['wx_user_id']
            g.mp_role = payload['role']
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'token 已过期，请重新登录'}), 401
        except Exception:
            return jsonify({'error': 'token 无效'}), 401
        return f(*args, **kwargs)
    return decorated


def mp_teacher_required(f):
    """装饰器：仅允许 role=user/admin/vip 的教师访问。"""
    from functools import wraps
    from flask import g

    @wraps(f)
    @mp_jwt_required
    def decorated(*args, **kwargs):
        if g.mp_role not in ('user', 'admin', 'vip'):
            return jsonify({'error': '需要教师权限'}), 403
        return f(*args, **kwargs)
    return decorated


# ── 接口实现 ──────────────────────────────────────────────────────────────────

@mp_bp.route('/api/mp/login', methods=['POST'])
def mp_login():
    """
    小程序登录入口。
    Body: { code, nickName?, avatarUrl? }
    Response:
      已有账号: { token, user, is_new_user: false }
      新用户:   { token: null, openid_token, is_new_user: true }
    """
    data = request.get_json(force=True) or {}
    code = (data.get('code') or '').strip()
    nick_name = data.get('nickName', '')
    avatar_url = data.get('avatarUrl', '')

    if not code:
        return jsonify({'error': '缺少 code 参数'}), 400

    openid, errmsg = _code2session(code)
    if not openid:
        current_app.logger.warning(f'[mp_login] code2session 失败: {errmsg}')
        return jsonify({'error': f'微信登录失败: {errmsg}'}), 401

    now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    row = db.session.execute(
        text('SELECT id, user_id FROM wx_users WHERE openid = :openid'),
        {'openid': openid}
    ).fetchone()

    if row:
        # 已绑定：更新 last_login，签发完整 JWT
        db.session.execute(
            text('UPDATE wx_users SET last_login=:now, nickname=:nick, avatar_url=:avatar WHERE openid=:openid'),
            {'now': now, 'nick': nick_name, 'avatar': avatar_url, 'openid': openid}
        )
        db.session.commit()
        user = User.query.get(row.user_id)
        token = _issue_jwt(user.id, row.id, user.role)
        return jsonify({'token': token, 'user': user.to_dict(), 'is_new_user': False})

    # 新微信用户：签发临时 openid_token，前端跳转角色选择页
    openid_token = _issue_openid_token(openid)
    return jsonify({'token': None, 'openid_token': openid_token, 'is_new_user': True})


@mp_bp.route('/api/mp/bind', methods=['POST'])
def mp_bind():
    """
    教师绑定已有 web 账号。
    Body: { openid_token, username, password }
    Response: { token, user }
    """
    data = request.get_json(force=True) or {}
    openid_token = (data.get('openid_token') or '').strip()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    openid = _decode_openid_token(openid_token)
    if not openid:
        return jsonify({'error': 'openid_token 无效或已过期，请重新扫码'}), 401

    if not username or not password:
        return jsonify({'error': '请输入用户名和密码'}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.is_active:
        return jsonify({'error': '用户名或密码错误'}), 401
    if not check_password_hash(user.password_hash, password):
        return jsonify({'error': '用户名或密码错误'}), 401
    if user.role == 'student':
        return jsonify({'error': '该账号是学生账号，无法绑定为教师'}), 400

    # 检查 openid 是否已绑定其他账号
    existing = db.session.execute(
        text('SELECT id FROM wx_users WHERE openid = :openid'),
        {'openid': openid}
    ).fetchone()
    if existing:
        return jsonify({'error': '该微信已绑定其他账号，请先解绑'}), 409

    # 检查该 user_id 是否已绑定其他 openid
    existing2 = db.session.execute(
        text('SELECT id FROM wx_users WHERE user_id = :uid'),
        {'uid': user.id}
    ).fetchone()
    if existing2:
        return jsonify({'error': '该账号已绑定其他微信，请先解绑'}), 409

    now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    db.session.execute(text('''
        INSERT INTO wx_users (openid, user_id, created_at, last_login)
        VALUES (:openid, :uid, :now, :now)
    '''), {'openid': openid, 'uid': user.id, 'now': now})
    db.session.commit()

    wx_row = db.session.execute(
        text('SELECT id FROM wx_users WHERE openid = :openid'),
        {'openid': openid}
    ).fetchone()
    token = _issue_jwt(user.id, wx_row.id, user.role)
    return jsonify({'token': token, 'user': user.to_dict()})


@mp_bp.route('/api/mp/register', methods=['POST'])
def mp_register():
    """
    教师在小程序注册新 web 账号。
    Body: { openid_token, username, password }
    Response: { token, user }
    """
    data = request.get_json(force=True) or {}
    openid_token = (data.get('openid_token') or '').strip()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    openid = _decode_openid_token(openid_token)
    if not openid:
        return jsonify({'error': 'openid_token 无效或已过期，请重新扫码'}), 401

    if not username or not password:
        return jsonify({'error': '请输入用户名和密码'}), 400
    if len(username) < 2 or len(username) > 32:
        return jsonify({'error': '用户名长度需在 2~32 个字符'}), 400
    if len(password) < 6:
        return jsonify({'error': '密码至少 6 位'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': '用户名已被占用'}), 409

    # 检查 openid 未绑定其他账号
    existing = db.session.execute(
        text('SELECT id FROM wx_users WHERE openid = :openid'),
        {'openid': openid}
    ).fetchone()
    if existing:
        return jsonify({'error': '该微信已绑定账号，请用绑定流程登录'}), 409

    new_user = User(
        username=username,
        password_hash=generate_password_hash(password),
        role='user',
    )
    db.session.add(new_user)
    db.session.flush()

    now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    db.session.execute(text('''
        INSERT INTO wx_users (openid, user_id, created_at, last_login)
        VALUES (:openid, :uid, :now, :now)
    '''), {'openid': openid, 'uid': new_user.id, 'now': now})
    db.session.commit()

    wx_row = db.session.execute(
        text('SELECT id FROM wx_users WHERE openid = :openid'),
        {'openid': openid}
    ).fetchone()
    token = _issue_jwt(new_user.id, wx_row.id, new_user.role)
    return jsonify({'token': token, 'user': new_user.to_dict()}), 201


@mp_bp.route('/api/mp/student-login', methods=['POST'])
def mp_student_login():
    """
    学生自动注册并登录（无需用户名密码，直接用微信 openid）。
    Body: { openid_token, nickName?, avatarUrl? }
    Response: { token, user }
    """
    data = request.get_json(force=True) or {}
    openid_token = (data.get('openid_token') or '').strip()
    nick_name = data.get('nickName', '')
    avatar_url = data.get('avatarUrl', '')

    openid = _decode_openid_token(openid_token)
    if not openid:
        return jsonify({'error': 'openid_token 无效或已过期，请重新进入小程序'}), 401

    # 检查是否已经绑定（理论上此接口只会在 is_new_user=true 时调用）
    existing = db.session.execute(
        text('SELECT id, user_id FROM wx_users WHERE openid = :openid'),
        {'openid': openid}
    ).fetchone()
    if existing:
        user = User.query.get(existing.user_id)
        token = _issue_jwt(user.id, existing.id, user.role)
        return jsonify({'token': token, 'user': user.to_dict()})

    # 自动创建学生账号
    username = f'student_{openid[:8]}'
    if User.query.filter_by(username=username).first():
        username = f'student_{secrets.token_hex(4)}'

    new_user = User(
        username=username,
        password_hash=generate_password_hash(secrets.token_hex(16)),
        role='student',
    )
    db.session.add(new_user)
    db.session.flush()

    now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    db.session.execute(text('''
        INSERT INTO wx_users (openid, user_id, nickname, avatar_url, created_at, last_login)
        VALUES (:openid, :uid, :nick, :avatar, :now, :now)
    '''), {'openid': openid, 'uid': new_user.id,
           'nick': nick_name, 'avatar': avatar_url, 'now': now})
    db.session.commit()

    wx_row = db.session.execute(
        text('SELECT id FROM wx_users WHERE openid = :openid'),
        {'openid': openid}
    ).fetchone()
    token = _issue_jwt(new_user.id, wx_row.id, 'student')
    return jsonify({'token': token, 'user': new_user.to_dict()}), 201


@mp_bp.route('/api/mp/me', methods=['GET'])
@mp_jwt_required
def mp_me():
    """获取当前用户信息（需 JWT）。"""
    from flask import g
    user = User.query.get(g.mp_user_id)
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    return jsonify({'user': user.to_dict()})


# ── 微信 API ──────────────────────────────────────────────────────────────────

def _code2session(code: str) -> tuple[str | None, str]:
    """调用微信 code2session 接口，返回 (openid, errmsg)。"""
    if not MP_APPID or not MP_SECRET:
        current_app.logger.error('[mp_auth] WX_MP_APPID / WX_MP_SECRET 未配置')
        return None, 'AppID/Secret 未配置'
    try:
        resp = requests.get(
            'https://api.weixin.qq.com/sns/jscode2session',
            params={
                'appid': MP_APPID,
                'secret': MP_SECRET,
                'js_code': code,
                'grant_type': 'authorization_code',
            },
            timeout=8,
        )
        data = resp.json()
        openid = data.get('openid')
        errmsg = data.get('errmsg', str(data.get('errcode', '未知错误')))
        return openid, errmsg
    except Exception as e:
        return None, str(e)
