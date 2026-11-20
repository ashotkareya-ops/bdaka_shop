from aiogram.types import (
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
)

BUYER_COMMANDS = [
    BotCommand(command="start", description="Открыть главное меню магазина"),
    BotCommand(command="catalog", description="Открыть каталог товаров"),
    BotCommand(command="profile", description="Мой профиль и баланс"),
    BotCommand(command="balance", description="Пополнить баланс"),
    BotCommand(command="purchases", description="Мои покупки и заказы"),
    BotCommand(command="transactions", description="История операций"),
    BotCommand(command="links", description="Полезные ссылки и поддержка"),
    BotCommand(command="help", description="Список команд покупателя"),
]

ADMIN_COMMANDS = BUYER_COMMANDS + [
    BotCommand(command="admin", description="Панель администратора"),
    BotCommand(command="products", description="Список товаров и их ID"),
    BotCommand(command="addcategory", description="Создать категорию"),
    BotCommand(command="addproduct", description="Добавить товар"),
    BotCommand(command="addkey", description="Добавить CDK на склад"),
    BotCommand(command="credit", description="Начислить баланс пользователю"),
    BotCommand(command="orders", description="Последние заказы"),
    BotCommand(command="linksupplier", description="Связать товар с поставщиком"),
    BotCommand(command="supplierbalance", description="Баланс Sandromania"),
    BotCommand(command="supplierproducts", description="Информация о каталоге поставщика"),
    BotCommand(command="syncsupplier", description="Синхронизировать каталог"),
    BotCommand(command="setprice", description="Установить розничную цену"),
    BotCommand(command="setmarkup", description="Установить наценку поставщика"),
]

async def register_bot_commands(bot, admin_ids: set[int]):
    # Default command menu is the buyer-facing list.
    await bot.set_my_commands(BUYER_COMMANDS, scope=BotCommandScopeDefault())
    # Admins get an expanded list only in their own private chat.
    for admin_id in sorted(admin_ids):
        await bot.set_my_commands(
            ADMIN_COMMANDS,
            scope=BotCommandScopeChat(chat_id=admin_id),
        )
