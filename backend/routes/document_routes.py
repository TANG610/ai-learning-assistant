"""
API 路由 - 文档管理
"""
import os
import hashlib
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request, jsonify, g
import config
from services.document_service import DocumentService
from models.database import DocumentDAO, get_db
from backend.middleware.auth import require_auth
from backend.utils.logger import log


document_bp = Blueprint("document", __name__)
executor = ThreadPoolExecutor(max_workers=2)

# 文档处理进度追踪（内存缓存）
_doc_progress = {}

# 文件分类
TEXT_EXTS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".md", ".markdown", ".txt"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
ALLOWED_EXTS = TEXT_EXTS | IMAGE_EXTS


@document_bp.route("/api/documents", methods=["GET"])
@require_auth
def list_documents():
    docs = DocumentDAO.get_all(user_id=g.user_id)
    return jsonify({"documents": docs, "total": len(docs)})


@document_bp.route("/api/documents/<int:doc_id>", methods=["GET"])
@require_auth
def get_document(doc_id):
    doc = DocumentDAO.get_by_id(doc_id)
    if not doc:
        return jsonify({"error": "文档不存在"}), 404

    # 查询文档分块
    conn = get_db()
    rows = conn.execute(
        "SELECT id, chunk_index, content, title_path, length(content) as char_count FROM document_chunks WHERE document_id = ? ORDER BY chunk_index",
        (doc_id,)
    ).fetchall()
    conn.close()

    chunks = []
    for r in rows:
        chunks.append({
            "id": r["id"],
            "chunk_index": r["chunk_index"],
            "title_path": r["title_path"] or "",
            "content": r["content"],
            "char_count": r["char_count"]
        })

    return jsonify({
        "document": doc,
        "chunks": chunks,
        "chunk_count": len(chunks)
    })


@document_bp.route("/api/documents/upload", methods=["POST"])
@require_auth
def upload_document():
    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "文件名为空"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        return jsonify({"error": f"不支持的文件格式: {ext}"}), 400

    # 判断文件类别
    file_category = "multimodal" if ext in IMAGE_EXTS else "text"

    try:
        file_hash, file_size = _hash_upload_stream(file)
        duplicate = _find_duplicate_upload(file.filename, file_size, file_hash, g.user_id)
        if duplicate:
            return jsonify({
                "error": "该文件已存在于知识库中，请勿重复上传",
                "duplicate_document": {
                    "id": duplicate["id"],
                    "filename": duplicate["filename"],
                    "status": duplicate["status"],
                    "chunk_count": duplicate.get("chunk_count", 0),
                }
            }), 409

        file_path, file_type, file_size = DocumentService.save_upload(file, file.filename, user_id=g.user_id)
        doc_id = DocumentDAO.create(file.filename, file_type, file_path, file_size, user_id=g.user_id, file_category=file_category)

        # Vercel functions may stop background threads after the response.
        DocumentDAO.update_status(doc_id, "processing")
        _doc_progress[doc_id] = {"status": "processing", "stage": "parsing", "stage_label": "正在解析文档...", "progress_pct": 10}
        if config.IS_VERCEL:
            _process_in_background(doc_id)
        else:
            executor.submit(_process_in_background, doc_id)

        return jsonify({
            "id": doc_id,
            "filename": file.filename,
            "file_type": file_type,
            "file_size": file_size,
            "status": "processing"
        }), 201

    except Exception as e:
        log.error(f"文档上传失败: {e}")
        return jsonify({"error": str(e)}), 500


def _hash_upload_stream(file):
    """Return sha256 and size for an uploaded file, then rewind its stream."""
    hasher = hashlib.sha256()
    size = 0
    stream = file.stream
    stream.seek(0)
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        hasher.update(chunk)
        size += len(chunk)
    stream.seek(0)
    return hasher.hexdigest(), size


def _find_duplicate_upload(filename, file_size, file_hash, user_id):
    conn = get_db()
    if user_id is not None:
        rows = conn.execute(
            "SELECT id, filename, file_path, file_size, status, chunk_count "
            "FROM documents WHERE user_id = ? AND file_size = ?",
            (user_id, file_size),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, filename, file_path, file_size, status, chunk_count "
            "FROM documents WHERE user_id IS NULL AND file_size = ?",
            (file_size,),
        ).fetchall()
    conn.close()

    for row in rows:
        path = row["file_path"]
        if path and os.path.exists(path) and _file_sha256(path) == file_hash:
            return dict(row)
    return None


