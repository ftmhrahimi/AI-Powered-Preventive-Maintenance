import sqlite3
import hashlib
import json
import os

DB_PATH = "pm_validator.db"

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
            data_json TEXT NOT NULL,
            savedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (username) REFERENCES users(username),
            UNIQUE(username, taskId)
        )
    ''')

    # Create admin user if not exists
    admin_user = "admin"
    admin_pass = "1234@Qwer"
    cursor.execute("SELECT * FROM users WHERE username = ?", (admin_user,))
    if not cursor.fetchone():
        # Simple hash for consistency with the requested pass
        h = hashlib.sha256(admin_pass.encode()).hexdigest()
        cursor.execute(
            "INSERT INTO users (username, name, password_hash, is_admin) VALUES (?, ?, ?, ?)",
            (admin_user, "System Admin", h, 1)
        )

    conn.commit()
    conn.close()

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

def save_report(username, report_data):
    conn = get_db()
    try:
        task_id = report_data.get('taskId')
        # We store the full JSON but also extract key fields for filtering
        conn.execute('''
            INSERT INTO reports
            (username, taskId, fileName, siteId, taskCategory, taskSubcategory, reportDate, fmeName, confirmation, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, taskId) DO UPDATE SET
            fileName=excluded.fileName, siteId=excluded.siteId, taskCategory=excluded.taskCategory,
            taskSubcategory=excluded.taskSubcategory, reportDate=excluded.reportDate,
            fmeName=excluded.fmeName, confirmation=excluded.confirmation, data_json=excluded.data_json,
            savedAt=CURRENT_TIMESTAMP
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
        "SELECT data_json FROM reports WHERE username = ? ORDER BY savedAt DESC",
        (username,)
    ).fetchall()
    conn.close()
    return [json.loads(r['data_json']) for r in rows]

def get_all_reports():
    conn = get_db()
    rows = conn.execute('''
        SELECT r.data_json, r.username
        FROM reports r
        ORDER BY r.savedAt DESC
    ''').fetchall()
    conn.close()

    results = []
    for r in rows:
        data = json.loads(r['data_json'])
        data['owner'] = r['username'] # Add owner field for admin view
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
