from aiogram.utils.keyboard import InlineKeyboardBuilder

def insufficient_balance_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В каталог", callback_data="back:catalog")
    return kb.as_markup()
