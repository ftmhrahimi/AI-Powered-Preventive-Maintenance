"""Per-item validation: fetch photos + metadata, run date/GPS checks, call the
LLM verdict, then apply system-cause overrides. Mirrors the SPA validateAllItems.
"""
import os
import io
import json
import base64
import requests
from PIL import Image

from . import geo, llm

MINIO_BASE = os.getenv("MINIO_BASE", "http://10.130.154.133:9000/pm-photos")
PHOTO_MAX  = int(os.getenv("PHOTO_MAX_INDEX", "50"))
GPS_RADIUS = int(os.getenv("GPS_RADIUS_METERS", "300"))
DATE_TOL   = int(os.getenv("DATE_TOLERANCE_DAYS", "3"))
# Validation sends ALL of an item's photos in ONE request. Full-size images
# blow past vLLM's context/multimodal limit → 400 Bad Request on multi-photo
# items. The browser (Chromium) engine downscaled each photo to 1000px wide at
# JPEG quality 0.7 before validating — that is exactly the configuration that
# produced the known-good results, so we match it. (Date/GPS are read from the
# full-size image separately by the backend metadata extractor, so stamped-text
# accuracy is unaffected.) Set LLM_IMAGE_MAX_W=0 to send full-size.
LLM_IMAGE_MAX_W   = int(os.getenv("LLM_IMAGE_MAX_W", "1000"))
LLM_IMAGE_QUALITY = int(os.getenv("LLM_IMAGE_QUALITY", "70"))


def _shrink(jpg_bytes):
    """Downscale to LLM_IMAGE_MAX_W width (browser-parity) for the LLM call."""
    if LLM_IMAGE_MAX_W <= 0:         # disabled → send full-resolution image
        return jpg_bytes
    try:
        img = Image.open(io.BytesIO(jpg_bytes)).convert("RGB")
        if img.width > LLM_IMAGE_MAX_W:
            scale = LLM_IMAGE_MAX_W / img.width
            img = img.resize((LLM_IMAGE_MAX_W, max(1, int(img.height * scale))))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=LLM_IMAGE_QUALITY)
        return buf.getvalue()
    except Exception:
        return jpg_bytes


def _get(url):
    try:
        r = requests.get(url, timeout=30)
        return r if r.ok else None
    except Exception:
        return None


def fetch_photos(task_id, row):
    """Return [(b64_data_url, meta_dict)] for an item's photos."""
    out = []
    for i in range(1, PHOTO_MAX + 1):
        jpg = _get(f"{MINIO_BASE}/photos/{task_id}/{row}/{i}.jpg")
        if not jpg:
            break
        # Downscale the copy sent to the LLM (display still uses the full-size
        # photo from MinIO). Cuts vision-encoder memory → avoids vLLM OOM under
        # concurrency and speeds inference.
        b64 = "data:image/jpeg;base64," + base64.b64encode(_shrink(jpg.content)).decode()
        meta = {}
        mj = _get(f"{MINIO_BASE}/photos/{task_id}/{row}/{i}.json")
        if mj:
            try:
                d = json.loads(mj.text)
                meta = {"name": f"{i}.jpg",
                        "date": d.get("date") or d.get("date_time"),
                        "lat": _num(d.get("lat") or d.get("latitude")),
                        "lon": _num(d.get("lng") or d.get("longitude"))}
            except Exception:
                meta = {"name": f"{i}.jpg"}
        out.append((b64, meta))
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def validate_item(item, header, report_date, site, rule):
    task_id = header.get("taskId")
    photos = fetch_photos(task_id, item["num"])
    if not photos:
        return {"row": item["num"], "verdict": "NO_EVIDENCE", "causes": [],
                "explanation": f"No photos in folder {item['num']}", "metaList": []}
    site_lat = site["lat"] if site else None
    site_lon = site["lon"] if site else None
    meta_list, system_causes, summary_lines = [], [], []
    for _, m in photos:
        d_ok, d_lbl = geo.date_check(m.get("date"), report_date, DATE_TOL)
        g_ok, dist, g_lbl = geo.gps_check(m.get("lat"), m.get("lon"), site_lat, site_lon, GPS_RADIUS)
        m.update(dateOk=d_ok, dateLabel=d_lbl, gpsOk=g_ok, dist=dist, gpsLabel=g_lbl)
        if not d_ok:
            system_causes.append("IMAGE_DATE_MISMATCH")
        if g_ok is False:
            system_causes.append("IMAGE_GPS_MISSING" if m.get("lat") is None else "IMAGE_GPS_MISMATCH")
        meta_list.append(m)
        loc = f"{m.get('lat')},{m.get('lon')}" if m.get("lat") is not None else "not found"
        summary_lines.append(f"  - {m.get('name')}: date={d_lbl}, GPS={loc}({g_lbl})")
    try:
        res = llm.validate_item(item, len(photos), report_date, site_lat, site_lon,
                                "\n".join(summary_lines), rule, header,
                                [p[0] for p in photos])
    except Exception as e:
        return {"row": item["num"], "verdict": "NO_EVIDENCE", "causes": [],
                "explanation": f"Validation error: {e}", "metaList": meta_list}
    if res.get("verdict") == "NO_EVIDENCE" and photos:
        res["verdict"] = "DISPUTED"
    res["causes"] = list({*system_causes, *(res.get("causes") or [])})
    if system_causes:
        res["verdict"] = "DISPUTED"
    res["metaList"] = meta_list
    return res
