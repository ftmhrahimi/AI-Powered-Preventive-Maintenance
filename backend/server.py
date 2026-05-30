from flask import Flask, request, jsonify
import tempfile
import os
import requests
import logging
import uuid
import threading
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from extractor import process_pdf
from config import LLM_SERVER_URL, BACKEND_HOST, BACKEND_PORT
from db import init_db, register_user, login_user, save_report, get_user_reports, get_all_reports, delete_report

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/app.log")]
)
logger = logging.getLogger(__name__)

JOB_REGISTRY = {}
JOB_REGISTRY_LOCK = threading.Lock()
MAX_WORKERS = 3
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

AUDIT_DB = "logs/audit.db"
AUDIT_LOCK = threading.Lock()

def init_audit_db():
    with sqlite3.connect(AUDIT_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                username TEXT,
                event_type TEXT NOT NULL,
                detail TEXT,
                ip_address TEXT,
                job_id TEXT,
                task_id TEXT,
                status TEXT
            )
        """)
        conn.commit()

init_audit_db()

def log_event(event_type, detail=None, username=None,
              ip_address=None, job_id=None, task_id=None, status=None):
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(
        f"[EVENT] {event_type} | user={username} | job={job_id} | "
        f"task={task_id} | status={status} | ip={ip_address} | {detail}"
    )
    with AUDIT_LOCK:
        with sqlite3.connect(AUDIT_DB) as conn:
            conn.execute(
                "INSERT INTO events (timestamp, username, event_type, detail, "
                "ip_address, job_id, task_id, status) VALUES (?,?,?,?,?,?,?,?)",
                (ts, username, event_type, detail, ip_address, job_id, task_id, status)
            )
            conn.commit()

def run_job(job_id, tmp_path):
    with JOB_REGISTRY_LOCK:
        JOB_REGISTRY[job_id]["status"] = "running"

    log_event("JOB_STARTED", job_id=job_id,
              detail=JOB_REGISTRY[job_id]["filename"])

    try:
        result = process_pdf(tmp_path)
        with JOB_REGISTRY_LOCK:
            JOB_REGISTRY[job_id]["status"] = "done"
            JOB_REGISTRY[job_id]["result"] = result
            JOB_REGISTRY[job_id]["progress_pct"] = 100
        log_event("JOB_COMPLETED", job_id=job_id,
                  task_id=result, status="success")
    except Exception as e:
        with JOB_REGISTRY_LOCK:
            JOB_REGISTRY[job_id]["status"] = "failed"
            JOB_REGISTRY[job_id]["error"] = str(e)
        log_event("JOB_FAILED", job_id=job_id,
                  detail=str(e), status="failed")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def cleanup_jobs():
    while True:
        time.sleep(1800)  # 30 minutes
        now = datetime.now(timezone.utc)
        with JOB_REGISTRY_LOCK:
            to_delete = []
            for job_id, job in JOB_REGISTRY.items():
                age = now - job["submitted_at"]
                if age.total_seconds() > 7200:  # 2 hours
                    to_delete.append(job_id)
            for job_id in to_delete:
                del JOB_REGISTRY[job_id]

threading.Thread(target=cleanup_jobs, daemon=True).start()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
init_db()

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({"success": False, "error": "File too large. Max 50MB."}), 413

@app.errorhandler(500)
def internal_server_error(error):
    return jsonify({"success": False, "error": "Internal server error."}), 500

# Allow specific origin and methods
CORS(app,
     resources={r"/*": {"origins": os.getenv("ALLOWED_ORIGIN", "*")}},
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "OPTIONS"])

limiter = Limiter(get_remote_address, app=app, default_limits=["200 per hour", "30 per minute"])

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

@app.route('/api/llm', methods=['POST', 'OPTIONS'])
@limiter.limit("60 per minute")
def proxy_llm():
    log_event("LLM_CALL", ip_address=request.remote_addr)
    if request.method == 'OPTIONS':
        return '', 204  # preflight
    try:
        payload = request.get_json()
        resp = requests.post(
            LLM_SERVER_URL,
            json=payload,
            timeout=300,
            stream=True  # Stream from LLM server
        )

        # Stream the response back chunk by chunk
        def generate():
            for chunk in resp.iter_content(chunk_size=4096):
                if chunk:
                    yield chunk

        return app.response_class(
            generate(),
            status=resp.status_code,
            headers={'Content-Type': resp.headers.get('Content-Type', 'application/json')}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/extract", methods=["POST", "OPTIONS"])
@limiter.limit("10 per minute")
def extract():
    if request.method == 'OPTIONS':
        return '', 204
    logger.info("\n========================")
    logger.info("NEW EXTRACTION REQUEST")
    logger.info("========================")
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400
    pdf = request.files["file"]
    logger.info("Uploaded file: %s", pdf.filename)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            pdf.save(tmp.name)
            logger.info("Saved temp PDF: %s", tmp.name)

            job_id = str(uuid.uuid4())
            with JOB_REGISTRY_LOCK:
                JOB_REGISTRY[job_id] = {
                    "job_id": job_id,
                    "filename": pdf.filename,
                    "submitted_at": datetime.now(timezone.utc),
                    "status": "pending",
                    "progress_pct": 0,
                    "progress_label": "Waiting in queue...",
                    "result": None,
                    "error": None
                }

            executor.submit(run_job, job_id, tmp.name)
            log_event("PDF_SUBMITTED", detail=pdf.filename,
                      ip_address=request.remote_addr, job_id=job_id)

            return jsonify({"success": True, "job_id": job_id})
    except Exception as e:
        logger.error("EXTRACTION ERROR: %s", str(e))
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/job/<job_id>", methods=["GET"])
def job_status(job_id):
    with JOB_REGISTRY_LOCK:
        job = JOB_REGISTRY.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)

@app.route("/audit", methods=["GET"])
@limiter.limit("60 per minute")
def audit_log():
    username  = request.args.get("username")
    event_type = request.args.get("event_type")
    job_id    = request.args.get("job_id")
    task_id   = request.args.get("task_id")
    from_date = request.args.get("from_date")
    to_date   = request.args.get("to_date")

    query  = "SELECT * FROM events WHERE 1=1"
    params = []
    if username:   query += " AND username=?";   params.append(username)
    if event_type: query += " AND event_type=?"; params.append(event_type)
    if job_id:     query += " AND job_id=?";     params.append(job_id)
    if task_id:    query += " AND task_id=?";    params.append(task_id)
    if from_date:  query += " AND timestamp>=?"; params.append(from_date)
    if to_date:    query += " AND timestamp<=?"; params.append(to_date)
    query += " ORDER BY timestamp DESC LIMIT 200"

    with sqlite3.connect(AUDIT_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


# ── Auth Routes ──
@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    data = request.get_json()
    if register_user(data.get('username'), data.get('name'), data.get('password')):
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Username already taken"}), 400


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json()
    user = login_user(data.get('username'), data.get('password'))
    if user:
        return jsonify({"success": True, "user": {"username": user['username'], "name": user['name'], "isAdmin": bool(user['is_admin'])}})
    return jsonify({"success": False, "error": "Invalid credentials"}), 401


# ── Report Routes ──
@app.route('/api/reports', methods=['GET'])
def list_reports():
    username = request.args.get('username')
    if not username:
        return jsonify([])
    return jsonify(get_user_reports(username))


@app.route('/api/reports', methods=['POST'])
def save_rep():
    data = request.get_json()
    username = data.get('username')
    report = data.get('report')
    if save_report(username, report):
        return jsonify({"success": True})
    return jsonify({"success": False}), 500


@app.route('/api/reports', methods=['DELETE'])
def remove_report():
    username = request.args.get('username')
    taskId = request.args.get('taskId')
    delete_report(username, taskId)
    return jsonify({"success": True})


@app.route('/api/admin/reports', methods=['GET'])
def admin_list_reports():
    # In a real app, verify admin status here
    return jsonify(get_all_reports())


if __name__ == "__main__":
    app.run(host=BACKEND_HOST, port=BACKEND_PORT, debug=False)
