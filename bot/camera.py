"""Camera integration for Bambu Lab X1C printer."""

import asyncio
import subprocess
import tempfile
import logging
from io import BytesIO
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)


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
        cmd = [
            "ffmpeg",
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
