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
from bot.keyboards.payments import (
    topup_amount_keyboard, topup_method_keyboard,
    topup_crypto_amount_keyboard, topup_invoice_keyboard,
)
from config.settings import settings
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


# ---------------------------------------------------------------------------
# Crypto Bot top-up (amount in USD, paid in USDT; credited to the ₽ balance at the current rate)
# ---------------------------------------------------------------------------
CRYPTO_MIN_USD = 1
CRYPTO_MAX_USD = 1000
_PENDING_CRYPTO: dict[int, float] = {}  # telegram_id -> expiry (monotonic); self-expiring so it never gets stuck


def _crypto_pending(telegram_id: int) -> bool:
    import time
    expiry = _PENDING_CRYPTO.get(telegram_id)
    if expiry is None:
        return False
    if expiry < time.monotonic():
        _PENDING_CRYPTO.pop(telegram_id, None)
        return False
    return True


async def _create_crypto_topup(message: Message, session, telegram_id: int, usd: int):
    from payments.providers.cryptobot import CryptoBotClient
    from services.exchange_rate import get_usd_rub_rate, usd_to_rub

    user = await session.scalar(
        select(User).where(User.telegram_id == telegram_id).with_for_update()
    )
    if not user:
        await message.answer("Сначала нажмите /start.")
        return
    try:
        # Use the admin-managed USD/RUB rate stored in PostgreSQL.
        # Internal balance is always denominated in RUB.
        rate = await get_usd_rub_rate(session)
        rub = float(usd_to_rub(usd, rate))
        if rub <= 0:
            raise ValueError("bad rate")
    except Exception:
        log.exception("Could not get USD/RUB rate for crypto top-up")
        await session.rollback()
        await message.answer("Не удалось получить курс. Попробуйте позже.")
        return

    payment = Payment(
        user_id=user.id, order_id=None, amount=rub,
        provider="cryptobot", status="CREATING", payload="",
    )
    session.add(payment)
    await session.flush()
    payment.payload = f"crypto-topup-{payment.id}-usd{usd}"
    await session.commit()

    try:
        invoice = await CryptoBotClient().create_invoice(
            usd, fiat="USD", accepted_assets=settings.crypto_accepted_assets,
            description=f"Пополнение баланса BDAKA SHOP на {usd} $",
            payload=payment.payload, expires_in=settings.crypto_pay_expires_in,
        )
        pay_url = invoice.get("bot_invoice_url") or invoice.get("pay_url")
        if not invoice.get("invoice_id") or not pay_url:
            raise ValueError("Unexpected invoice schema")
        payment.external_id = str(invoice["invoice_id"])
        payment.payment_url = str(pay_url)
        payment.status = "PENDING"
        await session.commit()
    except Exception:
        log.exception("Could not create Crypto Pay top-up invoice payment_id=%s", payment.id)
        payment.status = "FAILED"
        await session.commit()
        await message.answer("Не удалось создать счёт. Деньги не списаны. Попробуйте позже.")
        return

    await message.answer(
        f"🪙 <b>Счёт на пополнение создан</b>\n"
        f"К оплате: <b>{usd} $</b> (1 USDT = 1 $)\n"
        f"Будет зачислено: <b>{rub:.2f} ₽</b> (курс {rate:.2f} ₽ за 1 $)\n"
        "Баланс пополнится автоматически после оплаты.",
        reply_markup=topup_invoice_keyboard(str(pay_url), payment.id),
    )


@router.callback_query(F.data == "balance:method:crypto")
async def choose_crypto_method(callback: CallbackQuery, session):
    if not settings.crypto_pay_enabled:
        await callback.answer("Crypto Bot пока недоступен", show_alert=True)
        return
    _PENDING_TOPUP.discard(callback.from_user.id)
    _PENDING_CRYPTO.pop(callback.from_user.id, None)
    from services.exchange_rate import get_usd_rub_rate
    rate = await get_usd_rub_rate(session)
    await send_section(
        callback.message,
        "wallet.png",
        "🪙 <b>CRYPTO BOT (USDT)</b>\\n\\n"
        "Оплата принимается в USD/USDT. Баланс магазина всегда ведётся в рублях.\\n"
        f"Текущий курс магазина: <b>1 USD = {rate:.4f} ₽</b>.\\n"
        f"Например, 5 USD = <b>{5 * rate:.2f} ₽</b> на баланс.\\n\\n"
        "Выберите сумму пополнения или введите свою.",
        reply_markup=topup_crypto_amount_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("balance:cryptousd:"))
