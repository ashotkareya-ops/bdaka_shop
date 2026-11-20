from aiogram.utils.keyboard import InlineKeyboardBuilder


def profile_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Пополнить баланс", callback_data="balance:topup")
    kb.button(text="📦 Мои покупки", callback_data="profile:purchases")
    kb.button(text="💸 История операций", callback_data="profile:transactions")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()
