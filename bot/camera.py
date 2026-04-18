"""Camera integration for Bambu Lab X1C printer."""

import asyncio
import shutil
import subprocess
import tempfile
import logging
import os
from io import BytesIO
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)


def _find_ffmpeg() -> str:
    """Find ffmpeg executable, checking common Windows install locations."""
    # First check if it's in PATH
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    
    # Check common Windows locations
    common_paths = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    
    for path in common_paths:
        if os.path.isfile(path):
            return path
    
    # Try refreshing PATH from registry (Windows)
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
    
    return "ffmpeg"  # Fall back to hoping it's in PATH


def get_rtsp_url() -> str:
    """Build the RTSPS URL for the Bambu Lab printer camera."""
    return f"rtsps://bblp:{settings.PRINTER_ACCESS_CODE}@{settings.PRINTER_IP}:322/streaming/live/1"


async def capture_snapshot() -> BytesIO | None:
    """Capture a single JPEG frame from the cam server MJPEG stream.

    Reads the first complete JPEG frame from the already-running cam server
    at localhost:8001/stream. Falls back to direct ffmpeg RTSPS if unavailable.
    Returns a BytesIO containing the JPEG image, or None on failure.
    """
    if not settings.PRINTER_IP or not settings.PRINTER_ACCESS_CODE:
        logger.warning("Printer IP or access code not configured")
        return None

    cam_port = getattr(settings, "CAM_SERVER_PORT", "8001")
    stream_url = f"http://localhost:{cam_port}/stream"

    try:
        # Read raw MJPEG stream and extract first complete JPEG frame
        import urllib.request
        with urllib.request.urlopen(stream_url, timeout=10) as resp:
            raw = b""
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                raw += chunk
                # Look for JPEG start (FFD8) and end (FFD9) markers
                start = raw.find(b"\xff\xd8")
                if start != -1:
                    end = raw.find(b"\xff\xd9", start + 2)
                    if end != -1:
                        jpeg_data = raw[start:end + 2]
                        buf = BytesIO(jpeg_data)
                        buf.seek(0)
                        logger.info("Snapshot captured from cam server MJPEG stream")
                        return buf
                # Safety limit - don't read more than 2MB
                if len(raw) > 2 * 1024 * 1024:
                    break
        logger.warning("Could not extract JPEG frame from MJPEG stream, trying direct RTSPS")
    except Exception as e:
        logger.warning(f"Cam server snapshot error: {e}, trying direct RTSPS")

    # Fallback: direct RTSPS connection
    try:
        rtsp_url = get_rtsp_url()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        proc2 = await asyncio.create_subprocess_exec(
            _find_ffmpeg(),
            "-rtsp_transport", "tcp",
            "-i", rtsp_url,
            "-vframes", "1",
            "-q:v", "2",
            "-y", tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=30)

        tmp_file = Path(tmp_path)
        if tmp_file.exists() and tmp_file.stat().st_size > 0:
            buf2 = BytesIO(tmp_file.read_bytes())
            buf2.seek(0)
            tmp_file.unlink()
            logger.info("Snapshot captured via direct RTSPS fallback")
            return buf2

        logger.error(f"Direct RTSPS also failed: {stderr2.decode()[-100:]}")
        return None

    except asyncio.TimeoutError:
        logger.error("Direct RTSPS snapshot timed out")
        return None
    except Exception as e:
        logger.error(f"Direct RTSPS snapshot error: {e}")
        return None
    except FileNotFoundError:
        logger.error("ffmpeg not found. Install it: winget install ffmpeg")
        return None
    except Exception as e:
        logger.error(f"Snapshot capture failed: {e}")
        return None
