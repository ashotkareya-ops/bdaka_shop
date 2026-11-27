import hmac
import logging
from datetime import datetime
from sqlalchemy import select
from database.engine import SessionLocal
from database.models.payment import Payment
from database.models.order import Order
from database.models.product import Product
from database.models.digital_key import DigitalKey
from database.models.user import User
from config.constants import OrderStatus
from config.settings import settings
from suppliers.sandromania.client import SandromaniaClient
from services.order_delivery import send_order_delivery
from services.review_publisher import publish_purchase_notice

log = logging.getLogger(__name__)


def verify_callback_headers(headers) -> bool:
    merchant = headers.get("X-MerchantId", "")
    secret = headers.get("X-Secret", "")
    return bool(
        settings.platega_enabled
        and hmac.compare_digest(merchant, settings.platega_merchant_id)
        and hmac.compare_digest(secret, settings.platega_secret)
    )


async def process_platega_callback(data: dict, bot):
    external_id = str(data.get("id") or "")
    status = str(data.get("status") or "").upper()
    if not external_id or not status:
        raise ValueError("Callback is missing id/status")

    async with SessionLocal() as session:
        payment = await session.scalar(
            select(Payment).where(Payment.external_id == external_id).with_for_update()
        )
        if not payment or payment.provider != "platega":
            raise ValueError("Unknown Platega transaction")
        order = None
        if payment.order_id is not None:
            order = await session.scalar(
                select(Order).where(Order.id == payment.order_id).with_for_update()
            )
            if not order:
                raise ValueError("Order for payment was not found")

        # Do not trust callback status alone: validate payload, currency and exact amount.
        callback_payload = str(data.get("payload") or "")
        expected_payload = payment.payload or (f"order-{order.id}" if order else "")
        if not expected_payload or callback_payload != expected_payload:
            raise ValueError("Payment payload mismatch")
        if str(data.get("currency") or "").upper() != settings.currency.upper():
            raise ValueError("Payment currency mismatch")
        try:
            callback_amount = round(float(data.get("amount")), 2)
        except (TypeError, ValueError):
            raise ValueError("Invalid payment amount")
        if callback_amount != round(float(payment.amount), 2):
            raise ValueError("Payment amount mismatch")

        if status == "CONFIRMED":
            if payment.status != "CONFIRMED":
                payment.status = "CONFIRMED"
                payment.confirmed_at = datetime.utcnow()
                if order is None:
                    # Top-up payments have no order. Credit exactly once while the payment row is locked.
                    user = await session.scalar(select(User).where(User.id == payment.user_id).with_for_update())
                    if not user:
                        raise ValueError("User for top-up payment was not found")
                    from services.balance_service import add_balance
                    await add_balance(session, user, float(payment.amount),
                                      f"Пополнение баланса через Platega #{payment.id}",
                                      transaction_type="TOPUP")
                elif order.status == OrderStatus.PENDING.value:
                    order.status = OrderStatus.PAID.value
            await session.commit()
            if order is not None:
                await fulfill_paid_order(order.id, bot)
            else:
                user = await session.get(User, payment.user_id)
                if user:
                    await bot.send_message(user.telegram_id,
                        f"✅ <b>Баланс пополнен!</b>\nЗачислено: <b>{payment.amount:.2f} ₽</b>\n"
                        f"Текущий баланс: <b>{user.balance:.2f} ₽</b>")
            return

        if status in {"CANCELED", "CHARGEBACKED", "DISPUTED", "PARTIALLY_REFUNDED"}:
            payment.status = status
            if status == "CANCELED" and order is not None and order.status == OrderStatus.PENDING.value:
                order.status = OrderStatus.CANCELLED.value
            elif status in {"CHARGEBACKED", "DISPUTED", "PARTIALLY_REFUNDED"}:
                log.warning("Platega payment %s changed to %s; order %s needs review", external_id, status, order.id)
            await session.commit()
            return

        payment.status = status[:30]
        await session.commit()


