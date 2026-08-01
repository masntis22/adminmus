"""
Database module - SQLite storage for Admin Channel Bot
ماژول پایگاه داده - ذخیره‌سازی SQLite برای ربات ادمین کانال

Tables / جداول:
- config: Key-value configuration storage / ذخیره‌سازی تنظیمات کلید-مقدار
- templates: Message templates / قالب‌های پیام
- schedules: Scheduled sends with types (recurring/onetime) / زمان‌بندی ارسال
- collected_messages: Multi-task message collection / جمع‌آوری پیام‌ها

Functions / توابع:
- init(): Initialize database / مقداردهی اولیه دیتابیس
- get/put: Config operations / عملیات تنظیمات
- add/get/update/delete_template: Template CRUD / عملیات قالب
- add/get/update/delete_schedule: Schedule CRUD / عملیات زمان‌بندی
- add/get/delete_collected_message: Message collection / جمع‌آوری پیام
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "bot_data" / "admin.db"


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init():
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            image_file_id TEXT,
            text_content TEXT DEFAULT '',
            music_file_id TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER,
            channel_id TEXT NOT NULL,
            schedule_type TEXT DEFAULT 'recurring',
            times TEXT DEFAULT '[]',
            send_datetime TEXT,
            start_date TEXT,
            end_date TEXT,
            message_text TEXT DEFAULT '',
            image_file_id TEXT,
            music_file_id TEXT,
            name TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            last_sent_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS collected_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            message_type TEXT NOT NULL,
            text_content TEXT DEFAULT '',
            file_id TEXT DEFAULT '',
            file_type TEXT DEFAULT '',
            created_at TEXT
        );
    """)
    c.commit()

    # ── Migration: upgrade old schedules table ──
    _migrate_schedules(c)

    c.close()


def _migrate_schedules(c):
    """Upgrade old schedules table to new schema if needed / بروزرسانی جدول زمان‌بندی"""
    cursor = c.execute("PRAGMA table_info(schedules)")
    columns = {row[1] for row in cursor.fetchall()}

    alterations = {
        "schedule_type": "ALTER TABLE schedules ADD COLUMN schedule_type TEXT DEFAULT 'recurring'",
        "send_datetime": "ALTER TABLE schedules ADD COLUMN send_datetime TEXT",
        "start_date": "ALTER TABLE schedules ADD COLUMN start_date TEXT",
        "end_date": "ALTER TABLE schedules ADD COLUMN end_date TEXT",
        "message_text": "ALTER TABLE schedules ADD COLUMN message_text TEXT DEFAULT ''",
        "image_file_id": "ALTER TABLE schedules ADD COLUMN image_file_id TEXT",
        "music_file_id": "ALTER TABLE schedules ADD COLUMN music_file_id TEXT",
        "name": "ALTER TABLE schedules ADD COLUMN name TEXT DEFAULT ''",
        "last_sent_at": "ALTER TABLE schedules ADD COLUMN last_sent_at TEXT",
        "updated_at": "ALTER TABLE schedules ADD COLUMN updated_at TEXT",
    }

    for col, sql in alterations.items():
        if col not in columns:
            try:
                c.execute(sql)
            except sqlite3.OperationalError:
                pass  # already exists

    # Make template_id nullable for direct-message schedules
    # SQLite doesn't support ALTER COLUMN, so we recreate if needed
    try:
        c.execute("SELECT template_id FROM schedules LIMIT 1")
    except sqlite3.OperationalError:
        pass

    c.commit()


# ─── Config ───────────────────────────────────────────────────
def get(key, default=None):
    c = _conn()
    r = c.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    c.close()
    return r["value"] if r else default


def put(key, value):
    c = _conn()
    c.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?,?)", (key, str(value)))
    c.commit()
    c.close()


def all_config():
    c = _conn()
    rows = c.execute("SELECT * FROM config").fetchall()
    c.close()
    return {r["key"]: r["value"] for r in rows}


# ─── Templates ────────────────────────────────────────────────
def add_template(name, image=None, text="", music=None):
    c = _conn()
    now = datetime.now().isoformat()
    cur = c.execute(
        "INSERT INTO templates(name, image_file_id, text_content, music_file_id, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?)",
        (name, image, text, music, now, now),
    )
    c.commit()
    tid = cur.lastrowid
    c.close()
    return tid


