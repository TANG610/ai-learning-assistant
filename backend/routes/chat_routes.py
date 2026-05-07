"""
API 路由 - 对话问答（含 SSE 流式输出）
"""
import json
from flask import Blueprint, request, jsonify, Response, stream_with_context, g
from services.claude_service import LLMService
from services.document_service import DocumentService
from models.database import (
    ConversationDAO, ProgressDAO, KnowledgeDAO, StudySessionDAO, DocumentDAO, get_db
)
from backend.middleware.auth import require_auth

chat_bp = Blueprint("chat", __name__)
llm_service = LLMService()


@chat_bp.route("/api/conversations", methods=["GET"])
@require_auth
def list_conversations():
    convs = ConversationDAO.get_all(user_id=g.user_id)
    return jsonify({"conversations": convs})


@chat_bp.route("/api/conversations", methods=["POST"])
@require_auth
def create_conversation():
    data = request.get_json() or {}
    title = data.get("title", "新对话")
    document_id = data.get("document_id")
    conv_id = ConversationDAO.create(title, document_id, user_id=g.user_id)
    return jsonify({"id": conv_id, "title": title}), 201


@chat_bp.route("/api/conversations/<int:conv_id>", methods=["GET"])
@require_auth
def get_conversation(conv_id):
    messages = ConversationDAO.get_messages(conv_id)
    return jsonify({"messages": messages, "total": len(messages)})


@chat_bp.route("/api/conversations/<int:conv_id>", methods=["DELETE"])
@require_auth
def delete_conversation(conv_id):
    ConversationDAO.delete(conv_id)
    return jsonify({"status": "deleted"})


@chat_bp.route("/api/conversations/<int:conv_id>/messages", methods=["POST"])
@require_auth
def send_message(conv_id):
    """
    发送消息并获取AI回复（支持流式输出）

    请求体: {"message": "...", "document_id": 123, "stream": true}
    """
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "缺少 message 参数"}), 400

    user_message = data["message"]
    document_id = data.get("document_id")
    use_stream = data.get("stream", False)

    # RAG 检索
    context_chunks = []
    sources_meta = []
    if document_id:
        search_results = DocumentService.search_documents(user_message, document_id, top_k=5, user_id=g.user_id)
        # 分离：LLM 需要纯文本，前端需要结构化元数据
        for item in search_results:
            if item["score"] > 0.3:
                context_chunks.append(item["text"])
                sources_meta.append({
                    "doc_id": item.get("doc_id"),
                    "doc_name": _get_doc_name(item.get("doc_id")),
                    "chunk_index": item.get("chunk_index"),
                    "score": item["score"],
                    "preview": item["text"][:120].replace("\n", " "),
                    "content": item["text"]
                })

    if use_stream:
        return _stream_response(conv_id, user_message, document_id, context_chunks, sources_meta)
    else:
        return _normal_response(conv_id, user_message, document_id, context_chunks, sources_meta)


def _get_doc_name(doc_id):
    """根据文档 ID 查文档文件名"""
    if not doc_id:
        return "未知文档"
    try:
        doc = DocumentDAO.get_by_id(doc_id)
        if not doc:
            return f"文档{doc_id}"
        # 兼容：部分表有 title 字段，部分只有 filename
        return doc.get("title") or doc.get("filename") or f"文档{doc_id}"
    except Exception:
        return f"文档{doc_id}"


def _normal_response(conv_id, user_message, document_id, context_chunks, sources_meta):
    """非流式响应"""
    reply = llm_service.chat(conv_id, user_message, context_chunks, user_id=g.user_id)

    if document_id:
        ProgressDAO.update(document_id, status="in_progress")
        ProgressDAO.record_question(document_id)
        StudySessionDAO.create(document_id, session_type="qa", questions=1, user_id=g.user_id)

    return jsonify({
        "reply": reply,
        "sources": sources_meta,
        "source_count": len(sources_meta)
    })


def _stream_response(conv_id, user_message, document_id, context_chunks, sources_meta):
    """SSE 流式响应"""
    def generate():
        full_reply = ""
        try:
            for chunk in llm_service.chat_stream(conv_id, user_message, context_chunks, user_id=g.user_id):
                full_reply += chunk
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'done': True, 'sources': sources_meta}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        # 更新进度
        if document_id:
            ProgressDAO.update(document_id, status="in_progress")
            ProgressDAO.record_question(document_id)
            StudySessionDAO.create(document_id, session_type="qa", questions=1, user_id=g.user_id)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@chat_bp.route("/api/conversations/<int:conv_id>/title", methods=["PUT"])
@require_auth
def update_conversation_title(conv_id):
    data = request.get_json() or {}
    title = data.get("title", "")
    if not title:
        return jsonify({"error": "标题不能为空"}), 400
    ConversationDAO.update_title(conv_id, title)
    return jsonify({"status": "updated"})


@chat_bp.route("/api/practice/generate", methods=["POST"])
@require_auth
def generate_practice():
    data = request.get_json() or {}
    document_id = data.get("document_id")
    topic = data.get("topic", "")
    count = data.get("count", 5)
    difficulty = data.get("difficulty", "mixed")

    context = ""
    if document_id:
        results = DocumentService.search_documents(topic, document_id, top_k=10, user_id=g.user_id)
        context = "\n\n".join([item["text"] for item in results])

    result = llm_service.generate_practice_questions(topic, context, count, difficulty)

    if document_id:
        StudySessionDAO.create(document_id, session_type="practice", user_id=g.user_id)

    return jsonify({"content": result})
