# PM Batch Validator

## What This System Does
Users upload batches of Irancell PM Report PDFs via the browser. The frontend parses PDFs client-side using pdf.js, extracts checklist items and checkbox states, fetches corresponding photos from MinIO, then sends them to an LLM for AI validation. Results are shown in a dashboard with confirmation rates, GPS and date metadata checks per photo, and saved to browser-local persistent storage.

## Architecture
```
Browser → (port 80) → nginx → index.html
Browser JS → (POST /api/llm) → nginx → backend:9700/api/llm → LLM server
Browser JS → (POST /extract) → nginx → backend:9700/extract → extractor.py
Browser JS → (GET photos) → MinIO:9000
extractor.py → MinIO:9000 (upload)
extractor.py → LLM server (image metadata extraction)
```

## Services & Ports
| Service | Container name | Host port | Container port | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| frontend | frontend | 80 | 80 | nginx serving the SPA + reverse proxy |
| backend | backend | 9700 | 9700 | Flask/Gunicorn API (PDF extraction + LLM proxy) |
| MinIO | (external) | 9000 | 9000 | Object storage for photos and JSON metadata |
| LLM server | (external) | 8000 | 8000 | Inference server (OpenAI-compatible API) |

## Configuration Reference
| Key | Default in .env.example | Description |
| :--- | :--- | :--- |
| BACKEND_HOST | 0.0.0.0 | Host for the backend server |
| BACKEND_PORT | 9700 | Port for the backend server |
| LLM_SERVER_URL | http://localhost:8000/v1/chat/completions | URL of the external LLM server |
| LLM_MODEL_NAME | ./ | Name of the LLM model to use |
| MINIO_ENDPOINT | localhost:9000 | Endpoint for MinIO storage |
| MINIO_ACCESS_KEY | minioadmin | Access key for MinIO |
| MINIO_SECRET_KEY | minioadmin | Secret key for MinIO |
| MINIO_BUCKET | pm-photos | MinIO bucket name |
| MINIO_SECURE | false | Use secure connection for MinIO |
| FRONTEND_LLM_URL | http://localhost:9700/api/llm | LLM API URL for frontend |
| FRONTEND_EXTRACT_API | http://localhost:9700/extract | Extract API URL for frontend |
| FRONTEND_MINIO_BASE | http://localhost:9000/pm-photos | MinIO base URL for frontend |
| FRONTEND_EXTRACT_PHOTOS | false | Whether to extract photos from PDF |
| FRONTEND_LLM_MODEL | ./ | LLM model name for frontend |
| PHOTO_MAX_INDEX | 50 | Max photos per checklist item |
| GPS_RADIUS_METERS | 300 | GPS tolerance radius in meters |
| DATE_TOLERANCE_DAYS | 3 | Date tolerance in days |

## Deployment Scenarios

### 1. Connecting to Existing External Services (MinIO / LLM)
If MinIO and the LLM server are already running on your network (e.g., on a central server at `10.224.235.31`):

1.  **Update `.env`**:
    - Set `MINIO_ENDPOINT=10.224.235.31:9000`
    - Set `LLM_SERVER_URL=http://10.224.235.31:8000/v1/chat/completions`
    - Set all `FRONTEND_*` URLs to use the server's IP address so the browser can reach them.
2.  **Run**: `docker compose up -d`

### 2. Running with Local Services (Development)
If you want to run everything on your local machine, including MinIO:

1.  **Update `.env`**:
    - Use `localhost` for all endpoints.
    - Set `FRONTEND_MINIO_BASE=http://localhost:9000/pm-photos`
2.  **Update `docker-compose.yml`**:
    Add the MinIO service to the `services` section:
    ```yaml
    minio:
      image: minio/minio
      ports:
        - "9000:9000"
        - "9001:9001"
      environment:
        MINIO_ROOT_USER: minioadmin
        MINIO_ROOT_PASSWORD: minioadmin
      command: server /data --console-address ":9001"
    ```

### 3. Updating Configuration (Using existing images)
The system is designed so that you can change settings without rebuilding the Docker images.

- **How it works**: The `backend` reads `.env` variables at runtime. The `frontend` injects environment variables into `config.js` every time the container starts.
- **To change a setting**:
    1. Edit the `.env` file.
    2. Restart the containers: `docker compose up -d`
    - *Note: `docker compose up` automatically detects changes in `.env` and restarts affected services with the new configuration.*

## Quick Start
1. Copy `.env.example` to `.env` and fill in your server addresses.
2. Place `pdf.min.js` and `pdf.worker.min.js` into `frontend/js/`.
3. Run: `docker compose up --build`
4. Open `http://localhost` in a browser.
5. Register an account, select a folder of PM Report PDFs, click "Run All".

## Running Without Docker (Development)
### Backend:
```bash
cd backend
pip install -r requirements.txt
cp ../.env .env        # or export env vars manually
python server.py       # starts on port 9700
```

### Frontend:
Serve the `frontend/` directory with any static file server, e.g.:
```bash
python -m http.server 8080 --directory frontend/
```
Then open `http://localhost:8080`.
Note: set `FRONTEND_LLM_URL` etc. directly in `frontend/config.js` for dev.

## Data Flow Detail
1. Browser reads PDF bytes, extracts text + renders checkbox strip images.
2. LLM detects OK/NOT_OK state for each checkbox image via `/api/llm`.
3. LLM cleans and deduplicates item descriptions via `/api/llm`.
4. If `EXTRACT_PHOTOS=true`, PDF is posted to `/extract` → backend extracts images and uploads to MinIO under `photos/{taskId}/{itemNum}/{index}.jpg` and parallel JSON metadata files.
5. If `EXTRACT_PHOTOS=false` (default), photos are read directly from MinIO.
6. Browser fetches each photo from MinIO as base64.
7. Each item's photos + description are sent to LLM for validation verdict.
8. GPS and date metadata is read from the JSON sidecar files in MinIO.
9. Results are rendered in the modal; user can save to persistent storage.

## MinIO Bucket Layout
```
pm-photos/
└── photos/
    └── {taskId}/
        └── {itemNum}/
            ├── 1.jpg
            ├── 1.json     ← {"date_time":"…","lat":"…","lng":"…","taskID":"…"}
            ├── 2.jpg
            └── 2.json
```

## Tuning
- **PHOTO_MAX_INDEX**: max photos per checklist item (default 50)
- **GPS_RADIUS_METERS**: max acceptable distance from registered site GPS (default 300m)
- **DATE_TOLERANCE_DAYS**: max days difference between photo date and report date (default 3)

## Known Limitations / Notes
- User accounts and saved reports are stored in browser `localStorage` / `window.storage` — they are per-browser and not shared between users or machines.
- MinIO and the LLM inference server are external dependencies; this repo does not include them in `docker-compose.yml`.
- The frontend requires `pdf.js` (`pdf.min.js` + `pdf.worker.min.js`) in `frontend/js/`. These are not included in the repo due to licensing; download from [https://mozilla.github.io/pdf.js/](https://mozilla.github.io/pdf.js/).
