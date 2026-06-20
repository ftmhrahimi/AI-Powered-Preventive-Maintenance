import sqlite3
import hashlib
import json
import os

from config import DB_PATH

os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin BOOLEAN DEFAULT 0
        )
    ''')
    
    # Reports table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            taskId TEXT NOT NULL,
            fileName TEXT,
            siteId TEXT,
            taskCategory TEXT,
            taskSubcategory TEXT,
            reportDate TEXT,
            fmeName TEXT,
            confirmation INTEGER,
            status TEXT DEFAULT 'pending',
            data_json TEXT NOT NULL,
            savedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (username) REFERENCES users(username),
            UNIQUE(username, taskId)
        )
    ''')
    
    # Create admin user if not exists (credentials configurable via .env)
    admin_user = os.getenv("ADMIN_USERNAME", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD", "1234@Qwer")
    cursor.execute("SELECT * FROM users WHERE username = ?", (admin_user,))
    if not cursor.fetchone():
        # Simple hash for consistency with the requested pass
        h = hashlib.sha256(admin_pass.encode()).hexdigest()
        cursor.execute(
            "INSERT INTO users (username, name, password_hash, is_admin) VALUES (?, ?, ?, ?)",
            (admin_user, "System Admin", h, 1)
        )
        
# Migration: add status column to older databases that lack it
    try:
        cols = [r['name'] for r in cursor.execute("PRAGMA table_info(reports)").fetchall()]
        if 'status' not in cols:
            cursor.execute("ALTER TABLE reports ADD COLUMN status TEXT DEFAULT 'pending'")
    except Exception as e:
        print(f"Status column migration skipped: {e}")

    conn.commit()
    conn.close()
    init_user_files_table()
    init_task_rules_table()
    init_sites_table()
    init_server_runs_table()
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, name, password):
    conn = get_db()
    try:
        h = hash_password(password)
        conn.execute(
            "INSERT INTO users (username, name, password_hash) VALUES (?, ?, ?)",
            (username, name, h)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def login_user(username, password):
    conn = get_db()
    h = hash_password(password)
    user = conn.execute(
        "SELECT * FROM users WHERE username = ? AND password_hash = ?",
        (username, h)
    ).fetchone()
    conn.close()
    return dict(user) if user else None
def is_admin_user(username):
    if not username:
        return False
    conn = get_db()
    user = conn.execute(
        "SELECT is_admin FROM users WHERE username = ?",
        (username,)
    ).fetchone()
    conn.close()
    return bool(user and user['is_admin'])

def is_admin_user(username):
    if not username:
        return False
    conn = get_db()
    user = conn.execute(
        "SELECT is_admin FROM users WHERE username = ?",
        (username,)
    ).fetchone()
    conn.close()
    return bool(user and user['is_admin'])
    
import json

def save_report(username, report_data):
    conn = get_db()

    try:
        task_id = report_data.get('taskId')

        # Store full JSON and extracted fields
        conn.execute('''
            INSERT INTO reports 
            (
                username,
                taskId,
                fileName,
                siteId,
                taskCategory,
                taskSubcategory,
                reportDate,
                fmeName,
                confirmation,
                status,
                data_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(username, taskId) DO UPDATE SET
                fileName = excluded.fileName,
                siteId = excluded.siteId,
                taskCategory = excluded.taskCategory,
                taskSubcategory = excluded.taskSubcategory,
                reportDate = excluded.reportDate,
                fmeName = excluded.fmeName,
                confirmation = excluded.confirmation,
                status = excluded.status,
                data_json = excluded.data_json,
                savedAt = CURRENT_TIMESTAMP
        ''', (
            username,
            task_id,
            report_data.get('fileName'),
            report_data.get('siteId'),
            report_data.get('taskCategory'),
            report_data.get('taskSubcategory'),
            report_data.get('reportDate'),
            report_data.get('fmeName'),
            report_data.get('confirmation'),
            report_data.get('status', 'pending'),
            json.dumps(report_data)
        ))

        conn.commit()
        return True

    except Exception as e:
        print(f"Error saving report: {e}")
        return False

    finally:
        conn.close()
def get_user_reports(username):
    conn = get_db()
    rows = conn.execute(
        "SELECT data_json, status FROM reports WHERE username = ? ORDER BY savedAt DESC",
        (username,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        data = json.loads(r['data_json'])
        data['status'] = r['status'] or data.get('status') or 'pending'
        result.append(data)
    return result

def get_all_reports():
    conn = get_db()
    rows = conn.execute('''
        SELECT r.data_json, r.username, u.name AS owner_name
        FROM reports r
        LEFT JOIN users u ON u.username = r.username
        ORDER BY r.savedAt DESC
    ''').fetchall()
    conn.close()

    results = []
    for r in rows:
        data = json.loads(r['data_json'])
        data['owner'] = r['username'] # Keep username for admin actions/downloads
        data['ownerName'] = r['owner_name'] or r['username'] # Display registered full name in admin dashboard
        results.append(data)
    return results

def delete_report(username, task_id):
    conn = get_db()
    conn.execute(
        "DELETE FROM reports WHERE username = ? AND taskId = ?",
        (username, task_id)
    )
    conn.commit()
    conn.close()


def delete_report_by_filename(username, file_name):
    conn = get_db()
    conn.execute(
        "DELETE FROM reports WHERE username = ? AND fileName = ?",
        (username, file_name)
    )
    conn.commit()
    conn.close()


def init_user_files_table():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS user_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            fileName TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            confirmation INTEGER,
            data_json TEXT NOT NULL,
            updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(username, fileName),
            FOREIGN KEY (username) REFERENCES users(username)
        )
    ''')
    conn.commit()
    conn.close()


def save_user_file(username, file_data):
    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO user_files (username, fileName, status, confirmation, data_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(username, fileName) DO UPDATE SET
                status = excluded.status,
                confirmation = excluded.confirmation,
                data_json = excluded.data_json,
                updatedAt = CURRENT_TIMESTAMP
        ''', (
            username,
            file_data.get('fileName'),
            file_data.get('status', 'pending'),
            file_data.get('confirmation'),
            json.dumps(file_data)
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error saving user file: {e}")
        return False
    finally:
        conn.close()


def get_user_files(username):
    conn = get_db()
    rows = conn.execute(
        "SELECT data_json FROM user_files WHERE username = ? ORDER BY updatedAt ASC",
        (username,)
    ).fetchall()
    conn.close()
    return [json.loads(r['data_json']) for r in rows]


def delete_user_file(username, file_name):
    conn = get_db()
    conn.execute(
        "DELETE FROM user_files WHERE username = ? AND fileName = ?",
        (username, file_name)
    )
    conn.commit()
    conn.close()


def delete_all_user_files(username):
    conn = get_db()
    conn.execute(
        "DELETE FROM user_files WHERE username = ?",
        (username,)
    )
    conn.commit()
    conn.close()

def init_task_rules_table():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS task_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            taskCategory TEXT NOT NULL,
            taskSubcategory TEXT NOT NULL,
            taskNumber TEXT NOT NULL,
            expected TEXT,
            checkpoints TEXT,   -- JSON array stored as text
            fail_if TEXT,       -- JSON array stored as text
            updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(taskCategory, taskSubcategory, taskNumber)
        )
    ''')
    conn.commit()
    conn.close()

def get_all_task_rules():
    conn = get_db()
    rows = conn.execute("SELECT * FROM task_rules ORDER BY taskCategory, taskSubcategory, CAST(taskNumber AS INTEGER)").fetchall()
    conn.close()
    result = {}
    for r in rows:
        cat = r['taskCategory']
        sub = r['taskSubcategory']
        num = r['taskNumber']
        result.setdefault(cat, {}).setdefault(sub, {})[num] = {
            "expected": r['expected'] or '',
            "checkpoints": json.loads(r['checkpoints'] or '[]'),
            "fail_if": json.loads(r['fail_if'] or '[]')
        }
    return result

def upsert_task_rule(category, subcategory, task_number, expected, checkpoints, fail_if):
    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO task_rules (taskCategory, taskSubcategory, taskNumber, expected, checkpoints, fail_if)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(taskCategory, taskSubcategory, taskNumber) DO UPDATE SET
                expected = excluded.expected,
                checkpoints = excluded.checkpoints,
                fail_if = excluded.fail_if,
                updatedAt = CURRENT_TIMESTAMP
        ''', (category, subcategory, str(task_number), expected,
              json.dumps(checkpoints), json.dumps(fail_if)))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error upserting task rule: {e}")
        return False
    finally:
        conn.close()

def delete_task_rule(category, subcategory, task_number):
    conn = get_db()
    conn.execute(
        "DELETE FROM task_rules WHERE taskCategory=? AND taskSubcategory=? AND taskNumber=?",
        (category, subcategory, str(task_number))
    )
    conn.commit()
    conn.close()

def init_sites_table():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sites (
            siteId TEXT PRIMARY KEY,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_all_sites():
    conn = get_db()
    rows = conn.execute("SELECT siteId, lat, lon FROM sites ORDER BY siteId").fetchall()
    conn.close()
    return [{"siteId": r['siteId'], "lat": r['lat'], "lon": r['lon']} for r in rows]

def upsert_site(site_id, lat, lon):
    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO sites (siteId, lat, lon)
            VALUES (?, ?, ?)
            ON CONFLICT(siteId) DO UPDATE SET
                lat = excluded.lat,
                lon = excluded.lon,
                updatedAt = CURRENT_TIMESTAMP
        ''', (site_id, float(lat), float(lon)))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error upserting site: {e}")
        return False
    finally:
        conn.close()

def delete_site(site_id):
    conn = get_db()
    conn.execute("DELETE FROM sites WHERE siteId=?", (site_id,))
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────────
#  Server-side run queue
#
#  Lets a user request that their pending files be processed on the server by
#  a headless-browser worker, so the work continues even after they close the
#  browser / shut down their computer. State machine: pending → running →
#  done | failed.
# ──────────────────────────────────────────────────────────────────────────
def init_server_runs_table():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS server_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
            target TEXT,                             -- NULL = all pending; else a single fileName
            error TEXT,
            createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (username) REFERENCES users(username)
        )
    ''')
    # Migration for databases created before the 'target' column existed.
    try:
        conn.execute("ALTER TABLE server_runs ADD COLUMN target TEXT")
    except Exception:
        pass
    conn.commit()
    conn.close()


def get_user_session(username):
    """Return the minimal user object the frontend stores in its session
    (localStorage['pm_session']), so the worker can log in as that user."""
    if not username:
        return None
    conn = get_db()
    user = conn.execute(
        "SELECT username, name, is_admin FROM users WHERE username = ?",
        (username,)
    ).fetchone()
    conn.close()
    if not user:
        return None
    return {"username": user['username'], "name": user['name'], "isAdmin": bool(user['is_admin'])}


def enqueue_server_run(username, target=None):
    """Queue a server-side run for this user. target=None means "all pending
    files"; otherwise a single fileName. Reuses an existing pending/running run
    with the SAME target so double-clicks don't stack duplicates."""
    conn = get_db()
    try:
        if target is None:
            existing = conn.execute(
                "SELECT id, status FROM server_runs WHERE username = ? "
                "AND status IN ('pending','running') AND target IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (username,)
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id, status FROM server_runs WHERE username = ? "
                "AND status IN ('pending','running') AND target = ? "
                "ORDER BY id DESC LIMIT 1",
                (username, target)
            ).fetchone()
        if existing:
            return {"id": existing['id'], "status": existing['status'], "reused": True}
        cur = conn.execute(
            "INSERT INTO server_runs (username, status, target) VALUES (?, 'pending', ?)",
            (username, target)
        )
        conn.commit()
        return {"id": cur.lastrowid, "status": "pending", "reused": False}
    finally:
        conn.close()


def get_latest_server_run(username):
    """Return the user's most relevant run for the UI: a currently running one
    first, then the newest pending, then the newest of anything else."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, status, target, error, updatedAt FROM server_runs "
        "WHERE username = ? "
        "ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, "
        "id DESC LIMIT 1",
        (username,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def requeue_stale_running(max_age_seconds):
    """Reset 'running' rows whose worker likely died (no update within the
    cutoff) back to 'pending' so they get picked up again."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE server_runs SET status='pending', updatedAt=CURRENT_TIMESTAMP "
            "WHERE status='running' "
            "AND (strftime('%s','now') - strftime('%s', updatedAt)) > ?",
            (int(max_age_seconds),)
        )
        conn.commit()
    finally:
        conn.close()


