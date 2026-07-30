"""
Database module - SQLite storage for Admin Channel Bot
ماژول پایگاه داده - ذخیره‌سازی SQLite برای ربات ادمین کانال

Tables / جداول:
- config: Key-value configuration storage / ذخیره‌سازی تنظیمات کلید-مقدار
- templates: Message templates / قالب‌های پیام
- schedules: Scheduled sends / زمان‌بندی ارسال

Functions / توابع:
- init(): Initialize database / مقداردهی اولیه دیتابیس
- get/put: Config operations / عملیات تنظیمات
- add/get/update/delete_template: Template CRUD / عملیات قالب
- add/get/update/delete_schedule: Schedule CRUD / عملیات زمان‌بندی
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
            template_id INTEGER NOT NULL,
            channel_id TEXT NOT NULL,
            times TEXT DEFAULT '[]',
            active INTEGER DEFAULT 1,
            created_at TEXT,
            FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE
        );
    """)
    c.commit()
    c.close()


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
def add_schedule(template_id, channel_id, times):
    c = _conn()
    now = datetime.now().isoformat()
    cur = c.execute(
        "INSERT INTO schedules(template_id, channel_id, times, created_at) VALUES(?,?,?,?)",
        (template_id, channel_id, json.dumps(times), now),
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
    vals.append(sid)
    c.execute(f"UPDATE schedules SET {', '.join(parts)} WHERE id=?", vals)
    c.commit()
    c.close()


def delete_schedule(sid):
    c = _conn()
    c.execute("DELETE FROM schedules WHERE id=?", (sid,))
    c.commit()
    c.close()
