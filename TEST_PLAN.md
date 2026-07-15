# PM Batch Validator — Test Plan

A clear, end‑to‑end checklist to test the platform.

## How to use this document
- Work through the tables; record **Pass / Fail**, who tested, the date, and any
  notes in the sign‑off sheet at the end.
- Tests are split by **who can run them**:
  - **Part A — Platform‑only tests**: anything you can do from a **web browser**
    with a login. No server access needed. (Testers, admins, end users.)
  - **Part B — Server‑access tests**: things that need **SSH + Docker + the
    database** on the server. (Operator / deployer only.)
- If you only have a login and a browser, do **Part A**.

## Glossary
- **Acceptance %** — confirmed items ÷ total items, for a report.
- **Server‑side run** — processing happens on the always‑on server, not in your
  browser, so you can close the tab and it keeps going.
- **Disputed / Not OK** — an item the validator did not confirm.

## What you need
- A test admin login and a fresh non‑admin login.
- 5–10 valid report PDFs (mix of sizes; at least 3 for the concurrency tests).
- One PDF with **known** site/GPS, date, and checklist values (for §A14).
- One non‑PDF file and one very large file (> 50 MB) for the edge cases.
- For **Part B**: SSH access to the server and permission to run `docker`.

---

# PART A — Platform‑only tests (web browser, no server access)

## A1. Accounts & login

| ID | Steps | Expected |
|----|-------|----------|
| A1‑1 | Register a new user (name, username, password ≥ 6 chars) | Account created |
| A1‑2 | Register again with the same username | Rejected; no duplicate |
| A1‑3 | Register with a password < 6 chars / mismatched confirm | Blocked before submit |
| A1‑4 | Log in with correct details | Lands on Validator (user) / Dashboard (admin) |
| A1‑5 | Log in with a **wrong** password | Error: **"Incorrect username or password."** plus the hint **"Forgot your password? Ask an administrator to reset it."** |
| A1‑6 | Sign out, then reload the page | Returns to login; app not accessible |
| A1‑7 | Refresh the page while signed in | Stays signed in; previous files/reports restored |

## A2. Navigation & access by role

| ID | Steps | Expected |
|----|-------|----------|
| A2‑1 | As a **normal user**, look at the tabs | Only **Validator** and **Dashboard** visible |
| A2‑2 | As an **admin**, look at the tabs | Also: **Dashboard (all users)**, **Audit**, **Task Rules**, **Sites**, **Users** |
| A2‑3 | Switch between every tab a few times | Each loads its own content; no stale data |

## A3. File selection & upload

| ID | Steps | Expected |
|----|-------|----------|
| A3‑1 | **Select Folder** (or **＋ Add Files**) and choose PDFs | Rows appear immediately; bottom‑right notification shows **"x of N files uploaded"**, then disappears |
| A3‑2 | Add a non‑PDF file | Ignored (only `.pdf` accepted) |
| A3‑3 | Add a file whose name already exists | Asked to **replace** or **skip**; replace overwrites, skip keeps the original |
| A3‑4 | **While files are still uploading**, look at **Run All** | It is **disabled** (greyed, with a tooltip); per‑row **Run** is disabled too |
| A3‑5 | Wait for uploads to finish | **Run All** and per‑row **Run** become enabled automatically |
| A3‑6 | Open browser **DevTools → Network**. Run a file, Stop it, Run it again | **No new upload request** is sent on Run/Stop — the file uploads only once at selection |
| A3‑7 | Simulate an upload failure (e.g. go offline briefly during A3‑1) | Affected rows show **⟳ Retry upload**; a warning lists how many failed; nothing retries silently |
| A3‑8 | Click **⟳ Retry upload** on a failed row (back online) | Only that one file re‑uploads; it becomes runnable; others untouched |

## A4. Single Run / Stop

| ID | Steps | Expected |
|----|-------|----------|
| A4‑1 | Click **▶ Run** on one file | It processes; the bar advances with real stage labels to **Done** |
| A4‑2 | Open its report | **View Report** works; Acceptance % shown |
| A4‑3 | Click **■ Stop** on a file mid‑run | Only that file stops; **no other file is affected** |
| A4‑4 | **Re‑run** a stopped file | It runs again (no re‑upload) and completes |
| A4‑5 | **Re‑run** a Done file | It re‑processes and replaces its earlier result |

## A5. Run All / Stop All & concurrency

