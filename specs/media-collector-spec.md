# MediaCrawler 集成规范 (SDD v1.0)

> **状态**: 待评审
> **日期**: 2026-05-18
> **作者**: Senior Developer
> **方法**: 规范驱动开发 (Specification-Driven Development)

---

## 1. 项目概述

### 1.1 目标
将开源社群数据采集工具 **MediaCrawler** 集成为 AI 学习助手的外部数据引擎，实现：
- 从 Redis 书 / 抖音按关键词自动化采集 AI PM 相关碎片化知识
- 采集结果自动映射到现有的知识库（ChromaDB + SQLite）
- 前端提供采集源管理和执行入口

### 1.2 关键约束
| 约束 | 说明 |
|------|------|
| 已有基础 | 复用 `news_service.py`、`document_service.py`、`news_articles` 表 |
| 独立进程 | MediaCrawler 作为独立 FastAPI 服务运行，Flask 后端通过 HTTP 调用 |
| 无代码入侵 | 不修改 MediaCrawler 源码，只调用其 REST API |
| 需扫码登录 | MediaCrawler 依赖用户自己的 Chrome 和扫码 / Cookie 登录 |

---

## 2. 架构设计

```
┌─────────────────────────────────────────────────────┐
│  用户浏览器 (localhost:5000)                          │
│  ├── 采集中心页（新增）                               │
│  └── 知识流 / 资料库页（增强）                         │
└─────────────┬───────────────────────────────────────┘
              │ HTTP
┌─────────────▼───────────────────────────────────────┐
│  Flask 后端 (localhost:5000)                          │
│  ├── collector_service.py（新增）                     │
│  │   ├── 调用 MediaCrawler API 启动/状态/读取         │
│  │   ├── 结果 → LLM 摘要 → import_text → 入库         │
│  │   └── 已有 import_text 流程完全复用               │
│  ├── collector_routes.py（新增）                      │
│  └── news_service.py（已有，摘要/趋势/整合）          │
└─────────────┬───────────────────────────────────────┘
              │ HTTP
┌─────────────▼───────────────────────────────────────┐
│  MediaCrawler API (localhost:8080)                    │
│  ├── POST /api/crawler/start    启动爬虫              │
│  ├── GET  /api/crawler/status   查询状态              │
│  ├── GET  /api/data/files       列出数据文件           │
│  └── GET  /api/data/files/{p}   读取数据内容           │
└─────────────────────────────────────────────────────┘
```

---

## 3. 数据模型扩展

### 3.1 `news_articles` 表 — 新增字段

```sql
ALTER TABLE news_articles ADD COLUMN media_type TEXT DEFAULT 'text';
-- 值: 'text' | 'video' | 'image_note' | 'mixed'

ALTER TABLE news_articles ADD COLUMN media_url TEXT DEFAULT '';
-- 存储原始资源链接（小红书笔记链接、抖音视频链接等）

ALTER TABLE news_articles ADD COLUMN transcript TEXT DEFAULT '';
-- 预留：视频语音转文字结果（Phase 2 ASR 使用）
```

### 3.2 `rss_sources` 表 — 新增字段

```sql
ALTER TABLE rss_sources ADD COLUMN source_platform TEXT DEFAULT 'rss';
-- 值: 'rss' | 'xhs' | 'douyin' | 'manual' | 'xhs_api' | 'douyin_api'
```

### 3.3 `news_articles.source_type` 枚举值扩展

已有值: `manual`, `rss`, `digest`
新增值: `xhs_api`, `douyin_api`

### 3.4 新增表: `media_sources`（采集源配置）

```sql
CREATE TABLE media_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,               -- 来源名称，如 "AI产品经理-小红书"
    platform TEXT NOT NULL,           -- 'xhs' | 'douyin'
    crawler_type TEXT DEFAULT 'search', -- 'search' | 'creator'
    keywords TEXT DEFAULT '',         -- 搜索关键词，逗号分隔（search 模式用）
    creator_ids TEXT DEFAULT '',      -- 博主 URL/ID，逗号分隔（creator 模式用）
    login_type TEXT DEFAULT 'qrcode', -- 'qrcode' | 'cookie'
    cookies TEXT DEFAULT '',          -- Cookie 字符串（可选）
    enable_comments BOOLEAN DEFAULT 1,-- 是否采集评论
    max_results INTEGER DEFAULT 20,   -- 每次采集最大条数
    is_active BOOLEAN DEFAULT 1,      -- 是否启用
    last_fetched_at TEXT,             -- 最后采集时间
    article_count INTEGER DEFAULT 0,  -- 累计采集条数
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

**采集模式说明**：

| crawler_type | 使用字段 | 说明 |
|-------------|---------|------|
| `search` | `keywords` | 按关键词搜索平台内容 |
| `creator` | `creator_ids` | 采集指定博主的全部内容（支持 URL / 短链 / 纯 ID） |

### 3.5 MediaCrawler 数据 → `news_articles` 字段映射

#### 小红书 (xhs)

| MediaCrawler 字段 | news_articles 字段 | 说明 |
|-------------------|-------------------|------|
| `note_id` | `url` | 构造为 `xhs://note/{note_id}` |
| `title` | `title` | 笔记标题 |
| `desc` | `content` | 笔记正文 |
| `nickname` | `source_name` | 作者昵称 |
| `type` (normal/video) | `media_type` | 内容类型 |
| `video_url` / `image_list` | `media_url` | 媒体资源链接（JSON） |
| `tag_list` | `topics` (JSON 追加) | 话题标签 |
| `source_keyword` | `topics` (JSON 追加) | 搜索关键词 |
| `note_url` | 保留在 content 头部 | 原始链接引用 |

