import wave

from backend.services import transcription_service as ts


def _write_silent_wav(path, duration_seconds: int):
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\0\0" * 16000 * duration_seconds)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_provider_uses_baidu_when_keys_exist(monkeypatch):
    monkeypatch.setattr(ts, "ASR_PROVIDER", "")
    monkeypatch.setattr(ts, "BAIDU_ASR_API_KEY", "api-key")
    monkeypatch.setattr(ts, "BAIDU_ASR_SECRET_KEY", "secret-key")

    assert ts.TranscriptionService._get_provider() == "baidu"


def test_provider_allows_explicit_whisper(monkeypatch):
    monkeypatch.setattr(ts, "ASR_PROVIDER", "whisper")
    monkeypatch.setattr(ts, "BAIDU_ASR_API_KEY", "api-key")
    monkeypatch.setattr(ts, "BAIDU_ASR_SECRET_KEY", "secret-key")

    assert ts.TranscriptionService._get_provider() == "whisper"


def test_iter_pcm_chunks_splits_16k_mono_wav(tmp_path, monkeypatch):
    wav_path = tmp_path / "speech.wav"
    _write_silent_wav(wav_path, duration_seconds=3)
    monkeypatch.setattr(ts, "BAIDU_ASR_CHUNK_SECONDS", 1)

    chunks = list(ts.TranscriptionService._iter_pcm_chunks(str(wav_path)))

    assert len(chunks) == 3
    assert chunks[0]["start"] == 0
    assert chunks[0]["end"] == 1
    assert len(chunks[0]["data"]) == 16000 * 2
    assert chunks[-1]["start"] == 2
    assert chunks[-1]["end"] == 3


def test_baidu_token_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(ts, "BAIDU_ASR_API_KEY", "api-key")
    monkeypatch.setattr(ts, "BAIDU_ASR_SECRET_KEY", "secret-key")
    monkeypatch.setattr(ts.TranscriptionService, "_baidu_token", "")
    monkeypatch.setattr(ts.TranscriptionService, "_baidu_token_expire_at", 0)

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse({"access_token": "cached-token", "expires_in": 3600})

    monkeypatch.setattr(ts.requests, "post", fake_post)

    assert ts.TranscriptionService._get_baidu_access_token() == "cached-token"
    assert ts.TranscriptionService._get_baidu_access_token() == "cached-token"
    assert len(calls) == 1


def test_recognize_baidu_chunk_sends_json_payload(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeResponse({"err_no": 0, "result": ["你好世界"]})

    monkeypatch.setattr(ts.requests, "post", fake_post)

    text = ts.TranscriptionService._recognize_baidu_chunk(b"abc", "token")

    assert text == "你好世界"
    assert captured["kwargs"]["json"]["format"] == "pcm"
    assert captured["kwargs"]["json"]["rate"] == 16000
    assert captured["kwargs"]["json"]["channel"] == 1
    assert captured["kwargs"]["json"]["token"] == "token"
    assert captured["kwargs"]["json"]["len"] == 3


def test_run_baidu_stitches_chunk_results(tmp_path, monkeypatch):
    wav_path = tmp_path / "speech.wav"
    _write_silent_wav(wav_path, duration_seconds=2)
    monkeypatch.setattr(ts, "BAIDU_ASR_API_KEY", "api-key")
    monkeypatch.setattr(ts, "BAIDU_ASR_SECRET_KEY", "secret-key")
    monkeypatch.setattr(ts, "BAIDU_ASR_CHUNK_SECONDS", 1)
    monkeypatch.setattr(ts.TranscriptionService, "_get_baidu_access_token", classmethod(lambda cls: "token"))

    def fake_recognize(cls, pcm_data, token):
        return "第一段" if len(pcm_data) else ""

    monkeypatch.setattr(ts.TranscriptionService, "_recognize_baidu_chunk", classmethod(fake_recognize))

    result = ts.TranscriptionService._run_baidu(str(wav_path))

    assert result["text"] == "第一段\n第一段"
    assert result["language"] == "zh"
    assert [seg["start"] for seg in result["segments"]] == [0, 1]
