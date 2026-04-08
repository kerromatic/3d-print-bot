"""
3D Print Hub - FastAPI Dashboard Backend
Serves live data from the bot's SQLite database to the web dashboard.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from api.auth import check_auth, auth_response

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
    return _db

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    global _db
    if _db:
        await _db.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        public_paths = ["/", "/api/settings", "/api/stats", "/api/leaderboard",
                        "/api/prints", "/api/reviews", "/api/activity", "/api/channels",
                        "/api/snapshot-interval", "/api/printer/status"]
        if any(request.url.path == p or request.url.path.startswith(p + "?") for p in public_paths):
            return await call_next(request)
        static_exts = [".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2"]
        if any(request.url.path.endswith(ext) for ext in static_exts):
            return await call_next(request)
        if not check_auth(request):
            return auth_response()
        return await call_next(request)

app.add_middleware(AuthMiddleware)

# --- Prints ---
@app.get("/api/prints")
async def get_prints(limit: int = Query(50), offset: int = Query(0)):
    db = await get_db()
    rows = await (await db.execute(
        "SELECT * FROM prints ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
    )).fetchall()
    return [dict(r) for r in rows]

@app.delete("/api/prints/{print_id}")
async def delete_print(print_id: int):
    db = await get_db()
    await db.execute("DELETE FROM prints WHERE id=?", (print_id,))
    await db.commit()
    return {"ok": True}

# --- Reviews ---
@app.get("/api/reviews")
async def get_reviews(limit: int = Query(50)):
    db = await get_db()
    rows = await (await db.execute(
        "SELECT r.*, p.name as print_name FROM reviews r LEFT JOIN prints p ON r.print_id=p.id ORDER BY r.created_at DESC LIMIT ?", (limit,)
    )).fetchall()
    return [dict(r) for r in rows]

# --- Requests ---
@app.get("/api/requests")
async def get_requests(status: str = Query(None), limit: int = Query(50)):
    db = await get_db()
    if status:
        rows = await (await db.execute(
            "SELECT * FROM print_requests WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)
        )).fetchall()
    else:
        rows = await (await db.execute(
            "SELECT * FROM print_requests ORDER BY id DESC LIMIT ?", (limit,)
        )).fetchall()
    return [dict(r) for r in rows]

@app.put("/api/requests/{request_id}/status")
async def update_request_status(request_id: int, status: str = Form(...)):
    db = await get_db()
    await db.execute("UPDATE print_requests SET status=? WHERE id=?", (status, request_id))
    await db.commit()
    return {"ok": True}

@app.delete("/api/requests/{request_id}")
async def delete_request(request_id: int):
    db = await get_db()
    await db.execute("DELETE FROM print_requests WHERE id=?", (request_id,))
    await db.commit()
    return {"ok": True}

# --- Leaderboard ---
@app.get("/api/leaderboard")
async def leaderboard(limit: int = Query(20)):
    db = await get_db()
    rows = await (await db.execute(
        "SELECT * FROM users ORDER BY prints_shared DESC LIMIT ?", (limit,)
    )).fetchall()
    result = []
    for r in rows:
        u = dict(r)
        u["score"] = u.get("prints_shared", 0)
        result.append(u)
    return result

# --- Stats ---
@app.get("/api/stats")
async def stats():
    db = await get_db()
    now = datetime.utcnow()
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    total_prints = (await (await db.execute("SELECT COUNT(*) as c FROM prints")).fetchone())["c"]
    prints_this_week = (await (await db.execute(
        "SELECT COUNT(*) as c FROM prints WHERE created_at >= ?", (week_ago,)
    )).fetchone())["c"]

    total_reviews = (await (await db.execute("SELECT COUNT(*) as c FROM reviews")).fetchone())["c"]
    avg_row = await (await db.execute("SELECT AVG(rating) as a FROM reviews")).fetchone()
    avg_rating = round(avg_row["a"], 1) if avg_row["a"] else 0

    total_users = (await (await db.execute("SELECT COUNT(*) as c FROM users")).fetchone())["c"]
    members_this_week = (await (await db.execute(
        "SELECT COUNT(*) as c FROM users WHERE joined_at >= ?", (week_ago,)
    )).fetchone())["c"]

    open_requests = (await (await db.execute(
        "SELECT COUNT(*) as c FROM print_requests WHERE status='open'"
    )).fetchone())["c"]
    total_requests = (await (await db.execute("SELECT COUNT(*) as c FROM print_requests")).fetchone())["c"]

    return {
        "prints": total_prints,
        "prints_this_week": prints_this_week,
        "reviews": total_reviews,
        "avg": avg_rating,
        "members": total_users,
        "members_this_week": members_this_week,
        "open": open_requests,
        "requests": total_requests,
    }

# --- Activity feed ---
@app.get("/api/activity")
async def activity(limit: int = Query(20)):
    db = await get_db()
    prints = await (await db.execute(
        "SELECT 'print' as type, name as title, created_at FROM prints ORDER BY created_at DESC LIMIT ?", (limit,)
    )).fetchall()
    reviews = await (await db.execute(
        "SELECT 'review' as type, username as title, created_at FROM reviews ORDER BY created_at DESC LIMIT ?", (limit,)
    )).fetchall()
    combined = sorted(
        [dict(r) for r in prints] + [dict(r) for r in reviews],
        key=lambda x: x["created_at"], reverse=True
    )
    return combined[:limit]

# --- Channels ---
@app.get("/api/channels")
async def channels():
    return {
        "announcements": os.getenv("TOPIC_ANNOUNCEMENTS", ""),
        "gallery": os.getenv("TOPIC_GALLERY", ""),
        "reviews": os.getenv("TOPIC_REVIEWS", ""),
        "tips": os.getenv("TOPIC_TIPS", ""),
        "requests": os.getenv("TOPIC_REQUESTS", ""),
        "polls": os.getenv("TOPIC_POLLS", ""),
        "general": os.getenv("TOPIC_GENERAL", ""),
        "livecam": os.getenv("TOPIC_LIVECAM", ""),
    }

# --- Settings ---
@app.get("/api/settings")
async def get_settings():
    return {
        "bot_token_set": bool(os.getenv("BOT_TOKEN")),
        "main_group": os.getenv("MAIN_GROUP", ""),
        "topics": {
            "announcements": os.getenv("TOPIC_ANNOUNCEMENTS", ""),
            "gallery": os.getenv("TOPIC_GALLERY", ""),
            "reviews": os.getenv("TOPIC_REVIEWS", ""),
            "tips": os.getenv("TOPIC_TIPS", ""),
            "requests": os.getenv("TOPIC_REQUESTS", ""),
            "polls": os.getenv("TOPIC_POLLS", ""),
            "general": os.getenv("TOPIC_GENERAL", ""),
            "livecam": os.getenv("TOPIC_LIVECAM", ""),
        },
        "schedule": {
            "potd_time": os.getenv("POTD_TIME", "09:00"),
            "tip_time": os.getenv("TIP_TIME", "12:00"),
            "timezone": os.getenv("TIMEZONE", "America/New_York"),
        },
        "printer": {
            "ip": os.getenv("PRINTER_IP", ""),
            "has_access_code": bool(os.getenv("PRINTER_ACCESS_CODE")),
            "serial": os.getenv("PRINTER_SERIAL", ""),
            "cam_port": os.getenv("CAM_PORT", "8001"),
        }
    }

@app.post("/api/settings")
async def save_settings(request: Request):
    try:
        data = await request.json()
        env_path = Path(".env")
        env_lines = env_path.read_text().splitlines() if env_path.exists() else []
        env_map = {}
        for line in env_lines:
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env_map[k.strip()] = v.strip()
        mapping = {
            "bot_token": "BOT_TOKEN",
            "main_group": "MAIN_GROUP",
            "admin_ids": "ADMIN_IDS",
            "timezone": "TIMEZONE",
            "potd_time": "POTD_TIME",
            "tip_time": "TIP_TIME",
            "channel_announcements": "TOPIC_ANNOUNCEMENTS",
            "channel_gallery": "TOPIC_GALLERY",
            "channel_reviews": "TOPIC_REVIEWS",
            "channel_tips": "TOPIC_TIPS",
            "channel_requests": "TOPIC_REQUESTS",
            "channel_polls": "TOPIC_POLLS",
            "image_source_path": "UPLOADS_DIR",
            "image_source_url": "IMAGE_SOURCE_URL",
        }
        for key, env_key in mapping.items():
            if key in data and data[key] not in (None, ""):
                env_map[env_key] = str(data[key])
        new_env = "\n".join(f"{k}={v}" for k, v in env_map.items()) + "\n"
        env_path.write_text(new_env)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Snapshot interval ---
_snapshot_interval_cache = 600  # default 10 min

@app.get("/api/snapshot-interval")
async def get_snapshot_interval():
    global _snapshot_interval_cache
    try:
        from bot.scheduler import get_snapshot_interval as _get
        _snapshot_interval_cache = _get()
    except Exception:
        pass
    return {"interval": _snapshot_interval_cache}

@app.post("/api/snapshot-interval")
async def set_snapshot_interval_endpoint(interval: int = Form(...)):
    global _snapshot_interval_cache
    interval = max(60, interval)
    _snapshot_interval_cache = interval
    try:
        from bot.scheduler import set_snapshot_interval as _set
        _set(interval)
    except Exception:
        pass
    return {"interval": interval, "status": "updated"}

# --- Camera stream proxy ---
@app.get("/api/cam-stream")
async def cam_stream_proxy():
    cam_port = os.getenv("CAM_SERVER_PORT", "8001")
    import httpx
    from starlette.responses import StreamingResponse
    async def stream_generator():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"http://localhost:{cam_port}/stream") as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(stream_generator(), media_type="multipart/x-mixed-replace; boundary=frame")

# --- Upload ---
@app.post("/api/upload")
async def upload_print(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    dest = Path(UPLOADS_DIR) / file.filename
    dest.write_bytes(await file.read())
    db = await get_db()
    await db.execute(
        "INSERT INTO prints (name, description, image_path, tags) VALUES (?,?,?,?)",
        (name, description, str(dest), tags)
    )
    await db.commit()
    return {"ok": True, "path": str(dest)}

# Ensure required directories exist before mounting
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(DASHBOARD_DIR, exist_ok=True)
os.makedirs("assets", exist_ok=True)

# --- Printer status ---
@app.get("/api/printer/status")
async def get_printer_status():
    try:
        from bot.printer_mqtt import printer_status as ps
        return {
            "connected": ps.connected,
            "gcode_state": ps.gcode_state,
            "is_printing": ps.is_printing,
            "progress": ps.mc_percent,
            "remaining_minutes": ps.mc_remaining_time,
            "remaining_str": ps.remaining_str,
            "layer": ps.layer_num,
            "total_layers": ps.total_layer_num,
            "file": ps.print_name,
            "nozzle_temp": round(ps.nozzle_temper, 1),
            "bed_temp": round(ps.bed_temper, 1),
            "summary": ps.summary(),
        }
    except Exception as e:
        return {"connected": False, "gcode_state": "UNKNOWN", "is_printing": False, "error": str(e)}


# --- Health check ---
@app.get("/api/health")
async def health():
    return {"status": "ok"}

app.mount("/assets", StaticFiles(directory="assets"), name="assets")
app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
