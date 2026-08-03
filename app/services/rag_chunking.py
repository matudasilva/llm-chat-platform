"""Pure chunking functions for RAG ingestion (spec.md §Context, §Design decisions 3).

Recursive character splitting (~500 chars, 10-20% overlap), header-aware for
Markdown, function/class-level for Python. No I/O, no DB, no provider calls —
kept pure so it stays in the hermetic default test suite (spec.md §Design
decisions 10).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

DEFAULT_CHUNK_SIZE = 500
DEFAULT_OVERLAP = 75  # 15% of 500, within the 10-20% band.

_MD_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class RawChunk:
    text: str
    section: str  # header path ("## Foo > ### Bar") or function/class qualname


def split_recursive(text: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[str]:
    """Fixed-size character windows with overlap; never returns an empty chunk."""
    stripped = text.strip()
    if not stripped:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    if len(stripped) <= chunk_size:
        return [stripped]

    chunks: list[str] = []
    start = 0
    step = chunk_size - overlap
    while start < len(stripped):
        end = min(start + chunk_size, len(stripped))
        piece = stripped[start:end].strip()
        if piece:
            chunks.append(piece)
        if end == len(stripped):
            break
        start += step
    return chunks


def split_markdown(text: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[RawChunk]:
    """Header-aware: split by Markdown headers first, then recursively within each section."""
    matches = list(_MD_HEADER_RE.finditer(text))
    if not matches:
        return [RawChunk(text=c, section="") for c in split_recursive(text, chunk_size=chunk_size, overlap=overlap)]

    sections: list[tuple[str, str]] = []
    path: list[tuple[int, str]] = []  # (level, title) stack

    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()

        while path and path[-1][0] >= level:
            path.pop()
        path.append((level, title))
        section_path = " > ".join(t for _, t in path)

        section_text = f"{title}\n{body}".strip() if body else title
        sections.append((section_path, section_text))

    chunks: list[RawChunk] = []
    for section_path, section_text in sections:
        for piece in split_recursive(section_text, chunk_size=chunk_size, overlap=overlap):
            chunks.append(RawChunk(text=piece, section=section_path))
    return chunks


def split_python(source: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[RawChunk]:
    """Function/class-level: split by top-level def/class boundaries, then recursively within each."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [RawChunk(text=c, section="") for c in split_recursive(source, chunk_size=chunk_size, overlap=overlap)]

    lines = source.splitlines(keepends=True)
    top_level = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]

    if not top_level:
        return [RawChunk(text=c, section="") for c in split_recursive(source, chunk_size=chunk_size, overlap=overlap)]

    chunks: list[RawChunk] = []
    boundaries = sorted(node.lineno for node in top_level)
    preamble_end = boundaries[0] - 1
    preamble = "".join(lines[:preamble_end]).strip()
    if preamble:
        for piece in split_recursive(preamble, chunk_size=chunk_size, overlap=overlap):
            chunks.append(RawChunk(text=piece, section="<module>"))

    for i, node in enumerate(top_level):
        start = node.lineno - 1
        end = top_level[i + 1].lineno - 1 if i + 1 < len(top_level) else len(lines)
        body = "".join(lines[start:end]).strip()
        if not body:
            continue
        for piece in split_recursive(body, chunk_size=chunk_size, overlap=overlap):
            chunks.append(RawChunk(text=piece, section=node.name))
    return chunks


def chunk_document(doc_type: str, text: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[RawChunk]:
    if doc_type == "markdown":
        return split_markdown(text, chunk_size=chunk_size, overlap=overlap)
    if doc_type == "python":
        return split_python(text, chunk_size=chunk_size, overlap=overlap)
    return [RawChunk(text=c, section="") for c in split_recursive(text, chunk_size=chunk_size, overlap=overlap)]
