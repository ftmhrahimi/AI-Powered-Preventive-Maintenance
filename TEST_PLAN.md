# PM Batch Validator — Acceptance & Regression Test Plan

**Purpose:** End‑to‑end test suite to validate the platform before delivery.
Covers authentication, role‑based access, the file upload/run/stop lifecycle
(including the recently fixed concurrency & state‑isolation bugs), server‑side
processing resilience, reporting/dashboards, admin tools, validation logic,
security, and deployment.

**How to use this document**
- Execute tests top‑to‑bottom; later sections assume earlier ones passed.
- Record **Pass/Fail**, tester, date, and notes in the *Result* column.
- Anything marked **🔴 REGRESSION** guards a previously reported bug — these
  must pass before sign‑off.
- "Backend URL" below = the address of the backend API (e.g. via the nginx
  proxy on the frontend, or `http://<host>:9700`). "App" = the frontend URL.

---

## 0. Test Environment & Preconditions

| ID | Check | Expected |
|----|-------|----------|
| ENV‑1 | All containers up: `sudo docker compose ps` | `pm-backend`, `pm-frontend`, `pm-worker`, `pm-minio` all `running` (and `pm-minio-init` exited 0) |
| ENV‑2 | Latest code is actually deployed (images rebuilt, not just restarted) | `docker compose exec frontend grep -c "__saveScope" /usr/share/nginx/html/index.html` ≥ 1; `docker compose exec backend grep -c "get_active_server_runs" /app/db.py` ≥ 1 |
| ENV‑3 | Worker concurrency active | `docker compose logs worker \| grep -E "concurrency\|worker\["` shows `concurrency=3` and `worker[0/1/2] starting` |
| ENV‑4 | Health endpoint | `curl <backendURL>/health` → `{"status":"ok"}` |
| ENV‑5 | LLM inference server reachable | A full single‑file run completes to **Done** (proves `LLM_URL` works) |
| ENV‑6 | MinIO bucket/policy set | `pm-minio-init` log shows "MinIO bucket policy set"; photos load in a report |

**Test data needed**
- 5–10 valid PM report PDFs (mix of small and large; ≥ 3 needed for concurrency tests).
- At least one PDF with known GPS/site, date, and checklist values (to verify validation math).
- One non‑PDF file (e.g. `.txt`/`.png`).
- One oversized file (> 50 MB) for the size‑limit test.
- Admin credentials (from `.env`), and a fresh non‑admin account.

---

## 1. Authentication & Session

| ID | Steps | Expected |
|----|-------|----------|
| AUTH‑1 | Register a new user with valid name/username/password | Account created; auto sign‑in or redirect to login |
| AUTH‑2 | Register with an existing username | Rejected with a clear error; no duplicate created |
| AUTH‑3 | Register with password < 6 chars / mismatched confirm | Client‑side validation blocks submit |
| AUTH‑4 | Login with correct credentials | Lands on **Validator** (user) / **Dashboard** (admin) |
| AUTH‑5 | Login with wrong password | Rejected; no session created |
| AUTH‑6 | Login as admin (`ADMIN_USERNAME`) | Admin‑only tabs visible (Audit, Task Rules, Sites, all‑user Dashboard) |
| AUTH‑7 | Sign out, then reload page | Returns to login; protected views not accessible |
| AUTH‑8 | Refresh page while signed in | Session restored (no forced re‑login); previously loaded files reappear |
| AUTH‑9 | API auth guard | `curl <backendURL>/api/admin/reports` (no/invalid admin) → denied |

---

## 2. Navigation & Role‑Based Access

| ID | Steps | Expected |
|----|-------|----------|
| NAV‑1 | As **non‑admin**, inspect tab bar | Only **Validator** + **Dashboard** (own) visible. Admin/Audit/Task Rules/Sites hidden |
| NAV‑2 | As **admin**, inspect tab bar | Admin Dashboard, Audit, Task Rules, Sites all visible |
| NAV‑3 | Non‑admin hits admin API directly (`/api/admin/task-rules`, `/api/admin/sites`, `/api/admin/reports`) | Rejected (no data leak) |
| NAV‑4 | Switch between tabs repeatedly | No stale data; each tab loads its own content |

