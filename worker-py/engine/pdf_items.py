"""Raw checklist-item extraction from a PM report PDF, using PyMuPDF.

This is the Python port of the frontend `extractTasksFromPdf`. It deliberately
produces the SAME raw (messy, ~3x repeated) text the browser feeds to the LLM
cleaning passes — so downstream parity holds. Cleaning happens in engine.llm.

Coordinate note: pdf.js reports Y in a bottom-left origin (Y increases upward);
PyMuPDF uses a top-left origin (Y increases downward). We convert each span's
baseline origin to the pdf.js orientation via `Y = page_height - origin_y`, so
the exact same comparison/sort logic as the browser applies.
"""
import re
import unicodedata
from functools import cmp_to_key

import fitz  # PyMuPDF

ARABIC      = re.compile(r'[؀-ۿ]')
OK_RE       = re.compile(r'^ok$', re.I)
NOTOK_RE    = re.compile(r'not\s*ok', re.I)
NOTOK_EXACT = re.compile(r'^(ok|not\s*ok)$', re.I)
CHECK_GLYPH = re.compile(r'[☑☐✓✗]')  # ☑ ☐ ✓ ✗


def fix_persian(text: str) -> str:
    """Mirror of the frontend fixPersian(): NFKC collapses Arabic presentation
    forms (U+FB50–FDFF / U+FE70–FEFF) back to canonical letters."""
    return unicodedata.normalize('NFKC', text) if text else text


def _page_fragments(page):
    """Text fragments as {'str','x','y'} with Y in pdf.js (bottom-left) space."""
    H = page.rect.height
    out = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                t = (span["text"] or "").strip()
                if not t:
                    continue
                ox, oy = span["origin"]
                out.append({"str": t, "x": ox, "y": H - oy})
    return out


def _row_cmp(a, b):
    """Same comparator as the browser (Persian path): different lines sort by Y
    ascending; within a line (|dy|<=3) sort by X descending (RTL)."""
    if abs(a["y"] - b["y"]) > 3:
        return -1 if a["y"] < b["y"] else 1
    return -1 if a["x"] > b["x"] else (1 if a["x"] < b["x"] else 0)


def extract_raw_items(pdf_path):
    """Return [{'num','desc','result'}] of RAW (uncleaned) items, plus enough
    to feed the LLM cleaning passes. `result` is left as None here (checkbox
    detection is a separate LLM/vision step)."""
    doc = fitz.open(pdf_path)
    full_text = doc[0].get_text() if doc.page_count else ""
    is_english = not bool(ARABIC.search(full_text))
    tasks = []
    counter = 1
    for page in doc:
        items = _page_fragments(page)
        ok_items    = [it for it in items if OK_RE.match(it["str"])]
        notok_items = [it for it in items if NOTOK_RE.search(it["str"])]
        anchors = [n for n in notok_items
                   if any(abs(o["y"] - n["y"]) <= 10 for o in ok_items)]
        if not anchors:
            continue
        anchor_ys = sorted((a["y"] for a in anchors), reverse=True)
        n = len(anchor_ys)
        for i, y in enumerate(anchor_ys):
            top    = 1e5  if i == 0   else (anchor_ys[i-1] + y) / 2
            bottom = -1e5 if i == n-1 else (y + anchor_ys[i+1]) / 2
            box = [it for it in items
                   if it["y"] < top and it["y"] > bottom and it["y"] > bottom + 3
                   and not NOTOK_EXACT.match(it["str"].strip())
                   and not CHECK_GLYPH.search(it["str"])]
            box.sort(key=cmp_to_key(_row_cmp))
            raw = re.sub(r'\s+', ' ', ' '.join(it["str"] for it in box)).strip()
            desc = fix_persian(raw) if ARABIC.search(raw) else raw
            if len(desc) > 5:
                tasks.append({"num": counter, "desc": desc, "result": None})
                counter += 1
    return {"items": tasks, "is_english": is_english}


if __name__ == "__main__":
    import sys
    out = extract_raw_items(sys.argv[1])
    print("is_english:", out["is_english"])
    for t in out["items"]:
        print(f'{t["num"]:>2}. {t["desc"][:160]}')
