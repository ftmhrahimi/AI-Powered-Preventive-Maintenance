# Headless-browser worker that drives the exact frontend pipeline server-side.
# The official Playwright image already ships Chromium + all its system deps.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# Extra fonts so canvas rendering of Persian/Arabic PDF text is faithful.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto fonts-noto-core fonts-noto-extra \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker.py .

CMD ["python", "worker.py"]
