"""
API 路由 - 测评模块
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, request, jsonify, g
from services.claude_service import LLMService
from models.database import (
    AssessmentDAO, KnowledgeDAO, ProgressDAO, DocumentDAO, StudySessionDAO, get_db
)
from services.document_service import DocumentService
from backend.middleware.auth import require_auth

quiz_bp = Blueprint("quiz", __name__)
llm = LLMService()
ALL_KNOWLEDGE_VALUES = {None, "", "all", "__all__"}
ASSESSMENT_CONTEXT_CHAR_LIMIT = 6000


def _normalize_document_id(value):
    if value in ALL_KNOWLEDGE_VALUES:
        return None
    try:
        doc_id = int(value)
    except (TypeError, ValueError):
        return None
    return doc_id if doc_id > 0 else None


def _assessment_source_ids(assessment):
    raw = (assessment or {}).get("source_document_ids") or ""
    ids = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            ids.append(int(item))
        except ValueError:
            continue
    if not ids and assessment and assessment.get("document_id"):
        ids.append(int(assessment["document_id"]))
    return ids


def _get_single_document_context(document_id, user_id):
    doc = DocumentDAO.get_by_id(document_id)
    if not doc:
        return None, [], "文档不存在", 404
    if doc.get("user_id") and doc["user_id"] != user_id:
        return None, [], "无权访问此文档", 403

    conn = get_db()
    chunks = conn.execute(
        "SELECT content FROM document_chunks WHERE document_id = ? ORDER BY chunk_index",
        (document_id,)
    ).fetchall()
    conn.close()

    doc_content = "\n\n".join([c["content"] for c in chunks])
    if not doc_content.strip():
        return None, [], "文档内容为空，无法生成题目", 400

    return {
        "primary_document_id": document_id,
        "source_document_ids": [document_id],
        "scope_label": "",
        "doc_content": doc_content,
    }, [doc], None, None


def _get_all_documents_context(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT d.id, d.filename, c.content "
        "FROM documents d JOIN document_chunks c ON d.id = c.document_id "
        "WHERE d.user_id = ? AND d.status = 'parsed' "
        "ORDER BY d.created_at DESC, d.id DESC, c.chunk_index ASC",
        (user_id,)
    ).fetchall()
    conn.close()

    by_doc = {}
    for row in rows:
        doc_id = row["id"]
        if doc_id not in by_doc:
            by_doc[doc_id] = {"id": doc_id, "filename": row["filename"], "chunks": []}
        by_doc[doc_id]["chunks"].append(row["content"])

    docs = list(by_doc.values())
    if not docs:
        return None, [], "还没有已解析的知识库文档，无法生成题目", 400

    per_doc_limit = max(180, ASSESSMENT_CONTEXT_CHAR_LIMIT // max(len(docs), 1))
    parts = []
    for doc in docs:
        text = "\n".join(doc["chunks"]).strip()
        if not text:
            continue
        parts.append(f"【{doc['filename']}】\n{text[:per_doc_limit]}")

    doc_content = "\n\n".join(parts)
    if not doc_content.strip():
        return None, [], "知识库内容为空，无法生成题目", 400

    source_ids = [doc["id"] for doc in docs]
    return {
        "primary_document_id": source_ids[0],
        "source_document_ids": source_ids,
        "scope_label": "全部知识库",
        "doc_content": doc_content,
    }, docs, None, None


@quiz_bp.route("/api/assessments", methods=["POST"])
@require_auth
def create_assessment():
    data = request.get_json() or {}
    document_id = _normalize_document_id(data.get("document_id"))

    question_count = data.get("question_count", 8)

    if document_id is None:
        context, docs, error, status_code = _get_all_documents_context(g.user_id)
    else:
        context, docs, error, status_code = _get_single_document_context(document_id, g.user_id)
    if error:
        return jsonify({"error": error}), status_code

    # 并发执行出题 + 知识点提取
    status_key = f"create_{context['scope_label'] or context['primary_document_id']}"
    _assessment_status[status_key] = {"stage": "generating", "stage_label": "正在生成题目..."}

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_questions = pool.submit(llm.generate_assessment, context["doc_content"], question_count)
        future_kp = pool.submit(llm.extract_knowledge_points, context["doc_content"])

        # 等出题结果
        # result = future_questions.result()
        try:
            result = future_questions.result()
            print(f"[DEBUG] LLM result: {result}")  # 调试输出
        except Exception as e:
            print(f"[ERROR] LLM 调用失败: {e}")
            return jsonify({"error": f"LLM调用失败: {e}"}), 500
        if "error" in result:
            return jsonify({"error": f"出题失败: {result['error']}"}), 500

        questions = result.get("questions", [])
        if not questions:
            return jsonify({"error": "未能生成题目，请尝试其他文档"}), 500

        assessment_id = AssessmentDAO.create(
            context["primary_document_id"],
            user_id=g.user_id,
            source_document_ids=context["source_document_ids"],
            scope_label=context["scope_label"],
        )
        AssessmentDAO.update_status(assessment_id, "in_progress")

        difficulty_map = {"easy": "easy", "medium": "medium", "hard": "hard", "简单": "easy", "中等": "medium", "较难": "hard"}
        type_map = {"choice": "choice", "single_choice": "choice", "multi_choice": "multi_choice",
                    "true_false": "true_false", "tf": "true_false", "short_answer": "short_answer", "简答题": "short_answer"}

        for i, q in enumerate(questions):
            q_type = type_map.get(q.get("type", "choice"), "choice")
            options = q.get("options")
            if isinstance(options, dict):
                options = json.dumps(options, ensure_ascii=False)
            elif isinstance(options, list):
                options = json.dumps({chr(65 + j): opt for j, opt in enumerate(options)}, ensure_ascii=False)
            elif options is None:
                options = json.dumps({})

            correct = q.get("answer", "")

            if q_type == "true_false":
                correct = correct.strip()
                if correct in ("正确", "对", "true", "True", "TRUE", "是", "A"):
                    correct = "A"
                else:
                    correct = "B"

            AssessmentDAO.add_question(
                assessment_id=assessment_id, q_type=q_type,
                question_text=q.get("question", ""), options=options or "{}",
                correct_answer=correct, explanation=q.get("explanation", ""),
                knowledge_point=q.get("knowledge_point", "综合"),
                difficulty=difficulty_map.get(q.get("difficulty", "medium"), "medium"),
                sort_order=i
            )

        for source_doc_id in context["source_document_ids"]:
            ProgressDAO.update(source_doc_id, status="in_progress")

        # 等知识点提取结果（与出题并发，此时可能已完成）
        kp_list = future_kp.result()
        for source_doc_id in context["source_document_ids"]:
            for kp in kp_list:
                KnowledgeDAO.upsert(source_doc_id, kp.get("name", ""), mastery="learning", is_correct=None, user_id=g.user_id)

    _assessment_status.pop(status_key, None)

    stored_questions = AssessmentDAO.get_questions(assessment_id)
    display_questions = []
    for q in stored_questions:
        dq = {
            "id": q["id"], "question_type": q["question_type"],
            "question_text": q["question_text"], "options": q["options"],
            "knowledge_point": q["knowledge_point"], "difficulty": q["difficulty"],
            "sort_order": q["sort_order"]
        }
        display_questions.append(dq)

    return jsonify({
        "assessment_id": assessment_id, "document_id": context["primary_document_id"],
        "source_document_ids": context["source_document_ids"],
        "scope_label": context["scope_label"],
        "questions": display_questions, "total": len(display_questions)
    }), 201


@quiz_bp.route("/api/assessments/<int:assessment_id>", methods=["GET"])
@require_auth
def get_assessment(assessment_id):
    assessment = AssessmentDAO.get_by_id(assessment_id)
    if not assessment:
        return jsonify({"error": "测评不存在"}), 404
    if assessment.get("user_id") and assessment["user_id"] != g.user_id:
        return jsonify({"error": "测评不存在"}), 404

    questions = AssessmentDAO.get_questions(assessment_id)
    display_questions = []
    for q in questions:
        dq = {
            "id": q["id"], "question_type": q["question_type"],
            "question_text": q["question_text"], "options": q["options"],
            "knowledge_point": q["knowledge_point"], "difficulty": q["difficulty"],
            "sort_order": q["sort_order"]
        }
        if assessment["status"] == "completed":
            dq["user_answer"] = q["user_answer"]
            dq["is_correct"] = q["is_correct"]
            dq["score"] = q["score"]
            dq["ai_feedback"] = q["ai_feedback"]
        display_questions.append(dq)

    return jsonify({
        "assessment": assessment,
        "source_document_ids": _assessment_source_ids(assessment),
        "scope_label": assessment.get("scope_label", ""),
        "questions": display_questions
    })


@quiz_bp.route("/api/assessments/<int:assessment_id>/submit", methods=["POST"])
@require_auth
def submit_assessment(assessment_id):
    data = request.get_json() or {}
    answers = data.get("answers", [])
    if not answers:
        return jsonify({"error": "未提交任何答案"}), 400

    assessment = AssessmentDAO.get_by_id(assessment_id)
    if not assessment:
        return jsonify({"error": "测评不存在"}), 404
    if assessment.get("user_id") and assessment["user_id"] != g.user_id:
        return jsonify({"error": "测评不存在"}), 404

    questions = AssessmentDAO.get_questions(assessment_id)
    source_doc_ids = _assessment_source_ids(assessment)
    judge_questions = []
    judge_answers = []
    answer_map = {a["question_id"]: a["user_answer"] for a in answers}

    for q in questions:
        judge_questions.append(q)
        judge_answers.append({
            "question_index": q["sort_order"],
            "user_answer": answer_map.get(q["id"], "")
        })
        AssessmentDAO.submit_answer(q["id"], answer_map.get(q["id"], ""), -1, 0.0)

    _assessment_status[assessment_id] = {"stage": "judging", "stage_label": "AI 正在评判答案..."}

    result = llm.judge_answers(judge_questions, judge_answers)
    if "error" in result:
        return jsonify({"error": f"评判失败: {result['error']}"}), 500

    results = result.get("results", [])
    correct_count = 0
    total_score = 0.0

    for r in results:
        idx = r.get("question_index", 0)
        if idx < len(questions):
            q = questions[idx]
            is_correct = 1 if r.get("is_correct") else 0
            score = float(r.get("score", 0))
            if is_correct:
                correct_count += 1
            total_score += score

            # 将题目原文、正确答案和用户答案注入结果，方便前端展示
            r["question"] = q.get("question_text", "")
            r["correct_answer"] = q.get("correct_answer", "")
            r["user_answer"] = answer_map.get(q["id"], "")
            r["explanation"] = q.get("explanation", "")

            AssessmentDAO.submit_answer(
                q["id"], answer_map.get(q["id"], ""), is_correct, score, r.get("feedback", "")
            )

            kp_name = r.get("knowledge_point", "") or q.get("knowledge_point", "")
            mastery = r.get("mastery_level", "weak")
            if kp_name:
                for source_doc_id in source_doc_ids:
                    KnowledgeDAO.upsert(
                        source_doc_id, kp_name, mastery,
                        is_correct=bool(r.get("is_correct")), user_id=g.user_id
                    )

    total = len(questions)
    final_score = round(total_score / total * 100, 1) if total > 0 else 0
    knowledge_summary = _build_knowledge_summary(questions, results)

    AssessmentDAO.update_completed(assessment_id, correct_count, final_score, knowledge_summary)

    avg_score = final_score
    progress_status = "completed" if avg_score >= 80 else "review_needed"
    for source_doc_id in source_doc_ids:
        ProgressDAO.update(source_doc_id, status=progress_status, confidence=avg_score)

    conn = get_db()
    from datetime import datetime
    timestamp = datetime.now().strftime("%m-%d %H:%M")

    weak_kps = []
    for q, r in zip(questions, results):
        if not r.get("is_correct"):
            kp = r.get("knowledge_point") or q.get("knowledge_point", "")
            if kp:
                weak_kps.append(kp)
    weak_text = "、".join(list(set(weak_kps))[:5]) if weak_kps else "无"

    scope_label = assessment.get("scope_label") or "测评"
    new_entry = f"\n## {timestamp} {scope_label} {final_score}分 ({correct_count}/{total})\n薄弱点：{weak_text}\n"
    for source_doc_id in source_doc_ids:
        existing = conn.execute(
            "SELECT notes FROM learning_progress WHERE document_id=?", (source_doc_id,)
        ).fetchone()
        old_notes = existing["notes"] if existing and existing["notes"] else ""
        updated_notes = old_notes.rstrip() + new_entry
        conn.execute(
            "UPDATE learning_progress SET notes=?, updated_at=datetime('now','localtime') WHERE document_id=?",
            (updated_notes, source_doc_id)
        )
    conn.commit()
    conn.close()

    for source_doc_id in source_doc_ids:
        StudySessionDAO.create(source_doc_id, session_type="practice", questions=total, user_id=g.user_id)

    _assessment_status[assessment_id] = {"stage": "completed", "stage_label": "分析完成"}

    return jsonify({
        "assessment_id": assessment_id, "score": final_score,
        "correct_count": correct_count, "total": total,
        "results": results, "knowledge_summary": knowledge_summary
    })


# 测评任务状态追踪（内存缓存，用于进度轮询）
_assessment_status = {}

@quiz_bp.route("/api/assessments/<int:assessment_id>/status", methods=["GET"])
@require_auth
def assessment_status(assessment_id):
    status = _assessment_status.get(assessment_id, {"stage": "completed", "stage_label": "已完成"})
    return jsonify(status)


@quiz_bp.route("/api/assessments/history", methods=["GET"])
@require_auth
def assessment_history():
    doc_id = request.args.get("document_id", type=int)
    limit = request.args.get("limit", 20, type=int)

    conn = get_db()
    if doc_id:
        rows = conn.execute(
            "SELECT a.*, COALESCE(NULLIF(a.scope_label, ''), d.filename) AS filename FROM assessments a "
            "JOIN documents d ON a.document_id = d.id "
            "WHERE (a.document_id = ? OR ',' || a.source_document_ids || ',' LIKE ?) "
            "AND a.status = 'completed' AND a.user_id = ? "
            "ORDER BY a.created_at DESC LIMIT ?",
            (doc_id, f"%,{doc_id},%", g.user_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT a.*, COALESCE(NULLIF(a.scope_label, ''), d.filename) AS filename FROM assessments a "
            "JOIN documents d ON a.document_id = d.id "
            "WHERE a.status = 'completed' AND a.user_id = ? "
            "ORDER BY a.created_at DESC LIMIT ?",
            (g.user_id, limit)
        ).fetchall()
    conn.close()
    return jsonify({"assessments": [dict(r) for r in rows]})


def _build_knowledge_summary(questions, results):
    summary = {}
    for r in results:
        kp = r.get("knowledge_point", "综合")
        mastery = r.get("mastery_level", "weak")
        if kp not in summary:
            summary[kp] = {"total": 0, "correct": 0, "level": mastery}
        summary[kp]["total"] += 1
        if r.get("is_correct"):
            summary[kp]["correct"] += 1
    return json.dumps(summary, ensure_ascii=False)
