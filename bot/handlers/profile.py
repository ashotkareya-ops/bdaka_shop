from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy import select
from database.models.user import User
from bot.keyboards.profile import profile_keyboard
from bot.utils.section_media import send_section

router = Router()

async def _send_profile(target, user):
    text = (
        "👤 <b>ПРОФИЛЬ BDAKA SHOP</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user.telegram_id}</code>\n"
        f"💰 Баланс: <b>{user.balance:.2f} ₽</b>\n"
        f"🛍 Покупок: <b>{user.purchase_count}</b>\n\n"
        "Выберите нужный раздел:"
    )
    await send_section(target, "profile.png", text, reply_markup=profile_keyboard())

@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def profile(message: Message, session):
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    await _send_profile(message, user)

@router.callback_query(F.data == "menu:profile")
async def profile_from_home(callback: CallbackQuery, session):
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    await _send_profile(callback.message, user)
    await callback.answer()
