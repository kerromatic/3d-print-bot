import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


class Settings:
    """Central configuration loaded from environment variables."""

    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # Group (all topics live in the same supergroup)
    MAIN_GROUP: int = int(os.getenv("MAIN_GROUP", "0"))

    # Topic thread IDs within the supergroup
    TOPIC_ANNOUNCEMENTS: int = int(os.getenv("TOPIC_ANNOUNCEMENTS", "0"))
    TOPIC_GALLERY: int = int(os.getenv("TOPIC_GALLERY", "0"))
    TOPIC_REVIEWS: int = int(os.getenv("TOPIC_REVIEWS", "0"))
    TOPIC_TIPS: int = int(os.getenv("TOPIC_TIPS", "0"))
    TOPIC_REQUESTS: int = int(os.getenv("TOPIC_REQUESTS", "0"))
    TOPIC_POLLS: int = int(os.getenv("TOPIC_POLLS", "0"))
    TOPIC_GENERAL: int = int(os.getenv("TOPIC_GENERAL", "0"))

    # Camera (Bambu Lab X1C)
    PRINTER_IP: str = os.getenv("PRINTER_IP", "")
    PRINTER_ACCESS_CODE: str = os.getenv("PRINTER_ACCESS_CODE", "")
    PRINTER_SERIAL: str = os.getenv("PRINTER_SERIAL", "")
    TOPIC_LIVECAM: int = int(os.getenv("TOPIC_LIVECAM", "0"))
    CAM_SERVER_PORT: str = os.getenv("CAM_SERVER_PORT", "8001")
    CAM_SNAPSHOT_INTERVAL: int = int(os.getenv("CAM_SNAPSHOT_INTERVAL", "600"))

    # Dashboard auth
    DASH_USERNAME: str = os.getenv("DASH_USERNAME", "admin")
    DASH_PASSWORD: str = os.getenv("DASH_PASSWORD", "")

    # Public cam URL (set after ngrok setup)
    CAM_PUBLIC_URL: str = os.getenv("CAM_PUBLIC_URL", "")

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
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


class Settings:
    """Central configuration loaded from environment variables."""

    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # Group (all topics live in the same supergroup)
    MAIN_GROUP: int = int(os.getenv("MAIN_GROUP", "0"))

    # Topic thread IDs within the supergroup
    TOPIC_ANNOUNCEMENTS: int = int(os.getenv("TOPIC_ANNOUNCEMENTS", "0"))
    TOPIC_GALLERY: int = int(os.getenv("TOPIC_GALLERY", "0"))
    TOPIC_REVIEWS: int = int(os.getenv("TOPIC_REVIEWS", "0"))
    TOPIC_TIPS: int = int(os.getenv("TOPIC_TIPS", "0"))
    TOPIC_REQUESTS: int = int(os.getenv("TOPIC_REQUESTS", "0"))
    TOPIC_POLLS: int = int(os.getenv("TOPIC_POLLS", "0"))
    TOPIC_GENERAL: int = int(os.getenv("TOPIC_GENERAL", "0"))

    # Camera (Bambu Lab X1C)
    PRINTER_IP: str = os.getenv("PRINTER_IP", "")
    PRINTER_ACCESS_CODE: str = os.getenv("PRINTER_ACCESS_CODE", "")
    TOPIC_LIVECAM: int = int(os.getenv("TOPIC_LIVECAM", "0"))
    CAM_SERVER_PORT: str = os.getenv("CAM_SERVER_PORT", "8001")
    CAM_SNAPSHOT_INTERVAL: int = int(os.getenv("CAM_SNAPSHOT_INTERVAL", "600"))

    # Dashboard auth
    DASH_USERNAME: str = os.getenv("DASH_USERNAME", "admin")
    DASH_PASSWORD: str = os.getenv("DASH_PASSWORD", "")

    # Public cam URL (set after ngrok setup)
    CAM_PUBLIC_URL: str = os.getenv("CAM_PUBLIC_URL", "")

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
