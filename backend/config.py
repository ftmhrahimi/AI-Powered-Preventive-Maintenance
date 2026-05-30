import os

LLM_SERVER_URL   = os.getenv("LLM_SERVER_URL",  "http://10.130.154.133:8000/v1/chat/completions")
MODEL_NAME       = os.getenv("LLM_MODEL_NAME",  "./")
MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",  "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY","minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY","minioadmin")
MINIO_BUCKET     = os.getenv("MINIO_BUCKET",    "pm-photos")
MINIO_SECURE     = os.getenv("MINIO_SECURE",    "false").lower() == "true"
BACKEND_HOST     = os.getenv("BACKEND_HOST",    "0.0.0.0")
BACKEND_PORT     = int(os.getenv("BACKEND_PORT","9700"))
PDF_DIR          = os.getenv("PDF_DIR",          "./PM Reports")
PROMPT_PATH      = os.getenv("PROMPT_PATH",      "prompt.txt")