async def fulfill_paid_order(order_id: int, bot, send_telegram_delivery: bool = True):
    """Idempotently claim and fulfil a paid order. A claimed order is never auto-purchased twice."""
    async with SessionLocal() as session:
        order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if not order or order.status in {OrderStatus.COMPLETED.value, OrderStatus.PROCESSING.value, OrderStatus.FAILED.value}:
            return
        if order.status != OrderStatus.PAID.value:
            return
        product = await session.get(Product, order.product_id)
        user = await session.get(User, order.user_id)
        if not product or not user:
            log.error("Paid order %s missing product or user", order_id)
            return
        keys = (await session.scalars(
            select(DigitalKey).where(
                DigitalKey.product_id == product.id, DigitalKey.status == "AVAILABLE"
            ).with_for_update(skip_locked=True).limit(order.quantity or 1)
        )).all()
        if len(keys) >= (order.quantity or 1):
            for key in keys:
                key.status = "SOLD"
                key.order_id = order.id
            order.status = OrderStatus.COMPLETED.value
            user.purchase_count += 1
            await session.commit()
            if send_telegram_delivery:
                await send_order_delivery(bot, order.id)
            await publish_purchase_notice(bot, order.id)
            return

        if keys:
            # Do not partially fulfil a paid order. Keep it for manual reconciliation.
            order.status = OrderStatus.PROCESSING.value
            await session.commit()
            await notify_admins(bot, f"⚠️ Заказ #{order.id}: запрошено {order.quantity} шт., локально найдено {len(keys)}. Требуется проверка остатка.")
            if send_telegram_delivery:
                await bot.send_message(user.telegram_id, f"Оплата заказа #{order.id} подтверждена. Проверяем наличие полного количества товара.")
            return

        if product.supplier_name != "sandromania" or not product.supplier_product_id:
            order.status = OrderStatus.PROCESSING.value
            await session.commit()
            if send_telegram_delivery:
                await bot.send_message(user.telegram_id,
                    f"Оплата заказа #{order.id} подтверждена. Товар временно недоступен, заказ передан на проверку.")
            return

        # Claim before the external call. If the process crashes, reconcile this order manually;
        # never retry supplier purchase blindly with a fresh idempotency key.
        order.status = OrderStatus.PROCESSING.value
        await session.commit()
        supplier_id = int(product.supplier_product_id)
        idem = order.idempotency_key
        product_name = product.name
        telegram_id = user.telegram_id

    try:
        result = await SandromaniaClient().purchase_and_wait(supplier_id, idem, order.quantity or 1)
    except Exception:
        log.exception("Supplier fulfilment failed/uncertain for paid order %s", order_id)
        await notify_admins(bot,
            f"⚠️ Заказ #{order_id} оплачен, но закупка у поставщика не подтверждена "
            f"(ошибка/таймаут/нет баланса у поставщика). Проверьте заказ вручную, "
            f"повторно не покупайте и при необходимости сделайте возврат клиенту.")
        if send_telegram_delivery:
            await bot.send_message(telegram_id,
                f"Оплата заказа #{order_id} подтверждена. Поставка обрабатывается; поддержка проверит результат.")
        return

    async with SessionLocal() as session:
        order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if not order or order.status != OrderStatus.PROCESSING.value:
            return
        order.supplier_order_id = result.get("order_id")
        deliveries = result.get("deliveries") or ([result.get("delivery") or result.get("code")] if (result.get("delivery") or result.get("code")) else [])
        if len(deliveries) >= (order.quantity or 1):
            for delivery in deliveries[:(order.quantity or 1)]:
                session.add(DigitalKey(product_id=order.product_id, order_id=order.id,
                                       code=delivery, status="SOLD"))
            order.status = OrderStatus.COMPLETED.value
            user = await session.get(User, order.user_id)
            if user:
                user.purchase_count += 1
            await session.commit()
            if send_telegram_delivery:
                await send_order_delivery(bot, order_id)
            await publish_purchase_notice(bot, order_id)
            await supplier_balance_watch(bot)
        else:
            await session.commit()
            await notify_admins(bot,
                f"⏳ Заказ #{order_id} оплачен; поставщик принял заказ, но код ещё не выдан. Проверьте статус вручную.")
            if send_telegram_delivery:
                await bot.send_message(telegram_id,
                    f"Оплата заказа #{order_id} подтверждена. Поставщик обрабатывает заказ, код придёт отдельно.")


