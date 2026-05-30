"""
全局配置 - 从环境变量加载
"""
import os
import tempfile
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
IS_VERCEL = bool(os.getenv("VERCEL"))


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "")
    if value is None or str(value).strip() == "":
        return default
    return int(value)


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name, "")
    if value is None or str(value).strip() == "":
        return default
    return str(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "")
    if value is None or str(value).strip() == "":
        return default
    return float(value)


FLASK_HOST = _env_str("FLASK_HOST", "127.0.0.1")
FLASK_PORT = _env_int("FLASK_PORT", 5000)
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "true").lower() == "true"

# JWT
JWT_SECRET = os.getenv("JWT_SECRET", "ai-learning-secret-change-in-production")
JWT_EXPIRE_DAYS = _env_int("JWT_EXPIRE_DAYS", 7)

# 日志
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 数据目录（环境变量中相对路径以 BASE_DIR 为基准）
_DEFAULT_DATA_DIR = Path(tempfile.gettempdir()) / "ai-learning-assistant" if IS_VERCEL else BASE_DIR / "data"
DATA_DIR = Path(os.getenv("DATA_DIR", str(_DEFAULT_DATA_DIR)))
if not DATA_DIR.is_absolute():
    DATA_DIR = BASE_DIR / DATA_DIR
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(DATA_DIR / "uploads")))
if not UPLOAD_DIR.is_absolute():
    UPLOAD_DIR = BASE_DIR / UPLOAD_DIR
VECTOR_DB_DIR = Path(os.getenv("VECTOR_DB_DIR", str(DATA_DIR / "vector_db")))
if not VECTOR_DB_DIR.is_absolute():
    VECTOR_DB_DIR = BASE_DIR / VECTOR_DB_DIR
CHROMA_HOST = _env_str("CHROMA_HOST", "127.0.0.1")
CHROMA_PORT = _env_int("CHROMA_PORT", 8000)
CHROMA_SSL = os.getenv("CHROMA_SSL", "false").lower() in ("1", "true", "yes", "on")
REPORT_DIR = Path(os.getenv("REPORT_DIR", str(DATA_DIR / "reports")))
if not REPORT_DIR.is_absolute():
    REPORT_DIR = BASE_DIR / REPORT_DIR
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "learning.db")))
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = BASE_DIR / DATABASE_PATH
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("SUPABASE_DB_URL")
    or ""
)
DB_BACKEND = _env_str("DB_BACKEND", "postgres" if DATABASE_URL else "sqlite").lower()
DB_SSLMODE = _env_str("DB_SSLMODE", "require")

# 向量数据库
VECTOR_INDEX_ENABLED = os.getenv(
    "VECTOR_INDEX_ENABLED",
    "true" if DB_BACKEND == "postgres" else ("false" if IS_VERCEL else "true")
).lower() in ("1", "true", "yes", "on")
VECTOR_BACKEND = _env_str(
    "VECTOR_BACKEND",
    "pgvector" if DB_BACKEND == "postgres" else ("chroma" if VECTOR_INDEX_ENABLED else "none")
).lower()
CHUNK_SIZE = _env_int("CHUNK_SIZE", 500)
CHUNK_OVERLAP = _env_int("CHUNK_OVERLAP", 50)
RAG_ENGINE = _env_str("RAG_ENGINE", "langchain").lower()
RAG_TOP_K = _env_int("RAG_TOP_K", 8)
RAG_SCORE_THRESHOLD = _env_float("RAG_SCORE_THRESHOLD", 0.3)
RAG_CONTEXT_MAX_CHARS = _env_int("RAG_CONTEXT_MAX_CHARS", 12000)

# Embedding 模型：优先使用本地目录（离线），其次在线下载
_LOCAL_MINI_LM = BASE_DIR / "embedding_model" / "all-MiniLM-L6-v2"
_LOCAL_BGE = BASE_DIR / "embedding_model" / "bge-large-zh-v1.5"
_DEFAULT_EMBEDDING = str(_LOCAL_BGE) if _LOCAL_BGE.exists() else (str(_LOCAL_MINI_LM) if _LOCAL_MINI_LM.exists() else "all-MiniLM-L6-v2")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", _DEFAULT_EMBEDDING)
EMBEDDING_API_KEY = _env_str("EMBEDDING_API_KEY", _env_str("OPENAI_API_KEY", ""))
EMBEDDING_BASE_URL = _env_str("EMBEDDING_BASE_URL", _env_str("OPENAI_BASE_URL", "https://api.openai.com/v1"))
EMBEDDING_API_MODEL = _env_str("EMBEDDING_API_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSION = _env_int("EMBEDDING_DIMENSION", 1536)

# 确保目录存在
for d in [UPLOAD_DIR, VECTOR_DB_DIR, REPORT_DIR, DATA_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 每周报告生成时间（周几，0=周一）
REPORT_WEEKDAY = _env_int("REPORT_WEEKDAY", 0)
NEWS_FETCH_TIMEOUT = _env_int("NEWS_FETCH_TIMEOUT", 15)

# PDF parser. Use PDF_PARSER=mineru to parse PDFs through MinerU Agent API.
PDF_PARSER = os.getenv("PDF_PARSER", "pymupdf").strip().lower()
MINERU_API_BASE = os.getenv("MINERU_API_BASE", "https://mineru.net/api/v1/agent").rstrip("/")
MINERU_API_TOKEN = os.getenv("MINERU_API_TOKEN", "")
MINERU_LANGUAGE = os.getenv("MINERU_LANGUAGE", "ch")
MINERU_ENABLE_TABLE = os.getenv("MINERU_ENABLE_TABLE", "true").lower() in ("1", "true", "yes", "on")
MINERU_ENABLE_FORMULA = os.getenv("MINERU_ENABLE_FORMULA", "true").lower() in ("1", "true", "yes", "on")
MINERU_IS_OCR = os.getenv("MINERU_IS_OCR", "false").lower() in ("1", "true", "yes", "on")
MINERU_TIMEOUT = _env_int("MINERU_TIMEOUT", 300)
MINERU_POLL_INTERVAL = _env_int("MINERU_POLL_INTERVAL", 3)
