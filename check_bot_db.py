import asyncio
from sqlalchemy import text
from services.partner_order_worker import SessionLocal

async def main():
    async with SessionLocal() as session:
        result = await session.execute(text("""
            SELECT
                current_database() AS db,
                current_schema() AS schema,
                current_user AS db_user,
                current_setting('search_path') AS search_path,
                to_regclass('public.partner_order_jobs') AS jobs_table,
                to_regclass('public.orders') AS orders_table
        """))
        print(dict(result.mappings().one()))

asyncio.run(main())
