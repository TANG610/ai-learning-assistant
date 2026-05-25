"""
全局配置 - 从环境变量加载
"""
import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).parent

# 自动加载 .env 文件（任何方式启动都能读到）
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            # 不覆盖已有的环境变量（系统环境变量优先）
            if key not in os.environ:
                os.environ[key] = value

# ── LLM：DeepSeek（文本模型）──
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))

# ── LLM：多模态模型（视觉理解）──
MULTIMODAL_API_KEY = os.getenv("MULTIMODAL_API_KEY", "")
MULTIMODAL_BASE_URL = os.getenv("MULTIMODAL_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
MULTIMODAL_MODEL = os.getenv("MULTIMODAL_MODEL", "glm-4.6v")

# ── 模型提供商（JSON 数组）──
# 格式: [{"name":"DeepSeek","base_url":"...","api_key":"sk-...","model":"deepseek-v4-flash","type":"text"}, ...]
# 如果设置了此项，将从 JSON 中提取 LLM_API_KEY / MULTIMODAL_API_KEY 等兼容变量
import json as _json
_MODEL_PROVIDERS_RAW = os.getenv("MODEL_PROVIDERS", "")
MODEL_PROVIDERS = []
if _MODEL_PROVIDERS_RAW:
    try:
        MODEL_PROVIDERS = _json.loads(_MODEL_PROVIDERS_RAW)
    except _json.JSONDecodeError:
        MODEL_PROVIDERS = []

# 从 MODEL_PROVIDERS 提取兼容变量（仅在未单独设置时覆盖）
if MODEL_PROVIDERS:
    for p in MODEL_PROVIDERS:
        p_type = p.get("type", "text")
        if p_type == "text" and not os.getenv("LLM_API_KEY"):
            os.environ["LLM_API_KEY"] = p.get("api_key", "")
            os.environ["LLM_BASE_URL"] = p.get("base_url", "")
            os.environ["LLM_MODEL"] = p.get("model", "")
            LLM_API_KEY = p.get("api_key", "")
            LLM_BASE_URL = p.get("base_url", "")
            LLM_MODEL = p.get("model", "")
        elif p_type == "multimodal" and not os.getenv("MULTIMODAL_API_KEY"):
            os.environ["MULTIMODAL_API_KEY"] = p.get("api_key", "")
            os.environ["MULTIMODAL_BASE_URL"] = p.get("base_url", "")
            os.environ["MULTIMODAL_MODEL"] = p.get("model", "")
            MULTIMODAL_API_KEY = p.get("api_key", "")
            MULTIMODAL_BASE_URL = p.get("base_url", "")
            MULTIMODAL_MODEL = p.get("model", "")

# ── 可用模型列表 ──
AVAILABLE_MODELS = os.getenv("AVAILABLE_MODELS", LLM_MODEL).split(",")

# 兼容旧配置名
if not LLM_API_KEY and os.getenv("ANTHROPIC_API_KEY"):
    LLM_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Flask
FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "true").lower() == "true"

# JWT
JWT_SECRET = os.getenv("JWT_SECRET", "ai-learning-secret-change-in-production")
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "7"))

# 日志
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 数据目录（环境变量中相对路径以 BASE_DIR 为基准）
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
if not DATA_DIR.is_absolute():
    DATA_DIR = BASE_DIR / DATA_DIR
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(DATA_DIR / "uploads")))
if not UPLOAD_DIR.is_absolute():
    UPLOAD_DIR = BASE_DIR / UPLOAD_DIR
VECTOR_DB_DIR = Path(os.getenv("VECTOR_DB_DIR", str(DATA_DIR / "vector_db")))
if not VECTOR_DB_DIR.is_absolute():
    VECTOR_DB_DIR = BASE_DIR / VECTOR_DB_DIR
CHROMA_HOST = os.getenv("CHROMA_HOST", "127.0.0.1")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
CHROMA_SSL = os.getenv("CHROMA_SSL", "false").lower() in ("1", "true", "yes", "on")
REPORT_DIR = Path(os.getenv("REPORT_DIR", str(DATA_DIR / "reports")))
if not REPORT_DIR.is_absolute():
    REPORT_DIR = BASE_DIR / REPORT_DIR
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "learning.db")))
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = BASE_DIR / DATABASE_PATH

# 向量数据库
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))

# Embedding 模型：优先使用本地目录（离线），其次在线下载
_LOCAL_MINI_LM = BASE_DIR / "embedding_model" / "all-MiniLM-L6-v2"
_LOCAL_BGE = BASE_DIR / "embedding_model" / "bge-large-zh-v1.5"
_DEFAULT_EMBEDDING = str(_LOCAL_BGE) if _LOCAL_BGE.exists() else (str(_LOCAL_MINI_LM) if _LOCAL_MINI_LM.exists() else "all-MiniLM-L6-v2")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", _DEFAULT_EMBEDDING)

# 确保目录存在
for d in [UPLOAD_DIR, VECTOR_DB_DIR, REPORT_DIR, DATA_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 每周报告生成时间（周几，0=周一）
REPORT_WEEKDAY = int(os.getenv("REPORT_WEEKDAY", "0"))
NEWS_FETCH_TIMEOUT = int(os.getenv("NEWS_FETCH_TIMEOUT", "15"))
