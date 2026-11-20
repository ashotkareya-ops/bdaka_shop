import secrets
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select
from database.models.user import User
from database.models.product import Product
from database.models.order import Order
from database.models.digital_key import DigitalKey
from database.models.transaction import Transaction
from config.constants import OrderStatus
from config.settings import settings
from suppliers.sandromania.client import SandromaniaClient, SandromaniaAPIError

router = Router()
log = logging.getLogger(__name__)

@router.callback_query(F.data.startswith("buy:"))
async def buy_product(callback: CallbackQuery, session):
    product_id = int(callback.data.split(":")[1])
    user = await session.scalar(
        select(User).where(User.telegram_id == callback.from_user.id).with_for_update()
    )
    product = await session.get(Product, product_id)
    if not user or not product or not product.is_active:
        await callback.answer("Не удалось оформить заказ", show_alert=True)
        return

    key = await session.scalar(
        select(DigitalKey).where(
            DigitalKey.product_id == product.id,
            DigitalKey.status == "AVAILABLE"
        ).with_for_update(skip_locked=True).limit(1)
    )

    # Supplier fallback is enabled only when product has an explicit supplier mapping.
    use_supplier = key is None and product.supplier_name == "sandromania" and product.supplier_product_id
    if key is None and not use_supplier:
        await callback.answer("Товар временно отсутствует", show_alert=True)
        return
    if use_supplier and not settings.sandromania_enabled:
        await callback.answer("Интеграция поставщика не настроена", show_alert=True)
        return
    if use_supplier:
        try:
            from services.supplier_sync import refresh_supplier_product_stock
            live_item = await refresh_supplier_product_stock(session, product)
        except Exception:
            log.exception("Could not refresh supplier stock for product_id=%s", product.id)
            await callback.answer(
                "Не удалось проверить наличие у поставщика. Попробуйте немного позже.",
                show_alert=True,
            )
            return
        if (
            live_item is None
            or not product.supplier_available
            or product.supplier_stock is None
            or product.supplier_stock <= 0
        ):
            await callback.answer("Товар закончился или поставщик не подтвердил остаток.", show_alert=True)
            return
    if user.balance < product.price:
        await callback.answer("Недостаточно средств на балансе", show_alert=True)
        return

    order = Order(
        user_id=user.id, product_id=product.id, price=product.price,
        status=OrderStatus.PROCESSING.value if use_supplier else OrderStatus.COMPLETED.value,
        idempotency_key=secrets.token_urlsafe(24) if use_supplier else None
    )
    user.balance -= product.price
    session.add(order)
    session.add(Transaction(
        user_id=user.id, amount=-product.price, type="PURCHASE",
        description=f"Покупка: {product.name}"
    ))
    if key:
        key.status = "SOLD"
        key.order = order
        await session.commit()
        await callback.message.answer(
            f"✅ <b>Покупка успешно оформлена!</b>\n\n"
            f"Товар: {product.name}\nВаш CDK:\n<code>{key.code}</code>\n\n"
            "Сохраните код и следуйте инструкции поставщика."
        )
        await callback.answer("Заказ выполнен")
        return

    await session.commit()  # persist order and stable idempotency key before external call
    try:
        result = await SandromaniaClient().purchase_and_wait(
            int(product.supplier_product_id), order.idempotency_key
        )
        order.supplier_order_id = result.get("order_id")
        if result.get("code"):
            session.add(DigitalKey(
                product_id=product.id, order_id=order.id,
                code=result["code"], status="SOLD"
            ))
            order.status = OrderStatus.COMPLETED.value
            if product.supplier_stock is not None and product.supplier_stock > 0:
                product.supplier_stock -= 1
            await session.commit()
            await callback.message.answer(
                f"✅ <b>Покупка успешно оформлена!</b>\n\n"
                f"Товар: {product.name}\nВаш CDK:\n<code>{result['code']}</code>\n\n"
                "Сохраните код и следуйте инструкции поставщика."
            )
        else:
            order.status = OrderStatus.PROCESSING.value
            await session.commit()
            await callback.message.answer(
                f"⏳ Заказ #{order.id} принят поставщиком и обрабатывается. "
                "Код будет выдан после подтверждения результата. Обратитесь в поддержку, если ожидание затянулось."
            )
        await callback.answer("Заказ отправлен поставщику")
    except Exception:
        log.exception("Sandromania purchase result is uncertain for local order %s", order.id)
        # A timeout/5xx can happen after the supplier has accepted the purchase.
        # Keep the same idempotency key and do NOT auto-refund or retry with a new key.
        # Reconcile this order with the supplier before refunding or attempting another purchase.
        order.status = OrderStatus.PROCESSING.value
        await session.commit()
        await callback.message.answer(
            f"⏳ Не удалось однозначно получить результат закупки. "
            f"Заказ #{order.id} сохранён для проверки; средства пока удерживаются, "
            "чтобы не допустить двойной покупки. Поддержка проверит статус у поставщика."
        )
        await callback.answer("Заказ требует проверки", show_alert=True)
