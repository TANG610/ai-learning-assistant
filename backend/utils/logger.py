"""
日志系统 - 全局 logging 配置
"""
import logging
import logging.handlers
import os
import tempfile
from pathlib import Path
import config


def setup_logging():
    """初始化全局日志配置"""
    log_dir = Path(tempfile.gettempdir()) / "ai-learning-assistant" / "logs" if os.getenv("VERCEL") else config.BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    # 根 logger
    logger = logging.getLogger("ai_learning")
    logger.setLevel(level)

    # 防止重复添加 handler
    if logger.handlers:
        return logger

    # 格式
    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # 文件（按天轮转，保留 30 天）
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "app.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger


# 模块级 logger（供各模块直接 import）
log = setup_logging()
