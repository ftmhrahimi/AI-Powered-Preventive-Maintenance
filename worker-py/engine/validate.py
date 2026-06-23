"""Per-item validation: fetch photos + metadata, run date/GPS checks, call the
LLM verdict, then apply system-cause overrides. Mirrors the SPA validateAllItems.
"""
import os
import json
import base64
import requests

from . import geo, llm

MINIO_BASE = os.getenv("MINIO_BASE", "http://10.130.154.133:9000/pm-photos")
PHOTO_MAX  = int(os.getenv("PHOTO_MAX_INDEX", "50"))
GPS_RADIUS = int(os.getenv("GPS_RADIUS_METERS", "300"))
DATE_TOL   = int(os.getenv("DATE_TOLERANCE_DAYS", "3"))


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
        b64 = "data:image/jpeg;base64," + base64.b64encode(jpg.content).decode()
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
