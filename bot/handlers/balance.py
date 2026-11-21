import logging
import math

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, PreCheckoutQuery, LabeledPrice
)
from aiogram.dispatcher.event.bases import SkipHandler
from sqlalchemy import select

from database.models.user import User
from database.models.payment import Payment
from services.balance_service import add_balance
from bot.keyboards.payments import topup_amount_keyboard, topup_method_keyboard
from bot.keyboards.profile import profile_keyboard
from bot.utils.section_media import send_section

router = Router()
log = logging.getLogger(__name__)

_PENDING_TOPUP: set[int] = set()
MIN_TOPUP_AMOUNT = 10
MAX_TOPUP_AMOUNT = 100000
RUB_PER_STAR = 0.95


def _stars_for_rubles(amount_rub: int) -> int:
    """Round up because Telegram Stars are charged as whole units."""
    return math.ceil(amount_rub / RUB_PER_STAR)


async def _create_stars_invoice(message: Message, session, telegram_id: int, amount_rub: int):
    user = await session.scalar(
        select(User).where(User.telegram_id == telegram_id).with_for_update()
    )
    if not user:
        await message.answer("Сначала нажмите /start.")
        return

    stars = _stars_for_rubles(amount_rub)
    payment = Payment(
        user_id=user.id,
        order_id=None,
        amount=float(amount_rub),
        provider="telegram_stars",
        status="PENDING",
        payload="",
    )
    session.add(payment)
    await session.flush()
    payment.payload = f"stars-topup-{payment.id}"
    await session.commit()

    try:
        await message.answer_invoice(
            title="Пополнение баланса BDAKA SHOP",
            description=f"Зачисление {amount_rub} ₽ на внутренний баланс магазина.",
            payload=payment.payload,
            currency="XTR",
            prices=[LabeledPrice(label=f"Пополнение на {amount_rub} ₽", amount=stars)],
        )
    except Exception:
        log.exception("Could not send Telegram Stars invoice payment_id=%s", payment.id)
        payment.status = "FAILED"
        await session.commit()
        await message.answer("Не удалось создать счёт в Telegram Stars. Попробуйте позже.")
        return

    await message.answer(
        f"⭐ Счёт создан: <b>{stars} Stars</b>\n"
        f"На баланс будет зачислено: <b>{amount_rub} ₽</b>\n"
        f"Курс расчёта: 1 Star = {RUB_PER_STAR:.2f} ₽."
    )


async def _show_topup_methods(target):
    await send_section(
        target,
        "wallet.png",
        "💳 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n\n"
        "Выберите способ оплаты. Для цифровых товаров внутри Telegram "
        "доступна оплата через Telegram Stars.",
        reply_markup=topup_method_keyboard(),
    )


@router.message(Command("balance"))
async def balance_help(message: Message):
    _PENDING_TOPUP.discard(message.from_user.id)
    await _show_topup_methods(message)


@router.callback_query(F.data == "balance:topup")
async def show_topup_methods(callback: CallbackQuery):
    _PENDING_TOPUP.discard(callback.from_user.id)
    await _show_topup_methods(callback.message)
    await callback.answer()


@router.callback_query(F.data == "balance:method:stars")
async def choose_stars_method(callback: CallbackQuery):
    await send_section(
        callback.message,
        "wallet.png",
        "⭐ <b>TELEGRAM STARS</b>\n\n"
        f"Курс: 1 Star = {RUB_PER_STAR:.2f} ₽.\n"
        "Выберите сумму пополнения или введите свою.",
        reply_markup=topup_amount_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.in_({"balance:method:platega", "balance:method:crypto_pro"}))
async def unavailable_topup_method(callback: CallbackQuery):
    method_name = "Platega" if callback.data.endswith("platega") else "Crypto Pro"
    await callback.answer(
        f"{method_name} пока недоступен. Используйте Telegram Stars.",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("balance:amount:"))
async def choose_fixed_amount(callback: CallbackQuery, session):
    try:
        amount = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректная сумма", show_alert=True)
        return
    if not MIN_TOPUP_AMOUNT <= amount <= MAX_TOPUP_AMOUNT:
        await callback.answer("Недопустимая сумма", show_alert=True)
        return
    await _create_stars_invoice(callback.message, session, callback.from_user.id, amount)
    await callback.answer()


@router.callback_query(F.data == "balance:enter_amount")
async def request_topup_amount(callback: CallbackQuery):
    _PENDING_TOPUP.add(callback.from_user.id)
    await callback.message.answer(
        f"✍️ <b>Введите сумму пополнения</b>\n\n"
        f"Целое число от {MIN_TOPUP_AMOUNT} до {MAX_TOPUP_AMOUNT} ₽.\n"
        "Например: <code>100</code>.",
        reply_markup=_cancel_input_keyboard(),
    )
    await callback.answer()


