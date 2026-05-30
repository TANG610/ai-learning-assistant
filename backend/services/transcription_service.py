"""
Video transcription service.

Pipeline:
    video file -> ffmpeg 16 kHz mono WAV -> ASR provider -> text + segments

Temporary audio is always removed. The caller must call delete_video_dir()
after confirming the transcript quality is sufficient.
"""
import base64
import os
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import requests

from backend.utils.logger import log


ASR_PROVIDER = os.getenv("ASR_PROVIDER", "").strip().lower()
BAIDU_ASR_API_KEY = os.getenv("BAIDU_ASR_API_KEY", "").strip()
BAIDU_ASR_SECRET_KEY = os.getenv("BAIDU_ASR_SECRET_KEY", "").strip()
BAIDU_ASR_CUID = os.getenv("BAIDU_ASR_CUID", "ai-learning-assistant").strip()
BAIDU_ASR_DEV_PID = int(os.getenv("BAIDU_ASR_DEV_PID", "1537"))
BAIDU_ASR_CHUNK_SECONDS = int(os.getenv("BAIDU_ASR_CHUNK_SECONDS", "55"))
BAIDU_ASR_TIMEOUT = int(os.getenv("BAIDU_ASR_TIMEOUT", "30"))
LOCAL_WHISPER_ASR_ENABLED = os.getenv("LOCAL_WHISPER_ASR_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
BAIDU_ASR_FALLBACK_TO_WHISPER = os.getenv("BAIDU_ASR_FALLBACK_TO_WHISPER", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
BAIDU_TOKEN_URL = os.getenv("BAIDU_ASR_TOKEN_URL", "https://aip.baidubce.com/oauth/2.0/token")
BAIDU_ASR_URL = os.getenv("BAIDU_ASR_URL", "http://vop.baidu.com/server_api")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")
WHISPER_MODEL_PATH = os.getenv(
    "WHISPER_MODEL_PATH",
    str(Path(__file__).resolve().parents[2] / "models" / f"faster-whisper-{WHISPER_MODEL_SIZE}"),
)
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
FFMPEG_TIMEOUT = int(os.getenv("FFMPEG_TIMEOUT", "180"))


def _get_ffmpeg_exe() -> str:
    configured = os.getenv("FFMPEG_PATH", "").strip()
    if configured:
        return configured

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


class TranscriptionService:
    """Transcribe local videos and clean up temporary media files."""

    _model = None
    _baidu_token = ""
    _baidu_token_expire_at = 0.0

    @classmethod
    def _get_model(cls):
        if cls._model is None:
            model_ref = WHISPER_MODEL_PATH if os.path.isdir(WHISPER_MODEL_PATH) else WHISPER_MODEL_SIZE
            log.info(f"[Transcription] Loading faster-whisper model: {model_ref}")
            from faster_whisper import WhisperModel

            cls._model = WhisperModel(
                model_ref,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
            )
        return cls._model

    @classmethod
    def _get_provider(cls) -> str:
        if ASR_PROVIDER == "baidu":
            return ASR_PROVIDER
        if ASR_PROVIDER == "whisper":
            return "whisper" if LOCAL_WHISPER_ASR_ENABLED else "disabled"
        if BAIDU_ASR_API_KEY and BAIDU_ASR_SECRET_KEY:
            return "baidu"
        return "disabled"

    @classmethod
    def transcribe(cls, video_path: str) -> dict:
        """
        Transcribe a video. Temporary audio is always cleaned up; the caller
        decides whether to keep or delete the source video via delete_video_dir().

        Returns:
            {
                "text": str,
                "segments": [{"start": float, "end": float, "text": str}],
                "language": str,
            }
        """
        if not os.path.isfile(video_path):
            log.warning(f"[Transcription] Video file not found: {video_path}")
            return {"text": "", "segments": [], "language": ""}

        audio_path = None
        try:
            provider = cls._get_provider()
            if provider == "disabled":
                log.info("[Transcription] Local Whisper ASR is disabled.")
                return {"text": "", "segments": [], "language": ""}

            audio_path = cls._extract_audio(video_path)
            if not audio_path:
                return {"text": "", "segments": [], "language": ""}

            if provider == "baidu":
                try:
                    result = cls._run_baidu(audio_path)
                except Exception as e:
                    if not BAIDU_ASR_FALLBACK_TO_WHISPER or not LOCAL_WHISPER_ASR_ENABLED:
                        raise
                    log.warning(f"[Transcription] Baidu ASR failed, falling back to whisper: {e}")
                    result = cls._run_whisper(audio_path)
            else:
                result = cls._run_whisper(audio_path)

            log.info(f"[Transcription] Done: {len(result.get('text', ''))} chars")
            return result
        except Exception as e:
            log.error(f"[Transcription] Failed: {video_path} | {e}")
            return {"text": "", "segments": [], "language": ""}
        finally:
            cls._cleanup_audio(audio_path)

    @classmethod
    def transcribe_text(cls, video_path: str) -> str:
        return cls.transcribe(video_path).get("text", "")

    @classmethod
    def _extract_audio(cls, video_path: str) -> str | None:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        audio_path = tmp.name

        cmd = [
            _get_ffmpeg_exe(),
            "-y",
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            audio_path,
        ]

        try:
            subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT, check=True)
            if os.path.getsize(audio_path) > 1024:
                return audio_path
            log.warning(f"[Transcription] Extracted audio is empty: {video_path}")
            return None
        except subprocess.TimeoutExpired:
            log.error(f"[Transcription] ffmpeg timed out: {video_path}")
            return None
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="ignore")[:300] if e.stderr else str(e)
            log.error(f"[Transcription] ffmpeg failed: {stderr}")
            return None

    @classmethod
    def _run_whisper(cls, audio_path: str) -> dict:
        model = cls._get_model()
        result = cls._transcribe_with_options(model, audio_path, vad_filter=True)
        if not result["text"].strip():
            log.warning("[Transcription] VAD produced no text, retrying without VAD")
            result = cls._transcribe_with_options(model, audio_path, vad_filter=False)
        return result

    @classmethod
    def _transcribe_with_options(cls, model, audio_path: str, vad_filter: bool) -> dict:
        kwargs = {
            "language": "zh",
            "beam_size": 5,
            "vad_filter": vad_filter,
        }
        if vad_filter:
            kwargs["vad_parameters"] = {"min_silence_duration_ms": 500}

        segments, info = model.transcribe(audio_path, **kwargs)

        parts = []
        segment_items = []
        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            parts.append(text)
            segment_items.append(
                {
                    "start": round(float(segment.start), 2),
                    "end": round(float(segment.end), 2),
                    "text": text,
                }
            )
        return {
            "text": "\n".join(parts),
            "segments": segment_items,
            "language": getattr(info, "language", "") or "zh",
        }

    @classmethod
    def _run_baidu(cls, audio_path: str) -> dict:
        if not BAIDU_ASR_API_KEY or not BAIDU_ASR_SECRET_KEY:
            raise RuntimeError("BAIDU_ASR_API_KEY and BAIDU_ASR_SECRET_KEY are required")

        token = cls._get_baidu_access_token()
        parts = []
        segment_items = []

        for chunk in cls._iter_pcm_chunks(audio_path):
            text = cls._recognize_baidu_chunk(chunk["data"], token).strip()
            if not text:
                continue
            parts.append(text)
            segment_items.append(
                {
                    "start": round(float(chunk["start"]), 2),
                    "end": round(float(chunk["end"]), 2),
                    "text": text,
                }
            )

        return {
            "text": "\n".join(parts),
            "segments": segment_items,
            "language": "zh",
        }

    @classmethod
    def _get_baidu_access_token(cls) -> str:
        now = time.time()
        if cls._baidu_token and now < cls._baidu_token_expire_at - 60:
            return cls._baidu_token

        resp = requests.post(
            BAIDU_TOKEN_URL,
            params={
                "grant_type": "client_credentials",
                "client_id": BAIDU_ASR_API_KEY,
                "client_secret": BAIDU_ASR_SECRET_KEY,
            },
            timeout=BAIDU_ASR_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"Baidu token response missing access_token: {data}")

        cls._baidu_token = token
        cls._baidu_token_expire_at = now + int(data.get("expires_in") or 0)
        return cls._baidu_token

    @classmethod
    def _recognize_baidu_chunk(cls, pcm_data: bytes, token: str) -> str:
        if not pcm_data:
            return ""

        payload = {
            "format": "pcm",
            "rate": 16000,
            "channel": 1,
            "cuid": BAIDU_ASR_CUID,
            "token": token,
            "dev_pid": BAIDU_ASR_DEV_PID,
            "len": len(pcm_data),
            "speech": base64.b64encode(pcm_data).decode("ascii"),
        }
        resp = requests.post(
            BAIDU_ASR_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=BAIDU_ASR_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("err_no") != 0:
            raise RuntimeError(f"Baidu ASR error {data.get('err_no')}: {data.get('err_msg')}")
        result = data.get("result") or []
        return str(result[0]) if result else ""

    @classmethod
    def _iter_pcm_chunks(cls, audio_path: str):
        chunk_seconds = max(1, min(55, BAIDU_ASR_CHUNK_SECONDS))
        with wave.open(audio_path, "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frame_rate = wav_file.getframerate()
            if channels != 1 or sample_width != 2 or frame_rate != 16000:
                raise RuntimeError(
                    f"Expected 16 kHz mono 16-bit WAV, got channels={channels}, "
                    f"sample_width={sample_width}, frame_rate={frame_rate}"
                )

            frames_per_chunk = frame_rate * chunk_seconds
            start_frame = 0
            while True:
                data = wav_file.readframes(frames_per_chunk)
                if not data:
                    break
                frame_count = len(data) // (channels * sample_width)
                end_frame = start_frame + frame_count
                yield {
                    "start": start_frame / frame_rate,
                    "end": end_frame / frame_rate,
                    "data": data,
                }
                start_frame = end_frame

    @classmethod
    def _cleanup_audio(cls, audio_path: str | None):
        if audio_path:
            try:
                if os.path.isfile(audio_path):
                    os.remove(audio_path)
            except OSError:
                pass

    @classmethod
    def delete_video_dir(cls, video_path: str):
        """Delete a video file and its parent directory if empty.

        Call this after confirming the transcript is usable.
        """
        try:
            if video_path and os.path.isfile(video_path):
                os.remove(video_path)
                log.info(f"[Transcription] Deleted video: {video_path}")
        except OSError as e:
            log.warning(f"[Transcription] Delete video failed: {e}")

        if video_path:
            parent = Path(video_path).parent
            try:
                if parent.exists() and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass
