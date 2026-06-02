from flask import Flask, request, jsonify, send_file
import tempfile
import os
import shutil
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
from config import LLM_SERVER_URL as CONFIG_LLM_URL, BACKEND_HOST, BACKEND_PORT
from db import (init_db, register_user, login_user, save_report, get_user_reports,
                get_all_reports, delete_report, is_admin_user,
                save_user_file, get_user_files, delete_user_file, delete_all_user_files)
# PDF storage directory
PDF_STORAGE_DIR = os.path.join(os.path.dirname(__file__), 'storage', 'pdfs')
os.makedirs(PDF_STORAGE_DIR, exist_ok=True)

LLM_SERVER_URL = os.environ.get("LLM_SERVER_URL", CONFIG_LLM_URL)
LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY = 2.0
LLM_TIMEOUT_SECONDS = 120

LLM_HEALTH = {"available": True, "last_failure": None, "last_success": None}
LLM_HEALTH_LOCK = threading.Lock()

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

def call_llm_with_retry(payload):
    last_error = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                LLM_SERVER_URL,
                json=payload,
                timeout=LLM_TIMEOUT_SECONDS
            )
            resp.raise_for_status()
            with LLM_HEALTH_LOCK:
                LLM_HEALTH["available"] = True
                LLM_HEALTH["last_success"] = datetime.now(timezone.utc).isoformat()
            return resp.json()
        except requests.exceptions.Timeout:
            last_error = f"Timeout on attempt {attempt}"
            logger.warning(f"LLM timeout (attempt {attempt}/{LLM_MAX_RETRIES})")
        except requests.exceptions.ConnectionError:
            last_error = f"Connection error on attempt {attempt}"
            logger.warning(f"LLM connection error (attempt {attempt}/{LLM_MAX_RETRIES})")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"LLM error (attempt {attempt}/{LLM_MAX_RETRIES}): {e}")

        if attempt < LLM_MAX_RETRIES:
            time.sleep(LLM_RETRY_DELAY)

    with LLM_HEALTH_LOCK:
        LLM_HEALTH["available"] = False
        LLM_HEALTH["last_failure"] = datetime.now(timezone.utc).isoformat()

    logger.error(f"LLM failed after {LLM_MAX_RETRIES} attempts: {last_error}")
    log_event("LLM_FAILURE", detail=last_error, status="failed")
    raise RuntimeError(f"LLM unavailable after {LLM_MAX_RETRIES} attempts: {last_error}")

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
        job_meta = dict(JOB_REGISTRY.get(job_id, {}))
    username = job_meta.get("username")

    with JOB_REGISTRY_LOCK:
        JOB_REGISTRY[job_id]["status"] = "running"


    log_event("JOB_STARTED", username=username, job_id=job_id,
              detail=JOB_REGISTRY[job_id]["filename"], status="running")
    try:
        result = process_pdf(tmp_path)
        with JOB_REGISTRY_LOCK:
            JOB_REGISTRY[job_id]["status"] = "done"
            JOB_REGISTRY[job_id]["result"] = result
            JOB_REGISTRY[job_id]["progress_pct"] = 100
        log_event("JOB_COMPLETED", username=username, job_id=job_id,
                  task_id=result, status="success")
    except Exception as e:
        with JOB_REGISTRY_LOCK:
            JOB_REGISTRY[job_id]["status"] = "failed"
            JOB_REGISTRY[job_id]["error"] = str(e)
        log_event("JOB_FAILED", username=username, job_id=job_id,
                  detail=str(e), status="failed")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def check_llm_server_health():
    # Attempt to ping the /health endpoint of the LLM server
    # Based on user input, it returns 200 OK even if content is 0
    try:
        # Extract base URL from LLM_SERVER_URL
        from urllib.parse import urlparse
        parsed = urlparse(LLM_SERVER_URL)
        health_url = f"{parsed.scheme}://{parsed.netloc}/health"

        resp = requests.get(health_url, timeout=5)
        available = resp.status_code == 200

        with LLM_HEALTH_LOCK:
            LLM_HEALTH["available"] = available
            if available:
                LLM_HEALTH["last_success"] = datetime.now(timezone.utc).isoformat()
            else:
                LLM_HEALTH["last_failure"] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        with LLM_HEALTH_LOCK:
            LLM_HEALTH["available"] = False
            LLM_HEALTH["last_failure"] = datetime.now(timezone.utc).isoformat()

