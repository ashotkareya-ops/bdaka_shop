from sqlalchemy import select
from database.models.product import Product

async def list_products(session, category_id):
    return (await session.scalars(select(Product).where(
        Product.category_id == category_id, Product.is_active == True
    ))).all()
