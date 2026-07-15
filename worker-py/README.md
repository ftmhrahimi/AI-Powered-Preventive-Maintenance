# Python Engine (`worker-py`)

The processing engine for PM Portal — pure Python, **no browser**. It replaced
the old headless‑Chromium worker and is now the **default and only** engine
(`docker-compose.yml` service `worker-py`). It polls the server‑run queue and,
for each file, produces the same reports the browser pipeline used to.

## What it does (per file)
1. **Photo extraction** — delegated to the backend `/extract` (PyMuPDF →
   photos + per‑image date/GPS metadata via the LLM → MinIO).
2. **Item extraction** — `engine/pdf_items.py`, **deterministic, no LLM**:
   reads the PDF text layer, is RTL/LTR aware (bidi reorder for Persian, correct
   reading order for English), strips report headers and page watermarks, merges
   the ~3 repeated copies of each item, and splits a box that accidentally holds
   two items (missed checkbox anchor). No LLM here means no transcription drift.
3. **Checkbox detection** — `engine/render.py` rasterises each row's OK/Not‑OK
   strip and the LLM reads the ticked box.
4. **Validation** — `engine/validate.py`: fetch photos + metadata, run date
   (`DATE_TOLERANCE_DAYS`) and GPS (`GPS_RADIUS_METERS`, haversine) checks, then
   the LLM returns a verdict per item with the matching task rule. Date/GPS
   failures force `DISPUTED`. Photos are downscaled to `LLM_IMAGE_MAX_W` for the
   LLM call (browser parity; avoids vLLM 400s on multi‑photo items).
5. **Aggregate** — Acceptance % = confirmed ÷ total; progress and results are
   written back to the backend so the UI updates live.

LLM is used for three things only: photo metadata (backend), checkbox detection,
and per‑item validation. Item text is **not** sent to the LLM.

## Module map
- `worker.py` — queue loop: `/worker/claim` → process → `/worker/complete`, with
  heartbeat and throttled `/worker/run-status` cancellation. `WORKER_CONCURRENCY`
  threads (default 3).
- `engine/pdf_items.py` — deterministic checklist‑item extraction (PyMuPDF).
- `engine/render.py` — checkbox‑strip renderer (matches the old pdf.js crop).
- `engine/llm.py` — vLLM client: `detect_checkbox`, `validate_item`.
- `engine/prompts.py` — checkbox + validation prompts.
- `engine/geo.py` — haversine, date/GPS checks.
- `engine/validate.py` — per‑item orchestration + system‑cause overrides.
- `engine/pipeline.py` — `process_file` end‑to‑end.

## Configuration (from `.env`)
- `LLM_SERVER_URL`, `LLM_MODEL_NAME`, `LLM_TIMEOUT_SECONDS`
- `LLM_IMAGE_MAX_W` (default 1000; `0` = full‑size validation images)
- `WORKER_CONCURRENCY`, `WORKER_POLL_SECONDS`, `WORKER_TOKEN`
- `CHECKBOX_DETECT` (default true)
- `GPS_RADIUS_METERS`, `DATE_TOLERANCE_DAYS`, `PHOTO_MAX_INDEX`

Over the Docker network the container reaches the backend at
`http://backend:9700`, MinIO at `http://minio:9000/<bucket>`, and the LLM at
`LLM_SERVER_URL`. The image is a small `python:3.11-slim` + PyMuPDF/Pillow.

## Run / logs
```bash
docker compose up -d --build worker-py
docker compose logs -f worker-py
```

## Local extraction check (no vLLM needed)
The deterministic item extractor can be run on a PDF directly:
```bash
pip install -r requirements.txt
python -m engine.pdf_items /path/to/report.pdf   # prints is_english + items
```
