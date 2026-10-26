from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import fitz


HEADING_HINTS = re.compile(
    r"^(?:\d+(?:\.\d+)*[.)]?\s+)?("
    r"investment thesis|valuation|price target|risks?|catalysts?|"
    r"financials?|income statement|balance sheet|cash flow|"
    r"management|industry|competitive|outlook|recommendation|"
    r"bull case|bear case|key takeaways?|summary|appendix|"
    r"dcf|wacc|multiples?|estimates?|guidance|esg|"
    r"directors.? report|management discussion|auditor|"
    r"financial risk management"
    r")\b",
    re.IGNORECASE,
)
NOTE_HEADING = re.compile(r"^NOTE\s+\d+", re.IGNORECASE)
NUMBERED_HEADING = re.compile(r"^\d+(?:\.\d+)+\s+\S")
ALL_CAPS = re.compile(r"^[A-Z0-9][A-Z0-9 /,&:\-]{8,}$")
BOILERPLATE_LINE = re.compile(
    r"(CIN\s*(NO|NUMBER)?\s*:|"
    r"L\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}|"
    r"www\.[\w.-]+|"
    r"page\s+\d+\s+of\s+\d+)",
    re.IGNORECASE,
)
NOT_HEADINGS = {
    "PARTICULARS",
    "TOTAL",
    "NOTE",
    "YEAR ENDED",
    "RS. IN LAKHS",
    "RS IN LAKHS",
    "(RS. IN LAKHS)",
    "CONSOLIDATED",
    "STANDALONE",
}


@dataclass
class PageExtract:
    page_number: int
    text: str
    char_count: int
    has_table: bool
    table_count: int
    empty: bool
    failed: bool
    error: str | None = None
    headings: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    sections: list[tuple[str | None, str]] = field(default_factory=list)


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)


def _norm_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _heading_label(text: str) -> str:
    return text.split(" | ", 1)[0].strip()


def _is_heading(text: str, font_size: float, body_size: float) -> bool:
    cleaned = _heading_label(text)
    if not cleaned or len(cleaned) < 4 or len(cleaned) > 140:
        return False
    if BOILERPLATE_LINE.search(cleaned):
        return False
    key = re.sub(r"\s+", " ", cleaned).upper()
    if key in NOT_HEADINGS:
        return False
    if cleaned.endswith(".") and len(cleaned) > 40:
        return False
    if NOTE_HEADING.match(cleaned) or NUMBERED_HEADING.match(cleaned):
        return True
    if HEADING_HINTS.match(cleaned):
        return True
    if font_size >= body_size + 1.8 and len(cleaned.split()) <= 14:
        return True
    if ALL_CAPS.match(cleaned) and len(cleaned.split()) <= 8 and not re.search(r"\d{2,}", cleaned):
        if cleaned.upper().startswith("NOTE"):
            return True
        if HEADING_HINTS.match(cleaned):
            return True
    return False


def _extract_tables(page: fitz.Page) -> tuple[list[str], list[tuple[float, float, float, float]]]:
    tables: list[str] = []
    bboxes: list[tuple[float, float, float, float]] = []
    try:
        finder = page.find_tables()
        found = list(getattr(finder, "tables", finder) or [])
    except Exception:
        found = []
    for table in found:
        bbox = tuple(table.bbox)  # type: ignore[arg-type]
        try:
            markdown = table.to_markdown()
        except Exception:
            try:
                rows = table.extract()
                lines = []
                for row in rows:
                    cells = [str(c).strip() if c is not None else "" for c in row]
                    lines.append(" | ".join(cells))
                markdown = "\n".join(lines)
            except Exception:
                markdown = ""
        if markdown and markdown.strip() and markdown.count("\n") >= 1:
            tables.append(markdown.strip())
            bboxes.append(bbox)  # type: ignore[arg-type]
    return tables, bboxes


def _merge_row(spans: list[dict]) -> dict:
    spans = sorted(spans, key=lambda s: s["x0"])
    parts: list[str] = []
    prev_x1 = None
    for sp in spans:
        token = re.sub(r"\s+", " ", sp["text"]).strip()
        if not token:
            continue
        if prev_x1 is None:
            parts.append(token)
        else:
            gap = sp["x0"] - prev_x1
            if gap > 14:
                parts.append(" | ")
                parts.append(token)
            elif parts[-1].endswith("-") and token[:1].islower():
                parts[-1] = parts[-1][:-1] + token
            else:
                parts.append(" " + token)
        prev_x1 = sp["x1"]
    text = "".join(parts)
    text = re.sub(r"\s*\|\s*", " | ", text)
    text = re.sub(r" +", " ", text).strip()
    avg_size = sum(s["size"] for s in spans) / max(len(spans), 1)
    y0 = min(s["y0"] for s in spans)
    y1 = max(s["y1"] for s in spans)
    x0 = min(s["x0"] for s in spans)
    x1 = max(s["x1"] for s in spans)
    return {
        "text": text,
        "norm": _norm_line(text),
        "size": avg_size,
        "y0": y0,
        "y1": y1,
        "bbox": (x0, y0, x1, y1),
    }


