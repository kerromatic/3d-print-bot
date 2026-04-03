"""Inline keyboard callback handlers."""

from telegram import Update
from telegram.ext import ContextTypes

from config.settings import settings


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route inline button callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    db = context.bot_data["db"]

    if data.startswith("claim_"):
        request_id = int(data.split("_")[1])
        user_id = query.from_user.id
        success = await db.claim_request(request_id, user_id)

        if success:
            await db._increment_user_stat(
                user_id, query.from_user.username or "", "requests_fulfilled"
            )
            await query.edit_message_text(
                f"{query.message.text}\n\n\u2705 Claimed by @{query.from_user.username}!",
            )
        else:
            await query.answer("This request has already been claimed!", show_alert=True)
