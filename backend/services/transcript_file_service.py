"""
文字稿文件保存服务 — 将 news_articles 的 content/transcript 保存为 Markdown 文件

用途：数据备份 + 为后续 LLM 整理提供文件基础
"""
import re
from datetime import datetime
from pathlib import Path

import config

# 文字稿保存目录
TRANSCRIPTS_DIR = config.DATA_DIR / "transcripts"


def _sanitize_filename(text: str, max_len: int = 20) -> str:
    """将标题转为安全文件名片段：去特殊字符、限长度"""
    # 去除 emoji 和特殊字符，保留中文/英文/数字/下划线
    clean = re.sub(r'[^\w\u4e00-\u9fff]', '', text)
    return clean[:max_len] if clean else "untitled"


def _build_frontmatter(data: dict) -> str:
    """构建 YAML frontmatter"""
    lines = ["---"]
    lines.append(f"id: {data.get('id', '')}")
    safe_title = data.get('title', '').replace('"', '\\"')
    lines.append(f'title: "{safe_title}"')
    lines.append(f"source: {data.get('source_name', '')}")
    lines.append(f"type: {data.get('media_type', 'text')}")
    url = data.get('url', '')
    if url:
        lines.append(f"url: {url}")
    fetched = data.get('fetched_at', '')
    if fetched:
        lines.append(f"fetched_at: {fetched}")
    lines.append("---")
    return "\n".join(lines)


def save_transcript_file(
    article_id: int,
    title: str,
    source_name: str = "",
    media_type: str = "text",
    url: str = "",
    fetched_at: str = "",
    content: str = "",
    transcript: str = "",
) -> Path | None:
    """
    将一条 news_article 的内容保存为 Markdown 文件。

    Args:
        article_id: 文章 ID
        title: 文章标题
        source_name: 来源名称
        media_type: 媒体类型 text/image/video
        url: 原始链接
        fetched_at: 采集时间
        content: 文章正文（图片帖的 OCR 文本 / 视频的描述+标签+文字稿）
        transcript: ASR 转录文字稿（仅视频有）

    Returns:
        保存的文件路径，或 None（无内容可保存时）
    """
    # 如果两者都为空，不写文件
    if not content and not transcript:
        return None

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    # 文件名: id_{id}_{标题前20字符}.md
    safe_title = _sanitize_filename(title)
    filename = f"id_{article_id}_{safe_title}.md"
    filepath = TRANSCRIPTS_DIR / filename

    # 构建 frontmatter
    frontmatter = _build_frontmatter({
        "id": article_id,
        "title": title,
        "source_name": source_name,
        "media_type": media_type,
        "url": url,
        "fetched_at": fetched_at,
    })

    # 构建正文
    parts = [frontmatter, ""]

    if transcript:
        parts.append("## 原始文字稿\n")
        parts.append(transcript)
        parts.append("")

    if content and content != transcript:
        # content 可能包含 RAG 拼接内容，与 transcript 不同
        label = "正文内容" if media_type == "text" else "正文内容（含 OCR / RAG 拼接）"
        parts.append(f"## {label}\n")
        parts.append(content)
        parts.append("")

    # LLM 整理稿占位
    parts.append("## LLM 整理稿\n")
    parts.append("<!-- 待处理 -->")

    filepath.write_text("\n".join(parts), encoding="utf-8")
    return filepath
