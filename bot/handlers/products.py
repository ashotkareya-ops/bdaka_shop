import re
from html import escape

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, func

from bot.keyboards.products import buy_keyboard, unavailable_keyboard
from bot.utils.section_media import send_section, product_banner
from database.models.product import Product
from database.models.digital_key import DigitalKey
from database.models.order import Order
from database.models.user import User

router = Router()

_URL_RE = re.compile(r"https?://[^\s<>]+|www\.[^\s<>]+", re.IGNORECASE)


def _render_rich_text(raw: str) -> str:
    """Escape admin text, preserve line breaks and turn URLs into clickable links."""
    chunks = []
    last = 0
    for match in _URL_RE.finditer(raw):
        chunks.append(escape(raw[last:match.start()]))
        url = match.group(0)
        trailing = ""
        while url and url[-1] in ".,!?;:)]}»":
            trailing = url[-1] + trailing
            url = url[:-1]
        if url:
            href = url if url.lower().startswith(("http://", "https://")) else f"https://{url}"
            chunks.append(f'<a href="{escape(href, quote=True)}">{escape(url)}</a>')
        chunks.append(escape(trailing))
        last = match.end()
    chunks.append(escape(raw[last:]))
    return "".join(chunks).replace("\r\n", "\n").replace("\r", "\n")


def _split_description(value: str | None, product_name: str, price: float, stock_value: int | None) -> tuple[str, list[str]]:
    """Separate descriptive copy from delivery/warranty/term/stock metadata.

    Legacy descriptions may contain their own title and price. Those lines are
    removed because the product card renders title and price in the header.
    """
    lines = (value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    body: list[str] = []
    footer: list[str] = []
    title_key = re.sub(r"\s+", " ", (product_name or "").strip()).casefold()
    metadata_re = re.compile(r"^\s*(?:[^\wА-Яа-я]{0,5})?(выдача|гарантия|срок|наличие)\s*:\s*(.*)$", re.IGNORECASE)
    for index, original in enumerate(lines):
        line = original.strip()
        if not line:
            # Keep paragraph breaks in the actual description only.
            if body and body[-1] != "":
                body.append("")
            continue
        plain = re.sub(r"[*_`~]", "", line).strip()
        plain_no_emoji = re.sub(r"^[^A-Za-zА-Яа-я0-9]+", "", plain).strip()
        if title_key and re.sub(r"\s+", " ", plain_no_emoji).casefold() == title_key:
            continue
        # Do not repeat price inside the description: price is always rendered above.
        if re.match(r"^(?:[\W_]*)(?:цена|стоимость)\s*:", plain_no_emoji, re.IGNORECASE):
            continue
        if re.match(r"^(?:[\W_]*)(?:описание)\s*$", plain_no_emoji, re.IGNORECASE):
            continue
        m = metadata_re.match(plain_no_emoji)
        if m:
            label = m.group(1).capitalize()
            value_text = m.group(2).strip()
            if label.casefold() == "наличие":
                if "{{stock}}" in value_text:
                    value_text = value_text.replace("{{stock}}", str(stock_value) if stock_value is not None else "уточняется")
                elif "{{price}}" in value_text:
                    value_text = value_text.replace("{{price}}", f"{price:.2f}".rstrip("0").rstrip("."))
            footer.append(f"{label}: {value_text}".rstrip())
            continue
        # Strip common standalone section labels left by older templates.
        if plain_no_emoji.casefold() in {"описание", "✉️ описание"}:
            continue
        body.append(original.rstrip())

    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    description = "\n".join(body).strip() or "Описание скоро появится."
    # If the old description has no explicit stock footer, still show live stock once.
    if not any(item.casefold().startswith("наличие:") for item in footer):
        if stock_value is None:
            footer.append("Наличие: уточняется у поставщика")
        else:
            footer.append(f"Наличие: {stock_value} шт.")
    return description, footer


@router.callback_query(F.data.startswith("product:"))
async def product_details(callback: CallbackQuery, session):
    try:
        product_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный товар", show_alert=True)
        return

    product = await session.get(Product, product_id)
    if not product or not product.is_active or product.price <= 0:
        await callback.answer("Товар недоступен", show_alert=True)
        return

    local_stock = await session.scalar(
        select(func.count(DigitalKey.id)).where(
            DigitalKey.product_id == product.id,
            DigitalKey.status == "AVAILABLE",
        )
    ) or 0

    if local_stock:
        stock_text = f"🟢 В наличии: {local_stock} шт."
        can_buy = True
    elif product.supplier_name == "sandromania":
        if not product.supplier_available or product.supplier_stock == 0:
            stock_text = "🔴 Нет в наличии у поставщика"
            can_buy = False
        elif product.supplier_stock is None:
            stock_text = "🟡 Точное количество уточняется у поставщика"
            can_buy = False
        else:
            stock_text = f"🟢 В наличии у поставщика: {product.supplier_stock} шт."
            can_buy = True
    else:
        stock_text = "🔴 Нет в наличии"
        can_buy = False

    sold_count = await session.scalar(
        select(func.count(Order.id)).where(
            Order.product_id == product.id,
            Order.status == "COMPLETED",
        )
    ) or 0

    user = await session.scalar(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    balance = float(user.balance or 0) if user else 0.0

    # Header data appears once. Only the actual product instructions stay
    # inside the quote; delivery, warranty, term and stock are shown below it.
    safe_name = escape(product.name or "Товар")
    live_stock = local_stock if local_stock else (product.supplier_stock if product.supplier_name == "sandromania" else 0)
    description_text, footer_items = _split_description(
        product.description, product.name or "Товар", product.price, live_stock
    )
    description = _render_rich_text(description_text)
    footer = "\n".join(f"{escape(item)}" for item in footer_items)
    text = (
        f"{safe_name}\n\n"
        f"💰 Цена: <b>{product.price:.2f} ₽</b>\n"
        f"📊 Продано: {sold_count}\n\n"
        f"💳 Ваш баланс: <b>{balance:.2f} ₽</b>\n\n"
        f"💬 <b>Описание:</b>\n"
        f"<blockquote>{description}</blockquote>\n\n"
        f"{footer}"
    )

    markup = buy_keyboard(product.id) if can_buy else unavailable_keyboard()
    await send_section(
        callback.message,
        product_banner(product),
        text,
        reply_markup=markup,
    )
    await callback.answer()