---

## 3. File Selection & Upload Lifecycle  🔴 REGRESSION

> Upload must happen **once**, at selection, and be **decoupled** from run/stop.

| ID | Steps | Expected |
|----|-------|----------|
| UP‑1 | Click **Select Folder**, choose a folder of PDFs | Rows appear immediately; bottom‑right **upload notification** shows `"x of N files uploaded"` and progresses to N/N, then auto‑hides |
| UP‑2 | Click **＋ Add Files**, add more PDFs | New rows added & uploaded once; existing rows untouched |
| UP‑3 | Select a non‑PDF file | Ignored / filtered out (only `.pdf` accepted) |
| UP‑4 | Add a file with a name that already exists | Duplicate prompt appears; choosing *replace* cleans up old backend copy & re‑uploads; *skip* leaves original |
| UP‑5 | **While files are still uploading**, observe the **Run All** button | **Disabled** (greyed) with tooltip "Files are still uploading"; per‑row **Run** also disabled |
| UP‑6 | Uploads finish | **Run All** & per‑row **Run** re‑enable automatically |
| UP‑7 | Network/upload failure simulation (stop backend briefly during UP‑1, or block `/api/pdfs/upload`) | Affected rows show **⟳ Retry upload**; a warning toast lists how many failed; **no silent retry loop** |
| UP‑8 | Click **⟳ Retry upload** on a failed row (backend restored) | That **one** file re‑uploads; on success the row becomes runnable; others untouched |
| UP‑9 | Verify upload is **not** repeated by running | Open browser DevTools → Network. Run a file, Stop it, Run again. **No new `POST /api/pdfs/upload`** is issued on Run/Stop cycles |
| UP‑10 | Confirm bytes on server | `curl "<backendURL>/api/pdfs/list?username=<u>"` lists every selected file once |

---

## 4. Single‑File Run / Stop  🔴 REGRESSION

| ID | Steps | Expected |
|----|-------|----------|
| SR‑1 | Click **▶ Run** on one file | Status → running; bar advances with real labels (Submitting → Extracting → Validating → Complete) |
| SR‑2 | Let it finish | Status **Done**, 100%, Acceptance % shown, **View Report** enabled |
| SR‑3 | Click **■ Stop** mid‑run | That file → **Stopped**, bar resets to 0; **no other file affected**; global state stays consistent |
| SR‑4 | **Re‑run** a stopped file | Reuses already‑uploaded file (no re‑upload, see UP‑9); runs to completion |
| SR‑5 | **Re‑run** a Done file | Re‑processes and overwrites its prior result |
| SR‑6 | Stop a file the instant it starts (before first progress) | Cleanly stops; row shows Stopped; can be re‑run |

---

## 5. Run All / Stop All + Concurrency  🔴 REGRESSION

> Core of the recent fixes: parallel start, parallel real progress, isolated state.

| ID | Steps | Expected |
|----|-------|----------|
| RA‑1 | With ≥ 3 pending files, click **Run All** | **All** rows switch to running/queued **immediately** (no waiting for each upload) |
| RA‑2 | Observe progress | Up to `WORKER_CONCURRENCY` (default **3**) files show **real, simultaneous** progress; remaining show "Waiting…" |
| RA‑3 | 🔴 **Progress isolation** | **No** bar resets/empties; **no** jumping between files; each bar reflects only its own file. As a slot frees, a waiting file begins |
| RA‑4 | Let the whole batch finish | Every file → Done; summary counters (Total/Done/Disputed/Avg %) correct |
| RA‑5 | **Stop All** mid‑batch | All running files → Stopped; **Run All** reappears; **Stop All** hides; state consistent |
| RA‑6 | Button visibility logic | While any run active: **Run All** hidden, **Stop All** shown. When idle: reverse |
| RA‑7 | Server log cross‑check | `docker compose logs worker` shows multiple `processing server-run` entries overlapping in time (true parallelism) |

