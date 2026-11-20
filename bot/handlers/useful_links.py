from aiogram import Router, F
from aiogram.types import Message

router = Router()

@router.message(F.text == "🔗 Полезные ссылки")
async def useful_links(message: Message):
    await message.answer(
        "🔗 <b>Полезные ссылки</b>\n\n"
        "Поддержка: ссылка будет добавлена администратором\n"
        "Правила: ссылка будет добавлена администратором"
    )
