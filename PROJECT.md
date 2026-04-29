# AI 学习助手 — 项目文档

## 概要

| 属性 | 值 |
|------|-----|
| 名称 | AI 学习助手 (AI Learning Assistant) |
| 版本 | v2.3 |
| 定位 | 面向 AI 产品经理的 RAG 增强学习助手 |
| 技术栈 | Python Flask + 纯 JS SPA + SQLite + ChromaDB |
| 浏览器入口 | `http://127.0.0.1:5000` |

---

## 架构

```
浏览器 (index.html)
  │
  ├── GET /, /css/*, /js/*               → 前端 SPA
  ├── GET/POST /api/auth/*               → 认证（注册/登录/JWT）
  ├── GET/POST /api/documents/*          → 文档上传/管理
  ├── POST /api/conversations/*          → 对话（RAG + SSE 流式）
  ├── POST /api/assessments/*            → AI 测评
  ├── GET /api/progress/*, /api/reports/* → 学习进度与周报
  ├── GET/POST /api/models/*             → 模型切换
  └── GET/POST /api/settings/providers   → 模型提供商管理
                │
                ▼
         Flask (backend/app.py)
                │
     ┌──────────┼──────────┐
     ▼          ▼          ▼
  SQLite    ChromaDB   外部 LLM API
  (learning.db)  (向量)   ├── DeepSeek (文本)
                         └── 智谱 GLM-4.6V (多模态图片)
```

---

## 目录结构

```
ai-learning-assistant/
│
├── .env                          # 运行时环境变量（含 API Key，不提交）
├── .env.example                  # 环境变量模板
├── .gitignore
├── config.py                     # 全局配置（手动解析 .env）
├── requirements.txt              # Python 依赖
├── start.bat                     # Windows 启动脚本
├── README.md                     # 旧版说明
├── 使用说明.md                    # 用户手册
├── CLAUDE.md                     # Claude Code 行为指南
├── PROJECT.md                    # 本文件 — 项目完整文档
│
├── backend/
│   ├── app.py                    # Flask 入口，注册蓝图，健康检查
│   ├── routes/
│   │   ├── auth_routes.py        # /api/auth/* 认证
│   │   ├── document_routes.py    # /api/documents/* 上传/管理
│   │   ├── chat_routes.py        # /api/conversations/* RAG 对话
│   │   ├── quiz_routes.py        # /api/assessments/* AI 测评
│   │   └── progress_routes.py    # /api/progress/* 进度/周报
│   ├── services/
│   │   ├── claude_service.py     # LLM 路由器（多 Provider，RAG，测评，出题）
│   │   ├── document_service.py   # 文档处理（解析→分块→向量化→入库）
│   │   ├── document_parser.py    # 文件解析器（PDF/PPTX/DOCX/MD/TXT）
│   │   ├── vector_store.py       # ChromaDB 向量数据库封装
│   │   └── report_service.py     # 周报生成
│   ├── models/
│   │   └── database.py           # 9 张表 DDL + 9 个 DAO 类
│   ├── middleware/
│   │   └── auth.py               # JWT 认证装饰器
│   ├── utils/
│   │   └── logger.py             # 日志系统
│   └── migrations/
│       ├── 001_add_users.sql     # 用户系统迁移
│       └── 002_add_file_category.sql  # 多模态字段迁移
│
├── frontend/
│   ├── index.html                # SPA 入口
│   ├── css/
│   │   ├── reset.css             # 设计 Token + 重置
│   │   ├── layout.css            # 布局系统
│   │   ├── components.css        # 组件样式
│   │   └── pages.css             # 页面样式
│   └── js/
│       ├── app.js                # Hash 路由
│       ├── api.js                # HTTP 请求封装（含 SSE 流式）
│       ├── auth.js               # 登录/注册 UI + token 管理
│       ├── utils.js              # 工具函数
│       ├── components.js         # 可复用 UI 组件
│       └── pages/
│           ├── chat.js           # 对话页
│           ├── library.js        # 资料库页
│           ├── quiz.js           # 测评页
│           ├── progress.js       # 学习进度页
│           ├── report.js         # 学习报告页
│           └── settings.js       # 设置页
│
├── data/
│   ├── learning.db               # SQLite 数据库
│   ├── uploads/                  # 上传文件（按 user_id 分目录）
│   ├── vector_db/                # ChromaDB 持久化
│   └── reports/                  # 生成的周报 MD
│
├── embedding_model/
│   └── all-MiniLM-L6-v2/         # 本地 Embedding 模型（384 维）
│
└── tests/
    ├── conftest.py
    └── unit/
        └── test_dao.py           # DAO 单元测试
```

---

## 环境变量 / 配置

