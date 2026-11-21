from aiogram import Router, F
from aiogram.types import CallbackQuery
from bot.keyboards.products import buy_keyboard, unavailable_keyboard
from bot.utils.section_media import send_section, product_banner

router = Router()

@router.callback_query(F.data.startswith("product:"))
async def product_details(callback: CallbackQuery, session):
    try:
        product_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный товар", show_alert=True)
        return

    from database.models.product import Product
    from sqlalchemy import select, func
    from database.models.digital_key import DigitalKey

    product = await session.get(Product, product_id)
    if not product or not product.is_active or product.price <= 0:
        await callback.answer("Товар недоступен", show_alert=True)
        return

    local_stock = await session.scalar(
        select(func.count(DigitalKey.id)).where(
            DigitalKey.product_id == product.id,
            DigitalKey.status == "AVAILABLE",
        )
    )
    if local_stock:
        stock_text = f"🟢 В наличии: {local_stock} шт. на складе"
        can_buy = True
    elif product.supplier_name == "sandromania":
        if not product.supplier_available or product.supplier_stock == 0:
            stock_text = "🔴 Нет в наличии у поставщика"
            can_buy = False
        elif product.supplier_stock is None:
            stock_text = "🟡 Точное количество уточняется у поставщика"
            can_buy = False
        else:
            stock_text = f"🟢 В наличии у поставщика: {product.supplier_stock} шт."
            can_buy = True
    else:
        stock_text = "🔴 Нет в наличии"
        can_buy = False

    description = product.description or "Описание скоро появится."
    text = (
        f"✨ <b>{product.name}</b>\n"
        f"{description}\n\n"
        f"💳 Цена: <b>{product.price:.2f} ₽</b>\n"
        f"📦 {stock_text}\n\n"
        "🏷 <i>BDAKA SHOP</i>"
    )
    markup = buy_keyboard(product.id) if can_buy else unavailable_keyboard()
    await send_section(callback.message, product_banner(product), text, reply_markup=markup)
    await callback.answer()
