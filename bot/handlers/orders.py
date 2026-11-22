import secrets
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, PreCheckoutQuery, LabeledPrice, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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
from bot.keyboards.products import quantity_keyboard
import math
from datetime import datetime
from database.models.payment import Payment
from payments.providers.platega import PlategaClient, PlategaError

router = Router()

class QuantityStates(StatesGroup):
    waiting_for_quantity = State()

RUB_PER_STAR = 0.95


def _stars_for_rubles(amount_rub: float) -> int:
    return math.ceil(float(amount_rub) / RUB_PER_STAR)


log = logging.getLogger(__name__)

@router.callback_query(F.data.startswith("buy:"))
async def buy_product(callback: CallbackQuery, session, state: FSMContext):
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
        local_stock = await session.scalar(select(__import__('sqlalchemy').func.count(DigitalKey.id)).where(
            DigitalKey.product_id == product_id, DigitalKey.status == "AVAILABLE")) or 0
        max_quantity = local_stock
        if product.supplier_name == "sandromania" and product.supplier_available:
            max_quantity = max_quantity if max_quantity > 0 else int(product.supplier_stock or 0)
        if max_quantity <= 0:
            await callback.answer("Товар временно отсутствует", show_alert=True)
            return
        max_quantity = min(max_quantity, 100)
        text = (f"🛒 <b>Выбор количества</b>\nТовар: <b>{product.name}</b>\n"
                f"Цена за 1 шт.: <b>{product.price:.2f} ₽</b>\n"
                f"Доступно: <b>{max_quantity} шт.</b>\n\n"
                f"Выберите количество кнопками или нажмите на число для ручного ввода.\n"
                f"Итого: <b>{product.price:.2f} ₽</b>")
        await callback.message.edit_caption(caption=text, reply_markup=quantity_keyboard(product_id, 1, max_quantity)) if callback.message.photo else await callback.message.edit_text(text, reply_markup=quantity_keyboard(product_id, 1, max_quantity))
        await state.clear()
        await callback.answer()
        return
    if len(parts) != 4:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    method, raw_product_id, raw_quantity = parts[1], parts[2], parts[3]
    try:
        product_id, quantity = int(raw_product_id), int(raw_quantity)
    except ValueError:
        await callback.answer("Некорректный товар или количество", show_alert=True)
        return
    if not 1 <= quantity <= 100:
        await callback.answer("Можно заказать от 1 до 100 штук за один заказ", show_alert=True)
        return
    if method == "stars":
        await create_stars_order(callback, session, product_id, quantity)
    elif method == "crypto":
        await create_crypto_order(callback, session, product_id, quantity)
    elif method == "platega":
        await create_platega_order(callback, session, product_id, quantity)
    elif method == "balance":
        await create_balance_order(callback, session, product_id, quantity)
    else:
        await callback.answer("Неизвестный способ оплаты", show_alert=True)


@router.callback_query(F.data.startswith("qty:change:"))
async def change_quantity(callback: CallbackQuery, session):
    _, _, raw_id, raw_qty = callback.data.split(":")
    product_id, quantity = int(raw_id), int(raw_qty)
    product = await session.get(Product, product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True); return
    local_stock = await session.scalar(select(__import__('sqlalchemy').func.count(DigitalKey.id)).where(
        DigitalKey.product_id == product_id, DigitalKey.status == "AVAILABLE")) or 0
    max_quantity = local_stock
    if product.supplier_name == "sandromania" and product.supplier_available:
        max_quantity = max_quantity if max_quantity > 0 else int(product.supplier_stock or 0)
    max_quantity = min(max_quantity, 100)
    quantity = max(1, min(quantity, max_quantity))
    text = (f"🛒 <b>Выбор количества</b>\nТовар: <b>{product.name}</b>\n"
            f"Цена за 1 шт.: <b>{product.price:.2f} ₽</b>\nДоступно: <b>{max_quantity} шт.</b>\n\n"
            f"Количество: <b>{quantity}</b>\nИтого: <b>{product.price * quantity:.2f} ₽</b>")
    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=quantity_keyboard(product_id, quantity, max_quantity))
    else:
        await callback.message.edit_text(text, reply_markup=quantity_keyboard(product_id, quantity, max_quantity))
    await callback.answer()


@router.callback_query(F.data.startswith("qty:custom:"))
async def request_custom_quantity(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[2])
    await state.update_data(quantity_product_id=product_id)
    await state.set_state(QuantityStates.waiting_for_quantity)
    await callback.message.answer("Введите нужное количество числом (от 1 до 100).")
    await callback.answer()


