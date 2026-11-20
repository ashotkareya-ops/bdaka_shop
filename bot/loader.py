from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from bot.handlers import setup_routers
from bot.middlewares.database import DatabaseMiddleware
from config.settings import settings

def create_bot():
    return Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

def create_dispatcher():
    dp = Dispatcher()
    dp.update.middleware(DatabaseMiddleware())
    setup_routers(dp)
    return dp