由 `config.py` 从 `.env` 加载，关键变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | `""` | 文本模型 API Key |
| `LLM_BASE_URL` | `https://api.deepseek.com` | 文本模型地址 |
| `LLM_MODEL` | `deepseek-chat` | 文本模型名 |
| `LLM_MAX_TOKENS` | `4096` | 最大 token 数 |
| `MULTIMODAL_API_KEY` | `""` | 多模态模型 API Key |
| `MULTIMODAL_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | 多模态模型地址 |
| `MULTIMODAL_MODEL` | `glm-4.6v` | 多模态模型名 |
| `MODEL_PROVIDERS` | `[]` | JSON 数组，多 Provider 配置 |
| `AVAILABLE_MODELS` | `LLM_MODEL` | 前端可选模型（逗号分隔） |
| `FLASK_HOST` | `127.0.0.1` | 监听地址 |
| `FLASK_PORT` | `5000` | 监听端口 |
| `JWT_SECRET` | `ai-learning-secret-change-in-production` | JWT 密钥 |
| `JWT_EXPIRE_DAYS` | `7` | Token 过期天数 |
| `EMBEDDING_MODEL` | 本地 `embedding_model/` 优先 | 嵌入模型路径 |
| `CHUNK_SIZE` | `500` | 文本分块大小 |
| `CHUNK_OVERLAP` | `50` | 分块重叠量 |

`MODEL_PROVIDERS` 格式：
```json
[
  {
    "name": "DeepSeek V4 Flash",
    "base_url": "https://api.deepseek.com",
    "api_key": "sk-xxx",
    "model": "deepseek-v4-flash",
    "type": "text"
  },
  {
    "name": "智谱 GLM-4.6V",
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "api_key": "xxx",
    "model": "glm-4.6v",
    "type": "multimodal"
  }
]
```

---

## 数据库表结构

共 12 张表，均由 `init_db()` 创建：

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `users` | 用户账户 | id, username, email, password_hash |
| `user_settings` | 用户偏好 | user_id, preferences(JSON) |
| `documents` | 文档元数据 | id, filename, file_type, file_path, file_size, status, file_category, ocr_text, user_id |
| `document_chunks` | 文本分块 | id, document_id, chunk_index, content, vector_id, user_id |
| `conversations` | 对话会话 | id, title, document_id, user_id |
| `messages` | 对话消息 | id, conversation_id, role, content, source_chunks(JSON), user_id |
| `learning_progress` | 学习进度 | id, document_id, status, confidence_score, question_count, user_id |
| `study_sessions` | 学习记录 | id, document_id, session_type, duration_minutes, questions_asked, user_id |
| `knowledge_points` | 知识点掌握 | id, document_id, topic, mastery_level, encounter_count, correct_count, user_id |
| `weekly_reports` | 周报 | id, week_start, week_end, content, file_path, user_id |
| `assessments` | 测评会话 | id, document_id, status, score, correct_count, knowledge_summary, user_id |
| `assessment_questions` | 测评题目 | id, assessment_id, question_type, options, correct_answer, user_answer, is_correct, user_id |

---

## API 端点

### 认证 `/api/auth`
| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/auth/register` | 否 | 注册，返回 JWT |
| POST | `/api/auth/login` | 否 | 登录，返回 JWT |
| POST | `/api/auth/refresh` | 是 | 刷新 token |
| GET | `/api/auth/me` | 是 | 当前用户信息 |
| GET | `/api/auth/user/settings` | 是 | 获取偏好设置 |
| PUT | `/api/auth/user/settings` | 是 | 更新偏好设置 |

### 文档 `/api/documents`
| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/documents` | 是 | 文档列表 |
| GET | `/api/documents/<id>` | 是 | 文档详情+分块 |
| POST | `/api/documents/upload` | 是 | 上传（form-data） |
| DELETE | `/api/documents/<id>` | 是 | 级联删除 |
| GET | `/api/documents/<id>/progress` | 是 | 处理进度 |
| POST | `/api/documents/<id>/reparse` | 是 | 重新解析 |

支持格式：`.pdf .pptx .ppt .docx .doc .md .markdown .txt .jpg .jpeg .png .webp .bmp .gif`
图片文件标记为 `file_category: "multimodal"`，上传后自动调用视觉模型分析。

### 对话 `/api/conversations`
| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/conversations` | 是 | 对话列表 |
| POST | `/api/conversations` | 是 | 创建新对话 |
| GET | `/api/conversations/<id>` | 是 | 获取消息 |
| DELETE | `/api/conversations/<id>` | 是 | 删除对话 |
| POST | `/api/conversations/<id>/messages` | 是 | 发送消息（支持 SSE 流式） |
| PUT | `/api/conversations/<id>/title` | 是 | 修改标题 |
| POST | `/api/practice/generate` | 是 | 生成练习题 |

SSE 流式格式：`data: {"chunk":"..."}\n\n`，结束：`data: {"done":true}\n\n`

