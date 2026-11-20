from suppliers.sandromania.client import SandromaniaClient

async def fetch_catalog():
    return await SandromaniaClient().get_products()