@router.message(QuantityStates.waiting_for_quantity)
async def save_custom_quantity(message: Message, state: FSMContext, session):
    try:
        quantity = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите целое число от 1 до 100.")
        return
    if not 1 <= quantity <= 100:
        await message.answer("Количество должно быть от 1 до 100.")
        return
    data = await state.get_data()
    product_id = int(data["quantity_product_id"])
    product = await session.get(Product, product_id)
    if not product:
        await state.clear(); await message.answer("Товар не найден."); return
    local_stock = await session.scalar(select(__import__('sqlalchemy').func.count(DigitalKey.id)).where(
        DigitalKey.product_id == product_id, DigitalKey.status == "AVAILABLE")) or 0
    max_quantity = local_stock
    if product.supplier_name == "sandromania" and product.supplier_available:
        max_quantity = max_quantity if max_quantity > 0 else int(product.supplier_stock or 0)
    max_quantity = min(max_quantity, 100)
    if quantity > max_quantity:
        await message.answer(f"Сейчас доступно только {max_quantity} шт. Введите меньшее количество.")
        return
    await state.clear()
    text = (f"🛒 <b>Выбор количества</b>\nТовар: <b>{product.name}</b>\n"
            f"Цена за 1 шт.: <b>{product.price:.2f} ₽</b>\nКоличество: <b>{quantity}</b>\n"
            f"Итого: <b>{product.price * quantity:.2f} ₽</b>")
    from bot.keyboards.products import quantity_keyboard
    await message.answer(text, reply_markup=quantity_keyboard(product_id, quantity, max_quantity), parse_mode="HTML")


@router.callback_query(F.data.startswith("qty:confirm:"))
async def confirm_quantity(callback: CallbackQuery, session):
    _, _, raw_id, raw_qty = callback.data.split(":")
    product_id, quantity = int(raw_id), int(raw_qty)
    product = await session.get(Product, product_id)
    if not product or not product.is_active:
        await callback.answer("Товар недоступен", show_alert=True); return
    total = float(product.price) * quantity
    text = (f"🛒 <b>Расчёт заказа</b>\nТовар: <b>{product.name}</b>\n"
            f"🔢 Количество: <b>{quantity}</b>\nЦена за штуку: {product.price:.2f} ₽\n"
            f"💰 Итого: <b>{total:.2f} ₽</b>\n\nВыберите способ оплаты.")
    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=payment_method_keyboard(product_id, quantity))
    else:
        await callback.message.edit_text(text, reply_markup=payment_method_keyboard(product_id, quantity))
    await callback.answer()


