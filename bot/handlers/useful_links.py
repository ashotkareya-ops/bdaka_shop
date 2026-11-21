from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.settings import settings
from bot.utils.section_media import send_section

router = Router()


def links_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🛡 Гарантии", callback_data="links:guarantees")
    kb.button(text="🎧 Поддержка", callback_data="links:support")
    kb.button(text="⭐ Отзывы", callback_data="links:reviews")
    kb.button(text="❗ Правила", callback_data="links:rules")
    kb.button(text="📢 Новости", callback_data="links:channel")
    kb.button(text="💬 Чат магазина", url=settings.shop_chat_url)
    kb.button(text="🏠 Главное меню", callback_data="menu:home")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def back_keyboard(*, external_url: str | None = None, external_label: str = "Открыть"):
    kb = InlineKeyboardBuilder()
    if external_url:
        kb.button(text=external_label, url=external_url)
    else:
        kb.button(text=external_label, callback_data="links:channel_missing")
    kb.button(text="↩️ Назад к полезным ссылкам", callback_data="links:home")
    kb.button(text="🏠 Главное меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


async def show_links(target):
    await send_section(
        target,
        "links.png",
        "🔗 <b>ПОЛЕЗНЫЕ ССЫЛКИ</b>\n\n"
        "Гарантии, поддержка, отзывы, правила и канал магазина.",
        reply_markup=links_keyboard(),
    )


async def show_guarantees(target):
    text = (
        "🛡 <b>ГАРАНТИИ BDAKA SHOP</b>\n\n"
        "• Код выдаётся только из доступного остатка.\n"
        "• Если код не сработал, напишите в поддержку и укажите номер заказа.\n"
        "• При подтверждённой проблеме рассмотрим замену.\n\n"
        "Мы работаем с цифровыми товарами, которые магазин имеет право продавать."
    )
    await send_section(target, "rules.png", text, reply_markup=back_keyboard(
        external_url=settings.shop_support_url, external_label="🎧 Связаться с поддержкой"
    ))


async def show_support(target):
    text = (
        "🎧 <b>ПОДДЕРЖКА</b>\n\n"
        "Если возник вопрос по заказу, напишите в поддержку.\n"
        "Сразу укажите номер заказа и кратко опишите проблему."
    )
    await send_section(target, "support.png", text, reply_markup=back_keyboard(
        external_url=settings.shop_support_url, external_label="🎧 Написать в поддержку"
    ))


async def show_reviews(target):
    text = (
        "⭐ <b>ОТЗЫВЫ И ПОКУПКИ</b>\n\n"
        "Отзывы покупателей и журнал событий магазина публикуются в отдельном Telegram-канале."
    )
    await send_section(target, "reviews.png", text, reply_markup=back_keyboard(
        external_url=settings.shop_reviews_url,
        external_label="⭐ Открыть отзывы",
    ))


async def show_rules(target):
    text = (
        "❗ <b>ПРАВИЛА ПОКУПКИ</b>\n\n"
        "1. Выберите товар в каталоге.\n"
        "2. Оплатите заказ доступным способом.\n"
        "3. После подтверждения оплаты бот выдаст товар автоматически, если он доступен.\n"
        "4. Если возникла проблема, напишите в поддержку и укажите номер заказа.\n\n"
        "Замена рассматривается при подтверждённой проблеме с выданным товаром."
    )
    await send_section(target, "rules.png", text, reply_markup=back_keyboard(
        external_url=settings.shop_support_url, external_label="🎧 Вопрос по правилам"
    ))


async def show_channel(target):
    text = (
        "📢 <b>КАНАЛ МАГАЗИНА</b>\n\n"
        "В канале публикуются новости магазина, наличие товаров, обновления и акции."
    )
    await send_section(target, "links.png", text, reply_markup=back_keyboard(
        external_url=settings.shop_news_url,
        external_label="📢 Открыть новости магазина",
    ))


@router.message(Command("links"))
async def useful_links(message: Message):
    await show_links(message)


@router.callback_query(F.data == "menu:links")
async def useful_links_from_home(callback: CallbackQuery):
    await show_links(callback.message)
    await callback.answer()


@router.callback_query(F.data == "links:home")
async def links_home(callback: CallbackQuery):
    await show_links(callback.message)
    await callback.answer()


@router.callback_query(F.data == "links:guarantees")
async def links_guarantees(callback: CallbackQuery):
    await show_guarantees(callback.message)
    await callback.answer()


@router.callback_query(F.data == "links:support")
async def links_support(callback: CallbackQuery):
    await show_support(callback.message)
    await callback.answer()


@router.callback_query(F.data == "links:reviews")
async def links_reviews(callback: CallbackQuery):
    await show_reviews(callback.message)
    await callback.answer()


@router.callback_query(F.data == "links:rules")
async def links_rules(callback: CallbackQuery):
    await show_rules(callback.message)
    await callback.answer()


@router.callback_query(F.data == "links:channel")
async def links_channel(callback: CallbackQuery):
    await show_channel(callback.message)
    await callback.answer()


@router.callback_query(F.data == "links:channel_missing")
async def links_channel_missing(callback: CallbackQuery):
    await callback.answer(
        "Ссылка на канал ещё не добавлена.",
        show_alert=True,
    )
