"""
API 路由 - 对话问答（含 SSE 流式输出）
"""
import json
from flask import Blueprint, request, jsonify, Response, stream_with_context, g
import config
from services.claude_service import LLMService
from services.document_service import DocumentService
from services.rag_chain_service import RagChainService
from models.database import (
    ConversationDAO, ProgressDAO, KnowledgeDAO, StudySessionDAO, DocumentDAO, get_db
)
from backend.middleware.auth import require_auth
from backend.utils.logger import log

chat_bp = Blueprint("chat", __name__)
llm_service = LLMService()
rag_chain_service = RagChainService(llm_service)
RAG_SCORE_THRESHOLD = config.RAG_SCORE_THRESHOLD
RAG_TOP_K = config.RAG_TOP_K


def _normalize_document_id(value):
    """Return None for all-knowledge searches, otherwise a valid document id."""
    if value in (None, "", "all", "__all__"):
        return None
    try:
        doc_id = int(value)
    except (TypeError, ValueError):
        return None
    return doc_id if doc_id > 0 else None


def _normalize_rag_engine(value):
    return "legacy" if str(value or "").lower() == "legacy" else "langchain"


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
    document_id = _normalize_document_id(data.get("document_id"))
    conv_id = ConversationDAO.create(title, document_id, user_id=g.user_id)
    return jsonify({"id": conv_id, "title": title}), 201


@chat_bp.route("/api/conversations/<int:conv_id>", methods=["GET"])
@require_auth
def get_conversation(conv_id):
    conversation = ConversationDAO.get_by_id(conv_id, user_id=g.user_id)
    if not conversation:
        return jsonify({"error": "对话不存在"}), 404
    messages = ConversationDAO.get_messages(conv_id)
    return jsonify({"conversation": conversation, "messages": messages, "total": len(messages)})


@chat_bp.route("/api/conversations/<int:conv_id>", methods=["DELETE"])
@require_auth
def delete_conversation(conv_id):
    conversation = ConversationDAO.get_by_id(conv_id, user_id=g.user_id)
    if not conversation:
        return jsonify({"error": "对话不存在"}), 404
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
    document_id = _normalize_document_id(data.get("document_id"))
    use_stream = data.get("stream", False)
    rag_engine = _normalize_rag_engine(data.get("rag_engine") or config.RAG_ENGINE)
    conversation = ConversationDAO.get_by_id(conv_id, user_id=g.user_id)
    if not conversation:
        return jsonify({"error": "对话不存在"}), 404

    # RAG 检索
    if rag_engine == "langchain":
        if use_stream:
            return _langchain_stream_response(conv_id, user_message, document_id)
        try:
            result = rag_chain_service.answer(conv_id, user_message, document_id, user_id=g.user_id)
            _record_qa_progress(document_id)
            return jsonify(result)
        except Exception as e:
            log.warning(f"LangChain RAG failed; falling back to legacy RAG: {e}", exc_info=True)
            context_chunks, sources_meta, retrieval_debug = _build_legacy_rag_context(
                user_message,
                document_id,
                fallback_reason=str(e),
            )
            return _normal_response(conv_id, user_message, document_id, context_chunks, sources_meta, retrieval_debug)

    context_chunks = []
    sources_meta = []
    retrieval_debug = {
        "query": user_message,
        "document_id": document_id,
        "search_scope": "all_documents" if document_id is None else "single_document",
        "top_k": RAG_TOP_K,
        "score_threshold": RAG_SCORE_THRESHOLD,
        "rag_engine": "legacy",
        "results": [],
        "accepted_count": 0,
    }
    search_results = DocumentService.search_documents(user_message, document_id, top_k=RAG_TOP_K, user_id=g.user_id)
    # 分离：LLM 需要纯文本，前端需要结构化元数据
    for rank, item in enumerate(search_results, start=1):
        score = item.get("score", 0)
        accepted = score > RAG_SCORE_THRESHOLD
        source = {
            "rank": rank,
            "doc_id": item.get("doc_id"),
            "doc_name": _get_doc_name(item.get("doc_id")),
            "chunk_index": item.get("chunk_index"),
            "score": score,
            "rerank_score": item.get("rerank_score", score),
            "vector_score": item.get("vector_score"),
            "keyword_score": item.get("keyword_score"),
            "bm25_score": item.get("bm25_score"),
            "retrieval_sources": item.get("retrieval_sources", []),
            "matched_terms": item.get("matched_terms", []),
            "distance": item.get("distance"),
            "accepted": accepted,
            "reason": "sent_to_llm" if accepted else "below_threshold",
            "char_count": len(item.get("text") or ""),
            "preview": (item.get("text") or "")[:180].replace("\n", " "),
            "content": item.get("text") or "",
        }
        retrieval_debug["results"].append(source)
        if accepted:
            context_chunks.append(item["text"])
            sources_meta.append(source)
    retrieval_debug["accepted_count"] = len(sources_meta)

    if use_stream:
        return _stream_response(conv_id, user_message, document_id, context_chunks, sources_meta, retrieval_debug)
    else:
        return _normal_response(conv_id, user_message, document_id, context_chunks, sources_meta, retrieval_debug)


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


