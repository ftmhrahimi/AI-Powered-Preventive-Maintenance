# PM Batch Validator — Technical Documentation

Engineering reference for the PM (Preventive Maintenance) Report Validator:
architecture, technology, modules, data model, processing pipeline, and the
server‑side execution model. Intended for developers, reviewers, and technical
stakeholders.

---

## 1. What the product does (in one paragraph)
Field engineers submit **preventive‑maintenance report PDFs** (a checklist with
"OK / Not OK" marks plus site photos). The system extracts the photos and their
metadata, then validates each checklist item using a vision **LLM** combined with
deterministic checks (photo **capture date**, photo **GPS** vs. the registered
site, and admin‑defined **task rules**). It produces a per‑report **Acceptance %**
and per‑item verdicts with explanations, stored per user with admin oversight.
All heavy processing runs **server‑side** so users can close their browser and
the work continues.

---

## 2. High‑level architecture

```
                         ┌──────────────────────────────────────────────┐
   Browser (user)        │                 Docker network                │
  ┌───────────────┐      │                                              │
  │ index.html    │ HTTP │  ┌───────────┐    ┌──────────┐   ┌─────────┐ │
  │ (SPA + engine)│◄────►│  │ frontend  │    │ backend  │   │  minio  │ │
  └───────────────┘ nginx│  │ (nginx)   │──► │ (Flask + │──►│ (S3 obj │ │
        ▲                │  │ serves SPA│    │ gunicorn)│   │ storage)│ │
        │                │  │ proxies   │    └────┬─────┘   └─────────┘ │
        │                │  │ /api,/pm- │         │                     │
        │                │  │ photos    │         │ /worker/*           │
        │                │  └───────────┘    ┌────▼──────┐              │
        │                │                   │  worker   │  headless    │
        │  (results via  │                   │ (Playwright Chromium)    │
        │   server run)  │                   │  runs the SAME SPA code) │
        └────────────────┼───────────────────┴──────────┬───────────────┘
                         │                               │ HTTP
                         └───────────────────────────────▼──────────────►
                                                  External vLLM (LLM inference)
```

**Five runtime services** (`docker-compose.yml`):
- **frontend** — nginx serving the single‑file SPA (`index.html`), and reverse‑
  proxying `/api/*` to the backend and `/pm-photos/*` to MinIO. The SPA contains
  the *entire validation engine*.
- **backend** — Flask app (under gunicorn) for auth, persistence, PDF photo
  extraction (`/extract`), and the server‑run queue.
- **worker** — a headless Chromium (Playwright) that loads the **same SPA** and
  drives its engine, so server‑side runs produce identical output to a browser.
- **minio** — S3‑compatible object store for extracted **photos** and their
  **metadata JSON**.
- **minio‑init** — one‑shot container that creates the bucket and sets an
  anonymous read policy on startup.

External dependency: a **vLLM** server (OpenAI‑compatible `/v1/chat/completions`)
for all AI inference. Not part of the compose stack.

---

## 3. Technology stack

| Layer | Technology |
|------|------------|
| Frontend | Single HTML file: vanilla JS (no framework), **pdf.js** (client‑side PDF render/text), Canvas API (checkbox detection), IndexedDB (local PDF cache) |
| Frontend build | `build.mjs` + `html-minifier-terser` (minify markup/CSS/JS; top‑level names preserved) |
| Backend | **Python 3 / Flask**, **gunicorn** (WSGI), Flask‑CORS, Flask‑Limiter (rate limiting) |
| PDF extraction (backend) | **PyMuPDF (fitz)**, **Pillow** |
| Object storage | **MinIO** (S3 API), served read‑only to the browser via nginx `/pm-photos/` |
| Database | **SQLite** (two files: `pm_validator.db`, `audit.db`) |
| Headless worker | **Playwright** (sync API) + Chromium, `requests` |
| AI inference | External **vLLM** (vision‑capable, OpenAI chat API) |
| Orchestration | Docker Compose; named volumes for data/logs/storage/minio |

---

## 4. Repository layout

