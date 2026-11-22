import secrets
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, PreCheckoutQuery, LabeledPrice
from sqlalchemy import select
from database.models.user import User
from database.models.product import Product
from database.models.order import Order
from database.models.digital_key import DigitalKey
from database.models.transaction import Transaction
from config.constants import OrderStatus
from config.settings import settings
from services.order_delivery import send_order_delivery
from services.review_publisher import publish_purchase_notice
from suppliers.sandromania.client import SandromaniaClient, SandromaniaAPIError
from bot.keyboards.payments import payment_method_keyboard, invoice_keyboard
import math
from datetime import datetime
from database.models.payment import Payment
from payments.providers.platega import PlategaClient, PlategaError

router = Router()
RUB_PER_STAR = 0.95


def _stars_for_rubles(amount_rub: float) -> int:
    return math.ceil(float(amount_rub) / RUB_PER_STAR)


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
        # Replace the long product description with a compact checkout summary.
        checkout_text = (
            "🛒 <b>Расчёт заказа</b>\n"
            f"Товар: <b>{product.name}</b>\n"
            "🟢 Количество: 1\n"
            f"💰 Товар: <b>{product.price:.2f} ₽</b>\n"
            "<i>Выберите способ оплаты. </i>"
        )
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=checkout_text,
                reply_markup=payment_method_keyboard(product_id),
            )
        else:
            await callback.message.edit_text(
                checkout_text,
                reply_markup=payment_method_keyboard(product_id),
            )
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
    if method == "stars":
        await create_stars_order(callback, session, product_id)
        return
    if method == "crypto":
        await create_crypto_order(callback, session, product_id)
        return
    if method == "platega":
        await callback.answer(
            "Для цифровых товаров внутри Telegram доступна оплата только Telegram Stars.",
            show_alert=True,
        )
        return
    if method == "balance":
        await create_balance_order(callback, session, product_id)
        return
    await callback.answer("Неизвестный способ оплаты", show_alert=True)
    return
    user = await session.scalar(
        select(User).where(User.telegram_id == callback.from_user.id).with_for_update()
    )
    product = await session.get(Product, product_id)
    if not user:
        log.warning(
            "Checkout rejected: reason=user_not_found telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Профиль покупателя не найден. Отправьте /start и повторите попытку.", show_alert=True)
        return
    if not product:
        log.warning(
            "Checkout rejected: reason=product_not_found telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Товар не найден. Обновите каталог.", show_alert=True)
        return
    if not product.is_active:
        log.warning(
            "Checkout rejected: reason=product_inactive telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Этот товар временно недоступен.", show_alert=True)
        return
    if product.price is None or float(product.price) <= 0:
        log.warning(
            "Checkout rejected: reason=invalid_price telegram_id=%s product_id=%s price=%s",
            callback.from_user.id, product_id, product.price,
        )
        await callback.answer("У товара некорректная цена. Обратитесь в поддержку.", show_alert=True)
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
                "Не удалось проверить наличие у продавца. Попробуйте немного позже.",
                show_alert=True,
            )
            return
        if (
            live_item is None
            or not product.supplier_available
            or product.supplier_stock is None
            or product.supplier_stock <= 0
        ):
            await callback.answer("Товар закончился.", show_alert=True)
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
        order.status = OrderStatus.COMPLETED.value
        await session.commit()
        await send_order_delivery(callback.bot, order.id)
        await publish_purchase_notice(callback.bot, order.id)
        await callback.answer("Заказ выполнен")
        return

    await session.commit()  # persist order and stable idempotency key before external call
    try:
        result = await SandromaniaClient().purchase_and_wait(
            int(product.supplier_product_id), order.idempotency_key
        )
        order.supplier_order_id = result.get("order_id")
        delivery = result.get("delivery") or result.get("code")
        if delivery:
            session.add(DigitalKey(
                product_id=product.id, order_id=order.id,
                code=delivery, status="SOLD"
            ))
            order.status = OrderStatus.COMPLETED.value
            if product.supplier_stock is not None and product.supplier_stock > 0:
                product.supplier_stock -= 1
            await session.commit()
            await send_order_delivery(callback.bot, order.id)
            await publish_purchase_notice(callback.bot, order.id)
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
            "чтобы не допустить двойной покупки. Поддержка проверит статус."
        )
        await callback.answer("Заказ требует проверки", show_alert=True)


