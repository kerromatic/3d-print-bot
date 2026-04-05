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


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/api/health":
            return await call_next(request)
        if not check_auth(request):
            return auth_response()
        return await call_next(request)


app = FastAPI(title="3D Print Hub API")
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Prints ---
@app.get("/api/prints")
async def list_prints(limit: int = 50, offset: int = 0):
    db = await get_db()
    rows = await (await db.execute(
        "SELECT * FROM prints ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
    )).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/prints/{print_id}")
async def get_print(print_id: int):
    db = await get_db()
    row = await (await db.execute("SELECT * FROM prints WHERE id=?", (print_id,))).fetchone()
    if not row:
        raise HTTPException(404, "Print not found")
    return dict(row)


@app.post("/api/prints")
async def create_print(
    name: str = Form(...),
    description: str = Form(""),
    material: str = Form(""),
    printer: str = Form(""),
    tags: str = Form(""),
    stl_link: str = Form(""),
):
    db = await get_db()
    cur = await db.execute(
        "INSERT INTO prints (name, description, material, printer, tags, stl_link) VALUES (?,?,?,?,?,?)",
        (name, description, material, printer, tags, stl_link),
    )
    await db.commit()
    return {"id": cur.lastrowid, "name": name}


@app.delete("/api/prints/{print_id}")
async def delete_print(print_id: int):
    db = await get_db()
    await db.execute("DELETE FROM prints WHERE id=?", (print_id,))
    await db.commit()
    return {"deleted": print_id}


# --- Reviews ---
@app.get("/api/reviews")
async def list_reviews(limit: int = 50):
    db = await get_db()
    rows = await (await db.execute(
        "SELECT r.*, p.name as print_name FROM reviews r LEFT JOIN prints p ON r.print_id=p.id ORDER BY r.id DESC LIMIT ?",
        (limit,),
    )).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/reviews/{review_id}")
async def delete_review(review_id: int):
    db = await get_db()
    await db.execute("DELETE FROM reviews WHERE id=?", (review_id,))
    await db.commit()
    return {"deleted": review_id}


# --- Requests ---
@app.get("/api/requests")
async def list_requests(status: str = None, limit: int = 50):
    db = await get_db()
    if status:
        rows = await (await db.execute(
            "SELECT * FROM requests WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)
        )).fetchall()
    else:
        rows = await (await db.execute(
            "SELECT * FROM requests ORDER BY id DESC LIMIT ?", (limit,)
        )).fetchall()
    return [dict(r) for r in rows]


@app.put("/api/requests/{request_id}/status")
async def update_request_status(request_id: int, status: str = Form(...)):
    db = await get_db()
    await db.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
    await db.commit()
    return {"id": request_id, "status": status}


@app.delete("/api/requests/{request_id}")
async def delete_request(request_id: int):
    db = await get_db()
    await db.execute("DELETE FROM requests WHERE id=?", (request_id,))
    await db.commit()
    return {"deleted": request_id}


# --- Leaderboard ---
@app.get("/api/leaderboard")
async def leaderboard(limit: int = 20):
    db = await get_db()
    rows = await (await db.execute(
        "SELECT * FROM users ORDER BY prints_shared DESC LIMIT ?", (limit,)
    )).fetchall()
    return [dict(r) for r in rows]


# --- Stats ---
@app.get("/api/stats")
async def stats():
    db = await get_db()
    prints = await (await db.execute("SELECT COUNT(*) as c FROM prints")).fetchone()
    reviews = await (await db.execute("SELECT COUNT(*) as c FROM reviews")).fetchone()
    requests_open = await (await db.execute("SELECT COUNT(*) as c FROM requests WHERE status='open'")).fetchone()
    users = await (await db.execute("SELECT COUNT(*) as c FROM users")).fetchone()
    return {
        "total_prints": prints["c"],
        "total_reviews": reviews["c"],
        "open_requests": requests_open["c"],
        "total_users": users["c"],
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
            "cam_port": os.getenv("CAM_SERVER_PORT", "8001"),
        },
    }


# --- Health ---
@app.get("/api/health")
async def health():
    db = await get_db()
    await (await db.execute("SELECT 1")).fetchone()
    return {"status": "healthy", "db": DB_PATH, "timestamp": datetime.utcnow().isoformat()}


# --- Camera stream proxy ---
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


# --- Static dashboard ---
if os.path.isdir(DASHBOARD_DIR):
    app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")

