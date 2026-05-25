"""
文档处理服务 - 上传、解析、入库全流程
"""
import os
import shutil
import re
import math
from typing import Tuple, List, Dict, Optional
from pathlib import Path
import config
from models.database import DocumentDAO, get_db
from services.document_parser import parse_document, chunk_text, chunk_markdown_by_headings
from services.vector_store import VectorStore
from backend.utils.logger import log


class DocumentService:
    """文档上传与处理全流程"""

    @staticmethod
    def _safe_import_filename(title: str, max_len: int = 48) -> str:
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", title or "import")
        clean = re.sub(r"\s+", " ", clean).strip(" ._")
        return (clean or "import")[:max_len]

    @staticmethod
    def _dedupe_transcript_sections(content: str) -> str:
        """Drop timestamped ASR excerpts when the full transcript is already present."""
        if not content:
            return content

        full_match = re.search(r"(^|\n)完整文字稿\s*[:：]", content)
        timestamp_match = re.search(r"(^|\n)带时间戳片段\s*[:：]", content)
        if not full_match or not timestamp_match:
            return content

        timestamp_section = re.compile(
            r"(?ms)\n{0,2}带时间戳片段\s*[:：]\s*\n"
            r"(?:\[[0-9:.：]+\]\s*.*(?:\n|$))+"
        )
        cleaned = timestamp_section.sub("\n\n", content)
        if cleaned == content and timestamp_match.start() > full_match.start():
            cleaned = content[:timestamp_match.start()]

        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    @staticmethod
    def save_upload(file, filename: str, user_id: int = None) -> Tuple[str, str, int]:
        """
        保存上传文件

        Returns:
            (file_path, file_type, file_size)
        """
        suffix = Path(filename).suffix.lower()
        import uuid
        unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"

        # 按用户分目录
        if user_id:
            user_dir = config.UPLOAD_DIR / str(user_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            dest_path = user_dir / unique_name
        else:
            dest_path = config.UPLOAD_DIR / unique_name

        file.save(str(dest_path))
        file_size = dest_path.stat().st_size

        return str(dest_path), suffix.lstrip("."), file_size

    @staticmethod
    def import_text(title: str, content: str, user_id: int = None,
                    file_category: str = 'news') -> dict:
        """
        直接导入文本内容作为文档（无需文件上传），复用现有解析管道。

        Args:
            title: 文档标题
            content: 文本内容
            user_id: 用户ID
            file_category: 文档分类，默认 'news'

        Returns:
            {"doc_id": int, "chunks": int, "status": str}
        """
        import uuid
        content = DocumentService._dedupe_transcript_sections(content)
        import_dir = config.DATA_DIR / "imports" / (str(user_id) if user_id else "shared")
        import_dir.mkdir(parents=True, exist_ok=True)
        safe_title = DocumentService._safe_import_filename(title)
        import_path = import_dir / f"{uuid.uuid4().hex[:8]}_{safe_title}.txt"
        import_path.write_text(content, encoding="utf-8")

        doc_id = DocumentDAO.create(
            title, "txt", str(import_path), len(content.encode("utf-8")),
            user_id=user_id, file_category=file_category
        )
        result = DocumentService.process_document(doc_id)
        result["doc_id"] = doc_id
        return result

    @staticmethod
    def process_document(doc_id: int, progress_callback=None) -> dict:
        """
        处理文档：解析 → 分块 → 向量化 → 入库

        Args:
            doc_id: 文档ID
            progress_callback: callable(stage_label, progress_pct) 进度回调

        Returns:
            处理结果 {"chunks": int, "status": str}
        """
        doc = DocumentDAO.get_by_id(doc_id)
        if not doc:
            return {"error": "文档不存在"}

        file_category = doc.get("file_category", "text")

        try:
            # 1. 解析文档
            if progress_callback:
                if file_category == "multimodal":
                    progress_callback("正在调用视觉模型理解图片...", 25)
                else:
                    progress_callback("正在解析文档文本...", 30)

            if file_category == "multimodal":
                text, file_type = DocumentService._parse_multimodal(doc["file_path"], progress_callback)
            else:
                text, file_type = parse_document(doc["file_path"])

            text = DocumentService._dedupe_transcript_sections(text)

            if not text or not text.strip():
                DocumentDAO.update_status(doc_id, "error")
                return {"error": "文档内容为空"}

            # 2. 文本分块
            if progress_callback:
                progress_callback("正在切分文本块...", 50)
            if file_type in ("md", "markdown"):
                chunks = chunk_markdown_by_headings(text)
            else:
                chunks = chunk_text(text)
            if not chunks:
                DocumentDAO.update_status(doc_id, "error")
                return {"error": "分块结果为空"}

            # 3. 存入向量数据库
            if progress_callback:
                progress_callback(f"正在向量化 {len(chunks)} 个文本块...", 65)
            user_id = doc.get("user_id")
            vector_store = VectorStore()
            conn = get_db()
            conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))
            conn.commit()
            conn.close()
            vector_store.delete_document(doc_id, user_id=user_id)
            vector_ids = vector_store.add_chunks(doc_id, chunks, user_id=user_id)

            # 4. 存入SQLite
            if progress_callback:
                progress_callback("正在保存到数据库...", 85)
            conn = get_db()
            for i, chunk in enumerate(chunks):
                vid = vector_ids[i] if i < len(vector_ids) else None
                conn.execute(
                    "INSERT INTO document_chunks (document_id, chunk_index, content, vector_id, user_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (doc_id, i, chunk, vid, user_id)
                )
            # 保存 OCR 文本（多模态文件）
            if file_category == "multimodal":
                conn.execute(
                    "UPDATE documents SET ocr_text = ? WHERE id = ?",
                    (text, doc_id)
                )
            conn.commit()
            conn.close()

            # 5. 更新文档状态
            DocumentDAO.update_status(doc_id, "parsed", len(chunks))

            return {
                "chunks": len(chunks),
                "status": "parsed",
                "file_type": file_type,
                "text_length": len(text),
                "file_category": file_category
            }

        except BaseException as e:
            log.error(f"Document parse failed doc_id={doc_id}: {e}", exc_info=True)
            DocumentDAO.update_status(doc_id, "error")
            return {"error": str(e)}

    @staticmethod
    def _parse_multimodal(file_path: str, progress_callback=None) -> tuple:
        """多模态文件解析：调用视觉模型理解图片内容"""
        ext = Path(file_path).suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
            import base64
            try:
                with open(file_path, "rb") as f:
                    img_data = base64.b64encode(f.read()).decode("utf-8")

                file_size_kb = Path(file_path).stat().st_size / 1024
                file_name = Path(file_path).name

                # 尝试调用多模态视觉模型
                parse_error = None
                try:
                    from services.claude_service import LLMService
                    llm = LLMService()
                    result = llm.chat_with_image(
                        image_base64=img_data,
                        question=f"请详细描述这张图片的内容。如果是图表，请描述其中的数据和趋势。如果是界面截图，请描述界面布局和功能。图片文件名: {file_name}"
                    )
                    if result and not result.startswith("错误") and not result.startswith("多模态分析失败"):
                        text = (
                            f"[图片分析] 文件名: {file_name}\n"
                            f"文件大小: {file_size_kb:.1f} KB | 格式: {ext.upper()}\n"
                            f"---\n视觉模型分析结果:\n{result}"
                        )
                        return text, ext.lstrip(".")
                    else:
                        parse_error = result
                except Exception as e:
                    parse_error = str(e)

                # 多模态模型不可用时回退
                reason = parse_error or "未配置多模态模型"
                text = (
                    f"[图片文件] 文件名: {file_name}\n"
                    f"文件大小: {file_size_kb:.1f} KB | 格式: {ext.upper()}\n"
                    f"说明: 视觉模型暂时不可用（{reason}）。请在设置中确认多模态模型提供商配置正确后重新解析。"
                )
                return text, ext.lstrip(".")
            except Exception as e:
                return f"[图片解析失败] {e}", ext.lstrip(".")
        else:
            return parse_document(file_path)

    @staticmethod
    def delete_document(doc_id: int) -> dict:
        """删除文档及其所有关联数据"""
        doc = DocumentDAO.get_by_id(doc_id)
        if not doc:
            return {"error": "文档不存在"}

        # 删除文件
        try:
            os.remove(doc["file_path"])
        except OSError:
            pass

        # 删除向量数据
        user_id = doc.get("user_id")
        vector_store = VectorStore()
        vector_store.delete_document(doc_id, user_id=user_id)

        # 删除数据库记录（级联删除 chunks, progress 等）
        DocumentDAO.delete(doc_id)

        return {"status": "deleted", "doc_id": doc_id}

    @staticmethod
    def search_documents(query: str, doc_id: int = None, top_k: int = 5, user_id: int = None) -> list:
        """语义搜索文档内容

        Returns:
            [{"text": str, "score": float, "doc_id": int, "chunk_index": int}, ...]
        """
        try:
            vector_store = VectorStore()
            return vector_store.search(query, doc_id, top_k, user_id=user_id)
        except BaseException as e:
            log.error(f"Vector search failed: {e}", exc_info=True)
            return []

    @staticmethod
    def search_documents(query: str, doc_id: int = None, top_k: int = 5, user_id: int = None) -> list:
        """Search with vector recall + keyword recall + local reranking."""
        return DocumentService.hybrid_search_documents(query, doc_id, top_k, user_id=user_id)

    @staticmethod
    def hybrid_search_documents(query: str, doc_id: int = None, top_k: int = 5, user_id: int = None) -> list:
        """Dual-route retrieval over document chunks.

        Vector recall handles semantic paraphrases. Keyword recall handles exact
        titles, acronyms, names, noisy ASR/OCR fragments, and copied phrases.
        Results are merged by (doc_id, chunk_index) and reranked locally without
        downloading an extra reranker model.
        """
        top_k = max(1, int(top_k or 5))
        vector_results = DocumentService._safe_vector_search(query, doc_id, max(top_k * 2, top_k), user_id)
        keyword_results = DocumentService._keyword_search_documents(query, doc_id, max(top_k * 4, top_k), user_id)
        merged = DocumentService._merge_retrieval_results(vector_results, keyword_results)
        reranked = DocumentService._rerank_results(query, merged)
        return reranked[:top_k]

    @staticmethod
    def _safe_vector_search(query: str, doc_id: int = None, top_k: int = 5, user_id: int = None) -> list:
        try:
            vector_store = VectorStore()
            return vector_store.search(query, doc_id, top_k, user_id=user_id)
        except BaseException as e:
            log.error(f"Vector search failed: {e}", exc_info=True)
            return []

    @staticmethod
    def _keyword_search_documents(query: str, doc_id: int = None, top_k: int = 20, user_id: int = None) -> list:
        tokens = DocumentService._tokenize_for_retrieval(query)
        if not tokens:
            return []

        like_tokens = tokens[:16]
        where_clauses = []
        params = []
        if doc_id:
            where_clauses.append("document_id = ?")
            params.append(int(doc_id))
        if user_id is not None:
            where_clauses.append("user_id = ?")
            params.append(int(user_id))

        token_clauses = ["LOWER(content) LIKE ?" for _ in like_tokens]
        if token_clauses:
            where_clauses.append("(" + " OR ".join(token_clauses) + ")")
            params.extend(f"%{DocumentService._escape_like_token(token)}%" for token in like_tokens)

        where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        sql = (
            "SELECT document_id, chunk_index, content "
            "FROM document_chunks"
            f"{where_sql} "
            "ORDER BY created_at DESC "
            "LIMIT ?"
        )
        params.append(max(50, int(top_k) * 8))

        try:
            conn = get_db()
            rows = conn.execute(sql, params).fetchall()
            conn.close()
        except BaseException as e:
            log.warning(f"Keyword search failed: {e}")
            return []

        scored = []
        for row in rows:
            content = row["content"] or ""
            keyword_score, matched_terms = DocumentService._keyword_score(query, content, tokens)
            if keyword_score <= 0:
                continue
            scored.append({
                "text": content,
                "score": keyword_score,
                "keyword_score": keyword_score,
                "matched_terms": matched_terms[:12],
                "doc_id": row["document_id"],
                "chunk_index": row["chunk_index"],
            })

        scored.sort(key=lambda item: item["keyword_score"], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _merge_retrieval_results(vector_results: list, keyword_results: list) -> list:
        merged: Dict[tuple, dict] = {}

        for rank, item in enumerate(vector_results or [], start=1):
            key = DocumentService._result_key(item)
            if not key:
                continue
            score = float(item.get("score") or 0)
            merged[key] = {
                "text": item.get("text") or "",
                "doc_id": item.get("doc_id"),
                "chunk_index": item.get("chunk_index"),
                "distance": item.get("distance"),
                "vector_score": score,
                "keyword_score": 0.0,
                "vector_rank": rank,
                "keyword_rank": None,
                "retrieval_sources": ["vector"],
                "matched_terms": [],
            }

        for rank, item in enumerate(keyword_results or [], start=1):
            key = DocumentService._result_key(item)
            if not key:
                continue
            keyword_score = float(item.get("keyword_score", item.get("score") or 0))
            existing = merged.get(key)
            if existing:
                existing["keyword_score"] = max(existing.get("keyword_score", 0.0), keyword_score)
                existing["keyword_rank"] = rank
                existing["matched_terms"] = item.get("matched_terms", [])
                if "keyword" not in existing["retrieval_sources"]:
                    existing["retrieval_sources"].append("keyword")
                if not existing.get("text"):
                    existing["text"] = item.get("text") or ""
            else:
                merged[key] = {
                    "text": item.get("text") or "",
                    "doc_id": item.get("doc_id"),
                    "chunk_index": item.get("chunk_index"),
                    "distance": None,
                    "vector_score": 0.0,
                    "keyword_score": keyword_score,
                    "vector_rank": None,
                    "keyword_rank": rank,
                    "retrieval_sources": ["keyword"],
                    "matched_terms": item.get("matched_terms", []),
                }

        return list(merged.values())

    @staticmethod
    def _rerank_results(query: str, results: list) -> list:
        tokens = DocumentService._tokenize_for_retrieval(query)
        reranked = []
        for item in results:
            text = item.get("text") or ""
            vector_score = max(0.0, min(1.0, float(item.get("vector_score") or 0.0)))
            keyword_score = max(0.0, min(1.0, float(item.get("keyword_score") or 0.0)))
            lexical_score, matched_terms = DocumentService._keyword_score(query, text, tokens)
            keyword_score = max(keyword_score, lexical_score)
            dual_route_bonus = 0.08 if vector_score > 0 and keyword_score > 0 else 0.0
            exact_phrase_bonus = 0.06 if DocumentService._normalized_text(query) in DocumentService._normalized_text(text) else 0.0
            rank_bonus = DocumentService._rank_bonus(item.get("vector_rank"), item.get("keyword_rank"))

            rerank_score = (
                0.52 * vector_score
                + 0.42 * keyword_score
                + dual_route_bonus
                + exact_phrase_bonus
                + rank_bonus
            )
            item["keyword_score"] = round(keyword_score, 4)
            item["matched_terms"] = item.get("matched_terms") or matched_terms[:12]
            item["rerank_score"] = round(min(1.0, rerank_score), 4)
            item["score"] = item["rerank_score"]
            reranked.append(item)

        reranked.sort(
            key=lambda item: (
                item.get("rerank_score", 0),
                len(item.get("retrieval_sources", [])),
                item.get("vector_score", 0),
                item.get("keyword_score", 0),
            ),
            reverse=True,
        )
        return reranked

    @staticmethod
    def _result_key(item: dict) -> Optional[tuple]:
        doc_id = item.get("doc_id")
        chunk_index = item.get("chunk_index")
        if doc_id is None or chunk_index is None:
            text = item.get("text")
            return ("text", hash(text)) if text else None
        return (int(doc_id), int(chunk_index))

    @staticmethod
    def _rank_bonus(vector_rank, keyword_rank) -> float:
        bonus = 0.0
        if vector_rank:
            bonus += 0.025 / max(1, int(vector_rank))
        if keyword_rank:
            bonus += 0.02 / max(1, int(keyword_rank))
        return bonus

    @staticmethod
    def _tokenize_for_retrieval(text: str) -> List[str]:
        text = DocumentService._normalized_text(text)
        if not text:
            return []

        tokens = []
        tokens.extend(re.findall(r"[a-z0-9][a-z0-9_\-\.]{1,}", text))

        cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
        for run in cjk_runs:
            if len(run) <= 6:
                tokens.append(run)
            for size in (2, 3):
                if len(run) >= size:
                    tokens.extend(run[i:i + size] for i in range(0, len(run) - size + 1))

        seen = set()
        clean_tokens = []
        for token in tokens:
            token = token.strip("._- ")
            if len(token) < 2 or token in seen:
                continue
            seen.add(token)
            clean_tokens.append(token)
        return clean_tokens

    @staticmethod
    def _keyword_score(query: str, content: str, tokens: List[str]) -> tuple:
        normalized_content = DocumentService._normalized_text(content)
        if not normalized_content or not tokens:
            return 0.0, []

        matched = []
        weighted_hits = 0.0
        for token in tokens:
            count = normalized_content.count(token)
            if count:
                matched.append(token)
                weighted_hits += min(3, count) * (1.25 if len(token) >= 4 else 1.0)

        if not matched:
            return 0.0, []

        coverage = len(set(matched)) / max(1, len(set(tokens)))
        hit_density = min(1.0, weighted_hits / max(3.0, math.sqrt(max(1, len(normalized_content))) / 2))
        phrase = 1.0 if DocumentService._normalized_text(query) in normalized_content else 0.0
        score = min(1.0, 0.58 * coverage + 0.32 * hit_density + 0.10 * phrase)
        return round(score, 4), matched

    @staticmethod
    def _normalized_text(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").lower()).strip()

    @staticmethod
    def _escape_like_token(token: str) -> str:
        return token.replace("%", "\\%").replace("_", "\\_")