async def create_stars_order(callback: CallbackQuery, session, product_id: int):
    log.info(
        "Checkout callback received: method=stars telegram_id=%s product_id=%s",
        callback.from_user.id, product_id,
    )
    """Create a Telegram Stars invoice for a digital product."""
    user = await session.scalar(
        select(User).where(User.telegram_id == callback.from_user.id).with_for_update()
    )
    product = await session.get(Product, product_id)
    if not user:
        log.warning(
            "Checkout rejected: reason=user_not_found telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Профиль покупателя не найден. Отправьте /start и повторите попытку.", show_alert=True)
        return
    if not product:
        log.warning(
            "Checkout rejected: reason=product_not_found telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Товар не найден. Обновите каталог.", show_alert=True)
        return
    if not product.is_active:
        log.warning(
            "Checkout rejected: reason=product_inactive telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Этот товар временно недоступен.", show_alert=True)
        return
    if product.price is None or float(product.price) <= 0:
        log.warning(
            "Checkout rejected: reason=invalid_price telegram_id=%s product_id=%s price=%s",
            callback.from_user.id, product_id, product.price,
        )
        await callback.answer("У товара некорректная цена. Обратитесь в поддержку.", show_alert=True)
        return

    key = await session.scalar(
        select(DigitalKey).where(
            DigitalKey.product_id == product.id,
            DigitalKey.status == "AVAILABLE",
        ).with_for_update(skip_locked=True).limit(1)
    )
    use_supplier = (
        key is None
        and product.supplier_name == "sandromania"
        and product.supplier_product_id
    )
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
            log.exception("Stars stock check failed for product_id=%s", product.id)
            await callback.answer("Не удалось проверить наличие. Попробуйте позже.", show_alert=True)
            return
        if (
            live_item is None or not product.supplier_available
            or not product.supplier_stock or product.supplier_stock <= 0
        ):
            await callback.answer("Товар закончился.", show_alert=True)
            return

    if use_supplier and not await _supplier_ready(callback, product):
        return

    stars = _stars_for_rubles(product.price)
    order = Order(
        user_id=user.id,
        product_id=product.id,
        price=product.price,
        status=OrderStatus.PENDING.value,
        idempotency_key=secrets.token_urlsafe(24) if use_supplier else None,
    )
    session.add(order)
    await session.flush()
    payment = Payment(
        user_id=user.id,
        order_id=order.id,
        amount=float(product.price),
        provider="telegram_stars",
        status="PENDING",
        payload=f"stars-order-{order.id}",
    )
    session.add(payment)
    await session.commit()

    try:
        await callback.message.answer_invoice(
            title=product.name[:32],
            description=f"BDAKA SHOP — заказ #{order.id}",
            payload=payment.payload,
            currency="XTR",
            prices=[LabeledPrice(label=product.name[:32], amount=stars)],
        )
    except Exception:
        log.exception("Could not send Stars invoice for order_id=%s", order.id)
        order.status = OrderStatus.FAILED.value
        payment.status = "FAILED"
        await session.commit()
        await callback.answer("Не удалось создать счёт Telegram Stars", show_alert=True)
        return

    await callback.answer("Счёт Telegram Stars создан")


