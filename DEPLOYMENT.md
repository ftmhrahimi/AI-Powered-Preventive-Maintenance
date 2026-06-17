# PM Portal — Offline Server Deployment Guide

Target server: **10.130.154.133** (offline / air-gapped Linux server with Docker, Docker Compose, and a running vLLM service on port 8000. Nothing else is installed.)

The stack consists of four containers plus the existing vLLM service:

| Service  | Container   | Purpose                                            | Host port |
|----------|-------------|----------------------------------------------------|-----------|
| frontend | pm-frontend | nginx — serves the UI and proxies all API traffic  | 80        |
| backend  | pm-backend  | Flask/gunicorn — extraction, auth, reports, LLM proxy | 9700   |
| worker   | pm-worker   | Headless-browser worker — runs "Run on Server" jobs (continues after the user leaves) | — (internal only) |
| minio    | pm-minio    | Object storage for extracted photos/metadata       | 9001 (console only) |
| vLLM     | *(existing)*| LLM inference — **not** managed by this compose    | 8000      |

All traffic between containers uses the internal Docker network `pm-net`.
The browser only needs `http://10.130.154.133` (port 80); nginx proxies
`/api`, `/extract`, `/job`, `/health`, `/audit`, `/stop-all` to the backend
and `/pm-photos` to MinIO.

---

## 1. Build the images on a machine WITH internet access

The offline server cannot pull base images (`python:3.11-slim`, `nginx:alpine`,
`minio/minio`), so build and export everything on a connected machine first
(any Linux/Mac/WSL machine with Docker).

```bash
# On the connected machine, in the project root:
docker compose build                 # builds backend, frontend AND worker
docker pull minio/minio:latest       # MinIO is used as-is, just pull it
```

> **Note on the worker image.** The `worker` service is built from the official
> Playwright image (`mcr.microsoft.com/playwright/python`), which bundles
> Chromium and is **large (~2 GB)**. `docker compose build` pulls that base
> image automatically on the connected machine, so the offline server never
> needs internet — but expect the exported tar to grow by ~1.5–2 GB.

The frontend build is a multi-stage Docker build: a temporary `node:20-alpine`
stage minifies and strips `index.html` (production build), then the result is
copied into the final nginx image. This needs internet only on the connected
build machine — nothing extra is shipped to the offline server.

```bash
# Export all three images into a single archive:
docker save -o pm-portal-images.tar \
  pm-portal-backend:latest \
  pm-portal-frontend:latest \
  pm-portal-worker:latest \
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
scp pm-portal-images.tar <user>@10.130.154.133:/opt/
scp -r PM_portal <user>@10.130.154.133:/opt/pm-portal
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
docker images          # verify: pm-portal-backend, pm-portal-frontend, minio/minio
```

`docker load` imports the images into the local Docker engine — no internet needed.

## 4. Configure

Edit `/opt/pm-portal/.env` and check:

- `LLM_SERVER_URL=http://10.130.154.133:8000/v1/chat/completions` — must match
  your vLLM endpoint (adjust the path if your vLLM serves a different route).
- `LLM_MODEL_NAME` / `FRONTEND_LLM_MODEL` — must match the model name vLLM
  was started with (check with `curl http://10.130.154.133:8000/v1/models`).
- `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` — **change these**; they are both the
  MinIO root credentials and the backend's access credentials.
- `ADMIN_PASSWORD` — initial admin login for the portal; change it.
- `ALLOWED_ORIGIN=http://10.130.154.133` — the URL users open in the browser.
- `WORKER_TOKEN` *(optional)* — shared secret for the headless worker's internal
  endpoints. The worker endpoints (`/worker/*`) are already unreachable from
  outside (nginx does not proxy them), so this is defence-in-depth. If you set
  it, the same value is read by both `backend` and `worker` from `.env`.

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
curl http://10.130.154.133:9700/health
# → {"status":"ok","llm":{"available":true,...}}

