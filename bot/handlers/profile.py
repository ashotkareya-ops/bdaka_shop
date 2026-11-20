from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select
from database.models.user import User
from bot.keyboards.profile import profile_keyboard

router = Router()

@router.message(F.text == "👤 Профиль")
async def profile(message: Message, session):
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    await message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"Баланс: <b>{user.balance:.2f} ₽</b>\n"
        f"Покупок: {user.purchase_count}",
        reply_markup=profile_keyboard()
    )