@router.pre_checkout_query()
async def validate_stars_order(query: PreCheckoutQuery, session):
    payment = await session.scalar(
        select(Payment).where(Payment.payload == query.invoice_payload).with_for_update()
    )
    if (
        not payment
        or payment.provider != "telegram_stars"
        or payment.order_id is None
        or payment.status != "PENDING"
        or query.currency != "XTR"
        or query.total_amount != _stars_for_rubles(payment.amount)
    ):
        await query.answer(ok=False, error_message="Счёт недействителен. Создайте новый.")
        return
    order = await session.get(Order, payment.order_id)
    user = await session.get(User, payment.user_id)
    if (
        not order or order.status != OrderStatus.PENDING.value
        or not user or user.telegram_id != query.from_user.id
    ):
        await query.answer(ok=False, error_message="Заказ недействителен или принадлежит другому пользователю.")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def confirm_stars_order(message, session):
    successful = message.successful_payment
    payment = await session.scalar(
        select(Payment)
        .where(Payment.payload == successful.invoice_payload)
        .with_for_update()
    )
    if (
        not payment or payment.provider != "telegram_stars"
        or payment.order_id is None or successful.currency != "XTR"
        or successful.total_amount != _stars_for_rubles(payment.amount)
    ):
        log.error("Unmatched Telegram Stars order payment from user=%s", message.from_user.id)
        await message.answer("Не удалось сопоставить оплату с заказом. Обратитесь в поддержку.")
        return

    order = await session.scalar(
        select(Order).where(Order.id == payment.order_id).with_for_update()
    )
    user = await session.get(User, payment.user_id)
    if not order or not user or user.telegram_id != message.from_user.id:
        await message.answer("Не удалось подтвердить владельца заказа. Обратитесь в поддержку.")
        return

    charge_id = successful.telegram_payment_charge_id
    if payment.status == "CONFIRMED":
        await message.answer("Оплата этого заказа уже была обработана.")
        return
    if order.status != OrderStatus.PENDING.value:
        await message.answer("Статус заказа изменился. Обратитесь в поддержку.")
        return

    payment.status = "CONFIRMED"
    payment.external_id = charge_id
    payment.confirmed_at = datetime.utcnow()
    order.status = OrderStatus.PAID.value
    await session.commit()

    await message.answer(
        f"✅ Оплата заказа <b>#{order.id}</b> подтверждена в Telegram Stars. "
        "Начинаем подготовку товара."
    )
    from services.payment_service import fulfill_paid_order
    await fulfill_paid_order(order.id, message.bot)


async def create_platega_order(callback: CallbackQuery, session, product_id: int):
    log.info(
        "Checkout callback received: method=platega telegram_id=%s product_id=%s",
        callback.from_user.id, product_id,
    )
    user = await session.scalar(
        select(User).where(User.telegram_id == callback.from_user.id).with_for_update()
    )
    product = await session.get(Product, product_id)
    if not user:
        log.warning(
            "Checkout rejected: reason=user_not_found telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Профиль покупателя не найден. Отправьте /start и повторите попытку.", show_alert=True)
        return
    if not product:
        log.warning(
            "Checkout rejected: reason=product_not_found telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Товар не найден. Обновите каталог.", show_alert=True)
        return
    if not product.is_active:
        log.warning(
            "Checkout rejected: reason=product_inactive telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Этот товар временно недоступен.", show_alert=True)
        return
    if product.price is None or float(product.price) <= 0:
        log.warning(
            "Checkout rejected: reason=invalid_price telegram_id=%s product_id=%s price=%s",
            callback.from_user.id, product_id, product.price,
        )
        await callback.answer("У товара некорректная цена. Обратитесь в поддержку.", show_alert=True)
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
            await callback.answer("Товар закончился.", show_alert=True)
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
        f"🧾 <b>Заказ #{order.id} создан</b>"
        f"Товар: {product.name}"
        f"К оплате: <b>{product.price:.2f} ₽</b>"
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
    if not payment or payment.provider not in {"platega", "cryptobot"}:
        await callback.answer("Платёж не найден", show_alert=True)
        return
    if payment.provider == "cryptobot":
        if payment.status == "CONFIRMED":
            await callback.answer("Оплата подтверждена. Если товар ещё не пришёл, заказ обрабатывается.", show_alert=True)
            return
        if not payment.external_id:
            await callback.answer("Счёт ещё создаётся", show_alert=True)
            return
        try:
            from payments.providers.cryptobot import CryptoBotClient
            from services.payment_service import process_cryptobot_invoice
            invoice = await CryptoBotClient().get_invoice(payment.external_id)
            if not invoice:
                await callback.answer("Счёт не найден", show_alert=True)
                return
            state = str(invoice.get("status") or "").lower()
            if state == "paid":
                await process_cryptobot_invoice(invoice, callback.bot)
                await callback.answer("Оплата подтверждена. Выдача товара запущена.", show_alert=True)
            elif state == "expired":
                await process_cryptobot_invoice(invoice, callback.bot)
                await callback.answer("Счёт истёк. Оформите заказ заново.", show_alert=True)
            else:
                await callback.answer("Оплата пока не поступила. Попробуйте через минуту.", show_alert=True)
        except Exception:
            log.exception("Crypto payment status check failed: order_id=%s", order_id)
            await callback.answer("Не удалось проверить статус. Попробуйте позже.", show_alert=True)
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