---

## 6. Independence of All Four Controls — Sequence Matrix  🔴 REGRESSION

> Every sequence must leave the UI **and** backend state consistent. After each,
> reload the page (AUTH‑8) and confirm the table matches what you last saw.

| ID | Sequence | Expected end state |
|----|----------|--------------------|
| SEQ‑1 | Run All → Stop **one** file → that file shows Stopped | Only that file stopped; the other files keep running unaffected |
| SEQ‑2 | Run All → Stop one → **Run** that one again | Stopped file re‑runs; others unaffected; no re‑upload |
| SEQ‑3 | Run All → Stop one → **Stop All** | All stop; no orphaned "running" rows; Run All returns |
| SEQ‑4 | Run **one** → while it runs, **Run All** | Remaining pending files start; the already‑running one is not restarted/duplicated |
| SEQ‑5 | Run All → let 1 finish → Stop All | Finished file stays **Done** (not reverted to Stopped); rest Stopped |
| SEQ‑6 | Run All → Stop All → Run All again | Second Run All cleanly restarts all eligible files |
| SEQ‑7 | Run one → Stop one (same) → Run All → Stop All | No deadlock; buttons responsive throughout; final state consistent |
| SEQ‑8 | Rapidly double‑click **Run All** | No duplicate runs/rows; backend dedups per file |

---

## 7. Server‑Side Processing Resilience

> Work runs on the always‑on server; the user's machine can leave.

| ID | Steps | Expected |
|----|-------|----------|
| RES‑1 | Run All, then **close the browser tab**; reopen & sign in | Run continues server‑side; on return the table reflects live/finished progress |
| RES‑2 | Run All, then **sign out** and back **in** | Same — progress/results persisted and shown |
| RES‑3 | Run All, **lock screen / sleep** the client for a few minutes | Run unaffected; results present on return |
| RES‑4 | Banner copy | "☁ Server is processing…" banner appears while active and clears when done |
| RES‑5 | Kill & restart the **worker** mid‑run (`docker compose restart worker`) | Stale `running` runs are re‑queued and complete (no permanent stuck file) |
| RES‑6 | Stop All while watching a resumed run | Server run cancelled; files stop |

---

## 8. Report Viewing

| ID | Steps | Expected |
|----|-------|----------|
| REP‑1 | Click **View Report** on a Done file | Modal opens with parsed header, per‑item results, acceptance/confirmation, and photos |
| REP‑2 | Photos | Item photos load from MinIO (no broken images) |
| REP‑3 | Item verdicts | Pass/fail per checklist item matches the rules; failed items highlighted |
| REP‑4 | Close & reopen modal | Renders consistently; no leftover state from previous file |
| REP‑5 | Save/persist report | Report appears under **Dashboard**; survives reload |

---

## 9. User Dashboard (own history)

| ID | Steps | Expected |
|----|-------|----------|
| DASH‑1 | Open **Dashboard** as non‑admin | Lists only the current user's reports |
| DASH‑2 | Filters (Task ID, Site ID, min/max acceptance %) | Rows filter correctly; clearing restores |
| DASH‑3 | Column sort (e.g. Acceptance Rate) | Sorts asc/desc; indicator updates |
| DASH‑4 | Summary stats | Totals/averages match the filtered rows |
| DASH‑5 | Export (if present) | Exported file matches on‑screen filtered data |
| DASH‑6 | Open a report from Dashboard | Same modal as REP‑1 |

---

## 10. Admin Dashboard (all users)

| ID | Steps | Expected |
|----|-------|----------|
| ADM‑1 | Open Admin Dashboard | Reports across **all** users, with Owner column |
| ADM‑2 | Filter by Owner/Task/Site/% | Correct filtering |
| ADM‑3 | Sort columns | Works as DASH‑3 |
| ADM‑4 | Cross‑user isolation check | A non‑admin can never see another user's data (verify via NAV‑3 + DASH‑1) |

---

## 11. Audit Log (admin)

