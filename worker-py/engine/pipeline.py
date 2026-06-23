"""End-to-end processing of one file, Chromium-free. Mirrors the browser
runAllLocal→processJob for a single target. Writes progress via on_progress so
the existing UI polling keeps working unchanged.

Photo extraction (PDF→images+metadata→MinIO) is delegated to the backend
/extract endpoint by the worker BEFORE this runs, so here we only: extract
items, clean (LLM), detect checkboxes (vision), validate (vision), aggregate.
"""
import os
import fitz

from engine import pdf_items, llm, render, validate

CHECKBOX_DETECT = os.getenv("CHECKBOX_DETECT", "true").lower() == "true"


def process_file(pdf_path, header, site, task_rules, report_date,
                 on_progress=lambda pct, label: None, is_cancelled=lambda: False):
    on_progress(15, "Extracting items…")
    raw = pdf_items.extract_raw_items(pdf_path)
    raw_by_num = {t["num"]: t for t in raw["items"]}

    items = llm.clean_items(raw["items"], raw["is_english"])
    if not raw["is_english"]:
        items = llm.fix_bleed(items)

    # Checkbox OK/NOT_OK per row (vision). Map cleaned item → raw anchor by num.
    doc = fitz.open(pdf_path)
    on_progress(35, "Reading checkboxes…")
    for it in items:
        if is_cancelled():
            return {"status": "stopped"}
        result = "NOT_OK"
        if CHECKBOX_DETECT:
            src = raw_by_num.get(int(it["num"]))
            if src is not None:
                try:
                    strip = render.strip_for_anchor(doc[src["page"]], src["anchor_y"])
                    result = llm.detect_checkbox(strip)
                except Exception:
                    result = "NOT_OK"
        it["result"] = result

    on_progress(40, "Validating items…")
    results, confirmed = [], 0
    total = len(items)
    for idx, it in enumerate(items):
        if is_cancelled():
            return {"status": "stopped"}
        cat = header.get("taskCategory"); sub = header.get("taskSubcategory")
        rule = (task_rules.get(cat, {}).get(sub, {}) or {}).get(str(it["num"]))
        res = validate.validate_item(it, header, report_date, site, rule)
        if res.get("verdict") == "CONFIRMED":
            confirmed += 1
        results.append(res)
        on_progress(40 + int(55 * (idx + 1) / max(1, total)),
                    f"Validating {idx+1}/{total}…")

    confirmation = round(confirmed / total * 100) if total else 0
    return {"status": "done", "confirmation": confirmation,
            "parsedItems": items, "results": results}
