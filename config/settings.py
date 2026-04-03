import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


class Settings:
    """Central configuration loaded from environment variables."""

    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    CHANNEL_ANNOUNCEMENTS: int = int(os.getenv("CHANNEL_ANNOUNCEMENTS", "0"))
    CHANNEL_GALLERY: int = int(os.getenv("CHANNEL_GALLERY", "0"))
    CHANNEL_REVIEWS: int = int(os.getenv("CHANNEL_REVIEWS", "0"))
    CHANNEL_TIPS: int = int(os.getenv("CHANNEL_TIPS", "0"))
    CHANNEL_REQUESTS: int = int(os.getenv("CHANNEL_REQUESTS", "0"))
    CHANNEL_POLLS: int = int(os.getenv("CHANNEL_POLLS", "0"))
    MAIN_GROUP: int = int(os.getenv("MAIN_GROUP", "0"))

    ADMIN_IDS: list[int] = [
        int(x.strip())
        for x in os.getenv("ADMIN_IDS", "0").split(",")
        if x.strip()
    ]

    IMAGE_SOURCE_PATH: str = os.getenv("IMAGE_SOURCE_PATH", "./assets/prints/")
    IMAGE_SOURCE_URL: str = os.getenv("IMAGE_SOURCE_URL", "")

    POTD_TIME: str = os.getenv("POTD_TIME", "09:00")
    TIP_TIME: str = os.getenv("TIP_TIME", "12:00")
    TIMEZONE: str = os.getenv("TIMEZONE", "America/New_York")

    DB_PATH: str = os.getenv("DB_PATH", "./data/bot.db")

    @classmethod
    def channel_directory(cls) -> dict[str, int]:
        return {
            "announcements": cls.CHANNEL_ANNOUNCEMENTS,
            "gallery": cls.CHANNEL_GALLERY,
            "reviews": cls.CHANNEL_REVIEWS,
            "tips": cls.CHANNEL_TIPS,
            "requests": cls.CHANNEL_REQUESTS,
            "polls": cls.CHANNEL_POLLS,
            "general": cls.MAIN_GROUP,
        }

    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        return user_id in cls.ADMIN_IDS

    @classmethod
    def validate(cls) -> list[str]:
        issues = []
        if not cls.BOT_TOKEN or cls.BOT_TOKEN == "your_bot_token_here":
            issues.append("BOT_TOKEN is not set")
        if cls.MAIN_GROUP == 0:
            issues.append("MAIN_GROUP chat ID is not set")
        return issues


settings = Settings()
