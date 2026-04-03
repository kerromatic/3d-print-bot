from telegram import User


def star_rating(rating: int) -> str:
    return "⭐" * rating + "☆" * (5 - rating)


def format_print_card(print_data: dict, avg_rating: float | None = None) -> str:
    lines = [f"🖨️ <b>{print_data['name']}</b>"]
    if print_data.get("description"):
        lines.append(f"\n{print_data['description']}")
    if print_data.get("material"):
        lines.append(f"\n🧵 Material: {print_data['material']}")
    if print_data.get("printer"):
        lines.append(f"🔧 Printer: {print_data['printer']}")
    if print_data.get("tags"):
        tag_str = " ".join(f"#{t.strip()}" for t in print_data["tags"].split(",") if t.strip())
        lines.append(f"🏷️ {tag_str}")
    if print_data.get("stl_link"):
        lines.append(f'\n📎 <a href="{print_data["stl_link"]}">Download STL</a>')
    if avg_rating is not None:
        lines.append(f"\n{star_rating(round(avg_rating))} ({avg_rating}/5)")
    return "\n".join(lines)


def format_review_card(review: dict, print_name: str = "") -> str:
    header = "📝 Review"
    if print_name:
        header += f" for <b>{print_name}</b>"
    return (
        f"{header}\n"
        f"{star_rating(review['rating'])} ({review['rating']}/5)\n\n"
        f'"{review["text"]}"\n'
        f"— @{review['username']}"
    )


def format_request_card(request: dict) -> str:
    status_emoji = "🟢" if request["status"] == "open" else "🟡"
    return (
        f"{status_emoji} <b>Print Request #{request['id']}</b>\n\n"
        f"{request['description']}\n\n"
        f"Requested by: @{request['username']}\n"
        f"Status: {request['status'].title()}"
    )


def format_leaderboard(users: list[dict]) -> str:
    if not users:
        return "No contributors yet! Be the first to share a print or write a review."
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Community Leaderboard</b>\n"]
    for i, user in enumerate(users):
        prefix = medals[i] if i < 3 else f"  {i + 1}."
        name = user.get("display_name") or user.get("username") or "Unknown"
        score = user.get("score", 0)
        lines.append(
            f"{prefix} <b>{name}</b> — {score} pts "
            f"(🖨️{user['prints_shared']} 📝{user['reviews_given']} 🤝{user['requests_fulfilled']})"
        )
    return "\n".join(lines)


def format_tip(tip: dict) -> str:
    tags = " ".join(f"#{t}" for t in tip.get("tags", []))
    return f"💡 <b>Tip: {tip['title']}</b>\n\n{tip['text']}\n\n{tags}"


def get_user_display(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name or "Unknown"


def truncate(text: str, max_len: int = 200) -> str:
    return text if len(text) <= max_len else text[: max_len - 3] + "..."
