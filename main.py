"""3D Print Hub â Telegram Bot Entry Point."""

import logging
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from config.settings import settings
from utils.database import Database
from bot.handlers import (
    start_command,
    help_command,
    newprint_command,
    postimage_command,
    review_command,
    request_command,
    catalog_command,
    orderstatus_command,
    materials_command,
    pricing_command,
    faq_command,
    leaderboard_command,
    stats_command,
    poll_command,
    troubleshoot_command,
    potd_command,
    welcome_new_member,
)
from bot.callbacks import callback_handler
from bot.scheduler import schedule_jobs

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application):
    db = Database(settings.DB_PATH)
    await db.connect()
    application.bot_data["db"] = db
    logger.info("Database connected at %s", settings.DB_PATH)
    schedule_jobs(application.job_queue)
    logger.info("Scheduled jobs registered")


async def post_shutdown(application):
    db = application.bot_data.get("db")
    if db:
        await db.close()
        logger.info("Database closed")


def main():
    issues = settings.validate()
    if issues:
        for issue in issues:
            logger.error("Config issue: %s", issue)
        print("\nâ ï¸  Fix the issues above in config/.env before running the bot.\n")
        return

    app = (
        ApplicationBuilder()
        .token(settings.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("newprint", newprint_command))
    app.add_handler(CommandHandler("postimage", postimage_command))
    app.add_handler(CommandHandler("review", review_command))
    app.add_handler(CommandHandler("request", request_command))
    app.add_handler(CommandHandler("catalog", catalog_command))
    app.add_handler(CommandHandler("orderstatus", orderstatus_command))
    app.add_handler(CommandHandler("materials", materials_command))
    app.add_handler(CommandHandler("pricing", pricing_command))
    app.add_handler(CommandHandler("faq", faq_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("poll", poll_command))
    app.add_handler(CommandHandler("troubleshoot", troubleshoot_command))
    app.add_handler(CommandHandler("potd", potd_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member)
    )

    logger.info("ð¨ï¸ 3D Print Hub Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