def _source_from_search_result(rank, item):
    score = item.get("score", 0)
    accepted = score > RAG_SCORE_THRESHOLD
    return {
        "rank": rank,
        "doc_id": item.get("doc_id"),
        "doc_name": _get_doc_name(item.get("doc_id")),
        "chunk_index": item.get("chunk_index"),
        "score": score,
        "rerank_score": item.get("rerank_score", score),
        "vector_score": item.get("vector_score"),
        "keyword_score": item.get("keyword_score"),
        "bm25_score": item.get("bm25_score"),
        "retrieval_sources": item.get("retrieval_sources", []),
        "matched_terms": item.get("matched_terms", []),
        "distance": item.get("distance"),
        "accepted": accepted,
        "reason": "sent_to_llm" if accepted else "below_threshold",
        "char_count": len(item.get("text") or ""),
        "preview": (item.get("text") or "")[:180].replace("\n", " "),
        "content": item.get("text") or "",
    }


def _build_legacy_rag_context(user_message, document_id, fallback_reason=None):
    context_chunks = []
    sources_meta = []
    retrieval_debug = {
        "query": user_message,
        "document_id": document_id,
        "search_scope": "all_documents" if document_id is None else "single_document",
        "top_k": RAG_TOP_K,
        "score_threshold": RAG_SCORE_THRESHOLD,
        "rag_engine": "legacy",
        "results": [],
        "accepted_count": 0,
    }
    if fallback_reason:
        retrieval_debug["fallback_reason"] = fallback_reason

    search_results = DocumentService.search_documents(user_message, document_id, top_k=RAG_TOP_K, user_id=g.user_id)
    for rank, item in enumerate(search_results, start=1):
        source = _source_from_search_result(rank, item)
        retrieval_debug["results"].append(source)
        if source["accepted"]:
            context_chunks.append(item["text"])
            sources_meta.append(source)

    retrieval_debug["accepted_count"] = len(sources_meta)
    return context_chunks, sources_meta, retrieval_debug


def _record_qa_progress(document_id):
    if document_id:
        ProgressDAO.update(document_id, status="in_progress")
        ProgressDAO.record_question(document_id)
        StudySessionDAO.create(document_id, session_type="qa", questions=1, user_id=g.user_id)


def _normal_response(conv_id, user_message, document_id, context_chunks, sources_meta, retrieval_debug):
    """非流式响应"""
    reply = llm_service.chat(conv_id, user_message, context_chunks, user_id=g.user_id)

    _record_qa_progress(document_id)

    return jsonify({
        "reply": reply,
        "sources": sources_meta,
        "source_count": len(sources_meta),
        "retrieval_debug": retrieval_debug
    })


def _langchain_stream_response(conv_id, user_message, document_id):
    """SSE response for LangChain RAG, with legacy fallback before/inside streaming."""
    def generate():
        try:
            for event in rag_chain_service.answer_stream(conv_id, user_message, document_id, user_id=g.user_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            _record_qa_progress(document_id)
        except Exception as e:
            log.warning(f"LangChain streaming RAG failed; falling back to legacy RAG: {e}", exc_info=True)
            context_chunks, sources_meta, retrieval_debug = _build_legacy_rag_context(
                user_message,
                document_id,
                fallback_reason=str(e),
            )
            for chunk in llm_service.chat_stream(conv_id, user_message, context_chunks, user_id=g.user_id):
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'sources': sources_meta, 'retrieval_debug': retrieval_debug}, ensure_ascii=False)}\n\n"
            _record_qa_progress(document_id)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


def _stream_response(conv_id, user_message, document_id, context_chunks, sources_meta, retrieval_debug):
    """SSE 流式响应"""
    def generate():
        full_reply = ""
        try:
            for chunk in llm_service.chat_stream(conv_id, user_message, context_chunks, user_id=g.user_id):
                full_reply += chunk
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'done': True, 'sources': sources_meta, 'retrieval_debug': retrieval_debug}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        # 更新进度
        _record_qa_progress(document_id)

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
    conversation = ConversationDAO.get_by_id(conv_id, user_id=g.user_id)
    if not conversation:
        return jsonify({"error": "对话不存在"}), 404
    ConversationDAO.update_title(conv_id, title)
    return jsonify({"status": "updated"})


@chat_bp.route("/api/practice/generate", methods=["POST"])
@require_auth
def generate_practice():
    data = request.get_json() or {}
    document_id = _normalize_document_id(data.get("document_id"))
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
