FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user; pre-create the persistent dirs so named volumes
# inherit the correct ownership on first use.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data /app/logs /app/storage/pdfs \
    && chown -R appuser:appuser /app
USER appuser

ENV DATA_DIR=/app/data \
    LOG_DIR=/app/logs \
    STORAGE_DIR=/app/storage

EXPOSE 9700

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.getenv('BACKEND_PORT','9700')+'/health', timeout=4)" || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "server:app"]
