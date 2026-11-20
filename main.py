import asyncio
import logging
from aiohttp import web
from bot.loader import create_bot, create_dispatcher
from config.settings import settings
from database.engine import init_db, close_db
from utils.logger import setup_logging
from payments.webhook import create_payment_app
from bot.commands import register_bot_commands

async def main():
    setup_logging()
    await init_db()
    bot = create_bot()
    dp = create_dispatcher()
    await register_bot_commands(bot, settings.admins)
    runner = None
    try:
        if settings.platega_enabled:
            app = create_payment_app(bot)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, settings.platega_webhook_host, settings.platega_webhook_port)
            await site.start()
            logging.getLogger(__name__).info(
                "Payment webhook listening on %s:%s%s",
                settings.platega_webhook_host, settings.platega_webhook_port,
                settings.platega_webhook_path,
            )
        await dp.start_polling(bot)
    finally:
        if runner:
            await runner.cleanup()
        await bot.session.close()
        await close_db()

if __name__ == "__main__":
    asyncio.run(main())
