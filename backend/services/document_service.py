"""
文档处理服务 - 上传、解析、入库全流程
"""
import os
import shutil
from typing import Tuple
from pathlib import Path
import config
from models.database import DocumentDAO, get_db
from services.document_parser import parse_document, chunk_text
from services.vector_store import VectorStore


class DocumentService:
    """文档上传与处理全流程"""

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
        tmp_dir = config.UPLOAD_DIR / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"import_{uuid.uuid4().hex[:8]}.txt"
        tmp_path.write_text(content, encoding="utf-8")
        try:
            doc_id = DocumentDAO.create(
                title, "txt", str(tmp_path), len(content.encode("utf-8")),
                user_id=user_id, file_category=file_category
            )
            result = DocumentService.process_document(doc_id)
            result["doc_id"] = doc_id
            return result
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

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

            if not text or not text.strip():
                DocumentDAO.update_status(doc_id, "error")
                return {"error": "文档内容为空"}

            # 2. 文本分块
            if progress_callback:
                progress_callback("正在切分文本块...", 50)
            chunks = chunk_text(text)
            if not chunks:
                DocumentDAO.update_status(doc_id, "error")
                return {"error": "分块结果为空"}

            # 3. 存入向量数据库
            if progress_callback:
                progress_callback(f"正在向量化 {len(chunks)} 个文本块...", 65)
            user_id = doc.get("user_id")
            vector_store = VectorStore()
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

        except Exception as e:
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
        """语义搜索文档内容"""
        vector_store = VectorStore()
        return vector_store.search(query, doc_id, top_k, user_id=user_id)
