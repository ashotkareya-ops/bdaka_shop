import asyncio
import logging

from config.settings import settings
from database.engine import SessionLocal
from services.supplier_sync import sync_sandromania_catalog

log = logging.getLogger(__name__)
SYNC_INTERVAL_SECONDS = 4 * 60 * 60


async def supplier_price_sync_loop():
    """Sync supplier retail prices and stock on startup and every four hours."""
    while True:
        if settings.sandromania_enabled:
            try:
                async with SessionLocal() as session:
                    result = await sync_sandromania_catalog(session)
                log.info(
                    "Scheduled Sandromania sync completed: received=%s updated=%s created=%s skipped=%s",
                    result.get("received", 0),
                    result.get("updated", 0),
                    result.get("created", 0),
                    result.get("skipped", 0),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Scheduled Sandromania price sync failed; keeping previous shop prices")
        else:
            log.info("Sandromania price sync skipped: API credentials are not configured")

        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
