from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="📁 Управление категориями", callback_data="admin:categories")
    kb.button(text="📦 Управление товарами", callback_data="admin:products")
    kb.button(text="💰 Управление ценами", callback_data="admin:prices")
    kb.button(text="💱 Курс USD/RUB", callback_data="admin:fx_rate")
    kb.button(text="📦 Последние заказы", callback_data="admin:orders")
    kb.button(text="📝 Описания товаров", callback_data="admin:descriptions")
    kb.button(text="📚 Команды администратора", callback_data="admin:commands")
    kb.adjust(1)
    return kb.as_markup()
