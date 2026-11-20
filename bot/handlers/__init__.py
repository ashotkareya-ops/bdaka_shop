from bot.handlers.start import router as start_router
from bot.handlers.catalog import router as catalog_router
from bot.handlers.products import router as products_router
from bot.handlers.orders import router as orders_router
from bot.handlers.profile import router as profile_router
from bot.handlers.balance import router as balance_router
from bot.handlers.purchases import router as purchases_router
from bot.handlers.transactions import router as transactions_router
from bot.handlers.useful_links import router as links_router
from bot.handlers.admin.dashboard import router as admin_router

def setup_routers(dp):
    for router in (
        start_router, catalog_router, products_router, orders_router,
        profile_router, balance_router, purchases_router, transactions_router,
        links_router, admin_router
    ):
        dp.include_router(router)
