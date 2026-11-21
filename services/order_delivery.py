from datetime import datetime
from aiogram.types import InlineKeyboardMarkup, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from config.settings import settings
from database.engine import SessionLocal
from database.models.order import Order
from database.models.product import Product
from database.models.digital_key import DigitalKey
from database.models.user import User


def _is_url(value: str) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith(("https://", "http://"))


def _date_text(value):
    if not value:
        return "не указана"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M:%S")
    return str(value)


def _receipt_text(order, product):
    return (
        f"🧾 <b>Заказ #{order.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Товар:</b> {product.name}\n"
        f"🔢 <b>Количество:</b> 1\n"
        f"💰 <b>Сумма:</b> {order.price:.2f} ₽\n"
        f"📊 <b>Статус:</b> ✅ Выполнен\n"
        f"🕒 <b>Дата:</b> {_date_text(order.created_at)}"
    )


def _delivery_keyboard(order_id: int, delivery: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if _is_url(delivery):
        kb.button(text="🌐 Открыть активацию", url=delivery)
    else:
        kb.button(text="🌐 Открыть активацию", callback_data=f"order:activate:{order_id}")
    kb.button(text="📋 Скопировать код / данные", callback_data=f"order:copy:{order_id}")
    kb.button(text="📄 Скачать TXT", callback_data=f"order:txt:{order_id}")
    kb.button(text=f"🆘 Помощь по заказу #{order_id}", url=settings.shop_support_url)
    kb.adjust(1)
    return kb.as_markup()


async def send_order_delivery(bot, order_id: int):
    """Send a consistent two-message receipt + delivery for completed orders."""
    async with SessionLocal() as session:
        row = await session.execute(
            select(Order, Product, User)
            .join(Product, Order.product_id == Product.id)
            .join(User, Order.user_id == User.id)
            .where(Order.id == order_id)
        )
        result = row.first()
        if not result:
            return False
        order, product, user = result
        key = await session.scalar(
            select(DigitalKey).where(DigitalKey.order_id == order.id)
        )
        if not key or not key.code:
            return False
        delivery = key.code
        receipt = _receipt_text(order, product)
        is_link = _is_url(delivery)
        intro = (
            "🔑 <b>Ссылки / коды по заказу "
            f"#{order.id}</b>\n\n"
            "Откройте ссылку активации. Если выдан отдельный код, "
            "скопируйте его и вставьте на странице активации.\n\n"
            if is_link else
            "🔑 <b>Данные для активации по заказу "
            f"#{order.id}</b>\n\n"
            "Скопируйте код и следуйте инструкции продавца.\n\n"
        )
        delivery_text = intro + (delivery if is_link else f"<code>{delivery}</code>")
        keyboard = _delivery_keyboard(order.id, delivery)
        telegram_id = user.telegram_id

    await bot.send_message(telegram_id, receipt)
    await bot.send_message(telegram_id, delivery_text, reply_markup=keyboard, disable_web_page_preview=True)
    return True


async def send_order_txt(bot, order_id: int, telegram_id: int):
    async with SessionLocal() as session:
        row = await session.execute(
            select(Order, Product, User)
            .join(Product, Order.product_id == Product.id)
            .join(User, Order.user_id == User.id)
            .where(Order.id == order_id, User.telegram_id == telegram_id)
        )
        result = row.first()
        if not result:
            return False
        order, product, user = result
        key = await session.scalar(select(DigitalKey).where(DigitalKey.order_id == order.id))
        if not key or not key.code:
            return False
        content = (
            f"Заказ #{order.id}\n"
            f"Товар: {product.name}\n"
            f"Описание: {product.description or 'не указано'}\n"
            f"Количество: 1\n"
            f"Сумма: {order.price:.2f} RUB\n"
            f"Статус: Выполнен\n"
            f"Дата: {_date_text(order.created_at)}\n\n"
            f"Код / ссылка активации:\n{key.code}\n"
        )
        filename = f"order_{order.id}.txt"
    document = BufferedInputFile(content.encode("utf-8"), filename=filename)
    await bot.send_document(telegram_id, document, caption=f"📄 Данные заказа #{order_id}")
    return True
