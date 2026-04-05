"""
3D Print Hub ÃÂÃÂÃÂÃÂ¢ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ FastAPI Dashboard Backend
Serves live data from the bot's SQLite database to the web dashboard.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from api.auth import check_auth, auth_response

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for health endpoint
        if request.url.path == "/api/health":
            return await call_next(request)
        if not check_auth(request):
            return auth_response()
        return await call_next(request)


DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "./assets/prints")
DASHBOARD_DIR = os.getenv("DASHBOARD_DIR", "./dashboard")
API_PORT = int(os.getenv("API_PORT", "8000"))

_db = None

async def get_db():
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db

async def _init_tables(db):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description TEXT DEFAULT '', image_path TEXT DEFAULT '',
            tags TEXT DEFAULT '', printer TEXT DEFAULT '', material TEXT DEFAULT '',
            stl_link TEXT DEFAULT '', posted_by INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'posted',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            user_id INTEGER, username TEXT,
            rating INTEGER CHECK(rating BETWEEN 1 AND 5), text TEXT,
            message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT,
            prints_shared INTEGER DEFAULT 0, reviews_given INTEGER DEFAULT 0,
            requests_fulfilled INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS print_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0,
            username TEXT, description TEXT,
            claimed_by INTEGER DEFAULT NULL, claimed_by_username TEXT DEFAULT NULL,
            status TEXT DEFAULT 'open', message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS potd_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            featured_date TEXT DEFAULT (date('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS channel_stats (
            channel_id TEXT PRIMARY KEY, name TEXT,
            emoji TEXT DEFAULT '', message_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    await db.commit()


class PrintCreate(BaseModel):
    name: str
    description: str = ""
    material: str = ""
    printer: str = ""
    tags: str = ""
    stl_link: str = ""
    image_path: str = ""
    status: str = "draft"

class PrintUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    material: str | None = None
    printer: str | None = None
    tags: str | None = None
    stl_link: str | None = None
    image_path: str | None = None
    status: str | None = None

class ReviewCreate(BaseModel):
    print_id: int
    username: str
    rating: int = Field(ge=1, le=5)
    text: str

class RequestCreate(BaseModel):
    username: str
    description: str

class RequestUpdate(BaseModel):
    status: str | None = None
    claimed_by_username: str | None = None

class SettingsModel(BaseModel):
    bot_token: str = ""
    admin_ids: str = ""
    timezone: str = "America/New_York"
    potd_time: str = "09:00"
    tip_time: str = "12:00"
    channel_announcements: str = ""
    channel_gallery: str = ""
    channel_reviews: str = ""
    channel_tips: str = ""
    channel_requests: str = ""
    channel_polls: str = ""
    main_group: str = ""
    image_source_path: str = "./assets/prints/"
    image_source_url: str = ""

class ActivityCreate(BaseModel):
    type: str
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_db()
    yield
    if _db:
        await _db.close()

app = FastAPI(title="3D Print Hub API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/stats")
async def get_stats():
    db = await get_db()
    pc = await db.execute("SELECT COUNT(*) FROM prints")
    prints_count = (await pc.fetchone())[0]
    rc = await db.execute("SELECT COUNT(*) FROM reviews")
    reviews_count = (await rc.fetchone())[0]
    ar = await db.execute("SELECT AVG(rating) FROM reviews")
    avg_rating = (await ar.fetchone())[0]
    avg_rating = round(avg_rating, 1) if avg_rating else 0
    mc = await db.execute("SELECT COUNT(*) FROM users")
    members_count = (await mc.fetchone())[0]
    rq = await db.execute("SELECT COUNT(*) FROM print_requests")
    requests_total = (await rq.fetchone())[0]
    oq = await db.execute("SELECT COUNT(*) FROM print_requests WHERE status='open'")
    open_count = (await oq.fetchone())[0]
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    pw = await db.execute("SELECT COUNT(*) FROM prints WHERE created_at >= ?", (week_ago,))
    prints_week = (await pw.fetchone())[0]
    mw = await db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week_ago,))
    members_week = (await mw.fetchone())[0]
    return {"prints": prints_count, "prints_this_week": prints_week, "reviews": reviews_count, "avgRating": avg_rating, "members": members_count, "members_this_week": members_week, "requests": requests_total, "openRequests": open_count}


@app.get("/api/prints")
async def list_prints(search: str = "", status: str = "", limit: int = 50, offset: int = 0):
    db = await get_db()
    conditions, params = [], []
    if search:
        conditions.append("(p.name LIKE ? OR p.tags LIKE ? OR p.material LIKE ? OR p.description LIKE ?)")
        params.extend([f"%{search}%"] * 4)
    if status:
        conditions.append("p.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT p.*, COALESCE(AVG(r.rating),0) AS avg_rating, COUNT(r.id) AS review_count FROM prints p LEFT JOIN reviews r ON r.print_id=p.id {where} GROUP BY p.id ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(query, params)
    return [{**dict(row), "avg_rating": round(row["avg_rating"], 1), "review_count": row["review_count"]} for row in await cursor.fetchall()]

@app.get("/api/prints/{print_id}")
async def get_print_detail(print_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM prints WHERE id=?", (print_id,))
    row = await cursor.fetchone()
    if not row: raise HTTPException(404, "Print not found")
    avg = await db.execute("SELECT AVG(rating) FROM reviews WHERE print_id=?", (print_id,))
    avg_val = (await avg.fetchone())[0]
    rc = await db.execute("SELECT * FROM reviews WHERE print_id=? ORDER BY created_at DESC", (print_id,))
    reviews = [dict(r) for r in await rc.fetchall()]
    return {**dict(row), "avg_rating": round(avg_val, 1) if avg_val else 0, "reviews": reviews}

@app.post("/api/prints")
async def create_print(data: PrintCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO prints (name,description,material,printer,tags,stl_link,image_path) VALUES (?,?,?,?,?,?,?)", (data.name, data.description, data.material, data.printer, data.tags, data.stl_link, data.image_path))
    await db.commit()
    await _log_activity(db, "print", f"New print added: {data.name}")
    return {"id": cursor.lastrowid, "message": "Print created"}

@app.put("/api/prints/{print_id}")
async def update_print(print_id: int, data: PrintUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE prints SET {set_clause} WHERE id=?", list(fields.values()) + [print_id])
    await db.commit()
    return {"message": "Print updated"}

@app.delete("/api/prints/{print_id}")
async def delete_print(print_id: int):
    db = await get_db()
    await db.execute("DELETE FROM reviews WHERE print_id=?", (print_id,))
    await db.execute("DELETE FROM prints WHERE id=?", (print_id,))
    await db.commit()
    return {"message": "Print deleted"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    safe_name = file.filename.replace(" ", "_").replace("/", "_")
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    path = os.path.join(UPLOADS_DIR, filename)
    content = await file.read()
    with open(path, "wb") as f: f.write(content)
    return {"filename": filename, "path": path, "size": len(content)}


@app.get("/api/reviews")
async def list_reviews(limit: int = 50, offset: int = 0):
    db = await get_db()
    cursor = await db.execute("SELECT r.*, p.name AS print_name FROM reviews r LEFT JOIN prints p ON p.id=r.print_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    return [dict(row) for row in await cursor.fetchall()]

@app.get("/api/reviews/distribution")
async def review_distribution():
    db = await get_db()
    dist = {}
    for rating in range(1, 6):
        c = await db.execute("SELECT COUNT(*) FROM reviews WHERE rating=?", (rating,))
        dist[rating] = (await c.fetchone())[0]
    return dist

@app.post("/api/reviews")
async def create_review(data: ReviewCreate):
    db = await get_db()
    cursor = await db.execute("SELECT name FROM prints WHERE id=?", (data.print_id,))
    pr = await cursor.fetchone()
    if not pr: raise HTTPException(404, "Print not found")
    await db.execute("INSERT INTO reviews (print_id,username,rating,text) VALUES (?,?,?,?)", (data.print_id, data.username, data.rating, data.text))
    await db.commit()
    await _log_activity(db, "review", f"{data.username} reviewed {pr['name']} {'\u2b50'*data.rating}")
    return {"message": "Review created"}


@app.get("/api/requests")
async def list_requests(status: str = "", limit: int = 50):
    db = await get_db()
    if status:
        cursor = await db.execute("SELECT * FROM print_requests WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
    else:
        cursor = await db.execute("SELECT * FROM print_requests ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]

@app.post("/api/requests")
async def create_request(data: RequestCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO print_requests (username,description) VALUES (?,?)", (data.username, data.description))
    await db.commit()
    await _log_activity(db, "request", f"New request from {data.username}: {data.description[:60]}")
    return {"id": cursor.lastrowid, "message": "Request created"}

@app.put("/api/requests/{request_id}")
async def update_request(request_id: int, data: RequestUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    if "claimed_by_username" in fields and "status" not in fields:
        fields["status"] = "claimed"
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE print_requests SET {set_clause} WHERE id=?", list(fields.values()) + [request_id])
    await db.commit()
    if fields.get("status") == "fulfilled":
        await _log_activity(db, "request", f"Request #{request_id} fulfilled!")
    return {"message": "Request updated"}


@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 20):
    db = await get_db()
    cursor = await db.execute("SELECT *, (prints_shared*3 + reviews_given*2 + requests_fulfilled*5) AS score FROM users ORDER BY score DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]


@app.get("/api/activity")
async def get_activity(limit: int = 30):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in await cursor.fetchall()]
    now = datetime.utcnow()
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        delta = now - created
        if delta.days > 0: row["time_ago"] = f"{delta.days}d ago"
        elif delta.seconds >= 3600: row["time_ago"] = f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60: row["time_ago"] = f"{delta.seconds // 60}m ago"
        else: row["time_ago"] = "just now"
    return rows

@app.post("/api/activity")
async def create_activity(data: ActivityCreate):
    db = await get_db()
    await _log_activity(db, data.type, data.text)
    return {"message": "Activity logged"}

async def _log_activity(db, type, text):
    await db.execute("INSERT INTO activity_log (type,text) VALUES (?,?)", (type, text))
    await db.commit()


@app.get("/api/channels")
async def get_channels():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM channel_stats ORDER BY message_count DESC")
    rows = [dict(row) for row in await cursor.fetchall()]
    if not rows:
        return [
            {"channel_id": "announcements", "name": "Announcements", "emoji": "\ud83d\udce2", "message_count": 0},
            {"channel_id": "gallery", "name": "Gallery", "emoji": "\ud83d\uddbc\ufe0f", "message_count": 0},
            {"channel_id": "reviews", "name": "Reviews", "emoji": "\ud83d\udcdd", "message_count": 0},
            {"channel_id": "tips", "name": "Tips & Tricks", "emoji": "\ud83d\udca1", "message_count": 0},
            {"channel_id": "requests", "name": "Requests", "emoji": "\ud83d\ude4b", "message_count": 0},
            {"channel_id": "polls", "name": "Polls", "emoji": "\ud83d\udcca", "message_count": 0},
            {"channel_id": "general", "name": "General", "emoji": "\ud83d\udcac", "message_count": 0},
        ]
    return rows


SETTINGS_FILE = Path("./config/.env")

@app.get("/api/settings")
async def get_settings():
    if not SETTINGS_FILE.exists():
        return SettingsModel().dict()
    env = {}
    for line in SETTINGS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return {
        "bot_token": _mask_token(env.get("BOT_TOKEN", "")),
        "admin_ids": env.get("ADMIN_IDS", ""),
        "timezone": env.get("TIMEZONE", "America/New_York"),
        "potd_time": env.get("POTD_TIME", "09:00"),
        "tip_time": env.get("TIP_TIME", "12:00"),
        "channel_announcements": env.get("CHANNEL_ANNOUNCEMENTS", ""),
        "channel_gallery": env.get("CHANNEL_GALLERY", ""),
        "channel_reviews": env.get("CHANNEL_REVIEWS", ""),
        "channel_tips": env.get("CHANNEL_TIPS", ""),
        "channel_requests": env.get("CHANNEL_REQUESTS", ""),
        "channel_polls": env.get("CHANNEL_POLLS", ""),
        "main_group": env.get("MAIN_GROUP", ""),
        "image_source_path": env.get("IMAGE_SOURCE_PATH", "./assets/prints/"),
        "image_source_url": env.get("IMAGE_SOURCE_URL", ""),
    }

@app.put("/api/settings")
async def save_settings(data: SettingsModel):
    current_token = ""
    if SETTINGS_FILE.exists():
        for line in SETTINGS_FILE.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                current_token = line.split("=", 1)[1].strip()
    token = current_token if "\u2022\u2022\u2022\u2022" in data.bot_token else data.bot_token
    content = f"BOT_TOKEN={token}\nADMIN_IDS={data.admin_ids}\nCHANNEL_ANNOUNCEMENTS={data.channel_announcements}\nCHANNEL_GALLERY={data.channel_gallery}\nCHANNEL_REVIEWS={data.channel_reviews}\nCHANNEL_TIPS={data.channel_tips}\nCHANNEL_REQUESTS={data.channel_requests}\nCHANNEL_POLLS={data.channel_polls}\nMAIN_GROUP={data.main_group}\nPOTD_TIME={data.potd_time}\nTIP_TIME={data.tip_time}\nTIMEZONE={data.timezone}\nIMAGE_SOURCE_PATH={data.image_source_path}\nIMAGE_SOURCE_URL={data.image_source_url}\nDB_PATH={DB_PATH}\n"
    os.makedirs(SETTINGS_FILE.parent, exist_ok=True)
    SETTINGS_FILE.write_text(content)
    return {"message": "Settings saved"}

def _mask_token(token):
    if not token or token == "your_bot_token_here": return ""
    if len(token) > 10: return token[:4] + "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" + token[-4:]
    return "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


TIPS_FILE = Path("./config/tips.json")

@app.get("/api/tips")
async def get_tips():
    if TIPS_FILE.exists():
        return json.loads(TIPS_FILE.read_text()).get("tips", [])
    return []

@app.post("/api/tips")
async def add_tip(title: str = Form(...), text: str = Form(...), tags: str = Form("")):
    tips_data = {"tips": []}
    if TIPS_FILE.exists():
        tips_data = json.loads(TIPS_FILE.read_text())
    tips_data["tips"].append({"title": title, "text": text, "tags": [t.strip() for t in tags.split(",") if t.strip()]})
    os.makedirs(TIPS_FILE.parent, exist_ok=True)
    TIPS_FILE.write_text(json.dumps(tips_data, indent=2))
    return {"message": "Tip added", "count": len(tips_data["tips"])}


@app.get("/api/health")
async def health():
    db = await get_db()
    await (await db.execute("SELECT 1")).fetchone()
    return {"status": "healthy", "db": DB_PATH, "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/cam-stream")
async def cam_stream_proxy():
    """Proxy the camera MJPEG stream for the dashboard Live Cam tab."""
    cam_port = os.getenv("CAM_SERVER_PORT", "8001")
    import httpx
    from starlette.responses import StreamingResponse
    async def stream_generator():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"http://localhost:{cam_port}/stream") as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(stream_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


if os.path.isdir(DASHBOARD_DIR):
    app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
"""
3D Print Hub ÃÂÃÂ¢ÃÂÃÂÃÂÃÂ FastAPI Dashboard Backend
Serves live data from the bot's SQLite database to the web dashboard.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from api.auth import check_auth, auth_response

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for health endpoint
        if request.url.path == "/api/health":
            return await call_next(request)
        if not check_auth(request):
            return auth_response()
        return await call_next(request)


DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "./assets/prints")
DASHBOARD_DIR = os.getenv("DASHBOARD_DIR", "./dashboard")
API_PORT = int(os.getenv("API_PORT", "8000"))

_db = None

async def get_db():
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db

