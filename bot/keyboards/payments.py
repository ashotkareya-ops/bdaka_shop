from aiogram.utils.keyboard import InlineKeyboardBuilder


def payment_method_keyboard(product_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатить через Platega", callback_data=f"buy:platega:{product_id}")
    kb.button(text="👛 Оплатить с баланса", callback_data=f"buy:balance:{product_id}")
    kb.button(text="⬅️ Назад к товару", callback_data=f"product:{product_id}")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def invoice_keyboard(payment_url: str, order_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Перейти к оплате", url=payment_url)
    kb.button(text="🔄 Проверить оплату", callback_data=f"payment:check:{order_id}")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def insufficient_balance_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В каталог", callback_data="back:catalog")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def topup_amount_keyboard():
    kb = InlineKeyboardBuilder()
    for amount in (100, 300, 500, 1000):
        kb.button(text=f"💳 {amount} ₽", callback_data=f"balance:amount:{amount}")
    kb.button(text="⬅️ В профиль", callback_data="balance:profile")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


def topup_invoice_keyboard(payment_url: str, payment_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Перейти к оплате", url=payment_url)
    kb.button(text="✅ Проверить оплату", callback_data=f"payment:check_topup:{payment_id}")
    kb.button(text="👤 В профиль", callback_data="balance:profile")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()
