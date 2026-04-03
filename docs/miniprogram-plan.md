# 试卷系统微信小程序改造技术规划

**文档版本：** v1.0  
**日期：** 2026-04-03  
**适用项目：** 试卷生成-online → 微信小程序教学版

---

## 目录

1. [改造范围与目标](#1-改造范围与目标)
2. [整体架构设计](#2-整体架构设计)
3. [小程序目录结构](#3-小程序目录结构)
4. [数据库扩展方案](#4-数据库扩展方案)
5. [后端改造清单](#5-后端改造清单)
6. [认证与权限设计](#6-认证与权限设计)
7. [学生答题模块设计](#7-学生答题模块设计)
8. [自动评分逻辑](#8-自动评分逻辑)
9. [教师端功能设计](#9-教师端功能设计)
10. [前端技术选型](#10-前端技术选型)
11. [关键页面与交互流程](#11-关键页面与交互流程)
12. [API 接口清单](#12-api-接口清单)
13. [分阶段实施计划](#13-分阶段实施计划)
14. [风险与注意事项](#14-风险与注意事项)

---

## 1. 改造范围与目标

### 1.1 保留功能

| 模块 | 保留内容 | 说明 |
|------|---------|------|
| 题库管理 | 全部保留 | QuestionModel 数据结构完整复用 |
| 试卷管理 | 全部保留 | ExamModel 复用，新增"发布"状态 |
| 用户认证 | 保留 Web 端，扩展小程序端 | 双认证并存（Session + JWT） |
| 题目导入导出 | 全部保留 | 教师仍可在 Web 端批量管理 |
| 团队协作 | 全部保留 | 教师可共享题库 |

### 1.2 移除功能

| 模块 | 移除理由 | 处理方式 |
|------|---------|---------|
| AI 知识图谱（rag_routes.py） | 改造方向不需要，降低复杂度 | 后端代码保留但前端不暴露入口 |
| KG 可视化（kg_routes.py） | 同上 | 保留路由，小程序不访问 |
| 面试抽题模块（interview_routes.py） | 功能替换为学生答题模块 | 数据表保留，不新增；新建答题表 |

### 1.3 新增功能

| 功能 | 说明 |
|------|------|
| 微信小程序登录 | openid 绑定系统用户，JWT 认证 |
| 考试场次发布 | 教师将试卷封装为一次考试，设置时间窗口 |
| 扫码加入考试 | 学生扫描教师生成的二维码进入答题 |
| 在线答题 | 倒计时、断点续答、防切屏、选项乱序 |
| 自动评分 | 客观题即时评分，主观题标记人工复核 |
| 成绩查看 | 学生查看成绩；教师查看班级统计 |
| 随机套题 | 同一场考试，不同学生看到不同的题目顺序或不同套卷 |

### 1.4 用户角色重定义

| 角色 | 来源 | 能力 |
|------|------|------|
| `admin` | 原有 | Web 端全部功能 + 小程序教师视图 |
| `teacher`（原 `vip`） | 原有 vip 角色复用 | 小程序：发布考试、查看成绩统计；Web 端全功能 |
| `student`（原 `user`） | 微信登录自动注册 | 仅限小程序学生端：加入考试、答题、看成绩 |
| `guest` | 原有 | 不开放小程序访问 |

---

## 2. 整体架构设计

```
┌──────────────────────────────────────────────────────────────────┐
│                         客户端层                                  │
│                                                                  │
│   ┌─────────────────────┐      ┌──────────────────────────────┐  │
│   │    Web 浏览器        │      │       微信小程序              │  │
│   │  (现有 index.html)  │      │                              │  │
│   │  教师题库管理        │      │  主包（教师端）               │  │
│   │  试卷生成/导出       │      │  ├─ 登录页                   │  │
│   │  管理员后台          │      │  ├─ 试卷列表                 │  │
│   └──────────┬──────────┘      │  ├─ 发布考试                 │  │
│              │ Session Cookie  │  └─ 成绩统计                 │  │
│              │                 │                              │  │
│              │                 │  学生分包（packageStudent）   │  │
│              │                 │  ├─ 扫码加入                 │  │
│              │                 │  ├─ 答题页                   │  │
│              │                 │  └─ 成绩页                   │  │
│              │                 └───────────┬──────────────────┘  │
│              │                             │ Bearer JWT           │
└──────────────┼─────────────────────────────┼────────────────────-┘
               │                             │
┌──────────────▼─────────────────────────────▼────────────────────┐
│                      Flask 后端（现有 + 扩展）                    │
│                                                                  │
│  现有 Blueprint               新增 Blueprint                      │
│  ├─ main (routes.py)         ├─ mp_auth  (/api/mp/)             │
│  ├─ auth (auth_routes.py)    ├─ exam_session (/api/sessions/)   │
│  ├─ team (team_routes.py)    └─ answers (/api/answers/)         │
│  ├─ rag  (保留，不暴露)                                           │
│  └─ interview (保留，不扩展)                                      │
│                                                                  │
│  认证层：get_current_user_any()                                   │
│          └─ Session(Web) + JWT Bearer(小程序) 双兼容              │
└──────────────────────────────┬───────────────────────────────────┘
                               │
               ┌───────────────▼───────────────┐
               │        SQLite 数据库            │
               │  现有表（不改动字段）            │
               │  + wx_users（新增）             │
               │  + exam_sessions（新增）        │
               │  + student_exams（新增）        │
               │  + student_answers（新增）      │
               └───────────────────────────────┘
```

### 2.1 关键设计原则

1. **最小侵入**：现有 Web 功能零改动，所有扩展通过新增路由和新增表实现。
2. **认证双轨**：`get_current_user_any()` 同时支持 Session（Web）和 JWT Bearer（小程序），一套业务逻辑服务两端。
3. **数据复用**：`QuestionModel`、`ExamModel` 直接复用，不新增字段，新增表通过外键关联。
4. **渐进部署**：分阶段上线，后端先行，前端分包按需加载。

---

## 3. 小程序目录结构

```
miniprogram/
│
├── app.js                      # 全局初始化，检查登录态
├── app.json                    # 分包配置、tabBar、权限声明
├── app.wxss                    # 全局样式
│
├── pages/                      # 主包页面（首次启动必须加载）
│   ├── login/                  # 统一登录页（微信授权）
│   │   ├── login.js
│   │   ├── login.wxml
│   │   └── login.wxss
│   ├── index/                  # 首页（按角色分流：教师/学生）
│   │   ├── index.js
│   │   └── index.wxml
│   └── profile/                # 个人中心（角色展示、退出）
│       ├── profile.js
│       └── profile.wxml
│
├── packageStudent/             # 学生端分包（≤2MB，按需加载）
│   ├── pages/
│   │   ├── join-exam/          # 扫码/输入码加入考试
│   │   │   ├── join-exam.js
│   │   │   └── join-exam.wxml
│   │   ├── do-exam/            # 核心答题页
│   │   │   ├── do-exam.js
│   │   │   ├── do-exam.wxml
│   │   │   └── do-exam.wxss
│   │   └── result/             # 成绩与解析页
│   │       ├── result.js
│   │       └── result.wxml
│   └── components/
│       ├── question-item/      # 单道题渲染组件（含富文本）
│       ├── option-group/       # 选项组（单选/多选/判断）
│       ├── answer-nav/         # 答题卡导航（题号宫格）
│       └── count-down/         # 倒计时组件
│
├── packageTeacher/             # 教师端分包
│   ├── pages/
│   │   ├── exam-list/          # 我的试卷列表
│   │   ├── publish-exam/       # 发布考试（选试卷→设参数→生成码）
│   │   ├── monitor/            # 考试实时监控（在考人数、交卷进度）
│   │   └── score-detail/       # 成绩详情（班级统计 + 逐人查看）
│   └── components/
│       ├── exam-card/          # 试卷卡片
│       └── score-chart/        # 成绩分布图（使用 echarts-wx）
│
├── utils/
│   ├── request.js              # 网络请求封装（自动带 Bearer Token）
│   ├── auth.js                 # 登录态管理、Token 刷新
│   ├── exam-store.js           # 答题状态全局存储（轻量 Store）
│   └── html-helper.js          # HTML 清理、图片 URL 替换
│
└── components/                 # 全局公共组件（主包可用）
    └── empty-state/            # 空状态占位组件
```

### 3.1 app.json 关键配置

```json
{
  "pages": [
    "pages/login/login",
    "pages/index/index",
    "pages/profile/profile"
  ],
  "subpackages": [
    {
      "root": "packageStudent",
      "name": "student",
      "pages": [
        "pages/join-exam/join-exam",
        "pages/do-exam/do-exam",
        "pages/result/result"
      ]
    },
    {
      "root": "packageTeacher",
      "name": "teacher",
      "pages": [
        "pages/exam-list/exam-list",
        "pages/publish-exam/publish-exam",
        "pages/monitor/monitor",
        "pages/score-detail/score-detail"
      ]
    }
  ],
  "preloadRule": {
    "pages/index/index": {
      "network": "wifi",
      "packages": ["student", "teacher"]
    }
  },
  "tabBar": {
    "list": [
      { "pagePath": "pages/index/index", "text": "首页" },
      { "pagePath": "pages/profile/profile", "text": "我的" }
    ]
  },
  "permission": {
    "scope.camera": { "desc": "扫描考试二维码需要摄像头权限" }
  },
  "requiredPrivateInfos": ["getLocation"]
}
```

---

## 4. 数据库扩展方案

所有新表追加到 `app/factory.py` 的 `_migrate_db()` 函数中的 `new_tables` 列表，保持与现有迁移策略一致，**无 Alembic，幂等执行**。

### 4.1 新增表 DDL

```sql
-- 微信用户绑定表（openid → User 映射）
CREATE TABLE IF NOT EXISTS wx_users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    openid      TEXT UNIQUE NOT NULL,
    unionid     TEXT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nickname    TEXT,
    avatar_url  TEXT,
    role_in_mp  TEXT DEFAULT 'student',   -- student / teacher
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login  DATETIME
);

-- 考试场次（教师基于试卷创建的一次实际考试）
CREATE TABLE IF NOT EXISTS exam_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id         TEXT NOT NULL REFERENCES exams(exam_id),
    owner_id        INTEGER NOT NULL REFERENCES users(id),
    title           TEXT NOT NULL,
    description     TEXT,
    start_time      DATETIME,              -- NULL 表示即时开放
    end_time        DATETIME,              -- NULL 表示不限时
    duration_min    INTEGER DEFAULT 90,    -- 答题时限（分钟）
    allow_review    INTEGER DEFAULT 0,     -- 交卷后是否可查看解析
    randomize_opts  INTEGER DEFAULT 1,     -- 选项是否乱序
    randomize_qs    INTEGER DEFAULT 0,     -- 题目顺序是否乱序
    multi_paper     INTEGER DEFAULT 0,     -- 是否启用多套卷（A/B卷）
    qr_code_key     TEXT UNIQUE,           -- 扫码加入的唯一 key（8位随机）
    status          TEXT DEFAULT 'draft',  -- draft / active / closed
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 学生参加考试的记录（一人一记录）
CREATE TABLE IF NOT EXISTS student_exams (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES exam_sessions(id),
    student_id      INTEGER NOT NULL REFERENCES users(id),
    paper_variant   TEXT DEFAULT 'A',      -- 套卷标识（A/B/...）
    question_order  TEXT,                  -- JSON：题目 ID 的乱序数组
    start_time      DATETIME,
    submit_time     DATETIME,
    total_score     REAL,
    max_score       REAL,                  -- 试卷满分
    status          TEXT DEFAULT 'pending', -- pending/in_progress/submitted/graded
    switch_count    INTEGER DEFAULT 0,     -- 切屏次数
    ip_address      TEXT,
    UNIQUE(session_id, student_id)
);

-- 逐题答案存储
CREATE TABLE IF NOT EXISTS student_answers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    student_exam_id  INTEGER NOT NULL REFERENCES student_exams(id),
    question_id      TEXT NOT NULL REFERENCES questions(question_id),
    answer           TEXT,                -- 学生的作答
    score            REAL DEFAULT 0,     -- 得分
    full_score       REAL DEFAULT 0,     -- 该题满分
    is_correct       INTEGER,            -- 客观题：1/0；主观题：NULL
    graded_by        TEXT DEFAULT 'auto',-- auto / teacher
    teacher_comment  TEXT,               -- 教师批注（主观题）
    saved_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_exam_id, question_id)
);
```

### 4.2 现有表零改动说明

- `users`：不新增字段，role 字段 `user` 用于学生，`vip` 用于教师
- `questions`：不改动，直接通过 `student_answers.question_id` 关联
- `exams`：不改动，通过 `exam_sessions.exam_id` 关联
- `interview_*` 系列表：保留，不再扩展新功能

---

## 5. 后端改造清单

### 5.1 新增文件

| 文件 | 用途 |
|------|------|
| `app/mp_auth_routes.py` | 微信登录、JWT 签发 |
| `app/session_routes.py` | 考试场次 CRUD、发布、监控 |
| `app/answer_routes.py` | 答题保存、交卷、评分、成绩查询 |
| `app/grading.py` | 自动评分逻辑（纯函数，无副作用） |

### 5.2 改动现有文件（最小化）

**`app/auth_routes.py`**：新增 `get_current_user_any()` 函数

```python
def get_current_user_any():
    """兼容 Web Session（Cookie）和小程序 JWT Bearer Token。"""
    from flask import session, request, current_app
    import jwt as pyjwt

    # 优先 Web Session（现有逻辑不变）
    uid = session.get('user_id')
    if uid:
        return User.query.get(uid)

    # 小程序 JWT
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        try:
            payload = pyjwt.decode(
                auth[7:],
                current_app.config['SECRET_KEY'],
                algorithms=['HS256']
            )
            return User.query.get(payload.get('user_id'))
        except pyjwt.ExpiredSignatureError:
            return None  # 让调用方返回 401
        except pyjwt.InvalidTokenError:
            return None
    return None
```

**`app/factory.py`**：
- 在 `new_tables` 中追加 4 个新表的 DDL
- 注册 3 个新 Blueprint（mp_auth、session、answer）

**`app/routes.py`**：
- 将核心接口中的 `get_current_user()` 替换为 `get_current_user_any()`（约 15 处）
- 在返回 `question.to_dict()` 时，调用 `_absolutize_img()` 将图片 URL 转为绝对路径（小程序需要）

### 5.3 环境变量新增

在 `.env` 和 `.env.example` 中新增：

```
WX_MP_APPID=wx_xxxxxxxxxxxxxxxx     # 小程序 AppID
WX_MP_SECRET=xxxxxxxxxxxxxxxx       # 小程序 AppSecret
JWT_EXPIRE_DAYS=30                  # Token 有效期（天）
BASE_URL=https://your-domain.com    # 服务器公网地址（用于图片 URL 绝对化）
```

---

## 6. 认证与权限设计

### 6.1 微信登录流程

```
小程序                    Flask /api/mp/login          微信服务器
  │                              │                         │
  │ wx.login()                   │                         │
  │<─ code ──────────────────────│                         │
  │                              │                         │
  │ POST /api/mp/login           │                         │
  │ { code, nickName, avatarUrl }│                         │
  │──────────────────────────────>                         │
  │                              │ GET /sns/jscode2session │
  │                              │──────────────────────────>
  │                              │<─ { openid, session_key }
  │                              │                         │
  │                              │ 查 wx_users(openid)     │
  │                              │ 无记录 → 创建 User(role=student)
  │                              │           + WxUser      │
  │                              │                         │
  │                              │ 签 JWT (user_id, exp)   │
  │<── { token, user, role } ────│                         │
  │                              │                         │
  │ wx.setStorageSync('token')   │                         │
```

### 6.2 小程序端 Token 管理（`utils/auth.js`）

```javascript
const AUTH_KEY = 'mp_token'
const USER_KEY = 'mp_user'

const auth = {
  // 登录并存储 token
  async login() {
    const { code } = await wx.login()
    const { nickName, avatarUrl } = await this._getProfile()
    const res = await request.post('/api/mp/login', { code, nickName, avatarUrl })
    wx.setStorageSync(AUTH_KEY, res.token)
    wx.setStorageSync(USER_KEY, res.user)
    return res
  },

  getToken() { return wx.getStorageSync(AUTH_KEY) || '' },
  getUser()  { return wx.getStorageSync(USER_KEY) || null },
  isLoggedIn() { return !!this.getToken() },
  isTeacher() {
    const u = this.getUser()
    return u && (u.role === 'vip' || u.role === 'admin')
  },
  isStudent() {
    const u = this.getUser()
    return u && u.role === 'user'
  },

  logout() {
    wx.removeStorageSync(AUTH_KEY)
    wx.removeStorageSync(USER_KEY)
    wx.reLaunch({ url: '/pages/login/login' })
  },

  // 检查过期（JWT 解析 exp）
  isExpired() {
    const token = this.getToken()
    if (!token) return true
    try {
      const payload = JSON.parse(
        wx.arrayBufferToBase64(
          Uint8Array.from(atob(token.split('.')[1]),c=>c.charCodeAt(0)).buffer
        ).replace(/-/g,'+').replace(/_/g,'/')
      )
      // base64 decode 实际在小程序中需用 wx.arrayBufferToBase64
      return Date.now() / 1000 > payload.exp
    } catch { return true }
  }
}
module.exports = auth
```

### 6.3 权限矩阵（小程序端）

| 功能 | student | teacher(vip) | admin |
|------|---------|-------------|-------|
| 扫码加入考试 | ✓ | ✓ | ✓ |
| 在线答题 | ✓ | - | - |
| 查看自己成绩 | ✓ | - | - |
| 查看试卷列表 | - | ✓ | ✓ |
| 发布考试 | - | ✓ | ✓ |
| 实时监控考试 | - | ✓ | ✓ |
| 查看全班成绩 | - | ✓ | ✓ |
| 人工批改主观题 | - | ✓ | ✓ |

---

## 7. 学生答题模块设计

### 7.1 整体流程

```
学生打开小程序
       │
       ▼
  微信授权登录
  (自动注册 student 账号)
       │
       ▼
  首页（学生视图）
  [扫码加入考试] [我的历史成绩]
       │
       ▼ 扫码 or 输入 8 位码
  POST /api/sessions/{key}/join
       │
       ├── 考试未开始 → 等待页（倒计时）
       ├── 考试已结束 → 提示已截止
       └── 考试进行中 ─────────────────────────────┐
                                                   │
       ▼                                           │
  获取试卷 GET /api/sessions/{key}/paper            │
  (题目按 question_order 排序，选项已乱序)           │
       │                                           │
       ▼                                           │
  进入答题页（do-exam）                              │
  ┌────────────────────────────────────────────┐   │
  │  顶部：进度条 | 剩余时间 | 题目数           │   │
  │                                            │   │
  │  题目内容（mp-html 渲染，支持图片/公式）    │   │
  │                                            │   │
  │  选项区（单选 Radio / 多选 Checkbox）       │   │
  │    或 填空/简答 Textarea                   │   │
  │                                            │   │
  │  底部：[上一题] [答题卡] [下一题]           │   │
  └────────────────────────────────────────────┘   │
       │                                           │
       │ 每切换题目 POST /api/answers/save          │
       │ 每 30 秒自动保存                           │
       │ 切屏 → POST /api/answers/switch-event     │
       │                                           │
       ▼                                           │
  [交卷] → 确认弹窗 → POST /api/answers/submit     │
       │                                           │
       ▼                                           │
  成绩页（result）                                  │
  客观题：立即显示得分 + 正确答案（若 allow_review）  │
  主观题：显示"待批改"                              │
```

### 7.2 答题页核心状态（`do-exam.js`）

```javascript
Page({
  data: {
    sessionKey: '',         // 8位码
    studentExamId: null,    // student_exams.id
    questions: [],          // 当前套卷的题目列表（已乱序）
    currentIndex: 0,        // 当前题目下标
    answers: {},            // { question_id: answer_value }
    remainSeconds: 0,       // 剩余秒数（服务端下发）
    switchCount: 0,
    submitting: false,
  },

  _timer: null,
  _saveTimer: null,
  _leftAt: null,

  onLoad({ key }) {
    this.setData({ sessionKey: key })
    this._loadPaper(key)
  },

  async _loadPaper(key) {
    // GET /api/sessions/{key}/paper
    const res = await request.get(`/api/sessions/${key}/paper`)
    // 恢复断点：如果 studentExamId 存在，拉取已保存答案
    const savedAnswers = await this._restoreAnswers(res.student_exam_id)
    this.setData({
      questions: res.questions,
      studentExamId: res.student_exam_id,
      remainSeconds: res.remain_seconds,
      answers: savedAnswers,
    })
    this._startTimer(res.remain_seconds)
    this._startAutoSave()
  },

  // 断点续答：拉取服务端已保存的答案
  async _restoreAnswers(studentExamId) {
    const res = await request.get(`/api/answers/draft/${studentExamId}`)
    return res.answers || {}
  },

  // 保存单题答案（即时 + 防抖）
  saveAnswer(questionId, answer) {
    const answers = { ...this.data.answers, [questionId]: answer }
    this.setData({ answers })
    // 后台静默保存，不阻塞 UI
    request.post('/api/answers/save', {
      student_exam_id: this.data.studentExamId,
      question_id: questionId,
      answer,
    }).catch(() => {/* 忽略网络错误，下次 autoSave 会重试 */})
  },

  // 每 30 秒批量保存所有答案
  _startAutoSave() {
    this._saveTimer = setInterval(() => {
      request.post('/api/answers/save-all', {
        student_exam_id: this.data.studentExamId,
        answers: this.data.answers,
      }).catch(() => {})
    }, 30000)
  },

  // 倒计时（时间来自服务端，防止本地篡改）
  _startTimer(seconds) {
    this.setData({ remainSeconds: seconds })
    this._timer = setInterval(() => {
      const s = this.data.remainSeconds - 1
      if (s <= 0) {
        clearInterval(this._timer)
        this._submitExam(true) // 自动交卷
        return
      }
      this.setData({ remainSeconds: s })
    }, 1000)
  },

  // 防切屏
  onHide() {
    if (this.data.studentExamId) this._leftAt = Date.now()
  },
  onShow() {
    if (this._leftAt && this.data.studentExamId) {
      const sec = (Date.now() - this._leftAt) / 1000
      const count = this.data.switchCount + 1
      this.setData({ switchCount: count })
      request.post('/api/answers/switch-event', {
        student_exam_id: this.data.studentExamId,
        switch_count: count,
        duration_sec: sec,
      }).catch(() => {})
      this._leftAt = null
      // 可选：超过 N 次切屏自动交卷
      if (count >= 5) {
        wx.showToast({ title: '切屏次数过多，自动交卷', icon: 'none' })
        this._submitExam(true)
      }
    }
  },

  // 交卷
  async _submitExam(auto = false) {
    if (this.data.submitting) return
    this.setData({ submitting: true })
    clearInterval(this._timer)
    clearInterval(this._saveTimer)
    try {
      const res = await request.post('/api/answers/submit', {
        student_exam_id: this.data.studentExamId,
        answers: this.data.answers,
        auto_submit: auto,
      })
      wx.redirectTo({
        url: `/packageStudent/pages/result/result?id=${res.student_exam_id}`
      })
    } catch (e) {
      this.setData({ submitting: false })
      wx.showToast({ title: '交卷失败，请重试', icon: 'none' })
    }
  },

  onUnload() {
    clearInterval(this._timer)
    clearInterval(this._saveTimer)
  },
})
```

### 7.3 随机套题策略

同一场考试（`exam_session`），不同学生分配不同"套卷变体"：

**方案 A（推荐）：题目顺序乱序 + 选项乱序**
- 每个学生在加入考试时，后端随机生成一个题目 ID 列表的排列顺序，存入 `student_exams.question_order`（JSON）
- 同时对每道选择题，在下发时随机打乱选项顺序，并调整正确答案字母
- 学生看到的题目顺序、选项顺序各不相同，但基于同一套题
- 实现简单，不需要维护多套题目

**方案 B（可选）：多套卷（A/B 卷）**
- 教师提前创建两份不同试卷，在发布考试时绑定为"A卷"和"B卷"
- 学生按奇偶编号或随机分配到 A/B 卷
- 适合需要绝对隔离题目集合的高要求场景

**默认采用方案 A**，`exam_sessions.multi_paper = 0` 时使用方案 A。

---

## 8. 自动评分逻辑

### 8.1 评分模块（`app/grading.py`）

```python
"""
app/grading.py
自动评分逻辑：纯函数，无数据库副作用。
交卷时由 answer_routes.py 调用 grade_student_exam() 写回结果。
"""

import re


def auto_grade_question(question, student_answer: str, full_score: float) -> dict:
    """
    对单道题打分。
    返回：{
        'score': float,       实际得分
        'is_correct': bool|None,   客观题 True/False，主观题 None
        'method': str         'exact' / 'set' / 'partial' / 'normalized' / 'manual'
    }
    """
    q_type = (question.question_type or '').strip()
    correct = (question.answer or '').strip()
    student = (student_answer or '').strip()

    # ── 单选题、判断题：精确匹配（忽略大小写和全半角）──────────────────
    if q_type in ('单选', '是非', 'single_choice', 'true_false'):
        c = _normalize_choice(correct)
        s = _normalize_choice(student)
        is_correct = (c == s) and bool(c)
        return {
            'score': full_score if is_correct else 0.0,
            'is_correct': is_correct,
            'method': 'exact',
        }

    # ── 多选题：集合比较，漏选半分，多选不得分 ────────────────────────
    if q_type in ('多选', 'multiple_choice'):
        c_set = _parse_choice_set(correct)
        s_set = _parse_choice_set(student)
        if not c_set:
            return {'score': 0.0, 'is_correct': None, 'method': 'manual'}
        if c_set == s_set:
            return {'score': full_score, 'is_correct': True, 'method': 'set'}
        # 漏选（子集）：得一半分
        if s_set and s_set.issubset(c_set):
            return {'score': round(full_score * 0.5, 2), 'is_correct': False, 'method': 'partial'}
        # 多选或全错：0 分
        return {'score': 0.0, 'is_correct': False, 'method': 'set'}

    # ── 填空题（如果有此题型）：去空格、忽略大小写 ───────────────────
    if q_type in ('填空', 'fill_blank'):
        c_norm = re.sub(r'\s+', '', correct).upper()
        s_norm = re.sub(r'\s+', '', student).upper()
        is_correct = bool(c_norm) and (c_norm == s_norm)
        return {
            'score': full_score if is_correct else 0.0,
            'is_correct': is_correct,
            'method': 'normalized',
        }

    # ── 简答、论述、材料分析：标记人工批改 ──────────────────────────
    return {'score': 0.0, 'is_correct': None, 'method': 'manual'}


def grade_student_exam(student_exam_id: int, db, ExamSession, StudentExam,
                       StudentAnswer, QuestionModel) -> float:
    """
    交卷后批量评分，写回 student_answers 和 student_exams。
    返回：客观题总得分（主观题待人工）
    """
    se = StudentExam.query.get(student_exam_id)
    if not se:
        return 0.0

    # 获取试卷配置（题型 → 每题分值）
    session = ExamSession.query.get(se.session_id)
    exam_config = {}
    if session and session.exam:
        import json
        raw_config = session.exam.config or '{}'
        if isinstance(raw_config, str):
            raw_config = json.loads(raw_config)
        exam_config = raw_config  # {'单选': {'count':10,'points':1.5}, ...}

    answers = StudentAnswer.query.filter_by(student_exam_id=student_exam_id).all()
    total_auto = 0.0
    has_manual = False

    for ans in answers:
        q = QuestionModel.query.get(ans.question_id)
        if not q:
            continue
        # 获取该题满分
        q_type = q.question_type
        full_score = ans.full_score or float(
            exam_config.get(q_type, {}).get('points', 1)
        )
        result = auto_grade_question(q, ans.answer or '', full_score)
        ans.score = result['score']
        ans.is_correct = result['is_correct']
        ans.graded_by = result['method']
        ans.full_score = full_score

        if result['method'] == 'manual':
            has_manual = True
        else:
            total_auto += result['score']

    # 更新 student_exams 汇总
    se.total_score = total_auto
    se.status = 'partial' if has_manual else 'graded'
    db.session.commit()
    return total_auto


# ── 内部辅助函数 ─────────────────────────────────────────────────

def _normalize_choice(s: str) -> str:
    """单选/判断：统一大写，处理中文'正确/错误'↔'T/F'。"""
    s = s.strip().upper()
    mapping = {'正确': 'T', 'TRUE': 'T', '对': 'T',
               '错误': 'F', 'FALSE': 'F', '错': 'F', '×': 'F', '√': 'T'}
    return mapping.get(s, s)


def _parse_choice_set(s: str) -> set:
    """多选：'A,B,C' / 'ABC' / 'A B C' → {'A','B','C'}"""
    s = s.upper().replace('，', ',').replace(' ', ',')
    parts = re.split(r'[,\s]+', s)
    return {p.strip() for p in parts if re.match(r'^[A-Z]$', p.strip())}
```

### 8.2 主观题人工批改接口

```
POST /api/answers/grade-manual
Body: {
    "student_exam_id": 123,
    "question_id": "q_xxx",
    "score": 8.5,
    "comment": "思路正确，但缺少关键论据"
}
权限：teacher / admin
```

---

## 9. 教师端功能设计

### 9.1 发布考试流程

```
教师在小程序中：

[我的试卷列表]
    │ 选择一份试卷
    ▼
[发布考试配置页]
  ┌──────────────────────────────────┐
  │ 考试标题：___________            │
  │ 开始时间：[日期时间选择器]        │
  │ 结束时间：[日期时间选择器]        │
  │ 答题时限：__ 分钟                 │
  │ 题目乱序：[开关]                  │
  │ 选项乱序：[开关]（推荐开启）      │
  │ 交卷后可查看解析：[开关]          │
  │ [发布考试]                       │
  └──────────────────────────────────┘
        │
        ▼
  POST /api/sessions/create
        │
        ▼
  [考试码展示页]
  ┌──────────────────────────────────┐
  │                                  │
  │  考试码：  A7BX29KQ              │
  │                                  │
  │  [二维码图片]（含 KEY）           │
  │                                  │
  │  [保存图片分享给学生]             │
  │  [查看实时监控]                   │
  └──────────────────────────────────┘
```

### 9.2 实时监控页

通过轮询（每 10 秒）`GET /api/sessions/{id}/status` 更新：

```
┌─────────────────────────────────────┐
│ 《期末考试》监控                     │
│ 剩余时间：45:30                     │
│                                     │
│ 总参与人数：28                       │
│ 答题中：    22 人                   │
│ 已交卷：     6 人（提前）            │
│ 未开始：     0 人                   │
│                                     │
│ 切屏异常（>3次）：张三、李四         │
│                                     │
│ [结束考试] [查看成绩]               │
└─────────────────────────────────────┘
```

### 9.3 成绩统计页

```
GET /api/sessions/{id}/scores

┌─────────────────────────────────────┐
│ 平均分：72.3 / 100                   │
│ 最高分：98   最低分：35              │
│                                     │
│ 分数段分布：[柱状图]                 │
│ 0-59: 5人 ██                        │
│ 60-79: 12人 ████████                │
│ 80-100: 11人 ███████                │
│                                     │
│ 各题得分率：[列表]                   │
│ 第1题（单选）：得分率 85%            │
│ 第2题（多选）：得分率 62%            │
│ 第8题（简答）：待批改 28人           │
│                                     │
│ [逐人查看] [导出成绩 Excel]          │
└─────────────────────────────────────┘
```

---

## 10. 前端技术选型

### 10.1 UI 组件库

**选用：Vant Weapp（有赞出品，MIT 开源）**

```bash
# 小程序项目根目录
npm init -y
npm install @vant/weapp
# 在微信开发者工具中：工具 → 构建 npm
```

关键组件对应：

| 场景 | Vant 组件 |
|------|----------|
| 单选题 | `van-radio` + `van-radio-group` |
| 多选题 | `van-checkbox` + `van-checkbox-group` |
| 判断题 | `van-radio-group`（"正确"/"错误"） |
| 简答输入 | `van-field` type="textarea" |
| 倒计时 | `van-count-down` |
| 答题进度 | `van-progress` |
| 交卷确认 | `van-dialog` |
| 切屏警告 | `van-notify` |
| 成绩卡片 | `van-card` |
| 步骤导航 | `van-steps` |

### 10.2 富文本渲染

**选用：mp-html（MIT 开源，npm 安装）**

```bash
npm install mp-html
```

```xml
<!-- question-item/index.wxml -->
<mp-html content="{{question.content}}"
         lazy-load="{{true}}"
         selectable="{{false}}"
         image-preview="{{false}}" />
```

图片 URL 绝对化（后端处理，`routes.py` to_dict 时）：

```python
import os
BASE_URL = os.environ.get('BASE_URL', 'https://your-domain.com')

def _absolutize_img(html: str) -> str:
    if not html:
        return html
    return html.replace('src="/api/images/', f'src="{BASE_URL}/api/images/')
```

### 10.3 图表（教师成绩统计）

**选用：echarts-for-weixin（Apache ECharts 官方小程序适配版）**

```bash
npm install echarts
# 同时引入 ec-canvas 组件
```

### 10.4 开发框架

**直接使用原生小程序**（不使用 Taro/uni-app），原因：
- 项目规模适中，原生开发调试更直观
- 避免跨端框架引入额外复杂度和包体积
- 微信开发者工具原生支持更好

---

## 11. 关键页面与交互流程

### 11.1 登录页（pages/login）

```
[微信头像 + 欢迎文字]

[一键登录]  ← wx.getUserProfile + wx.login
           ← POST /api/mp/login
           ← 根据 role 跳转：student → 首页学生视图
                              teacher → 首页教师视图
```

### 11.2 首页分流（pages/index）

```javascript
// index.js - onLoad
const user = auth.getUser()
if (auth.isTeacher()) {
  // 展示教师视图：[我的试卷] [发布考试] [成绩查询]
  this.setData({ view: 'teacher' })
  wx.loadSubpackage({ name: 'teacher', success: () => {} })
} else {
  // 展示学生视图：[扫码参加考试] [我的考试记录]
  this.setData({ view: 'student' })
  wx.loadSubpackage({ name: 'student', success: () => {} })
}
```

### 11.3 答题卡（do-exam 内嵌组件）

```
题目编号宫格，已答/未答用颜色区分：

 [1✓] [2✓] [3 ] [4✓] [5 ]
 [6 ] [7✓] [8 ] [9✓] [10]

 已答：22题   未答：8题

 [确认交卷]
```

### 11.4 成绩页（packageStudent/pages/result）

```
┌─────────────────────────────────────┐
│ 《期末考试》成绩                     │
│                                     │
│         72 / 100 分                 │
│                                     │
│ 客观题：52/60    主观题：20/40*      │
│ *主观题得分待教师批改               │
│                                     │
│ 用时：45分23秒   切屏：1次           │
│                                     │
│ [查看答题详情]（若 allow_review）    │
│                                     │
│ 逐题列表（allow_review 开启时）：    │
│ ✓ 第1题  得1.5分                   │
│ ✗ 第3题  得0分  正确答案：B         │
│   解析：[mp-html 渲染解析文字]       │
│ ? 第8题  待批改                     │
└─────────────────────────────────────┘
```

---

## 12. API 接口清单

### 12.1 微信小程序专属接口（新增）

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/mp/login` | 微信登录（code→JWT） | 无 |
| GET | `/api/mp/me` | 获取当前用户信息 | JWT |
| PUT | `/api/mp/profile` | 更新昵称/头像 | JWT |

### 12.2 考试场次接口（新增）

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/sessions/create` | 发布考试（教师） | teacher+ |
| GET | `/api/sessions/{id}` | 获取场次详情 | teacher+ |
| PUT | `/api/sessions/{id}` | 修改场次配置 | 场次 owner |
| POST | `/api/sessions/{id}/close` | 提前结束考试 | 场次 owner |
| GET | `/api/sessions/{id}/status` | 实时监控数据 | 场次 owner |
| GET | `/api/sessions/{id}/scores` | 全班成绩汇总 | 场次 owner |
| GET | `/api/sessions/{id}/scores/export` | 导出成绩 Excel | 场次 owner |
| POST | `/api/sessions/{key}/join` | 学生加入考试（key=qr_code_key） | student |
| GET | `/api/sessions/{key}/paper` | 获取试卷（含乱序） | student（已加入） |
| GET | `/api/sessions/my` | 我的考试历史（学生） | student |

### 12.3 答题接口（新增）

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/answers/draft/{student_exam_id}` | 获取断点续答草稿 | 本人 |
| POST | `/api/answers/save` | 保存单题答案 | 本人 |
| POST | `/api/answers/save-all` | 批量保存所有答案 | 本人 |
| POST | `/api/answers/submit` | 交卷（触发评分） | 本人 |
| POST | `/api/answers/switch-event` | 上报切屏事件 | 本人 |
| GET | `/api/answers/result/{student_exam_id}` | 查看成绩（需 allow_review） | 本人 |
| POST | `/api/answers/grade-manual` | 人工批改主观题 | teacher+ |
| GET | `/api/answers/student/{student_exam_id}` | 教师查看某学生作答 | 场次 owner |

### 12.4 复用现有接口（加 JWT 支持）

以下接口只需在认证层加 `get_current_user_any()` 即可被小程序复用，无需其他改动：

| 路径 | 用途 |
|------|------|
| `GET /api/exams` | 教师查看自己的试卷列表 |
| `GET /api/exams/{exam_id}` | 教师查看试卷详情 |
| `GET /api/question-types` | 获取题型列表 |

---

## 13. 分阶段实施计划

### Phase 1：后端基础扩展（约 1 周）

**目标**：后端接受小程序请求，学生可登录

**任务清单**：
- [ ] 新增 4 张表（`wx_users`, `exam_sessions`, `student_exams`, `student_answers`）到 `factory._migrate_db()`
- [ ] 实现 `app/mp_auth_routes.py`（wx.login → code2Session → JWT）
- [ ] 在 `auth_routes.py` 中实现 `get_current_user_any()`
- [ ] 将 `routes.py` 核心接口的 `get_current_user()` 替换为 `get_current_user_any()`
- [ ] 新增 `.env` 变量：`WX_MP_APPID`, `WX_MP_SECRET`, `BASE_URL`
- [ ] 在 `routes.py` 的 `to_dict()` 中对 `content`/`explanation` 字段做图片 URL 绝对化
- [ ] 安装依赖：`pip install PyJWT`
- [ ] 在微信公众平台配置服务器域名白名单

**验收标准**：Postman 调用 `/api/mp/login` 能正确返回 JWT Token，带 Bearer Token 请求 `/api/exams` 能返回数据。

---

### Phase 2：考试发布与管理接口（约 1 周）

**目标**：教师可发布考试，生成考试码

**任务清单**：
- [ ] 实现 `app/session_routes.py`（CRUD + 状态管理 + 实时监控接口）
- [ ] 生成 `qr_code_key`（8位大写字母+数字随机码，保证唯一）
- [ ] 实现学生加入接口 `POST /api/sessions/{key}/join`（创建 `student_exams` 记录）
- [ ] 实现试卷下发接口 `GET /api/sessions/{key}/paper`（题目乱序 + 选项乱序逻辑）
- [ ] 实现成绩汇总接口 `GET /api/sessions/{id}/scores`
- [ ] 实现 Excel 成绩导出（复用现有 `openpyxl` 逻辑）
- [ ] 注册 Blueprint 到 `factory.py`

**验收标准**：通过 API 测试能完整走通"发布→加入→获取试卷"流程。

---

### Phase 3：答题与评分接口（约 1 周）

**目标**：核心答题链路可用

**任务清单**：
- [ ] 实现 `app/grading.py`（按第 8 节设计）
- [ ] 实现 `app/answer_routes.py`（保存/交卷/评分/结果查询）
- [ ] 实现断点续答（`GET /api/answers/draft/{id}`）
- [ ] 实现切屏上报（`POST /api/answers/switch-event`）
- [ ] 实现人工批改接口（`POST /api/answers/grade-manual`）
- [ ] 完整测试：单选/多选/判断/简答 各题型评分

**验收标准**：自动评分正确率 100%（客观题），主观题正确标记为 `method='manual'`。

---

### Phase 4：小程序学生端（约 2 周）

**目标**：学生可在小程序完成答题全流程

**任务清单**：
- [ ] 搭建小程序项目，配置 `app.json` 分包
- [ ] 集成 Vant Weapp、mp-html
- [ ] 实现登录页（wx.getUserProfile + wx.login）
- [ ] 实现首页（学生视图：扫码入口 + 历史记录）
- [ ] 实现扫码加入页（wx.scanCode + 手动输入 8 位码）
- [ ] 实现答题页（核心：倒计时、题目渲染、答案保存、答题卡、交卷）
- [ ] 实现成绩页（得分展示 + 逐题解析）
- [ ] 联调测试

**验收标准**：完整走通"扫码→答题→交卷→看成绩"，断网恢复后断点续答有效。

---

### Phase 5：小程序教师端（约 1.5 周）

**目标**：教师可在小程序发布和管理考试

**任务清单**：
- [ ] 实现教师首页（试卷列表 + 快捷操作）
- [ ] 实现发布考试页（参数配置 + 生成二维码）
- [ ] 实现实时监控页（轮询状态 + 异常标记）
- [ ] 实现成绩统计页（图表 + 逐人查看）
- [ ] 实现人工批改页（主观题打分）
- [ ] 实现导出成绩功能（调用后端接口 + wx.downloadFile）

**验收标准**：教师完整走通"发布→监控→批改→导出"。

---

### Phase 6：测试与上线（约 1 周）

**任务清单**：
- [ ] 真机测试（iOS + Android 各至少一台）
- [ ] 并发压测（模拟 50 人同时答题）
- [ ] 微信小程序提交审核（填写类目：教育→学习辅助）
- [ ] 生产服务器配置：HTTPS 必须（小程序强制）
- [ ] 服务器安全检查：JWT Secret 强度、接口限速
- [ ] 备份现有数据库

**总估时：约 7.5 周（单人开发）**

---

## 14. 风险与注意事项

### 14.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 题目含复杂 HTML/表格/图片，小程序渲染异常 | 中 | 提前用 mp-html 测试现有题目样本；可降级为纯文本 |
| 微信小程序图片域名校验失败 | 高 | 服务器必须配置 HTTPS，在微信后台添加 `downloadFile` 域名白名单 |
| SQLite 并发写入瓶颈（50+ 人同时交卷） | 中 | 开启 WAL 模式（`PRAGMA journal_mode=WAL`）；如压测不达标，升级 PostgreSQL |
| 学生故意断网规避倒计时 | 低 | 服务端记录 `start_time`，提交时校验 `submit_time - start_time >= duration_min * 60`；超时自动标记 |
| JWT Token 过期导致答题中断 | 高 | Token 有效期设 30 天；答题过程中检测 401 时自动刷新（静默重新登录） |

### 14.2 业务注意事项

1. **HTTPS 强制**：微信小程序只能请求 HTTPS 接口，生产服务器必须配置 SSL 证书（Let's Encrypt 免费）。
2. **图片域名**：`/api/images/<id>` 返回的图片必须通过 HTTPS 访问，且域名需在微信后台的"downloadFile 合法域名"中注册。
3. **选项乱序与答案映射**：打乱选项顺序时，必须同步记录选项原始顺序（或重新映射正确答案字母），否则自动评分会出错。建议后端在下发试卷时就将选项打乱并直接修正 `answer` 字段（如原答案 B → 打乱后 B 移到第 3 位 → 新答案改为 C），在 `student_exams.question_order` 中存储每题的选项映射表。
4. **主观题评分**：简答/论述题无法自动评分，必须有教师人工批改入口；成绩页需明确区分"已出分"和"待批改"状态。
5. **小程序审核**：涉及"在线考试"功能，审核时可能需要说明不涉及营利性培训，类目选择"教育→学习辅助"。
6. **数据隔离**：学生只能看到自己的答题记录，教师只能看到自己发布的场次，通过 `session.owner_id = current_user.id` 严格过滤。
7. **现有 Web 端零影响**：所有新增接口使用新 Blueprint 前缀（`/api/mp/`、`/api/sessions/`、`/api/answers/`），不修改现有接口，Web 端正常使用不受任何影响。

### 14.3 上线前核查清单

- [ ] `.env` 中 `WX_MP_APPID` 和 `WX_MP_SECRET` 已填写
- [ ] `BASE_URL` 设置为真实 HTTPS 域名
- [ ] 微信公众平台已添加服务器 `request` / `downloadFile` / `uploadFile` 域名
- [ ] 生产数据库已开启 WAL 模式
- [ ] 新增 4 张表在生产库已创建（`factory._migrate_db()` 执行成功）
- [ ] `PyJWT` 已加入 `requirements.txt`
- [ ] HTTPS 证书有效（Let's Encrypt 或商业证书）
- [ ] 小程序已通过真机测试（iOS + Android）
- [ ] 现有 Web 端功能回归测试通过
