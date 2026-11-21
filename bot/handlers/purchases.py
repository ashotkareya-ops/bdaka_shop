from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from html import escape

from database.models.user import User
from database.models.order import Order
from database.models.product import Product
from database.models.digital_key import DigitalKey
from bot.utils.section_media import send_section
from services.order_delivery import send_order_delivery, send_order_txt, _is_url

router = Router()


async def _get_owned_order(session, telegram_id: int, order_id: int):
    return await session.scalar(
        select(Order)
        .join(User, Order.user_id == User.id)
        .where(Order.id == order_id, User.telegram_id == telegram_id)
    )


@router.callback_query(F.data == "profile:purchases")
async def purchases(callback: CallbackQuery, session):
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    if not user:
        await callback.answer("Профиль не найден", show_alert=True)
        return
    rows = (await session.execute(
        select(Order, Product).join(Product, Order.product_id == Product.id)
        .where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(15)
    )).all()

    kb = InlineKeyboardBuilder()
    for order, product in rows:
        status = "✅" if order.status == "COMPLETED" else "⏳" if order.status == "PROCESSING" else "🧾"
        kb.button(
            text=f"{status} {product.name[:32]} · #{order.id}",
            callback_data=f"order:open:{order.id}",
        )
    kb.button(text="👤 В профиль", callback_data="balance:profile")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)

    if not rows:
        text = "📦 <b>МОИ ПОКУПКИ</b>\n\nПокупок пока нет."
    else:
        text = (
            "📦 <b>МОИ ПОКУПКИ</b>\n\n"
            "Выберите заказ, чтобы открыть чек, ссылку или код активации."
        )
    await send_section(callback.message, "orders.png", text, reply_markup=kb.as_markup())
    await callback.answer()


@router.message(Command("purchases"))
async def purchases_command(message: Message, session):
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    rows = (await session.execute(
        select(Order, Product).join(Product, Order.product_id == Product.id)
        .where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(15)
    )).all()
    kb = InlineKeyboardBuilder()
    for order, product in rows:
        status = "✅" if order.status == "COMPLETED" else "⏳" if order.status == "PROCESSING" else "🧾"
        kb.button(
            text=f"{status} {product.name[:32]} · #{order.id}",
            callback_data=f"order:open:{order.id}",
        )
    kb.button(text="👤 В профиль", callback_data="balance:profile")
    kb.button(text="🏠 Главное меню", callback_data="menu:home")
    kb.adjust(1)
    text = (
        "📦 <b>МОИ ПОКУПКИ</b>\n\nВыберите заказ, чтобы открыть его данные."
        if rows else "📦 <b>МОИ ПОКУПКИ</b>\n\nПокупок пока нет."
    )
    await send_section(message, "orders.png", text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("order:open:"))
async def open_order_delivery(callback: CallbackQuery, session):
    try:
        order_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный номер заказа", show_alert=True)
        return
    order = await _get_owned_order(session, callback.from_user.id, order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if order.status != "COMPLETED":
        await callback.answer(f"Статус заказа: {order.status}", show_alert=True)
        return
    sent = await send_order_delivery(callback.bot, order_id)
    if sent:
        await callback.answer("Данные заказа отправлены")
    else:
        await callback.answer("Данные заказа пока недоступны. Напишите в поддержку.", show_alert=True)


@router.callback_query(F.data.startswith("order:copy:"))
async def copy_order_delivery(callback: CallbackQuery, session):
    try:
        order_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный номер заказа", show_alert=True)
        return
    order = await _get_owned_order(session, callback.from_user.id, order_id)
    if not order or order.status != "COMPLETED":
        await callback.answer("Заказ не найден или ещё не выполнен", show_alert=True)
        return
    key = await session.scalar(select(DigitalKey).where(DigitalKey.order_id == order_id))
    if not key or not key.code:
        await callback.answer("Данные заказа не найдены", show_alert=True)
        return
    await callback.message.answer(
        f"📋 <b>Данные для копирования · заказ #{order_id}</b>\n\n"
        f"<code>{escape(key.code)}</code>",
        disable_web_page_preview=True,
    )
    await callback.answer("Отправил данные отдельным сообщением")


@router.callback_query(F.data.startswith("order:activate:"))
async def activate_order(callback: CallbackQuery, session):
    try:
        order_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный номер заказа", show_alert=True)
        return
    order = await _get_owned_order(session, callback.from_user.id, order_id)
    if not order or order.status != "COMPLETED":
        await callback.answer("Заказ не найден или ещё не выполнен", show_alert=True)
        return
    key = await session.scalar(select(DigitalKey).where(DigitalKey.order_id == order_id))
    if not key or not key.code:
        await callback.answer("Данные заказа не найдены", show_alert=True)
        return
    if _is_url(key.code):
        await callback.answer("Ссылка активации находится в сообщении выше")
    else:
        await callback.message.answer(
            f"🔑 <b>Код для заказа #{order_id}</b>\n\n"
            f"<code>{escape(key.code)}</code>\n\n"
            "Скопируйте код и вставьте его на странице активации продавца."
        )
        await callback.answer()


@router.callback_query(F.data.startswith("order:txt:"))
async def download_order_txt(callback: CallbackQuery, session):
    try:
        order_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный номер заказа", show_alert=True)
        return
    order = await _get_owned_order(session, callback.from_user.id, order_id)
    if not order or order.status != "COMPLETED":
        await callback.answer("Заказ не найден или ещё не выполнен", show_alert=True)
        return
    sent = await send_order_txt(callback.bot, order_id, callback.from_user.id)
    await callback.answer("TXT-файл отправлен" if sent else "Не удалось подготовить файл",
                          show_alert=not sent)