#### 抖音 (douyin)

| MediaCrawler 字段 | news_articles 字段 | 说明 |
|-------------------|-------------------|------|
| `aweme_id` | `url` | 构造为 `dy://video/{aweme_id}` |
| `title` + `desc` | `title` / `content` | 标题 + 视频描述 |
| `nickname` | `source_name` | 作者昵称 |
| `aweme_type` | `media_type` | 内容类型 |
| `video_download_url` | `media_url` | 视频下载链接 |
| `source_keyword` | `topics` (JSON 追加) | 搜索关键词 |

---

## 4. API 端点设计

### 4.1 采集源管理 — `/api/collect/sources`

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| `GET` | `/api/collect/sources` | 是 | 列出当前用户所有采集源 |
| `POST` | `/api/collect/sources` | 是 | 新增采集源 |
| `PUT` | `/api/collect/sources/<id>` | 是 | 更新采集源 |
| `DELETE` | `/api/collect/sources/<id>` | 是 | 删除采集源 |
| `GET` | `/api/collect/sources/<id>/stats` | 是 | 采集源统计（采集次数/条数/最后时间） |

**POST /api/collect/sources 请求体**:
```json
// 模式1：关键词搜索
{
  "name": "AI产品经理-小红书",
  "platform": "xhs",
  "crawler_type": "search",
  "keywords": "AI产品经理,大模型应用,AI面试",
  "login_type": "qrcode",
  "max_results": 20,
  "enable_comments": false
}

// 模式2：指定博主采集
{
  "name": "某AI博主-抖音",
  "platform": "douyin",
  "crawler_type": "creator",
  "creator_ids": "https://www.douyin.com/user/MS4wLjABAAAAxxx",
  "max_results": 30,
  "enable_comments": false
}
```

### 4.2 采集执行 — `/api/collect/tasks`

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| `POST` | `/api/collect/tasks/start` | 是 | 启动采集任务（指定 source_id） |
| `GET` | `/api/collect/tasks/status` | 是 | 当前采集状态 |
| `POST` | `/api/collect/tasks/stop` | 是 | 停止采集 |
| `GET` | `/api/collect/tasks/import` | 是 | 导入最近一次采集结果到知识库 |
| `GET` | `/api/collect/health` | 是 | MediaCrawler 服务健康检查 |

**POST /start 请求体**:
```json
{
  "source_id": 1
}
```

**GET /status 响应体**:
```json
{
  "status": "idle",
  "source_name": "AI产品经理-小红书",
  "started_at": "2026-05-18T15:30:00",
  "crawled_count": 20,
  "logs": ["..."]
}
```

### 4.3 导出复用 — 已有的 `/api/news/` 端点

采集结果导入后成为 `news_articles`，**无需新增端点**，复用：
- `GET /api/news/articles` — 浏览已采集内容（可过滤 source_type=xhs_api）
- `GET /api/news/articles/<id>/save-to-library` — 单篇保存到知识库
- `POST /api/news/digest` — AI 生成采集摘要
- `GET /api/news/trends` — 趋势检测

---

## 5. 核心服务 — `collector_service.py` 行为规范

### 5.1 类结构

```python
class CollectorService:
    """
    MediaCrawler 采集服务

    职责:
    1. 封装对 MediaCrawler API 的 HTTP 调用
    2. 管理采集生命周期（启动 → 轮询 → 完成 → 导入）
    3. 采集结果 → LLM 摘要 → 知识库入库
    """

    MC_BASE_URL = "http://localhost:8080"

    async def health_check() -> bool
    async def start_crawl(source_id: int) -> dict
    async def get_status() -> dict
    def stop_crawl() -> bool
    async def import_results() -> dict
```

### 5.2 `start_crawl` 行为

1. 从 DB 读取 `media_source` 配置
2. 根据 `crawler_type` 构造不同的 MediaCrawler 请求：
   - `search` 模式：传 `keywords` 字段
   - `creator` 模式：传 `creator_ids` 字段（MediaCrawler 自动解析 URL/短链/纯 ID）
3. 发送到 MediaCrawler `POST /api/crawler/start`
4. 记录 `last_fetched_at` 时间戳
5. 返回启动结果

### 5.3 `get_status` 行为

