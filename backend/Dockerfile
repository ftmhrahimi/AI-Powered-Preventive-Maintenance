FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9700

# PERFORMANCE FIX 5 — use gunicorn with multiple workers instead of
# Flask dev server. 4 workers handles concurrent PDF extraction jobs
# without blocking the /api/llm proxy endpoint.
CMD ["gunicorn", "--workers=4", "--timeout=360", "--bind=0.0.0.0:9700", "server:app"]
