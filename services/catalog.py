from sqlalchemy import select
from database.models.category import Category
from database.models.product import Product

async def get_categories(session):
    return (await session.scalars(select(Category).where(Category.is_active == True))).all()

async def get_products(session, category_id):
    return (await session.scalars(select(Product).where(
        Product.category_id == category_id, Product.is_active == True
    ))).all()
