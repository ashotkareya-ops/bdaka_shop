from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from sqlalchemy import select
from database.models.user import User
from database.models.order import Order
from database.models.product import Product
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.utils.section_media import send_section

router = Router()


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
    kb.button(text="👤 В профиль", callback_data="balance:profile")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)
    if not rows:
        text = "📦 <b>МОИ ПОКУПКИ</b>\n\nПокупок пока нет."
    else:
        lines = ["📦 <b>МОИ ПОКУПКИ</b>"]
        for order, product in rows:
            lines.append(f"Заказ #{order.id} — {product.name} — {order.price:.2f} ₽ — {order.status}")
        text = "\n".join(lines)
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
    kb.button(text="👤 В профиль", callback_data="balance:profile")
    kb.button(text="🏠 Главное меню", callback_data="menu:home")
    kb.adjust(1)
    if not rows:
        text = "📦 <b>МОИ ПОКУПКИ</b>\n\nПокупок пока нет."
    else:
        lines = ["📦 <b>МОИ ПОКУПКИ</b>"]
        for order, product in rows:
            lines.append(f"Заказ #{order.id} — {product.name} — {order.price:.2f} ₽ — {order.status}")
        text = "\n".join(lines)
    await send_section(message, "orders.png", text, reply_markup=kb.as_markup())
