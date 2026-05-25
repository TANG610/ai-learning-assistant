"""OCR service for text-heavy social media images.

The service uses an OpenAI-compatible vision endpoint. Configure dedicated OCR
credentials with OCR_API_KEY/OCR_BASE_URL/OCR_MODEL, or let it fall back to the
existing MULTIMODAL_* settings.
"""
import base64
import mimetypes
import os
from pathlib import Path

from openai import OpenAI

import config
from backend.utils.logger import log


class OcrService:
    """Third-party OCR adapter backed by a vision model."""

    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    _client = None

    @staticmethod
    def _enabled() -> bool:
        return os.getenv("IMAGE_OCR_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _api_key() -> str:
        return os.getenv("OCR_API_KEY") or config.MULTIMODAL_API_KEY

    @staticmethod
    def _base_url() -> str:
        return os.getenv("OCR_BASE_URL") or config.MULTIMODAL_BASE_URL

    @staticmethod
    def _model() -> str:
        return os.getenv("OCR_MODEL") or config.MULTIMODAL_MODEL

    @staticmethod
    def is_available() -> bool:
        return bool(OcrService._enabled() and OcrService._api_key() and OcrService._model())

    @staticmethod
    def _get_client() -> OpenAI:
        if OcrService._client is None:
            OcrService._client = OpenAI(
                api_key=OcrService._api_key(),
                base_url=OcrService._base_url(),
            )
        return OcrService._client

    @staticmethod
    def _cache_path(image_path: Path) -> Path:
        return image_path.with_name(f"{image_path.name}.ocr.txt")

    @staticmethod
    def _use_cache() -> bool:
        return os.getenv("IMAGE_OCR_CACHE", "true").lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _clean_text(text: str) -> str:
        text = (text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0] if "```" in text else text
        text = text.strip()
        empty_markers = {"无", "无文字", "没有文字", "图片中没有文字", "no text"}
        return "" if text.lower() in empty_markers else text

    @staticmethod
    def extract_text_from_image(image_path: str | Path, context: str = "") -> dict:
        """Extract visible text from one local image."""
        image_path = Path(image_path)
        if image_path.suffix.lower() not in OcrService.IMAGE_EXTS:
            return {"text": "", "error": f"Unsupported image type: {image_path.suffix}"}
        if not image_path.exists():
            return {"text": "", "error": f"Image not found: {image_path}"}
        if not OcrService.is_available():
            return {"text": "", "error": "OCR is not configured"}

        cache_path = OcrService._cache_path(image_path)
        if OcrService._use_cache() and cache_path.exists():
            return {"text": cache_path.read_text(encoding="utf-8").strip(), "cached": True}

        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        image_base64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        prompt = (
            "请对这张图片做 OCR，只提取图片中可见的文字。\n"
            "要求：\n"
            "1. 保留原始语序、段落和换行；\n"
            "2. 不要总结、不要解释、不要补充图片描述；\n"
            "3. 对明显识别不确定的字用 [?] 标注；\n"
            "4. 如果没有可识别文字，返回空字符串。"
        )
        if context:
            prompt = f"上下文: {context}\n\n{prompt}"

        try:
            response = OcrService._get_client().chat.completions.create(
                model=OcrService._model(),
                max_tokens=int(os.getenv("IMAGE_OCR_MAX_TOKENS", "4096")),
                messages=[
                    {"role": "system", "content": "你是严谨的 OCR 引擎，只输出识别到的文字。"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                            },
                        ],
                    },
                ],
            )
            text = OcrService._clean_text(response.choices[0].message.content)
            if OcrService._use_cache():
                cache_path.write_text(text, encoding="utf-8")
            return {"text": text}
        except Exception as e:
            log.warning(f"OCR failed for {image_path}: {e}")
            return {"text": "", "error": str(e)}

    @staticmethod
    def extract_text_from_images(image_paths: list[str | Path], context: str = "") -> list[dict]:
        max_images = int(os.getenv("IMAGE_OCR_MAX_IMAGES", "8"))
        results = []
        for image_path in image_paths[:max_images]:
            result = OcrService.extract_text_from_image(image_path, context=context)
            result["image_path"] = str(image_path)
            results.append(result)
        return results

    @staticmethod
    def format_ocr_results(results: list[dict]) -> str:
        sections = []
        for idx, item in enumerate(results, 1):
            text = (item.get("text") or "").strip()
            if not text:
                continue
            image_name = Path(item.get("image_path", "")).name or f"image_{idx}"
            sections.append(f"[图片 {idx}: {image_name}]\n{text}")
        return "\n\n".join(sections).strip()
