# PM Portal — Offline Server Deployment Guide

Target server: **<PRODUCTION_SERVER>** (offline / air-gapped Linux server with Docker, Docker Compose, and a running vLLM service on port 8000. Nothing else is installed.)

The stack consists of four containers plus the existing vLLM service:

| Service   | Container     | Purpose                                            | Host port |
|-----------|---------------|----------------------------------------------------|-----------|
| frontend  | pm-frontend   | nginx — serves the UI and proxies all API traffic  | 80        |
| backend   | pm-backend    | Flask/gunicorn — auth, reports, photo extraction, LLM metadata, queue API | 9700 |
| worker-py | pm-worker-py  | Python engine (no browser) — extracts items, detects checkboxes, validates photos | — (internal only) |
| minio     | pm-minio      | Object storage for extracted photos/metadata       | 9001 (console only) |
| vLLM      | *(existing)*  | LLM inference — **not** managed by this compose    | 8000      |

All traffic between containers uses the internal Docker network `pm-net`.
The browser only needs `http://<PRODUCTION_SERVER>` (port 80); nginx proxies
`/api`, `/extract`, `/job`, `/health`, `/audit`, `/stop-all` to the backend
and `/pm-photos` to MinIO.

---

## 1. Build the images on a machine WITH internet access

The offline server cannot pull base images (`python:3.11-slim`, `nginx:alpine`,
`minio/minio`), so build and export everything on a connected machine first
(any Linux/Mac/WSL machine with Docker).

```bash
# On the connected machine, in the project root:
docker compose build                 # builds backend, frontend AND worker-py
docker pull minio/minio:latest       # MinIO is used as-is, just pull it
```

> **Note.** The processing engine is now a small Python image
> (`python:3.11-slim`, no browser) — a few hundred MB instead of the old
> ~2 GB Chromium worker. `docker compose build` pulls every base image
> (`python:3.11-slim`, `node:20-alpine`, `nginx:alpine`) on the connected
> machine, so the air-gapped server needs no internet.

The frontend build is a multi-stage Docker build: a temporary `node:20-alpine`
stage minifies and strips `index.html` (production build), then the result is
copied into the final nginx image. This needs internet only on the connected
build machine — nothing extra is shipped to the offline server.

```bash
# Export all four images into a single archive:
docker save -o pm-portal-images.tar \
  pm-portal-backend:latest \
  pm-portal-frontend:latest \
  pm-portal-worker-py:latest \
  minio/minio:latest
```

`docker save` writes the complete images (including base layers) to a tar file
that can be moved on a USB drive or over the internal network.

## 2. Copy files to the server

You need exactly two things on the server:

1. `pm-portal-images.tar` — the images
2. The project directory (for `docker-compose.yml` and `.env`)

```bash
# From the connected machine (replace <user>):
scp pm-portal-images.tar <user>@<PRODUCTION_SERVER>:/opt/
scp -r PM_portal <user>@<PRODUCTION_SERVER>:/opt/pm-portal
```

Recommended directory layout on the server:

```
/opt/pm-portal/
├── docker-compose.yml
├── .env                  ← configuration (edit before first start)
├── backend/              ← only needed if you rebuild on the server
└── frontend/
```

## 3. Load the images on the server

```bash
cd /opt
docker load -i pm-portal-images.tar
docker images          # verify: pm-portal-backend, pm-portal-frontend, pm-portal-worker-py, minio/minio
```

`docker load` imports the images into the local Docker engine — no internet needed.

## 4. Configure

Create `.env` from the template and edit it:

```bash
cd /opt/pm-portal
cp .env.example .env
nano .env            # or vi
```

`.env.example` documents every variable. The ones you **must** set:

- `LLM_SERVER_URL=http://<PRODUCTION_SERVER>:8000/v1/chat/completions` — your vLLM
  endpoint (adjust the path if vLLM serves a different route). Used by both the
  backend (photo date/GPS metadata) and the worker (validation).
- `LLM_MODEL_NAME` — the model name vLLM was started with
  (check: `curl http://<PRODUCTION_SERVER>:8000/v1/models`).