async def create_crypto_order(callback: CallbackQuery, session, product_id: int):
    log.info(
        "Checkout callback received: method=crypto telegram_id=%s product_id=%s",
        callback.from_user.id, product_id,
    )
    """Create an order and a Crypto Pay invoice (price in RUB, buyer pays in crypto)."""
    from payments.providers.cryptobot import CryptoBotClient, CryptoBotError

    if not settings.crypto_pay_enabled:
        await callback.answer("Оплата криптовалютой пока не настроена", show_alert=True)
        return
    user = await session.scalar(
        select(User).where(User.telegram_id == callback.from_user.id).with_for_update()
    )
    product = await session.get(Product, product_id)
    if not user:
        log.warning(
            "Checkout rejected: reason=user_not_found telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Профиль покупателя не найден. Отправьте /start и повторите попытку.", show_alert=True)
        return
    if not product:
        log.warning(
            "Checkout rejected: reason=product_not_found telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Товар не найден. Обновите каталог.", show_alert=True)
        return
    if not product.is_active:
        log.warning(
            "Checkout rejected: reason=product_inactive telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Этот товар временно недоступен.", show_alert=True)
        return
    if product.price is None or float(product.price) <= 0:
        log.warning(
            "Checkout rejected: reason=invalid_price telegram_id=%s product_id=%s price=%s",
            callback.from_user.id, product_id, product.price,
        )
        await callback.answer("У товара некорректная цена. Обратитесь в поддержку.", show_alert=True)
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
            await callback.answer("Товар закончился.", show_alert=True)
            return

    if use_supplier and not await _supplier_ready(callback, product):
        return

    order = Order(
        user_id=user.id, product_id=product.id, price=product.price,
        status=OrderStatus.PENDING.value,
        idempotency_key=secrets.token_urlsafe(24) if use_supplier else None,
    )
    session.add(order)
    await session.flush()
    payment = Payment(
        user_id=user.id, order_id=order.id, amount=float(product.price),
        provider="cryptobot", status="CREATING", payload=f"crypto-order-{order.id}",
    )
    session.add(payment)
    await session.commit()

    try:
        invoice = await CryptoBotClient().create_invoice(
            product.price,
            fiat=settings.currency,
            accepted_assets=settings.crypto_accepted_assets,
            description=f"BDAKA SHOP — заказ #{order.id}",
            payload=payment.payload,
            expires_in=settings.crypto_pay_expires_in,
        )
        pay_url = invoice.get("bot_invoice_url") or invoice.get("pay_url")
        if not invoice.get("invoice_id") or not pay_url:
            raise CryptoBotError(f"Unexpected invoice schema: keys={sorted(invoice)}")
        payment.external_id = str(invoice["invoice_id"])
        payment.payment_url = str(pay_url)
        payment.status = "PENDING"
        await session.commit()
    except Exception:
        log.exception("Could not create Crypto Pay invoice for order_id=%s", order.id)
        order.status = OrderStatus.FAILED.value
        payment.status = "FAILED"
        await session.commit()
        await callback.message.answer("Не удалось создать счёт. Деньги не списаны. Попробуйте позже.")
        await callback.answer("Ошибка создания счёта", show_alert=True)
        return

    minutes = max(1, settings.crypto_pay_expires_in // 60)
    await callback.message.answer(
        f"🧾 <b>Заказ #{order.id} создан</b>\n"
        f"Товар: {product.name}\n"
        f"К оплате: <b>{product.price:.2f} ₽</b> (в криптовалюте по курсу Crypto Bot)\n"
        f"Счёт действует {minutes} мин. Товар придёт автоматически после оплаты.",
        reply_markup=invoice_keyboard(str(pay_url), order.id),
    )
    await callback.answer("Счёт создан")


async def _supplier_ready(callback: CallbackQuery, product) -> bool:
    """Do not take money for a product the supplier balance cannot cover."""
    from services.supplier_sync import supplier_can_afford
    from services.payment_service import supplier_balance_watch
    try:
        ok = await supplier_can_afford(product)
    except Exception:
        log.exception("Supplier balance check failed for product_id=%s", product.id)
        await callback.answer("Не удалось проверить доступность товара. Попробуйте позже.", show_alert=True)
        return False
    if not ok:
        log.warning("Supplier balance too low for product_id=%s", product.id)
        await supplier_balance_watch(callback.bot, force=True)
        await callback.answer("Товар временно недоступен. Попробуйте позже.", show_alert=True)
        return False
    return True


async def create_balance_order(callback: CallbackQuery, session, product_id: int):
    log.info(
        "Checkout callback received: method=balance telegram_id=%s product_id=%s",
        callback.from_user.id, product_id,
    )
    """Pay for a product from the internal balance, then run the normal fulfilment."""
    user = await session.scalar(
        select(User).where(User.telegram_id == callback.from_user.id).with_for_update()
    )
    product = await session.get(Product, product_id)
    if not user:
        log.warning(
            "Checkout rejected: reason=user_not_found telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Профиль покупателя не найден. Отправьте /start и повторите попытку.", show_alert=True)
        return
    if not product:
        log.warning(
            "Checkout rejected: reason=product_not_found telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Товар не найден. Обновите каталог.", show_alert=True)
        return
    if not product.is_active:
        log.warning(
            "Checkout rejected: reason=product_inactive telegram_id=%s product_id=%s",
            callback.from_user.id, product_id,
        )
        await callback.answer("Этот товар временно недоступен.", show_alert=True)
        return
    if product.price is None or float(product.price) <= 0:
        log.warning(
            "Checkout rejected: reason=invalid_price telegram_id=%s product_id=%s price=%s",
            callback.from_user.id, product_id, product.price,
        )
        await callback.answer("У товара некорректная цена. Обратитесь в поддержку.", show_alert=True)
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
            await callback.answer("Товар закончился.", show_alert=True)
            return
        if not await _supplier_ready(callback, product):
            return
    if round(float(user.balance), 2) < round(float(product.price), 2):
        await callback.answer("Недостаточно средств на балансе. Пополните баланс в профиле.", show_alert=True)
        return

    order = Order(
        user_id=user.id, product_id=product.id, price=product.price,
        status=OrderStatus.PAID.value,
        idempotency_key=secrets.token_urlsafe(24) if use_supplier else None,
    )
    user.balance -= product.price
    session.add(order)
    await session.flush()
    session.add(Transaction(
        user_id=user.id, amount=-product.price, type="PURCHASE",
        description=f"Покупка #{order.id}: {product.name}",
    ))
    await session.commit()
    await callback.answer("Оплачено с баланса")
    from services.payment_service import fulfill_paid_order
    await fulfill_paid_order(order.id, callback.bot)