def _cancel_input_keyboard():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✖️ Отмена", callback_data="balance:cancel_amount")
    return kb.as_markup()


@router.callback_query(F.data == "balance:cancel_amount")
async def cancel_topup_amount(callback: CallbackQuery):
    _PENDING_TOPUP.discard(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Ввод суммы отменён.",
        reply_markup=topup_amount_keyboard(),
    )
    await callback.answer("Отменено")


@router.message(F.text)
async def receive_topup_amount(message: Message, session):
    telegram_id = message.from_user.id if message.from_user else None
    if telegram_id is None or telegram_id not in _PENDING_TOPUP:
        raise SkipHandler

    raw = (message.text or "").strip().replace(" ", "")
    if not raw.isdigit():
        await message.answer("Введите целое число в рублях, например 100.")
        return

    amount = int(raw)
    if not MIN_TOPUP_AMOUNT <= amount <= MAX_TOPUP_AMOUNT:
        await message.answer(
            f"Минимальная сумма — {MIN_TOPUP_AMOUNT} ₽, максимальная — "
            f"{MAX_TOPUP_AMOUNT} ₽. Введите другую сумму."
        )
        return

    _PENDING_TOPUP.discard(telegram_id)
    await _create_stars_invoice(message, session, telegram_id, amount)


@router.pre_checkout_query()
async def confirm_stars_pre_checkout(query: PreCheckoutQuery, session):
    payment = await session.scalar(
        select(Payment).where(Payment.payload == query.invoice_payload).with_for_update()
    )
    if (
        not payment
        or payment.provider != "telegram_stars"
        or payment.order_id is not None
        or payment.status != "PENDING"
        or query.currency != "XTR"
        or query.total_amount != _stars_for_rubles(int(payment.amount))
    ):
        await query.answer(ok=False, error_message="Счёт недействителен. Создайте новый.")
        return
    user = await session.get(User, payment.user_id)
    if not user or user.telegram_id != query.from_user.id:
        await query.answer(ok=False, error_message="Этот счёт создан для другого пользователя.")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def receive_successful_stars_payment(message: Message, session):
    successful = message.successful_payment
    payment = await session.scalar(
        select(Payment)
        .where(Payment.payload == successful.invoice_payload)
        .with_for_update()
    )
    if (
        not payment
        or payment.provider != "telegram_stars"
        or payment.order_id is not None
        or successful.currency != "XTR"
        or successful.total_amount != _stars_for_rubles(int(payment.amount))
    ):
        log.error("Unmatched or invalid Telegram Stars payment from user=%s", message.from_user.id)
        await message.answer("Платёж получен, но не удалось автоматически сопоставить счёт. Обратитесь в поддержку.")
        return

    if payment.status == "CONFIRMED":
        await message.answer("Этот платёж уже был зачислен ранее.")
        return

    user = await session.scalar(
        select(User).where(User.id == payment.user_id).with_for_update()
    )
    if not user or user.telegram_id != message.from_user.id:
        log.error("Telegram Stars payer mismatch for payment_id=%s", payment.id)
        await message.answer("Не удалось подтвердить владельца счёта. Обратитесь в поддержку.")
        return

    charge_id = successful.telegram_payment_charge_id
    payment.status = "CONFIRMED"
    payment.external_id = charge_id
    payment.confirmed_at = __import__("datetime").datetime.utcnow()
    await add_balance(
        session,
        user,
        float(payment.amount),
        f"Пополнение через Telegram Stars #{payment.id}",
        transaction_type="TOPUP",
    )
    await session.commit()
    await message.answer(
        f"✅ <b>Баланс успешно пополнен!</b>\n"
        f"Зачислено: <b>{payment.amount:.2f} ₽</b>\n"
        f"Текущий баланс: <b>{user.balance:.2f} ₽</b>"
    )


@router.callback_query(F.data == "balance:profile")
async def back_to_profile(callback: CallbackQuery, session):
    _PENDING_TOPUP.discard(callback.from_user.id)
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    if user:
        await send_section(
            callback.message,
            "profile.png",
            f"👤 <b>Профиль</b>\n\nID: <code>{user.telegram_id}</code>\n"
            f"Баланс: <b>{user.balance:.2f} ₽</b>\nПокупок: {user.purchase_count}",
            reply_markup=profile_keyboard(),
        )
    await callback.answer()
