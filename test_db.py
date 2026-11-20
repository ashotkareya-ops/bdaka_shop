import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy.engine import make_url
import asyncpg

load_dotenv()
url = make_url(os.environ["DATABASE_URL"])

async def main():
    print("Проверка подключения asyncpg...")
    try:
        conn = await asyncpg.connect(
            host=url.host,
            port=url.port or 5432,
            user=url.username,
            password=url.password,
            database=url.database,
            timeout=10
        )
        result = await conn.fetchrow(
            "SELECT current_database(), current_user"
        )
        print("УСПЕХ:", result)
        await conn.close()
    except Exception as e:
        print("ОШИБКА:", type(e).__name__, str(e))

asyncio.run(main())
