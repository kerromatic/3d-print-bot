"""Telegram command handlers."""

import json
import random
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config.settings import settings
from utils.helpers import (
    format_print_card, format_leaderboard, format_tip,
    get_user_display, star_rating,
)
from bot.posting import post_new_print, post_to_gallery, post_review, post_request

TIPS_PATH = Path(__file__).parent.parent / "config" / "tips.json"
TIPS = []
if TIPS_PATH.exists():
    TIPS = json.loads(TIPS_PATH.read_text()).get("tips", [])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    await db.upsert_user(update.effective_user.id, update.effective_user.username or "", update.effective_user.full_name or "")
    text = (
        "\ud83d\udc4b <b>Welcome to the 3D Print Hub!</b>\n\n"
        "I help manage this community \u2014 posting prints, collecting reviews, "
        "sharing tips, and tracking contributions.\n\n"
        "<b>\ud83d\udcc2 Channels:</b>\n"
        "\u2022 <b>Announcements</b> \u2014 New prints & community news\n"
        "\u2022 <b>Gallery</b> \u2014 Photo showcase\n"
        "\u2022 <b>Reviews</b> \u2014 Community ratings\n"
        "\u2022 <b>Tips & Tricks</b> \u2014 Daily 3D printing tips\n"
        "\u2022 <b>Requests</b> \u2014 Request a print\n"
        "\u2022 <b>Polls</b> \u2014 Community votes\n\n"
        "Type /help to see all commands!"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "\ud83e\udd16 <b>Available Commands</b>\n\n"
        "<b>Everyone:</b>\n"
        "/start \u2014 Welcome & channel info\n"
        "/help \u2014 This message\n"
        "/tip \u2014 Random 3D printing tip\n"
        "/search &lt;keyword&gt; \u2014 Search prints\n"
        "/review &lt;print_id&gt; &lt;1-5&gt; &lt;text&gt; \u2014 Submit a review\n"
        "/request &lt;description&gt; \u2014 Request a print\n"
        "/leaderboard \u2014 Top contributors\n"
        "/stats \u2014 Community stats\n"
        "/troubleshoot &lt;issue&gt; \u2014 Quick fix suggestions\n\n"
        "<b>Admins:</b>\n"
        "/newprint \u2014 Post a new print (reply to a photo)\n"
        "/postimage \u2014 Post image to gallery (reply to a photo)\n"
        "/poll &lt;question&gt; | &lt;option1&gt; | &lt;option2&gt; ... \u2014 Create a poll\n"
        "/potd \u2014 Trigger Print of the Day\n"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def newprint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not settings.is_admin(update.effective_user.id):
        await update.message.reply_text("\u26d4 Admin only command.")
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: Reply to a photo with:\n"
            "<code>/newprint Name | Description | Material | Printer | tags | STL_URL</code>\n"
            "Only Name is required.", parse_mode="HTML")
        return
    raw = " ".join(context.args)
    parts = [p.strip() for p in raw.split("|")]
    name = parts[0]
    description = parts[1] if len(parts) > 1 else ""
    material = parts[2] if len(parts) > 2 else ""
    printer = parts[3] if len(parts) > 3 else ""
    tags = parts[4] if len(parts) > 4 else ""
    stl_link = parts[5] if len(parts) > 5 else ""
    db = context.bot_data["db"]
    image_path = ""
    reply = update.message.reply_to_message
    if reply and reply.photo:
        photo = reply.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_path = file.file_path
    print_data = {"name": name, "description": description, "material": material, "printer": printer, "tags": tags, "stl_link": stl_link, "image_path": image_path}
    print_id = await db.add_print(name=name, description=description, image_path=image_path, tags=tags, printer=printer, material=material, stl_link=stl_link, posted_by=update.effective_user.id)
    await post_new_print(context.bot, print_data, image_path or None)
    await db._increment_user_stat(update.effective_user.id, update.effective_user.username or "", "prints_shared")
    await update.message.reply_text(f'\u2705 Print <b>#{print_id}</b> \u2014 "{name}" posted!', parse_mode="HTML")


async def postimage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not settings.is_admin(update.effective_user.id):
        await update.message.reply_text("\u26d4 Admin only command.")
        return
    reply = update.message.reply_to_message
    if not reply or not reply.photo:
        await update.message.reply_text("Reply to a photo with /postimage [optional caption]")
        return
    caption = " ".join(context.args) if context.args else ""
    photo = reply.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    await post_to_gallery(context.bot, file.file_path, caption)
    await update.message.reply_text("\u2705 Posted to gallery!")


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: <code>/review &lt;print_id&gt; &lt;1-5&gt; &lt;your review&gt;</code>", parse_mode="HTML")
        return
    db = context.bot_data["db"]
    try:
        print_id = int(context.args[0])
        rating = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Print ID and rating must be numbers.")
        return
    if not 1 <= rating <= 5:
        await update.message.reply_text("Rating must be between 1 and 5.")
        return
    print_data = await db.get_print(print_id)
    if not print_data:
        await update.message.reply_text(f"Print #{print_id} not found.")
        return
    review_text = " ".join(context.args[2:])
    user = update.effective_user
    await db.add_review(print_id=print_id, user_id=user.id, username=user.username or user.full_name, rating=rating, text=review_text)
    review_data = {"rating": rating, "text": review_text, "username": user.username or user.full_name}
    await post_review(context.bot, review_data, print_data["name"])
    await update.message.reply_text(f"\u2705 Review submitted! {star_rating(rating)} for <b>{print_data['name']}</b>", parse_mode="HTML")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search <keyword>")
        return
    db = context.bot_data["db"]
    keyword = " ".join(context.args)
    results = await db.search_prints(keyword)
    if not results:
        await update.message.reply_text(f'No prints found for "{keyword}".')
        return
    lines = [f'\ud83d\udd0d <b>Results for "{keyword}"</b>\n']
    for p in results[:10]:
        avg = await db.get_average_rating(p["id"])
        rating_str = f" \u2014 {star_rating(round(avg))}" if avg else ""
        lines.append(f"\u2022 <b>#{p['id']}</b> {p['name']}{rating_str}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def request_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /request <describe what you need printed>")
        return
    db = context.bot_data["db"]
    user = update.effective_user
    description = " ".join(context.args)
    req_id = await db.add_request(user_id=user.id, username=user.username or user.full_name, description=description)
    request_data = {"id": req_id, "description": description, "username": user.username or user.full_name, "status": "open"}
    await post_request(context.bot, request_data)
    await update.message.reply_text(f"\u2705 Request <b>#{req_id}</b> posted!", parse_mode="HTML")


