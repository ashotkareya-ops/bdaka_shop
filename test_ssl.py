import asyncio
import os
import asyncpg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

load_dotenv()
url = make_url(os.environ["DATABASE_URL"])

async def test(ssl):
    print(f"\nПроверка SSL={ssl}")
    try:
        conn = await asyncpg.connect(
            host="127.0.0.1",
            port=5432,
            user=url.username,
            password=url.password,
            database=url.database,
            ssl=ssl,
            timeout=10
        )
        print("УСПЕХ:", await conn.fetchval("SELECT version()"))
        await conn.close()
    except Exception as e:
        print("ОШИБКА:", repr(e))

async def main():
    await test(False)
    await test(True)

asyncio.run(main())
