from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from sqlalchemy import select
from database.models.user import User
from database.models.transaction import Transaction
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.utils.section_media import send_section

router = Router()


@router.callback_query(F.data == "profile:transactions")
async def transactions(callback: CallbackQuery, session):
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    if not user:
        await callback.answer("Профиль не найден", show_alert=True)
        return
    rows = (await session.scalars(
        select(Transaction).where(Transaction.user_id == user.id)
        .order_by(Transaction.created_at.desc()).limit(15)
    )).all()
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 В профиль", callback_data="balance:profile")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)
    if not rows:
        text = "💸 <b>ИСТОРИЯ ОПЕРАЦИЙ</b>\n\nОпераций пока нет."
    else:
        lines = ["💸 <b>ИСТОРИЯ ОПЕРАЦИЙ</b>", "━━━━━━━━━━━━━━━━━━"]
        for row in rows:
            lines.append(f"{row.amount:+.2f} ₽ — {row.description}")
        text = "\n".join(lines)
    await send_section(callback.message, "wallet.png", text, reply_markup=kb.as_markup())
    await callback.answer()


@router.message(Command("transactions"))
async def transactions_command(message: Message, session):
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    rows = (await session.scalars(
        select(Transaction).where(Transaction.user_id == user.id)
        .order_by(Transaction.created_at.desc()).limit(15)
    )).all()
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 В профиль", callback_data="balance:profile")
    kb.button(text="🏠 Главное меню", callback_data="menu:home")
    kb.adjust(1)
    if not rows:
        text = "💸 <b>ИСТОРИЯ ОПЕРАЦИЙ</b>\n\nОпераций пока нет."
    else:
        lines = ["💸 <b>ИСТОРИЯ ОПЕРАЦИЙ</b>", "━━━━━━━━━━━━━━━━━━"]
        for row in rows:
            lines.append(f"{row.amount:+.2f} ₽ — {row.description}")
        text = "\n".join(lines)
    await send_section(message, "wallet.png", text, reply_markup=kb.as_markup())