# ---------------------------------------------------------------------------
# Crypto Pay (Crypto Bot)
# ---------------------------------------------------------------------------

async def notify_admins(bot, text: str):
    """Best-effort alert to every admin; never raises."""
    for admin_id in settings.admins:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            log.warning("Could not notify admin %s", admin_id)


async def process_cryptobot_invoice(invoice: dict, bot) -> str:
    """
    Apply a Crypto Pay invoice state to our payment/order. Safe to call many times
    (webhook, poller and the "check payment" button can all race): the payment and
    order rows are locked and fulfilment is claimed exactly once.
    Returns the resulting payment status.
    """
    invoice_id = str(invoice.get("invoice_id") or "")
    status = str(invoice.get("status") or "").lower()
    if not invoice_id or not status:
        raise ValueError("Invoice is missing invoice_id/status")

    newly_confirmed = False
    telegram_id = None
    order_id = None
    async with SessionLocal() as session:
        payment = await session.scalar(
            select(Payment)
            .where(Payment.external_id == invoice_id, Payment.provider == "cryptobot")
            .with_for_update()
        )
        if not payment:
            raise ValueError("Unknown Crypto Pay invoice")
        if payment.order_id is None:
            return await _process_crypto_topup(session, payment, invoice, status, bot)
        order = await session.scalar(
            select(Order).where(Order.id == payment.order_id).with_for_update()
        )
        if not order:
            raise ValueError("Order for payment was not found")
        order_id = order.id

        if status == "paid":
            # Never trust the status alone: the invoice must be ours and for the exact amount.
            if str(invoice.get("payload") or "") != (payment.payload or ""):
                raise ValueError("Crypto Pay payload mismatch")
            if str(invoice.get("currency_type") or "fiat") == "fiat":
                if str(invoice.get("fiat") or "").upper() != settings.currency.upper():
                    raise ValueError("Crypto Pay currency mismatch")
                try:
                    paid_amount = round(float(invoice.get("amount")), 2)
                except (TypeError, ValueError):
                    raise ValueError("Invalid Crypto Pay amount")
                if paid_amount != round(float(payment.amount), 2):
                    raise ValueError("Crypto Pay amount mismatch")
            if payment.status != "CONFIRMED":
                payment.status = "CONFIRMED"
                payment.confirmed_at = datetime.utcnow()
                newly_confirmed = True
                if order.status == OrderStatus.PENDING.value:
                    order.status = OrderStatus.PAID.value
                user = await session.get(User, payment.user_id)
                telegram_id = user.telegram_id if user else None
            await session.commit()
        elif status == "expired":
            if payment.status == "PENDING":
                payment.status = "EXPIRED"
                if order.status == OrderStatus.PENDING.value:
                    order.status = OrderStatus.CANCELLED.value
            await session.commit()
            return payment.status
        else:
            return payment.status  # "active": still waiting for the buyer

    if newly_confirmed and telegram_id:
        try:
            await bot.send_message(
                telegram_id,
                f"✅ Оплата заказа <b>#{order_id}</b> получена. Готовим товар.",
            )
        except Exception:
            log.warning("Could not notify buyer about order %s", order_id)
    await fulfill_paid_order(order_id, bot)
    return "CONFIRMED"


