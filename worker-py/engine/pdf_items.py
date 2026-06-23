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


def _norm(s):
    """Aggressive normalisation for comparing lines (drops marks, spaces,
    punctuation, digits) so the 3 repeated table rows compare equal."""
    s = re.sub(r'[‌​‎‏­ً-ٟ]', '', s)
    return re.sub(r'[\s.,،؛;:()\-\d]', '', unicodedata.normalize('NFKC', s)).strip()


def _clean_box(box):
    """Deterministically turn a row's raw fragments into ONE clean description.

    PM reports repeat each item's description across ~3 table rows (text row,
    checkbox row, photo row); header pages also bleed header fields in. We:
      1. group fragments into lines (Y bands), keeping ascending-Y reading order;
      2. keep lines that REPEAT (the description appears >=2x) and drop one-off
         lines (headers/noise) — falling back to all lines if nothing repeats;
      3. keep the first occurrence of each unique line, NFKC-normalise, and strip
         a leading item number.
    No LLM involved.
    """
    rows = sorted(box, key=lambda it: it["y"])
    lines = []
    for it in rows:
        if lines and abs(lines[-1]["y"] - it["y"]) <= 3:
            lines[-1]["items"].append(it)
        else:
            lines.append({"y": it["y"], "items": [it]})
    texts = []
    for ln in lines:
        ln["items"].sort(key=lambda i: -i["x"])  # RTL within a line
        texts.append(re.sub(r'\s+', ' ', ' '.join(i["str"] for i in ln["items"])).strip())

    counts = {}
    for t in texts:
        counts[_norm(t)] = counts.get(_norm(t), 0) + 1
    repeated = [t for t in texts if counts.get(_norm(t), 0) >= 2]
    chosen = repeated if repeated else texts

    seen, kept = set(), []
    for t in chosen:
        nrm = _norm(t)
        if not nrm or nrm in seen:
            continue
        seen.add(nrm)
        kept.append(t)
    desc = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', ' '.join(kept))).strip()
    desc = re.sub(r'(?<!\d)\d{1,2}\.\s*', '', desc, count=1)  # drop a leading "12."
    return desc


def extract_raw_items(pdf_path):
    """Return {'items':[{'num','desc','result','page','anchor_y'}], 'is_english'}.
    Descriptions are cleaned DETERMINISTICALLY here (no LLM). `result` is None
    (checkbox detection is a separate vision step); `page`/`anchor_y` locate the
    row's checkbox band (pdf.js bottom-left Y)."""
    doc = fitz.open(pdf_path)
    full_text = doc[0].get_text() if doc.page_count else ""
    is_english = not bool(ARABIC.search(full_text))
    tasks = []
    counter = 1
    for page_index, page in enumerate(doc):
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
            desc = _clean_box(box)
            if len(desc) > 5:
                tasks.append({"num": counter, "desc": desc, "result": None,
                              "page": page_index, "anchor_y": y})
                counter += 1
    return {"items": tasks, "is_english": is_english}


HEADER_KEYS = {
    'Task ID:': 'taskId', 'Task Category:': 'taskCategory',
    'Task Subcategory:': 'taskSubcategory', 'Site ID:': 'siteId',
    'Report Date:': 'reportDate', 'Report FME:': 'fmeName',
}


def parse_header(pdf_path):
    """Port of the SPA header parse: scan text lines for known labels."""
    doc = fitz.open(pdf_path)
    lines = []
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                txt = " ".join(s["text"] for s in line["spans"]).strip()
                if txt:
                    lines.append(txt)
    header = {}
    for i, ln in enumerate(lines):
        for label, key in HEADER_KEYS.items():
            if ln.startswith(label):
                header[key] = ln[len(label):].strip() or (lines[i+1].strip() if i+1 < len(lines) else '')
    return header


if __name__ == "__main__":
    import sys
    out = extract_raw_items(sys.argv[1])
    print("is_english:", out["is_english"])
    for t in out["items"]:
        print(f'{t["num"]:>2}. {t["desc"][:160]}')
