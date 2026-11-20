from aiogram.utils.keyboard import InlineKeyboardBuilder


def categories_keyboard(categories):
    kb = InlineKeyboardBuilder()
    for category in categories:
        kb.button(text=f"📁 {category.name}", callback_data=f"cat:{category.id}")
    kb.adjust(2)
    kb.row()
    kb.button(text="🔄 Обновить каталог", callback_data="refresh:catalog")
    kb.adjust(2, 1)
    return kb.as_markup()