async def choose_crypto_amount(callback: CallbackQuery, session):
    try:
        usd = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректная сумма", show_alert=True)
        return
    if not CRYPTO_MIN_USD <= usd <= CRYPTO_MAX_USD or not settings.crypto_pay_enabled:
        await callback.answer("Недопустимая сумма", show_alert=True)
        return
    await _create_crypto_topup(callback.message, session, callback.from_user.id, usd)
    await callback.answer()


@router.callback_query(F.data == "balance:cryptoenter")
async def request_crypto_amount(callback: CallbackQuery):
    import time
    _PENDING_TOPUP.discard(callback.from_user.id)
    _PENDING_CRYPTO[callback.from_user.id] = time.monotonic() + 120
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✖️ Отмена", callback_data="balance:cryptocancel")
    await callback.message.answer(
        f"✍️ <b>Введите сумму в долларах</b>\n\n"
        f"Целое число от {CRYPTO_MIN_USD} до {CRYPTO_MAX_USD} $. Например: <code>5</code>.",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "balance:cryptocancel")
async def cancel_crypto_amount(callback: CallbackQuery):
    _PENDING_CRYPTO.pop(callback.from_user.id, None)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Ввод суммы отменён.", reply_markup=topup_crypto_amount_keyboard())
    await callback.answer("Отменено")


@router.message(F.text)
async def receive_crypto_amount(message: Message, session):
    telegram_id = message.from_user.id if message.from_user else None
    if telegram_id is None or not _crypto_pending(telegram_id):
        raise SkipHandler
    raw = (message.text or "").strip().replace(" ", "").replace("$", "")
    if not raw.isdigit():
        await message.answer("Введите целое число в долларах, например 5.")
        return
    usd = int(raw)
    if not CRYPTO_MIN_USD <= usd <= CRYPTO_MAX_USD:
        await message.answer(f"Минимум {CRYPTO_MIN_USD} $, максимум {CRYPTO_MAX_USD} $. Введите другую сумму.")
        return
    _PENDING_CRYPTO.pop(telegram_id, None)
    await _create_crypto_topup(message, session, telegram_id, usd)


@router.callback_query(F.data.startswith("payment:check_topup:"))
async def check_crypto_topup(callback: CallbackQuery, session):
    try:
        payment_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный платёж", show_alert=True)
        return
    payment = await session.scalar(
        select(Payment).join(User, Payment.user_id == User.id).where(
            Payment.id == payment_id,
            User.telegram_id == callback.from_user.id,
            Payment.provider == "cryptobot",
            Payment.order_id.is_(None),
        )
    )
    if not payment:
        await callback.answer("Платёж не найден", show_alert=True)
        return
    if payment.status == "CONFIRMED":
        await callback.answer("Баланс уже пополнен.", show_alert=True)
        return
    if not payment.external_id:
        await callback.answer("Счёт ещё создаётся", show_alert=True)
        return
    try:
        from payments.providers.cryptobot import CryptoBotClient
        from services.payment_service import process_cryptobot_invoice
        invoice = await CryptoBotClient().get_invoice(payment.external_id)
        state = str((invoice or {}).get("status") or "").lower()
        if state in {"paid", "expired"}:
            await session.rollback()
            await process_cryptobot_invoice(invoice, callback.bot)
            await callback.answer(
                "Оплата подтверждена, баланс пополнен." if state == "paid" else "Счёт истёк. Создайте новый.",
                show_alert=True,
            )
        else:
            await callback.answer("Оплата пока не поступила. Попробуйте через минуту.", show_alert=True)
    except Exception:
        log.exception("Crypto top-up status check failed: payment_id=%s", payment_id)
        await callback.answer("Не удалось проверить статус. Попробуйте позже.", show_alert=True)
