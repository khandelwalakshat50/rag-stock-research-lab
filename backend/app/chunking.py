from __future__ import annotations

import re
from dataclasses import dataclass

from .pdf_extract import PageExtract

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


@dataclass
class TextChunk:
    chunk_index: int
    page_number: int
    heading: str | None
    is_table: bool
    text: str
    char_length: int


def _split_long(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.strip()
    if len(text) <= chunk_size:
        return [text] if text else []

    sentences = SENTENCE_SPLIT.split(text)
    pieces: list[str] = []
    buf = ""
    for sentence in sentences:
        candidate = (buf + " " + sentence).strip() if buf else sentence
        if len(candidate) <= chunk_size:
            buf = candidate
            continue
        if buf:
            pieces.append(buf)
        if len(sentence) > chunk_size:
            start = 0
            while start < len(sentence):
                end = min(start + chunk_size, len(sentence))
                pieces.append(sentence[start:end])
                start = max(end - overlap, end) if end < len(sentence) else end
            buf = ""
        else:
            buf = sentence
    if buf:
        pieces.append(buf)

    if overlap <= 0 or len(pieces) <= 1:
        return pieces

    overlapped: list[str] = [pieces[0]]
    for piece in pieces[1:]:
        prev = overlapped[-1]
        tail = prev[-overlap:]
        space = tail.rfind(" ")
        if space > overlap // 3:
            tail = tail[space + 1 :]
        merged = (tail + " " + piece).strip()
        overlapped.append(merged if len(merged) <= chunk_size + overlap else piece)
    return overlapped


BOILERPLATE_CHUNK = re.compile(
    r"(CIN\s*(NO|NUMBER)?\s*:|L\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6})",
    re.IGNORECASE,
)
TITLE_STUB = re.compile(r"^(note\s+\d+\b|particulars|total)\b", re.IGNORECASE)


def _norm_chunk(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def is_low_info_chunk(text: str, heading: str | None = None, is_table: bool = False) -> bool:
    """True for title-only stubs, OCR junk, and other chunks that should not go to the LLM."""
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return True
    if BOILERPLATE_CHUNK.search(compact) and len(compact) < 160:
        return True
    letters = sum(ch.isalpha() for ch in compact)
    if len(compact) >= 12 and letters / len(compact) < 0.38:
        return True
    if compact.count("~") >= 2:
        return True
    if heading and compact.lower() == _norm_chunk(heading):
        return True
    if not is_table and len(compact) < 80:
        if TITLE_STUB.match(compact) or compact.upper() == compact:
            return True
        if letters < 24:
            return True
    return False


def _is_boilerplate_chunk(text: str, is_table: bool, heading: str | None = None) -> bool:
    return is_low_info_chunk(text, heading, is_table)


def chunk_pages(
    pages: list[PageExtract],
    chunk_size: int = 1000,
    overlap: int = 200,
) -> list[TextChunk]:
    raw: list[tuple[int, str | None, bool, str]] = []
    last_heading: str | None = None

    for page in pages:
        if page.sections:
            for heading, text in page.sections:
                body = text.strip()
                if not body:
                    continue
                if heading and heading not in body[: min(len(body), len(heading) + 8)]:
                    body = f"{heading}\n{body}"
                is_table = body.count(" | ") >= 2 and body.count("\n") >= 1
                raw.append((page.page_number, heading or last_heading, is_table, body))
                if heading:
                    last_heading = heading
        elif page.tables:
            for table in page.tables:
                raw.append((page.page_number, last_heading, True, table))
        elif page.text.strip():
            heading = page.headings[-1] if page.headings else last_heading
            raw.append((page.page_number, heading, False, page.text.strip()))
        if page.headings:
            last_heading = page.headings[-1]

    chunks: list[TextChunk] = []
    idx = 0
    seen: set[str] = set()
    for page_number, heading, is_table, text in raw:
        if is_table:
            # Keep tables intact. Only split enormous tables by row groups.
            if len(text) <= chunk_size * 2:
                parts = [text]
            else:
                rows = text.split("\n")
                header = rows[0] if rows else ""
                parts = []
                buf = header
                for row in rows[1:]:
                    candidate = buf + "\n" + row
                    if len(candidate) > chunk_size and buf != header:
                        parts.append(buf)
                        buf = header + "\n" + row
                    else:
                        buf = candidate
                if buf.strip():
                    parts.append(buf)
        else:
            parts = _split_long(text, chunk_size, overlap)

        for part in parts:
            if _is_boilerplate_chunk(part, is_table, heading):
                continue
            key = _norm_chunk(part)
            if key in seen:
                continue
            seen.add(key)
            chunks.append(
                TextChunk(
                    chunk_index=idx,
                    page_number=page_number,
                    heading=heading,
                    is_table=is_table,
                    text=part,
                    char_length=len(part),
                )
            )
            idx += 1
    return chunks


def chunk_histogram(chunks: list[TextChunk], bin_size: int = 200) -> list[dict]:
    if not chunks:
        return []
    max_len = max(c.char_length for c in chunks)
    bins = []
    start = 0
    while start <= max_len:
        end = start + bin_size
        count = sum(1 for c in chunks if start <= c.char_length < end)
        bins.append({"range": f"{start}-{end - 1}", "count": count})
        start = end
    return bins