def claim_next_server_run():
    """Atomically move the oldest pending run to 'running' and return it.
    Relies on the caller holding an in-process lock (backend runs single
    process), plus a guarded UPDATE for safety."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, username, target FROM server_runs WHERE status='pending' "
            "ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        cur = conn.execute(
            "UPDATE server_runs SET status='running', updatedAt=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='pending'",
            (row['id'],)
        )
        conn.commit()
        if cur.rowcount != 1:
            return None
        return {"id": row['id'], "username": row['username'], "target": row['target']}
    finally:
        conn.close()


def heartbeat_server_run(run_id):
    conn = get_db()
    conn.execute(
        "UPDATE server_runs SET updatedAt=CURRENT_TIMESTAMP WHERE id=? AND status='running'",
        (run_id,)
    )
    conn.commit()
    conn.close()


def finish_server_run(run_id, status, error=None):
    conn = get_db()
    conn.execute(
        "UPDATE server_runs SET status=?, error=?, updatedAt=CURRENT_TIMESTAMP WHERE id=?",
        (status, error, run_id)
    )
    conn.commit()
    conn.close()


def cancel_server_run(username):
    """Mark the user's active (pending or running) run as cancelled. The worker
    polls for this and stops the headless run at the next item boundary."""
    conn = get_db()
    cur = conn.execute(
        "UPDATE server_runs SET status='cancelled', updatedAt=CURRENT_TIMESTAMP "
        "WHERE username=? AND status IN ('pending','running')",
        (username,)
    )
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n
