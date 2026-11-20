from sqlalchemy import select
from database.models.user import User

async def get_user_by_telegram_id(session, telegram_id):
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))