async def poll_pending_crypto_payments(bot):
    """Check all unfinished Crypto Pay invoices (works without a public webhook URL)."""
    from datetime import timedelta
    from payments.providers.cryptobot import CryptoBotClient

    async with SessionLocal() as session:
        pending = (await session.scalars(
            select(Payment.external_id).where(
                Payment.provider == "cryptobot",
                Payment.status == "PENDING",
                Payment.external_id.is_not(None),
                Payment.created_at > datetime.utcnow() - timedelta(days=3),
            )
        )).all()
        # Orders that were paid but never claimed for fulfilment (e.g. crash between steps).
        stuck_paid = (await session.scalars(
            select(Order.id).where(
                Order.status == OrderStatus.PAID.value,
                Order.created_at < datetime.utcnow() - timedelta(minutes=2),
            )
        )).all()

    client = CryptoBotClient()
    for i in range(0, len(pending), 100):
        chunk = list(pending[i:i + 100])
        for invoice in await client.get_invoices(chunk):
            try:
                await process_cryptobot_invoice(invoice, bot)
            except Exception:
                log.exception("Crypto Pay invoice %s processing failed", invoice.get("invoice_id"))
    for order_id in stuck_paid:
        try:
            await fulfill_paid_order(order_id, bot)
        except Exception:
            log.exception("Recovery fulfilment failed for order %s", order_id)


async def crypto_payment_poller(bot):
    import asyncio
    while True:
        try:
            await poll_pending_crypto_payments(bot)
            if settings.sandromania_enabled:
                await supplier_balance_watch(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Crypto Pay polling cycle failed")
        await asyncio.sleep(max(5.0, settings.crypto_pay_poll_interval))


_last_balance_check = 0.0
_last_balance_alert = 0.0


async def supplier_balance_watch(bot, force: bool = False):
    """Warn admins when the Sandromania balance is low. Rate-limited: checks every 30 min, alerts every 6 h."""
    import time
    global _last_balance_check, _last_balance_alert
    now = time.monotonic()
    if not force and _last_balance_check and now - _last_balance_check < 1800:
        return
    _last_balance_check = now
    try:
        balance = await SandromaniaClient().get_balance_rub()
    except Exception as exc:
        log.warning("Could not read Sandromania balance (%s): %s", type(exc).__name__, exc)
        return
    if balance < settings.supplier_low_balance_rub and (
        not _last_balance_alert or now - _last_balance_alert > 6 * 3600
    ):
        _last_balance_alert = now
        await notify_admins(bot,
            f"💸 Низкий баланс у Sandromania: {balance:.2f} ₽ (порог {settings.supplier_low_balance_rub:.0f} ₽). "
            f"Пополните, иначе оплаченные заказы не смогут выполниться.")


async def _process_crypto_topup(session, payment, invoice: dict, status: str, bot) -> str:
    """Credit the internal balance for a paid Crypto Pay top-up invoice (exactly once)."""
    import re
    if status == "expired":
        if payment.status == "PENDING":
            payment.status = "EXPIRED"
        await session.commit()
        return payment.status
    if status != "paid":
        return payment.status

    if str(invoice.get("payload") or "") != (payment.payload or ""):
        raise ValueError("Crypto Pay payload mismatch")
    match = re.search(r"-usd(\d+)$", payment.payload or "")
    if not match:
        raise ValueError("Top-up payload has no amount")
    if str(invoice.get("currency_type") or "fiat") != "fiat" or str(invoice.get("fiat") or "").upper() != "USD":
        raise ValueError("Crypto Pay currency mismatch")
    try:
        paid_usd = round(float(invoice.get("amount")), 2)
    except (TypeError, ValueError):
        raise ValueError("Invalid Crypto Pay amount")
    if paid_usd != round(float(match.group(1)), 2):
        raise ValueError("Crypto Pay amount mismatch")

    if payment.status == "CONFIRMED":
        return "CONFIRMED"
    user = await session.scalar(select(User).where(User.id == payment.user_id).with_for_update())
    if not user:
        raise ValueError("User for top-up payment was not found")
    payment.status = "CONFIRMED"
    payment.confirmed_at = datetime.utcnow()
    from services.balance_service import add_balance
    await add_balance(session, user, float(payment.amount),
                      f"Пополнение через Crypto Bot #{payment.id}", transaction_type="TOPUP")
    await session.commit()
    try:
        await bot.send_message(user.telegram_id,
            f"✅ <b>Баланс пополнен!</b>\nЗачислено: <b>{payment.amount:.2f} ₽</b>\n"
            f"Текущий баланс: <b>{user.balance:.2f} ₽</b>")
    except Exception:
        log.warning("Could not notify user about top-up %s", payment.id)
    return "CONFIRMED"