def get_templates():
    c = _conn()
    rows = c.execute("SELECT * FROM templates ORDER BY id").fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_template(tid):
    c = _conn()
    r = c.execute("SELECT * FROM templates WHERE id=?", (tid,)).fetchone()
    c.close()
    return dict(r) if r else None


def update_template(tid, **kw):
    if not kw:
        return
    c = _conn()
    parts = [f"{k}=?" for k in kw]
    vals = list(kw.values()) + [datetime.now().isoformat(), tid]
    c.execute(f"UPDATE templates SET {', '.join(parts)}, updated_at=? WHERE id=?", vals)
    c.commit()
    c.close()


def delete_template(tid):
    c = _conn()
    c.execute("DELETE FROM templates WHERE id=?", (tid,))
    c.commit()
    c.close()


# ─── Schedules ────────────────────────────────────────────────
def add_schedule(template_id, channel_id, times, schedule_type="recurring",
                 start_date=None, end_date=None, send_datetime=None,
                 name="", message_text="", image_file_id=None, music_file_id=None):
    c = _conn()
    now = datetime.now().isoformat()
    cur = c.execute(
        """INSERT INTO schedules(
            template_id, channel_id, schedule_type, times, send_datetime,
            start_date, end_date, name, message_text, image_file_id,
            music_file_id, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (template_id, channel_id, schedule_type, json.dumps(times),
         send_datetime, start_date, end_date, name,
         message_text or "", image_file_id, music_file_id, now, now),
    )
    c.commit()
    sid = cur.lastrowid
    c.close()
    return sid


def get_schedules():
    c = _conn()
    rows = c.execute("SELECT * FROM schedules ORDER BY id").fetchall()
    c.close()
    result = []
    for r in rows:
        d = dict(r)
        d["times"] = json.loads(d["times"]) if d["times"] else []
        result.append(d)
    return result


def get_schedule(sid):
    c = _conn()
    r = c.execute("SELECT * FROM schedules WHERE id=?", (sid,)).fetchone()
    c.close()
    if r:
        d = dict(r)
        d["times"] = json.loads(d["times"]) if d["times"] else []
        return d
    return None


def get_active_schedules():
    c = _conn()
    rows = c.execute("SELECT * FROM schedules WHERE active=1").fetchall()
    c.close()
    result = []
    for r in rows:
        d = dict(r)
        d["times"] = json.loads(d["times"]) if d["times"] else []
        result.append(d)
    return result


def update_schedule(sid, **kw):
    if not kw:
        return
    c = _conn()
    parts = []
    vals = []
    for k, v in kw.items():
        if k == "times":
            v = json.dumps(v)
        parts.append(f"{k}=?")
        vals.append(v)
    parts.append("updated_at=?")
    vals.append(datetime.now().isoformat())
    vals.append(sid)
    c.execute(f"UPDATE schedules SET {', '.join(parts)} WHERE id=?", vals)
    c.commit()
    c.close()


def delete_schedule(sid):
    c = _conn()
    c.execute("DELETE FROM schedules WHERE id=?", (sid,))
    c.commit()
    c.close()


# ─── Collected Messages (Multi-task) ──────────────────────────
def add_collected_message(user_id, session_id, message_type, text_content="",
                          file_id="", file_type=""):
    c = _conn()
    now = datetime.now().isoformat()
    cur = c.execute(
        """INSERT INTO collected_messages(
            user_id, session_id, message_type, text_content, file_id, file_type, created_at
        ) VALUES(?,?,?,?,?,?,?)""",
        (user_id, session_id, message_type, text_content, file_id, file_type, now),
    )
    c.commit()
    mid = cur.lastrowid
    c.close()
    return mid


def get_collected_messages(user_id, session_id):
    c = _conn()
    rows = c.execute(
        "SELECT * FROM collected_messages WHERE user_id=? AND session_id=? ORDER BY id",
        (user_id, session_id),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def clear_collected_messages(user_id, session_id):
    c = _conn()
    c.execute(
        "DELETE FROM collected_messages WHERE user_id=? AND session_id=?",
        (user_id, session_id),
    )
    c.commit()
    c.close()
