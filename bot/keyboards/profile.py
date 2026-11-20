from aiogram.utils.keyboard import InlineKeyboardBuilder

def profile_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Мои покупки", callback_data="profile:purchases")
    kb.button(text="💳 Транзакции", callback_data="profile:transactions")
    kb.adjust(1)
    return kb.as_markup()
