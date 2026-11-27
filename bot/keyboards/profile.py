from aiogram.utils.keyboard import InlineKeyboardBuilder
from config.settings import settings


def profile_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Пополнить баланс", callback_data="balance:topup")
    kb.button(text="📦 Мои покупки", callback_data="profile:purchases")
    kb.button(text="💸 История операций", callback_data="profile:transactions")
    kb.button(text="🤝 Партнёрам / API", callback_data="partner:api")
    kb.button(text="🔐 Политика конфиденциальности", callback_data="profile:privacy")
    kb.button(text="📄 Пользовательское соглашение", callback_data="profile:agreement")
    kb.button(text="⭐ Отзывы и логи", url=settings.shop_reviews_url)
    kb.button(text="📢 Новости магазина", url=settings.shop_news_url)
    kb.button(text="💬 Чат магазина", url=settings.shop_chat_url)
    kb.button(text="🎧 Поддержка", url=settings.shop_support_url)
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()