async def create_stars_order(callback: CallbackQuery, session, product_id: int, quantity: int = 1):
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

    local_count = await session.scalar(
        select(__import__('sqlalchemy').func.count(DigitalKey.id)).where(
            DigitalKey.product_id == product.id, DigitalKey.status == "AVAILABLE"
        )
    ) or 0
    if 0 < local_count < quantity:
        await callback.answer(f"На складе доступно только {local_count} шт.", show_alert=True)
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
    if local_count < quantity and not use_supplier:
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
            or not product.supplier_stock or product.supplier_stock < quantity
        ):
            await callback.answer("Товар закончился.", show_alert=True)
            return

    total_price = float(product.price) * quantity
    stars = _stars_for_rubles(total_price)
    order = Order(
        user_id=user.id,
        product_id=product.id,
        price=total_price, quantity=quantity,
        status=OrderStatus.PENDING.value,
        idempotency_key=secrets.token_urlsafe(24) if use_supplier else None,
    )
    session.add(order)
    await session.flush()
    payment = Payment(
        user_id=user.id,
        order_id=order.id,
        amount=total_price,
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
            prices=[LabeledPrice(label=f"{product.name[:22]} x{quantity}"[:32], amount=stars)],
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


async def create_platega_order(callback: CallbackQuery, session, product_id: int, quantity: int = 1):
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

    local_count = await session.scalar(
        select(__import__('sqlalchemy').func.count(DigitalKey.id)).where(
            DigitalKey.product_id == product.id, DigitalKey.status == "AVAILABLE"
        )
    ) or 0
    if 0 < local_count < quantity:
        await callback.answer(f"На складе доступно только {local_count} шт.", show_alert=True)
        return
    key = await session.scalar(
        select(DigitalKey).where(
            DigitalKey.product_id == product.id, DigitalKey.status == "AVAILABLE"
        ).with_for_update(skip_locked=True).limit(1)
    )
    use_supplier = local_count == 0 and product.supplier_name == "sandromania" and product.supplier_product_id
    if local_count < quantity and not use_supplier:
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
        if live_item is None or not product.supplier_available or not product.supplier_stock or product.supplier_stock < quantity:
            await callback.answer("Товар закончился.", show_alert=True)
            return

    if not settings.platega_enabled:
        await callback.answer("Оплата Platega пока не настроена", show_alert=True)
        return

    total_price = float(product.price) * quantity
    order = Order(
        user_id=user.id, product_id=product.id, price=total_price, quantity=quantity,
        status=OrderStatus.PENDING.value,
        idempotency_key=secrets.token_urlsafe(24) if use_supplier else None,
    )
    session.add(order)
    await session.flush()
    payment = Payment(
        user_id=user.id, order_id=order.id, amount=total_price,
        provider="platega", status="CREATING", payload=f"order-{order.id}",
    )
    session.add(payment)
    await session.commit()

    try:
        invoice = await PlategaClient().create_invoice(
            amount=total_price, currency=settings.currency,
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


async def create_crypto_order(callback: CallbackQuery, session, product_id: int, quantity: int = 1):
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

    local_count = await session.scalar(
        select(__import__('sqlalchemy').func.count(DigitalKey.id)).where(
            DigitalKey.product_id == product.id, DigitalKey.status == "AVAILABLE"
        )
    ) or 0
    if 0 < local_count < quantity:
        await callback.answer(f"На складе доступно только {local_count} шт.", show_alert=True)
        return
    key = await session.scalar(
        select(DigitalKey).where(
            DigitalKey.product_id == product.id, DigitalKey.status == "AVAILABLE"
        ).with_for_update(skip_locked=True).limit(1)
    )
    use_supplier = local_count == 0 and product.supplier_name == "sandromania" and product.supplier_product_id
    if local_count < quantity and not use_supplier:
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
        if live_item is None or not product.supplier_available or not product.supplier_stock or product.supplier_stock < quantity:
            await callback.answer("Товар закончился.", show_alert=True)
            return

    total_price = float(product.price) * quantity
    order = Order(
        user_id=user.id, product_id=product.id, price=total_price, quantity=quantity,
        status=OrderStatus.PENDING.value,
        idempotency_key=secrets.token_urlsafe(24) if use_supplier else None,
    )
    session.add(order)
    await session.flush()
    payment = Payment(
        user_id=user.id, order_id=order.id, amount=total_price,
        provider="cryptobot", status="CREATING", payload=f"crypto-order-{order.id}",
    )
    session.add(payment)
    await session.commit()

    try:
        invoice = await CryptoBotClient().create_invoice(
            total_price,
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


async def create_balance_order(callback: CallbackQuery, session, product_id: int, quantity: int = 1):
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
    local_count = await session.scalar(
        select(__import__('sqlalchemy').func.count(DigitalKey.id)).where(
            DigitalKey.product_id == product.id, DigitalKey.status == "AVAILABLE"
        )
    ) or 0
    if 0 < local_count < quantity:
        await callback.answer(f"На складе доступно только {local_count} шт.", show_alert=True)
        return
    key = await session.scalar(
        select(DigitalKey).where(
            DigitalKey.product_id == product.id, DigitalKey.status == "AVAILABLE"
        ).with_for_update(skip_locked=True).limit(1)
    )
    use_supplier = local_count == 0 and product.supplier_name == "sandromania" and product.supplier_product_id
    if local_count < quantity and not use_supplier:
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
        if live_item is None or not product.supplier_available or not product.supplier_stock or product.supplier_stock < quantity:
            await callback.answer("Товар закончился.", show_alert=True)
            return
    total_price = float(product.price) * quantity
    if round(float(user.balance), 2) < round(total_price, 2):
        await callback.answer("Недостаточно средств на балансе. Пополните баланс в профиле.", show_alert=True)
        return

    order = Order(
        user_id=user.id, product_id=product.id, price=total_price, quantity=quantity,
        status=OrderStatus.PAID.value,
        idempotency_key=secrets.token_urlsafe(24) if use_supplier else None,
    )
    user.balance -= total_price
    session.add(order)
    await session.flush()
    session.add(Transaction(
        user_id=user.id, amount=-total_price, type="PURCHASE",
        description=f"Покупка #{order.id}: {product.name}",
    ))
    await session.commit()
    await callback.answer("Оплачено с баланса")
    from services.payment_service import fulfill_paid_order
    await fulfill_paid_order(order.id, callback.bot)
