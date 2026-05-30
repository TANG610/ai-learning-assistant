"""
MediaCrawler 集成采集服务 — 小红书/抖音内容自动化采集、摘要与入库

架构: Flask 后端 ←HTTP→ MediaCrawler 独立服务 (localhost:8080)
数据流: 采集 → JSONL读取 → LLM摘要(复用news_service) → import_text() → 分块 → 向量化 → ChromaDB入库
"""
import json
import os
import re
import time
import threading
import uuid
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests

import config
from models.database import (
    CollectorTaskDAO,
    MediaSourceDAO,
    NewsDAO,
    RawCollectedItemDAO,
    get_db,
)
from services.news_service import NewsService
from services.document_service import DocumentService
from services.ocr_service import OcrService
from services.transcription_service import TranscriptionService
from services.transcript_file_service import save_transcript_file
from backend.utils.logger import log

# MediaCrawler API 地址
MEDIACRAWLER_BASE = os.getenv("MEDIACRAWLER_URL", "http://localhost:8080")
MEDIACRAWLER_ENABLED = os.getenv("MEDIACRAWLER_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
MEDIACRAWLER_DISABLED_MESSAGE = "MediaCrawler is temporarily disabled."
MEDIACRAWLER_TIMEOUT = int(os.getenv("MEDIACRAWLER_TIMEOUT", "300"))  # 爬虫启动超时(秒)
MIN_VIDEO_TRANSCRIPT_CHARS = int(os.getenv("MIN_VIDEO_TRANSCRIPT_CHARS", "30"))
MEDIACRAWLER_VIDEO_WAIT_SECONDS = int(os.getenv("MEDIACRAWLER_VIDEO_WAIT_SECONDS", "600"))
MEDIACRAWLER_VIDEO_WAIT_INTERVAL = int(os.getenv("MEDIACRAWLER_VIDEO_WAIT_INTERVAL", "5"))
MEDIACRAWLER_IMAGE_WAIT_SECONDS = int(os.getenv("MEDIACRAWLER_IMAGE_WAIT_SECONDS", "60"))
MEDIACRAWLER_DATA_DIR = Path(os.getenv(
    "MEDIACRAWLER_DATA_DIR",
    str((config.BASE_DIR.parent / "MediaCrawler" / "data").resolve())
))

# 平台名称映射: 项目内部名称 → MediaCrawler API 名称
PLATFORM_MAP = {
    "xhs": "xhs", "xiaohongshu": "xhs",
    "douyin": "dy", "dy": "dy", "tiktok": "dy",
    "kuaishou": "ks", "ks": "ks",
    "bilibili": "bili", "bili": "bili",
    "weibo": "wb", "wb": "wb",
}

# 后台任务状态追踪
_collect_tasks = {}
_executor = ThreadPoolExecutor(max_workers=2)
_task_lock = threading.Lock()


class CollectorService:
    """MediaCrawler 采集协调服务"""

    @staticmethod
    def _default_progress() -> dict:
        return {
            "stage": "crawling",
            "stage_index": 0,
            "total_records": 0,
            "processed_records": 0,
            "current_record_title": "",
        }

    @staticmethod
    def _new_run_id() -> str:
        return f"run_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _task_from_store(task_id: str) -> dict | None:
        task = _collect_tasks.get(task_id)
        if task:
            return task
        task = CollectorTaskDAO.get(task_id)
        if task:
            task.setdefault("progress", CollectorService._default_progress())
            task.setdefault("errors", [])
            task.setdefault("result_files", [])
            _collect_tasks[task_id] = task
        return task

    @staticmethod
    def _persist_task(task_id: str, **updates):
        task = _collect_tasks.get(task_id)
        if task:
            task.update(updates)
        CollectorTaskDAO.update(task_id, **updates)

    @staticmethod
    def _update_progress(task_id: str, **updates):
        task = CollectorService._task_from_store(task_id)
        if not task:
            return
        progress = dict(task.get("progress") or CollectorService._default_progress())
        progress.update(updates)
        task["progress"] = progress
        CollectorTaskDAO.update(task_id, progress=progress)

    @staticmethod
    def _record_title(record: dict) -> str:
        return str(
            record.get("title")
            or record.get("desc")
            or record.get("note_title")
            or record.get("video_desc")
            or "未命名"
        )[:200]

    @staticmethod
    def _record_content(record: dict) -> str:
        return str(
            record.get("content")
            or record.get("note_content")
            or record.get("desc")
            or record.get("video_desc")
            or ""
        )

    @staticmethod
    def _record_url(record: dict, platform: str, source_name: str = "") -> str:
        media_id = CollectorService._record_media_id(record, platform)
        return str(
            record.get("note_url")
            or record.get("aweme_url")
            or record.get("share_url")
            or record.get("video_url")
            or record.get("url")
            or (f"{platform}://{media_id}" if media_id else f"{platform}://{source_name}/{int(time.time())}")
        )

    # ═══════════ MediaCrawler API 交互 ═══════════

    @staticmethod
    def _call_crawler_api(method: str, endpoint: str, json_data: dict = None) -> dict:
        """调用 MediaCrawler API 通用方法"""
        if not MEDIACRAWLER_ENABLED:
            return {
                "status": "disabled",
                "disabled": True,
                "error": MEDIACRAWLER_DISABLED_MESSAGE,
            }

        url = f"{MEDIACRAWLER_BASE}{endpoint}"
        try:
            if method.upper() == "GET":
                resp = requests.get(url, timeout=30)
            else:
                resp = requests.post(url, json=json_data, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError:
            log.error(f"无法连接 MediaCrawler 服务 ({MEDIACRAWLER_BASE})，请确保已启动")
            return {"error": "MediaCrawler 服务未运行，请先启动 MediaCrawler"}
        except requests.Timeout:
            return {"error": "MediaCrawler 服务响应超时"}
        except Exception as e:
            log.error(f"MediaCrawler API 调用失败: {endpoint} | {e}")
            return {"error": str(e)}

    @staticmethod
    def get_crawler_status() -> dict:
        """查询 MediaCrawler 服务状态"""
        if not MEDIACRAWLER_ENABLED:
            return {
                "status": "disabled",
                "disabled": True,
                "message": MEDIACRAWLER_DISABLED_MESSAGE,
            }
        return CollectorService._call_crawler_api("GET", "/api/crawler/status")

    @staticmethod
    def list_data_files() -> list:
        """列出 MediaCrawler 已生成的数据文件"""
        result = CollectorService._call_crawler_api("GET", "/api/data/files")
        if result.get("error"):
            return []
        return result.get("files", result if isinstance(result, list) else [])

    @staticmethod
    def read_data_file(file_path: str) -> list:
        """
        读取 MediaCrawler 输出的数据文件（JSON/JSONL），通过 API 获取。

        MediaCrawler API /api/data/files/{path} 返回:
          {"data": [{...}, ...], "total": N}  (preview 模式)
          或直接返回 JSON 数组 / JSONL 文本

        Returns: [{title, content, url, ...}, ...]
        """
        full_url = f"{MEDIACRAWLER_BASE}/api/data/files/{file_path}?preview=true"
        try:
            resp = requests.get(full_url, timeout=30)
            resp.raise_for_status()

            # 尝试解析为 JSON
            try:
                body = resp.json()
            except Exception:
                # 非 JSON 响应，尝试按 JSONL 解析
                raw = resp.text.strip()
                if not raw:
                    return []
                records = []
                for line in raw.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        log.warning(f"JSONL 行解析失败: {line[:100]}")
                return records

            # 处理 structured response: {"data": [...], "total": N}
            if isinstance(body, dict) and "data" in body:
                return body["data"] if isinstance(body["data"], list) else []

            # 直接是列表
            if isinstance(body, list):
                return body

            # 单条记录
            if isinstance(body, dict):
                return [body]

            return []
        except Exception as e:
            log.error(f"读取数据文件失败: {file_path} | {e}")
            return []

    @staticmethod
    def start_crawl(source_id: int, user_id: int = None) -> dict:
        """
        启动 MediaCrawler 采集任务。

        Args:
            source_id: media_sources 表中的采集源ID
            user_id: 用户ID

        Returns:
            {"status": "started", "task_id": str}
        """
        source = MediaSourceDAO.get_by_id(source_id)
        if not source:
            return {"error": "采集源不存在"}

        if not MEDIACRAWLER_ENABLED:
            return {
                "status": "disabled",
                "disabled": True,
                "error": MEDIACRAWLER_DISABLED_MESSAGE,
            }

        platform = source["platform"]
        crawler_type = source["crawler_type"]

        # 将内部平台名映射为 MediaCrawler API 名称 (douyin → dy)
        api_platform = PLATFORM_MAP.get(platform.lower(), platform)

        # 构建 MediaCrawler 请求（匹配 CrawlerStartRequest schema）
        payload = {
            "platform": api_platform,
            "login_type": source.get("login_type", "qrcode"),
            "crawler_type": crawler_type,
            "cookies": source.get("cookies", ""),
            "enable_comments": bool(source.get("enable_comments", 1)),
            "enable_get_medias": True,
            "save_option": "jsonl",
            "start_page": 1,
            "max_notes": max(1, int(source.get("max_results") or 1)),
            "headless": False,  # 抖音博主页采集用真实浏览器窗口更稳定
        }
        if crawler_type == "search":
            keywords = source.get("keywords", "")
            if not keywords:
                return {"error": "关键词搜索模式下 keywords 不能为空"}
            payload["keywords"] = keywords
        elif crawler_type == "creator":
            creator_ids = source.get("creator_ids", "")
            if not creator_ids:
                return {"error": "博主采集模式下 creator_ids 不能为空"}
            payload["creator_ids"] = creator_ids
        elif crawler_type == "detail":
            specified_ids = source.get("creator_ids") or source.get("keywords") or ""
            if not specified_ids:
                return {"error": "detail mode requires a video URL or ID"}
            payload["specified_ids"] = specified_ids

        log.info(f"启动采集任务: {source['name']} (platform={platform}, type={crawler_type})")

        # 调用 MediaCrawler 启动接口
        result = CollectorService._call_crawler_api(
            "POST", "/api/crawler/start", json_data=payload
        )

        if result.get("error"):
            return result

        # 记录后台任务。task_id/run_id 每次运行唯一，避免同一个采集源多次任务互相覆盖。
        run_id = CollectorService._new_run_id()
        task_id = run_id
        started_ts = time.time()
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        progress = CollectorService._default_progress()
        task_payload = {
            "task_id": task_id,
            "run_id": run_id,
            "status": "running",
            "source_id": source_id,
            "source_name": source["name"],
            "platform": platform,
            "crawler_type": crawler_type,
            "user_id": user_id,
            "started_at": started_at,
            "started_ts": started_ts,
            "crawler_result": result,
            "progress": progress,
            "errors": [],
            "result_files": [],
        }
        CollectorTaskDAO.create(
            task_id=task_id,
            run_id=run_id,
            source_id=source_id,
            user_id=user_id,
            source_name=source["name"],
            platform=platform,
            crawler_type=crawler_type,
            started_ts=started_ts,
            started_at=started_at,
            crawler_result=result,
            progress=progress,
        )
        with _task_lock:
            _collect_tasks[task_id] = task_payload

        # 更新最后采集时间
        MediaSourceDAO.update(source_id, last_fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        return {
            "status": "started",
            "task_id": task_id,
            "run_id": run_id,
            "source_name": source["name"],
            "platform": platform,
            "crawler_type": crawler_type,
        }

    @staticmethod
    def get_collect_status(task_id: str = None, user_id: int = None) -> dict:
        """查询采集任务状态"""
        if task_id:
            task = CollectorService._task_from_store(task_id)
            if not task:
                return {"status": "not_found"}
            if user_id is not None and task.get("user_id") != user_id:
                return {"status": "not_found"}
            # 同时查询 MediaCrawler 底层状态
            if task.get("status") in {"running", "pending"}:
                task = dict(task)
                task["crawler_status"] = CollectorService.get_crawler_status()
            return task

        # 返回所有任务
        stored_tasks = CollectorTaskDAO.list(user_id=user_id, statuses=["running", "pending"], limit=20)
        for task in stored_tasks:
            _collect_tasks.setdefault(task["task_id"], task)
        return {
            "tasks": [
                {
                    "task_id": t["task_id"],
                    "run_id": t.get("run_id"),
                    "source_id": t.get("source_id"),
                    "source_name": t["source_name"],
                    "status": t["status"],
                    "platform": t["platform"],
                }
                for t in stored_tasks
            ]
        }

    # ═══════════ 数据导入 ═══════════

    @staticmethod
    def stop_crawl(task_id: str = None) -> dict:
        """Stop MediaCrawler and mark tracked collector tasks as stopped."""
        result = CollectorService._call_crawler_api("POST", "/api/crawler/stop")
        stopped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with _task_lock:
            if task_id and task_id in _collect_tasks:
                _collect_tasks[task_id]["status"] = "stopped"
                _collect_tasks[task_id]["stopped_at"] = stopped_at
                _collect_tasks[task_id]["stop_result"] = result
                CollectorTaskDAO.update(
                    task_id,
                    status="stopped",
                    stopped_at=stopped_at,
                    crawler_result=result,
                    error=result.get("error", ""),
                )
            elif not task_id:
                for tid, task in _collect_tasks.items():
                    if task.get("status") == "running":
                        task["status"] = "stopped"
                        task["stopped_at"] = stopped_at
                        task["stop_result"] = result
                        CollectorTaskDAO.update(
                            tid,
                            status="stopped",
                            stopped_at=stopped_at,
                            crawler_result=result,
                            error=result.get("error", ""),
                        )
                for task in CollectorTaskDAO.list(statuses=["running"], limit=100):
                    CollectorTaskDAO.update(
                        task["task_id"],
                        status="stopped",
                        stopped_at=stopped_at,
                        crawler_result=result,
                        error=result.get("error", ""),
                    )

        if result.get("error"):
            return {"status": "stopped", "warning": result.get("error"), "task_id": task_id}
        return {"status": "stopped", "task_id": task_id, "crawler_result": result}

    @staticmethod
    def import_from_crawl(task_id: str, user_id: int = None) -> dict:
        """
        读取采集结果并导入知识库（由前端/定时任务调用）。

        流程: 读取JSONL → 原始记录落表 → 逐条整理/ASR/摘要 → 入ChromaDB

        Returns:
            {"imported": int, "skipped": int, "errors": [str]}
        """
        task = CollectorService._task_from_store(task_id)
        if not task:
            return {"error": "采集任务不存在"}

        source_id = task["source_id"]
        if not MEDIACRAWLER_ENABLED:
            return {
                "status": "disabled",
                "disabled": True,
                "error": MEDIACRAWLER_DISABLED_MESSAGE,
            }

        source = MediaSourceDAO.get_by_id(source_id)
        if not source:
            return {"error": "采集源不存在"}

        def _set_source_last_import_count(count: int) -> int:
            count = max(0, int(count or 0))
            MediaSourceDAO.update(source_id, article_count=count)
            return count

        def _finish_empty_import(errors: list[str]) -> dict:
            last_import_count = _set_source_last_import_count(0)
            completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with _task_lock:
                if task_id in _collect_tasks:
                    _collect_tasks[task_id]["status"] = "completed"
                    _collect_tasks[task_id]["imported"] = 0
                    _collect_tasks[task_id]["skipped"] = 0
                    _collect_tasks[task_id]["errors"] = errors
                    _collect_tasks[task_id]["article_count"] = last_import_count
                    _collect_tasks[task_id]["completed_at"] = completed_at
            CollectorTaskDAO.update(
                task_id,
                status="completed",
                completed_at=completed_at,
                imported=0,
                skipped=0,
                errors=errors,
                article_count=last_import_count,
            )
            return {"imported": 0, "skipped": 0, "errors": errors, "source_name": source["name"], "article_count": last_import_count}

        # 优先使用已绑定到本 run_id 的结果文件；首次导入时再从 MediaCrawler 文件列表发现。
        bound_files = task.get("result_files") or []
        files = [{"path": path, "name": Path(path).name, "modified_at": task.get("started_ts", 0)} for path in bound_files]
        if not files:
            files = CollectorService.list_data_files()
            if not files:
                return _finish_empty_import(["没有找到数据文件，采集可能还未完成"])

        # 筛选相关文件（按平台过滤）
        # files 是 dict 列表: [{"name": ..., "path": ..., "type": ...}, ...]
        platform = source["platform"]
        api_platform = PLATFORM_MAP.get(platform.lower(), platform)
        platform_aliases = {
            "dy": {"dy", "douyin"},
            "douyin": {"dy", "douyin"},
            "xhs": {"xhs", "xiaohongshu"},
            "xiaohongshu": {"xhs", "xiaohongshu"},
        }.get(api_platform.lower(), {api_platform.lower()})

        def _is_target_file(file_info: dict) -> bool:
            path = str(file_info.get("path", "")).replace("\\", "/").lower()
            name = str(file_info.get("name", "")).lower()
            combined = f"{path}/{name}"
            if "comment" in combined:
                return False
            if "content" not in combined and "search" not in combined:
                return False
            return any(
                combined.startswith(f"{alias}/")
                or f"/{alias}_" in combined
                or f"{alias}_" in name
                for alias in platform_aliases
            )

        started_ts = float(task.get("started_ts") or 0)
        target_files = [
            f for f in files
            if (
                isinstance(f, dict)
                and _is_target_file(f)
                and (not started_ts or float(f.get("modified_at") or 0) >= started_ts - 60)
            )
        ]
        jsonl_files = [
            f for f in target_files
            if str(f.get("path", "") or f.get("name", "")).lower().endswith(".jsonl")
        ]
        if jsonl_files:
            target_files = jsonl_files
        if not target_files:
            return _finish_empty_import([f"没有找到 {platform} 平台的采集结果文件"])

        result_file_paths = [
            str(f.get("path") if isinstance(f, dict) else f)
            for f in target_files
        ]
        CollectorService._persist_task(task_id, result_files=result_file_paths)

        raw_items = []
        total_records = 0
        for file_info in target_files:
            file_path = file_info.get("path") if isinstance(file_info, dict) else file_info
            records = CollectorService.read_data_file(file_path)
            if not records:
                continue
            total_records += len(records)
            for record_index, record in enumerate(records):
                if not isinstance(record, dict):
                    continue
                title = CollectorService._record_title(record)
                content = CollectorService._record_content(record)
                url = CollectorService._record_url(record, platform, source["name"])
                canonical_id = CollectorService._record_media_id(record, platform) or url
                item_id = RawCollectedItemDAO.create(
                    task_id=task_id,
                    run_id=task.get("run_id") or task_id,
                    source_id=source_id,
                    user_id=user_id,
                    platform=platform,
                    source_name=source["name"],
                    file_path=file_path,
                    record_index=record_index,
                    record=record,
                    canonical_id=canonical_id,
                    url=url,
                    title=title,
                    content=content,
                )
                if item_id:
                    raw_items.append(RawCollectedItemDAO.get(item_id))

        pending_items = [
            item for item in RawCollectedItemDAO.list_by_task(task_id, statuses=["pending", "error"])
            if item
        ]
        if not pending_items and raw_items:
            pending_items = [item for item in raw_items if item and item.get("status") in {"pending", "error"}]

        imported = 0
        skipped = 0
        errors = []
        max_import = int(source.get("max_results") or 1)

        CollectorService._update_progress(
            task_id,
            total_records=total_records,
            stage="asr",
            stage_index=1,
            processed_records=0,
        )

        global_idx = 0

        for raw_item in pending_items:
            record = raw_item.get("record") or {}
            title_hint = raw_item.get("title") or CollectorService._record_title(record)
            CollectorService._update_progress(
                task_id,
                processed_records=global_idx,
                current_record_title=str(title_hint)[:60],
            )

            try:
                result = CollectorService._import_single_record(
                    record=record,
                    source_name=source["name"],
                    platform=platform,
                    user_id=user_id,
                    task_id=task_id,
                    raw_item_id=raw_item["id"],
                )
                if result.get("skipped"):
                    skipped += 1
                    RawCollectedItemDAO.update_status(
                        raw_item["id"], "skipped", skip_reason=result.get("reason", "")
                    )
                elif result.get("error"):
                    errors.append(result["error"])
                    RawCollectedItemDAO.update_status(
                        raw_item["id"], "error", error=result["error"]
                    )
                else:
                    imported += 1
                    RawCollectedItemDAO.update_status(
                        raw_item["id"],
                        "imported",
                        article_id=result.get("article_id"),
                        document_id=result.get("document_id"),
                    )
                    if imported >= max_import:
                        global_idx += 1
                        break
            except Exception as e:
                err = f"导入异常: {e}"
                errors.append(err)
                RawCollectedItemDAO.update_status(raw_item["id"], "error", error=err)

            global_idx += 1
            CollectorService._update_progress(task_id, processed_records=global_idx)
            if imported >= max_import:
                break

        # 更新采集源的上次导入数量，而不是历史累计文章数
        last_import_count = _set_source_last_import_count(imported)

        # 更新任务状态
        completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _task_lock:
            if task_id in _collect_tasks:
                _collect_tasks[task_id]["status"] = "completed"
                _collect_tasks[task_id]["imported"] = imported
                _collect_tasks[task_id]["skipped"] = skipped
                _collect_tasks[task_id]["errors"] = errors
                _collect_tasks[task_id]["article_count"] = last_import_count
                _collect_tasks[task_id]["completed_at"] = completed_at
        CollectorTaskDAO.update(
            task_id,
            status="completed",
            completed_at=completed_at,
            imported=imported,
            skipped=skipped,
            errors=errors,
            article_count=last_import_count,
        )

        log.info(f"采集导入完成: {task['source_name']} — 导入 {imported}, 跳过 {skipped}")

        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "source_name": source["name"],
            "article_count": last_import_count,
        }

    @staticmethod
    def _is_video_record(record: dict) -> bool:
        """判断采集记录是否是视频内容。"""
        note_type = str(record.get("type") or record.get("aweme_type") or "").lower()
        return bool(
            record.get("video_url")
            or record.get("video_play_url")
            or record.get("video_download_url")
            or note_type in {"video", "2", "4"}
        )

    @staticmethod
    def _record_media_id(record: dict, platform: str) -> str:
        platform_key = platform.lower()
        if platform_key in {"douyin", "dy", "tiktok"}:
            return str(record.get("aweme_id") or "").strip()
        if platform_key in {"xhs", "xiaohongshu"}:
            return str(record.get("note_id") or record.get("notice_id") or "").strip()
        return str(record.get("aweme_id") or record.get("note_id") or record.get("id") or "").strip()

    @staticmethod
    def _find_local_video_path(record: dict, platform: str, wait_seconds: int = 0) -> str:
        """Find the video downloaded by MediaCrawler for this record."""
        media_id = CollectorService._record_media_id(record, platform)
        if not media_id:
            return ""

        platform_key = platform.lower()
        if platform_key in {"douyin", "dy", "tiktok"}:
            video_dir = MEDIACRAWLER_DATA_DIR / "douyin" / "videos" / media_id
        elif platform_key in {"xhs", "xiaohongshu"}:
            video_dir = MEDIACRAWLER_DATA_DIR / "xhs" / "videos" / media_id
        else:
            return ""

        deadline = time.time() + max(0, wait_seconds)
        while True:
            if video_dir.exists():
                candidates = sorted(video_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
                if candidates:
                    return str(candidates[0])

            if time.time() >= deadline:
                return ""

            time.sleep(max(1, MEDIACRAWLER_VIDEO_WAIT_INTERVAL))

    @staticmethod
    def _find_local_image_paths(record: dict, platform: str, wait_seconds: int = 0) -> list[str]:
        """Find images downloaded by MediaCrawler for this record."""
        media_id = CollectorService._record_media_id(record, platform)
        if not media_id:
            return []

        platform_key = platform.lower()
        if platform_key in {"xhs", "xiaohongshu"}:
            image_dir = MEDIACRAWLER_DATA_DIR / "xhs" / "images" / media_id
        else:
            return []

        def _sort_key(path: Path):
            try:
                return (0, int(path.stem))
            except ValueError:
                return (1, path.name)

        deadline = time.time() + max(0, wait_seconds)
        while True:
            if image_dir.exists():
                candidates = [
                    p for p in image_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in OcrService.IMAGE_EXTS
                ]
                if candidates:
                    return [str(p) for p in sorted(candidates, key=_sort_key)]

            if time.time() >= deadline:
                return []

            time.sleep(max(1, MEDIACRAWLER_VIDEO_WAIT_INTERVAL))

    @staticmethod
    def _record_image_urls(record: dict) -> list[str]:
        value = record.get("image_list") or record.get("images") or []
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("[") and value.endswith("]"):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    value = [value]
            else:
                value = [item.strip() for item in value.split(",") if item.strip()]

        urls = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    url = item.get("url") or item.get("origin_url") or item.get("trace_id")
                    if url:
                        urls.append(str(url))
                elif item:
                    urls.append(str(item))
        elif value:
            urls.append(str(value))
        return urls

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        seconds = max(0, int(seconds or 0))
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    @staticmethod
    def _format_segments(segments: list, limit: int = 80) -> str:
        lines = []
        for seg in (segments or [])[:limit]:
            ts = CollectorService._format_timestamp(seg.get("start", 0))
            text = str(seg.get("text", "")).strip()
            if text:
                lines.append(f"[{ts}] {text}")
        return "\n".join(lines)

    @staticmethod
    def _extract_tags(record: dict) -> list:
        tags = []
        for key in ["tag_list", "topics", "keywords", "source_keyword"]:
            val = record.get(key)
            if not val:
                continue
            if isinstance(val, list):
                tags.extend(str(v.get("name", v)) if isinstance(v, dict) else str(v) for v in val)
            elif isinstance(val, str):
                if val.startswith("[") and val.endswith("]"):
                    try:
                        parsed = json.loads(val)
                        if isinstance(parsed, list):
                            tags.extend(str(v.get("name", v)) if isinstance(v, dict) else str(v) for v in parsed)
                            continue
                    except (json.JSONDecodeError, TypeError):
                        pass
                tags.extend([item.strip() for item in re.split(r"[,，#\s]+", val) if item.strip()])
            else:
                tags.append(str(val))
        return list(dict.fromkeys(t for t in tags if t))

    @staticmethod
    def _build_video_rag_content(content: str, transcript: str, segments: list, record: dict) -> str:
        parts = []
        desc = (content or "").strip()
        if desc:
            parts.append(f"视频描述:\n{desc}")
        tags = CollectorService._extract_tags(record)
        if tags:
            parts.append(f"标签:\n{', '.join(tags)}")
        if transcript:
            parts.append(f"完整文字稿:\n{transcript}")
        # Timestamped segments repeat the transcript text and are kept for
        # summarization metadata only, not for RAG chunk content.
        return "\n\n".join(parts).strip()

    @staticmethod
    def _build_image_rag_content(content: str, ocr_text: str, record: dict) -> str:
        parts = []
        desc = (content or "").strip()
        if desc:
            parts.append(f"图文笔记正文:\n{desc}")
        tags = CollectorService._extract_tags(record)
        if tags:
            parts.append(f"标签:\n{', '.join(tags)}")
        if ocr_text:
            parts.append(f"图片OCR文字:\n{ocr_text}")
        return "\n\n".join(parts).strip()

    @staticmethod
    def _normalize_key_points(items: list) -> list[str]:
        normalized = []
        for item in items or []:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = str(
                    item.get("point")
                    or item.get("title")
                    or item.get("summary")
                    or item.get("name")
                    or ""
                ).strip()
                if not text:
                    text = json.dumps(item, ensure_ascii=False)
            else:
                text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized

    @staticmethod
    def _import_single_record(record: dict, source_name: str, platform: str,
                               user_id: int = None, task_id: str = None,
                               raw_item_id: int = None) -> dict:
        """
        将单条采集记录导入知识库。

        MediaCrawler 输出字段适配（各平台字段名略有不同）：
        - title / desc / content / note_content / video_desc
        - video_url / note_url / share_url
        - author_name / nickname
        - like_count / comment_count / collected_count
        """
        # 进度更新辅助函数
        def _update_stage(stage: str, stage_index: int, title_hint: str = ""):
            if not task_id:
                return
            updates = {"stage": stage, "stage_index": stage_index}
            if title_hint:
                updates["current_record_title"] = str(title_hint)[:60]
            CollectorService._update_progress(task_id, **updates)

        # 提取标题和正文（适配多平台字段）
        title = (
            record.get("title") or
            record.get("desc") or
            record.get("note_title") or
            record.get("video_desc") or
            "未命名"
        )[:200]

        content = (
            record.get("content") or
            record.get("note_content") or
            record.get("desc") or
            record.get("video_desc") or
            ""
        )

        # 如果正文为空但有点赞/评论等元数据，构造基本信息
        if not content or len(content) < 10:
            # 尝试从其他字段提取有价值信息
            extra_parts = []
            for key in ["tag_list", "topics", "keywords"]:
                val = record.get(key, "")
                if isinstance(val, list):
                    extra_parts.append(" ".join(str(v) for v in val))
                elif isinstance(val, str) and val:
                    # CSV 格式下 list 字段可能是 JSON 字符串，尝试解析
                    if val.startswith("[") and val.endswith("]"):
                        try:
                            parsed = json.loads(val)
                            if isinstance(parsed, list):
                                extra_parts.append(" ".join(str(v) for v in parsed))
                                continue
                        except (json.JSONDecodeError, TypeError):
                            pass
                    extra_parts.append(val)
                elif val:
                    extra_parts.append(str(val))
            content = " ".join(extra_parts) if extra_parts else title

        is_video = CollectorService._is_video_record(record)
        media_type = "video" if is_video else "text"
        media_url = ""
        transcript = ""
        transcript_segments = []
        video_path = ""
        image_ocr_text = ""

        if is_video:
            _update_stage("asr", 1, f"ASR: {title}")
            media_url = (
                record.get("video_url")
                or record.get("video_play_url")
                or record.get("video_download_url")
                or record.get("aweme_url")
                or record.get("note_url")
                or record.get("share_url")
                or ""
            )
            video_path = CollectorService._find_local_video_path(
                record,
                platform,
                wait_seconds=MEDIACRAWLER_VIDEO_WAIT_SECONDS,
            )
            if video_path:
                asr_result = TranscriptionService.transcribe(video_path)
                transcript = asr_result.get("text", "")
                transcript_segments = asr_result.get("segments", [])
            else:
                log.warning(
                    f"Local video not found for ASR: platform={platform}, id={CollectorService._record_media_id(record, platform)}"
                )
        elif record.get("image_list") or record.get("images"):
            media_type = "image"
            image_urls = CollectorService._record_image_urls(record)
            media_url = image_urls[0] if image_urls else ""
            _update_stage("ocr", 1, f"OCR: {title}")
            image_paths = CollectorService._find_local_image_paths(
                record,
                platform,
                wait_seconds=MEDIACRAWLER_IMAGE_WAIT_SECONDS,
            )
            if image_paths:
                ocr_results = OcrService.extract_text_from_images(image_paths, context=title)
                image_ocr_text = OcrService.format_ocr_results(ocr_results)
                transcript = image_ocr_text
                if not image_ocr_text:
                    ocr_errors = [item.get("error") for item in ocr_results if item.get("error")]
                    if ocr_errors:
                        log.warning(
                            f"OCR produced no text: platform={platform}, id={CollectorService._record_media_id(record, platform)}, error={ocr_errors[0]}"
                        )
            else:
                log.warning(
                    f"Local images not found for OCR: platform={platform}, id={CollectorService._record_media_id(record, platform)}"
                )

        if is_video and len(transcript.strip()) < MIN_VIDEO_TRANSCRIPT_CHARS:
            log.warning(
                f"Skip video without transcript: platform={platform}, id={CollectorService._record_media_id(record, platform)}, title={title[:50]}"
            )
            return {"skipped": True, "reason": "视频未生成有效文字稿，跳过入库"}


        # Transcript passed quality check, safe to delete the video
        if video_path:
            TranscriptionService.delete_video_dir(video_path)

        if is_video:
            rag_content = CollectorService._build_video_rag_content(content, transcript, transcript_segments, record)
        elif media_type == "image":
            rag_content = CollectorService._build_image_rag_content(content, image_ocr_text, record)
        else:
            rag_content = content

        if not rag_content or len(rag_content) < 10:
            return {"skipped": True, "reason": "内容为空"}


        # 构造 URL（兼容各平台字段名）
        url = CollectorService._record_url(record, platform, source_name)

        # 去重检查
        existing = NewsDAO.get_by_url(url, user_id=user_id)
        if existing:
            return {"skipped": True, "reason": "URL 已存在"}

        # 作者信息
        author = record.get("author_name") or record.get("nickname") or ""
        if author:
            rag_content = f"作者: {author}\n\n{rag_content}"

        # LLM 摘要
        _update_stage("llm_summary", 2, f"摘要: {title}")
        try:
            if is_video:
                summary_data = NewsService.summarize_video_transcript(
                    title=title,
                    transcript=transcript,
                    desc=content,
                    tags=CollectorService._extract_tags(record),
                    segments=transcript_segments,
                )
            else:
                summary_data = NewsService.summarize_article(title, rag_content)
        except Exception as e:
            log.warning(f"LLM 摘要失败 ({title[:30]}): {e}")
            summary_data = {"summary": "", "key_points": [], "topics": [], "structure": []}

        # 导入文档 (RAG 管道)
        _update_stage("vector_import", 3, f"入库: {title}")
        try:
            doc_result = DocumentService.import_text(
                title=title, content=rag_content, user_id=user_id, file_category="news"
            )
            document_id = doc_result.get("doc_id")
        except Exception as e:
            log.error(f"文档导入失败 ({title[:30]}): {e}")
            return {"error": f"文档导入失败: {e}"}

        # 写入 news_articles
        key_points = summary_data.get("key_points") or summary_data.get("key_takeaways", [])
        if summary_data.get("structure"):
            key_points = summary_data.get("key_takeaways") or summary_data.get("structure")
        key_points = CollectorService._normalize_key_points(key_points)
        key_points_json = json.dumps(key_points, ensure_ascii=False)
        topics_json = json.dumps(summary_data.get("topics", []), ensure_ascii=False)

        source_type_map = {
            "xhs": "xhs_api",
            "xiaohongshu": "xhs_api",
            "douyin": "douyin_api",
            "dy": "douyin_api",
            "tiktok": "douyin_api",
        }
        source_type = source_type_map.get(platform.lower(), "manual")

        # 媒体类型和 URL
        article_id = NewsDAO.create(
            document_id=document_id,
            title=title,
            url=url,
            source_name=source_name,
            source_type=source_type,
            summary=summary_data.get("summary", ""),
            key_points=key_points_json,
            topics=topics_json,
            language="zh",
            user_id=user_id,
            content=rag_content,
        )

        # 更新扩展字段 (media_type, media_url, transcript)
        if media_type != "text" or media_url:
            conn = get_db()
            conn.execute(
                "UPDATE news_articles SET media_type=?, media_url=?, transcript=? WHERE id=?",
                (media_type, media_url, transcript, article_id)
            )
            conn.commit()
            conn.close()

        # 保存文字稿/内容到 Markdown 文件
        try:
            saved_path = save_transcript_file(
                article_id=article_id,
                title=title,
                source_name=source_name,
                media_type=media_type,
                url=url,
                fetched_at=datetime.now().isoformat(),
                content=rag_content,
                transcript=transcript,
            )
            if saved_path:
                log.info(f"文字稿已保存: {saved_path.name}")
        except Exception as e:
            log.warning(f"文字稿保存失败 (id={article_id}): {e}")

        return {
            "article_id": article_id,
            "document_id": document_id,
            "title": title,
            "source_type": source_type,
        }

    # ═══════════ 异步采集 + 自动导入 ═══════════

    @staticmethod
    def collect_and_import_async(source_id: int, user_id: int = None) -> dict:
        """
        后台异步执行：启动采集 → 轮询等待 → 导入数据。

        返回立即返回 task_id，实际工作在后台线程执行。
        状态通过 get_collect_status(task_id) 查询。
        """
        # 先启动采集
        if not MEDIACRAWLER_ENABLED:
            return {
                "status": "disabled",
                "disabled": True,
                "error": MEDIACRAWLER_DISABLED_MESSAGE,
            }

        start_result = CollectorService.start_crawl(source_id, user_id=user_id)
        if start_result.get("error"):
            return start_result

        task_id = start_result["task_id"]

        def _run():
            """后台等待采集完成并导入"""
            max_wait = MEDIACRAWLER_TIMEOUT
            poll_interval = 5
            waited = 0

            while waited < max_wait:
                time.sleep(poll_interval)
                waited += poll_interval

                crawler_status = CollectorService.get_crawler_status()
                # 判断爬虫是否完成（空闲状态或完成标志）
                status_str = str(crawler_status).lower()

                # 更新爬虫阶段进度
                elapsed_min = waited // 60
                CollectorService._update_progress(
                    task_id,
                    stage="crawling",
                    stage_index=0,
                    current_record_title=f"已等待 {elapsed_min} 分钟",
                )

                if "idle" in status_str or "completed" in status_str or "finished" in status_str:
                    break
                if crawler_status.get("error"):
                    with _task_lock:
                        if task_id in _collect_tasks:
                            _collect_tasks[task_id]["status"] = "error"
                            _collect_tasks[task_id]["error"] = crawler_status.get("error")
                    CollectorTaskDAO.update(
                        task_id,
                        status="error",
                        error=crawler_status.get("error"),
                        errors=[crawler_status.get("error")],
                    )
                    return

            # 导入数据
            CollectorService.import_from_crawl(task_id, user_id=user_id)

        _executor.submit(_run)

        return start_result

    # ═══════════ 一键采集所有活跃源 ═══════════

    @staticmethod
    def collect_all_active(user_id: int = None) -> dict:
        """
        串行采集所有活跃的媒体源。

        Returns:
            {"status": "started", "sources": [...], "total": int}
        """
        if not MEDIACRAWLER_ENABLED:
            return {
                "status": "disabled",
                "disabled": True,
                "error": MEDIACRAWLER_DISABLED_MESSAGE,
                "total": 0,
                "tasks": [],
            }

        sources = MediaSourceDAO.get_active(user_id=user_id)
        if not sources:
            return {"status": "completed", "message": "没有活跃的采集源", "total": 0}

        task_ids = []
        for src in sources:
            result = CollectorService.collect_and_import_async(src["id"], user_id=user_id)
            if result.get("task_id"):
                task_ids.append({
                    "task_id": result["task_id"],
                    "source_name": src["name"],
                    "platform": src["platform"],
                })

        return {
            "status": "started",
            "total": len(task_ids),
            "tasks": task_ids,
        }
