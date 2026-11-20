from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy import select
from database.models.user import User
from bot.keyboards.main import main_menu

router = Router()

@router.message(CommandStart())
async def start(message: Message, session):
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user:
        referrer_id = None
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 2 and parts[1].startswith("ref_"):
            try:
                candidate = int(parts[1][4:])
                if candidate != message.from_user.id:
                    referrer = await session.scalar(select(User).where(User.telegram_id == candidate))
                    if referrer:
                        referrer_id = referrer.id
            except ValueError:
                pass
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            balance=0,
            referrer_id=referrer_id
        )
        session.add(user)
        await session.commit()
    await message.answer(
        f"👋 Добро пожаловать в <b>BDAKA SHOP</b>, {message.from_user.first_name}!\n\nВыберите раздел в меню.",
        reply_markup=main_menu()
    )
