"""
Headless-browser worker for server-side processing.

Why this exists
---------------
The entire audit pipeline (PDF rendering via pdf.js + canvas, checkbox
detection, item extraction, photo fetching, AI validation) lives in the
frontend and is driven by the browser. Historically that meant: close the
browser / shut down the machine → the work stops mid-step, because the
browser tab IS the engine.

This worker runs that *exact same frontend code* inside a headless Chromium
on the always-on server. It logs in as the requesting user, lets the page
restore their pending files from the backend, and clicks "Run All". Because
it is the identical code path, the output is identical to running locally —
but it keeps going even after the user leaves.

State is persisted by the frontend itself (each setJob() saves job state to
the backend via /api/userfiles, and PDFs were already uploaded to backend
storage). So when the user comes back, their jobs show up completed.

Flow
----
  loop:
    POST /worker/claim                      -> {run: {id, username, user}} | {run: null}
    if run:
        open headless page as that user
        wait for jobs to restore (pending)
        evaluate runAll()  (awaits until every job reaches a terminal state)
        POST /worker/complete {id, status}
    else:
        sleep(poll interval)
"""

import os
import json
import time
import threading
import logging

import requests
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s worker: %(message)s",
)
log = logging.getLogger("worker")

BACKEND_URL  = os.environ.get("WORKER_BACKEND_URL", "http://backend:9700").rstrip("/")
FRONTEND_URL = os.environ.get("WORKER_FRONTEND_URL", "http://frontend").rstrip("/")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
POLL_SECONDS = int(os.environ.get("WORKER_POLL_SECONDS", "5"))
# How many files to process at once (each in its own headless browser). This
# restores the old "several files run together" behaviour now that each file is
# an independent server-run.
WORKER_CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "3"))
HEARTBEAT_SECONDS = int(os.environ.get("WORKER_HEARTBEAT_SECONDS", "60"))
# How long to wait for the page to restore at least one pending job before
# assuming there is nothing to do.
RESTORE_TIMEOUT_MS = int(os.environ.get("WORKER_RESTORE_TIMEOUT_MS", "120000"))
# Upper bound for a whole batch to finish (default 6 hours).
COMPLETION_TIMEOUT_MS = int(os.environ.get("WORKER_COMPLETION_TIMEOUT_MS", str(6 * 60 * 60 * 1000)))

_HEADERS = {"X-Worker-Token": WORKER_TOKEN} if WORKER_TOKEN else {}


def _post(path, payload=None):
    return requests.post(BACKEND_URL + path, json=(payload or {}), headers=_HEADERS, timeout=30)


def claim_run():
    try:
        resp = _post("/worker/claim")
        resp.raise_for_status()
        return resp.json().get("run")
    except Exception as e:
        log.warning("claim failed: %s", e)
        return None


def run_is_cancelled(run_id):
    """True if THIS specific run was cancelled.

    Each file is its own run, so we must check the exact run we are processing —
    checking "the user's latest run" would be wrong, because the same user may
    have enqueued other files (newer runs) that are still active."""
    try:
        resp = _post("/worker/run-status", {"id": run_id})
        resp.raise_for_status()
        return (resp.json() or {}).get("status") == "cancelled"
    except Exception:
        return False


def complete_run(run_id, username, status, error=None):
    try:
        _post("/worker/complete", {"id": run_id, "username": username,
                                   "status": status, "error": error})
    except Exception as e:
        log.warning("complete failed for run %s: %s", run_id, e)


class Heartbeat:
    """Periodically pings the backend so a long run is not treated as stale."""

    def __init__(self, run_id):
        self.run_id = run_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                _post("/worker/heartbeat", {"id": self.run_id})
            except Exception as e:
                log.debug("heartbeat failed: %s", e)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()


# Conditions evaluated inside the page's own JS context.
# runAllLocal is the REAL in-page pipeline (runAll, in the human UI, only
# delegates to the server — the worker must drive the actual engine).
_PIPELINE_READY = "() => typeof runAllLocal === 'function' && Array.isArray(jobs)"
_NONE_ACTIVE = (
    "() => Array.isArray(jobs) && "
    "!jobs.some(j => j.status === 'running' || j.status === 'pending')"
)
# Completion check for a SINGLE-file (targeted) run. The page also restored the
# user's OTHER pending files, but this run only processes its one target — so it
# is finished when that target file leaves running/pending, regardless of the
# others. (For target=None we fall back to _NONE_ACTIVE.)
_TARGET_DONE = (
    "(name) => { const j = Array.isArray(jobs) && "
    "jobs.find(x => x.file && x.file.name === name); "
    "return !j || (j.status !== 'running' && j.status !== 'pending'); }"
)
# Diagnostic snapshot of what the restored page actually sees. 'saved' is how
# many files the backend has for this user; 'jobs' is how many were rebuilt in
# the page; 'pending' is how many are runnable. If saved>0 but jobs==0 the PDFs
# could not be downloaded (not in backend storage).
_RESTORE_SNAPSHOT = (
    "async () => {"
    "  let saved = -1;"
    "  try { saved = (await getUserFiles(currentUser.username)).length; } catch (e) {}"
    "  const j = Array.isArray(jobs) ? jobs : [];"
    "  return { saved: saved, jobs: j.length,"
    "    pending: j.filter(x => ['pending','stopped','error'].includes(x.status)).length };"
    "}"
)


