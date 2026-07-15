# Chromium-free Python engine worker. No browser → small image, low RAM.
FROM python:3.11-slim

WORKDIR /app

# PyMuPDF / Pillow wheels are self-contained; no system libs needed on slim.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY engine/ ./engine/
COPY worker.py ./

CMD ["python", "-u", "worker.py"]
