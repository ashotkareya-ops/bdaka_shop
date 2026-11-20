import logging
from aiohttp import web
from config.settings import settings
from services.payment_service import verify_callback_headers, process_platega_callback

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

    app.router.add_post(settings.platega_webhook_path, platega_webhook)
    app.router.add_get("/health", lambda request: web.json_response({"status": "ok"}))
    return app