def background_maintenance():
    last_health_check = 0
    while True:
        now_ts = time.time()

        # Every 30 seconds check LLM health
        if now_ts - last_health_check > 30:
            check_llm_server_health()
            last_health_check = now_ts

        # Every 30 minutes clean up jobs
        # (This is a bit simplified, but fine for a daemon thread)
        now_dt = datetime.now(timezone.utc)
        with JOB_REGISTRY_LOCK:
            to_delete = []
            for job_id, job in JOB_REGISTRY.items():
                age = now_dt - job["submitted_at"]
                if age.total_seconds() > 7200:  # 2 hours
                    to_delete.append(job_id)
            for job_id in to_delete:
                del JOB_REGISTRY[job_id]

        time.sleep(10)

threading.Thread(target=background_maintenance, daemon=True).start()

app = Flask(__name__)
CORS(app)
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
     methods=["GET", "POST", "DELETE", "OPTIONS"])

limiter = Limiter(get_remote_address, app=app, default_limits=["200 per hour", "30 per minute"])

# @app.route('/health', methods=['GET'])
# def health():
#     return jsonify({
#         "status": "ok",
#         "llm": LLM_HEALTH
#     }), 200
# ✅ Fixed
@app.route('/health')
def health():
    with LLM_HEALTH_LOCK:
        llm_health = dict(LLM_HEALTH)  # copy under lock
    return jsonify({
        "status": "ok",
        "llm": llm_health  # frontend reads data.llm.available
    })
# @app.route('/api/llm', methods=['POST', 'OPTIONS'])
# @limiter.limit("60 per minute")
# def proxy_llm():
    # log_event("LLM_CALL", ip_address=request.remote_addr)
    # if request.method == 'OPTIONS':
    #     return '', 204  # preflight
@app.route('/api/llm', methods=['POST', 'OPTIONS'])
@limiter.limit("100 per minute")
def proxy_llm():
    if request.method == 'OPTIONS':
        return '', 204
    payload = request.get_json() or {}
    username = payload.get('username')
    job_id = payload.get('job_id')
    task_id = payload.get('task_id')
    model = payload.get('model', '?')

    try:  # <-- Indented 4 spaces
        resp = requests.post(
            LLM_SERVER_URL,
            json=payload,
            timeout=300,
            stream=True  # Stream from LLM server
        )
        log_event(
            "LLM_CALL",
            ip_address=request.remote_addr,
            username=username,
            job_id=job_id,
            task_id=task_id,
            status="success" if resp.status_code < 400 else "failed",
            detail=f"model={model}; upstream_status={resp.status_code}"
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

    except Exception as e:  # <-- Line 277: Must align EXACTLY with 'try:' (4 spaces)
        log_event(
            "LLM_CALL",
            ip_address=request.remote_addr,
            username=username,
            job_id=job_id,
            task_id=task_id,
            status="failed",
            detail=f"model={model}; error={str(e)}"
        )
        return jsonify({"error": str(e)}), 500


@app.route("/extract", methods=["POST", "OPTIONS"])
@limiter.limit("100 per minute")
def extract():
    if request.method == 'OPTIONS':
        return '', 204
    logger.info("\n========================")
    logger.info("NEW EXTRACTION REQUEST")
    logger.info("========================")
    username = request.form.get("username")
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
                    "username": username,
                    "submitted_at": datetime.now(timezone.utc),
                    "status": "pending",
                    "progress_pct": 0,
                    "progress_label": "Waiting in queue...",
                    "result": None,
                    "error": None
                }

            executor.submit(run_job, job_id, tmp.name)
            log_event("PDF_SUBMITTED", username=username, detail=pdf.filename,
                      ip_address=request.remote_addr, job_id=job_id, status="pending")

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
    admin_username = request.args.get("admin_username")
    if not is_admin_user(admin_username):
        return jsonify({"error": "Admin access required"}), 403

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
    admin_username = request.args.get("admin_username")
    if not is_admin_user(admin_username):
        return jsonify({"error": "Admin access required"}), 403
    return jsonify(get_all_reports())


