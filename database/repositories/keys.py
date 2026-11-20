from sqlalchemy import select
from database.models.digital_key import DigitalKey

async def count_available_keys(session, product_id):
    from sqlalchemy import func
    return await session.scalar(select(func.count()).select_from(DigitalKey).where(
        DigitalKey.product_id == product_id, DigitalKey.status == "AVAILABLE"
    ))