```
frontend/
  index.html        # the SPA + the entire validation engine (~3.9k lines)
  config.js         # runtime config injected by nginx (envsubst) at container start
  build.mjs         # production minifier
  nginx.conf        # static serving + /api & /pm-photos proxy + CSP headers
  Dockerfile        # build (minify) → nginx:alpine
  js/pdf.min.js, pdf.worker.min.js
backend/
  server.py         # Flask routes (auth, reports, files, extract, server-run, admin, worker)
  db.py             # SQLite schema + all data-access functions
  extractor.py      # PyMuPDF photo extraction + per-image metadata via LLM → MinIO
  config.py         # env-driven configuration
  gunicorn.conf.py  # WSGI server config
worker/
  worker.py         # Playwright headless driver for server-side runs
docker-compose.yml  # the 5 services + volumes + network
DEPLOYMENT.md, USER_GUIDE.md, TEST_PLAN.md
```

---

## 5. End‑to‑end processing pipeline (one file)

There are **two LLM uses** and **two stages** (backend extraction, then frontend
validation). The frontend pipeline is driven either by the user's browser or,
for server runs, by the headless worker — it is the *same code*.

1. **Selection & upload** (browser): on folder/file pick, each PDF is uploaded
   **once** to backend storage (`/api/pdfs/upload`) and cached in IndexedDB.