| ID | Steps | Expected |
|----|-------|----------|
| AUD‑1 | Open **Audit** | Recent events listed (login, run requested/started/finished, stop, cancel, etc.) |
| AUD‑2 | Perform a login + a Run All, refresh Audit | New events appear with user, type, timestamp |
| AUD‑3 | Filters (user/event/task) | Narrow results correctly |
| AUD‑4 | Stop events recorded | Single Stop and Stop All produce distinct audit entries |

---

## 12. Task Rules CRUD (admin)

| ID | Steps | Expected |
|----|-------|----------|
| TR‑1 | Add a rule (category/subcategory/task #, expected, checkpoints, fail‑if) | Saved; appears in table |
| TR‑2 | Required‑field validation | Missing category/subcategory/number → blocked with message |
| TR‑3 | Edit/overwrite a rule | Updated value persists |
| TR‑4 | Delete a rule | Removed from table & backend |
| TR‑5 | Effect on validation | A processed report uses the updated rule (run a matching PDF, confirm verdict changes accordingly) |

---

## 13. Sites CRUD (admin)

| ID | Steps | Expected |
|----|-------|----------|
| ST‑1 | Add a site (Site ID, Lat, Lon) | Saved & listed |
| ST‑2 | Validation | Non‑numeric lat/lon or missing ID → blocked |
| ST‑3 | Delete a site | Removed |
| ST‑4 | GPS validation uses it | Process a report for that site; GPS check uses the stored coordinates |

## 13a. Users — password reset (admin)

| ID | Steps | Expected |
|----|-------|----------|
| USR‑1 | Open **👤 Users** tab as admin | User list (username, name, role) loads; reset form visible |
| USR‑2 | Pick a user, enter matching new passwords (≥6), **Reset Password** | Success confirmation; audit entry `ADMIN_PASSWORD_RESET` created |
| USR‑3 | Sign in as that user with the **new** password | Login succeeds |
| USR‑4 | Sign in with the **old** password | Login fails |
| USR‑5 | Try password < 6 chars or mismatched confirm | Blocked with a clear message; no change made |
| USR‑6 | Call `/api/admin/users` or `/api/admin/reset-password` as a **non‑admin** | Rejected (403) |

---

## 14. Validation Logic Correctness

> Use the known‑value PDF so expected results are deterministic.

| ID | Check | Expected |
|----|-------|----------|
| VAL‑1 | **GPS radius** (`GPS_RADIUS_METERS`, default 300 m) | Report GPS within radius of site → pass; outside → fail. Test both a near and far coordinate |
| VAL‑2 | **Date tolerance** (`DATE_TOLERANCE_DAYS`, default 3) | Report date within ±3 days of expected → pass; beyond → fail |
| VAL‑3 | **Acceptance / Confirmation %** | Equals `round(confirmed items / total items × 100)`; spot‑check the math on one report |
| VAL‑4 | **Checkbox / checklist detection** | Checked vs unchecked items detected correctly vs the source PDF |
| VAL‑5 | **Photo extraction** | Number of photos per item matches the PDF (up to `PHOTO_MAX_INDEX`) |
| VAL‑6 | **English vs Persian PDF** | Both render and parse without garbling |

---

## 15. Edge Cases & Error Handling

| ID | Steps | Expected |
|----|-------|----------|
| EDGE‑1 | Upload file > 50 MB | Rejected by size limit with clear feedback (no crash) |
| EDGE‑2 | Corrupt / non‑report PDF | Job ends in **Error** with a message; other jobs unaffected |
| EDGE‑3 | LLM server down during run | Job fails gracefully (Error), retryable; UI not frozen |
| EDGE‑4 | Backend down during run | UI shows transient errors but recovers polling when backend returns |
| EDGE‑5 | Remove a file (🗑) while idle | Row removed; backend PDF + record + IndexedDB cleaned |
| EDGE‑6 | Clear Folder | All files removed from UI + backend + IndexedDB; blocked while a run is active |
| EDGE‑7 | Empty state | With no files, table shows the empty prompt; Run All disabled |
| EDGE‑8 | Rate limiting | Hammer `/extract` beyond its limit → 429 (not a crash) |

---

## 16. Security & Permissions

| ID | Steps | Expected |
|----|-------|----------|
| SEC‑1 | Direct call to admin endpoints as non‑admin | Denied |
| SEC‑2 | Access another user's files: `GET /api/userfiles?username=<other>` | Should not expose data to an unauthorized caller (verify access control) |
| SEC‑3 | Download another user's PDF via `/api/pdfs/download` | Properly scoped/denied |
| SEC‑4 | Worker‑only endpoints (`/worker/claim`, `/worker/run-status`, `/worker/complete`) | Require `X-Worker-Token` when configured; rejected without it |
| SEC‑5 | CORS | Only `ALLOWED_ORIGIN` permitted (cross‑origin from elsewhere blocked) |
| SEC‑6 | Password storage | Passwords are hashed in the DB (not plaintext) |
| SEC‑7 | Default admin password changed | Confirm the shipped default was rotated before delivery |

---

## 17. Concurrency / Load

| ID | Steps | Expected |
|----|-------|----------|
| LOAD‑1 | Run All on 10+ files | Processes `WORKER_CONCURRENCY` at a time; all eventually Done; no clobbered progress (RA‑3 holds at scale) |
| LOAD‑2 | Two different users run batches at the same time | Each sees only their own progress; no cross‑user interference |
| LOAD‑3 | Increase `WORKER_CONCURRENCY` (e.g. 5), rebuild worker | That many files process concurrently; memory stays acceptable |
| LOAD‑4 | Long batch left overnight (optional) | Heartbeat keeps runs alive; no premature "stale" requeue thrash |

---

## 18. Deployment / Operational

| ID | Steps | Expected |
|----|-------|----------|
| DEP‑1 | Cold `docker compose up -d --build` | Stack comes up; minio‑init sets policy; app reachable |
| DEP‑2 | Restart individual services | Backend/worker/frontend restart cleanly and reconnect |
| DEP‑3 | Data persistence | Reports/users/PDFs survive container restart (named volumes intact) |
| DEP‑4 | Config via `.env` | Changing `WORKER_CONCURRENCY`, `GPS_RADIUS_METERS`, etc. takes effect after rebuild |
| DEP‑5 | Logs | App + access logs written; errors traceable |

---

## 19. Browser / Compatibility

| ID | Check | Expected |
|----|-------|----------|
| BR‑1 | Chrome/Edge (primary) | Full functionality incl. folder picker (`webkitdirectory`) |
| BR‑2 | Firefox | Works (note folder‑picker differences if any) |
| BR‑3 | Hard refresh after deploy | New `index.html` served (no stale cache) |
| BR‑4 | Responsive layout | Tables/modals usable at common window sizes |

---

## 20. Regression Quick‑Suite (run before every release)

Minimum gate that exercises every previously‑fixed bug:

1. **UP‑5/UP‑6** — Run All disabled during upload, re‑enables after.
2. **UP‑9** — Stop→Run causes no re‑upload.
3. **RA‑1/RA‑2** — Run All starts all at once; 3 progress in parallel.
4. **RA‑3** — No progress bar reset/jump (state isolation).
5. **SEQ‑1/SEQ‑2/SEQ‑3** — Stopping one file never corrupts the others or global state.
6. **SEQ‑5** — Finished file stays Done through Stop All.
7. **RES‑1** — Close tab; run continues server‑side.

All 7 must pass.

---

### Sign‑off

| Area | Tester | Date | Result | Notes |
|------|--------|------|--------|-------|
| Auth & Access | | | | |
| Upload lifecycle | | | | |
| Run/Stop (single) | | | | |
| Run All / Stop All / Concurrency | | | | |
| Sequence matrix | | | | |
| Server‑side resilience | | | | |
| Reports & Dashboards | | | | |
| Admin tools (Audit/Rules/Sites) | | | | |
| Validation logic | | | | |
| Security | | | | |
| Deployment | | | | |

**Release approved by:** ______________________  **Date:** ____________
