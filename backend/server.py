from flask import Flask, request, jsonify
import tempfile
import os
import requests
import logging
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
            task_dir = process_pdf(tmp.name)
            logger.info("Extraction complete, task dir: %s", task_dir)
        return jsonify({"success": True, "task_dir": task_dir})
    except Exception as e:
        logger.error("EXTRACTION ERROR: %s", str(e))
        return jsonify({"success": False, "error": str(e)}), 500


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
