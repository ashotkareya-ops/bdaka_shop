from database.engine import SessionLocal

class DatabaseMiddleware:
    async def __call__(self, handler, event, data):
        async with SessionLocal() as session:
            data["session"] = session
            return await handler(event, data)
