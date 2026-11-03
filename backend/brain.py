
import os, re, sqlite3, hmac, unicodedata
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher
from fastapi import APIRouter, Header, HTTPException, Query

router = APIRouter(prefix="/api/brain", tags=["Brain Training"])
BASE = Path(__file__).resolve().parent
DB = BASE / "brain.db"
ENV = BASE / ".env"

def setting(name):
    value = os.environ.get(name)
    if value:
        return value
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db

with connect() as db:
    db.execute("""CREATE TABLE IF NOT EXISTS trainings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger_text TEXT NOT NULL,
        response_text TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'عام',
        mode TEXT NOT NULL DEFAULT 'hybrid',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")

def authorize(key):
    expected = setting("BRAIN_ADMIN_KEY")
    if not expected or not key or not hmac.compare_digest(key, expected):
        raise HTTPException(401, "مفتاح إدارة التدريب غير صحيح")

def clean(s):
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    s = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())

def similarity(a, b):
    a, b = clean(a), clean(b)
    if not a or not b:
        return 0
    if a == b or b in a:
        return 1.0
    x, y = set(a.split()), set(b.split())
    overlap = len(x & y) / max(1, len(x | y))
    return round(max(overlap, SequenceMatcher(None, a, b).ratio() * .85), 4)

@router.post("/train")
def add(data: dict, x_admin_key: str | None = Header(default=None)):
    authorize(x_admin_key)
    trigger = str(data.get("trigger_text", "")).strip()
    response = str(data.get("response_text", "")).strip()
    category = str(data.get("category", "عام")).strip() or "عام"
    mode = data.get("mode", "hybrid")
    if not trigger or not response or mode not in ("hybrid", "literal"):
        raise HTTPException(400, "بيانات التدريب غير صالحة")
    if len(trigger) > 2000 or len(response) > 10000:
        raise HTTPException(400, "النص أطول من الحد المسموح")
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        cur = db.execute(
            "INSERT INTO trainings(trigger_text,response_text,category,mode,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (trigger,response,category,mode,now,now))
    return {"ok": True, "id": cur.lastrowid}

@router.get("/train")
def listing(x_admin_key: str | None = Header(default=None)):
    authorize(x_admin_key)
    with connect() as db:
        rows = db.execute("SELECT * FROM trainings ORDER BY id DESC").fetchall()
    return {"items": [dict(r) for r in rows]}

@router.put("/train/{item_id}")
def update(item_id: int, data: dict, x_admin_key: str | None = Header(default=None)):
    authorize(x_admin_key)
    with connect() as db:
        old = db.execute("SELECT * FROM trainings WHERE id=?", (item_id,)).fetchone()
        if not old:
            raise HTTPException(404, "التدريب غير موجود")
        trigger = str(data.get("trigger_text", old["trigger_text"])).strip()
        response = str(data.get("response_text", old["response_text"])).strip()
        category = str(data.get("category", old["category"])).strip() or "عام"
        mode = data.get("mode", old["mode"])
        enabled = int(bool(data.get("enabled", old["enabled"])))
        if not trigger or not response or mode not in ("hybrid", "literal"):
            raise HTTPException(400, "بيانات غير صالحة")
        db.execute("UPDATE trainings SET trigger_text=?,response_text=?,category=?,mode=?,enabled=?,updated_at=? WHERE id=?",
                   (trigger,response,category,mode,enabled,datetime.now(timezone.utc).isoformat(),item_id))
    return {"ok": True}

@router.delete("/train/{item_id}")
def delete(item_id: int, x_admin_key: str | None = Header(default=None)):
    authorize(x_admin_key)
    with connect() as db:
        cur = db.execute("DELETE FROM trainings WHERE id=?", (item_id,))
        if not cur.rowcount:
            raise HTTPException(404, "التدريب غير موجود")
    return {"ok": True}

@router.get("/stats")
def stats(x_admin_key: str | None = Header(default=None)):
    authorize(x_admin_key)
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM trainings").fetchone()[0]
        active = db.execute("SELECT COUNT(*) FROM trainings WHERE enabled=1").fetchone()[0]
    return {"total": total, "active": active}

def find_training(query, threshold=.48):
    with connect() as db:
        rows = db.execute("SELECT * FROM trainings WHERE enabled=1").fetchall()
    if not rows:
        return None
    ranked = [(similarity(query, r["trigger_text"]), r) for r in rows]
    score, row = max(ranked, key=lambda x: x[0])
    if score < threshold:
        return None
    return {"id": row["id"], "trigger_text": row["trigger_text"],
            "response_text": row["response_text"], "category": row["category"],
            "mode": row["mode"], "score": score}

@router.get("/match")
def match(q: str = Query(min_length=1, max_length=2000),
          x_admin_key: str | None = Header(default=None)):
    authorize(x_admin_key)
    result = find_training(q)
    return {"matched": bool(result), "result": result}


# User monitoring and IP blocking
with connect() as db:
    db.execute("""CREATE TABLE IF NOT EXISTS user_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL, ip TEXT NOT NULL,
        message TEXT NOT NULL, created_at TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS blocked_ips (
        ip TEXT PRIMARY KEY, note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
    )""")

# إضافة نوع الرسالة مع الحفاظ على السجلات القديمة
with connect() as db:
    columns = [r["name"] for r in db.execute("PRAGMA table_info(user_activity)").fetchall()]
    if "role" not in columns:
        db.execute("ALTER TABLE user_activity ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")


def record_activity(username, ip, message, role="user"):
    username = str(username or "زائر").strip()[:60] or "زائر"
    role = "assistant" if role == "assistant" else "user"
    with connect() as db:
        db.execute(
            "INSERT INTO user_activity(username,ip,message,created_at,role) VALUES(?,?,?,?,?)",
            (username, str(ip)[:64], str(message or "").strip()[:10000],
             datetime.now(timezone.utc).isoformat(), role)
        )

def is_ip_blocked(ip):
    with connect() as db:
        return db.execute(
            "SELECT 1 FROM blocked_ips WHERE ip=? AND enabled=1", (ip,)
        ).fetchone() is not None

@router.get("/users")
def monitored_users(x_admin_key: str | None = Header(default=None)):
    authorize(x_admin_key)
    with connect() as db:
        rows = db.execute("""
            SELECT username,ip,
                   SUM(CASE WHEN role='user' THEN 1 ELSE 0 END) requests,
                   COUNT(*) messages, MAX(created_at) last_seen
            FROM user_activity
            GROUP BY username,ip ORDER BY last_seen DESC
        """).fetchall()
        blocked = {r["ip"] for r in db.execute(
            "SELECT ip FROM blocked_ips WHERE enabled=1"
        ).fetchall()}
    return {"items": [{**dict(r), "blocked": r["ip"] in blocked} for r in rows]}

@router.get("/activity")
def user_activity(
    ip: str | None = Query(default=None, max_length=64),
    username: str | None = Query(default=None, max_length=60),
    x_admin_key: str | None = Header(default=None)
):
    authorize(x_admin_key)
    conditions, values = [], []
    if ip:
        conditions.append("ip=?")
        values.append(ip)
    if username:
        conditions.append("username=?")
        values.append(username)
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM user_activity" + where + " ORDER BY id ASC",
            values
        ).fetchall()
    return {"items": [dict(r) for r in rows]}

@router.get("/blocks")
def blocked_list(x_admin_key: str | None = Header(default=None)):
    authorize(x_admin_key)
    with connect() as db:
        rows = db.execute("SELECT * FROM blocked_ips ORDER BY created_at DESC").fetchall()
    return {"items": [dict(r) for r in rows]}

@router.post("/block")
def block_ip(data: dict, x_admin_key: str | None = Header(default=None)):
    authorize(x_admin_key)
    import ipaddress
    try:
        ip = str(ipaddress.ip_address(str(data.get("ip", "")).strip()))
    except ValueError:
        raise HTTPException(400, "عنوان IP غير صالح")
    parsed = ipaddress.ip_address(ip)
    if parsed.is_loopback or parsed.is_unspecified or parsed.is_multicast:
        raise HTTPException(400, "لا يمكن حظر عنوان محلي أو غير صالح")
    note = str(data.get("note", "")).strip()[:200]
    with connect() as db:
        db.execute("""INSERT INTO blocked_ips(ip,note,created_at,enabled)
            VALUES(?,?,?,1) ON CONFLICT(ip) DO UPDATE SET
            note=excluded.note,enabled=1""",
            (ip, note, datetime.now(timezone.utc).isoformat()))
    return {"ok": True, "ip": ip}

@router.post("/unblock")
def unblock_ip(data: dict, x_admin_key: str | None = Header(default=None)):
    authorize(x_admin_key)
    import ipaddress
    try:
        ip = str(ipaddress.ip_address(str(data.get("ip", "")).strip()))
    except ValueError:
        raise HTTPException(400, "عنوان IP غير صالح")
    with connect() as db:
        cur = db.execute("UPDATE blocked_ips SET enabled=0 WHERE ip=?", (ip,))
    return {"ok": True, "changed": bool(cur.rowcount)}
