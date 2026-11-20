from sqlalchemy import select
from database.models.order import Order

async def list_user_orders(session, user_id, limit=20):
    return (await session.scalars(select(Order).where(
        Order.user_id == user_id
    ).order_by(Order.created_at.desc()).limit(limit))).all()