# ── PDF Storage Routes ──

@app.route('/api/pdfs/upload', methods=['POST', 'OPTIONS'])
@limiter.limit("30 per minute")
def upload_pdf():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        username = request.form.get('username')
        if not username:
            return jsonify({'success': False, 'error': 'No username'}), 400

        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file'}), 400

        pdf = request.files['file']
        if not pdf.filename.lower().endswith('.pdf'):
            return jsonify({'success': False, 'error': 'Not a PDF'}), 400

        # Save to storage/pdfs/{username}/{filename}
        user_dir = os.path.join(PDF_STORAGE_DIR, username)
        os.makedirs(user_dir, exist_ok=True)

        # Sanitize filename — remove path separators
        safe_name = os.path.basename(pdf.filename)
        save_path = os.path.join(user_dir, safe_name)
        pdf.save(save_path)

        logger.info(f"PDF uploaded: {username}/{safe_name}")
        return jsonify({'success': True, 'filename': safe_name})

    except Exception as e:
        logger.error(f"PDF upload error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/pdfs/list', methods=['GET'])
@limiter.limit("60 per minute")
def list_pdfs():
    try:
        username = request.args.get('username')
        if not username:
            return jsonify([])

        user_dir = os.path.join(PDF_STORAGE_DIR, username)
        if not os.path.exists(user_dir):
            return jsonify([])

        # Return list of PDF filenames for this user
        files = [
            f for f in os.listdir(user_dir)
            if f.lower().endswith('.pdf')
        ]
        return jsonify(files)

    except Exception as e:
        logger.error(f"PDF list error: {e}")
        return jsonify([])


@app.route('/api/pdfs/download', methods=['GET'])
@limiter.limit("60 per minute")
def download_pdf():
    try:
        username = request.args.get('username')
        filename = request.args.get('filename')

        if not username or not filename:
            return jsonify({'error': 'Missing username or filename'}), 400

        # Sanitize — prevent path traversal attack
        safe_name = os.path.basename(filename)
        file_path = os.path.join(PDF_STORAGE_DIR, username, safe_name)

        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404

        return send_file(
            file_path,
            mimetype='application/pdf',
            as_attachment=False,
            download_name=safe_name
        )

    except Exception as e:
        logger.error(f"PDF download error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/pdfs/delete', methods=['DELETE', 'OPTIONS'])
@limiter.limit("30 per minute")
def delete_pdf():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        username = request.args.get('username')
        filename = request.args.get('filename')

        if not username or not filename:
            return jsonify({'success': False, 'error': 'Missing params'}), 400

        safe_name = os.path.basename(filename)
        file_path = os.path.join(PDF_STORAGE_DIR, username, safe_name)

        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"PDF deleted: {username}/{safe_name}")

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"PDF delete error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ── User Files Routes ──

@app.route('/api/userfiles', methods=['GET'])
def list_user_files():
    username = request.args.get('username')
    if not username:
        return jsonify([])
    return jsonify(get_user_files(username))


@app.route('/api/userfiles', methods=['POST'])
def save_user_files():
    data = request.get_json()
    username = data.get('username')
    files = data.get('files', [])
    if not username:
        return jsonify({'success': False, 'error': 'No username'}), 400
    for f in files:
        save_user_file(username, f)
    return jsonify({'success': True})


@app.route('/api/userfiles', methods=['DELETE'])
def remove_user_file():
    username = request.args.get('username')
    file_name = request.args.get('fileName')
    if not username:
        return jsonify({'success': False, 'error': 'No username'}), 400
    if file_name:
        delete_user_file(username, file_name)
    else:
        delete_all_user_files(username)
    return jsonify({'success': True})


if __name__ == "__main__":
    app.run(host=BACKEND_HOST, port=BACKEND_PORT, debug=False)
