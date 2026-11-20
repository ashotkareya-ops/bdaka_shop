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
from bot.keyboards.payments import payment_method_keyboard, invoice_keyboard
from database.models.payment import Payment
from payments.providers.platega import PlategaClient, PlategaError

router = Router()
log = logging.getLogger(__name__)

@router.callback_query(F.data.startswith("buy:"))
async def buy_product(callback: CallbackQuery, session):
    parts = callback.data.split(":")
    if len(parts) == 2:
        try:
            product_id = int(parts[1])
        except ValueError:
            await callback.answer("Некорректный товар", show_alert=True)
            return
        product = await session.get(Product, product_id)
        if not product or not product.is_active:
            await callback.answer("Товар недоступен", show_alert=True)
            return
        await callback.message.edit_reply_markup(reply_markup=payment_method_keyboard(product_id))
        await callback.answer()
        return
    if len(parts) != 3:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    method, raw_product_id = parts[1], parts[2]
    try:
        product_id = int(raw_product_id)
    except ValueError:
        await callback.answer("Некорректный товар", show_alert=True)
        return
    if method == "platega":
        await create_platega_order(callback, session, product_id)
        return
    if method != "balance":
        await callback.answer("Неизвестный способ оплаты", show_alert=True)
        return
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


async def create_platega_order(callback: CallbackQuery, session, product_id: int):
    user = await session.scalar(
        select(User).where(User.telegram_id == callback.from_user.id).with_for_update()
    )
    product = await session.get(Product, product_id)
    if not user or not product or not product.is_active or product.price <= 0:
        await callback.answer("Не удалось оформить заказ", show_alert=True)
        return

    key = await session.scalar(
        select(DigitalKey).where(
            DigitalKey.product_id == product.id, DigitalKey.status == "AVAILABLE"
        ).with_for_update(skip_locked=True).limit(1)
    )
    use_supplier = key is None and product.supplier_name == "sandromania" and product.supplier_product_id
    if key is None and not use_supplier:
        await callback.answer("Товар временно отсутствует", show_alert=True)
        return
    if use_supplier:
        if not settings.sandromania_enabled:
            await callback.answer("Интеграция поставщика не настроена", show_alert=True)
            return
        try:
            from services.supplier_sync import refresh_supplier_product_stock
            live_item = await refresh_supplier_product_stock(session, product)
        except Exception:
            log.exception("Supplier stock check failed for product_id=%s", product.id)
            await callback.answer("Не удалось проверить наличие. Попробуйте позже.", show_alert=True)
            return
        if live_item is None or not product.supplier_available or not product.supplier_stock or product.supplier_stock <= 0:
            await callback.answer("Товар закончился у поставщика", show_alert=True)
            return

    if not settings.platega_enabled:
        await callback.answer("Оплата Platega пока не настроена", show_alert=True)
        return

    order = Order(
        user_id=user.id, product_id=product.id, price=product.price,
        status=OrderStatus.PENDING.value,
        idempotency_key=secrets.token_urlsafe(24) if use_supplier else None,
    )
    session.add(order)
    await session.flush()
    payment = Payment(
        user_id=user.id, order_id=order.id, amount=product.price,
        provider="platega", status="CREATING", payload=f"order-{order.id}",
    )
    session.add(payment)
    await session.commit()

    try:
        invoice = await PlategaClient().create_invoice(
            amount=product.price, currency=settings.currency,
            payload=f"order-{order.id}", description=f"BDAKA SHOP — заказ #{order.id}",
        )
        payment.external_id = invoice["external_id"]
        payment.payment_url = invoice["url"]
        payment.status = "PENDING"
        await session.commit()
    except Exception:
        log.exception("Could not create Platega invoice for order_id=%s", order.id)
        order.status = OrderStatus.FAILED.value
        payment.status = "FAILED"
        await session.commit()
        await callback.message.answer("Не удалось создать платёж. Деньги не списаны. Попробуйте позже.")
        await callback.answer("Ошибка создания платежа", show_alert=True)
        return

    await callback.message.answer(
        f"🧾 <b>Заказ #{order.id} создан</b>\n"
        f"Товар: {product.name}\n"
        f"К оплате: <b>{product.price:.2f} ₽</b>\n\n"
        "После оплаты вернитесь в бот. Товар будет выдан после подтверждения Platega.",
        reply_markup=invoice_keyboard(invoice["url"], order.id),
    )
    await callback.answer("Счёт создан")


@router.callback_query(F.data.startswith("payment:check:"))
async def check_payment(callback: CallbackQuery, session):
    try:
        order_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный заказ", show_alert=True)
        return
    payment = await session.scalar(
        select(Payment).join(Order, Payment.order_id == Order.id)
        .where(Order.id == order_id, Order.user_id == select(User.id).where(User.telegram_id == callback.from_user.id).scalar_subquery())
    )
    if not payment or payment.provider != "platega":
        await callback.answer("Платёж не найден", show_alert=True)
        return
    if payment.status == "CONFIRMED":
        await callback.answer("Оплата подтверждена. Если товар ещё не пришёл, заказ обрабатывается.", show_alert=True)
        return
    if not payment.external_id:
        await callback.answer("Платёж ещё создаётся", show_alert=True)
        return
    try:
        state = await PlategaClient().get_transaction(payment.external_id)
        status = str(state.get("status", "")).upper()
        if status == "CONFIRMED":
            details = state.get("paymentDetails") or {}
            from services.payment_service import process_platega_callback
            await process_platega_callback({
                "id": payment.external_id,
                "amount": details.get("amount", state.get("amount")),
                "currency": details.get("currency", state.get("currency")),
                "status": "CONFIRMED",
                "payload": state.get("payload") or payment.payload,
            }, callback.bot)
            await callback.answer("Оплата подтверждена. Выдача товара запущена.", show_alert=True)
        else:
            await callback.answer(f"Статус платежа: {status or 'неизвестен'}", show_alert=True)
    except Exception:
        log.exception("Payment status check failed: order_id=%s", order_id)
        await callback.answer("Не удалось проверить статус. Попробуйте позже.", show_alert=True)
