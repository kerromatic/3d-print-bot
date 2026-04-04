"""Scheduled tasks Ã¢ÂÂ Print of the Day, Tip of the Day, auto-gallery."""

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

# Load tips
TIPS_PATH = Path(__file__).parent.parent / "config" / "tips.json"
TIPS = []
if TIPS_PATH.exists():
    TIPS = json.loads(TIPS_PATH.read_text()).get("tips", [])


async def run_potd(context: ContextTypes.DEFAULT_TYPE):
    """Select and post a random Print of the Day."""
    db = context.bot_data["db"]
    print_data = await db.get_random_print_for_potd()
    if not print_data:
        return  # No eligible prints

    avg_rating = await db.get_average_rating(print_data["id"])
    await post_potd(context.bot, print_data, avg_rating)
    await db.record_potd(print_data["id"])


async def run_tip_of_the_day(context: ContextTypes.DEFAULT_TYPE):
    """Post a random tip to the tips channel."""
    if not TIPS:
        return
    tip = random.choice(TIPS)
    await post_tip(context.bot, tip)


async def run_gallery_scan(context: ContextTypes.DEFAULT_TYPE):
    """Scan the local images folder and post any new images to gallery."""
    folder = settings.IMAGE_SOURCE_PATH
    new_images = get_pending_images(folder)

    for img_path in new_images:
        buf = load_image_from_path(img_path)
        if buf:
            filename = Path(img_path).stem.replace("_", " ").replace("-", " ").title()
            await post_to_gallery(context.bot, buf, caption=f"Ã°ÂÂÂ¸ {filename}")
            mark_as_posted(folder, Path(img_path).name)


async def run_cam_snapshot(context: ContextTypes.DEFAULT_TYPE):
    """Capture and post a snapshot from the printer camera to the Live Prints topic."""
    if not settings.PRINTER_IP or not settings.PRINTER_ACCESS_CODE:
        return
    if not settings.TOPIC_LIVECAM:
        return
    
    snapshot = await capture_snapshot()
    if snapshot:
        import datetime
        now = datetime.datetime.now().strftime("%I:%M %p")
        await context.bot.send_photo(
            chat_id=settings.MAIN_GROUP,
            message_thread_id=settings.TOPIC_LIVECAM,
            photo=snapshot,
            caption=f"Live snapshot at {now}",
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
            interval=settings.CAM_SNAPSHOT_INTERVAL,
            first=30,
            name="cam_snapshot",
        )

    # Gallery scan every 30 minutes
    job_queue.run_repeating(run_gallery_scan, interval=1800, first=10, name="gallery_scan")
