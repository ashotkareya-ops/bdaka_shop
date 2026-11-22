from aiogram.utils.keyboard import InlineKeyboardBuilder


def _stock_label(product):
    if not product.supplier_name:
        return "📦"
    if not product.supplier_available or product.supplier_stock == 0:
        return "⛔ Нет в наличии"
    if product.supplier_stock is None:
        return "🔄 Наличие уточняется"
    return f"🟢 Остаток: {product.supplier_stock}"


def products_keyboard(products):
    kb = InlineKeyboardBuilder()
    for product in products:
        stock = _stock_label(product)
        kb.button(
            text=f"{product.name} · {product.price:.0f} ₽ · {stock}",
            callback_data=f"product:{product.id}",
        )
    kb.button(text="⬅️ К разделам", callback_data="back:catalog")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def buy_keyboard(product_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Купить", callback_data=f"buy:{product_id}")
    kb.button(text="⬅️ К товарам", callback_data="back:products")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def unavailable_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔔 Сейчас нет в наличии", callback_data="stock:unavailable")
    kb.button(text="⬅️ К товарам", callback_data="back:products")
    kb.button(text="🏠 Вернуться в главное меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def quantity_keyboard(product_id: int, quantity: int, max_quantity: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="➖", callback_data=f"qty:change:{product_id}:{max(1, quantity-1)}")
    kb.button(text=f"{quantity} шт.", callback_data=f"qty:custom:{product_id}")
    kb.button(text="➕", callback_data=f"qty:change:{product_id}:{min(max_quantity, quantity+1)}")
    for amount in (1, 5, 10, 25, 50):
        if amount <= max_quantity:
            kb.button(text=str(amount), callback_data=f"qty:change:{product_id}:{amount}")
    kb.button(text="✍️ Ввести количество", callback_data=f"qty:custom:{product_id}")
    kb.button(text="✅ Продолжить", callback_data=f"qty:confirm:{product_id}:{quantity}")
    kb.button(text="⬅️ К товару", callback_data=f"product:{product_id}")
    kb.adjust(3, 5, 1, 1, 1)
    return kb.as_markup()


def quantity_keyboard(product_id: int, quantity: int, max_quantity: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="➖", callback_data=f"qty:change:{product_id}:{max(1, quantity-1)}")
    kb.button(text=f"{quantity} шт.", callback_data=f"qty:custom:{product_id}")
    kb.button(text="➕", callback_data=f"qty:change:{product_id}:{min(max_quantity, quantity+1)}")
    for amount in (1, 5, 10, 25, 50):
        if amount <= max_quantity:
            kb.button(text=str(amount), callback_data=f"qty:change:{product_id}:{amount}")
    kb.button(text="✍️ Ввести количество", callback_data=f"qty:custom:{product_id}")
    kb.button(text="✅ Продолжить", callback_data=f"qty:confirm:{product_id}:{quantity}")
    kb.button(text="⬅️ К товару", callback_data=f"product:{product_id}")
    kb.adjust(3, 5, 1, 1, 1)
    return kb.as_markup()
