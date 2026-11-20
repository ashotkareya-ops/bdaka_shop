from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍 Каталог"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🔗 Полезные ссылки")],
        ],
        resize_keyboard=True
    )
