from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz

from app.chunking import chunk_pages
from app.pdf_extract import extract_pdf


def build_sample_pdf(path: Path) -> None:
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "INVESTMENT THESIS", fontsize=16)
    p1.insert_text(
        (72, 110),
        "We initiate coverage of Acme Robotics (ACME) with a Buy rating and a $42 price target. "
        "The company is converting a robotics backlog into recurring software revenue. "
        "Our thesis hinges on 30% software mix by FY2027 and operating leverage in North America.",
        fontsize=11,
    )
    p1.insert_text((72, 190), "VALUATION", fontsize=16)
    p1.insert_text(
        (72, 220),
        "We use a 10-year DCF with 9.5% WACC and 3.0% terminal growth. "
        "The DCF supports $40-$45, and 22x FY2026E EPS of $1.90 implies $42.",
        fontsize=11,
    )

    p2 = doc.new_page()
    p2.insert_text((72, 72), "FINANCIALS", fontsize=16)
    p2.insert_text((72, 110), "Revenue | EBITDA | EPS", fontsize=11)
    p2.insert_text((72, 128), "FY24  | 1200 | 210 | 1.10", fontsize=11)
    p2.insert_text((72, 146), "FY25E | 1480 | 280 | 1.45", fontsize=11)
    p2.insert_text((72, 164), "FY26E | 1810 | 360 | 1.90", fontsize=11)
    p2.insert_text((72, 200), "The table above should stay intact as a single retrieval unit when possible.", fontsize=11)

    p3 = doc.new_page()
    p3.insert_text((72, 36), "AEROFLEX INDUSTRIES LIMITED", fontsize=9)
    p3.insert_text((72, 50), "( CIN NO : L27509MH1993PLC074576)", fontsize=8)
    p3.insert_text((72, 72), "RISKS", fontsize=16)
    p3.insert_text(
        (72, 110),
        "Key risks include customer concentration (top 3 = 41% of sales), slower factory automation capex, "
        "and a higher-for-longer rate environment that would lift WACC and compress the multiple.",
        fontsize=11,
    )

    # Running letterhead on extra pages should not become its own retrieved chunks.
    for _ in range(4):
        extra = doc.new_page()
        extra.insert_text((72, 36), "AEROFLEX INDUSTRIES LIMITED", fontsize=9)
        extra.insert_text((72, 50), "( CIN NO : L27509MH1993PLC074576)", fontsize=8)
        extra.insert_text((72, 110), "Notes to the financial statements continue on this page.", fontsize=11)

    p4 = doc.new_page()
    p4.insert_text((72, 72), "NOTE 24: COST OF MATERIAL CONSUMED", fontsize=13)
    p4.insert_text((72, 110), "Opening Stock of Raw Material", fontsize=10)
    p4.insert_text((380, 110), "2,917.89", fontsize=10)
    p4.insert_text((480, 110), "1,813.78", fontsize=10)
    p4.insert_text((72, 132), "COST OF MATERIAL CONSUMED", fontsize=10)
    p4.insert_text((380, 132), "24,254.82", fontsize=10)
    p4.insert_text((480, 132), "22,034.16", fontsize=10)
    doc.save(path)
    doc.close()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "sample.pdf"
        build_sample_pdf(pdf)
        pages = extract_pdf(str(pdf))
        assert len(pages) == 8, pages
        assert pages[0].char_count > 50
        assert any("INVESTMENT THESIS" in h for p in pages for h in p.headings) or "INVESTMENT THESIS" in pages[0].text
        letterhead_only = 0
        for p in pages:
            joined = " ".join(p.text.split())
            if joined.startswith("AEROFLEX") and "customer concentration" not in joined.lower() and "Notes to the financial" not in joined:
                letterhead_only += 1
        assert letterhead_only == 0, "running CIN headers should be stripped from page text"
        chunks = chunk_pages(pages, chunk_size=400, overlap=80)
        assert chunks, "expected chunks"
        assert all(c.page_number >= 1 for c in chunks)
        joined = " ".join(c.text for c in chunks)
        assert "$42" in joined
        assert "WACC" in joined
        assert "customer concentration" in joined
        assert "Notes to the financial statements" in joined
        assert "24,254.82" in joined
        assert not any(c.text.strip() in {"COST OF MATERIAL CONSUMED", "NOTE 24: COST OF MATERIAL CONSUMED"} for c in chunks)
        assert not any("L27509MH1993PLC074576" in c.text and len(c.text) < 160 for c in chunks)
        print(f"ok: {len(pages)} pages, {len(chunks)} chunks")
        for c in chunks:
            print(f"  chunk {c.chunk_index} p.{c.page_number} table={c.is_table} len={c.char_length} heading={c.heading!r}")


if __name__ == "__main__":
    main()
