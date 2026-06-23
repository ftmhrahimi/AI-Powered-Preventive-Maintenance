"""Chromium-free worker: claims server-runs and processes them in pure Python.

Drop-in for the Playwright worker. Reuses the SAME backend queue (/worker/*) and
writes per-file state to the same user_files store, so the frontend UI is
unchanged. Run several instances (WORKER_CONCURRENCY threads) for parallelism;
each is I/O-bound on the LLM, so memory is a fraction of a browser.
"""
import os
import io
import time
import json
import logging
import tempfile
import threading

import requests

from engine import pdf_items, pipeline

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s pyworker: %(message)s")
log = logging.getLogger("pyworker")

BACKEND = os.getenv("WORKER_BACKEND_URL", "http://backend:9700").rstrip("/")
TOKEN   = os.getenv("WORKER_TOKEN", "")
POLL    = int(os.getenv("WORKER_POLL_SECONDS", "5"))
CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "3"))
EXTRACT_PHOTOS = os.getenv("EXTRACT_PHOTOS", "true").lower() == "true"
HEADERS = {"X-Worker-Token": TOKEN} if TOKEN else {}


# ── Backend protocol ─────────────────────────────────────────────────────────
def claim():
    try:
        r = requests.post(f"{BACKEND}/worker/claim", headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.json().get("run")
    except Exception as e:
        log.warning("claim failed: %s", e)
        return None


def heartbeat(run_id):
    try:
        requests.post(f"{BACKEND}/worker/heartbeat", json={"id": run_id}, headers=HEADERS, timeout=15)
    except Exception:
        pass


def complete(run_id, username, status, error=None):
    try:
        requests.post(f"{BACKEND}/worker/complete",
                      json={"id": run_id, "username": username, "status": status, "error": error},
                      headers=HEADERS, timeout=30)
    except Exception as e:
        log.warning("complete failed: %s", e)


def run_cancelled(run_id):
    try:
        r = requests.post(f"{BACKEND}/worker/run-status", json={"id": run_id}, headers=HEADERS, timeout=15)
        return (r.json() or {}).get("status") == "cancelled"
    except Exception:
        return False


def stop_job(job_id):
    """Tell the backend to stop an in-flight /extract job."""
    try:
        requests.post(f"{BACKEND}/stop-job/{job_id}", headers=HEADERS, timeout=15)
    except Exception:
        pass


class Cancelled(Exception):
    pass


class Cancel:
    """Throttled cancellation check: polls /worker/run-status at most every 2s,
    and latches True once cancelled. Used everywhere in the run so Stop / Stop All
    take effect within ~2s, in every phase (incl. photo extraction)."""
    def __init__(self, run_id):
        self.run_id = run_id
        self._latched = False
        self._last = 0.0

    def check(self):
        if self._latched:
            return True
        now = time.time()
        if now - self._last >= 2:
            self._last = now
            if run_cancelled(self.run_id):
                self._latched = True
        return self._latched

    def sleep(self, seconds):
        """Sleep in 1s steps so cancellation is noticed quickly."""
        end = time.time() + seconds
        while time.time() < end:
            if self.check():
                return
            time.sleep(min(1.0, end - time.time()))



def download_pdf(username, filename):
    r = requests.get(f"{BACKEND}/api/pdfs/download",
                     params={"username": username, "filename": filename},
                     headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.content


def save_file_state(username, filename, state):
    """Upsert a single file's state into user_files (same shape the SPA saves)."""
    payload = {"fileName": filename, "status": state.get("status", "pending"),
               "confirmation": state.get("confirmation"),
               "pct": state.get("pct"), "barLabel": state.get("barLabel"),
               "parsedHeader": state.get("parsedHeader", {}),
               "parsedItems": state.get("parsedItems", []),
               "results": state.get("results", [])}
    try:
        requests.post(f"{BACKEND}/api/userfiles",
                      json={"username": username, "files": [payload]},
                      headers=HEADERS, timeout=30)
    except Exception as e:
        log.warning("save_file_state failed: %s", e)


def load_site(site_id):
    try:
        sites = requests.get(f"{BACKEND}/api/sites", headers=HEADERS, timeout=30).json()
        for s in sites:
            if str(s.get("siteId", "")).upper() == str(site_id or "").upper():
                return {"lat": float(s["lat"]), "lon": float(s["lon"])}
    except Exception:
        pass
    return None


def load_rules():
    try:
        return requests.get(f"{BACKEND}/api/task-rules", headers=HEADERS, timeout=30).json()
    except Exception:
        return {}


def ensure_photos(pdf_bytes, username, filename, progress, cancel):
    """Mirror the browser: POST the PDF to /extract, poll /job until done.
    Honours cancellation at every poll (Stop during extraction stops the job)."""
    if not EXTRACT_PHOTOS:
        return
    if cancel.check():
        raise Cancelled()
    files = {"file": (filename, io.BytesIO(pdf_bytes), "application/pdf")}
    r = requests.post(f"{BACKEND}/extract", files=files, data={"username": username},
                      headers=HEADERS, timeout=120)
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(data.get("error") or "extract submit failed")
    job_id = data["job_id"]
    while True:
        if cancel.check():
            stop_job(job_id)
            raise Cancelled()
        p = requests.get(f"{BACKEND}/job/{job_id}", headers=HEADERS, timeout=30).json()
        st = p.get("status")
        if st == "failed":
            raise RuntimeError(p.get("error") or "extraction failed")
        if st in ("stopped", "cancelled"):
            raise Cancelled()
        progress(max(5, p.get("progress_pct", 5)), p.get("progress_label") or "Extracting…")
        if st == "done":
            return
        cancel.sleep(3)


# ── One run ──────────────────────────────────────────────────────────────────
def process_run(run):
    run_id, username, filename = run["id"], run["username"], run.get("target")
    if not filename:
        complete(run_id, username, "failed", "no target")
        return

    cancel = Cancel(run_id)

    def progress(pct, label):
        # Never overwrite a stopped file with 'pending' progress — once the run
        # is cancelled we stop writing, so the frontend's 'stopped' state sticks.
        if cancel.check():
            return
        save_file_state(username, filename,
                        {"status": "pending", "pct": pct, "barLabel": label})

    stop_hb = threading.Event()

    def hb_loop():
        while not stop_hb.wait(20):
            heartbeat(run_id)
    threading.Thread(target=hb_loop, daemon=True).start()

    def mark_stopped():
        save_file_state(username, filename, {"status": "stopped", "pct": 0, "barLabel": "Stopped"})
        complete(run_id, username, "cancelled")
        log.info("run %s cancelled", run_id)

    try:
        if cancel.check():
            mark_stopped(); return
        pdf_bytes = download_pdf(username, filename)
        header = _header_from_bytes(pdf_bytes)
        report_date = header.get("reportDate", "")
        site = load_site(header.get("siteId"))
        rules = load_rules()

        progress(2, "Submitting PDF…")
        ensure_photos(pdf_bytes, username, filename, progress, cancel)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(pdf_bytes); tmp.flush()
            out = pipeline.process_file(
                tmp.name, header, site, rules, report_date,
                on_progress=progress, is_cancelled=cancel.check)

        if out.get("status") == "stopped" or cancel.check():
            mark_stopped(); return

        save_file_state(username, filename, {
            "status": "done", "pct": 100, "barLabel": "Complete",
            "confirmation": out["confirmation"], "parsedHeader": header,
            "parsedItems": out["parsedItems"], "results": out["results"]})
        complete(run_id, username, "done")
        log.info("run %s done (%s%%)", run_id, out["confirmation"])
    except Cancelled:
        mark_stopped()
    except Exception as e:
        if cancel.check():
            mark_stopped()
        else:
            log.exception("run %s failed", run_id)
            save_file_state(username, filename, {"status": "error", "pct": 100, "barLabel": "Failed: " + str(e)})
            complete(run_id, username, "failed", str(e))
    finally:
        stop_hb.set()


def _header_from_bytes(pdf_bytes):
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as t:
        t.write(pdf_bytes); t.flush()
        return pdf_items.parse_header(t.name)


def worker_loop(wid):
    log.info("python worker[%d] started — backend=%s", wid, BACKEND)
    while True:
        run = claim()
        if not run:
            time.sleep(POLL)
            continue
        log.info("worker[%d] processing run %s (%s) for %s", wid, run["id"], run.get("target"), run["username"])
        process_run(run)


def main():
    log.info("python engine worker starting with concurrency=%d", CONCURRENCY)
    threads = [threading.Thread(target=worker_loop, args=(i,), daemon=True) for i in range(max(1, CONCURRENCY))]
    for t in threads: t.start()
    for t in threads: t.join()


if __name__ == "__main__":
    main()
