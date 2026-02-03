from __future__ import annotations
from typing import List, Dict, Any
import re


# Markdown-style headings: #, ##, ###, etc.
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def semantic_chunk(
    text: str,
    *,
    max_chars: int = 3000,
    min_chars: int = 200,
) -> List[Dict[str, Any]]:
    """
    Heading-aware semantic chunker.

    Splits text by semantic boundaries while tracking structure.

    Returns a list of dicts:
    {
        "text": str,
        "metadata": {
            "heading": str | None,
            "heading_level": int | None,
            "section_path": list[str]
        }
    }
    """

    # Normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    lines = text.splitlines()

    chunks: List[Dict[str, Any]] = []

    buffer: list[str] = []
    buf_len = 0

    section_stack: list[str] = []
    current_heading: str | None = None
    current_level: int | None = None

    def flush() -> None:
        nonlocal buffer, buf_len
        if not buffer:
            return

        chunk_text = "\n".join(buffer).strip()
        if not chunk_text:
            buffer = []
            buf_len = 0
            return

        chunks.append(
            {
                "text": chunk_text,
                "metadata": {
                    "heading": current_heading,
                    "heading_level": current_level,
                    "section_path": list(section_stack),
                },
            }
        )

        buffer = []
        buf_len = 0

    for line in lines:
        line = line.rstrip()

        # ---------------- heading detection ----------------
        m = HEADING_RE.match(line)
        if m:
            # finish previous chunk before starting new section
            flush()

            level = len(m.group(1))
            title = m.group(2).strip()

            # maintain section hierarchy
            while len(section_stack) >= level:
                section_stack.pop()
            section_stack.append(title)

            current_heading = title
            current_level = level
            continue

        # ---------------- skip pure whitespace ----------------
        if not line.strip():
            # blank lines act as soft boundaries
            if buf_len >= min_chars:
                flush()
            continue

        # ---------------- size control ----------------
        if buf_len + len(line) > max_chars:
            flush()

        buffer.append(line)
        buf_len += len(line)

        # flush once we have a reasonable semantic unit
        if buf_len >= min_chars:
            flush()

    # flush remainder
    flush()

    return chunks
