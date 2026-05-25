import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))


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
