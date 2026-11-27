"""Consumes partner API orders through the existing BDAKA SHOP fulfilment flow.

Safety rule: never automatically retry an order after fulfil_paid_order has started.
A supplier request may have succeeded even if the bot timed out or restarted.
"""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import text

from database.engine import SessionLocal
from services.payment_service import fulfill_paid_order

log = logging.getLogger(__name__)


async def _claim_job():
    """Atomically claim one pending job; SKIP LOCKED supports multiple bot workers."""
    async with SessionLocal() as session:
        async with session.begin():
            result = await session.execute(text("""
                WITH next_job AS (
                    SELECT id
                    FROM public.partner_order_jobs
                    WHERE status = 'PENDING'
                    ORDER BY created_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE public.partner_order_jobs AS job
                SET status = 'PROCESSING', updated_at = :now, last_error = NULL
                FROM next_job
                WHERE job.id = next_job.id
                RETURNING job.id, job.order_id
            """), {"now": datetime.utcnow()})
            row = result.mappings().first()
            return dict(row) if row else None


async def _finish_job(job_id: int, order_id: int, error: str | None = None):
    """Mirror the order's real state; PROCESSING is not a failed order."""
    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT status FROM orders WHERE id = :order_id"),
            {"order_id": order_id},
        )
        order_status = result.scalar_one_or_none()

        if order_status == "COMPLETED":
            job_status = "COMPLETED"
            last_error = None
        elif order_status == "PROCESSING":
            # The supplier may have accepted the order but not delivered the code yet.
            # Keep it out of the PENDING queue to prevent duplicate supplier purchases.
            job_status = "PROCESSING"
            last_error = error or "Ожидается завершение поставки; автоматический повтор отключён"
        else:
            # Includes missing order, PAID-but-not-fulfilled, FAILED and CANCELLED.
            job_status = "NEEDS_REVIEW"
            last_error = error or f"Требуется проверка заказа; текущий статус: {order_status or 'NOT_FOUND'}"

        await session.execute(text("""
            UPDATE partner_order_jobs
            SET status = :status, updated_at = :now, last_error = :last_error
            WHERE id = :job_id
        """), {
            "status": job_status,
            "now": datetime.utcnow(),
            "last_error": last_error[:1000] if last_error else None,
            "job_id": job_id,
        })
        await session.commit()
        log.info("Partner job %s for order %s -> %s", job_id, order_id, job_status)


async def partner_order_worker(bot, poll_interval: float = 2.0):
    """Run inside the existing Telegram bot process; never retries uncertain purchases."""
    log.info("Partner order worker started")
    while True:
        try:
            job = await _claim_job()
            if not job:
                await asyncio.sleep(poll_interval)
                continue

            order_id = int(job["order_id"])
            job_id = int(job["id"])
            error = None
            try:
                await fulfill_paid_order(
                    order_id, bot, send_telegram_delivery=False
                )
            except Exception as exc:
                # The supplier call may have succeeded before an exception/timeout.
                # Do not reset this job to PENDING and do not purchase again blindly.
                log.exception("Partner order fulfilment failed: order_id=%s", order_id)
                error = f"Ошибка выполнения: {type(exc).__name__}"

            await _finish_job(job_id, order_id, error)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Partner order worker cycle failed")
            await asyncio.sleep(poll_interval)