- `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` — **change these**; they are both the
  MinIO root credentials and the backend's access credentials.
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` — the primary portal admin login.
- `BACKUP_ADMIN_USERNAME` / `BACKUP_ADMIN_PASSWORD` *(recommended)* — seed a single
  **backup admin** so a locked-out primary admin can be recovered in-app (either
  admin can reset the other from the Users tab). Keep these separate and safe.
- `ALLOWED_ORIGIN=http://<PRODUCTION_SERVER>` — the URL users open in the browser.

Useful optional knobs (sensible defaults already in `.env.example`):

- `WORKER_CONCURRENCY=3` — files processed in parallel by the worker.
- `LLM_IMAGE_MAX_W=1000` — validation photos are downscaled to this width before
  the LLM call (avoids vLLM 400s on multi-photo items); set `0` for full size.
- `LLM_TIMEOUT_SECONDS`, `GPS_RADIUS_METERS`, `DATE_TOLERANCE_DAYS`, `PHOTO_MAX_INDEX`.
- `WORKER_TOKEN` — shared secret for the internal `/worker/*` queue endpoints
  (defence-in-depth; they are not proxied by nginx). If set, the same value is
  read by both `backend` and `worker-py`.

## 5. Start everything

```bash
cd /opt/pm-portal
docker compose up -d
```

`-d` runs in the background. The first start creates the named volumes
(`backend-data`, `backend-logs`, `backend-storage`, `minio-data`), waits for
MinIO to become healthy, then starts the backend and frontend.

All services use `restart: unless-stopped`, so they **start automatically
after a server reboot** (as long as the Docker daemon is enabled:
`sudo systemctl enable docker`).

## 6. Verify

```bash
docker compose ps          # all services should be "running (healthy)"

# Backend health (also reports vLLM availability):
curl http://<PRODUCTION_SERVER>:9700/health
# → {"status":"ok","llm":{"available":true,...}}

# Frontend through nginx:
curl -I http://<PRODUCTION_SERVER>/            # → HTTP 200
curl http://<PRODUCTION_SERVER>/health         # proxied backend health

# MinIO:
docker compose exec minio mc ready local  # → "The cluster is ready"
```

Then open `http://<PRODUCTION_SERVER>` in a browser and log in with the admin
account from `.env`.

## 6a. How processing works (server-side)

All processing runs on the **always-on server**, so a user can upload their
files, start them, and close the browser or shut down their machine — the work
finishes on its own and the results are there when they return.

1. The user selects PDFs (uploaded once to the backend) and clicks **▶ Run All**
   (or per-file **▶ Run**). The browser records the request via
   `POST /api/server-run` and can then be closed safely.
2. The `worker-py` container claims each file from the queue (`/worker/claim`)
   and, in pure Python (no browser): extracts the checklist items, detects each
   row's OK/Not-OK checkbox, fetches the photos + date/GPS metadata, and asks the
   LLM to validate each item.
3. Progress and results are written back to the backend as each step completes,
   so the UI's status/percent updates live and the finished report appears under
   the user's history.

Watch it work:

```bash
docker compose logs -f worker-py
# → "claimed run …", "validating 1/N …", "completed"
```

`WORKER_CONCURRENCY` (default 3) sets how many files run at once. If the worker
container restarts mid-batch, an in-progress run is automatically requeued after
`SERVER_RUN_STALE_SECONDS` (default 900s) and resumes; finished files are not
redone.

## 7. Day-to-day operations

```bash
cd /opt/pm-portal

docker compose ps                      # status of all services
docker compose logs -f                 # follow all logs
docker compose logs -f backend         # follow one service
docker compose logs --tail 200 backend # last 200 lines

docker compose stop                    # stop (keeps containers + data)
docker compose start                   # start again
docker compose restart backend         # restart one service
docker compose down                    # remove containers (volumes/data KEPT)
docker compose up -d                   # recreate and start
```