def _page_rows(page: fitz.Page) -> tuple[list[dict], float]:
    blocks = page.get_text("dict").get("blocks", [])
    spans: list[dict] = []
    sizes: list[float] = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                raw = span.get("text", "")
                if not raw.strip():
                    continue
                bbox = span.get("bbox", (0, 0, 0, 0))
                size = float(span.get("size", 11))
                sizes.append(size)
                spans.append(
                    {
                        "text": raw,
                        "x0": float(bbox[0]),
                        "y0": float(bbox[1]),
                        "x1": float(bbox[2]),
                        "y1": float(bbox[3]),
                        "size": size,
                    }
                )
    body_size = sorted(sizes)[len(sizes) // 2] if sizes else 11.0
    if not spans:
        return [], body_size
    spans.sort(key=lambda s: (s["y0"], s["x0"]))
    rows: list[list[dict]] = []
    current = [spans[0]]
    anchor = spans[0]["y0"]
    for sp in spans[1:]:
        if abs(sp["y0"] - anchor) <= 3.5:
            current.append(sp)
        else:
            rows.append(current)
            current = [sp]
            anchor = sp["y0"]
    rows.append(current)
    height = float(page.rect.height or 1)
    merged = []
    for group in rows:
        row = _merge_row(group)
        if len(row["text"]) <= 2 and not re.search(r"[A-Za-z0-9]", row["text"]):
            continue
        row["body_size"] = body_size
        row["y_frac"] = row["y0"] / height
        merged.append(row)
    return merged, body_size


def _boilerplate_norms(all_page_rows: list[list[dict]]) -> set[str]:
    n_pages = max(len(all_page_rows), 1)
    header_counts: Counter[str] = Counter()
    for rows in all_page_rows:
        seen = set()
        for row in rows:
            if row["y_frac"] >= 0.08 and row["y_frac"] <= 0.92:
                continue
            norm = row["norm"]
            if not norm or norm in seen:
                continue
            seen.add(norm)
            header_counts[norm] += 1
    threshold = max(3, int(0.22 * n_pages))
    boiler: set[str] = set()
    for norm, count in header_counts.items():
        if count >= threshold and len(norm) <= 120:
            boiler.add(norm)
    return boiler


def _is_skipped_line(line: dict, boilerplate: set[str]) -> bool:
    text = line["text"]
    if line["norm"] in boilerplate:
        return True
    if BOILERPLATE_LINE.search(text):
        return True
    if line["y_frac"] < 0.08 or line["y_frac"] > 0.92:
        if len(line["norm"]) <= 80 and (
            "LIMITED" in text.upper() or "PRIVATE" in text.upper() or BOILERPLATE_LINE.search(text)
        ):
            return True
    return False


def _heading_only(heading: str | None, text: str) -> bool:
    body = _norm_line(text)
    if not body:
        return True
    head = _norm_line(heading or "")
    if head and body.lower() == head.lower():
        return True
    return False


def extract_pdf(path: str, progress_cb=None) -> list[PageExtract]:
    doc = fitz.open(path)
    pages: list[PageExtract] = []
    total = doc.page_count
    last_heading: str | None = None

    page_meta: list[tuple[list[str], list[tuple[float, float, float, float]], list[dict], float]] = []
    for i, page in enumerate(doc):
        if progress_cb:
            progress_cb(
                "parsing",
                (i + 0.2) / max(total, 1),
                f"Extracting page {i + 1}/{total}",
            )
        try:
            tables, table_bboxes = _extract_tables(page)
            rows, body_size = _page_rows(page)
            page_meta.append((tables, table_bboxes, rows, body_size))
        except Exception:
            page_meta.append(([], [], [], 11.0))

    boilerplate = _boilerplate_norms([meta[2] for meta in page_meta])

    for i, (tables, table_bboxes, rows, body_size) in enumerate(page_meta):
        page_number = i + 1
        try:
            labeled_tables: list[str] = []
            for markdown, bbox in zip(tables, table_bboxes):
                heading = None
                for row in reversed(rows):
                    if row["y0"] >= bbox[1] - 1:
                        continue
                    if _is_skipped_line(row, boilerplate):
                        continue
                    if _is_heading(row["text"], row["size"], body_size):
                        heading = row["text"]
                        break
                labeled_tables.append(f"{heading}\n{markdown}" if heading else markdown)

            kept_rows = []
            for row in rows:
                if _is_skipped_line(row, boilerplate):
                    continue
                if any(_overlap(row["bbox"], tb) for tb in table_bboxes):
                    continue
                kept_rows.append(row)

            headings: list[str] = []
            text_parts: list[str] = []
            sections: list[tuple[str | None, str]] = []
            current_heading = last_heading
            current_lines: list[str] = []

            def flush() -> None:
                nonlocal current_lines
                if not current_lines:
                    return
                body = "\n".join(current_lines)
                if not _heading_only(current_heading, body):
                    sections.append((current_heading, body))
                current_lines = []

            for row in kept_rows:
                line_text = row["text"]
                if _is_heading(line_text, row["size"], body_size):
                    flush()
                    current_heading = _heading_label(line_text)
                    last_heading = current_heading
                    headings.append(current_heading)
                    continue
                current_lines.append(line_text)
                text_parts.append(line_text)
            flush()

            if labeled_tables:
                for table in labeled_tables:
                    first = table.split("\n", 1)[0]
                    table_heading = first if _is_heading(first, body_size + 2, body_size) else (
                        headings[-1] if headings else last_heading
                    )
                    sections.append((table_heading, table))
                    text_parts.append(table)

            text = "\n".join(text_parts).strip()
            char_count = len(text)
            empty = char_count < 20 and not labeled_tables
            pages.append(
                PageExtract(
                    page_number=page_number,
                    text=text,
                    char_count=len(text),
                    has_table=bool(labeled_tables) or any(" | " in t for t in text_parts),
                    table_count=len(labeled_tables),
                    empty=empty,
                    failed=False,
                    headings=headings,
                    tables=labeled_tables,
                    sections=sections,
                )
            )
        except Exception as exc:
            pages.append(
                PageExtract(
                    page_number=page_number,
                    text="",
                    char_count=0,
                    has_table=False,
                    table_count=0,
                    empty=True,
                    failed=True,
                    error=str(exc),
                )
            )
    doc.close()
    if progress_cb:
        progress_cb("parsing", 1.0, f"Extracted {total} pages")
    return pages
