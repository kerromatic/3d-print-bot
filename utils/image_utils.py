import aiohttp
import os
from pathlib import Path
from io import BytesIO
from PIL import Image


async def fetch_image_from_url(url: str) -> BytesIO | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200 and "image" in resp.content_type:
                    data = await resp.read()
                    buf = BytesIO(data)
                    buf.name = url.split("/")[-1].split("?")[0] or "image.jpg"
                    return buf
    except Exception as e:
        print(f"Error fetching image from {url}: {e}")
    return None


def load_image_from_path(path: str) -> BytesIO | None:
    try:
        p = Path(path)
        if p.exists() and p.is_file():
            with open(p, "rb") as f:
                buf = BytesIO(f.read())
                buf.name = p.name
                return buf
    except Exception as e:
        print(f"Error loading image from {path}: {e}")
    return None


def get_pending_images(folder: str, posted_log: str = ".posted") -> list[str]:
    folder_path = Path(folder)
    if not folder_path.exists():
        return []
    log_path = folder_path / posted_log
    posted = set()
    if log_path.exists():
        posted = set(log_path.read_text().strip().splitlines())
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    new_images = []
    for f in sorted(folder_path.iterdir()):
        if f.is_file() and f.suffix.lower() in image_exts and f.name not in posted:
            new_images.append(str(f))
    return new_images


def mark_as_posted(folder: str, filename: str, posted_log: str = ".posted"):
    log_path = Path(folder) / posted_log
    with open(log_path, "a") as f:
        f.write(f"{filename}\n")


def resize_for_telegram(image_buf: BytesIO, max_size: int = 10_000_000) -> BytesIO:
    if image_buf.getbuffer().nbytes <= max_size:
        image_buf.seek(0)
        return image_buf
    image_buf.seek(0)
    img = Image.open(image_buf)
    quality = 85
    while True:
        out = BytesIO()
        out.name = getattr(image_buf, "name", "image.jpg")
        img.save(out, format="JPEG", quality=quality, optimize=True)
        if out.getbuffer().nbytes <= max_size or quality <= 20:
            out.seek(0)
            return out
        quality -= 10
        if quality <= 40:
            w, h = img.size
            img = img.resize((w // 2, h // 2), Image.LANCZOS)
