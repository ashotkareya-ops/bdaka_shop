from sqlalchemy import select
from database.models.payment import Payment

async def get_payment_by_external_id(session, external_id):
    return await session.scalar(select(Payment).where(Payment.external_id == external_id))
