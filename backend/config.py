import os

# External vLLM service (already running on the host server).
# Override via .env — never hardcode elsewhere in the codebase.
LLM_SERVER_URL   = os.getenv("LLM_SERVER_URL",  "http://localhost:8000/v1/chat/completions")
MODEL_NAME       = os.getenv("LLM_MODEL_NAME",  "./")
LLM_TIMEOUT      = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))

# MinIO runs as a container on the internal Docker network ("minio" service).
MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",  "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET     = os.getenv("MINIO_BUCKET",    "pm-photos")
MINIO_SECURE     = os.getenv("MINIO_SECURE",    "false").lower() == "true"

BACKEND_HOST     = os.getenv("BACKEND_HOST",    "0.0.0.0")
BACKEND_PORT     = int(os.getenv("BACKEND_PORT", "9700"))

# Persistent paths — each maps to a Docker volume in docker-compose.yml.
DATA_DIR         = os.getenv("DATA_DIR",        "data")
LOG_DIR          = os.getenv("LOG_DIR",         "logs")
STORAGE_DIR      = os.getenv("STORAGE_DIR",     "storage")
DB_PATH          = os.getenv("DB_PATH",         os.path.join(DATA_DIR, "pm_validator.db"))
AUDIT_DB_PATH    = os.getenv("AUDIT_DB_PATH",   os.path.join(DATA_DIR, "audit.db"))

PDF_DIR          = os.getenv("PDF_DIR",         "./PM Reports")
PROMPT_PATH      = os.getenv("PROMPT_PATH",     "prompt.txt")
