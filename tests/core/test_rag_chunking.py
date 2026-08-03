from __future__ import annotations

import pytest

from app.services.rag_chunking import (
    chunk_document,
    split_markdown,
    split_python,
    split_recursive,
)


def test_split_recursive_returns_single_chunk_when_shorter_than_chunk_size() -> None:
    text = "short document"
    assert split_recursive(text, chunk_size=500, overlap=75) == [text]


def test_split_recursive_empty_document_returns_no_chunks() -> None:
    assert split_recursive("", chunk_size=500, overlap=75) == []
    assert split_recursive("   \n  ", chunk_size=500, overlap=75) == []


def test_split_recursive_document_longer_than_one_chunk() -> None:
    text = "x" * 1200
    chunks = split_recursive(text, chunk_size=500, overlap=75)
    assert len(chunks) == 3
    assert all(len(c) <= 500 for c in chunks)


def test_split_recursive_overlap_is_shared_between_consecutive_chunks() -> None:
    text = "".join(f"{i:04d}" for i in range(200))  # deterministic, indexable content
    chunks = split_recursive(text, chunk_size=100, overlap=20)
    # Last 20 chars of chunk[i] equal the first 20 chars of chunk[i+1]'s source window.
    assert chunks[0][-20:] == text[80:100]
    assert chunks[1][:20] == text[80:100]


def test_split_recursive_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError):
        split_recursive("x" * 10, chunk_size=100, overlap=100)
    with pytest.raises(ValueError):
        split_recursive("x" * 10, chunk_size=100, overlap=-1)


def test_split_markdown_header_boundaries_produce_separate_sections() -> None:
    md = "# Title\nIntro.\n\n## Section A\nContent A.\n\n## Section B\nContent B."
    chunks = split_markdown(md, chunk_size=500, overlap=75)
    sections = {c.section for c in chunks}
    assert any("Section A" in s for s in sections)
    assert any("Section B" in s for s in sections)
    assert not any("Section A" in c.text and "Content B" in c.text for c in chunks)


def test_split_markdown_nested_headers_build_a_path() -> None:
    md = "# Top\n\n## Mid\n\n### Leaf\nbody text"
    chunks = split_markdown(md, chunk_size=500, overlap=75)
    leaf_chunks = [c for c in chunks if "body text" in c.text]
    assert leaf_chunks
    assert leaf_chunks[0].section == "Top > Mid > Leaf"


def test_split_markdown_document_shorter_than_one_chunk() -> None:
    md = "# Only header\nshort body"
    chunks = split_markdown(md, chunk_size=500, overlap=75)
    assert len(chunks) == 1


def test_split_markdown_empty_document_returns_no_chunks() -> None:
    assert split_markdown("", chunk_size=500, overlap=75) == []


def test_split_markdown_no_headers_falls_back_to_recursive() -> None:
    text = "plain prose with no markdown headers at all, just text."
    chunks = split_markdown(text, chunk_size=500, overlap=75)
    assert len(chunks) == 1
    assert chunks[0].section == ""


def test_split_python_splits_by_top_level_function_and_class() -> None:
    source = (
        "import os\n\n"
        "def foo():\n"
        "    return 1\n\n"
        "class Bar:\n"
        "    def method(self):\n"
        "        return 2\n"
    )
    chunks = split_python(source, chunk_size=500, overlap=75)
    sections = {c.section for c in chunks}
    assert "foo" in sections
    assert "Bar" in sections
    foo_chunk = next(c for c in chunks if c.section == "foo")
    assert "return 1" in foo_chunk.text
    assert "return 2" not in foo_chunk.text


def test_split_python_module_level_code_before_first_def_is_preamble() -> None:
    source = "CONSTANT = 1\n\ndef foo():\n    return CONSTANT\n"
    chunks = split_python(source, chunk_size=500, overlap=75)
    preamble = [c for c in chunks if c.section == "<module>"]
    assert preamble
    assert "CONSTANT = 1" in preamble[0].text


def test_split_python_falls_back_to_recursive_on_syntax_error() -> None:
    broken = "def foo(:\n    this is not valid python"
    chunks = split_python(broken, chunk_size=500, overlap=75)
    assert len(chunks) == 1
    assert chunks[0].section == ""


def test_split_python_falls_back_to_recursive_when_no_top_level_defs() -> None:
    script = "import os\nprint(os.getcwd())\n"
    chunks = split_python(script, chunk_size=500, overlap=75)
    assert len(chunks) == 1
    assert chunks[0].section == ""


def test_chunk_document_dispatches_by_doc_type() -> None:
    md_chunks = chunk_document("markdown", "# H\nbody")
    py_chunks = chunk_document("python", "def f():\n    pass\n")
    other_chunks = chunk_document("text", "plain text body")
    assert md_chunks and py_chunks and other_chunks
