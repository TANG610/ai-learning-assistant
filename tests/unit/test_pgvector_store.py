import sys
import types

from backend.services.vector_store import PgVectorStore


def test_pgvector_embedding_request_passes_configured_dimension(monkeypatch):
    calls = []

    class FakeEmbeddings:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                data=[types.SimpleNamespace(embedding=[0.1, 0.2, 0.3])]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.embeddings = FakeEmbeddings()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setattr("config.EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr("config.EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr("config.EMBEDDING_API_MODEL", "text-embedding-v4")
    monkeypatch.setattr("config.EMBEDDING_DIMENSION", 1536)

    embeddings = PgVectorStore()._embed(["hello"])

    assert embeddings == [[0.1, 0.2, 0.3]]
    assert calls == [
        {
            "model": "text-embedding-v4",
            "input": ["hello"],
            "dimensions": 1536,
        }
    ]
