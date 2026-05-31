# AI 学习助手 - 产品 PM 专版

面向产品经理的个人 AI 学习助手。它可以把文档、图片和资讯沉淀为可检索的知识库，并围绕这些资料完成问答、测评、进度追踪和学习报告生成。

## 在线访问

- 网站地址：[https://ai-learning-assistant-amber.vercel.app/](https://ai-learning-assistant-amber.vercel.app/)
- 本地入口：[http://127.0.0.1:5000](http://127.0.0.1:5000)

## 核心功能

- **资料库**：上传 PDF、PPT、Word、Markdown、TXT 和图片，自动解析并入库。
- **知识问答**：基于上传资料进行 RAG 问答，支持流式输出。
- **知识测评**：围绕指定资料生成测评题，记录得分和掌握情况。
- **学习进度**：查看学习统计、知识点掌握度和历史记录。
- **学习报告**：自动生成周学习报告，并支持 Markdown 下载。
- **AI 资讯**：聚合 AI 相关资讯，也可手动录入文章链接。
- **内容采集**：可对接 MediaCrawler 服务采集外部内容，默认关闭。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 前端 | 原生 HTML / CSS / JavaScript SPA |
| 后端 | Python Flask |
| 鉴权 | JWT |
| 数据库 | SQLite，本地开发默认；PostgreSQL / Supabase，可选 |
| 向量检索 | ChromaDB，本地默认；pgvector，可选 |
| RAG | LangChain + OpenAI-compatible API |
| 文档解析 | PyMuPDF、python-pptx、python-docx、Markdown |
| 部署 | Vercel Flask Runtime |

## 快速开始

### 1. 安装依赖

```bash
cd ai-learning-assistant
pip install -r requirements.txt
```

### 2. 配置环境变量

复制环境变量模板：

```bash
copy .env.example .env
```

至少需要配置文本模型 API：

```env
LLM_API_KEY=你的 API Key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

如果要启用图片理解、图片 OCR 或多模态资料解析，还需要配置：

```env
MULTIMODAL_API_KEY=你的多模态 API Key
MULTIMODAL_BASE_URL=https://open.bigmodel.cn/api/paas/v4
MULTIMODAL_MODEL=glm-4.6v
```

### 3. 启动项目

Windows 可以直接运行：

```bat
start.bat
```

也可以用命令行启动：

```bash
python backend/app.py
```

启动后访问 [http://127.0.0.1:5000](http://127.0.0.1:5000)。

## 目录结构

```text
ai-learning-assistant/
├── app.py                    # Vercel / Flask 入口适配
├── backend/                  # Flask 后端
│   ├── app.py                # 应用入口、静态页面服务、健康检查
│   ├── routes/               # API 路由
│   ├── services/             # 文档解析、RAG、测评、报告等业务逻辑
│   ├── models/               # 数据库初始化和 DAO
│   ├── middleware/           # JWT 鉴权
│   └── migrations/           # 数据库迁移脚本
├── frontend/                 # 原生 JS 单页应用
│   ├── index.html
│   ├── css/
│   └── js/
├── data/                     # 本地运行数据，自动生成
├── eval/                     # RAG 评测数据和脚本
├── scripts/                  # 辅助脚本
├── tests/                    # 单元测试和集成测试
├── config.py                 # 全局配置
├── requirements.txt          # 本地开发依赖
├── requirements-vercel.txt   # Vercel 部署依赖
└── vercel.json               # Vercel 构建配置
```

## 常用配置

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `LLM_API_KEY` | 文本模型 API Key | 空 |
| `LLM_BASE_URL` | 文本模型接口地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | 文本模型名称 | `deepseek-chat` |
| `MULTIMODAL_API_KEY` | 多模态模型 API Key | 空 |
| `DATABASE_URL` | PostgreSQL / Supabase 连接串 | 空，默认 SQLite |
| `DB_BACKEND` | 数据库后端 | 有 `DATABASE_URL` 时为 `postgres`，否则为 `sqlite` |
| `VECTOR_BACKEND` | 向量检索后端 | `chroma` 或 `pgvector` |
| `FLASK_PORT` | 本地服务端口 | `5000` |
| `JWT_SECRET` | JWT 密钥 | 开发默认值，生产环境必须修改 |

## 测试

```bash
pytest
```

## 部署

项目已经包含 Vercel 配置：

```json
{
  "installCommand": "pip install -r requirements-vercel.txt"
}
```

部署前请在 Vercel 项目环境变量中配置生产可用的 `LLM_API_KEY`、`JWT_SECRET`、数据库连接和向量检索相关配置。

## 说明

- `.env` 存放 API Key 和本地配置，不要提交到仓库。
- 本地开发默认使用 SQLite 和 ChromaDB，适合快速试用。
- 线上部署建议使用 PostgreSQL / Supabase，并把 `JWT_SECRET` 改成随机强密钥。