### 测评 `/api/assessments`
| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/assessments` | 是 | 创建测评 |
| GET | `/api/assessments/<id>` | 是 | 测评详情 |
| POST | `/api/assessments/<id>/submit` | 是 | 提交答案 |
| GET | `/api/assessments/<id>/status` | 是 | 处理状态 |
| GET | `/api/assessments/history` | 是 | 历史记录 |

### 进度与报告
| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/progress` | 是 | 文档级进度 |
| GET | `/api/progress/stats` | 是 | 总体统计 |
| GET | `/api/progress/overview` | 是 | 学习概览 |
| GET | `/api/progress/calendar` | 是 | 90 天热力图 |
| GET | `/api/progress/mastery` | 是 | 五级掌握度 |
| POST | `/api/study-session` | 是 | 记录学习时长 |
| GET | `/api/knowledge/weak` | 是 | 薄弱知识点 |
| POST | `/api/knowledge/encounter` | 是 | 记录知识点遇 |
| GET | `/api/knowledge/mastery` | 是 | 知识点详情 |
| POST | `/api/reports/generate` | 是 | 生成周报 |
| GET | `/api/reports` | 是 | 报告列表 |
| GET | `/api/reports/<id>` | 是 | 报告详情 |
| GET | `/api/reports/<id>/download` | 是 | 下载 MD |

### 系统
| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/health` | 否 | 健康检查 |
| GET | `/api/models` | 是 | 可用模型列表 |
| POST | `/api/models/switch` | 是 | 切换模型 |
| GET | `/api/settings/providers` | 是 | 模型提供商列表 |
| POST | `/api/settings/providers` | 是 | 更新提供商配置 |

---

## 核心服务说明

### LLMService (`backend/services/claude_service.py`)
别名 `ClaudeService`。多 Provider 路由器：
- 从 `MODEL_PROVIDERS` JSON 构建多个 OpenAI-compatible 客户端
- 支持 `text` 和 `multimodal` 两种 Provider 类型
- 自动切换模型（`set_model` / 全局 `_current_global_model`）
- RAG 增强对话（上下文片段注入 system prompt）
- 网络异常自动重试（2s/4s/6s）
- SSE 流式输出
- 系统提示词定位为"AI 产品经理学习助手"

### DocumentService (`backend/services/document_service.py`)
文档全生命周期管理：
1. 保存上传文件到 `data/uploads/{user_id}/`
2. 异步处理：解析 → 分块 → 向量化 → 入库
3. 图片文件调用 `chat_with_image` 视觉模型分析
4. 视觉模型不可用时写友好回退文本（不含特定模型名称）
5. 级联删除：文件 + ChromaDB collection + SQLite 记录

### VectorStore (`backend/services/vector_store.py`)
单例模式 ChromaDB 封装：
- 延迟加载 SentenceTransformer 嵌入模型
- 按用户隔离 collection：`user_{user_id}_doc_{doc_id}`
- 批量化写入（100 条/批）
- 余弦距离语义搜索

### 前端路由（Hash SPA）
| Hash | 页面 | 模块 |
|------|------|------|
| `#/chat` | 对话 | `pages/chat.js` |
| `#/library` | 资料库 | `pages/library.js` |
| `#/progress` | 学习进度 | `pages/progress.js` |
| `#/report` | 学习报告 | `pages/report.js` |
| `#/quiz` | 测评 | `pages/quiz.js` |
| `#/settings` | 设置 | `pages/settings.js` |
| `#/login` | 登录 | `auth.js` |
| `#/register` | 注册 | `auth.js` |

---

## 启动方式

### Windows
```bat
start.bat
```
或手动：
```bash
pip install -r requirements.txt
python backend/app.py
```

### 默认账号
注册页面创建新用户，所有数据按用户隔离。

---

## 五级掌握度体系

| 等级 | 标识 | 颜色 | 条件 |
|------|------|------|------|
| L0 | 未接触 | gray | 0 次测评 |
| L1 | 入门 | amber | >=1 次测评，>=60分 |
| L2 | 熟悉 | blue | >=2 次测评，>=80分 |
| L3 | 精通 | green | >=3 次测评，>=90分 |
| L4 | 专家 | purple | >=3 次测评，>=90分 |

---

## 关键设计决策

1. **多 Provider 架构** — 通过 `MODEL_PROVIDERS` JSON 同时支持多个 LLM，可在设置页热切换
2. **用户数据隔离** — 所有表含 `user_id`，ChromaDB collection 按用户分
3. **异步文档处理** — `ThreadPoolExecutor` 后台处理，前端轮询进度
4. **本地 Embedding** — 使用 `all-MiniLM-L6-v2` 和 `bge-small-zh-v1.5` 离线嵌入
5. **SSE 流式** — 对话页实时渲染 AI 回复
6. **前端零框架** — 纯 JS SPA，基于 `window.location.hash` 路由
7. **杂志风格 UI** — 暖色系，衬线标题字体 Bodoni Moda，ECharts 图表
8. **SQLite + ChromaDB 双数据库** — 结构化数据 + 向量语义搜索