1. 调用 MediaCrawler `GET /api/crawler/status`
2. 如果 `status == "idle"` 且之前为 `"running"`，说明采集完成
3. 自动触发 `import_results`

### 5.4 `import_results` 行为 (核心流程)

1. 调用 `GET /api/data/files?platform={xhs|douyin}` 获取结果文件列表
2. 读取最新 JSONL 文件内容
3. 对每条结果：
   a. 根据映射表构造 `news_articles` 行
   b. 调用已有的 `news_service.summarize_article()` 生成 AI 摘要（3 句摘要 + 关键点 + 主题标签）
   c. 调用已有的 `DocumentService.import_text()` 进入 RAG 流水线（分块 → 向量化 → 入库）
   d. 写入 `news_articles` 表
4. 更新 `media_source.article_count`
5. 返回导入统计（成功/失败/重复数）

### 5.5 错误处理

| 场景 | 行为 |
|------|------|
| MediaCrawler 未启动 | 返回 `health: false`，前端提示"MediaCrawler 服务未运行" |
| 采集超时 | 5 分钟超时，返回部分结果 |
| 结果文件不存在 | 返回空列表 |
| 单条笔记重复 (`url` UNIQUE) | 跳过，记录 skip_count |
| LLM 摘要失败 | 降级：用 content 前 200 字做摘要 |

---

## 6. 前端页面设计

### 6.1 采集中心页 — `#/collect`

```
┌─────────────────────────────────────────────┐
│  📡 AI PM 资源采集中心                        │
│                                             │
│  ┌─ 采集源配置 ───────────────────────────┐ │
│  │ [RSS: 机器之心] [RSS: 量子位] ...        │ │
│  │ [小红书: AI面试经验] [抖音: AI产品拆解]    │ │
│  │ [+ 新增采集源]                           │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  ┌─ 采集控制 ──────────────────────────────┐│
│  │ 当前任务: 无                             ││
│  │ [启动一键采集]  [停止]                    ││
│  │ 状态: ⬤ idle   最后采集: 2026-05-18      ││
│  └────────────────────────────────────────┘ │
│                                             │
│  ┌─ 采集历史 ──────────────────────────────┐│
│  │ 05-18 15:30 | 小红书·AI面试 | 20条 | ✅  ││
│  │ 05-17 10:00 | RSS·机器之心 | 5条  | ✅  ││
│  │ [查看详情]                               ││
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

### 6.2 复用已有页面增强

| 页面 | 改动 |
|------|------|
| 知识流 `#/news`（已是 `news_routes.py`） | 无改动，采集结果自动汇入 |
| 资料库 `#/library` | 增加 `source_type` 筛选下拉框 |

---

## 7. 实施步骤

| 步骤 | 内容 | 依赖 |
|------|------|------|
| S1 | 创建数据库迁移 `003_add_collector_fields.sql` | 无 |
| S2 | 更新 `database.py` — 新增 `MediaSourceDAO` + 表 DDL | S1 |
| S3 | 实现 `collector_service.py` | S2 |
| S4 | 实现 `collector_routes.py` | S3 |
| S5 | 在 `app.py` 注册 Blueprint | S4 |
| S6 | 实现前端 `pages/collect.js` | S4 |
| S7 | 更新前端路由 `app.js` + `index.html` | S6 |
| S8 | 联调测试 | S7 |

---

## 8. 测试用例

### 8.1 单元测试

| ID | 场景 | 预期 |
|----|------|------|
| T1 | `health_check` 时 MediaCrawler 在线 | 返回 `True` |
| T2 | `health_check` 时 MediaCrawler 离线 | 返回 `False`，不抛异常 |
| T3 | `import_results` 无数据文件 | 返回 0 导入 |
| T4 | `import_results` URL 重复 | skip，不 crash |
| T5 | 小红书数据映射 | 字段正确映射到 news_articles |

### 8.2 集成测试

| ID | 场景 | 预期 |
|----|------|------|
| T6 | 完整流程：启动采集 → 状态轮询 → 导入 → 查库 | 20 条笔记出现在 news_articles 中 |
| T7 | 导入后 RAG 可检索 | 对话中能搜到导入的小红书内容 |

---

## 9. 不做的内容

- ❌ 不修改 MediaCrawler 源码
- ❌ 不实现真正的"定时自动采集"（Phase 2，需要用户常驻登录态）
- ❌ 不实现 ASR 语音转文字（Phase 2）
- ❌ 不实现浏览器插件（Phase 5）
- ❌ 不接入 TikHub / 新红 / 飞瓜 API

---

## 10. 风险

| 风险 | 缓解措施 |
|------|---------|
| MediaCrawler 扫码登录需要人工介入 | 前端提示引导用户扫码；采集任务间保持浏览器会话 |
| 小红书/抖音风控导致采集中断 | 单次采集量控制在 20 条以内；有错误日志 |
| MediaCrawler 版本更新 API 变化 | 仅用 4 个稳定 API 接口，变化风险低 |
