from bot.loader import create_bot, create_dispatcher
from config.settings import settings
from database.engine import init_db, close_db
from utils.logger import setup_logging
import asyncio

async def main():
    setup_logging()
    await init_db()
    bot = create_bot()
    dp = create_dispatcher()
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await close_db()

if __name__ == "__main__":
    asyncio.run(main())
