from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select
from database.models.user import User
from database.models.transaction import Transaction

router = Router()

@router.callback_query(F.data == "profile:transactions")
async def transactions(callback: CallbackQuery, session):
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    rows = (await session.scalars(
        select(Transaction).where(Transaction.user_id == user.id)
        .order_by(Transaction.created_at.desc()).limit(15)
    )).all()
    if not rows:
        await callback.message.answer("Транзакций пока нет.")
    else:
        lines = ["💳 <b>Транзакции</b>"]
        for row in rows:
            lines.append(f"{row.amount:+.2f} ₽ — {row.description}")
        await callback.message.answer("\n".join(lines))
    await callback.answer()