| ID | Steps | Expected |
|----|-------|----------|
| A5‑1 | With ≥ 3 pending files, click **Run All** | **All** rows start at once (none waits for another's upload) |
| A5‑2 | Watch the progress bars | Several files (up to the configured limit, default 3) show **real progress at the same time**; the rest show **Waiting…** |
| A5‑3 | Keep watching | **No bar resets, empties, or jumps between files**; each bar reflects only its own file; waiting files start as slots free up |
| A5‑4 | Let the batch finish | Every file → Done; the summary counters (Total/Done/Disputed/Avg %) are correct |
| A5‑5 | Click **Stop All** mid‑batch | All running files stop; **Run All** reappears; state stays consistent |

## A6. The four controls in combination

Run each sequence, then **reload the page** and confirm the table matches what you
last saw.

| ID | Sequence | Expected end state |
|----|----------|--------------------|
| A6‑1 | Run All → Stop **one** file | Only that file stopped; the others keep running |
| A6‑2 | Run All → Stop one → **Run** that one again | It re‑runs; others unaffected; no re‑upload |
| A6‑3 | Run All → Stop one → **Stop All** | Everything stops cleanly; Run All returns |
| A6‑4 | Run All → let 1 finish → **Stop All** | The finished file stays **Done** (not reverted); the rest are Stopped |
| A6‑5 | Double‑click **Run All** quickly | No duplicate runs/rows |

## A7. Server‑side processing (from the user's side)

| ID | Steps | Expected |
|----|-------|----------|
| A7‑1 | Run All, then **close the tab**; reopen and sign in | Processing continued; the table shows live/finished progress |
| A7‑2 | Run All, then **sign out** and back **in** | Same — progress/results preserved |
| A7‑3 | While a run is active | A blue **"☁ Server is processing…"** banner is shown; it clears when done |

## A8. Reading & saving reports

| ID | Steps | Expected |
|----|-------|----------|
| A8‑1 | Open a Done file's report | Header, overall verdict, per‑item rows, photos shown |
| A8‑2 | Click a **photo thumbnail** | Opens **full‑size** in a viewer; can step through and close |
| A8‑3 | Read the per‑photo pills | **Date** and **GPS** pills show ✓/✗ with clear text (e.g. **Date missing**, **GPS missing**) |
| A8‑4 | Click **💾 Save Report** | "✓ Report saved" appears |
| A8‑5 | Process a file but **don't** save it | It does **not** appear in the Dashboard |
| A8‑6 | Save a file, then open the Dashboard | The saved report appears |

## A9. Dashboards

| ID | Steps | Expected |
|----|-------|----------|
| A9‑1 | Open **Dashboard** as a normal user | Shows only **your** saved reports |
| A9‑2 | Use filters (Task ID, Site ID, min/max %) and sort columns | Rows filter/sort correctly; KPIs match |
| A9‑3 | (Admin) Open the all‑users Dashboard | Shows reports from **all** users, with an Owner column |
| A9‑4 | (Admin) Click a report's **file name** | Downloads the **original uploaded PDF** in a new tab |
| A9‑5 | (Admin) Open a report and click a thumbnail | Photo opens full‑size |

## A10. Task Rules (admin)

| ID | Steps | Expected |
|----|-------|----------|
| A10‑1 | Add a rule (Category, Subcategory, Task #, Expected, Checkpoints, Fail‑if) | Saved and listed |
| A10‑2 | Save with a missing required field | Blocked with a message |
| A10‑3 | Edit a rule (same keys) / delete a rule | Update persists / row removed |
| A10‑4 | Add a rule that matches a report item, then **re‑run** that report | The AI's reasoning for that item reflects the rule's wording (rules reach the AI) |
| A10‑5 | CSV import using the template | Rules imported and listed |

> Reminder: a rule's **Category + Subcategory + Task #** must match the report
> exactly. Rules *guide* the AI; they don't *force* a verdict.

## A11. Sites (admin)

| ID | Steps | Expected |
|----|-------|----------|
| A11‑1 | Add a site (Site ID, Lat, Lon) | Saved and listed |
| A11‑2 | Enter non‑numeric lat/lon or blank ID | Blocked |
| A11‑3 | Delete a site | Removed |
| A11‑4 | Process a report for that site | The GPS check uses the stored coordinates |

## A12. Users — password reset (admin)

| ID | Steps | Expected |
|----|-------|----------|
| A12‑1 | Open **👤 Users** | User list loads; reset form visible |
| A12‑2 | Pick a user, enter matching new passwords (≥ 6), **Reset Password** | Success message |
| A12‑3 | Sign in as that user with the **new** password | Login succeeds |
| A12‑4 | Sign in with the **old** password | Login fails |
| A12‑5 | Try a password < 6 chars or mismatched confirm | Blocked; no change made |
| A12‑6 | As the **backup admin**, reset the **primary admin's** password | Succeeds (admins can reset each other) |

## A13. Audit Log (admin)

| ID | Steps | Expected |
|----|-------|----------|
| A13‑1 | Open **Audit** | Recent events listed with user + timestamp |
| A13‑2 | Do a login + a Run All + a password reset, refresh Audit | New events appear (incl. `ADMIN_PASSWORD_RESET`) |
| A13‑3 | Filter by user / event / task | Narrows correctly |

## A14. Validation results sanity (use the known‑value PDF)

| ID | Check | Expected |
|----|-------|----------|
| A14‑1 | **Acceptance %** | Equals confirmed ÷ total; spot‑check one report's math |
| A14‑2 | **Date check** | Photo dates within tolerance pass; outside fail; unreadable → **Date missing** |
| A14‑3 | **GPS check** | Photos within the radius pass; far ones show **Off‑site**; no location → **GPS missing** |
| A14‑4 | **Verdict badges** | **Not OK + Technically Compliant** = only date/GPS unverified; **Not OK + Technically Non‑Compliant** = real content reason |
| A14‑5 | **Photos** | Each item's photos load (no broken images) |

## A15. Persian (RTL) reports

| ID | Steps | Expected |
|----|-------|----------|
| A15‑1 | Process a Persian report (including longer items) and read the descriptions | Item text reads correctly — **no garbled/duplicated letters** |
| A15‑2 | Open a Persian report's AI explanations | Display correctly right‑to‑left |

## A16. Misc UI

| ID | Steps | Expected |
|----|-------|----------|
| A16‑1 | Look at the **LLM status pill** | **🟢 LLM Online** when the AI is reachable; **🔴 LLM Offline** otherwise |
| A16‑2 | With 🔴 LLM Offline, try a run | Runs end in **Error** at the AI step (expected) — tells you the AI service is down |
| A16‑3 | Remove a file (🗑) when idle | Row removed |
| A16‑4 | **Clear Folder** while a run is active | Blocked (can't clear during processing) |
| A16‑5 | Empty state (no files) | Shows the empty prompt; Run All disabled |
| A16‑6 | Hard‑refresh after a new deploy | The latest UI loads (no stale cache) |

---

# PART B — Server‑access tests (SSH + Docker + database)

> Run these on the server. Adjust container names / ports if your setup differs.

## B1. Deployment & containers

| ID | Steps | Expected |
|----|-------|----------|
| B1‑1 | `sudo docker compose ps` | `pm-backend`, `pm-frontend`, `pm-worker-py`, `pm-minio` all running; `pm-minio-init` exited 0 |
| B1‑2 | `curl http://localhost:9700/health` | Returns JSON incl. `{"status":"ok", ...}` |
| B1‑3 | Cold start: `sudo docker compose up -d --build` | Whole stack comes up; app reachable |

## B2. Configuration & secrets (.env)

| ID | Steps | Expected |
|----|-------|----------|
| B2‑1 | After editing `.env`, recreate (not just restart): `sudo docker compose up -d --build backend` | New `.env` values take effect (restart alone does **not** reload `.env`) |
| B2‑2 | `sudo docker exec pm-backend printenv \| grep BACKUP_ADMIN` | Shows `BACKUP_ADMIN_USERNAME` / `BACKUP_ADMIN_PASSWORD` |
| B2‑3 | Backup admin seeded: `sudo docker exec pm-backend python3 -c "import sqlite3;print(sqlite3.connect('/app/data/pm_validator.db').execute('SELECT username,is_admin FROM users').fetchall())"` | Includes `('backupadmin', 1)` |
| B2‑4 | Default admin password was changed from the shipped default | Confirm before go‑live |

## B3. Data persistence

| ID | Steps | Expected |
|----|-------|----------|
| B3‑1 | Save a report, then `sudo docker compose restart backend` | Report still present after restart |
| B3‑2 | `sudo docker compose down && sudo docker compose up -d` | Users, reports, and uploaded PDFs survive (named volumes intact) |

## B4. Worker concurrency & resilience

| ID | Steps | Expected |
|----|-------|----------|
| B4‑1 | `sudo docker compose logs worker-py \| grep -E "concurrency\|worker\["` | Shows `concurrency=3` and `worker[0/1/2] starting` |
| B4‑2 | Trigger a Run All (in the browser), then watch `sudo docker compose logs -f worker-py` | Multiple files' progress lines overlap in time (real parallelism) |
| B4‑3 | Restart the worker mid‑run: `sudo docker compose restart worker-py` | In‑flight runs are re‑queued and finish; no file is stuck forever |

## B5. API security & access control (curl)

| ID | Steps | Expected |
|----|-------|----------|
| B5‑1 | `curl "http://localhost:9700/api/admin/reports?admin_username=someuser"` (non‑admin) | Rejected (403) |
| B5‑2 | `curl -X POST http://localhost:9700/api/admin/reset-password -H 'Content-Type: application/json' -d '{"admin_username":"notadmin","username":"x","newPassword":"abcdef"}'` | Rejected (403) |
| B5‑3 | `curl "http://localhost:9700/api/admin/users?admin_username=notadmin"` | Rejected (403) |
| B5‑4 | `curl -X POST http://localhost:9700/worker/claim` (no/invalid `X-Worker-Token`) | If `WORKER_TOKEN` is set: **403**. If it's empty: returns a claim (a finding — set `WORKER_TOKEN`). |
| B5‑5 | From the **public** URL users open (the frontend, e.g. `:8080`): `curl -i http://<host>:8080/worker/claim` | Returns the app's **index.html** (SPA fallback) or 404 — **never** a worker JSON `{"run":...}`. nginx must not proxy `/worker/*`. |
| B5‑6 | `curl http://localhost:9700/api/task-rules` | Returns the rules JSON (public read used by the worker) |
| B5‑7 | Inspect the DB `users` table | Passwords are **hashed**, never plaintext |

## B6. Backend health & integrations

| ID | Steps | Expected |
|----|-------|----------|
| B6‑1 | `curl http://localhost:9700/health` shows the LLM field | `llm.available` true when the inference server is up |
| B6‑2 | Stop/unreachable LLM, run a file | Job ends in **Error** (graceful); UI shows 🔴 LLM Offline |
| B6‑3 | MinIO bucket/policy | `pm-minio-init` log shows the bucket policy set; photos load in reports |
| B6‑4 | Oversized PDF (> 50 MB) via the app | Rejected by the size limit; no crash |
| B6‑5 | Hammer `/extract` beyond its limit | Returns 429 (rate limited), not a crash |

## B7. Logs & audit (server side)

| ID | Steps | Expected |
|----|-------|----------|
| B7‑1 | `sudo docker compose logs backend` after some activity | App + access logs present; errors traceable |
| B7‑2 | Audit DB receives events (login, run, stop, password reset) | Rows recorded with user + timestamp |

## B8. Break‑glass: admin lockout recovery

| ID | Steps | Expected |
|----|-------|----------|
| B8‑1 | With a **backup admin** configured, "forget" the primary admin password | Backup admin logs in and resets the primary from the **Users** tab — no DB access needed |
| B8‑2 | (Both admins lost) Reset directly in the DB: `sudo docker exec -it pm-backend python3 -c "import hashlib,sqlite3;h=hashlib.sha256('NewPass'.encode()).hexdigest();c=sqlite3.connect('/app/data/pm_validator.db');print(c.execute('UPDATE users SET password_hash=? WHERE username=? AND is_admin=1',(h,'admin')).rowcount);c.commit()"` | `1` row updated; login works with the new password |

---

# Sign‑off

| Area | Tester | Date | Result | Notes |
|------|--------|------|--------|-------|
| A1–A2 Accounts & access | | | | |
| A3 Upload lifecycle | | | | |
| A4–A6 Run/Stop/Run All/Stop All & sequences | | | | |
| A7 Server‑side processing | | | | |
| A8–A9 Reports & dashboards | | | | |
| A10–A13 Admin tools | | | | |
| A14–A16 Validation, Persian, misc | | | | |
| B1–B3 Deploy, config, persistence | | | | |
| B4 Worker | | | | |
| B5–B6 Security & integrations | | | | |
| B7–B8 Logs & recovery | | | | |

**Release approved by:** ______________________  **Date:** ____________
