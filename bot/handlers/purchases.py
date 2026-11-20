from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select
from database.models.user import User
from database.models.order import Order
from database.models.product import Product

router = Router()

@router.callback_query(F.data == "profile:purchases")
async def purchases(callback: CallbackQuery, session):
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    rows = (await session.execute(
        select(Order, Product).join(Product, Order.product_id == Product.id)
        .where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(15)
    )).all()
    if not rows:
        await callback.message.answer("Покупок пока нет.")
    else:
        lines = ["📦 <b>Последние покупки</b>"]
        for order, product in rows:
            lines.append(f"#{order.id} — {product.name} — {order.price:.2f} ₽ — {order.status}")
        await callback.message.answer("\n".join(lines))
    await callback.answer()
