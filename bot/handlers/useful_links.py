from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from bot.keyboards.navigation import home_keyboard
from bot.utils.section_media import send_section

router = Router()

async def _send_links(target):
    await send_section(
        target, "catalog.png",
        "🔗 <b>ПОЛЕЗНЫЕ ССЫЛКИ</b>\n"
        "Поддержка: ссылка будет добавлена администратором\n"
        "Правила: ссылка будет добавлена администратором",
        reply_markup=home_keyboard(),
    )

@router.message(Command("links"))
async def useful_links(message: Message):
    await _send_links(message)

@router.callback_query(F.data == "menu:links")
async def useful_links_from_home(callback: CallbackQuery):
    await _send_links(callback.message)
    await callback.answer()
