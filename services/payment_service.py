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


async def fulfill_paid_order(order_id: int, bot):
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
        key = await session.scalar(
            select(DigitalKey).where(
                DigitalKey.product_id == product.id, DigitalKey.status == "AVAILABLE"
            ).with_for_update(skip_locked=True).limit(1)
        )
        if key:
            key.status = "SOLD"
            key.order_id = order.id
            order.status = OrderStatus.COMPLETED.value
            user.purchase_count += 1
            await session.commit()
            await send_order_delivery(bot, order.id)
            await publish_purchase_notice(bot, order.id)
            return

        if product.supplier_name != "sandromania" or not product.supplier_product_id:
            order.status = OrderStatus.PROCESSING.value
            await session.commit()
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
        result = await SandromaniaClient().purchase_and_wait(supplier_id, idem)
    except Exception:
        log.exception("Supplier fulfilment failed/uncertain for paid order %s", order_id)
        await bot.send_message(telegram_id,
            f"Оплата заказа #{order_id} подтверждена. Поставка обрабатывается; поддержка проверит результат.")
        return

    async with SessionLocal() as session:
        order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if not order or order.status != OrderStatus.PROCESSING.value:
            return
        order.supplier_order_id = result.get("order_id")
        delivery = result.get("delivery") or result.get("code")
        if delivery:
            session.add(DigitalKey(product_id=order.product_id, order_id=order.id,
                                   code=delivery, status="SOLD"))
            order.status = OrderStatus.COMPLETED.value
            user = await session.get(User, order.user_id)
            if user:
                user.purchase_count += 1
            await session.commit()
            await send_order_delivery(bot, order_id)
            await publish_purchase_notice(bot, order_id)
        else:
            await session.commit()
            await bot.send_message(telegram_id,
                f"Оплата заказа #{order_id} подтверждена. Поставщик обрабатывает заказ, код придёт отдельно.")
