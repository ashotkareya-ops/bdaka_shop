from aiogram.utils.keyboard import InlineKeyboardBuilder

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🛍 Каталог", callback_data="menu:catalog")
    kb.button(text="👤 Профиль", callback_data="menu:profile")
    kb.button(text="🔗 Полезные ссылки", callback_data="menu:links")
    kb.adjust(2, 1)
    return kb.as_markup()
