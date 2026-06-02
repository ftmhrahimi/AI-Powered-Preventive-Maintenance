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
            status TEXT DEFAULT 'pending',
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
