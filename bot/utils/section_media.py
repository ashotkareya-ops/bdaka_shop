from pathlib import Path
from aiogram.types import FSInputFile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BANNER_DIR = PROJECT_ROOT / "assets" / "banners"

def product_banner(product) -> str:
    name = str(getattr(product, "name", "")).casefold()
    rules = (
        (("claude",), "claude.png"),
        (("gemini",), "gemini.png"),
        (("capcut", "cap cut"), "capcut.png"),
        (("chatgpt", "chat gpt", "чат гпт"), "chatgpt.png"),
        (("adobe", "photoshop", "premiere", "acrobat"), "adobe.png"),
    )
    for needles, filename in rules:
        if any(word in name for word in needles):
            return filename
    return "catalog.png"

async def send_section(target, banner_name: str, caption: str, reply_markup=None):
    path = BANNER_DIR / banner_name
    if path.is_file():
        return await target.answer_photo(
            photo=FSInputFile(path),
            caption=caption,
            reply_markup=reply_markup,
        )
    return await target.answer(caption, reply_markup=reply_markup)