async def _init_tables(db):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description TEXT DEFAULT '', image_path TEXT DEFAULT '',
            tags TEXT DEFAULT '', printer TEXT DEFAULT '', material TEXT DEFAULT '',
            stl_link TEXT DEFAULT '', posted_by INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'posted',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            user_id INTEGER, username TEXT,
            rating INTEGER CHECK(rating BETWEEN 1 AND 5), text TEXT,
            message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT,
            prints_shared INTEGER DEFAULT 0, reviews_given INTEGER DEFAULT 0,
            requests_fulfilled INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS print_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0,
            username TEXT, description TEXT,
            claimed_by INTEGER DEFAULT NULL, claimed_by_username TEXT DEFAULT NULL,
            status TEXT DEFAULT 'open', message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS potd_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            featured_date TEXT DEFAULT (date('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS channel_stats (
            channel_id TEXT PRIMARY KEY, name TEXT,
            emoji TEXT DEFAULT '', message_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    await db.commit()


class PrintCreate(BaseModel):
    name: str
    description: str = ""
    material: str = ""
    printer: str = ""
    tags: str = ""
    stl_link: str = ""
    image_path: str = ""
    status: str = "draft"

class PrintUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    material: str | None = None
    printer: str | None = None
    tags: str | None = None
    stl_link: str | None = None
    image_path: str | None = None
    status: str | None = None

class ReviewCreate(BaseModel):
    print_id: int
    username: str
    rating: int = Field(ge=1, le=5)
    text: str

class RequestCreate(BaseModel):
    username: str
    description: str

class RequestUpdate(BaseModel):
    status: str | None = None
    claimed_by_username: str | None = None

class SettingsModel(BaseModel):
    bot_token: str = ""
    admin_ids: str = ""
    timezone: str = "America/New_York"
    potd_time: str = "09:00"
    tip_time: str = "12:00"
    channel_announcements: str = ""
    channel_gallery: str = ""
    channel_reviews: str = ""
    channel_tips: str = ""
    channel_requests: str = ""
    channel_polls: str = ""
    main_group: str = ""
    image_source_path: str = "./assets/prints/"
    image_source_url: str = ""

class ActivityCreate(BaseModel):
    type: str
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_db()
    yield
    if _db:
        await _db.close()

app = FastAPI(title="3D Print Hub API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/stats")
async def get_stats():
    db = await get_db()
    pc = await db.execute("SELECT COUNT(*) FROM prints")
    prints_count = (await pc.fetchone())[0]
    rc = await db.execute("SELECT COUNT(*) FROM reviews")
    reviews_count = (await rc.fetchone())[0]
    ar = await db.execute("SELECT AVG(rating) FROM reviews")
    avg_rating = (await ar.fetchone())[0]
    avg_rating = round(avg_rating, 1) if avg_rating else 0
    mc = await db.execute("SELECT COUNT(*) FROM users")
    members_count = (await mc.fetchone())[0]
    rq = await db.execute("SELECT COUNT(*) FROM print_requests")
    requests_total = (await rq.fetchone())[0]
    oq = await db.execute("SELECT COUNT(*) FROM print_requests WHERE status='open'")
    open_count = (await oq.fetchone())[0]
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    pw = await db.execute("SELECT COUNT(*) FROM prints WHERE created_at >= ?", (week_ago,))
    prints_week = (await pw.fetchone())[0]
    mw = await db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week_ago,))
    members_week = (await mw.fetchone())[0]
    return {"prints": prints_count, "prints_this_week": prints_week, "reviews": reviews_count, "avgRating": avg_rating, "members": members_count, "members_this_week": members_week, "requests": requests_total, "openRequests": open_count}


