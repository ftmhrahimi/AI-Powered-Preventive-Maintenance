"""Deterministic checks ported from the frontend: GPS distance + photo date.

These are the only HARD validations (independent of the AI). Ported 1:1 from
the SPA so verdicts match.
"""
import math
from datetime import datetime


def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres (R=6371000), identical to the SPA."""
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_date(value):
    """Lenient date parse; returns a date or None. Mirrors treating 'unknown'
    and unparseable values as missing (see the SPA's NaN handling)."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    m = __import__("re").search(r"(\d{4}-\d{2}-\d{2})", s)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def date_check(photo_date, report_date, tolerance_days):
    """(ok, label). ok=False with 'Date missing' if unparseable, mirroring the
    frontend fix that treats invalid/'unknown' dates as missing."""
    pd = _parse_date(photo_date)
    rd = _parse_date(report_date)
    if pd is None:
        return False, "✗ Date missing"
    if rd is None:
        return False, f"✗ {photo_date}"
    diff = abs((pd - rd).days)
    ok = diff <= tolerance_days
    return ok, (f"✓ {photo_date}" if ok else f"✗ {photo_date}")


def gps_check(photo_lat, photo_lon, site_lat, site_lon, radius_m):
    """(ok, dist_or_None, label). Mirrors the frontend GPS pill logic."""
    if site_lat is None or photo_lat is None:
        return False, None, "✗ GPS missing"
    dist = round(haversine(site_lat, site_lon, photo_lat, photo_lon))
    ok = dist <= radius_m
    return ok, dist, (f"✓ On-site ({dist}m)" if ok else f"✗ Off-site ({dist}m)")
