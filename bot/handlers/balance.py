import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from database.models.user import User
from database.models.payment import Payment
from config.settings import settings
from payments.providers.platega import PlategaClient
from bot.keyboards.payments import topup_amount_keyboard, topup_invoice_keyboard
from bot.keyboards.profile import profile_keyboard
from bot.utils.section_media import send_section

router = Router()
log = logging.getLogger(__name__)

@router.message(Command("balance"))
async def balance_help(message: Message):
    await send_section(message, "wallet.png", "💳 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n\nВыберите сумму пополнения:", reply_markup=topup_amount_keyboard())

@router.callback_query(F.data == "balance:topup")
async def show_topup_amounts(callback: CallbackQuery):
    await send_section(callback.message, "wallet.png", "💳 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n\nВыберите сумму в рублях:", reply_markup=topup_amount_keyboard())
    await callback.answer()

@router.callback_query(F.data == "balance:profile")
async def back_to_profile(callback: CallbackQuery, session):
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    if user:
        await send_section(
            callback.message, "profile.png",
            f"👤 <b>Профиль</b>\n\nID: <code>{user.telegram_id}</code>\n"
            f"Баланс: <b>{user.balance:.2f} ₽</b>\nПокупок: {user.purchase_count}",
            reply_markup=profile_keyboard()
        )
    await callback.answer()

@router.callback_query(F.data.startswith("balance:amount:"))
async def create_topup(callback: CallbackQuery, session):
    try:
        amount = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректная сумма", show_alert=True)
        return
    if amount not in {100, 300, 500, 1000}:
        await callback.answer("Недопустимая сумма", show_alert=True)
        return
    if not settings.platega_enabled:
        await callback.answer("Пополнение через Platega пока не настроено", show_alert=True)
        return
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id).with_for_update())
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    payment = Payment(
        user_id=user.id, order_id=None, amount=float(amount), provider="platega",
        status="CREATING", payload="",
    )
    session.add(payment)
    await session.flush()
    payment.payload = f"topup-{payment.id}"
    await session.commit()
    try:
        invoice = await PlategaClient().create_invoice(
            amount=amount, currency=settings.currency, payload=payment.payload,
            description=f"BDAKA SHOP — пополнение баланса #{payment.id}",
        )
        payment.external_id = invoice["external_id"]
        payment.payment_url = invoice["url"]
        payment.status = "PENDING"
        await session.commit()
    except Exception:
        log.exception("Could not create Platega top-up invoice payment_id=%s", payment.id)
        payment.status = "FAILED"
        await session.commit()
        await callback.message.answer("Не удалось создать платёж. Баланс не изменён. Попробуйте позже.")
        await callback.answer("Ошибка создания платежа", show_alert=True)
        return
    await callback.message.answer(
        f"🧾 <b>Пополнение #{payment.id}</b>\nСумма: <b>{amount} ₽</b>\n\n"
        "Перейдите по ссылке для оплаты. Баланс будет зачислен после подтверждения платежа.",
        reply_markup=topup_invoice_keyboard(invoice["url"], payment.id)
    )
    await callback.answer("Счёт создан")


@router.callback_query(F.data.startswith("payment:check_topup:"))
async def check_topup_payment(callback: CallbackQuery, session):
    try:
        payment_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный платёж", show_alert=True)
        return
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    payment = await session.get(Payment, payment_id)
    if not user or not payment or payment.user_id != user.id or payment.provider != "platega" or payment.order_id is not None:
        await callback.answer("Платёж не найден", show_alert=True)
        return
    if payment.status == "CONFIRMED":
        await callback.answer("Платёж уже подтверждён", show_alert=True)
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
                "status": status,
                "payload": state.get("payload") or payment.payload,
            }, callback.bot)
            await callback.answer("Баланс пополнен", show_alert=True)
        else:
            await callback.answer(f"Статус платежа: {status or 'неизвестен'}", show_alert=True)
    except Exception:
        log.exception("Top-up payment status check failed: payment_id=%s", payment_id)
        await callback.answer("Не удалось проверить оплату. Попробуйте позже.", show_alert=True)
