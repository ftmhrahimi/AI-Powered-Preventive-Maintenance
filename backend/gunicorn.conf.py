import os

bind = f"0.0.0.0:{os.getenv('BACKEND_PORT', '9700')}"

# IMPORTANT: the app stores job state (JOB_REGISTRY, stop flags, LLM health,
# rate limits) in process memory, so it must run as a SINGLE process.
# Concurrency comes from threads instead of worker processes.
workers = 1
worker_class = "gthread"
threads = int(os.getenv("GUNICORN_THREADS", "16"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "300"))

# Log to stdout/stderr so `docker compose logs` captures everything.
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
