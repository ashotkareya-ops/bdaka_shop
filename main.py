import asyncio
import logging
from pathlib import Path
from filelock import FileLock, Timeout
from aiohttp import web
from bot.loader import create_bot, create_dispatcher
from config.settings import settings
from database.engine import init_db, close_db
from utils.logger import setup_logging
from payments.webhook import create_payment_app
from bot.commands import register_bot_commands

async def main():
    setup_logging()
    # Prevent two local instances from polling Telegram with the same bot token.
    lock_path = Path(__file__).resolve().parent / ".bot_polling.lock"
    polling_lock = FileLock(str(lock_path))
    try:
        polling_lock.acquire(timeout=0)
    except Timeout:
        logging.getLogger(__name__).error(
            "Another BDAKA SHOP instance is already running; refusing to start polling."
        )
        return
    await init_db()
    bot = create_bot()
    dp = create_dispatcher()
    await register_bot_commands(bot, settings.admins)
    runner = None
    poller = None
    supplier_sync_task = None
    partner_worker_task = None
    try:
        if settings.sandromania_enabled:
            from services.supplier_price_scheduler import supplier_price_sync_loop
            supplier_sync_task = asyncio.create_task(supplier_price_sync_loop())
            logging.getLogger(__name__).info(
                "Sandromania retail price sync started (every 4 hours)"
            )
        # Process orders created through BDAKA STORE API in the same fulfilment flow.
        from services.partner_order_worker import partner_order_worker
        partner_worker_task = asyncio.create_task(partner_order_worker(bot))
        logging.getLogger(__name__).info("Partner API order worker started")
        if settings.crypto_pay_enabled:
            from services.payment_service import crypto_payment_poller
            poller = asyncio.create_task(crypto_payment_poller(bot))
            logging.getLogger(__name__).info("Crypto Pay invoice poller started")
        if settings.platega_enabled or settings.webhook_server_enabled:
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
        if partner_worker_task:
            partner_worker_task.cancel()
            try:
                await partner_worker_task
            except asyncio.CancelledError:
                pass
        if poller:
            poller.cancel()
        if supplier_sync_task:
            supplier_sync_task.cancel()
            try:
                await supplier_sync_task
            except asyncio.CancelledError:
                pass
        if runner:
            await runner.cleanup()
        await bot.session.close()
        await close_db()
        polling_lock.release()

if __name__ == "__main__":
    asyncio.run(main())
