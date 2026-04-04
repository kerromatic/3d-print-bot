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
    """Capture a single frame from the printer camera using ffmpeg.
    
    Returns a BytesIO containing the JPEG image, or None on failure.
    """
    rtsp_url = get_rtsp_url()
    
    if not settings.PRINTER_IP or not settings.PRINTER_ACCESS_CODE:
        logger.warning("Printer IP or access code not configured")
        return None
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        
        # Use ffmpeg to grab a single frame from the RTSPS stream
        ffmpeg_path = _find_ffmpeg()
        cmd = [
            ffmpeg_path,
            "-rtsp_transport", "tcp",
            "-i", rtsp_url,
            "-frames:v", "1",
            "-update", "1",
            "-y",
            tmp_path,
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        
        if process.returncode != 0:
            logger.error(f"ffmpeg failed: {stderr.decode()[-200:]}")
            return None
        
        # Read the captured frame
        tmp_file = Path(tmp_path)
        if tmp_file.exists() and tmp_file.stat().st_size > 0:
            buf = BytesIO(tmp_file.read_bytes())
            buf.seek(0)
            tmp_file.unlink()
            return buf
        
        logger.error("Snapshot file is empty or missing")
        return None
        
    except asyncio.TimeoutError:
        logger.error("ffmpeg timed out capturing snapshot")
        return None
    except FileNotFoundError:
        logger.error("ffmpeg not found. Install it: winget install ffmpeg")
        return None
    except Exception as e:
        logger.error(f"Snapshot capture failed: {e}")
        return None
