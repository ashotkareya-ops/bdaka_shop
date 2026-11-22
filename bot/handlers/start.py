import logging
from pathlib import Path

from aiogram import Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from database.models.user import User
from bot.utils.section_media import send_section
from bot.keyboards.main import main_menu

router = Router()
log = logging.getLogger(__name__)

REQUIRED_CHANNEL = "@bdaka_store"
CHANNEL_URL = "https://t.me/bdaka_store"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUBSCRIPTION_BANNER = PROJECT_ROOT / "assets" / "banners" / "subscription.png"


def subscription_keyboard(start_payload: str | None = None):
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Подписаться на канал", url=CHANNEL_URL)
    callback_data = "subscription:check"
    if start_payload and start_payload.startswith("ref_"):
        callback_data = f"subscription:check:{start_payload}"
    kb.button(text="🔄 Проверить подписку", callback_data=callback_data)
    kb.adjust(1)
    return kb.as_markup()


async def check_subscription(bot, user_id: int) -> tuple[bool, bool]:
    """Return (is_subscribed, api_error)."""
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
    except TelegramAPIError:
        log.exception("Could not check subscription for user_id=%s channel=%s", user_id, REQUIRED_CHANNEL)
        return False, True

    if member.status in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    }:
        return True, False

    # Restricted members can still belong to a channel/supergroup.
    return bool(getattr(member, "is_member", False)), False


async def show_subscription_required(target, start_payload: str | None = None, api_error: bool = False):
    if api_error:
        text = (
            "⚠️ Сейчас не удалось проверить подписку.\n\n"
            "Попробуйте ещё раз чуть позже. Если ошибка повторяется, сообщите администратору магазина."
        )
    else:
        text = (
            "👋 Привет! Добро пожаловать в <b>BDAKA SHOP</b>!\n\n"
            "Чтобы начать пользоваться ботом, подпишитесь, пожалуйста, на наш "
            "<a href=\"https://t.me/bdaka_store\">канал новостей</a>.\n\n"
            "Там мы первыми публикуем информацию о скидках, акциях, новых товарах "
            "и пополнениях ассортимента. Так вы не пропустите выгодные предложения!\n\n"
            "После подписки нажмите кнопку «Проверить подписку» ниже."
        )
    markup = subscription_keyboard(start_payload)
    if SUBSCRIPTION_BANNER.is_file():
        await target.answer_photo(
            photo=FSInputFile(SUBSCRIPTION_BANNER),
            caption=text,
            reply_markup=markup,
        )
    else:
        # Fallback keeps the subscription gate usable if the banner is missing.
        await target.answer(text, reply_markup=markup, disable_web_page_preview=True)


async def ensure_user(session, telegram_user, start_payload: str | None = None):
    user = await session.scalar(select(User).where(User.telegram_id == telegram_user.id))
    if not user:
        referrer_id = None
        if start_payload and start_payload.startswith("ref_"):
            try:
                candidate = int(start_payload[4:])
                if candidate != telegram_user.id:
                    referrer = await session.scalar(select(User).where(User.telegram_id == candidate))
                    if referrer:
                        referrer_id = referrer.id
            except ValueError:
                pass
        user = User(
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            full_name=telegram_user.full_name,
            balance=0,
            referrer_id=referrer_id,
        )
        session.add(user)
        await session.commit()
    return user


async def show_main_menu(target, user_name: str = "покупатель"):
    text = (
        f"👋 Добро пожаловать в <b>BDAKA SHOP</b>, {user_name}!\n\n"
        "<i>Выберите нужный раздел в меню ниже</i>"
    )
    await send_section(
        target, "home.png", text,
        reply_markup=main_menu(),
    )


@router.message(CommandStart())
async def start(message: Message, session):
    parts = (message.text or "").split(maxsplit=1)
    start_payload = parts[1].strip() if len(parts) == 2 else None

    is_subscribed, api_error = await check_subscription(message.bot, message.from_user.id)
    if not is_subscribed:
        await show_subscription_required(message, start_payload, api_error)
        return

    await ensure_user(session, message.from_user, start_payload)
    await show_main_menu(message, message.from_user.first_name)


@router.callback_query(lambda c: c.data and c.data.startswith("subscription:check"))
async def subscription_check(callback: CallbackQuery, session):
    parts = (callback.data or "").split(":", maxsplit=2)
    start_payload = parts[2] if len(parts) == 3 else None

    is_subscribed, api_error = await check_subscription(callback.bot, callback.from_user.id)
    if not is_subscribed:
        if api_error:
            await callback.answer("Не удалось проверить подписку. Попробуйте ещё раз позже.", show_alert=True)
        else:
            await callback.answer("Подписка пока не найдена. Подпишитесь на канал и нажмите кнопку ещё раз.", show_alert=True)
        return

    await ensure_user(session, callback.from_user, start_payload)
    await callback.answer("Подписка подтверждена!")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await show_main_menu(callback.message, callback.from_user.first_name)


@router.message(Command("help"))
async def buyer_help(message: Message):
    try:
        await message.delete()
    except Exception:
        pass
    await message.answer(
        "<b>Команды покупателя</b>\n"
        "/start — главное меню\n"
        "/catalog — каталог товаров\n"
        "/profile — профиль и баланс\n"
        "/balance — пополнение баланса\n"
        "/purchases — мои покупки\n"
        "/transactions — история операций\n"
        "/links — полезные ссылки"
    )


@router.callback_query(lambda c: c.data == "menu:home")
async def menu_home(callback: CallbackQuery):
    await show_main_menu(callback.message, callback.from_user.first_name)
    await callback.answer()
