from telegram import User


def star_rating(rating: int) -> str:
    return "\u2b50" * rating + "\u2606" * (5 - rating)


def format_print_card(print_data: dict, avg_rating: float | None = None) -> str:
    lines = [f"\ud83d\udda8\ufe0f <b>{print_data['name']}</b>"]
    if print_data.get("description"):
        lines.append(f"\n{print_data['description']}")
    if print_data.get("material"):
        lines.append(f"\n\ud83e\uddf5 Material: {print_data['material']}")
    if print_data.get("printer"):
        lines.append(f"\ud83d\udd27 Printer: {print_data['printer']}")
    if print_data.get("tags"):
        tag_str = " ".join(f"#{t.strip()}" for t in print_data["tags"].split(",") if t.strip())
        lines.append(f"\ud83c\udff7\ufe0f {tag_str}")
    if print_data.get("stl_link"):
        lines.append(f'\n\ud83d\udcce <a href="{print_data["stl_link"]}">Download STL</a>')
    if avg_rating is not None:
        lines.append(f"\n{star_rating(round(avg_rating))} ({avg_rating}/5)")
    return "\n".join(lines)


def format_review_card(review: dict, print_name: str = "") -> str:
    header = "\ud83d\udcdd Review"
    if print_name:
        header += f" for <b>{print_name}</b>"
    return (
        f"{header}\n"
        f"{star_rating(review['rating'])} ({review['rating']}/5)\n\n"
        f'"{review["text"]}"\n'
        f"\u2014 @{review['username']}"
    )


def format_request_card(request: dict) -> str:
    status_emoji = "\ud83d\udfe2" if request["status"] == "open" else "\ud83d\udfe1"
    return (
        f"{status_emoji} <b>Print Request #{request['id']}</b>\n\n"
        f"{request['description']}\n\n"
        f"Requested by: @{request['username']}\n"
        f"Status: {request['status'].title()}"
    )


def format_leaderboard(users: list[dict]) -> str:
    if not users:
        return "No contributors yet!"
    medals = ["\ud83e\udd47", "\ud83e\udd48", "\ud83e\udd49"]
    lines = ["\ud83c\udfc6 <b>Community Leaderboard</b>\n"]
    for i, user in enumerate(users):
        prefix = medals[i] if i < 3 else f"  {i + 1}."
        name = user.get("display_name") or user.get("username") or "Unknown"
        score = user.get("score", 0)
        lines.append(
            f"{prefix} <b>{name}</b> \u2014 {score} pts "
            f"(\ud83d\udda8\ufe0f{user['prints_shared']} \ud83d\udcdd{user['reviews_given']} \ud83e\udd1d{user['requests_fulfilled']})"
        )
    return "\n".join(lines)


def format_tip(tip: dict) -> str:
    tags = " ".join(f"#{t}" for t in tip.get("tags", []))
    return f"\ud83d\udca1 <b>Tip: {tip['title']}</b>\n\n{tip['text']}\n\n{tags}"


def get_user_display(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name or "Unknown"


def truncate(text: str, max_len: int = 200) -> str:
    return text if len(text) <= max_len else text[: max_len - 3] + "..."