@app.get("/api/prints")
async def list_prints(search: str = "", status: str = "", limit: int = 50, offset: int = 0):
    db = await get_db()
    conditions, params = [], []
    if search:
        conditions.append("(p.name LIKE ? OR p.tags LIKE ? OR p.material LIKE ? OR p.description LIKE ?)")
        params.extend([f"%{search}%"] * 4)
    if status:
        conditions.append("p.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT p.*, COALESCE(AVG(r.rating),0) AS avg_rating, COUNT(r.id) AS review_count FROM prints p LEFT JOIN reviews r ON r.print_id=p.id {where} GROUP BY p.id ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(query, params)
    return [{**dict(row), "avg_rating": round(row["avg_rating"], 1), "review_count": row["review_count"]} for row in await cursor.fetchall()]

@app.get("/api/prints/{print_id}")
async def get_print_detail(print_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM prints WHERE id=?", (print_id,))
    row = await cursor.fetchone()
    if not row: raise HTTPException(404, "Print not found")
    avg = await db.execute("SELECT AVG(rating) FROM reviews WHERE print_id=?", (print_id,))
    avg_val = (await avg.fetchone())[0]
    rc = await db.execute("SELECT * FROM reviews WHERE print_id=? ORDER BY created_at DESC", (print_id,))
    reviews = [dict(r) for r in await rc.fetchall()]
    return {**dict(row), "avg_rating": round(avg_val, 1) if avg_val else 0, "reviews": reviews}

@app.post("/api/prints")
async def create_print(data: PrintCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO prints (name,description,material,printer,tags,stl_link,image_path) VALUES (?,?,?,?,?,?,?)", (data.name, data.description, data.material, data.printer, data.tags, data.stl_link, data.image_path))
    await db.commit()
    await _log_activity(db, "print", f"New print added: {data.name}")
    return {"id": cursor.lastrowid, "message": "Print created"}

@app.put("/api/prints/{print_id}")
async def update_print(print_id: int, data: PrintUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE prints SET {set_clause} WHERE id=?", list(fields.values()) + [print_id])
    await db.commit()
    return {"message": "Print updated"}

@app.delete("/api/prints/{print_id}")
async def delete_print(print_id: int):
    db = await get_db()
    await db.execute("DELETE FROM reviews WHERE print_id=?", (print_id,))
    await db.execute("DELETE FROM prints WHERE id=?", (print_id,))
    await db.commit()
    return {"message": "Print deleted"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    safe_name = file.filename.replace(" ", "_").replace("/", "_")
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    path = os.path.join(UPLOADS_DIR, filename)
    content = await file.read()
    with open(path, "wb") as f: f.write(content)
    return {"filename": filename, "path": path, "size": len(content)}


@app.get("/api/reviews")
async def list_reviews(limit: int = 50, offset: int = 0):
    db = await get_db()
    cursor = await db.execute("SELECT r.*, p.name AS print_name FROM reviews r LEFT JOIN prints p ON p.id=r.print_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    return [dict(row) for row in await cursor.fetchall()]

@app.get("/api/reviews/distribution")
async def review_distribution():
    db = await get_db()
    dist = {}
    for rating in range(1, 6):
        c = await db.execute("SELECT COUNT(*) FROM reviews WHERE rating=?", (rating,))
        dist[rating] = (await c.fetchone())[0]
    return dist

@app.post("/api/reviews")
async def create_review(data: ReviewCreate):
    db = await get_db()
    cursor = await db.execute("SELECT name FROM prints WHERE id=?", (data.print_id,))
    pr = await cursor.fetchone()
    if not pr: raise HTTPException(404, "Print not found")
    await db.execute("INSERT INTO reviews (print_id,username,rating,text) VALUES (?,?,?,?)", (data.print_id, data.username, data.rating, data.text))
    await db.commit()
    await _log_activity(db, "review", f"{data.username} reviewed {pr['name']} {'\u2b50'*data.rating}")
    return {"message": "Review created"}


@app.get("/api/requests")
async def list_requests(status: str = "", limit: int = 50):
    db = await get_db()
    if status:
        cursor = await db.execute("SELECT * FROM print_requests WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
    else:
        cursor = await db.execute("SELECT * FROM print_requests ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]

@app.post("/api/requests")
async def create_request(data: RequestCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO print_requests (username,description) VALUES (?,?)", (data.username, data.description))
    await db.commit()
    await _log_activity(db, "request", f"New request from {data.username}: {data.description[:60]}")
    return {"id": cursor.lastrowid, "message": "Request created"}

@app.put("/api/requests/{request_id}")
async def update_request(request_id: int, data: RequestUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    if "claimed_by_username" in fields and "status" not in fields:
        fields["status"] = "claimed"
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE print_requests SET {set_clause} WHERE id=?", list(fields.values()) + [request_id])
    await db.commit()
    if fields.get("status") == "fulfilled":
        await _log_activity(db, "request", f"Request #{request_id} fulfilled!")
    return {"message": "Request updated"}


@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 20):
    db = await get_db()
    cursor = await db.execute("SELECT *, (prints_shared*3 + reviews_given*2 + requests_fulfilled*5) AS score FROM users ORDER BY score DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]


@app.get("/api/activity")
async def get_activity(limit: int = 30):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in await cursor.fetchall()]
    now = datetime.utcnow()
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        delta = now - created
        if delta.days > 0: row["time_ago"] = f"{delta.days}d ago"
        elif delta.seconds >= 3600: row["time_ago"] = f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60: row["time_ago"] = f"{delta.seconds // 60}m ago"
        else: row["time_ago"] = "just now"
    return rows

@app.post("/api/activity")
async def create_activity(data: ActivityCreate):
    db = await get_db()
    await _log_activity(db, data.type, data.text)
    return {"message": "Activity logged"}

async def _log_activity(db, type, text):
    await db.execute("INSERT INTO activity_log (type,text) VALUES (?,?)", (type, text))
    await db.commit()


@app.get("/api/channels")
async def get_channels():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM channel_stats ORDER BY message_count DESC")
    rows = [dict(row) for row in await cursor.fetchall()]
    if not rows:
        return [
            {"channel_id": "announcements", "name": "Announcements", "emoji": "\ud83d\udce2", "message_count": 0},
            {"channel_id": "gallery", "name": "Gallery", "emoji": "\ud83d\uddbc\ufe0f", "message_count": 0},
            {"channel_id": "reviews", "name": "Reviews", "emoji": "\ud83d\udcdd", "message_count": 0},
            {"channel_id": "tips", "name": "Tips & Tricks", "emoji": "\ud83d\udca1", "message_count": 0},
            {"channel_id": "requests", "name": "Requests", "emoji": "\ud83d\ude4b", "message_count": 0},
            {"channel_id": "polls", "name": "Polls", "emoji": "\ud83d\udcca", "message_count": 0},
            {"channel_id": "general", "name": "General", "emoji": "\ud83d\udcac", "message_count": 0},
        ]
    return rows


SETTINGS_FILE = Path("./config/.env")

@app.get("/api/settings")
async def get_settings():
    if not SETTINGS_FILE.exists():
        return SettingsModel().dict()
    env = {}
    for line in SETTINGS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return {
        "bot_token": _mask_token(env.get("BOT_TOKEN", "")),
        "admin_ids": env.get("ADMIN_IDS", ""),
        "timezone": env.get("TIMEZONE", "America/New_York"),
        "potd_time": env.get("POTD_TIME", "09:00"),
        "tip_time": env.get("TIP_TIME", "12:00"),
        "channel_announcements": env.get("CHANNEL_ANNOUNCEMENTS", ""),
        "channel_gallery": env.get("CHANNEL_GALLERY", ""),
        "channel_reviews": env.get("CHANNEL_REVIEWS", ""),
        "channel_tips": env.get("CHANNEL_TIPS", ""),
        "channel_requests": env.get("CHANNEL_REQUESTS", ""),
        "channel_polls": env.get("CHANNEL_POLLS", ""),
        "main_group": env.get("MAIN_GROUP", ""),
        "image_source_path": env.get("IMAGE_SOURCE_PATH", "./assets/prints/"),
        "image_source_url": env.get("IMAGE_SOURCE_URL", ""),
    }

@app.put("/api/settings")
async def save_settings(data: SettingsModel):
    current_token = ""
    if SETTINGS_FILE.exists():
        for line in SETTINGS_FILE.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                current_token = line.split("=", 1)[1].strip()
    token = current_token if "\u2022\u2022\u2022\u2022" in data.bot_token else data.bot_token
    content = f"BOT_TOKEN={token}\nADMIN_IDS={data.admin_ids}\nCHANNEL_ANNOUNCEMENTS={data.channel_announcements}\nCHANNEL_GALLERY={data.channel_gallery}\nCHANNEL_REVIEWS={data.channel_reviews}\nCHANNEL_TIPS={data.channel_tips}\nCHANNEL_REQUESTS={data.channel_requests}\nCHANNEL_POLLS={data.channel_polls}\nMAIN_GROUP={data.main_group}\nPOTD_TIME={data.potd_time}\nTIP_TIME={data.tip_time}\nTIMEZONE={data.timezone}\nIMAGE_SOURCE_PATH={data.image_source_path}\nIMAGE_SOURCE_URL={data.image_source_url}\nDB_PATH={DB_PATH}\n"
    os.makedirs(SETTINGS_FILE.parent, exist_ok=True)
    SETTINGS_FILE.write_text(content)
    return {"message": "Settings saved"}

def _mask_token(token):
    if not token or token == "your_bot_token_here": return ""
    if len(token) > 10: return token[:4] + "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" + token[-4:]
    return "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


TIPS_FILE = Path("./config/tips.json")

@app.get("/api/tips")
async def get_tips():
    if TIPS_FILE.exists():
        return json.loads(TIPS_FILE.read_text()).get("tips", [])
    return []

@app.post("/api/tips")
async def add_tip(title: str = Form(...), text: str = Form(...), tags: str = Form("")):
    tips_data = {"tips": []}
    if TIPS_FILE.exists():
        tips_data = json.loads(TIPS_FILE.read_text())
    tips_data["tips"].append({"title": title, "text": text, "tags": [t.strip() for t in tags.split(",") if t.strip()]})
    os.makedirs(TIPS_FILE.parent, exist_ok=True)
    TIPS_FILE.write_text(json.dumps(tips_data, indent=2))
    return {"message": "Tip added", "count": len(tips_data["tips"])}


@app.get("/api/health")
async def health():
    db = await get_db()
    await (await db.execute("SELECT 1")).fetchone()
    return {"status": "healthy", "db": DB_PATH, "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/cam-stream")
async def cam_stream_proxy():
    """Proxy the camera MJPEG stream for the dashboard Live Cam tab."""
    cam_port = os.getenv("CAM_SERVER_PORT", "8001")
    import httpx
    from starlette.responses import StreamingResponse
    async def stream_generator():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"http://localhost:{cam_port}/stream") as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(stream_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


if os.path.isdir(DASHBOARD_DIR):
    app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
"""
3D Print Hub ÃÂ¢ÃÂÃÂ FastAPI Dashboard Backend
Serves live data from the bot's SQLite database to the web dashboard.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from api.auth import check_auth, auth_response

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for health endpoint
        if request.url.path == "/api/health":
            return await call_next(request)
        if not check_auth(request):
            return auth_response()
        return await call_next(request)


DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "./assets/prints")
DASHBOARD_DIR = os.getenv("DASHBOARD_DIR", "./dashboard")
API_PORT = int(os.getenv("API_PORT", "8000"))

_db = None

async def get_db():
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db

async def _init_tables(db):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description TEXT DEFAULT '', image_path TEXT DEFAULT '',
            tags TEXT DEFAULT '', printer TEXT DEFAULT '', material TEXT DEFAULT '',
            stl_link TEXT DEFAULT '', posted_by INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'posted',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            user_id INTEGER, username TEXT,
            rating INTEGER CHECK(rating BETWEEN 1 AND 5), text TEXT,
            message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT,
            prints_shared INTEGER DEFAULT 0, reviews_given INTEGER DEFAULT 0,
            requests_fulfilled INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS print_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0,
            username TEXT, description TEXT,
            claimed_by INTEGER DEFAULT NULL, claimed_by_username TEXT DEFAULT NULL,
            status TEXT DEFAULT 'open', message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS potd_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            featured_date TEXT DEFAULT (date('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS channel_stats (
            channel_id TEXT PRIMARY KEY, name TEXT,
            emoji TEXT DEFAULT '', message_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    await db.commit()


class PrintCreate(BaseModel):
    name: str
    description: str = ""
    material: str = ""
    printer: str = ""
    tags: str = ""
    stl_link: str = ""
    image_path: str = ""
    status: str = "draft"

class PrintUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    material: str | None = None
    printer: str | None = None
    tags: str | None = None
    stl_link: str | None = None
    image_path: str | None = None
    status: str | None = None

class ReviewCreate(BaseModel):
    print_id: int
    username: str
    rating: int = Field(ge=1, le=5)
    text: str

class RequestCreate(BaseModel):
    username: str
    description: str

class RequestUpdate(BaseModel):
    status: str | None = None
    claimed_by_username: str | None = None

class SettingsModel(BaseModel):
    bot_token: str = ""
    admin_ids: str = ""
    timezone: str = "America/New_York"
    potd_time: str = "09:00"
    tip_time: str = "12:00"
    channel_announcements: str = ""
    channel_gallery: str = ""
    channel_reviews: str = ""
    channel_tips: str = ""
    channel_requests: str = ""
    channel_polls: str = ""
    main_group: str = ""
    image_source_path: str = "./assets/prints/"
    image_source_url: str = ""

class ActivityCreate(BaseModel):
    type: str
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_db()
    yield
    if _db:
        await _db.close()

app = FastAPI(title="3D Print Hub API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/stats")
async def get_stats():
    db = await get_db()
    pc = await db.execute("SELECT COUNT(*) FROM prints")
    prints_count = (await pc.fetchone())[0]
    rc = await db.execute("SELECT COUNT(*) FROM reviews")
    reviews_count = (await rc.fetchone())[0]
    ar = await db.execute("SELECT AVG(rating) FROM reviews")
    avg_rating = (await ar.fetchone())[0]
    avg_rating = round(avg_rating, 1) if avg_rating else 0
    mc = await db.execute("SELECT COUNT(*) FROM users")
    members_count = (await mc.fetchone())[0]
    rq = await db.execute("SELECT COUNT(*) FROM print_requests")
    requests_total = (await rq.fetchone())[0]
    oq = await db.execute("SELECT COUNT(*) FROM print_requests WHERE status='open'")
    open_count = (await oq.fetchone())[0]
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    pw = await db.execute("SELECT COUNT(*) FROM prints WHERE created_at >= ?", (week_ago,))
    prints_week = (await pw.fetchone())[0]
    mw = await db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week_ago,))
    members_week = (await mw.fetchone())[0]
    return {"prints": prints_count, "prints_this_week": prints_week, "reviews": reviews_count, "avgRating": avg_rating, "members": members_count, "members_this_week": members_week, "requests": requests_total, "openRequests": open_count}


@app.get("/api/prints")
async def list_prints(search: str = "", status: str = "", limit: int = 50, offset: int = 0):
    db = await get_db()
    conditions, params = [], []
    if search:
        conditions.append("(p.name LIKE ? OR p.tags LIKE ? OR p.material LIKE ? OR p.description LIKE ?)")
        params.extend([f"%{search}%"] * 4)
    if status:
        conditions.append("p.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT p.*, COALESCE(AVG(r.rating),0) AS avg_rating, COUNT(r.id) AS review_count FROM prints p LEFT JOIN reviews r ON r.print_id=p.id {where} GROUP BY p.id ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(query, params)
    return [{**dict(row), "avg_rating": round(row["avg_rating"], 1), "review_count": row["review_count"]} for row in await cursor.fetchall()]

@app.get("/api/prints/{print_id}")
async def get_print_detail(print_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM prints WHERE id=?", (print_id,))
    row = await cursor.fetchone()
    if not row: raise HTTPException(404, "Print not found")
    avg = await db.execute("SELECT AVG(rating) FROM reviews WHERE print_id=?", (print_id,))
    avg_val = (await avg.fetchone())[0]
    rc = await db.execute("SELECT * FROM reviews WHERE print_id=? ORDER BY created_at DESC", (print_id,))
    reviews = [dict(r) for r in await rc.fetchall()]
    return {**dict(row), "avg_rating": round(avg_val, 1) if avg_val else 0, "reviews": reviews}

@app.post("/api/prints")
async def create_print(data: PrintCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO prints (name,description,material,printer,tags,stl_link,image_path) VALUES (?,?,?,?,?,?,?)", (data.name, data.description, data.material, data.printer, data.tags, data.stl_link, data.image_path))
    await db.commit()
    await _log_activity(db, "print", f"New print added: {data.name}")
    return {"id": cursor.lastrowid, "message": "Print created"}

@app.put("/api/prints/{print_id}")
async def update_print(print_id: int, data: PrintUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE prints SET {set_clause} WHERE id=?", list(fields.values()) + [print_id])
    await db.commit()
    return {"message": "Print updated"}

@app.delete("/api/prints/{print_id}")
async def delete_print(print_id: int):
    db = await get_db()
    await db.execute("DELETE FROM reviews WHERE print_id=?", (print_id,))
    await db.execute("DELETE FROM prints WHERE id=?", (print_id,))
    await db.commit()
    return {"message": "Print deleted"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    safe_name = file.filename.replace(" ", "_").replace("/", "_")
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    path = os.path.join(UPLOADS_DIR, filename)
    content = await file.read()
    with open(path, "wb") as f: f.write(content)
    return {"filename": filename, "path": path, "size": len(content)}


@app.get("/api/reviews")
async def list_reviews(limit: int = 50, offset: int = 0):
    db = await get_db()
    cursor = await db.execute("SELECT r.*, p.name AS print_name FROM reviews r LEFT JOIN prints p ON p.id=r.print_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    return [dict(row) for row in await cursor.fetchall()]

@app.get("/api/reviews/distribution")
async def review_distribution():
    db = await get_db()
    dist = {}
    for rating in range(1, 6):
        c = await db.execute("SELECT COUNT(*) FROM reviews WHERE rating=?", (rating,))
        dist[rating] = (await c.fetchone())[0]
    return dist

@app.post("/api/reviews")
async def create_review(data: ReviewCreate):
    db = await get_db()
    cursor = await db.execute("SELECT name FROM prints WHERE id=?", (data.print_id,))
    pr = await cursor.fetchone()
    if not pr: raise HTTPException(404, "Print not found")
    await db.execute("INSERT INTO reviews (print_id,username,rating,text) VALUES (?,?,?,?)", (data.print_id, data.username, data.rating, data.text))
    await db.commit()
    await _log_activity(db, "review", f"{data.username} reviewed {pr['name']} {'\u2b50'*data.rating}")
    return {"message": "Review created"}


@app.get("/api/requests")
async def list_requests(status: str = "", limit: int = 50):
    db = await get_db()
    if status:
        cursor = await db.execute("SELECT * FROM print_requests WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
    else:
        cursor = await db.execute("SELECT * FROM print_requests ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]

@app.post("/api/requests")
async def create_request(data: RequestCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO print_requests (username,description) VALUES (?,?)", (data.username, data.description))
    await db.commit()
    await _log_activity(db, "request", f"New request from {data.username}: {data.description[:60]}")
    return {"id": cursor.lastrowid, "message": "Request created"}

@app.put("/api/requests/{request_id}")
async def update_request(request_id: int, data: RequestUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    if "claimed_by_username" in fields and "status" not in fields:
        fields["status"] = "claimed"
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE print_requests SET {set_clause} WHERE id=?", list(fields.values()) + [request_id])
    await db.commit()
    if fields.get("status") == "fulfilled":
        await _log_activity(db, "request", f"Request #{request_id} fulfilled!")
    return {"message": "Request updated"}


@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 20):
    db = await get_db()
    cursor = await db.execute("SELECT *, (prints_shared*3 + reviews_given*2 + requests_fulfilled*5) AS score FROM users ORDER BY score DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]


@app.get("/api/activity")
async def get_activity(limit: int = 30):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in await cursor.fetchall()]
    now = datetime.utcnow()
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        delta = now - created
        if delta.days > 0: row["time_ago"] = f"{delta.days}d ago"
        elif delta.seconds >= 3600: row["time_ago"] = f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60: row["time_ago"] = f"{delta.seconds // 60}m ago"
        else: row["time_ago"] = "just now"
    return rows

@app.post("/api/activity")
async def create_activity(data: ActivityCreate):
    db = await get_db()
    await _log_activity(db, data.type, data.text)
    return {"message": "Activity logged"}

async def _log_activity(db, type, text):
    await db.execute("INSERT INTO activity_log (type,text) VALUES (?,?)", (type, text))
    await db.commit()


@app.get("/api/channels")
async def get_channels():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM channel_stats ORDER BY message_count DESC")
    rows = [dict(row) for row in await cursor.fetchall()]
    if not rows:
        return [
            {"channel_id": "announcements", "name": "Announcements", "emoji": "\ud83d\udce2", "message_count": 0},
            {"channel_id": "gallery", "name": "Gallery", "emoji": "\ud83d\uddbc\ufe0f", "message_count": 0},
            {"channel_id": "reviews", "name": "Reviews", "emoji": "\ud83d\udcdd", "message_count": 0},
            {"channel_id": "tips", "name": "Tips & Tricks", "emoji": "\ud83d\udca1", "message_count": 0},
            {"channel_id": "requests", "name": "Requests", "emoji": "\ud83d\ude4b", "message_count": 0},
            {"channel_id": "polls", "name": "Polls", "emoji": "\ud83d\udcca", "message_count": 0},
            {"channel_id": "general", "name": "General", "emoji": "\ud83d\udcac", "message_count": 0},
        ]
    return rows


SETTINGS_FILE = Path("./config/.env")

@app.get("/api/settings")
async def get_settings():
    if not SETTINGS_FILE.exists():
        return SettingsModel().dict()
    env = {}
    for line in SETTINGS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return {
        "bot_token": _mask_token(env.get("BOT_TOKEN", "")),
        "admin_ids": env.get("ADMIN_IDS", ""),
        "timezone": env.get("TIMEZONE", "America/New_York"),
        "potd_time": env.get("POTD_TIME", "09:00"),
        "tip_time": env.get("TIP_TIME", "12:00"),
        "channel_announcements": env.get("CHANNEL_ANNOUNCEMENTS", ""),
        "channel_gallery": env.get("CHANNEL_GALLERY", ""),
        "channel_reviews": env.get("CHANNEL_REVIEWS", ""),
        "channel_tips": env.get("CHANNEL_TIPS", ""),
        "channel_requests": env.get("CHANNEL_REQUESTS", ""),
        "channel_polls": env.get("CHANNEL_POLLS", ""),
        "main_group": env.get("MAIN_GROUP", ""),
        "image_source_path": env.get("IMAGE_SOURCE_PATH", "./assets/prints/"),
        "image_source_url": env.get("IMAGE_SOURCE_URL", ""),
    }

@app.put("/api/settings")
async def save_settings(data: SettingsModel):
    current_token = ""
    if SETTINGS_FILE.exists():
        for line in SETTINGS_FILE.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                current_token = line.split("=", 1)[1].strip()
    token = current_token if "\u2022\u2022\u2022\u2022" in data.bot_token else data.bot_token
    content = f"BOT_TOKEN={token}\nADMIN_IDS={data.admin_ids}\nCHANNEL_ANNOUNCEMENTS={data.channel_announcements}\nCHANNEL_GALLERY={data.channel_gallery}\nCHANNEL_REVIEWS={data.channel_reviews}\nCHANNEL_TIPS={data.channel_tips}\nCHANNEL_REQUESTS={data.channel_requests}\nCHANNEL_POLLS={data.channel_polls}\nMAIN_GROUP={data.main_group}\nPOTD_TIME={data.potd_time}\nTIP_TIME={data.tip_time}\nTIMEZONE={data.timezone}\nIMAGE_SOURCE_PATH={data.image_source_path}\nIMAGE_SOURCE_URL={data.image_source_url}\nDB_PATH={DB_PATH}\n"
    os.makedirs(SETTINGS_FILE.parent, exist_ok=True)
    SETTINGS_FILE.write_text(content)
    return {"message": "Settings saved"}

def _mask_token(token):
    if not token or token == "your_bot_token_here": return ""
    if len(token) > 10: return token[:4] + "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" + token[-4:]
    return "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


TIPS_FILE = Path("./config/tips.json")

@app.get("/api/tips")
async def get_tips():
    if TIPS_FILE.exists():
        return json.loads(TIPS_FILE.read_text()).get("tips", [])
    return []

@app.post("/api/tips")
async def add_tip(title: str = Form(...), text: str = Form(...), tags: str = Form("")):
    tips_data = {"tips": []}
    if TIPS_FILE.exists():
        tips_data = json.loads(TIPS_FILE.read_text())
    tips_data["tips"].append({"title": title, "text": text, "tags": [t.strip() for t in tags.split(",") if t.strip()]})
    os.makedirs(TIPS_FILE.parent, exist_ok=True)
    TIPS_FILE.write_text(json.dumps(tips_data, indent=2))
    return {"message": "Tip added", "count": len(tips_data["tips"])}


@app.get("/api/health")
async def health():
    db = await get_db()
    await (await db.execute("SELECT 1")).fetchone()
    return {"status": "healthy", "db": DB_PATH, "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/cam-stream")
async def cam_stream_proxy():
    """Proxy the camera MJPEG stream for the dashboard Live Cam tab."""
    cam_port = os.getenv("CAM_SERVER_PORT", "8001")
    from starlette.responses import StreamingResponse
    import httpx
    async def stream():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"http://localhost:{cam_port}/stream") as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame")


if os.path.isdir(DASHBOARD_DIR):
    app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
"""
3D Print Hub ÃÂ¢ÃÂÃÂ FastAPI Dashboard Backend
Serves live data from the bot's SQLite database to the web dashboard.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from api.auth import check_auth, auth_response

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for health endpoint
        if request.url.path == "/api/health":
            return await call_next(request)
        if not check_auth(request):
            return auth_response()
        return await call_next(request)


DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "./assets/prints")
DASHBOARD_DIR = os.getenv("DASHBOARD_DIR", "./dashboard")
API_PORT = int(os.getenv("API_PORT", "8000"))

_db = None

async def get_db():
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db

async def _init_tables(db):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description TEXT DEFAULT '', image_path TEXT DEFAULT '',
            tags TEXT DEFAULT '', printer TEXT DEFAULT '', material TEXT DEFAULT '',
            stl_link TEXT DEFAULT '', posted_by INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'posted',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            user_id INTEGER, username TEXT,
            rating INTEGER CHECK(rating BETWEEN 1 AND 5), text TEXT,
            message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT,
            prints_shared INTEGER DEFAULT 0, reviews_given INTEGER DEFAULT 0,
            requests_fulfilled INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS print_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0,
            username TEXT, description TEXT,
            claimed_by INTEGER DEFAULT NULL, claimed_by_username TEXT DEFAULT NULL,
            status TEXT DEFAULT 'open', message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS potd_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            featured_date TEXT DEFAULT (date('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS channel_stats (
            channel_id TEXT PRIMARY KEY, name TEXT,
            emoji TEXT DEFAULT '', message_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    await db.commit()


class PrintCreate(BaseModel):
    name: str
    description: str = ""
    material: str = ""
    printer: str = ""
    tags: str = ""
    stl_link: str = ""
    image_path: str = ""
    status: str = "draft"

class PrintUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    material: str | None = None
    printer: str | None = None
    tags: str | None = None
    stl_link: str | None = None
    image_path: str | None = None
    status: str | None = None

class ReviewCreate(BaseModel):
    print_id: int
    username: str
    rating: int = Field(ge=1, le=5)
    text: str

class RequestCreate(BaseModel):
    username: str
    description: str

class RequestUpdate(BaseModel):
    status: str | None = None
    claimed_by_username: str | None = None

class SettingsModel(BaseModel):
    bot_token: str = ""
    admin_ids: str = ""
    timezone: str = "America/New_York"
    potd_time: str = "09:00"
    tip_time: str = "12:00"
    channel_announcements: str = ""
    channel_gallery: str = ""
    channel_reviews: str = ""
    channel_tips: str = ""
    channel_requests: str = ""
    channel_polls: str = ""
    main_group: str = ""
    image_source_path: str = "./assets/prints/"
    image_source_url: str = ""

class ActivityCreate(BaseModel):
    type: str
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_db()
    yield
    if _db:
        await _db.close()

app = FastAPI(title="3D Print Hub API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/stats")
async def get_stats():
    db = await get_db()
    pc = await db.execute("SELECT COUNT(*) FROM prints")
    prints_count = (await pc.fetchone())[0]
    rc = await db.execute("SELECT COUNT(*) FROM reviews")
    reviews_count = (await rc.fetchone())[0]
    ar = await db.execute("SELECT AVG(rating) FROM reviews")
    avg_rating = (await ar.fetchone())[0]
    avg_rating = round(avg_rating, 1) if avg_rating else 0
    mc = await db.execute("SELECT COUNT(*) FROM users")
    members_count = (await mc.fetchone())[0]
    rq = await db.execute("SELECT COUNT(*) FROM print_requests")
    requests_total = (await rq.fetchone())[0]
    oq = await db.execute("SELECT COUNT(*) FROM print_requests WHERE status='open'")
    open_count = (await oq.fetchone())[0]
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    pw = await db.execute("SELECT COUNT(*) FROM prints WHERE created_at >= ?", (week_ago,))
    prints_week = (await pw.fetchone())[0]
    mw = await db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week_ago,))
    members_week = (await mw.fetchone())[0]
    return {"prints": prints_count, "prints_this_week": prints_week, "reviews": reviews_count, "avgRating": avg_rating, "members": members_count, "members_this_week": members_week, "requests": requests_total, "openRequests": open_count}


@app.get("/api/prints")
async def list_prints(search: str = "", status: str = "", limit: int = 50, offset: int = 0):
    db = await get_db()
    conditions, params = [], []
    if search:
        conditions.append("(p.name LIKE ? OR p.tags LIKE ? OR p.material LIKE ? OR p.description LIKE ?)")
        params.extend([f"%{search}%"] * 4)
    if status:
        conditions.append("p.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT p.*, COALESCE(AVG(r.rating),0) AS avg_rating, COUNT(r.id) AS review_count FROM prints p LEFT JOIN reviews r ON r.print_id=p.id {where} GROUP BY p.id ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(query, params)
    return [{**dict(row), "avg_rating": round(row["avg_rating"], 1), "review_count": row["review_count"]} for row in await cursor.fetchall()]

@app.get("/api/prints/{print_id}")
async def get_print_detail(print_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM prints WHERE id=?", (print_id,))
    row = await cursor.fetchone()
    if not row: raise HTTPException(404, "Print not found")
    avg = await db.execute("SELECT AVG(rating) FROM reviews WHERE print_id=?", (print_id,))
    avg_val = (await avg.fetchone())[0]
    rc = await db.execute("SELECT * FROM reviews WHERE print_id=? ORDER BY created_at DESC", (print_id,))
    reviews = [dict(r) for r in await rc.fetchall()]
    return {**dict(row), "avg_rating": round(avg_val, 1) if avg_val else 0, "reviews": reviews}

@app.post("/api/prints")
async def create_print(data: PrintCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO prints (name,description,material,printer,tags,stl_link,image_path) VALUES (?,?,?,?,?,?,?)", (data.name, data.description, data.material, data.printer, data.tags, data.stl_link, data.image_path))
    await db.commit()
    await _log_activity(db, "print", f"New print added: {data.name}")
    return {"id": cursor.lastrowid, "message": "Print created"}

@app.put("/api/prints/{print_id}")
async def update_print(print_id: int, data: PrintUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE prints SET {set_clause} WHERE id=?", list(fields.values()) + [print_id])
    await db.commit()
    return {"message": "Print updated"}

@app.delete("/api/prints/{print_id}")
async def delete_print(print_id: int):
    db = await get_db()
    await db.execute("DELETE FROM reviews WHERE print_id=?", (print_id,))
    await db.execute("DELETE FROM prints WHERE id=?", (print_id,))
    await db.commit()
    return {"message": "Print deleted"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    safe_name = file.filename.replace(" ", "_").replace("/", "_")
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    path = os.path.join(UPLOADS_DIR, filename)
    content = await file.read()
    with open(path, "wb") as f: f.write(content)
    return {"filename": filename, "path": path, "size": len(content)}


@app.get("/api/reviews")
async def list_reviews(limit: int = 50, offset: int = 0):
    db = await get_db()
    cursor = await db.execute("SELECT r.*, p.name AS print_name FROM reviews r LEFT JOIN prints p ON p.id=r.print_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    return [dict(row) for row in await cursor.fetchall()]

@app.get("/api/reviews/distribution")
async def review_distribution():
    db = await get_db()
    dist = {}
    for rating in range(1, 6):
        c = await db.execute("SELECT COUNT(*) FROM reviews WHERE rating=?", (rating,))
        dist[rating] = (await c.fetchone())[0]
    return dist

@app.post("/api/reviews")
async def create_review(data: ReviewCreate):
    db = await get_db()
    cursor = await db.execute("SELECT name FROM prints WHERE id=?", (data.print_id,))
    pr = await cursor.fetchone()
    if not pr: raise HTTPException(404, "Print not found")
    await db.execute("INSERT INTO reviews (print_id,username,rating,text) VALUES (?,?,?,?)", (data.print_id, data.username, data.rating, data.text))
    await db.commit()
    await _log_activity(db, "review", f"{data.username} reviewed {pr['name']} {'\u2b50'*data.rating}")
    return {"message": "Review created"}


@app.get("/api/requests")
async def list_requests(status: str = "", limit: int = 50):
    db = await get_db()
    if status:
        cursor = await db.execute("SELECT * FROM print_requests WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
    else:
        cursor = await db.execute("SELECT * FROM print_requests ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]

@app.post("/api/requests")
async def create_request(data: RequestCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO print_requests (username,description) VALUES (?,?)", (data.username, data.description))
    await db.commit()
    await _log_activity(db, "request", f"New request from {data.username}: {data.description[:60]}")
    return {"id": cursor.lastrowid, "message": "Request created"}

@app.put("/api/requests/{request_id}")
async def update_request(request_id: int, data: RequestUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    if "claimed_by_username" in fields and "status" not in fields:
        fields["status"] = "claimed"
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE print_requests SET {set_clause} WHERE id=?", list(fields.values()) + [request_id])
    await db.commit()
    if fields.get("status") == "fulfilled":
        await _log_activity(db, "request", f"Request #{request_id} fulfilled!")
    return {"message": "Request updated"}


@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 20):
    db = await get_db()
    cursor = await db.execute("SELECT *, (prints_shared*3 + reviews_given*2 + requests_fulfilled*5) AS score FROM users ORDER BY score DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]


@app.get("/api/activity")
async def get_activity(limit: int = 30):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in await cursor.fetchall()]
    now = datetime.utcnow()
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        delta = now - created
        if delta.days > 0: row["time_ago"] = f"{delta.days}d ago"
        elif delta.seconds >= 3600: row["time_ago"] = f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60: row["time_ago"] = f"{delta.seconds // 60}m ago"
        else: row["time_ago"] = "just now"
    return rows

@app.post("/api/activity")
async def create_activity(data: ActivityCreate):
    db = await get_db()
    await _log_activity(db, data.type, data.text)
    return {"message": "Activity logged"}

async def _log_activity(db, type, text):
    await db.execute("INSERT INTO activity_log (type,text) VALUES (?,?)", (type, text))
    await db.commit()


@app.get("/api/channels")
async def get_channels():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM channel_stats ORDER BY message_count DESC")
    rows = [dict(row) for row in await cursor.fetchall()]
    if not rows:
        return [
            {"channel_id": "announcements", "name": "Announcements", "emoji": "\ud83d\udce2", "message_count": 0},
            {"channel_id": "gallery", "name": "Gallery", "emoji": "\ud83d\uddbc\ufe0f", "message_count": 0},
            {"channel_id": "reviews", "name": "Reviews", "emoji": "\ud83d\udcdd", "message_count": 0},
            {"channel_id": "tips", "name": "Tips & Tricks", "emoji": "\ud83d\udca1", "message_count": 0},
            {"channel_id": "requests", "name": "Requests", "emoji": "\ud83d\ude4b", "message_count": 0},
            {"channel_id": "polls", "name": "Polls", "emoji": "\ud83d\udcca", "message_count": 0},
            {"channel_id": "general", "name": "General", "emoji": "\ud83d\udcac", "message_count": 0},
        ]
    return rows


SETTINGS_FILE = Path("./config/.env")

@app.get("/api/settings")
async def get_settings():
    if not SETTINGS_FILE.exists():
        return SettingsModel().dict()
    env = {}
    for line in SETTINGS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return {
        "bot_token": _mask_token(env.get("BOT_TOKEN", "")),
        "admin_ids": env.get("ADMIN_IDS", ""),
        "timezone": env.get("TIMEZONE", "America/New_York"),
        "potd_time": env.get("POTD_TIME", "09:00"),
        "tip_time": env.get("TIP_TIME", "12:00"),
        "channel_announcements": env.get("CHANNEL_ANNOUNCEMENTS", ""),
        "channel_gallery": env.get("CHANNEL_GALLERY", ""),
        "channel_reviews": env.get("CHANNEL_REVIEWS", ""),
        "channel_tips": env.get("CHANNEL_TIPS", ""),
        "channel_requests": env.get("CHANNEL_REQUESTS", ""),
        "channel_polls": env.get("CHANNEL_POLLS", ""),
        "main_group": env.get("MAIN_GROUP", ""),
        "image_source_path": env.get("IMAGE_SOURCE_PATH", "./assets/prints/"),
        "image_source_url": env.get("IMAGE_SOURCE_URL", ""),
    }

@app.put("/api/settings")
async def save_settings(data: SettingsModel):
    current_token = ""
    if SETTINGS_FILE.exists():
        for line in SETTINGS_FILE.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                current_token = line.split("=", 1)[1].strip()
    token = current_token if "\u2022\u2022\u2022\u2022" in data.bot_token else data.bot_token
    content = f"BOT_TOKEN={token}\nADMIN_IDS={data.admin_ids}\nCHANNEL_ANNOUNCEMENTS={data.channel_announcements}\nCHANNEL_GALLERY={data.channel_gallery}\nCHANNEL_REVIEWS={data.channel_reviews}\nCHANNEL_TIPS={data.channel_tips}\nCHANNEL_REQUESTS={data.channel_requests}\nCHANNEL_POLLS={data.channel_polls}\nMAIN_GROUP={data.main_group}\nPOTD_TIME={data.potd_time}\nTIP_TIME={data.tip_time}\nTIMEZONE={data.timezone}\nIMAGE_SOURCE_PATH={data.image_source_path}\nIMAGE_SOURCE_URL={data.image_source_url}\nDB_PATH={DB_PATH}\n"
    os.makedirs(SETTINGS_FILE.parent, exist_ok=True)
    SETTINGS_FILE.write_text(content)
    return {"message": "Settings saved"}

def _mask_token(token):
    if not token or token == "your_bot_token_here": return ""
    if len(token) > 10: return token[:4] + "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" + token[-4:]
    return "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


TIPS_FILE = Path("./config/tips.json")

@app.get("/api/tips")
async def get_tips():
    if TIPS_FILE.exists():
        return json.loads(TIPS_FILE.read_text()).get("tips", [])
    return []

@app.post("/api/tips")
async def add_tip(title: str = Form(...), text: str = Form(...), tags: str = Form("")):
    tips_data = {"tips": []}
    if TIPS_FILE.exists():
        tips_data = json.loads(TIPS_FILE.read_text())
    tips_data["tips"].append({"title": title, "text": text, "tags": [t.strip() for t in tags.split(",") if t.strip()]})
    os.makedirs(TIPS_FILE.parent, exist_ok=True)
    TIPS_FILE.write_text(json.dumps(tips_data, indent=2))
    return {"message": "Tip added", "count": len(tips_data["tips"])}


@app.get("/api/health")
async def health():
    db = await get_db()
    await (await db.execute("SELECT 1")).fetchone()
    return {"status": "healthy", "db": DB_PATH, "timestamp": datetime.utcnow().isoformat()}


if os.path.isdir(DASHBOARD_DIR):
    
@app.get("/api/cam-stream")
async def cam_stream_proxy():
    """Proxy the camera MJPEG stream for the dashboard Live Cam tab."""
    cam_port = os.getenv("CAM_SERVER_PORT", "8001")
    import httpx
    from starlette.responses import StreamingResponse
    async def stream_generator():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"http://localhost:{cam_port}/stream") as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(stream_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
"""
3D Print Hub Ã¢ÂÂ FastAPI Dashboard Backend
Serves live data from the bot's SQLite database to the web dashboard.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from api.auth import check_auth, auth_response

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for health endpoint
        if request.url.path == "/api/health":
            return await call_next(request)
        if not check_auth(request):
            return auth_response()
        return await call_next(request)


DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "./assets/prints")
DASHBOARD_DIR = os.getenv("DASHBOARD_DIR", "./dashboard")
API_PORT = int(os.getenv("API_PORT", "8000"))

_db = None

async def get_db():
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db

async def _init_tables(db):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description TEXT DEFAULT '', image_path TEXT DEFAULT '',
            tags TEXT DEFAULT '', printer TEXT DEFAULT '', material TEXT DEFAULT '',
            stl_link TEXT DEFAULT '', posted_by INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'posted',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            user_id INTEGER, username TEXT,
            rating INTEGER CHECK(rating BETWEEN 1 AND 5), text TEXT,
            message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT,
            prints_shared INTEGER DEFAULT 0, reviews_given INTEGER DEFAULT 0,
            requests_fulfilled INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS print_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0,
            username TEXT, description TEXT,
            claimed_by INTEGER DEFAULT NULL, claimed_by_username TEXT DEFAULT NULL,
            status TEXT DEFAULT 'open', message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS potd_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            featured_date TEXT DEFAULT (date('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS channel_stats (
            channel_id TEXT PRIMARY KEY, name TEXT,
            emoji TEXT DEFAULT '', message_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    await db.commit()


class PrintCreate(BaseModel):
    name: str
    description: str = ""
    material: str = ""
    printer: str = ""
    tags: str = ""
    stl_link: str = ""
    image_path: str = ""
    status: str = "draft"

class PrintUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    material: str | None = None
    printer: str | None = None
    tags: str | None = None
    stl_link: str | None = None
    image_path: str | None = None
    status: str | None = None

class ReviewCreate(BaseModel):
    print_id: int
    username: str
    rating: int = Field(ge=1, le=5)
    text: str

class RequestCreate(BaseModel):
    username: str
    description: str

class RequestUpdate(BaseModel):
    status: str | None = None
    claimed_by_username: str | None = None

class SettingsModel(BaseModel):
    bot_token: str = ""
    admin_ids: str = ""
    timezone: str = "America/New_York"
    potd_time: str = "09:00"
    tip_time: str = "12:00"
    channel_announcements: str = ""
    channel_gallery: str = ""
    channel_reviews: str = ""
    channel_tips: str = ""
    channel_requests: str = ""
    channel_polls: str = ""
    main_group: str = ""
    image_source_path: str = "./assets/prints/"
    image_source_url: str = ""

class ActivityCreate(BaseModel):
    type: str
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_db()
    yield
    if _db:
        await _db.close()

app = FastAPI(title="3D Print Hub API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/stats")
async def get_stats():
    db = await get_db()
    pc = await db.execute("SELECT COUNT(*) FROM prints")
    prints_count = (await pc.fetchone())[0]
    rc = await db.execute("SELECT COUNT(*) FROM reviews")
    reviews_count = (await rc.fetchone())[0]
    ar = await db.execute("SELECT AVG(rating) FROM reviews")
    avg_rating = (await ar.fetchone())[0]
    avg_rating = round(avg_rating, 1) if avg_rating else 0
    mc = await db.execute("SELECT COUNT(*) FROM users")
    members_count = (await mc.fetchone())[0]
    rq = await db.execute("SELECT COUNT(*) FROM print_requests")
    requests_total = (await rq.fetchone())[0]
    oq = await db.execute("SELECT COUNT(*) FROM print_requests WHERE status='open'")
    open_count = (await oq.fetchone())[0]
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    pw = await db.execute("SELECT COUNT(*) FROM prints WHERE created_at >= ?", (week_ago,))
    prints_week = (await pw.fetchone())[0]
    mw = await db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week_ago,))
    members_week = (await mw.fetchone())[0]
    return {"prints": prints_count, "prints_this_week": prints_week, "reviews": reviews_count, "avgRating": avg_rating, "members": members_count, "members_this_week": members_week, "requests": requests_total, "openRequests": open_count}


@app.get("/api/prints")
async def list_prints(search: str = "", status: str = "", limit: int = 50, offset: int = 0):
    db = await get_db()
    conditions, params = [], []
    if search:
        conditions.append("(p.name LIKE ? OR p.tags LIKE ? OR p.material LIKE ? OR p.description LIKE ?)")
        params.extend([f"%{search}%"] * 4)
    if status:
        conditions.append("p.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT p.*, COALESCE(AVG(r.rating),0) AS avg_rating, COUNT(r.id) AS review_count FROM prints p LEFT JOIN reviews r ON r.print_id=p.id {where} GROUP BY p.id ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(query, params)
    return [{**dict(row), "avg_rating": round(row["avg_rating"], 1), "review_count": row["review_count"]} for row in await cursor.fetchall()]

@app.get("/api/prints/{print_id}")
async def get_print_detail(print_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM prints WHERE id=?", (print_id,))
    row = await cursor.fetchone()
    if not row: raise HTTPException(404, "Print not found")
    avg = await db.execute("SELECT AVG(rating) FROM reviews WHERE print_id=?", (print_id,))
    avg_val = (await avg.fetchone())[0]
    rc = await db.execute("SELECT * FROM reviews WHERE print_id=? ORDER BY created_at DESC", (print_id,))
    reviews = [dict(r) for r in await rc.fetchall()]
    return {**dict(row), "avg_rating": round(avg_val, 1) if avg_val else 0, "reviews": reviews}

@app.post("/api/prints")
async def create_print(data: PrintCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO prints (name,description,material,printer,tags,stl_link,image_path) VALUES (?,?,?,?,?,?,?)", (data.name, data.description, data.material, data.printer, data.tags, data.stl_link, data.image_path))
    await db.commit()
    await _log_activity(db, "print", f"New print added: {data.name}")
    return {"id": cursor.lastrowid, "message": "Print created"}

@app.put("/api/prints/{print_id}")
async def update_print(print_id: int, data: PrintUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE prints SET {set_clause} WHERE id=?", list(fields.values()) + [print_id])
    await db.commit()
    return {"message": "Print updated"}

@app.delete("/api/prints/{print_id}")
async def delete_print(print_id: int):
    db = await get_db()
    await db.execute("DELETE FROM reviews WHERE print_id=?", (print_id,))
    await db.execute("DELETE FROM prints WHERE id=?", (print_id,))
    await db.commit()
    return {"message": "Print deleted"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    safe_name = file.filename.replace(" ", "_").replace("/", "_")
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    path = os.path.join(UPLOADS_DIR, filename)
    content = await file.read()
    with open(path, "wb") as f: f.write(content)
    return {"filename": filename, "path": path, "size": len(content)}


@app.get("/api/reviews")
async def list_reviews(limit: int = 50, offset: int = 0):
    db = await get_db()
    cursor = await db.execute("SELECT r.*, p.name AS print_name FROM reviews r LEFT JOIN prints p ON p.id=r.print_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    return [dict(row) for row in await cursor.fetchall()]

@app.get("/api/reviews/distribution")
async def review_distribution():
    db = await get_db()
    dist = {}
    for rating in range(1, 6):
        c = await db.execute("SELECT COUNT(*) FROM reviews WHERE rating=?", (rating,))
        dist[rating] = (await c.fetchone())[0]
    return dist

@app.post("/api/reviews")
async def create_review(data: ReviewCreate):
    db = await get_db()
    cursor = await db.execute("SELECT name FROM prints WHERE id=?", (data.print_id,))
    pr = await cursor.fetchone()
    if not pr: raise HTTPException(404, "Print not found")
    await db.execute("INSERT INTO reviews (print_id,username,rating,text) VALUES (?,?,?,?)", (data.print_id, data.username, data.rating, data.text))
    await db.commit()
    await _log_activity(db, "review", f"{data.username} reviewed {pr['name']} {'\u2b50'*data.rating}")
    return {"message": "Review created"}


@app.get("/api/requests")
async def list_requests(status: str = "", limit: int = 50):
    db = await get_db()
    if status:
        cursor = await db.execute("SELECT * FROM print_requests WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
    else:
        cursor = await db.execute("SELECT * FROM print_requests ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]

@app.post("/api/requests")
async def create_request(data: RequestCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO print_requests (username,description) VALUES (?,?)", (data.username, data.description))
    await db.commit()
    await _log_activity(db, "request", f"New request from {data.username}: {data.description[:60]}")
    return {"id": cursor.lastrowid, "message": "Request created"}

@app.put("/api/requests/{request_id}")
async def update_request(request_id: int, data: RequestUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    if "claimed_by_username" in fields and "status" not in fields:
        fields["status"] = "claimed"
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE print_requests SET {set_clause} WHERE id=?", list(fields.values()) + [request_id])
    await db.commit()
    if fields.get("status") == "fulfilled":
        await _log_activity(db, "request", f"Request #{request_id} fulfilled!")
    return {"message": "Request updated"}


@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 20):
    db = await get_db()
    cursor = await db.execute("SELECT *, (prints_shared*3 + reviews_given*2 + requests_fulfilled*5) AS score FROM users ORDER BY score DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]


@app.get("/api/activity")
async def get_activity(limit: int = 30):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in await cursor.fetchall()]
    now = datetime.utcnow()
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        delta = now - created
        if delta.days > 0: row["time_ago"] = f"{delta.days}d ago"
        elif delta.seconds >= 3600: row["time_ago"] = f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60: row["time_ago"] = f"{delta.seconds // 60}m ago"
        else: row["time_ago"] = "just now"
    return rows

@app.post("/api/activity")
async def create_activity(data: ActivityCreate):
    db = await get_db()
    await _log_activity(db, data.type, data.text)
    return {"message": "Activity logged"}

async def _log_activity(db, type, text):
    await db.execute("INSERT INTO activity_log (type,text) VALUES (?,?)", (type, text))
    await db.commit()


@app.get("/api/channels")
async def get_channels():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM channel_stats ORDER BY message_count DESC")
    rows = [dict(row) for row in await cursor.fetchall()]
    if not rows:
        return [
            {"channel_id": "announcements", "name": "Announcements", "emoji": "\ud83d\udce2", "message_count": 0},
            {"channel_id": "gallery", "name": "Gallery", "emoji": "\ud83d\uddbc\ufe0f", "message_count": 0},
            {"channel_id": "reviews", "name": "Reviews", "emoji": "\ud83d\udcdd", "message_count": 0},
            {"channel_id": "tips", "name": "Tips & Tricks", "emoji": "\ud83d\udca1", "message_count": 0},
            {"channel_id": "requests", "name": "Requests", "emoji": "\ud83d\ude4b", "message_count": 0},
            {"channel_id": "polls", "name": "Polls", "emoji": "\ud83d\udcca", "message_count": 0},
            {"channel_id": "general", "name": "General", "emoji": "\ud83d\udcac", "message_count": 0},
        ]
    return rows


SETTINGS_FILE = Path("./config/.env")

@app.get("/api/settings")
async def get_settings():
    if not SETTINGS_FILE.exists():
        return SettingsModel().dict()
    env = {}
    for line in SETTINGS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return {
        "bot_token": _mask_token(env.get("BOT_TOKEN", "")),
        "admin_ids": env.get("ADMIN_IDS", ""),
        "timezone": env.get("TIMEZONE", "America/New_York"),
        "potd_time": env.get("POTD_TIME", "09:00"),
        "tip_time": env.get("TIP_TIME", "12:00"),
        "channel_announcements": env.get("CHANNEL_ANNOUNCEMENTS", ""),
        "channel_gallery": env.get("CHANNEL_GALLERY", ""),
        "channel_reviews": env.get("CHANNEL_REVIEWS", ""),
        "channel_tips": env.get("CHANNEL_TIPS", ""),
        "channel_requests": env.get("CHANNEL_REQUESTS", ""),
        "channel_polls": env.get("CHANNEL_POLLS", ""),
        "main_group": env.get("MAIN_GROUP", ""),
        "image_source_path": env.get("IMAGE_SOURCE_PATH", "./assets/prints/"),
        "image_source_url": env.get("IMAGE_SOURCE_URL", ""),
    }

@app.put("/api/settings")
async def save_settings(data: SettingsModel):
    current_token = ""
    if SETTINGS_FILE.exists():
        for line in SETTINGS_FILE.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                current_token = line.split("=", 1)[1].strip()
    token = current_token if "\u2022\u2022\u2022\u2022" in data.bot_token else data.bot_token
    content = f"BOT_TOKEN={token}\nADMIN_IDS={data.admin_ids}\nCHANNEL_ANNOUNCEMENTS={data.channel_announcements}\nCHANNEL_GALLERY={data.channel_gallery}\nCHANNEL_REVIEWS={data.channel_reviews}\nCHANNEL_TIPS={data.channel_tips}\nCHANNEL_REQUESTS={data.channel_requests}\nCHANNEL_POLLS={data.channel_polls}\nMAIN_GROUP={data.main_group}\nPOTD_TIME={data.potd_time}\nTIP_TIME={data.tip_time}\nTIMEZONE={data.timezone}\nIMAGE_SOURCE_PATH={data.image_source_path}\nIMAGE_SOURCE_URL={data.image_source_url}\nDB_PATH={DB_PATH}\n"
    os.makedirs(SETTINGS_FILE.parent, exist_ok=True)
    SETTINGS_FILE.write_text(content)
    return {"message": "Settings saved"}

def _mask_token(token):
    if not token or token == "your_bot_token_here": return ""
    if len(token) > 10: return token[:4] + "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" + token[-4:]
    return "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


TIPS_FILE = Path("./config/tips.json")

@app.get("/api/tips")
async def get_tips():
    if TIPS_FILE.exists():
        return json.loads(TIPS_FILE.read_text()).get("tips", [])
    return []

@app.post("/api/tips")
async def add_tip(title: str = Form(...), text: str = Form(...), tags: str = Form("")):
    tips_data = {"tips": []}
    if TIPS_FILE.exists():
        tips_data = json.loads(TIPS_FILE.read_text())
    tips_data["tips"].append({"title": title, "text": text, "tags": [t.strip() for t in tags.split(",") if t.strip()]})
    os.makedirs(TIPS_FILE.parent, exist_ok=True)
    TIPS_FILE.write_text(json.dumps(tips_data, indent=2))
    return {"message": "Tip added", "count": len(tips_data["tips"])}


@app.get("/api/health")
async def health():
    db = await get_db()
    await (await db.execute("SELECT 1")).fetchone()
    return {"status": "healthy", "db": DB_PATH, "timestamp": datetime.utcnow().isoformat()}


if os.path.isdir(DASHBOARD_DIR):
    
@app.get("/api/cam-stream")
async def cam_stream_proxy():
    """Proxy the camera MJPEG stream for the dashboard Live Cam tab."""
    cam_port = os.getenv("CAM_SERVER_PORT", "8001")
    from starlette.responses import StreamingResponse
    import httpx
    async def stream():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"http://localhost:{cam_port}/stream") as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame")


app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
"""
3D Print Hub ÃÂ¢ÃÂÃÂ FastAPI Dashboard Backend
Serves live data from the bot's SQLite database to the web dashboard.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from api.auth import check_auth, auth_response

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for health endpoint
        if request.url.path == "/api/health":
            return await call_next(request)
        if not check_auth(request):
            return auth_response()
        return await call_next(request)


DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "./assets/prints")
DASHBOARD_DIR = os.getenv("DASHBOARD_DIR", "./dashboard")
API_PORT = int(os.getenv("API_PORT", "8000"))

_db = None

async def get_db():
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db

async def _init_tables(db):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description TEXT DEFAULT '', image_path TEXT DEFAULT '',
            tags TEXT DEFAULT '', printer TEXT DEFAULT '', material TEXT DEFAULT '',
            stl_link TEXT DEFAULT '', posted_by INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'posted',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            user_id INTEGER, username TEXT,
            rating INTEGER CHECK(rating BETWEEN 1 AND 5), text TEXT,
            message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT,
            prints_shared INTEGER DEFAULT 0, reviews_given INTEGER DEFAULT 0,
            requests_fulfilled INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS print_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0,
            username TEXT, description TEXT,
            claimed_by INTEGER DEFAULT NULL, claimed_by_username TEXT DEFAULT NULL,
            status TEXT DEFAULT 'open', message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS potd_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            featured_date TEXT DEFAULT (date('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS channel_stats (
            channel_id TEXT PRIMARY KEY, name TEXT,
            emoji TEXT DEFAULT '', message_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    await db.commit()


class PrintCreate(BaseModel):
    name: str
    description: str = ""
    material: str = ""
    printer: str = ""
    tags: str = ""
    stl_link: str = ""
    image_path: str = ""
    status: str = "draft"

class PrintUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    material: str | None = None
    printer: str | None = None
    tags: str | None = None
    stl_link: str | None = None
    image_path: str | None = None
    status: str | None = None

class ReviewCreate(BaseModel):
    print_id: int
    username: str
    rating: int = Field(ge=1, le=5)
    text: str

class RequestCreate(BaseModel):
    username: str
    description: str

class RequestUpdate(BaseModel):
    status: str | None = None
    claimed_by_username: str | None = None

class SettingsModel(BaseModel):
    bot_token: str = ""
    admin_ids: str = ""
    timezone: str = "America/New_York"
    potd_time: str = "09:00"
    tip_time: str = "12:00"
    channel_announcements: str = ""
    channel_gallery: str = ""
    channel_reviews: str = ""
    channel_tips: str = ""
    channel_requests: str = ""
    channel_polls: str = ""
    main_group: str = ""
    image_source_path: str = "./assets/prints/"
    image_source_url: str = ""

class ActivityCreate(BaseModel):
    type: str
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_db()
    yield
    if _db:
        await _db.close()

app = FastAPI(title="3D Print Hub API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/stats")
async def get_stats():
    db = await get_db()
    pc = await db.execute("SELECT COUNT(*) FROM prints")
    prints_count = (await pc.fetchone())[0]
    rc = await db.execute("SELECT COUNT(*) FROM reviews")
    reviews_count = (await rc.fetchone())[0]
    ar = await db.execute("SELECT AVG(rating) FROM reviews")
    avg_rating = (await ar.fetchone())[0]
    avg_rating = round(avg_rating, 1) if avg_rating else 0
    mc = await db.execute("SELECT COUNT(*) FROM users")
    members_count = (await mc.fetchone())[0]
    rq = await db.execute("SELECT COUNT(*) FROM print_requests")
    requests_total = (await rq.fetchone())[0]
    oq = await db.execute("SELECT COUNT(*) FROM print_requests WHERE status='open'")
    open_count = (await oq.fetchone())[0]
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    pw = await db.execute("SELECT COUNT(*) FROM prints WHERE created_at >= ?", (week_ago,))
    prints_week = (await pw.fetchone())[0]
    mw = await db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week_ago,))
    members_week = (await mw.fetchone())[0]
    return {"prints": prints_count, "prints_this_week": prints_week, "reviews": reviews_count, "avgRating": avg_rating, "members": members_count, "members_this_week": members_week, "requests": requests_total, "openRequests": open_count}


@app.get("/api/prints")
async def list_prints(search: str = "", status: str = "", limit: int = 50, offset: int = 0):
    db = await get_db()
    conditions, params = [], []
    if search:
        conditions.append("(p.name LIKE ? OR p.tags LIKE ? OR p.material LIKE ? OR p.description LIKE ?)")
        params.extend([f"%{search}%"] * 4)
    if status:
        conditions.append("p.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT p.*, COALESCE(AVG(r.rating),0) AS avg_rating, COUNT(r.id) AS review_count FROM prints p LEFT JOIN reviews r ON r.print_id=p.id {where} GROUP BY p.id ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(query, params)
    return [{**dict(row), "avg_rating": round(row["avg_rating"], 1), "review_count": row["review_count"]} for row in await cursor.fetchall()]

@app.get("/api/prints/{print_id}")
async def get_print_detail(print_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM prints WHERE id=?", (print_id,))
    row = await cursor.fetchone()
    if not row: raise HTTPException(404, "Print not found")
    avg = await db.execute("SELECT AVG(rating) FROM reviews WHERE print_id=?", (print_id,))
    avg_val = (await avg.fetchone())[0]
    rc = await db.execute("SELECT * FROM reviews WHERE print_id=? ORDER BY created_at DESC", (print_id,))
    reviews = [dict(r) for r in await rc.fetchall()]
    return {**dict(row), "avg_rating": round(avg_val, 1) if avg_val else 0, "reviews": reviews}

@app.post("/api/prints")
async def create_print(data: PrintCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO prints (name,description,material,printer,tags,stl_link,image_path) VALUES (?,?,?,?,?,?,?)", (data.name, data.description, data.material, data.printer, data.tags, data.stl_link, data.image_path))
    await db.commit()
    await _log_activity(db, "print", f"New print added: {data.name}")
    return {"id": cursor.lastrowid, "message": "Print created"}

@app.put("/api/prints/{print_id}")
async def update_print(print_id: int, data: PrintUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE prints SET {set_clause} WHERE id=?", list(fields.values()) + [print_id])
    await db.commit()
    return {"message": "Print updated"}

@app.delete("/api/prints/{print_id}")
async def delete_print(print_id: int):
    db = await get_db()
    await db.execute("DELETE FROM reviews WHERE print_id=?", (print_id,))
    await db.execute("DELETE FROM prints WHERE id=?", (print_id,))
    await db.commit()
    return {"message": "Print deleted"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    safe_name = file.filename.replace(" ", "_").replace("/", "_")
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    path = os.path.join(UPLOADS_DIR, filename)
    content = await file.read()
    with open(path, "wb") as f: f.write(content)
    return {"filename": filename, "path": path, "size": len(content)}


@app.get("/api/reviews")
async def list_reviews(limit: int = 50, offset: int = 0):
    db = await get_db()
    cursor = await db.execute("SELECT r.*, p.name AS print_name FROM reviews r LEFT JOIN prints p ON p.id=r.print_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    return [dict(row) for row in await cursor.fetchall()]

@app.get("/api/reviews/distribution")
async def review_distribution():
    db = await get_db()
    dist = {}
    for rating in range(1, 6):
        c = await db.execute("SELECT COUNT(*) FROM reviews WHERE rating=?", (rating,))
        dist[rating] = (await c.fetchone())[0]
    return dist

@app.post("/api/reviews")
async def create_review(data: ReviewCreate):
    db = await get_db()
    cursor = await db.execute("SELECT name FROM prints WHERE id=?", (data.print_id,))
    pr = await cursor.fetchone()
    if not pr: raise HTTPException(404, "Print not found")
    await db.execute("INSERT INTO reviews (print_id,username,rating,text) VALUES (?,?,?,?)", (data.print_id, data.username, data.rating, data.text))
    await db.commit()
    await _log_activity(db, "review", f"{data.username} reviewed {pr['name']} {'\u2b50'*data.rating}")
    return {"message": "Review created"}


@app.get("/api/requests")
async def list_requests(status: str = "", limit: int = 50):
    db = await get_db()
    if status:
        cursor = await db.execute("SELECT * FROM print_requests WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
    else:
        cursor = await db.execute("SELECT * FROM print_requests ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]

@app.post("/api/requests")
async def create_request(data: RequestCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO print_requests (username,description) VALUES (?,?)", (data.username, data.description))
    await db.commit()
    await _log_activity(db, "request", f"New request from {data.username}: {data.description[:60]}")
    return {"id": cursor.lastrowid, "message": "Request created"}

@app.put("/api/requests/{request_id}")
async def update_request(request_id: int, data: RequestUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    if "claimed_by_username" in fields and "status" not in fields:
        fields["status"] = "claimed"
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE print_requests SET {set_clause} WHERE id=?", list(fields.values()) + [request_id])
    await db.commit()
    if fields.get("status") == "fulfilled":
        await _log_activity(db, "request", f"Request #{request_id} fulfilled!")
    return {"message": "Request updated"}


@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 20):
    db = await get_db()
    cursor = await db.execute("SELECT *, (prints_shared*3 + reviews_given*2 + requests_fulfilled*5) AS score FROM users ORDER BY score DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]


@app.get("/api/activity")
async def get_activity(limit: int = 30):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in await cursor.fetchall()]
    now = datetime.utcnow()
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        delta = now - created
        if delta.days > 0: row["time_ago"] = f"{delta.days}d ago"
        elif delta.seconds >= 3600: row["time_ago"] = f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60: row["time_ago"] = f"{delta.seconds // 60}m ago"
        else: row["time_ago"] = "just now"
    return rows

@app.post("/api/activity")
async def create_activity(data: ActivityCreate):
    db = await get_db()
    await _log_activity(db, data.type, data.text)
    return {"message": "Activity logged"}

async def _log_activity(db, type, text):
    await db.execute("INSERT INTO activity_log (type,text) VALUES (?,?)", (type, text))
    await db.commit()


@app.get("/api/channels")
async def get_channels():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM channel_stats ORDER BY message_count DESC")
    rows = [dict(row) for row in await cursor.fetchall()]
    if not rows:
        return [
            {"channel_id": "announcements", "name": "Announcements", "emoji": "\ud83d\udce2", "message_count": 0},
            {"channel_id": "gallery", "name": "Gallery", "emoji": "\ud83d\uddbc\ufe0f", "message_count": 0},
            {"channel_id": "reviews", "name": "Reviews", "emoji": "\ud83d\udcdd", "message_count": 0},
            {"channel_id": "tips", "name": "Tips & Tricks", "emoji": "\ud83d\udca1", "message_count": 0},
            {"channel_id": "requests", "name": "Requests", "emoji": "\ud83d\ude4b", "message_count": 0},
            {"channel_id": "polls", "name": "Polls", "emoji": "\ud83d\udcca", "message_count": 0},
            {"channel_id": "general", "name": "General", "emoji": "\ud83d\udcac", "message_count": 0},
        ]
    return rows


SETTINGS_FILE = Path("./config/.env")

@app.get("/api/settings")
async def get_settings():
    if not SETTINGS_FILE.exists():
        return SettingsModel().dict()
    env = {}
    for line in SETTINGS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return {
        "bot_token": _mask_token(env.get("BOT_TOKEN", "")),
        "admin_ids": env.get("ADMIN_IDS", ""),
        "timezone": env.get("TIMEZONE", "America/New_York"),
        "potd_time": env.get("POTD_TIME", "09:00"),
        "tip_time": env.get("TIP_TIME", "12:00"),
        "channel_announcements": env.get("CHANNEL_ANNOUNCEMENTS", ""),
        "channel_gallery": env.get("CHANNEL_GALLERY", ""),
        "channel_reviews": env.get("CHANNEL_REVIEWS", ""),
        "channel_tips": env.get("CHANNEL_TIPS", ""),
        "channel_requests": env.get("CHANNEL_REQUESTS", ""),
        "channel_polls": env.get("CHANNEL_POLLS", ""),
        "main_group": env.get("MAIN_GROUP", ""),
        "image_source_path": env.get("IMAGE_SOURCE_PATH", "./assets/prints/"),
        "image_source_url": env.get("IMAGE_SOURCE_URL", ""),
    }

@app.put("/api/settings")
async def save_settings(data: SettingsModel):
    current_token = ""
    if SETTINGS_FILE.exists():
        for line in SETTINGS_FILE.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                current_token = line.split("=", 1)[1].strip()
    token = current_token if "\u2022\u2022\u2022\u2022" in data.bot_token else data.bot_token
    content = f"BOT_TOKEN={token}\nADMIN_IDS={data.admin_ids}\nCHANNEL_ANNOUNCEMENTS={data.channel_announcements}\nCHANNEL_GALLERY={data.channel_gallery}\nCHANNEL_REVIEWS={data.channel_reviews}\nCHANNEL_TIPS={data.channel_tips}\nCHANNEL_REQUESTS={data.channel_requests}\nCHANNEL_POLLS={data.channel_polls}\nMAIN_GROUP={data.main_group}\nPOTD_TIME={data.potd_time}\nTIP_TIME={data.tip_time}\nTIMEZONE={data.timezone}\nIMAGE_SOURCE_PATH={data.image_source_path}\nIMAGE_SOURCE_URL={data.image_source_url}\nDB_PATH={DB_PATH}\n"
    os.makedirs(SETTINGS_FILE.parent, exist_ok=True)
    SETTINGS_FILE.write_text(content)
    return {"message": "Settings saved"}

def _mask_token(token):
    if not token or token == "your_bot_token_here": return ""
    if len(token) > 10: return token[:4] + "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" + token[-4:]
    return "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


TIPS_FILE = Path("./config/tips.json")

@app.get("/api/tips")
async def get_tips():
    if TIPS_FILE.exists():
        return json.loads(TIPS_FILE.read_text()).get("tips", [])
    return []

@app.post("/api/tips")
async def add_tip(title: str = Form(...), text: str = Form(...), tags: str = Form("")):
    tips_data = {"tips": []}
    if TIPS_FILE.exists():
        tips_data = json.loads(TIPS_FILE.read_text())
    tips_data["tips"].append({"title": title, "text": text, "tags": [t.strip() for t in tags.split(",") if t.strip()]})
    os.makedirs(TIPS_FILE.parent, exist_ok=True)
    TIPS_FILE.write_text(json.dumps(tips_data, indent=2))
    return {"message": "Tip added", "count": len(tips_data["tips"])}


@app.get("/api/health")
async def health():
    db = await get_db()
    await (await db.execute("SELECT 1")).fetchone()
    return {"status": "healthy", "db": DB_PATH, "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/cam-stream")
async def cam_stream_proxy():
    """Proxy the camera MJPEG stream for the dashboard Live Cam tab."""
    cam_port = os.getenv("CAM_SERVER_PORT", "8001")
    import httpx
    from starlette.responses import StreamingResponse
    async def stream_generator():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"http://localhost:{cam_port}/stream") as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(stream_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


if os.path.isdir(DASHBOARD_DIR):
    app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
"""
3D Print Hub Ã¢ÂÂ FastAPI Dashboard Backend
Serves live data from the bot's SQLite database to the web dashboard.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from api.auth import check_auth, auth_response

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for health endpoint
        if request.url.path == "/api/health":
            return await call_next(request)
        if not check_auth(request):
            return auth_response()
        return await call_next(request)


DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "./assets/prints")
DASHBOARD_DIR = os.getenv("DASHBOARD_DIR", "./dashboard")
API_PORT = int(os.getenv("API_PORT", "8000"))

_db = None

async def get_db():
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db

async def _init_tables(db):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description TEXT DEFAULT '', image_path TEXT DEFAULT '',
            tags TEXT DEFAULT '', printer TEXT DEFAULT '', material TEXT DEFAULT '',
            stl_link TEXT DEFAULT '', posted_by INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'posted',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            user_id INTEGER, username TEXT,
            rating INTEGER CHECK(rating BETWEEN 1 AND 5), text TEXT,
            message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT,
            prints_shared INTEGER DEFAULT 0, reviews_given INTEGER DEFAULT 0,
            requests_fulfilled INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS print_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0,
            username TEXT, description TEXT,
            claimed_by INTEGER DEFAULT NULL, claimed_by_username TEXT DEFAULT NULL,
            status TEXT DEFAULT 'open', message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS potd_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            featured_date TEXT DEFAULT (date('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS channel_stats (
            channel_id TEXT PRIMARY KEY, name TEXT,
            emoji TEXT DEFAULT '', message_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    await db.commit()


class PrintCreate(BaseModel):
    name: str
    description: str = ""
    material: str = ""
    printer: str = ""
    tags: str = ""
    stl_link: str = ""
    image_path: str = ""
    status: str = "draft"

class PrintUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    material: str | None = None
    printer: str | None = None
    tags: str | None = None
    stl_link: str | None = None
    image_path: str | None = None
    status: str | None = None

class ReviewCreate(BaseModel):
    print_id: int
    username: str
    rating: int = Field(ge=1, le=5)
    text: str

class RequestCreate(BaseModel):
    username: str
    description: str

class RequestUpdate(BaseModel):
    status: str | None = None
    claimed_by_username: str | None = None

class SettingsModel(BaseModel):
    bot_token: str = ""
    admin_ids: str = ""
    timezone: str = "America/New_York"
    potd_time: str = "09:00"
    tip_time: str = "12:00"
    channel_announcements: str = ""
    channel_gallery: str = ""
    channel_reviews: str = ""
    channel_tips: str = ""
    channel_requests: str = ""
    channel_polls: str = ""
    main_group: str = ""
    image_source_path: str = "./assets/prints/"
    image_source_url: str = ""

class ActivityCreate(BaseModel):
    type: str
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_db()
    yield
    if _db:
        await _db.close()

app = FastAPI(title="3D Print Hub API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/stats")
async def get_stats():
    db = await get_db()
    pc = await db.execute("SELECT COUNT(*) FROM prints")
    prints_count = (await pc.fetchone())[0]
    rc = await db.execute("SELECT COUNT(*) FROM reviews")
    reviews_count = (await rc.fetchone())[0]
    ar = await db.execute("SELECT AVG(rating) FROM reviews")
    avg_rating = (await ar.fetchone())[0]
    avg_rating = round(avg_rating, 1) if avg_rating else 0
    mc = await db.execute("SELECT COUNT(*) FROM users")
    members_count = (await mc.fetchone())[0]
    rq = await db.execute("SELECT COUNT(*) FROM print_requests")
    requests_total = (await rq.fetchone())[0]
    oq = await db.execute("SELECT COUNT(*) FROM print_requests WHERE status='open'")
    open_count = (await oq.fetchone())[0]
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    pw = await db.execute("SELECT COUNT(*) FROM prints WHERE created_at >= ?", (week_ago,))
    prints_week = (await pw.fetchone())[0]
    mw = await db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week_ago,))
    members_week = (await mw.fetchone())[0]
    return {"prints": prints_count, "prints_this_week": prints_week, "reviews": reviews_count, "avgRating": avg_rating, "members": members_count, "members_this_week": members_week, "requests": requests_total, "openRequests": open_count}


@app.get("/api/prints")
async def list_prints(search: str = "", status: str = "", limit: int = 50, offset: int = 0):
    db = await get_db()
    conditions, params = [], []
    if search:
        conditions.append("(p.name LIKE ? OR p.tags LIKE ? OR p.material LIKE ? OR p.description LIKE ?)")
        params.extend([f"%{search}%"] * 4)
    if status:
        conditions.append("p.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT p.*, COALESCE(AVG(r.rating),0) AS avg_rating, COUNT(r.id) AS review_count FROM prints p LEFT JOIN reviews r ON r.print_id=p.id {where} GROUP BY p.id ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(query, params)
    return [{**dict(row), "avg_rating": round(row["avg_rating"], 1), "review_count": row["review_count"]} for row in await cursor.fetchall()]

@app.get("/api/prints/{print_id}")
async def get_print_detail(print_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM prints WHERE id=?", (print_id,))
    row = await cursor.fetchone()
    if not row: raise HTTPException(404, "Print not found")
    avg = await db.execute("SELECT AVG(rating) FROM reviews WHERE print_id=?", (print_id,))
    avg_val = (await avg.fetchone())[0]
    rc = await db.execute("SELECT * FROM reviews WHERE print_id=? ORDER BY created_at DESC", (print_id,))
    reviews = [dict(r) for r in await rc.fetchall()]
    return {**dict(row), "avg_rating": round(avg_val, 1) if avg_val else 0, "reviews": reviews}

@app.post("/api/prints")
async def create_print(data: PrintCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO prints (name,description,material,printer,tags,stl_link,image_path) VALUES (?,?,?,?,?,?,?)", (data.name, data.description, data.material, data.printer, data.tags, data.stl_link, data.image_path))
    await db.commit()
    await _log_activity(db, "print", f"New print added: {data.name}")
    return {"id": cursor.lastrowid, "message": "Print created"}

@app.put("/api/prints/{print_id}")
async def update_print(print_id: int, data: PrintUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE prints SET {set_clause} WHERE id=?", list(fields.values()) + [print_id])
    await db.commit()
    return {"message": "Print updated"}

@app.delete("/api/prints/{print_id}")
async def delete_print(print_id: int):
    db = await get_db()
    await db.execute("DELETE FROM reviews WHERE print_id=?", (print_id,))
    await db.execute("DELETE FROM prints WHERE id=?", (print_id,))
    await db.commit()
    return {"message": "Print deleted"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    safe_name = file.filename.replace(" ", "_").replace("/", "_")
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    path = os.path.join(UPLOADS_DIR, filename)
    content = await file.read()
    with open(path, "wb") as f: f.write(content)
    return {"filename": filename, "path": path, "size": len(content)}


@app.get("/api/reviews")
async def list_reviews(limit: int = 50, offset: int = 0):
    db = await get_db()
    cursor = await db.execute("SELECT r.*, p.name AS print_name FROM reviews r LEFT JOIN prints p ON p.id=r.print_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    return [dict(row) for row in await cursor.fetchall()]

@app.get("/api/reviews/distribution")
async def review_distribution():
    db = await get_db()
    dist = {}
    for rating in range(1, 6):
        c = await db.execute("SELECT COUNT(*) FROM reviews WHERE rating=?", (rating,))
        dist[rating] = (await c.fetchone())[0]
    return dist

@app.post("/api/reviews")
async def create_review(data: ReviewCreate):
    db = await get_db()
    cursor = await db.execute("SELECT name FROM prints WHERE id=?", (data.print_id,))
    pr = await cursor.fetchone()
    if not pr: raise HTTPException(404, "Print not found")
    await db.execute("INSERT INTO reviews (print_id,username,rating,text) VALUES (?,?,?,?)", (data.print_id, data.username, data.rating, data.text))
    await db.commit()
    await _log_activity(db, "review", f"{data.username} reviewed {pr['name']} {'\u2b50'*data.rating}")
    return {"message": "Review created"}


@app.get("/api/requests")
async def list_requests(status: str = "", limit: int = 50):
    db = await get_db()
    if status:
        cursor = await db.execute("SELECT * FROM print_requests WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
    else:
        cursor = await db.execute("SELECT * FROM print_requests ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]

@app.post("/api/requests")
async def create_request(data: RequestCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO print_requests (username,description) VALUES (?,?)", (data.username, data.description))
    await db.commit()
    await _log_activity(db, "request", f"New request from {data.username}: {data.description[:60]}")
    return {"id": cursor.lastrowid, "message": "Request created"}

@app.put("/api/requests/{request_id}")
async def update_request(request_id: int, data: RequestUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    if "claimed_by_username" in fields and "status" not in fields:
        fields["status"] = "claimed"
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE print_requests SET {set_clause} WHERE id=?", list(fields.values()) + [request_id])
    await db.commit()
    if fields.get("status") == "fulfilled":
        await _log_activity(db, "request", f"Request #{request_id} fulfilled!")
    return {"message": "Request updated"}


@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 20):
    db = await get_db()
    cursor = await db.execute("SELECT *, (prints_shared*3 + reviews_given*2 + requests_fulfilled*5) AS score FROM users ORDER BY score DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]


@app.get("/api/activity")
async def get_activity(limit: int = 30):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in await cursor.fetchall()]
    now = datetime.utcnow()
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        delta = now - created
        if delta.days > 0: row["time_ago"] = f"{delta.days}d ago"
        elif delta.seconds >= 3600: row["time_ago"] = f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60: row["time_ago"] = f"{delta.seconds // 60}m ago"
        else: row["time_ago"] = "just now"
    return rows

@app.post("/api/activity")
async def create_activity(data: ActivityCreate):
    db = await get_db()
    await _log_activity(db, data.type, data.text)
    return {"message": "Activity logged"}

async def _log_activity(db, type, text):
    await db.execute("INSERT INTO activity_log (type,text) VALUES (?,?)", (type, text))
    await db.commit()


@app.get("/api/channels")
async def get_channels():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM channel_stats ORDER BY message_count DESC")
    rows = [dict(row) for row in await cursor.fetchall()]
    if not rows:
        return [
            {"channel_id": "announcements", "name": "Announcements", "emoji": "\ud83d\udce2", "message_count": 0},
            {"channel_id": "gallery", "name": "Gallery", "emoji": "\ud83d\uddbc\ufe0f", "message_count": 0},
            {"channel_id": "reviews", "name": "Reviews", "emoji": "\ud83d\udcdd", "message_count": 0},
            {"channel_id": "tips", "name": "Tips & Tricks", "emoji": "\ud83d\udca1", "message_count": 0},
            {"channel_id": "requests", "name": "Requests", "emoji": "\ud83d\ude4b", "message_count": 0},
            {"channel_id": "polls", "name": "Polls", "emoji": "\ud83d\udcca", "message_count": 0},
            {"channel_id": "general", "name": "General", "emoji": "\ud83d\udcac", "message_count": 0},
        ]
    return rows


SETTINGS_FILE = Path("./config/.env")

@app.get("/api/settings")
async def get_settings():
    if not SETTINGS_FILE.exists():
        return SettingsModel().dict()
    env = {}
    for line in SETTINGS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return {
        "bot_token": _mask_token(env.get("BOT_TOKEN", "")),
        "admin_ids": env.get("ADMIN_IDS", ""),
        "timezone": env.get("TIMEZONE", "America/New_York"),
        "potd_time": env.get("POTD_TIME", "09:00"),
        "tip_time": env.get("TIP_TIME", "12:00"),
        "channel_announcements": env.get("CHANNEL_ANNOUNCEMENTS", ""),
        "channel_gallery": env.get("CHANNEL_GALLERY", ""),
        "channel_reviews": env.get("CHANNEL_REVIEWS", ""),
        "channel_tips": env.get("CHANNEL_TIPS", ""),
        "channel_requests": env.get("CHANNEL_REQUESTS", ""),
        "channel_polls": env.get("CHANNEL_POLLS", ""),
        "main_group": env.get("MAIN_GROUP", ""),
        "image_source_path": env.get("IMAGE_SOURCE_PATH", "./assets/prints/"),
        "image_source_url": env.get("IMAGE_SOURCE_URL", ""),
    }

@app.put("/api/settings")
async def save_settings(data: SettingsModel):
    current_token = ""
    if SETTINGS_FILE.exists():
        for line in SETTINGS_FILE.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                current_token = line.split("=", 1)[1].strip()
    token = current_token if "\u2022\u2022\u2022\u2022" in data.bot_token else data.bot_token
    content = f"BOT_TOKEN={token}\nADMIN_IDS={data.admin_ids}\nCHANNEL_ANNOUNCEMENTS={data.channel_announcements}\nCHANNEL_GALLERY={data.channel_gallery}\nCHANNEL_REVIEWS={data.channel_reviews}\nCHANNEL_TIPS={data.channel_tips}\nCHANNEL_REQUESTS={data.channel_requests}\nCHANNEL_POLLS={data.channel_polls}\nMAIN_GROUP={data.main_group}\nPOTD_TIME={data.potd_time}\nTIP_TIME={data.tip_time}\nTIMEZONE={data.timezone}\nIMAGE_SOURCE_PATH={data.image_source_path}\nIMAGE_SOURCE_URL={data.image_source_url}\nDB_PATH={DB_PATH}\n"
    os.makedirs(SETTINGS_FILE.parent, exist_ok=True)
    SETTINGS_FILE.write_text(content)
    return {"message": "Settings saved"}

def _mask_token(token):
    if not token or token == "your_bot_token_here": return ""
    if len(token) > 10: return token[:4] + "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" + token[-4:]
    return "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


TIPS_FILE = Path("./config/tips.json")

@app.get("/api/tips")
async def get_tips():
    if TIPS_FILE.exists():
        return json.loads(TIPS_FILE.read_text()).get("tips", [])
    return []

@app.post("/api/tips")
async def add_tip(title: str = Form(...), text: str = Form(...), tags: str = Form("")):
    tips_data = {"tips": []}
    if TIPS_FILE.exists():
        tips_data = json.loads(TIPS_FILE.read_text())
    tips_data["tips"].append({"title": title, "text": text, "tags": [t.strip() for t in tags.split(",") if t.strip()]})
    os.makedirs(TIPS_FILE.parent, exist_ok=True)
    TIPS_FILE.write_text(json.dumps(tips_data, indent=2))
    return {"message": "Tip added", "count": len(tips_data["tips"])}


@app.get("/api/health")
async def health():
    db = await get_db()
    await (await db.execute("SELECT 1")).fetchone()
    return {"status": "healthy", "db": DB_PATH, "timestamp": datetime.utcnow().isoformat()}


if os.path.isdir(DASHBOARD_DIR):
    
@app.get("/api/cam-stream")
async def cam_stream_proxy():
    """Proxy the camera MJPEG stream for the dashboard Live Cam tab."""
    cam_port = os.getenv("CAM_SERVER_PORT", "8001")
    from starlette.responses import StreamingResponse
    import httpx
    async def stream():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"http://localhost:{cam_port}/stream") as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame")


app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
"""
3D Print Hub Ã¢ÂÂ FastAPI Dashboard Backend
Serves live data from the bot's SQLite database to the web dashboard.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from api.auth import check_auth, auth_response

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for health endpoint
        if request.url.path == "/api/health":
            return await call_next(request)
        if not check_auth(request):
            return auth_response()
        return await call_next(request)


DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "./assets/prints")
DASHBOARD_DIR = os.getenv("DASHBOARD_DIR", "./dashboard")
API_PORT = int(os.getenv("API_PORT", "8000"))

_db = None

async def get_db():
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db

async def _init_tables(db):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description TEXT DEFAULT '', image_path TEXT DEFAULT '',
            tags TEXT DEFAULT '', printer TEXT DEFAULT '', material TEXT DEFAULT '',
            stl_link TEXT DEFAULT '', posted_by INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'posted',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            user_id INTEGER, username TEXT,
            rating INTEGER CHECK(rating BETWEEN 1 AND 5), text TEXT,
            message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT,
            prints_shared INTEGER DEFAULT 0, reviews_given INTEGER DEFAULT 0,
            requests_fulfilled INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS print_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0,
            username TEXT, description TEXT,
            claimed_by INTEGER DEFAULT NULL, claimed_by_username TEXT DEFAULT NULL,
            status TEXT DEFAULT 'open', message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS potd_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            featured_date TEXT DEFAULT (date('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS channel_stats (
            channel_id TEXT PRIMARY KEY, name TEXT,
            emoji TEXT DEFAULT '', message_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    await db.commit()


class PrintCreate(BaseModel):
    name: str
    description: str = ""
    material: str = ""
    printer: str = ""
    tags: str = ""
    stl_link: str = ""
    image_path: str = ""
    status: str = "draft"

class PrintUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    material: str | None = None
    printer: str | None = None
    tags: str | None = None
    stl_link: str | None = None
    image_path: str | None = None
    status: str | None = None

class ReviewCreate(BaseModel):
    print_id: int
    username: str
    rating: int = Field(ge=1, le=5)
    text: str

class RequestCreate(BaseModel):
    username: str
    description: str

class RequestUpdate(BaseModel):
    status: str | None = None
    claimed_by_username: str | None = None

class SettingsModel(BaseModel):
    bot_token: str = ""
    admin_ids: str = ""
    timezone: str = "America/New_York"
    potd_time: str = "09:00"
    tip_time: str = "12:00"
    channel_announcements: str = ""
    channel_gallery: str = ""
    channel_reviews: str = ""
    channel_tips: str = ""
    channel_requests: str = ""
    channel_polls: str = ""
    main_group: str = ""
    image_source_path: str = "./assets/prints/"
    image_source_url: str = ""

class ActivityCreate(BaseModel):
    type: str
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_db()
    yield
    if _db:
        await _db.close()

app = FastAPI(title="3D Print Hub API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/stats")
async def get_stats():
    db = await get_db()
    pc = await db.execute("SELECT COUNT(*) FROM prints")
    prints_count = (await pc.fetchone())[0]
    rc = await db.execute("SELECT COUNT(*) FROM reviews")
    reviews_count = (await rc.fetchone())[0]
    ar = await db.execute("SELECT AVG(rating) FROM reviews")
    avg_rating = (await ar.fetchone())[0]
    avg_rating = round(avg_rating, 1) if avg_rating else 0
    mc = await db.execute("SELECT COUNT(*) FROM users")
    members_count = (await mc.fetchone())[0]
    rq = await db.execute("SELECT COUNT(*) FROM print_requests")
    requests_total = (await rq.fetchone())[0]
    oq = await db.execute("SELECT COUNT(*) FROM print_requests WHERE status='open'")
    open_count = (await oq.fetchone())[0]
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    pw = await db.execute("SELECT COUNT(*) FROM prints WHERE created_at >= ?", (week_ago,))
    prints_week = (await pw.fetchone())[0]
    mw = await db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week_ago,))
    members_week = (await mw.fetchone())[0]
    return {"prints": prints_count, "prints_this_week": prints_week, "reviews": reviews_count, "avgRating": avg_rating, "members": members_count, "members_this_week": members_week, "requests": requests_total, "openRequests": open_count}


@app.get("/api/prints")
async def list_prints(search: str = "", status: str = "", limit: int = 50, offset: int = 0):
    db = await get_db()
    conditions, params = [], []
    if search:
        conditions.append("(p.name LIKE ? OR p.tags LIKE ? OR p.material LIKE ? OR p.description LIKE ?)")
        params.extend([f"%{search}%"] * 4)
    if status:
        conditions.append("p.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT p.*, COALESCE(AVG(r.rating),0) AS avg_rating, COUNT(r.id) AS review_count FROM prints p LEFT JOIN reviews r ON r.print_id=p.id {where} GROUP BY p.id ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(query, params)
    return [{**dict(row), "avg_rating": round(row["avg_rating"], 1), "review_count": row["review_count"]} for row in await cursor.fetchall()]

@app.get("/api/prints/{print_id}")
async def get_print_detail(print_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM prints WHERE id=?", (print_id,))
    row = await cursor.fetchone()
    if not row: raise HTTPException(404, "Print not found")
    avg = await db.execute("SELECT AVG(rating) FROM reviews WHERE print_id=?", (print_id,))
    avg_val = (await avg.fetchone())[0]
    rc = await db.execute("SELECT * FROM reviews WHERE print_id=? ORDER BY created_at DESC", (print_id,))
    reviews = [dict(r) for r in await rc.fetchall()]
    return {**dict(row), "avg_rating": round(avg_val, 1) if avg_val else 0, "reviews": reviews}

@app.post("/api/prints")
async def create_print(data: PrintCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO prints (name,description,material,printer,tags,stl_link,image_path) VALUES (?,?,?,?,?,?,?)", (data.name, data.description, data.material, data.printer, data.tags, data.stl_link, data.image_path))
    await db.commit()
    await _log_activity(db, "print", f"New print added: {data.name}")
    return {"id": cursor.lastrowid, "message": "Print created"}

@app.put("/api/prints/{print_id}")
async def update_print(print_id: int, data: PrintUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE prints SET {set_clause} WHERE id=?", list(fields.values()) + [print_id])
    await db.commit()
    return {"message": "Print updated"}

@app.delete("/api/prints/{print_id}")
async def delete_print(print_id: int):
    db = await get_db()
    await db.execute("DELETE FROM reviews WHERE print_id=?", (print_id,))
    await db.execute("DELETE FROM prints WHERE id=?", (print_id,))
    await db.commit()
    return {"message": "Print deleted"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    safe_name = file.filename.replace(" ", "_").replace("/", "_")
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    path = os.path.join(UPLOADS_DIR, filename)
    content = await file.read()
    with open(path, "wb") as f: f.write(content)
    return {"filename": filename, "path": path, "size": len(content)}


@app.get("/api/reviews")
async def list_reviews(limit: int = 50, offset: int = 0):
    db = await get_db()
    cursor = await db.execute("SELECT r.*, p.name AS print_name FROM reviews r LEFT JOIN prints p ON p.id=r.print_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    return [dict(row) for row in await cursor.fetchall()]

@app.get("/api/reviews/distribution")
async def review_distribution():
    db = await get_db()
    dist = {}
    for rating in range(1, 6):
        c = await db.execute("SELECT COUNT(*) FROM reviews WHERE rating=?", (rating,))
        dist[rating] = (await c.fetchone())[0]
    return dist

@app.post("/api/reviews")
async def create_review(data: ReviewCreate):
    db = await get_db()
    cursor = await db.execute("SELECT name FROM prints WHERE id=?", (data.print_id,))
    pr = await cursor.fetchone()
    if not pr: raise HTTPException(404, "Print not found")
    await db.execute("INSERT INTO reviews (print_id,username,rating,text) VALUES (?,?,?,?)", (data.print_id, data.username, data.rating, data.text))
    await db.commit()
    await _log_activity(db, "review", f"{data.username} reviewed {pr['name']} {'\u2b50'*data.rating}")
    return {"message": "Review created"}


@app.get("/api/requests")
async def list_requests(status: str = "", limit: int = 50):
    db = await get_db()
    if status:
        cursor = await db.execute("SELECT * FROM print_requests WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
    else:
        cursor = await db.execute("SELECT * FROM print_requests ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]

@app.post("/api/requests")
async def create_request(data: RequestCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO print_requests (username,description) VALUES (?,?)", (data.username, data.description))
    await db.commit()
    await _log_activity(db, "request", f"New request from {data.username}: {data.description[:60]}")
    return {"id": cursor.lastrowid, "message": "Request created"}

@app.put("/api/requests/{request_id}")
async def update_request(request_id: int, data: RequestUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    if "claimed_by_username" in fields and "status" not in fields:
        fields["status"] = "claimed"
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE print_requests SET {set_clause} WHERE id=?", list(fields.values()) + [request_id])
    await db.commit()
    if fields.get("status") == "fulfilled":
        await _log_activity(db, "request", f"Request #{request_id} fulfilled!")
    return {"message": "Request updated"}


@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 20):
    db = await get_db()
    cursor = await db.execute("SELECT *, (prints_shared*3 + reviews_given*2 + requests_fulfilled*5) AS score FROM users ORDER BY score DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]


@app.get("/api/activity")
async def get_activity(limit: int = 30):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in await cursor.fetchall()]
    now = datetime.utcnow()
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        delta = now - created
        if delta.days > 0: row["time_ago"] = f"{delta.days}d ago"
        elif delta.seconds >= 3600: row["time_ago"] = f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60: row["time_ago"] = f"{delta.seconds // 60}m ago"
        else: row["time_ago"] = "just now"
    return rows

@app.post("/api/activity")
async def create_activity(data: ActivityCreate):
    db = await get_db()
    await _log_activity(db, data.type, data.text)
    return {"message": "Activity logged"}

async def _log_activity(db, type, text):
    await db.execute("INSERT INTO activity_log (type,text) VALUES (?,?)", (type, text))
    await db.commit()


@app.get("/api/channels")
async def get_channels():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM channel_stats ORDER BY message_count DESC")
    rows = [dict(row) for row in await cursor.fetchall()]
    if not rows:
        return [
            {"channel_id": "announcements", "name": "Announcements", "emoji": "\ud83d\udce2", "message_count": 0},
            {"channel_id": "gallery", "name": "Gallery", "emoji": "\ud83d\uddbc\ufe0f", "message_count": 0},
            {"channel_id": "reviews", "name": "Reviews", "emoji": "\ud83d\udcdd", "message_count": 0},
            {"channel_id": "tips", "name": "Tips & Tricks", "emoji": "\ud83d\udca1", "message_count": 0},
            {"channel_id": "requests", "name": "Requests", "emoji": "\ud83d\ude4b", "message_count": 0},
            {"channel_id": "polls", "name": "Polls", "emoji": "\ud83d\udcca", "message_count": 0},
            {"channel_id": "general", "name": "General", "emoji": "\ud83d\udcac", "message_count": 0},
        ]
    return rows


SETTINGS_FILE = Path("./config/.env")

@app.get("/api/settings")
async def get_settings():
    if not SETTINGS_FILE.exists():
        return SettingsModel().dict()
    env = {}
    for line in SETTINGS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return {
        "bot_token": _mask_token(env.get("BOT_TOKEN", "")),
        "admin_ids": env.get("ADMIN_IDS", ""),
        "timezone": env.get("TIMEZONE", "America/New_York"),
        "potd_time": env.get("POTD_TIME", "09:00"),
        "tip_time": env.get("TIP_TIME", "12:00"),
        "channel_announcements": env.get("CHANNEL_ANNOUNCEMENTS", ""),
        "channel_gallery": env.get("CHANNEL_GALLERY", ""),
        "channel_reviews": env.get("CHANNEL_REVIEWS", ""),
        "channel_tips": env.get("CHANNEL_TIPS", ""),
        "channel_requests": env.get("CHANNEL_REQUESTS", ""),
        "channel_polls": env.get("CHANNEL_POLLS", ""),
        "main_group": env.get("MAIN_GROUP", ""),
        "image_source_path": env.get("IMAGE_SOURCE_PATH", "./assets/prints/"),
        "image_source_url": env.get("IMAGE_SOURCE_URL", ""),
    }

@app.put("/api/settings")
async def save_settings(data: SettingsModel):
    current_token = ""
    if SETTINGS_FILE.exists():
        for line in SETTINGS_FILE.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                current_token = line.split("=", 1)[1].strip()
    token = current_token if "\u2022\u2022\u2022\u2022" in data.bot_token else data.bot_token
    content = f"BOT_TOKEN={token}\nADMIN_IDS={data.admin_ids}\nCHANNEL_ANNOUNCEMENTS={data.channel_announcements}\nCHANNEL_GALLERY={data.channel_gallery}\nCHANNEL_REVIEWS={data.channel_reviews}\nCHANNEL_TIPS={data.channel_tips}\nCHANNEL_REQUESTS={data.channel_requests}\nCHANNEL_POLLS={data.channel_polls}\nMAIN_GROUP={data.main_group}\nPOTD_TIME={data.potd_time}\nTIP_TIME={data.tip_time}\nTIMEZONE={data.timezone}\nIMAGE_SOURCE_PATH={data.image_source_path}\nIMAGE_SOURCE_URL={data.image_source_url}\nDB_PATH={DB_PATH}\n"
    os.makedirs(SETTINGS_FILE.parent, exist_ok=True)
    SETTINGS_FILE.write_text(content)
    return {"message": "Settings saved"}

def _mask_token(token):
    if not token or token == "your_bot_token_here": return ""
    if len(token) > 10: return token[:4] + "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" + token[-4:]
    return "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


TIPS_FILE = Path("./config/tips.json")

@app.get("/api/tips")
async def get_tips():
    if TIPS_FILE.exists():
        return json.loads(TIPS_FILE.read_text()).get("tips", [])
    return []

@app.post("/api/tips")
async def add_tip(title: str = Form(...), text: str = Form(...), tags: str = Form("")):
    tips_data = {"tips": []}
    if TIPS_FILE.exists():
        tips_data = json.loads(TIPS_FILE.read_text())
    tips_data["tips"].append({"title": title, "text": text, "tags": [t.strip() for t in tags.split(",") if t.strip()]})
    os.makedirs(TIPS_FILE.parent, exist_ok=True)
    TIPS_FILE.write_text(json.dumps(tips_data, indent=2))
    return {"message": "Tip added", "count": len(tips_data["tips"])}


@app.get("/api/health")
async def health():
    db = await get_db()
    await (await db.execute("SELECT 1")).fetchone()
    return {"status": "healthy", "db": DB_PATH, "timestamp": datetime.utcnow().isoformat()}


if os.path.isdir(DASHBOARD_DIR):
    
@app.get("/api/cam-stream")
async def cam_stream_proxy():
    """Proxy the camera MJPEG stream for the dashboard Live Cam tab."""
    cam_port = os.getenv("CAM_SERVER_PORT", "8001")
    import httpx
    from starlette.responses import StreamingResponse
    async def stream_generator():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"http://localhost:{cam_port}/stream") as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(stream_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
"""
3D Print Hub â FastAPI Dashboard Backend
Serves live data from the bot's SQLite database to the web dashboard.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from api.auth import check_auth, auth_response

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for health endpoint
        if request.url.path == "/api/health":
            return await call_next(request)
        if not check_auth(request):
            return auth_response()
        return await call_next(request)


DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "./assets/prints")
DASHBOARD_DIR = os.getenv("DASHBOARD_DIR", "./dashboard")
API_PORT = int(os.getenv("API_PORT", "8000"))

_db = None

async def get_db():
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db

async def _init_tables(db):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description TEXT DEFAULT '', image_path TEXT DEFAULT '',
            tags TEXT DEFAULT '', printer TEXT DEFAULT '', material TEXT DEFAULT '',
            stl_link TEXT DEFAULT '', posted_by INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'posted',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            user_id INTEGER, username TEXT,
            rating INTEGER CHECK(rating BETWEEN 1 AND 5), text TEXT,
            message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT,
            prints_shared INTEGER DEFAULT 0, reviews_given INTEGER DEFAULT 0,
            requests_fulfilled INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS print_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0,
            username TEXT, description TEXT,
            claimed_by INTEGER DEFAULT NULL, claimed_by_username TEXT DEFAULT NULL,
            status TEXT DEFAULT 'open', message_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS potd_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, print_id INTEGER,
            featured_date TEXT DEFAULT (date('now')),
            FOREIGN KEY (print_id) REFERENCES prints(id)
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS channel_stats (
            channel_id TEXT PRIMARY KEY, name TEXT,
            emoji TEXT DEFAULT '', message_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    await db.commit()


class PrintCreate(BaseModel):
    name: str
    description: str = ""
    material: str = ""
    printer: str = ""
    tags: str = ""
    stl_link: str = ""
    image_path: str = ""
    status: str = "draft"

class PrintUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    material: str | None = None
    printer: str | None = None
    tags: str | None = None
    stl_link: str | None = None
    image_path: str | None = None
    status: str | None = None

class ReviewCreate(BaseModel):
    print_id: int
    username: str
    rating: int = Field(ge=1, le=5)
    text: str

class RequestCreate(BaseModel):
    username: str
    description: str

class RequestUpdate(BaseModel):
    status: str | None = None
    claimed_by_username: str | None = None

class SettingsModel(BaseModel):
    bot_token: str = ""
    admin_ids: str = ""
    timezone: str = "America/New_York"
    potd_time: str = "09:00"
    tip_time: str = "12:00"
    channel_announcements: str = ""
    channel_gallery: str = ""
    channel_reviews: str = ""
    channel_tips: str = ""
    channel_requests: str = ""
    channel_polls: str = ""
    main_group: str = ""
    image_source_path: str = "./assets/prints/"
    image_source_url: str = ""

class ActivityCreate(BaseModel):
    type: str
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_db()
    yield
    if _db:
        await _db.close()

app = FastAPI(title="3D Print Hub API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/stats")
async def get_stats():
    db = await get_db()
    pc = await db.execute("SELECT COUNT(*) FROM prints")
    prints_count = (await pc.fetchone())[0]
    rc = await db.execute("SELECT COUNT(*) FROM reviews")
    reviews_count = (await rc.fetchone())[0]
    ar = await db.execute("SELECT AVG(rating) FROM reviews")
    avg_rating = (await ar.fetchone())[0]
    avg_rating = round(avg_rating, 1) if avg_rating else 0
    mc = await db.execute("SELECT COUNT(*) FROM users")
    members_count = (await mc.fetchone())[0]
    rq = await db.execute("SELECT COUNT(*) FROM print_requests")
    requests_total = (await rq.fetchone())[0]
    oq = await db.execute("SELECT COUNT(*) FROM print_requests WHERE status='open'")
    open_count = (await oq.fetchone())[0]
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    pw = await db.execute("SELECT COUNT(*) FROM prints WHERE created_at >= ?", (week_ago,))
    prints_week = (await pw.fetchone())[0]
    mw = await db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week_ago,))
    members_week = (await mw.fetchone())[0]
    return {"prints": prints_count, "prints_this_week": prints_week, "reviews": reviews_count, "avgRating": avg_rating, "members": members_count, "members_this_week": members_week, "requests": requests_total, "openRequests": open_count}


@app.get("/api/prints")
async def list_prints(search: str = "", status: str = "", limit: int = 50, offset: int = 0):
    db = await get_db()
    conditions, params = [], []
    if search:
        conditions.append("(p.name LIKE ? OR p.tags LIKE ? OR p.material LIKE ? OR p.description LIKE ?)")
        params.extend([f"%{search}%"] * 4)
    if status:
        conditions.append("p.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT p.*, COALESCE(AVG(r.rating),0) AS avg_rating, COUNT(r.id) AS review_count FROM prints p LEFT JOIN reviews r ON r.print_id=p.id {where} GROUP BY p.id ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(query, params)
    return [{**dict(row), "avg_rating": round(row["avg_rating"], 1), "review_count": row["review_count"]} for row in await cursor.fetchall()]

@app.get("/api/prints/{print_id}")
async def get_print_detail(print_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM prints WHERE id=?", (print_id,))
    row = await cursor.fetchone()
    if not row: raise HTTPException(404, "Print not found")
    avg = await db.execute("SELECT AVG(rating) FROM reviews WHERE print_id=?", (print_id,))
    avg_val = (await avg.fetchone())[0]
    rc = await db.execute("SELECT * FROM reviews WHERE print_id=? ORDER BY created_at DESC", (print_id,))
    reviews = [dict(r) for r in await rc.fetchall()]
    return {**dict(row), "avg_rating": round(avg_val, 1) if avg_val else 0, "reviews": reviews}

@app.post("/api/prints")
async def create_print(data: PrintCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO prints (name,description,material,printer,tags,stl_link,image_path) VALUES (?,?,?,?,?,?,?)", (data.name, data.description, data.material, data.printer, data.tags, data.stl_link, data.image_path))
    await db.commit()
    await _log_activity(db, "print", f"New print added: {data.name}")
    return {"id": cursor.lastrowid, "message": "Print created"}

@app.put("/api/prints/{print_id}")
async def update_print(print_id: int, data: PrintUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE prints SET {set_clause} WHERE id=?", list(fields.values()) + [print_id])
    await db.commit()
    return {"message": "Print updated"}

@app.delete("/api/prints/{print_id}")
async def delete_print(print_id: int):
    db = await get_db()
    await db.execute("DELETE FROM reviews WHERE print_id=?", (print_id,))
    await db.execute("DELETE FROM prints WHERE id=?", (print_id,))
    await db.commit()
    return {"message": "Print deleted"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    safe_name = file.filename.replace(" ", "_").replace("/", "_")
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    path = os.path.join(UPLOADS_DIR, filename)
    content = await file.read()
    with open(path, "wb") as f: f.write(content)
    return {"filename": filename, "path": path, "size": len(content)}


@app.get("/api/reviews")
async def list_reviews(limit: int = 50, offset: int = 0):
    db = await get_db()
    cursor = await db.execute("SELECT r.*, p.name AS print_name FROM reviews r LEFT JOIN prints p ON p.id=r.print_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    return [dict(row) for row in await cursor.fetchall()]

@app.get("/api/reviews/distribution")
async def review_distribution():
    db = await get_db()
    dist = {}
    for rating in range(1, 6):
        c = await db.execute("SELECT COUNT(*) FROM reviews WHERE rating=?", (rating,))
        dist[rating] = (await c.fetchone())[0]
    return dist

@app.post("/api/reviews")
async def create_review(data: ReviewCreate):
    db = await get_db()
    cursor = await db.execute("SELECT name FROM prints WHERE id=?", (data.print_id,))
    pr = await cursor.fetchone()
    if not pr: raise HTTPException(404, "Print not found")
    await db.execute("INSERT INTO reviews (print_id,username,rating,text) VALUES (?,?,?,?)", (data.print_id, data.username, data.rating, data.text))
    await db.commit()
    await _log_activity(db, "review", f"{data.username} reviewed {pr['name']} {'\u2b50'*data.rating}")
    return {"message": "Review created"}


@app.get("/api/requests")
async def list_requests(status: str = "", limit: int = 50):
    db = await get_db()
    if status:
        cursor = await db.execute("SELECT * FROM print_requests WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
    else:
        cursor = await db.execute("SELECT * FROM print_requests ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]

@app.post("/api/requests")
async def create_request(data: RequestCreate):
    db = await get_db()
    cursor = await db.execute("INSERT INTO print_requests (username,description) VALUES (?,?)", (data.username, data.description))
    await db.commit()
    await _log_activity(db, "request", f"New request from {data.username}: {data.description[:60]}")
    return {"id": cursor.lastrowid, "message": "Request created"}

@app.put("/api/requests/{request_id}")
async def update_request(request_id: int, data: RequestUpdate):
    db = await get_db()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields")
    if "claimed_by_username" in fields and "status" not in fields:
        fields["status"] = "claimed"
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE print_requests SET {set_clause} WHERE id=?", list(fields.values()) + [request_id])
    await db.commit()
    if fields.get("status") == "fulfilled":
        await _log_activity(db, "request", f"Request #{request_id} fulfilled!")
    return {"message": "Request updated"}


@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 20):
    db = await get_db()
    cursor = await db.execute("SELECT *, (prints_shared*3 + reviews_given*2 + requests_fulfilled*5) AS score FROM users ORDER BY score DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]


@app.get("/api/activity")
async def get_activity(limit: int = 30):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in await cursor.fetchall()]
    now = datetime.utcnow()
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        delta = now - created
        if delta.days > 0: row["time_ago"] = f"{delta.days}d ago"
        elif delta.seconds >= 3600: row["time_ago"] = f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60: row["time_ago"] = f"{delta.seconds // 60}m ago"
        else: row["time_ago"] = "just now"
    return rows

@app.post("/api/activity")
async def create_activity(data: ActivityCreate):
    db = await get_db()
    await _log_activity(db, data.type, data.text)
    return {"message": "Activity logged"}

async def _log_activity(db, type, text):
    await db.execute("INSERT INTO activity_log (type,text) VALUES (?,?)", (type, text))
    await db.commit()


@app.get("/api/channels")
async def get_channels():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM channel_stats ORDER BY message_count DESC")
    rows = [dict(row) for row in await cursor.fetchall()]
    if not rows:
        return [
            {"channel_id": "announcements", "name": "Announcements", "emoji": "\ud83d\udce2", "message_count": 0},
            {"channel_id": "gallery", "name": "Gallery", "emoji": "\ud83d\uddbc\ufe0f", "message_count": 0},
            {"channel_id": "reviews", "name": "Reviews", "emoji": "\ud83d\udcdd", "message_count": 0},
            {"channel_id": "tips", "name": "Tips & Tricks", "emoji": "\ud83d\udca1", "message_count": 0},
            {"channel_id": "requests", "name": "Requests", "emoji": "\ud83d\ude4b", "message_count": 0},
            {"channel_id": "polls", "name": "Polls", "emoji": "\ud83d\udcca", "message_count": 0},
            {"channel_id": "general", "name": "General", "emoji": "\ud83d\udcac", "message_count": 0},
        ]
    return rows


SETTINGS_FILE = Path("./config/.env")

@app.get("/api/settings")
async def get_settings():
    if not SETTINGS_FILE.exists():
        return SettingsModel().dict()
    env = {}
    for line in SETTINGS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return {
        "bot_token": _mask_token(env.get("BOT_TOKEN", "")),
        "admin_ids": env.get("ADMIN_IDS", ""),
        "timezone": env.get("TIMEZONE", "America/New_York"),
        "potd_time": env.get("POTD_TIME", "09:00"),
        "tip_time": env.get("TIP_TIME", "12:00"),
        "channel_announcements": env.get("CHANNEL_ANNOUNCEMENTS", ""),
        "channel_gallery": env.get("CHANNEL_GALLERY", ""),
        "channel_reviews": env.get("CHANNEL_REVIEWS", ""),
        "channel_tips": env.get("CHANNEL_TIPS", ""),
        "channel_requests": env.get("CHANNEL_REQUESTS", ""),
        "channel_polls": env.get("CHANNEL_POLLS", ""),
        "main_group": env.get("MAIN_GROUP", ""),
        "image_source_path": env.get("IMAGE_SOURCE_PATH", "./assets/prints/"),
        "image_source_url": env.get("IMAGE_SOURCE_URL", ""),
    }

@app.put("/api/settings")
async def save_settings(data: SettingsModel):
    current_token = ""
    if SETTINGS_FILE.exists():
        for line in SETTINGS_FILE.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                current_token = line.split("=", 1)[1].strip()
    token = current_token if "\u2022\u2022\u2022\u2022" in data.bot_token else data.bot_token
    content = f"BOT_TOKEN={token}\nADMIN_IDS={data.admin_ids}\nCHANNEL_ANNOUNCEMENTS={data.channel_announcements}\nCHANNEL_GALLERY={data.channel_gallery}\nCHANNEL_REVIEWS={data.channel_reviews}\nCHANNEL_TIPS={data.channel_tips}\nCHANNEL_REQUESTS={data.channel_requests}\nCHANNEL_POLLS={data.channel_polls}\nMAIN_GROUP={data.main_group}\nPOTD_TIME={data.potd_time}\nTIP_TIME={data.tip_time}\nTIMEZONE={data.timezone}\nIMAGE_SOURCE_PATH={data.image_source_path}\nIMAGE_SOURCE_URL={data.image_source_url}\nDB_PATH={DB_PATH}\n"
    os.makedirs(SETTINGS_FILE.parent, exist_ok=True)
    SETTINGS_FILE.write_text(content)
    return {"message": "Settings saved"}

def _mask_token(token):
    if not token or token == "your_bot_token_here": return ""
    if len(token) > 10: return token[:4] + "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" + token[-4:]
    return "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


TIPS_FILE = Path("./config/tips.json")

@app.get("/api/tips")
async def get_tips():
    if TIPS_FILE.exists():
        return json.loads(TIPS_FILE.read_text()).get("tips", [])
    return []

@app.post("/api/tips")
async def add_tip(title: str = Form(...), text: str = Form(...), tags: str = Form("")):
    tips_data = {"tips": []}
    if TIPS_FILE.exists():
        tips_data = json.loads(TIPS_FILE.read_text())
    tips_data["tips"].append({"title": title, "text": text, "tags": [t.strip() for t in tags.split(",") if t.strip()]})
    os.makedirs(TIPS_FILE.parent, exist_ok=True)
    TIPS_FILE.write_text(json.dumps(tips_data, indent=2))
    return {"message": "Tip added", "count": len(tips_data["tips"])}


@app.get("/api/health")
async def health():
    db = await get_db()
    await (await db.execute("SELECT 1")).fetchone()
    return {"status": "healthy", "db": DB_PATH, "timestamp": datetime.utcnow().isoformat()}


if os.path.isdir(DASHBOARD_DIR):
    
@app.get("/api/cam-stream")
async def cam_stream_proxy():
    """Proxy the camera MJPEG stream for the dashboard Live Cam tab."""
    cam_port = os.getenv("CAM_SERVER_PORT", "8001")
    from starlette.responses import StreamingResponse
    import httpx
    async def stream():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"http://localhost:{cam_port}/stream") as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame")


app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