def _file_sha256(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _process_in_background(doc_id):
    """后台线程处理文档（含进度上报）"""
    try:
        log.info(f"后台处理文档 ID={doc_id}")
        _doc_progress[doc_id] = {"status": "processing", "stage": "parsing", "stage_label": "正在解析文档...", "progress_pct": 20}
        result = DocumentService.process_document(doc_id, progress_callback=lambda stage, pct: _update_progress(doc_id, stage, pct))
        if result.get("status") == "parsed":
            _doc_progress[doc_id] = {"status": "parsed", "stage": "done", "stage_label": "解析完成", "progress_pct": 100}
        else:
            _doc_progress[doc_id] = {"status": "error", "stage": "error", "stage_label": str(result.get("error", "未知错误")), "progress_pct": 0}
        log.info(f"文档处理完成 ID={doc_id}: {result.get('status')} {result.get('chunks', 0)}块")
    except Exception as e:
        log.error(f"后台处理文档失败 ID={doc_id}: {e}")
        _doc_progress[doc_id] = {"status": "error", "stage": "error", "stage_label": str(e), "progress_pct": 0}


def _update_progress(doc_id, stage, pct):
    _doc_progress[doc_id] = {"status": "processing", "stage": stage, "stage_label": stage, "progress_pct": pct}


def _queue_reparse_document(doc):
    doc_id = int(doc["id"])
    DocumentDAO.update_status(doc_id, "processing", chunk_count=doc.get("chunk_count", 0) or 0)
    _doc_progress[doc_id] = {
        "status": "processing",
        "stage": "queued",
        "stage_label": "重新解析已排队...",
        "progress_pct": 5,
    }
    executor.submit(_process_in_background, doc_id)
    return doc_id


def _get_reparse_candidates(user_id):
    docs = DocumentDAO.get_all(user_id=user_id)
    return [doc for doc in docs if doc.get("status") != "processing"]


@document_bp.route("/api/documents/<int:doc_id>", methods=["DELETE"])
@require_auth
def delete_document(doc_id):
    # 校验文档归属当前用户
    doc = DocumentDAO.get_by_id(doc_id)
    if not doc:
        return jsonify({"error": "文档不存在"}), 404
    if doc.get("user_id") and doc["user_id"] != g.user_id:
        return jsonify({"error": "无权删除此文档"}), 403
    result = DocumentService.delete_document(doc_id)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@document_bp.route("/api/documents/<int:doc_id>/progress", methods=["GET"])
@require_auth
def document_progress(doc_id):
    progress = _doc_progress.get(doc_id, {"status": "unknown", "stage": "unknown", "stage_label": "无进度信息", "progress_pct": 0})
    return jsonify(progress)


@document_bp.route("/api/documents/reparse-all", methods=["POST"])
@require_auth
def reparse_all_documents():
    candidates = _get_reparse_candidates(g.user_id)
    queued_ids = [_queue_reparse_document(doc) for doc in candidates]
    skipped_processing = len(DocumentDAO.get_all(user_id=g.user_id)) - len(candidates)

    return jsonify({
        "status": "processing" if queued_ids else "noop",
        "queued_count": len(queued_ids),
        "queued_doc_ids": queued_ids,
        "skipped_processing": skipped_processing,
    }), 202


@document_bp.route("/api/documents/<int:doc_id>/reparse", methods=["POST"])
@require_auth
def reparse_document(doc_id):
    doc = DocumentDAO.get_by_id(doc_id)
    if not doc:
        return jsonify({"error": "文档不存在"}), 404
    if doc.get("user_id") and doc["user_id"] != g.user_id:
        return jsonify({"error": "无权重新解析此文档"}), 403
    if doc.get("status") == "processing":
        return jsonify({"error": "文档正在处理中，请稍后再试"}), 409

    _queue_reparse_document(doc)
    return jsonify({"status": "processing", "doc_id": doc_id}), 202
