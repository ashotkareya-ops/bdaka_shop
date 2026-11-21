import hashlib
import logging
from datetime import datetime
from html import escape
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import select

from config.settings import settings
from database.engine import SessionLocal
from database.models.order import Order
from database.models.product import Product

log = logging.getLogger(__name__)


def _reviews_chat_id() -> str:
    """
    Resolve the reviews destination from config/settings.py.
    Supports @username, https://t.me/username and numeric channel IDs.
    """
    value = (settings.shop_reviews_url or "").strip()
    if not value:
        raise ValueError("SHOP_REVIEWS_URL / shop_reviews_url is empty")

    if value.startswith("-100") or value.lstrip("-").isdigit():
        return value

    if value.startswith("@"):
        return value

    parsed = urlparse(value if "://" in value else f"https://{value}")
    path = parsed.path.strip("/")
    if not path or path.startswith("+") or path.startswith("joinchat"):
        raise ValueError(
            "Reviews URL must be a public channel link such as https://t.me/bdaka_reviews"
        )
    username = path.split("/")[0]
    if username.startswith("@"):
        return username
    return f"@{username}"


async def publish_purchase_notice(bot, order_id: int) -> bool:
    """
    Publish an automatically generated purchase log (not a customer-written review).
    The entire notice is wrapped in Telegram blockquote formatting to match the
    highlighted framed style shown by the user.
    """
    try:
        async with SessionLocal() as session:
            row = await session.execute(
                select(Order, Product)
                .join(Product, Order.product_id == Product.id)
                .where(Order.id == order_id)
            )
            result = row.first()
            if not result:
                log.warning("Purchase notice skipped: order %s was not found", order_id)
                return False

            order, product = result
            if order.status != "COMPLETED":
                log.info(
                    "Purchase notice skipped for order %s: status=%s",
                    order_id, order.status
                )
                return False

            created_at = order.created_at
            if created_at is None:
                created_at = datetime.now(ZoneInfo("Europe/Moscow"))
            elif created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=ZoneInfo("UTC"))
                created_at = created_at.astimezone(ZoneInfo("Europe/Moscow"))
            else:
                created_at = created_at.astimezone(ZoneInfo("Europe/Moscow"))

            product_name = escape(product.name)
            time_text = created_at.strftime("%d-%m-%Y %H:%M MSK")

        purchase_id = hashlib.sha256(
            f"BDAKA-PURCHASE-{order_id}".encode("utf-8")
        ).hexdigest()[:10].upper()

        text = (
            "<blockquote>"
            "📦 <b>New Purchase!</b>\n\n"
            f"👤 ID: <code>{purchase_id}</code>\n"
            f"🛍 Product: <b>{product_name}</b>\n"
            "🟢 Quantity: <b>1</b>\n"
            f"⏳ Time: <b>{time_text}</b>"
            "</blockquote>"
        )

        chat_id = _reviews_chat_id()
        message = await bot.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=True,
        )
        log.info(
            "Purchase notice published: order_id=%s chat_id=%s message_id=%s",
            order_id, chat_id, message.message_id
        )
        return True

    except Exception:
        # Publishing must never interrupt order fulfilment.
        log.exception(
            "Could not publish purchase notice for order %s. "
            "Check bot admin rights and shop_reviews_url.",
            order_id
        )
        return False
