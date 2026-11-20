from aiogram.utils.keyboard import InlineKeyboardBuilder


def home_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    return kb.as_markup()