`docker compose down` never deletes the named volumes — your databases,
uploaded PDFs and photos survive. Only `docker compose down -v` would delete
them; **never run that** unless you intend to wipe all data.

## 8. Updating the application

On the connected machine:

```bash
docker compose build
docker save -o pm-portal-images.tar pm-portal-backend:latest pm-portal-frontend:latest pm-portal-worker-py:latest
```

On the server:

```bash
docker load -i pm-portal-images.tar
cd /opt/pm-portal
docker compose up -d        # recreates only containers whose image changed
```

Data is untouched because it lives in volumes, not in the containers.

## 9. Backup and restore

The persistent data lives in four named volumes. Back them up with a
throwaway container that tars the volume contents:

```bash
mkdir -p /opt/backups
for v in backend-data backend-logs backend-storage minio-data; do
  docker run --rm \
    -v pm-portal_${v}:/source:ro \
    -v /opt/backups:/backup \
    alpine tar czf /backup/${v}-$(date +%F).tar.gz -C /source .
done
```

(Volume names are prefixed with the compose project name `pm-portal`.
Confirm with `docker volume ls`.)

Restore (with the stack stopped: `docker compose down`):

```bash
docker run --rm \
  -v pm-portal_backend-data:/target \
  -v /opt/backups:/backup \
  alpine sh -c "rm -rf /target/* && tar xzf /backup/backend-data-2026-06-10.tar.gz -C /target"
# repeat per volume, then:
docker compose up -d
```

## 10. Troubleshooting

| Symptom | Check / fix |
|---|---|
| `docker compose ps` shows backend unhealthy | `docker compose logs backend`. Most common: vLLM unreachable (test `curl http://<PRODUCTION_SERVER>:8000/health` from the server) or MinIO credentials in `.env` changed after MinIO already initialized its volume. |
| "LLM Offline" pill in the UI | vLLM is down or `LLM_SERVER_URL` is wrong. The backend probes `http://<llm-host>/health` every 30 s. |
| MinIO loops with "invalid credentials" | The MinIO volume was initialized with old credentials. Either restore the old `MINIO_ACCESS_KEY/SECRET_KEY`, or wipe MinIO data: `docker compose down && docker volume rm pm-portal_minio-data && docker compose up -d` (deletes all photos). |
| Uploads fail with 413 | File exceeds 50 MB (backend limit) / 100 MB (nginx limit). |
| Port 80 already in use | Set `FRONTEND_PORT=8080` in `.env`, then `docker compose up -d`; access via `http://<PRODUCTION_SERVER>:8080` and update `ALLOWED_ORIGIN` accordingly. |
| Containers don't come back after reboot | `sudo systemctl enable --now docker`. The `unless-stopped` policy then restarts them. |
| Need a shell inside a container | `docker compose exec backend sh` |
| Files never finish processing | `docker compose logs -f worker-py`. Check it reached the backend (`WORKER_BACKEND_URL=http://backend:9700`) and that `LLM_SERVER_URL` is correct. A run stuck "running" with a dead worker is auto-requeued after `SERVER_RUN_STALE_SECONDS` (default 900s). |
| Validation items error with `400` from the LLM | Too many full-size photos in one request. Keep `LLM_IMAGE_MAX_W=1000` (default) or lower it; do not set `0` unless vLLM has plenty of GPU headroom. |
| Images fail to build offline | They must be built on the **connected** machine (`docker compose build`) and shipped in the tar; base images cannot be pulled on the air-gapped server. |
| Photos don't load in reports | Photos exist only for PDFs processed via `/extract`. Verify objects: open MinIO console `http://<PRODUCTION_SERVER>:9001` (login = MinIO credentials from `.env`), bucket `pm-photos`. |

### vLLM connectivity note

The backend reaches vLLM at `http://<PRODUCTION_SERVER>:8000` — the server's own
LAN IP — which works from inside containers because Docker's bridge network
routes to the host. If vLLM ever listens only on `127.0.0.1`, reconfigure it
to listen on `0.0.0.0` (or the LAN IP), otherwise containers cannot reach it.
