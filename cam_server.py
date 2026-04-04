"""Standalone camera-only web server for public live feed.

This runs on a separate port (8001) from the dashboard (8000).
Only exposes the camera feed - no dashboard, no API, no database.
Safe to expose via ngrok for customers.
"""

import asyncio
import os
import shutil
import subprocess
import signal
import sys
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from config.settings import settings

app = FastAPI(title="Guapo Prints Live Cam", docs_url=None, redoc_url=None)


def get_rtsp_url() -> str:
    return f"rtsps://bblp:{settings.PRINTER_ACCESS_CODE}@{settings.PRINTER_IP}:322/streaming/live/1"


def _find_ffmpeg() -> str:
    """Find ffmpeg executable, checking common Windows install locations."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    common_paths = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    for path in common_paths:
        if os.path.isfile(path):
            return path
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
            sys_path = winreg.QueryValueEx(key, "Path")[0]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            user_path = winreg.QueryValueEx(key, "Path")[0]
        fresh_path = sys_path + ";" + user_path
        for d in fresh_path.split(";"):
            candidate = os.path.join(d.strip(), "ffmpeg.exe")
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass
    return "ffmpeg"


async def generate_mjpeg():
    """Stream MJPEG frames from the printer camera via ffmpeg."""
    rtsp_url = get_rtsp_url()
    
    ffmpeg_path = _find_ffmpeg()
    cmd = [
        ffmpeg_path,
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-f", "mjpeg",
        "-q:v", "5",
        "-r", "10",
        "-an",
        "pipe:1",
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    try:
        buffer = b""
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                break
            buffer += chunk
            
            # Find JPEG boundaries (SOI: FFD8, EOI: FFD9)
            while True:
                start = buffer.find(b"\xff\xd8")
                end = buffer.find(b"\xff\xd9", start + 2) if start != -1 else -1
                
                if start != -1 and end != -1:
                    frame = buffer[start:end + 2]
                    buffer = buffer[end + 2:]
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
                else:
                    break
    finally:
        process.kill()
        await process.wait()


@app.get("/stream")
async def video_stream():
    """MJPEG stream endpoint."""
    return StreamingResponse(
        generate_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/live", response_class=HTMLResponse)
async def live_page():
    """Public-facing live camera page. Clean, branded, camera-only."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Guapo Prints! - Live Cam</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #0a0a0a;
    color: #e0e0e0;
    font-family: 'Segoe UI', sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  .header {
    text-align: center;
    padding: 20px;
  }
  .header h1 {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 2px;
    color: #c45a2c;
  }
  .header p {
    font-size: 12px;
    color: #555;
    text-transform: uppercase;
    letter-spacing: 3px;
    margin-top: 4px;
  }
  .cam-container {
    position: relative;
    max-width: 960px;
    width: 95%;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #262626;
    background: #141414;
  }
  .cam-container img {
    width: 100%;
    display: block;
  }
  .live-badge {
    position: absolute;
    top: 12px;
    left: 12px;
    background: rgba(220, 38, 38, 0.9);
    color: white;
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .live-dot {
    width: 8px;
    height: 8px;
    background: white;
    border-radius: 50%;
    animation: pulse 1.5s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }
  .footer {
    text-align: center;
    padding: 16px;
    font-size: 11px;
    color: #333;
    letter-spacing: 1px;
  }
  .footer a {
    color: #c45a2c;
    text-decoration: none;
  }
  .offline {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 400px;
    font-size: 16px;
    color: #555;
  }
</style>
</head>
<body>
<div class="header">
  <h1>GUAPO PRINTS!</h1>
  <p>Live Print Camera</p>
</div>
<div class="cam-container">
  <img id="stream" src="/stream" alt="Live Camera Feed"
    onerror="this.style.display='none'; document.getElementById('offline').style.display='flex';" />
  <div id="offline" class="offline" style="display:none;">
    Camera is offline or no print in progress
  </div>
  <div class="live-badge">
    <span class="live-dot"></span>
    LIVE
  </div>
</div>
<div class="footer">
  Powered by <a href="https://t.me/LayerGOD_bot">LayerGOD</a> | Guapo Prints!
</div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirect root to live page."""
    return '<meta http-equiv="refresh" content="0;url=/live">'


def run_cam_server():
    """Run the camera server on port 8001."""
    import uvicorn
    uvicorn.run(
        "cam_server:app",
        host="0.0.0.0",
        port=int(settings.CAM_SERVER_PORT),
        log_level="warning",
    )
