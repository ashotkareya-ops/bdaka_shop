import logging
from aiohttp import web
from config.settings import settings
from services.payment_service import (
    verify_callback_headers, process_platega_callback, process_cryptobot_invoice,
)
from payments.providers.cryptobot import verify_webhook_signature

log = logging.getLogger(__name__)


def create_payment_app(bot):
    app = web.Application(client_max_size=64 * 1024)

    async def platega_webhook(request: web.Request):
        if not verify_callback_headers(request.headers):
            raise web.HTTPUnauthorized(text="Unauthorized")
        try:
            data = await request.json()
            await process_platega_callback(data, bot)
        except ValueError as exc:
            log.warning("Rejected Platega callback: %s", exc)
            raise web.HTTPBadRequest(text="Invalid callback")
        except Exception:
            log.exception("Platega callback processing failed")
            raise web.HTTPInternalServerError(text="Processing failed")
        return web.Response(status=200)

    async def cryptobot_webhook(request: web.Request):
        raw = await request.read()
        signature = request.headers.get("crypto-pay-api-signature", "")
        if not settings.crypto_pay_enabled or not verify_webhook_signature(
            settings.crypto_pay_token, raw, signature
        ):
            raise web.HTTPUnauthorized(text="Unauthorized")
        try:
            update = await request.json()
            if update.get("update_type") == "invoice_paid":
                await process_cryptobot_invoice(update.get("payload") or {}, bot)
        except ValueError as exc:
            log.warning("Rejected Crypto Pay webhook: %s", exc)
            raise web.HTTPBadRequest(text="Invalid callback")
        except Exception:
            log.exception("Crypto Pay webhook processing failed")
            raise web.HTTPInternalServerError(text="Processing failed")
        return web.Response(status=200)

    app.router.add_post(settings.platega_webhook_path, platega_webhook)
    if settings.crypto_pay_enabled:
        app.router.add_post(settings.crypto_pay_webhook_path, cryptobot_webhook)
    app.router.add_get("/health", lambda request: web.json_response({"status": "ok"}))
    return app
