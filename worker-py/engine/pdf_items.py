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
    """Text fragments as {'str','x','y','chars'} with Y in pdf.js (bottom-left)
    space. `chars` is the per-glyph list [{'c','x'}] sorted later by x to recover
    true visual order — PyMuPDF's span string is NOT reliably visual for RTL."""
    H = page.rect.height
    out = []
    for block in page.get_text("rawdict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                chars = [{"c": c["c"], "x": c["bbox"][0]}
                         for c in span.get("chars", []) if c.get("c")]
                t = "".join(c["c"] for c in chars).strip()
                if not t:
                    continue
                ox, oy = span["origin"]
                out.append({"str": t, "x": ox, "y": H - oy, "chars": chars})
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


def _is_ltr(c):
    return c.isascii() and c.isalnum()


# Bidi mirrored characters: when an RTL run is reversed for display, paired
# punctuation must be swapped so "(" stays an opener in logical order, etc.
_MIRROR = {'(': ')', ')': '(', '[': ']', ']': '[', '{': '}', '}': '{',
           '<': '>', '>': '<', '«': '»', '»': '«'}


def _vis_to_logical_rtl(vis):
    """Convert a single line given in true VISUAL order (left→right as displayed)
    into logical reading order for an RTL (Persian) line.

    Reversing the visual order yields logical order for the RTL letters (the
    sentence-ending period that sits at the far left visually lands at the end).
    Two corrections follow standard bidi: (1) mirror paired brackets — a visual
    ')' is logically '('; (2) embedded Latin/number runs (e.g. "PM-2025…",
    "CMWO") get reversed by the flip, so re-reverse each Latin run to restore it.
    No LLM involved."""
    rev = ''.join(_MIRROR.get(c, c) for c in reversed(vis))
    out, i, n = [], 0, len(rev)
    while i < n:
        if _is_ltr(rev[i]):
            j = i
            # extend across a Latin run, swallowing inner separators (-:/.,)
            while j < n and (_is_ltr(rev[j]) or
                             (rev[j] in '-:/.,' and j + 1 < n and _is_ltr(rev[j + 1]))):
                j += 1
            out.append(rev[i:j][::-1])
            i = j
        else:
            out.append(rev[i]); i += 1
    return re.sub(r'\s+', ' ', ''.join(out)).strip()


def _line_text(chars, is_english):
    """Build one line's logical text from its glyphs. Sort by x for true visual
    order, then: English/LTR docs read left→right as-is; Persian/RTL docs need
    the visual→logical flip.

    NFKC is applied AFTER the RTL flip so that a lam-alef ligature glyph (ﻼ),
    which expands to two chars 'لا', is reversed as a single unit first and only
    then expanded — otherwise the reversal would swap them to 'ال'."""
    chars = sorted(chars, key=lambda c: c["x"])
    vis = re.sub(r'\s+', ' ', ''.join(c["c"] for c in chars)).strip()
    if not vis:
        return ''
    logical = vis if is_english else _vis_to_logical_rtl(vis)
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', logical)).strip()


