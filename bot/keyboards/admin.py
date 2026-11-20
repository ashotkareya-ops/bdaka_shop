from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Управление ценами", callback_data="admin:prices")
    kb.button(text="📦 Последние заказы", callback_data="admin:orders")
    kb.adjust(1)
    return kb.as_markup()
