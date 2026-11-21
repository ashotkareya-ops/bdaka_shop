from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.methods import SendMessage, SendPhoto, SendDocument, SendVideo, SendAnimation, SendAudio, SendVoice
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.handlers import setup_routers
from bot.middlewares.database import DatabaseMiddleware
from config.settings import settings

async def _add_default_close_button(make_request, bot, method):
    """
    Add a compact Close button to outgoing private-chat messages that have
    no inline keyboard of their own. Channel/group posts are left untouched.
    """
    supported = (SendMessage, SendPhoto, SendDocument, SendVideo, SendAnimation, SendAudio, SendVoice)
    chat_id = getattr(method, "chat_id", None)
    try:
        is_private_chat = int(chat_id) > 0
    except (TypeError, ValueError):
        is_private_chat = False
    if (
        isinstance(method, supported)
        and is_private_chat
        and getattr(method, "reply_markup", None) is None
    ):
        method.reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="✖️ Закрыть", callback_data="ui:close")
            ]]
        )
    return await make_request(bot, method)


def create_bot():
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    bot.session.middleware(_add_default_close_button)
    return bot

def create_dispatcher():
    dp = Dispatcher()
    dp.update.middleware(DatabaseMiddleware())
    setup_routers(dp)
    return dp
