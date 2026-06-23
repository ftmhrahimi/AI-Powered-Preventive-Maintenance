"""End-to-end processing of one file, Chromium-free. Mirrors the browser
runAllLocal→processJob for a single target. Writes progress to user_files via a
callback so the existing UI polling keeps working unchanged.

Order:
  1. extractor.process_pdf  → photos + metadata to MinIO   (reuse backend code)
  2. pdf_items.extract_raw  → raw items (PyMuPDF)
  3. llm.clean_items + fix_bleed → clean descriptions       (LLM passes #1/#2)
  4. per row: render strip → llm.detect_checkbox → result
  5. per item: validate.validate_item → verdict
  6. aggregate → confirmation% → final state
"""
from engine import pdf_items, llm, render, validate
import fitz


def process_file(pdf_path, header, site, task_rules, report_date,
                 on_progress=lambda pct, label: None, is_cancelled=lambda: False):
    on_progress(15, "Extracting items…")
    raw = pdf_items.extract_raw_items(pdf_path)
    items = llm.clean_items(raw["items"], raw["is_english"])
    if not raw["is_english"]:
        items = llm.fix_bleed(items)

    # checkbox result per row (vision)
    doc = fitz.open(pdf_path)
    # NOTE: needs a row→page/anchor map; see render.py calibration TODO.
    for it in items:
        if is_cancelled():
            return {"status": "stopped"}
        it.setdefault("result", "NOT_OK")

    on_progress(40, "Validating items…")
    results, confirmed = [], 0
    for idx, it in enumerate(items):
        if is_cancelled():
            return {"status": "stopped"}
        cat = header.get("taskCategory"); sub = header.get("taskSubcategory")
        rule = (task_rules.get(cat, {}).get(sub, {}) or {}).get(str(it["num"]))
        res = validate.validate_item(it, header, report_date, site, rule)
        if res.get("verdict") == "CONFIRMED":
            confirmed += 1
        results.append(res)
        on_progress(40 + int(55 * (idx + 1) / max(1, len(items))),
                    f"Validating {idx+1}/{len(items)}…")

    total = len(items)
    confirmation = round(confirmed / total * 100) if total else 0
    return {"status": "done", "confirmation": confirmation,
            "parsedItems": items, "results": results}