async def tip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not TIPS:
        await update.message.reply_text("No tips loaded.")
        return
    tip = random.choice(TIPS)
    await update.message.reply_text(format_tip(tip), parse_mode="HTML")


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    users = await db.get_leaderboard()
    await update.message.reply_text(format_leaderboard(users), parse_mode="HTML")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    prints = await db.get_print_count()
    reviews = await db.get_review_count()
    users = await db.get_user_count()
    text = f"\ud83d\udcca <b>Community Stats</b>\n\n\ud83d\udda8\ufe0f Prints shared: {prints}\n\ud83d\udcdd Reviews written: {reviews}\n\ud83d\udc65 Members tracked: {users}\n"
    await update.message.reply_text(text, parse_mode="HTML")


async def poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not settings.is_admin(update.effective_user.id):
        await update.message.reply_text("\u26d4 Admin only command.")
        return
    raw = " ".join(context.args) if context.args else ""
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 3:
        await update.message.reply_text("Usage: <code>/poll Question | Option1 | Option2 | ...</code>", parse_mode="HTML")
        return
    await context.bot.send_poll(chat_id=settings.CHANNEL_POLLS, question=parts[0], options=parts[1:], is_anonymous=False)
    await update.message.reply_text("\u2705 Poll posted!")


TROUBLESHOOT_DB = {
    "stringing": "\ud83e\uddf5 <b>Stringing Fix</b>\n\n\u2022 Lower nozzle temp by 5-10\u00b0C\n\u2022 Retraction: 0.8-1.2mm (direct drive) or 4-6mm (Bowden)\n\u2022 Increase retraction speed to 35-45mm/s\n\u2022 Enable wipe/coasting\n\u2022 Dry your filament",
    "warping": "\ud83c\udf0a <b>Warping Fix</b>\n\n\u2022 Increase bed temp by 5\u00b0C\n\u2022 Use brim or raft\n\u2022 Clean bed with IPA\n\u2022 Use enclosure for ABS/ASA\n\u2022 Reduce fan for first 3-5 layers",
    "adhesion": "\ud83d\udd17 <b>Bed Adhesion Fix</b>\n\n\u2022 Clean bed with IPA\n\u2022 Re-level / re-run mesh\n\u2022 Slow first layer to 15-20mm/s\n\u2022 Increase first layer width to 120%\n\u2022 Use glue stick or hairspray",
    "layer": "\ud83d\udcd0 <b>Layer Shift Fix</b>\n\n\u2022 Check belt tension\n\u2022 Tighten grub screws on pulleys\n\u2022 Lower acceleration/jerk\n\u2022 Check for obstructions\n\u2022 Ensure stepper current is adequate",
    "clog": "\ud83d\udd27 <b>Nozzle Clog Fix</b>\n\n\u2022 Cold pull: heat to 200\u00b0C, push filament, cool to 90\u00b0C, pull\n\u2022 Use acupuncture needle\n\u2022 Check heat creep (hotend fan)\n\u2022 Replace nozzle every ~1kg for brass",
    "elephant": "\ud83d\udc18 <b>Elephant's Foot Fix</b>\n\n\u2022 Lower bed temp by 5\u00b0C\n\u2022 Increase Z-offset 0.02-0.05mm\n\u2022 Add chamfer to model\n\u2022 Use elephant foot compensation in slicer",
}

async def troubleshoot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        issues = ", ".join(TROUBLESHOOT_DB.keys())
        await update.message.reply_text(f"Usage: /troubleshoot <issue>\n\nAvailable: {issues}")
        return
    keyword = context.args[0].lower()
    for key, text in TROUBLESHOOT_DB.items():
        if keyword in key or key in keyword:
            await update.message.reply_text(text, parse_mode="HTML")
            return
    issues = ", ".join(TROUBLESHOOT_DB.keys())
    await update.message.reply_text(f"Issue not found. Available: {issues}")


async def potd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not settings.is_admin(update.effective_user.id):
        await update.message.reply_text("\u26d4 Admin only command.")
        return
    from bot.scheduler import run_potd
    await run_potd(context)
    await update.message.reply_text("\u2705 Print of the Day posted!")


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        db = context.bot_data["db"]
        await db.upsert_user(member.id, member.username or "", member.full_name or "")
        name = member.full_name or member.username or "friend"
        text = (
            f"\ud83d\udc4b Welcome to <b>3D Print Hub</b>, {name}!\n\n"
            "Check out our channels, share your prints, and join the conversation.\n"
            "Type /help to see what I can do!"
        )
        await update.message.reply_text(text, parse_mode="HTML")
