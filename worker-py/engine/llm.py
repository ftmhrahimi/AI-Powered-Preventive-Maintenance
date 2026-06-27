"""vLLM client + the LLM-driven stages, ported from the SPA. Text + vision.

Needs a reachable vLLM endpoint (OpenAI chat API). Used for: item clean/dedup
(pass #1), bleed-fix (pass #2), checkbox detection, and per-item validation.
"""
import os
import re
import json
import base64
import requests

from . import prompts

LLM_URL   = os.getenv("LLM_SERVER_URL", "http://10.130.154.133:8000/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL_NAME", "./")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_RETRY_DELAY = float(os.getenv("LLM_RETRY_DELAY", "2.0"))


def _chat(messages, temperature=0.0):
    """Call vLLM with retry/backoff on transient failures (5xx / timeouts) so a
    single LLM hiccup doesn't fail the whole item/run."""
    import time
    delay = LLM_RETRY_DELAY
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            r = requests.post(LLM_URL, json={"model": LLM_MODEL, "messages": messages,
                                             "temperature": temperature}, timeout=LLM_TIMEOUT)
            if r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code} from LLM")
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""
        except Exception:
            if attempt >= LLM_MAX_RETRIES:
                raise
            time.sleep(delay)
            delay *= 2


def _img_msg(text, image_b64_urls):
    content = [{"type": "text", "text": text}]
    for url in image_b64_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [{"role": "user", "content": content}]


# ── Pass #1: clean/dedup item descriptions (batches of 5, overlap 1) ──────────
def clean_items(raw_items, is_english):
    CHUNK, OVERLAP = 5, 1
    out = []
    i = 0
    while i < len(raw_items):
        batch = raw_items[i:i + CHUNK]
        if not batch:
            break
        text = "\n".join(f"{t['num']}. {t['desc']}\nNot OK" for t in batch)
        try:
            raw = _chat([{"role": "user", "content": prompts.extract_prompt(text, is_english)}])
            m = re.search(r"\[[\s\S]*\]", raw)
            parsed = json.loads(m.group(0)) if m else []
        except Exception:
            parsed = []
        out.extend(parsed if parsed else [{"num": t["num"], "desc": t["desc"], "result": "NOT_OK"} for t in batch])
        i += CHUNK - OVERLAP
    # dedupe by (num | normalized desc), keep first, sort by num
    seen = {}
    for it in out:
        if not it.get("desc"):
            continue
        key = f"{it['num']}|" + re.sub(r"[‌​‎‏.,،;؛\s]", "", it["desc"])
        seen.setdefault(key, it)
    return sorted(seen.values(), key=lambda x: int(x["num"]))


# ── Pass #2: neighbour bleed-fix (Persian) — see SPA cleanConsecutiveTasks ────
def _norm(s):
    import unicodedata
    s = re.sub(r"[‌​‎‏­]", "", s)
    s = re.sub(r"[ً-ٟ]", "", s)
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


def fix_bleed(items):
    if len(items) < 2:
        return items
    cleaned = [dict(it) for it in items]
    for i, curr in enumerate(cleaned):
        if not curr.get("desc") or len(curr["desc"]) < 15:
            continue
        cs = _norm(curr["desc"])
        neighbours = []
        if i > 0 and cleaned[i-1].get("desc"):
            neighbours.append(cleaned[i-1])
        if i < len(cleaned)-1 and cleaned[i+1].get("desc"):
            neighbours.append(cleaned[i+1])
        bleed = None
        for nb in neighbours:
            ns = _norm(nb["desc"])
            if len(ns) < 15:
                continue
            if cs.find(ns[:40]) >= 0 or cs.find(ns[-40:]) >= 0:
                bleed = nb
                break
        if not bleed:
            continue
        try:
            raw = _chat([{"role": "user", "content": prompts.bleed_fix_prompt(
                curr["num"], curr["desc"], bleed["num"], bleed["desc"])}])
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                r = json.loads(m.group(0))
                if r.get("desc") and len(r["desc"]) > 5:
                    cleaned[i]["desc"] = r["desc"]
        except Exception:
            pass
    return cleaned


# ── Checkbox detection (vision) ──────────────────────────────────────────────
def detect_checkbox(strip_b64_url):
    try:
        raw = _chat(_img_msg(prompts.CHECKBOX, [strip_b64_url]))
        return "NOT_OK" if re.search(r"not[_\s]*ok", raw, re.I) else "OK"
    except Exception:
        return "OK"


# ── Per-item validation (vision) ─────────────────────────────────────────────
def validate_item(item, photo_count, report_date, site_lat, site_lon,
                  meta_summary, rule, header, photo_b64_urls):
    text = prompts.validation_prompt(item, photo_count, report_date, site_lat,
                                     site_lon, meta_summary, rule, header)
    raw = _chat(_img_msg(text, photo_b64_urls))
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError("No JSON in validation response")
    return json.loads(m.group(0))
