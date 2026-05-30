import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))


def test_parse_pdf_with_mineru_agent_api(monkeypatch, tmp_path):
    import requests
    from backend.services import document_parser as parser

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(parser.config, "MINERU_API_BASE", "https://mineru.example/api/v1/agent")
    monkeypatch.setattr(parser.config, "MINERU_TIMEOUT", 10)
    monkeypatch.setattr(parser.config, "MINERU_POLL_INTERVAL", 1)
    monkeypatch.setattr(parser.time, "sleep", lambda _: None)

    class DummyResponse:
        def __init__(self, payload=None, text=""):
            self.payload = payload or {}
            self.text = text

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_post(url, json, headers, timeout):
        assert url == "https://mineru.example/api/v1/agent/parse/file"
        assert json["filename"] == "sample.pdf"
        return DummyResponse({"data": {"task_id": "task-1", "upload_url": "https://upload.example/pdf"}})

    def fake_put(url, data, timeout):
        assert url == "https://upload.example/pdf"
        assert data.read() == b"%PDF-1.4"
        return DummyResponse()

    def fake_get(url, headers, timeout):
        assert url == "https://mineru.example/api/v1/agent/parse/task-1"
        return DummyResponse({"data": {"status": "done", "markdown": "# Parsed\n\ncontent"}})

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "put", fake_put)
    monkeypatch.setattr(requests, "get", fake_get)

    assert parser._parse_pdf_with_mineru(str(pdf)) == "# Parsed\n\ncontent"


def test_parse_pdf_document_uses_mineru_markdown(monkeypatch, tmp_path):
    from backend.services import document_parser as parser

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(parser.config, "PDF_PARSER", "mineru")
    monkeypatch.setattr(parser, "_parse_pdf_with_mineru", lambda _: "# Heading\n\ncontent")

    text, file_type = parser.parse_pdf_document(str(pdf))

    assert text == "# Heading\n\ncontent"
    assert file_type == "markdown"


def test_parse_pdf_document_falls_back_to_pymupdf(monkeypatch, tmp_path):
    from backend.services import document_parser as parser

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(parser.config, "PDF_PARSER", "mineru")

    def failing_mineru(_):
        raise RuntimeError("mineru unavailable")

    monkeypatch.setattr(parser, "_parse_pdf_with_mineru", failing_mineru)
    monkeypatch.setattr(parser, "_parse_pdf_with_pymupdf", lambda _: "plain text")

    text, file_type = parser.parse_pdf_document(str(pdf))

    assert text == "plain text"
    assert file_type == "pdf"


def test_chunk_markdown_by_headings_preserves_title_path():
    from backend.services.document_parser import chunk_markdown_by_headings

    markdown = """# Agent Evaluation

Intro text.

## Tool Accuracy

Check whether the agent chooses the correct tool and arguments.

## Hallucination Rate

Measure unsupported claims.
"""

    chunks = chunk_markdown_by_headings(markdown, chunk_size=500, overlap=50)

    assert len(chunks) == 3
    assert chunks[0].startswith("[Title Path] Agent Evaluation")
    assert "[Title Path] Agent Evaluation > Tool Accuracy" in chunks[1]
    assert "correct tool and arguments" in chunks[1]
    assert "[Title Path] Agent Evaluation > Hallucination Rate" in chunks[2]


def test_chunk_markdown_by_headings_ignores_headings_inside_code_fences():
    from backend.services.document_parser import chunk_markdown_by_headings

    markdown = """# Real Heading

```md
# Not A Heading
```

Body after code.
"""

    chunks = chunk_markdown_by_headings(markdown, chunk_size=500, overlap=50)

    assert len(chunks) == 1
    assert "[Title Path] Real Heading" in chunks[0]
    assert "# Not A Heading" in chunks[0]


def test_chunk_markdown_by_headings_falls_back_without_headings():
    from backend.services.document_parser import chunk_markdown_by_headings

    markdown = "first paragraph\n\nsecond paragraph"

    chunks = chunk_markdown_by_headings(markdown, chunk_size=500, overlap=50)

    assert chunks == ["first paragraph\n\nsecond paragraph"]


def test_chunk_markdown_by_headings_splits_long_section_with_repeated_path():
    from backend.services.document_parser import chunk_markdown_by_headings

    body = "\n\n".join([f"Paragraph {i} with repeated Agent evaluation details." for i in range(8)])
    markdown = f"# Agent Evaluation\n\n{body}"

    chunks = chunk_markdown_by_headings(markdown, chunk_size=180, overlap=20)

    assert len(chunks) > 1
    assert all(chunk.startswith("[Title Path] Agent Evaluation") for chunk in chunks)
