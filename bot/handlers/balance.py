from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

@router.message(Command("balance"))
async def balance_help(message: Message):
    await message.answer(
        "Пополнение баланса пока выполняется администратором после проверки фактического платежа. "
        "Автоматический платёжный провайдер ещё не подключён."
    )