# Frontend through nginx:
curl -I http://10.130.154.133/            # → HTTP 200
curl http://10.130.154.133/health         # proxied backend health

# MinIO:
docker compose exec minio mc ready local  # → "The cluster is ready"
```

Then open `http://10.130.154.133` in a browser and log in with the admin
account from `.env`.

## 6a. "Run on Server" — processing that survives the browser closing

Normally the audit pipeline runs **inside the user's browser tab**: closing the
tab or shutting down the computer freezes every job at its current step. The
**☁ Run on Server** button (next to **▶ Run All**) hands the user's pending
files to the always-on server instead.

How it works:

1. The user uploads/queues their PDFs as usual (already stored on the backend)
   and clicks **☁ Run on Server**. The browser records a request via
   `POST /api/server-run` and can then be closed safely.
2. The `worker` container claims the request and opens the **exact same
   frontend page** in a headless Chromium, logged in as that user. It restores
   the pending files and runs the identical pipeline — so results are identical
   to running locally.
3. Each step is persisted to the backend as it completes (the frontend already
   saves job state via `/api/userfiles`). When the user logs back in, their
   files show as completed.

Watch it work:

```bash
docker compose logs -f worker
# → "claimed server-run …", "starting runAll()", "completed"
```

Only one `worker` replica should run (it processes one user's batch at a time,
then picks up the next). If the worker container restarts mid-batch, any
in-progress run is automatically requeued and resumes; already-finished files
are not redone.

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
docker save -o pm-portal-images.tar pm-portal-backend:latest pm-portal-frontend:latest pm-portal-worker:latest
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
| `docker compose ps` shows backend unhealthy | `docker compose logs backend`. Most common: vLLM unreachable (test `curl http://10.130.154.133:8000/health` from the server) or MinIO credentials in `.env` changed after MinIO already initialized its volume. |
| "LLM Offline" pill in the UI | vLLM is down or `LLM_SERVER_URL` is wrong. The backend probes `http://<llm-host>/health` every 30 s. |
| MinIO loops with "invalid credentials" | The MinIO volume was initialized with old credentials. Either restore the old `MINIO_ACCESS_KEY/SECRET_KEY`, or wipe MinIO data: `docker compose down && docker volume rm pm-portal_minio-data && docker compose up -d` (deletes all photos). |
| Uploads fail with 413 | File exceeds 50 MB (backend limit) / 100 MB (nginx limit). |
| Port 80 already in use | Set `FRONTEND_PORT=8080` in `.env`, then `docker compose up -d`; access via `http://10.130.154.133:8080` and update `ALLOWED_ORIGIN` accordingly. |
| Containers don't come back after reboot | `sudo systemctl enable --now docker`. The `unless-stopped` policy then restarts them. |
| Need a shell inside a container | `docker compose exec backend sh` |
| "Run on Server" never finishes the files | `docker compose logs -f worker`. Check the worker reached the frontend (`WORKER_FRONTEND_URL=http://frontend`) and the backend (`WORKER_BACKEND_URL=http://backend:9700`). A run stuck "running" with a dead worker is auto-requeued after `SERVER_RUN_STALE_SECONDS` (default 900s). |
| Worker image fails to build offline | It must be built on the **connected** machine (`docker compose build`) and shipped in the tar; the Playwright base image cannot be pulled on the air-gapped server. |
| Photos don't load in reports | Photos exist only for PDFs processed via `/extract`. Verify objects: open MinIO console `http://10.130.154.133:9001` (login = MinIO credentials from `.env`), bucket `pm-photos`. |

### vLLM connectivity note

The backend reaches vLLM at `http://10.130.154.133:8000` — the server's own
LAN IP — which works from inside containers because Docker's bridge network
routes to the host. If vLLM ever listens only on `127.0.0.1`, reconfigure it
to listen on `0.0.0.0` (or the LAN IP), otherwise containers cannot reach it.
