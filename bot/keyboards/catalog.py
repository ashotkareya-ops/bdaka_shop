from aiogram.utils.keyboard import InlineKeyboardBuilder


def categories_keyboard(categories):
    kb = InlineKeyboardBuilder()
    for category in categories:
        kb.button(text=f"📁 {category.name}", callback_data=f"cat:{category.id}")
    kb.button(text="🔄 Обновить каталог", callback_data="refresh:catalog")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(2, 1, 1)
    return kb.as_markup()
