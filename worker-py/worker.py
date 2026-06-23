"""Chromium-free worker: claim server-runs and process them in pure Python.

Drop-in replacement for the Playwright worker. Reuses the SAME backend queue
(/worker/claim, /worker/heartbeat, /worker/complete) and writes per-file state
to the same user_files store, so the frontend UI is unchanged.

SKELETON — wire up file download (from backend storage), header parsing, the
user_files progress writes, and per-run cancellation against /api/server-run,
then run several of these (thread/process pool) for concurrency.
"""
import os
import time
import logging
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s pyworker: %(message)s")
log = logging.getLogger("pyworker")

BACKEND = os.getenv("WORKER_BACKEND_URL", "http://backend:9700").rstrip("/")
TOKEN   = os.getenv("WORKER_TOKEN", "")
POLL    = int(os.getenv("WORKER_POLL_SECONDS", "5"))
HEADERS = {"X-Worker-Token": TOKEN} if TOKEN else {}


def claim():
    try:
        r = requests.post(f"{BACKEND}/worker/claim", headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.json().get("run")
    except Exception as e:
        log.warning("claim failed: %s", e)
        return None


def complete(run_id, username, status, error=None):
    try:
        requests.post(f"{BACKEND}/worker/complete",
                      json={"id": run_id, "username": username, "status": status, "error": error},
                      headers=HEADERS, timeout=30)
    except Exception as e:
        log.warning("complete failed: %s", e)


def main():
    log.info("python worker starting — backend=%s", BACKEND)
    while True:
        run = claim()
        if not run:
            time.sleep(POLL)
            continue
        log.info("processing run %s (%s) for %s", run["id"], run.get("target"), run["username"])
        # TODO: download the target PDF, parse header, load site + rules,
        #       call engine.pipeline.process_file with on_progress writing to
        #       /api/userfiles and is_cancelled polling /api/server-run.
        complete(run["id"], run["username"], "done")


if __name__ == "__main__":
    main()