def _clean_box(box, is_english):
    """Deterministically turn a row's raw fragments into ONE clean description.

    PM reports repeat each item's description across ~3 table rows (text row,
    checkbox row, photo row); header pages also bleed header fields in. We:
      1. group fragments into lines (Y bands), keeping ascending-Y reading order;
      2. rebuild each line in correct logical order from its glyphs (visual x
         order → logical via _line_text: identity for English, bidi flip for
         Persian, fixing embedded English/numbers and the item number);
      3. segment the lines into the ~3 repeated copies (each starts with the
         item number) and take a per-line MAJORITY VOTE across copies, so a copy
         polluted by header/footer bleed can't corrupt the description; fall back
         to a repeat-filter + dedup when copies can't be aligned;
      4. NFKC-normalise and strip a leading item number.
    No LLM involved.
    """
    # Reading order differs by language (matches the browser sort): these PM
    # PDFs stack a paragraph's wrapped lines bottom-to-top for Persian but
    # top-to-bottom for English. In pdf.js (bottom-left, y-up) space that is
    # ascending-Y for Persian and descending-Y for English.
    rows = sorted(box, key=lambda it: it["y"], reverse=is_english)
    lines = []
    for it in rows:
        if lines and abs(lines[-1]["y"] - it["y"]) <= 3:
            lines[-1]["items"].append(it)
        else:
            lines.append({"y": it["y"], "items": [it]})
    texts = []
    for ln in lines:
        chars = [c for it in ln["items"] for c in it["chars"]]
        t = _line_text(chars, is_english)
        if t:
            texts.append(t)

    # The first box (top of a page) also captures the report header above the
    # first item ("Task ID: …", "Report FME: …"). The real description begins at
    # the item-number line, so drop everything before it. This matters most when
    # an item appears only once (no repetition for the majority vote to exploit).
    first_num = next((i for i, t in enumerate(texts) if _NUM_LINE.match(t)), None)
    if first_num is not None:
        texts = texts[first_num:]

    kept = _majority_lines(texts)
    if kept is None:
        # Fallback: keep repeated lines (dropping one-off header/noise lines),
        # then dedup preserving order.
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
    # After reordering, the item number sits at the very start ("10 فونداسیون…");
    # strip a single leading number (with optional dot). Numbers inside the text
    # (e.g. "10 درصد") are untouched.
    desc = re.sub(r'^\s*[\d۰-۹]{1,2}\.?\s*', '', desc, count=1)
    return desc


_NUM_LINE = re.compile(r'^\s*[\d۰-۹]{1,2}\s*[.\-)]?\s+\S')


def _majority_lines(texts):
    """Split `texts` into the repeated copies of the paragraph (each copy starts
    with the item-number line) and return one clean copy by per-line majority
    vote across the copies. Returns None when fewer than 2 alignable copies are
    found, so the caller can fall back to the simpler repeat/dedup path."""
    starts = [i for i, t in enumerate(texts) if _NUM_LINE.match(t)]
    if len(starts) < 2:
        return None
    bounds = starts + [len(texts)]
    copies = [texts[a:b] for a, b in zip(bounds, bounds[1:])]
    # Align only the copies that share the most common line count.
    from collections import Counter
    modal_len = Counter(len(c) for c in copies).most_common(1)[0][0]
    good = [c for c in copies if len(c) == modal_len]
    if len(good) < 2:
        return None
    out = []
    for i in range(modal_len):
        col = [c[i] for c in good]
        best = Counter(_norm(x) for x in col).most_common(1)[0][0]
        out.append(next(x for x in col if _norm(x) == best))
    return out


def _watermark_texts(doc, min_pages=8):
    """Identify stamped notes/watermarks: a span whose text appears verbatim on
    many distinct pages (e.g. a reviewer annotation "battery wo falt darad").
    These bleed into description lines, so we drop them everywhere. Real
    checklist text never recurs across this many pages."""
    from collections import defaultdict
    pages = defaultdict(set)
    for pno, page in enumerate(doc):
        for it in _page_fragments(page):
            s = it["str"].strip()
            # Keep the OK / Not OK checkbox markers — they recur on every page
            # but are the anchors that locate each row.
            if NOTOK_EXACT.match(s) or CHECK_GLYPH.search(s):
                continue
            nrm = _norm(it["str"])
            if nrm:
                pages[nrm].add(pno)
    return {t for t, ps in pages.items() if len(ps) >= min_pages}


def extract_raw_items(pdf_path):
    """Return {'items':[{'num','desc','result','page','anchor_y'}], 'is_english'}.
    Descriptions are cleaned DETERMINISTICALLY here (no LLM). `result` is None
    (checkbox detection is a separate vision step); `page`/`anchor_y` locate the
    row's checkbox band (pdf.js bottom-left Y)."""
    doc = fitz.open(pdf_path)
    full_text = doc[0].get_text() if doc.page_count else ""
    is_english = not bool(ARABIC.search(full_text))
    watermarks = _watermark_texts(doc)
    tasks = []
    counter = 1
    for page_index, page in enumerate(doc):
        items = [it for it in _page_fragments(page)
                 if _norm(it["str"]) not in watermarks]
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
            desc = _clean_box(box, is_english)
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