2. **Photo extraction** (`processJob` → backend `/extract`):
   - Backend saves the PDF to a temp file and submits an async job to a
     `ThreadPoolExecutor`; tracks it in an in‑memory `JOB_REGISTRY` (job_id).
   - `extractor.process_pdf` (PyMuPDF): finds the **Task ID**, locates each
     checklist row by its **OK / Not OK** text anchors, extracts the images
     belonging to each row, and uploads each as
     `photos/<taskId>/<row>/<n>.jpg` to MinIO.
   - For each image it calls the **LLM (use #1)** to read EXIF‑like metadata
     (`date_time`, `lat`, `lng`, `taskID`) and uploads it as
     `photos/<taskId>/<row>/<n>.json`. Missing values default to `"unknown"`.
   - The browser polls `/job/<job_id>` for progress until done.
3. **Item validation** (frontend `processAudit`/`validateAllItems`):
   - pdf.js reads the PDF text layer → checklist **items** (number, description,
     reported OK/NotOK). Checkbox state is also confirmed by rasterising the row
     to canvas and detecting the ticked box.
   - For each item: fetch its photos + metadata JSON from MinIO; compute the
     **date** check (within `DATE_TOLERANCE_DAYS`) and **GPS** check (haversine
     distance ≤ `GPS_RADIUS_METERS` of the site coordinates).
   - Build a validation prompt including the matching **task rule** (if any) and
     call the **LLM (use #2)** for a verdict: `CONFIRMED | DISPUTED | NO_EVIDENCE`.
   - System causes (date/GPS failures) force `DISPUTED` regardless of the AI.
4. **Aggregate & persist**: compute **Acceptance %** = confirmed ÷ total, set the
   job `done`, and save per‑file state to the backend (`/api/userfiles`). The
   user can then open and **Save Report** (`/api/reports`) to make it appear in
   dashboards.

---

## 6. Module reference

### 6.1 Frontend — `frontend/index.html`
A single page that is both the UI **and** the processing engine. Key subsystems
(all global functions; inline `onclick` handlers rely on stable top‑level names,
which the minifier preserves):

- **Auth/session**: `doLogin`, `doRegister`, `setSessionUser`, `startApp`. Session
  is held in `localStorage['pm_session']`; on load the app restores the user and
  their files. (The worker seeds this same key to "log in".)
- **File & upload lifecycle**: `handleFiles` (dedup prompt, IndexedDB cache,
  one‑time upload), `uploadFile` / `ensureUploaded` / `retryUpload`, and the
  per‑job `uploadStatus` (`uploading | uploaded | error`) — *independent* of run
  status. Upload progress shows in a dedicated bottom‑right toast.
- **Job model & rendering**: `jobs[]` array, `buildJobRow`, `renderJobsTable`,
  `setJob` (mutate + render + persist), `updateGlobalBtns`, `updateSummary`.
- **Run/stop controls**: `runAll`, `runServerSingle`, `stopSingle`, `stopAll`,
  `launchServerJobs` — all operate through the **server‑run model** (§7).
- **Server‑run watcher**: `startServerRunView` polls `/api/server-run`, merges
  per‑file state (`mergeServerFiles`), and tracks live files in
  `serverActiveTargets` / `startingFiles`.
- **Local engine (the real pipeline)**: `runAllLocal` (worker queue, `MAX_
  CONCURRENT=3`), `processJob`, `validateAllItems`, `buildValidationPrompt`,
  `extractTasksFromPdf`, checkbox detection, `extractImageMeta`, `haversine`,
  `fixPersian` (NFKC). **Only the headless worker calls `runAllLocal`** — the
  human UI delegates to the server.
- **Reports/UI**: `openModal`/`renderModalContent`, lightbox (`openLightbox`),
  `saveCurrentReport`, dashboards (`renderHistory`, `renderAdmin`), admin tabs
  (Task Rules, Sites, Users, Audit), `checkLlmHealth` (status pill).

### 6.2 Backend — `backend/server.py`
Flask application (CORS + rate limiting). Responsibilities:
- **Auth**: `/api/auth/register`, `/api/auth/login`.
- **Reports & files**: `/api/reports` (CRUD), `/api/userfiles` (per‑file state
  upsert), `/api/pdfs/*` (upload/list/download/delete), `/api/files/replace`.
- **Photo extraction**: `/extract` (async via `ThreadPoolExecutor` +
  `JOB_REGISTRY`), `/job/<id>` (progress), `/stop-job/<id>`, `/stop-all`
  (in‑memory `STOP_ALL_FLAG`).
- **Server‑run queue**: `/api/server-run` (POST enqueue / GET status incl. active
  runs), `/api/server-run/cancel` (per‑target or all).
- **Admin**: `/api/admin/reports`, `/api/admin/task-rules`, `/api/admin/sites`,
  `/api/admin/users`, `/api/admin/reset-password`, `/audit`. Plus public reads
  `/api/sites` and `/api/task-rules` (needed by the worker during validation).
- **Worker‑internal** (not proxied by nginx; optional `X-Worker-Token`):
  `/worker/claim`, `/worker/heartbeat`, `/worker/complete`, `/worker/run-status`.
- Cross‑cutting: `log_event` (writes to the audit DB), structured logging, a
  background maintenance thread (`requeue_stale_running`).

### 6.3 Backend — `backend/extractor.py`
PyMuPDF + Pillow + MinIO. `process_pdf` → `taskID_extracator`,
`ok_not_ok_locations` (find rows by OK/Not OK anchors), `image_extractor`
(map images to rows, upload JPEGs), `extract_fields_to_minio` (per‑image LLM
metadata → JSON). MinIO client is created lazily with retries and re‑applies the
anonymous read policy on connect. Honours a `stop_check` callback for cancellation.

### 6.4 Backend — `backend/db.py`
SQLite schema creation + all data‑access functions. Creates the **primary admin**
and an optional **backup admin** from env on startup (insert‑if‑missing). Tables
in §9. Passwords hashed with **SHA‑256** (`hash_password`). Server‑run helpers:
`enqueue_server_run`, `claim_next_server_run`, `heartbeat_server_run`,
`finish_server_run`, `requeue_stale_running`, `cancel_server_run`,
`get_active_server_runs`, `get_server_run_status`.

### 6.5 `config.py` / `gunicorn.conf.py`
`config.py` centralises all env‑driven settings (LLM URL/model/timeout, MinIO
creds, ports, data/log/storage paths, DB paths). `gunicorn.conf.py` configures
the WSGI server (workers/threads/bind/logging).

### 6.6 Worker — `worker/worker.py`
The headless execution engine. `main()` spawns `WORKER_CONCURRENCY` (default 3)
threads, **each with its own Playwright + Chromium browser**, so multiple files
process in parallel. Each loop: `claim_run` → open a page as the user (seeds the
session) → wait for the SPA to restore the user's pending files → `runAllLocal
([target])` for that one file → poll for completion or per‑run cancellation
(`run_is_cancelled` by run id) → `complete_run`. A heartbeat thread keeps the run
fresh. See §7.

### 6.7 Infra
- **`nginx.conf`**: serves the SPA; proxies `/api/` → backend, `/pm-photos/` →
  MinIO; sets CSP/security headers; SPA fallback to `index.html` for unknown
  paths (so `/worker/*` on the public URL returns the app page, never the
  backend route).
- **`Dockerfile` (frontend)**: build stage runs `node build.mjs` (minify) →
  runtime nginx stage; `config.js` is rendered from a template via envsubst at
  container start.
- **`build.mjs`**: minifies HTML/CSS/JS, drops `console.*` and comments, **keeps
  top‑level identifiers** (inline handlers depend on them).
- **`docker-compose.yml`**: the 5 services, named volumes (`backend-data`,
  `backend-logs`, `backend-storage`, `minio-data`), bridge network, healthchecks.

---

## 7. Server‑side execution model (deep dive)

This is the core of the system and the source of the run/stop semantics.

**Per‑file run model.** "Run All" and single "Run" both enqueue **one
independent server‑run per file** (`server_runs` row with `target = fileName`).
This gives full per‑file isolation: each file can be started, stopped, and
re‑run independently.

**Lifecycle of a run:**
1. Browser uploads the PDF (once), marks the job running optimistically, and
   `POST /api/server-run {target}` enqueues a `pending` run (deduped per active
   target).
2. A worker thread `POST /worker/claim` → backend atomically moves the oldest
   `pending` run to `running` (in‑process lock + guarded UPDATE) and returns the
   user session.
3. The worker opens a headless page **as that user**, lets the SPA restore the
   user's files, and calls `runAllLocal([target])` — the real engine, with
   `MAX_CONCURRENT=3` *inside* the page (here only the one target is queued).
4. A heartbeat thread `POST /worker/heartbeat` keeps `updatedAt` fresh.
5. The worker polls completion (the target file reaching a terminal state) and
   `run_is_cancelled(run_id)`; on cancel it stops just that page. Then
   `POST /worker/complete {status}`.

**Concurrency.** A single worker process runs `WORKER_CONCURRENCY` independent
browser loops; the backend's claim lock prevents double‑claiming. So N files
process simultaneously across N browsers.

**Cancellation.**
- *Stop one file* → `POST /api/server-run/cancel {target}` cancels just that run;
  the owning worker stops its page; other runs continue.
- *Stop All* → cancel with no target = all the user's active runs.

**Crash/restart resilience.** If a worker dies mid‑run, the run stays `running`
until `requeue_stale_running` resets it to `pending` after
`SERVER_RUN_STALE_SECONDS` (default **900 s**), then any free worker re‑claims it.
No file is lost.

**State isolation across worker pages (critical).** Each worker page restores the
**full** file list but processes only its target. Because `setJob → saveUserFiles`
persists to a *shared* backend store, a naïve full save would overwrite other
files' live progress. This is prevented by **`__saveScope`**: `runAllLocal` sets
it to the run's target(s) so each page persists **only its own file**. The human
page leaves the scope `null` (it owns its whole view). Stops use
`saveSingleUserFile` for the same reason.

---

## 8. Frontend state management & isolation

- **Two independent lifecycles per job**: `uploadStatus` (upload) and `status`
  (run). They never drive each other — upload happens once at selection; run/stop
  reuse the uploaded file.
- **Optimistic UI**: on Run All, all rows flip to running immediately
  (`markJobLaunching`), then uploads/enqueues proceed in parallel.
- **Live‑file tracking**: `serverActiveTargets` (runs reported active by the
  backend) ∪ `startingFiles` (launched, not yet enqueued) decide which rows show
  "processing".
- **Targeted persistence**: `saveSingleUserFile` (one file) and `__saveScope`
  (worker pages) prevent cross‑file/cross‑page state clobbering.
- **Button gating**: `updateGlobalBtns` disables Run All while any file is
  uploading and toggles Run All/Stop All by run state.

---

## 9. Data model

**`pm_validator.db`** (main):
- **users** — `username` (PK), `name`, `password_hash` (SHA‑256), `is_admin`.
- **reports** — saved reports: `username`, `taskId`, `fileName`, `siteId`,
  `taskCategory/Subcategory`, `reportDate`, `fmeName`, `confirmation`, `status`,
  `data_json` (full report), `savedAt`; `UNIQUE(username, taskId)`.
- **user_files** — per‑file working state (upsert): `username`, `fileName`,
  `status`, `confirmation`, `data_json` (pct/barLabel/results…); `UNIQUE(username,
  fileName)`.
- **task_rules** — `taskCategory`, `taskSubcategory`, `taskNumber`, `expected`,
  `checkpoints` (JSON), `fail_if` (JSON); `UNIQUE(cat, sub, num)`.
- **sites** — `siteId`, `lat`, `lon`.
- **server_runs** — `id`, `username`, `status` (`pending|running|done|failed|
  cancelled`), `target` (fileName or NULL=all), `error`, `createdAt`, `updatedAt`.

**`audit.db`**: **events** — `timestamp`, `username`, `event_type`, `description`,
`detail`, `ip_address`, `job_id`, `task_id`, `status`.

**In‑memory (per backend process, not persisted)**: `JOB_REGISTRY` (`/extract`
jobs), `STOP_ALL_FLAG`. Lost on restart by design.

**MinIO** (`pm-photos` bucket): `photos/<taskId>/<row>/<n>.jpg` and
`.../<n>.json` (metadata). Served read‑only to the browser via nginx
`/pm-photos/`.

---

## 10. Validation logic details
- **Checkbox/row detection**: backend uses OK/Not OK text anchors to bound rows;
  the frontend additionally rasterises rows to canvas to confirm the ticked box.
- **Date check**: photo `date_time` vs report date, within `DATE_TOLERANCE_DAYS`
  (default 3). Unparseable/`"unknown"` → **Date missing** (treated as fail).
- **GPS check**: haversine distance between photo lat/lng and the site's
  registered coordinates ≤ `GPS_RADIUS_METERS` (default 300). No coords →
  **GPS missing**.
- **Task rules**: matched by `taskCategory → taskSubcategory → taskNumber`
  (= item row). Injected into the validation prompt as Expected/Checkpoints/
  Fail‑if. They **guide** the LLM; they do not hard‑force a verdict.
- **Verdicts**: `CONFIRMED` (OK) / `DISPUTED` (Not OK) / `NO_EVIDENCE`. Date/GPS
  system failures force `DISPUTED`. A disputed item with only date/GPS causes is
  badged **Technically Compliant**; with a content cause, **Technically
  Non‑Compliant**. **Acceptance %** = confirmed ÷ total.
- **Persian/RTL**: PDF text layers store Arabic **presentation forms**;
  `fixPersian` applies Unicode **NFKC** to normalise them to canonical letters so
  display and the LLM input are correct.

---

## 11. API reference (selected)

| Method & path | Auth | Purpose |
|---|---|---|
| `POST /api/auth/register`, `/login` | public | Account create / login |
| `POST /extract` · `GET /job/<id>` | user | Submit PDF for photo extraction · poll progress |
| `POST /stop-job/<id>` · `POST /stop-all` | user | Cancel extraction job(s) |
| `POST/GET/DELETE /api/reports` | user | Saved reports CRUD |
| `GET/POST/DELETE /api/userfiles` | user | Per‑file working state |
| `POST /api/pdfs/upload` · `GET /api/pdfs/list` · `GET /api/pdfs/download` · `DELETE /api/pdfs/delete` | user | PDF storage |
| `POST /api/server-run` · `GET /api/server-run` · `POST /api/server-run/cancel` | user | Server‑run enqueue / status / cancel |
| `GET /api/sites` · `GET /api/task-rules` | public read | Used by the worker during validation |
| `GET/POST/DELETE /api/admin/{reports,task-rules,sites,users}` · `POST /api/admin/reset-password` · `GET /audit` | admin | Admin management |
| `POST /worker/{claim,heartbeat,complete,run-status}` | worker token | Internal worker protocol (not nginx‑proxied) |

---

## 12. Configuration (key env vars)

| Var | Default | Used by |
|---|---|---|
| `LLM_SERVER_URL`, `LLM_MODEL_NAME`, `LLM_TIMEOUT_SECONDS` | — | LLM inference |
| `MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET/SECURE` | minio:9000 / minioadmin / pm-photos | Object storage |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | admin / (default) | Primary admin seed |
| `BACKUP_ADMIN_USERNAME`, `BACKUP_ADMIN_PASSWORD` | unset | Backup admin seed (recovery) |
| `WORKER_TOKEN` | "" | Auth for `/worker/*` |
| `WORKER_CONCURRENCY` | 3 | Parallel files on the worker |
| `WORKER_POLL_SECONDS`, `WORKER_*_TIMEOUT_MS` | — | Worker timing |
| `SERVER_RUN_STALE_SECONDS` | 900 | Requeue dead runs |
| `GPS_RADIUS_METERS`, `DATE_TOLERANCE_DAYS`, `PHOTO_MAX_INDEX` | 300 / 3 / 50 | Validation thresholds (frontend) |
| `ALLOWED_ORIGIN`, `FRONTEND_PORT`, `BACKEND_PORT` | * / 8080 / 9700 | CORS / ports |

> `.env` is read at container **create** time, not on `restart`. Apply changes
> with `docker compose up -d --build <service>`.

---

## 13. Security model
- **Roles**: admin vs. user. Admin endpoints check `is_admin_user`; admins come
  only from configuration (no UI to create/remove admins). One **backup admin**
  is supported for in‑app lockout recovery.
- **Passwords**: SHA‑256 hashed (unsalted — see limitations). Reset only by an
  admin via the Users tab (`ADMIN_PASSWORD_RESET` audited).
- **Worker endpoints**: `/worker/*` aren't nginx‑proxied (not reachable via the
  public URL) and can require `X-Worker-Token`. The backend port is exposed on
  the Docker host, so set `WORKER_TOKEN` if that port is on an untrusted network.
- **CORS** restricted via `ALLOWED_ORIGIN`; nginx sets CSP/X‑Frame/etc.
- **Object storage**: MinIO bucket is anonymous **read‑only** (photos are not
  secret); writes require the backend's credentials.
- **Audit log**: logins, runs, stops, cancels, password resets, rule/site changes.

---

## 14. Deployment & operations (summary)
- Build & run: `docker compose up -d --build`. Source is baked into images at
  build time (no bind mounts), so **rebuild to deploy** — `restart` reuses the
  old image and does not reload `.env`.
- Persistence via named volumes: DBs (`backend-data`), logs, PDF storage,
  MinIO data. Survive restarts.
- Recovery: locked‑out admin → the other admin resets via Users tab; both lost →
  direct SQLite `UPDATE` of `password_hash` (break‑glass).
- See `DEPLOYMENT.md` for the offline‑server procedure and `TEST_PLAN.md` for
  validation.

---

## 15. Known limitations & technical debt
- **Password hashing is unsalted SHA‑256.** Adequate for "hashed, not plaintext"
  but bcrypt/argon2 would be stronger. Migrating requires re‑hashing on next
  login or a reset.
- **No user self‑service** password change or first‑login forced change; resets
  are admin‑driven.
- **`/extract` job state is in‑memory** (`JOB_REGISTRY`) — lost on backend
  restart; server‑run state (which is persisted) is the durable layer.
- **Per‑file server runs serialise per file across pages** but rely on a single
  worker process scaling by threads/browsers; very large batches scale by raising
  `WORKER_CONCURRENCY` (memory‑bound, ~1 Chromium per slot).
- **Task rules guide, not force** — there is no deterministic "force fail" rule
  (only GPS/date are hard checks). Could be added if required.
- **Persian PDF text** depends on the source's text layer; NFKC fixes presentation
  forms, but pathological PDFs could still need OCR.
- **SQLite** is single‑node; fine for this scale, but concurrent write contention
  would push toward Postgres if usage grows substantially.

---

*Generated as engineering reference. Keep in sync with the code when modules
change.*
