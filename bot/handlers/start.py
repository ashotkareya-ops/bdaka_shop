from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from database.models.user import User
from bot.utils.section_media import send_section
from bot.keyboards.main import main_menu

router = Router()

async def show_main_menu(target, user_name: str = "покупатель"):
    text = (
        f"👋 Добро пожаловать в <b>BDAKA SHOP</b>, {user_name}!\n\n"
        "<i>Выберите нужный раздел в меню ниже</i>"
    )
    await send_section(
        target, "home.png", text,
        reply_markup=main_menu(),
    )

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
            referrer_id=referrer_id,
        )
        session.add(user)
        await session.commit()
    await show_main_menu(message, message.from_user.first_name)

@router.message(Command("help"))
async def buyer_help(message: Message):
    try:
        await message.delete()
    except Exception:
        pass
    await message.answer(
        "<b>Команды покупателя</b>\n"
        "/start — главное меню\n"
        "/catalog — каталог товаров\n"
        "/profile — профиль и баланс\n"
        "/balance — пополнение баланса\n"
        "/purchases — мои покупки\n"
        "/transactions — история операций\n"
        "/links — полезные ссылки"
    )

@router.callback_query(lambda c: c.data == "menu:home")
async def menu_home(callback: CallbackQuery):
    await show_main_menu(callback.message, callback.from_user.first_name)
    await callback.answer()
