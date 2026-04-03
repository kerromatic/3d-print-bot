"""Channel posting logic — routes content to the correct Telegram channels."""

from telegram import Bot
from io import BytesIO

from config.settings import settings
from utils.helpers import format_print_card, format_review_card, format_request_card, format_tip
from utils.image_utils import fetch_image_from_url, load_image_from_path, resize_for_telegram


async def post_new_print(bot: Bot, print_data: dict, image=None) -> int | None:
    caption = format_print_card(print_data)
    channel = settings.CHANNEL_ANNOUNCEMENTS
    photo = await _resolve_image(image)
    if photo:
        photo = resize_for_telegram(photo)
        msg = await bot.send_photo(chat_id=channel, photo=photo, caption=caption, parse_mode="HTML")
    else:
        msg = await bot.send_message(chat_id=channel, text=caption, parse_mode="HTML")
    return msg.message_id


async def post_to_gallery(bot: Bot, image, caption: str = "") -> int | None:
    photo = await _resolve_image(image)
    if not photo:
        return None
    photo = resize_for_telegram(photo)
    msg = await bot.send_photo(chat_id=settings.CHANNEL_GALLERY, photo=photo, caption=caption, parse_mode="HTML")
    return msg.message_id


async def post_review(bot: Bot, review: dict, print_name: str = "") -> int | None:
    text = format_review_card(review, print_name)
    msg = await bot.send_message(chat_id=settings.CHANNEL_REVIEWS, text=text, parse_mode="HTML")
    return msg.message_id


async def post_request(bot: Bot, request: dict) -> int | None:
    text = format_request_card(request)
    msg = await bot.send_message(chat_id=settings.CHANNEL_REQUESTS, text=text, parse_mode="HTML")
    return msg.message_id


async def post_tip(bot: Bot, tip: dict) -> int | None:
    text = format_tip(tip)
    msg = await bot.send_message(chat_id=settings.CHANNEL_TIPS, text=text, parse_mode="HTML")
    return msg.message_id


async def post_potd(bot: Bot, print_data: dict, avg_rating=None) -> int | None:
    caption = "\ud83c\udf1f <b>Print of the Day!</b> \ud83c\udf1f\n\n" + format_print_card(print_data, avg_rating)
    channel = settings.CHANNEL_ANNOUNCEMENTS
    photo = await _resolve_image(print_data.get("image_path"))
    if photo:
        photo = resize_for_telegram(photo)
        msg = await bot.send_photo(chat_id=channel, photo=photo, caption=caption, parse_mode="HTML")
    else:
        msg = await bot.send_message(chat_id=channel, text=caption, parse_mode="HTML")
    return msg.message_id


async def _resolve_image(image) -> BytesIO | None:
    if image is None:
        return None
    if isinstance(image, BytesIO):
        image.seek(0)
        return image
    if isinstance(image, str):
        if image.startswith(("http://", "https://")):
            return await fetch_image_from_url(image)
        else:
            return load_image_from_path(image)
    return None
