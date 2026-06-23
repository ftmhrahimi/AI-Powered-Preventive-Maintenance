# Python Engine (Chromium‑free worker) — Work In Progress

Goal: replace the headless‑Chromium worker (Option **C**) with a pure‑Python
engine that produces the **same results** as the browser pipeline, eliminating
the per‑browser RAM cost.

Status: **scaffold + parity proof for the deterministic stage.** Not yet wired
into `docker-compose.yml`. The old Playwright worker stays as the default; this
runs behind a rollout flag until parity is verified.

---

## Key finding from the parity work (read this first)
The browser's "item extraction" is **not** fully deterministic. The flow is:

1. `extractTasksFromPdf` (pdf.js) → **raw, messy** tasks: each description is
   repeated ~3× (3 table rows per item) and header text can bleed in.
2. `extractItemsWithBatching` → **LLM pass #1** (`callLLMExtract`) cleans/dedups
   each batch of items into proper descriptions.
3. `cleanConsecutiveTasks` → **LLM pass #2** removes text that bled between
   neighbouring items (Persian only).

So the clean descriptions you see in reports come from **two LLM passes**, not
from parsing alone. The Python port must replicate those passes (same prompts)
to stay byte‑for‑byte compatible. This is fine — it's no Chromium — but it means
the engine makes these LLM calls per file:

| Stage | LLM call | Source prompt |
|------|----------|----------------|
| Photo + metadata extraction | yes (per image) | `backend/extractor.py` + `prompt.txt` |
| Checkbox OK/Not‑OK detection | yes (per row) | `detectCheckboxFromStrip` |
| Item description clean/dedup | yes (per batch of 5) | `callLLMExtract` |
| Neighbour bleed‑fix (Persian) | yes (only on detected bleed) | `cleanConsecutiveTasks` |
| Per‑item validation | yes (per item) | `buildValidationPrompt` |

All prompts are ported verbatim into `engine/prompts.py`.

## What is already proven
- **PyMuPDF == pdf.js for coordinates/text.** On the real `E2782` PDF, PyMuPDF
  span origins (converted to bottom‑left Y) match the pdf.js `getTextContent`
  dump within ~1px, with identical text fragments. (See `parity_harness.py`.)
- **NFKC works in Python** exactly like the frontend `fixPersian` (e.g.
  `ﺳیﺴﺘﻢ` → `سیستم`), so Persian comes out correct.
- The raw extractor (`engine/pdf_items.py`) reproduces the messy raw text the
  browser feeds to LLM pass #1 — the right input for parity.

## Architecture (target)
```
server_runs queue (unchanged)  ──►  worker-py (this)  ──►  writes user_files (unchanged)
                                       │
                                       ├─ extractor.process_pdf      (photos+meta → MinIO)   [reused]
                                       ├─ engine.pdf_items           (raw items, PyMuPDF)
                                       ├─ engine.llm.clean_items     (LLM pass #1 + #2)
                                       ├─ engine.llm.detect_checkbox (per row)
                                       └─ engine.validate.validate_item (date/GPS/rule + LLM)
```
The DB contracts (`server_runs`, `user_files`) are the seam: the frontend UI and
queue are untouched; only the engine implementation changes.

## Module map
- `engine/pdf_items.py` — PyMuPDF raw item extraction (deterministic). **Done.**
- `engine/geo.py` — haversine + date/GPS checks. **Done.**
- `engine/prompts.py` — all LLM prompts, ported verbatim. **Done.**
- `engine/llm.py` — vLLM client + clean/checkbox/validate calls. *Functional,
  needs the vLLM endpoint to verify.*
- `engine/render.py` — render a page row to a checkbox‑strip image (PyMuPDF
  pixmap + crop). *Needs calibration vs the pdf.js crop offsets.*
- `engine/validate.py` — per‑item orchestration (photos+meta → checks → verdict).
- `engine/pipeline.py` — `process_file` end‑to‑end (writes progress to user_files).
- `worker.py` — claim/heartbeat/complete loop (no browser). *Skeleton.*
- `parity_harness.py` — compare Python vs browser output on real PDFs.

## How to run the parity harness (deterministic stage)
```bash
pip install -r requirements.txt
python parity_harness.py /path/to/E2782.pdf      # prints raw items + normalized
```
For the LLM stages, point `LLM_SERVER_URL` at the vLLM endpoint and run the full
pipeline against a known report, then diff the resulting Acceptance % and
per‑item verdicts against a browser run of the same file.

## Remaining work / risks
1. **Checkbox strip cropping** — translate pdf.js crop (cropX=170, cropW=160,
   PADDING=30 at scale 2) to PyMuPDF DPI/clip. Needs visual calibration.
2. **Coordinate origin** — pdf.js is bottom‑left (y up); PyMuPDF is top‑left
   (y down). `pdf_items.py` converts via `H - origin_y`; keep this consistent in
   `render.py`.
3. **Parity validation** — golden‑set comparison on several PDFs (Persian +
   multi‑page) before switching the default worker.
4. **Concurrency** — the engine is I/O‑bound (LLM waits); use a thread/process
   pool. Memory is a fraction of Chromium.

## Rollout
- Keep `worker` (Playwright) as default.
- Add `worker-py` as a second service; route runs to it via an env flag
  (e.g. `ENGINE=python`). Run both in parallel on a subset, compare, then flip
  the default and retire the browser worker.