def process_run(browser, run):
    run_id = run["id"]
    user = run["user"]
    username = run["username"]
    log.info("processing server-run %s for user '%s'", run_id, username)

    context = browser.new_context()
    try:
        # Log in as the user exactly the way the frontend does: by seeding the
        # session object the app reads on DOMContentLoaded. Also mark this page
        # as the headless worker so it does not re-enqueue itself on unload.
        context.add_init_script(
            "window.__PM_HEADLESS_WORKER = true;"
            "try { localStorage.setItem('pm_session', %s); } catch (e) {}"
            % json.dumps(json.dumps(user))
        )
        page = context.new_page()
        page.set_default_timeout(120000)

        # Load the app, retrying to ride out service-startup races (e.g. the
        # frontend not being up yet right after a stack restart).
        last_err = None
        for attempt in range(1, 6):
            try:
                page.goto(FRONTEND_URL, wait_until="domcontentloaded")
                page.wait_for_function(_PIPELINE_READY, timeout=60000)
                last_err = None
                break
            except Exception as e:
                last_err = e
                log.warning("run %s: page load attempt %d failed: %s", run_id, attempt, e)
                time.sleep(min(2 ** attempt, 15))
        if last_err is not None:
            raise last_err

        # Wait for the user's pending files to be restored from the backend,
        # logging what the page actually sees so failures are diagnosable.
        restore_deadline = time.time() + (RESTORE_TIMEOUT_MS / 1000.0)
        pending = 0
        while time.time() < restore_deadline:
            try:
                snap = page.evaluate(_RESTORE_SNAPSHOT)
            except Exception as e:
                log.warning("run %s: restore snapshot failed: %s", run_id, e)
                snap = None
            if snap:
                log.info("run %s: restore — backend_files=%s rebuilt_jobs=%s pending=%s",
                         run_id, snap.get("saved"), snap.get("jobs"), snap.get("pending"))
                if (snap.get("pending") or 0) > 0:
                    pending = snap["pending"]
                    break
            time.sleep(2)
        if pending == 0:
            log.info("run %s: no pending jobs to process", run_id)
            return "done", None

        target = run.get("target")
        log.info("run %s: starting runAllLocal(target=%s)", run_id, target or "ALL")
        # Kick off the pipeline WITHOUT awaiting its promise here. runAllLocal()
        # marks the queued jobs 'running' synchronously before its first await,
        # so by the time evaluate returns the work is already in flight. We then
        # poll for completion instead of holding one multi-hour protocol call.
        # target=None processes every pending file; otherwise only that fileName.
        if target:
            page.evaluate("(name) => { runAllLocal([name]); }", target)
        else:
            page.evaluate("() => { runAllLocal(); }")

        # Poll until every job reaches a terminal state, or the user cancels.
        deadline = time.time() + (COMPLETION_TIMEOUT_MS / 1000.0)
        while True:
            if run_is_cancelled(run_id):
                log.info("run %s: cancellation requested — stopping", run_id)
                try:
                    page.evaluate("() => { stopAll(); }")
                except Exception:
                    pass
                return "cancelled", None
            try:
                done = (page.evaluate(_TARGET_DONE, target) if target
                        else page.evaluate(_NONE_ACTIVE))
                if done:
                    log.info("run %s: completed", run_id)
                    return "done", None
            except Exception as e:
                log.warning("run %s: progress check failed: %s", run_id, e)
            if time.time() > deadline:
                return "failed", "completion timeout"
            time.sleep(3)
    finally:
        context.close()


def worker_loop(worker_id):
    """One independent worker: its own browser, claiming and processing runs
    one at a time. Several of these run concurrently so multiple files process
    in parallel (each file is its own server-run, so they stay isolated)."""
    log.info("worker[%d] starting — backend=%s frontend=%s", worker_id, BACKEND_URL, FRONTEND_URL)
    # Each thread gets its OWN Playwright driver + browser; the sync API is not
    # shareable across threads, so we never hand one browser to two threads.
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            while True:
                run = claim_run()
                if not run:
                    time.sleep(POLL_SECONDS)
                    continue
                status, error = "done", None
                try:
                    with Heartbeat(run["id"]):
                        status, error = process_run(browser, run)
                except Exception as e:
                    log.exception("worker[%d] run %s failed", worker_id, run["id"])
                    status, error = "failed", str(e)
                complete_run(run["id"], run["username"], status, error)
        finally:
            browser.close()


def main():
    n = max(1, WORKER_CONCURRENCY)
    log.info("worker starting with concurrency=%d", n)
    # The backend serialises claims (in-process lock + guarded UPDATE), so
    # multiple loops claiming at once never grab the same run.
    threads = [threading.Thread(target=worker_loop, args=(i,), daemon=True)
               for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
