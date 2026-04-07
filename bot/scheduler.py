import os
"""Scheduled tasks - Print of the Day, Tip of the Day, auto-gallery."""

import json
import random
from pathlib import Path
from datetime import time
from zoneinfo import ZoneInfo

from telegram.ext import ContextTypes

from config.settings import settings
from bot.posting import post_potd, post_tip, post_to_gallery
from utils.image_utils import get_pending_images, mark_as_posted, load_image_from_path
from bot.camera import capture_snapshot
from bot.printer_mqtt import printer_status

# Load tips
TIPS_PATH = Path(__file__).parent.parent / "config" / "tips.json"
TIPS = []
if TIPS_PATH.exists():
    TIPS = json.loads(TIPS_PATH.read_text())

# Dynamic snapshot interval (can be changed from dashboard)
_snapshot_interval = settings.CAM_SNAPSHOT_INTERVAL


def get_snapshot_interval() -> int:
    """Get the current snapshot interval in seconds."""
    return _snapshot_interval


def set_snapshot_interval(seconds: int):
    """Set the snapshot interval in seconds (minimum 60)."""
    global _snapshot_interval
    _snapshot_interval = max(60, seconds)


async def run_potd(context: ContextTypes.DEFAULT_TYPE):
    """Post print of the day."""
    images = get_pending_images(os.getenv("UPLOADS_DIR", "./assets/prints"))
    if not images:
        return
    chosen = random.choice(images)
    photo = load_image_from_path(chosen["path"])
    if photo:
        await post_potd(context.bot, photo, chosen.get("caption", ""))
        mark_as_posted(chosen["id"])


async def run_tip_of_the_day(context: ContextTypes.DEFAULT_TYPE):
    """Post a random tip."""
    if not TIPS:
        return
    tip = random.choice(TIPS)
    title = tip.get("title", "Tip")
    body = tip.get("body", "")
    text = f"<b>{title}</b>\n\n{body}"
    await post_tip(context.bot, text)


async def run_gallery_scan(context: ContextTypes.DEFAULT_TYPE):
    """Scan for new images and post them to the gallery."""
    images = get_pending_images(str(settings.UPLOADS_DIR))
    for img in images[:3]:
        photo = load_image_from_path(img["path"])
        if photo:
            await post_to_gallery(context.bot, photo, img.get("caption", ""))
            mark_as_posted(img["id"])


async def run_cam_snapshot(context: ContextTypes.DEFAULT_TYPE):
    """Capture and post a snapshot to Live Prints - only when actively printing."""
    if not settings.PRINTER_IP or not settings.PRINTER_ACCESS_CODE:
        return
    if not settings.TOPIC_LIVECAM:
        return

    # Only post snapshots when the printer is actively printing
    if not printer_status.is_printing:
        return

    snapshot = await capture_snapshot()
    if snapshot:
        # Use rich caption from MQTT data
        caption = printer_status.caption_for_snapshot()
        await context.bot.send_photo(
            chat_id=settings.MAIN_GROUP,
            message_thread_id=settings.TOPIC_LIVECAM,
            photo=snapshot,
            caption=caption,
            parse_mode="HTML",
        )


def schedule_jobs(job_queue):
    """Register all scheduled jobs with the bot's job queue."""
    tz = ZoneInfo(settings.TIMEZONE)

    # Print of the Day
    h, m = map(int, settings.POTD_TIME.split(":"))
    job_queue.run_daily(run_potd, time=time(h, m, tzinfo=tz), name="potd")

    # Tip of the Day
    h, m = map(int, settings.TIP_TIME.split(":"))
    job_queue.run_daily(run_tip_of_the_day, time=time(h, m, tzinfo=tz), name="tip")

    # Camera snapshot
    if settings.PRINTER_IP and settings.TOPIC_LIVECAM:
        job_queue.run_repeating(
            run_cam_snapshot,
            interval=_snapshot_interval,
            first=30,
            name="cam_snapshot",
        )

    # Gallery scan every 30 minutes
    try:
        job_queue.run_repeating(run_gallery_scan, interval=1800, first=10, name="gallery_scan")
    except Exception:
        pass
