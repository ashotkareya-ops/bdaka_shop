from suppliers.sandromania.client import SandromaniaClient

async def buy_one(product_id: int, idempotency_key: str):
    return await SandromaniaClient().purchase_and_wait(product_id, idempotency_key)
