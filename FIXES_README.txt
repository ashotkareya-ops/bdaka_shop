Исправления тестовой сборки BDAKA SHOP

1. database/engine.py автоматически нормализует DATABASE_URL:
   - postgresql:// -> postgresql+asyncpg://
   - sslmode=require -> ssl=require
   - удаляет неподдерживаемый asyncpg параметр channel_binding.
   Поэтому обычный connection string из Neon также будет работать.
2. services/partner_order_worker.py использует явную схему public для partner_order_jobs.
3. .env в этой сборке содержит тестовые значения из присланного архива; DATABASE_URL приведён к asyncpg.

Перед публикацией/передачей архива:
- замените BOT_TOKEN, ключи Sandromania, Crypto Pay, Platega и пароль Neon;
- не отправляйте этот .env партнёрам;
- запускайте только один polling-процесс Telegram-бота с данным BOT_TOKEN.

Проверка:
  python -c "from config.settings import settings; print(settings.database_url.split('://')[0])"
  python .\check_bot_db.py
  python main.py

Ожидаемая база: neondb; таблицы public.partner_order_jobs и public.orders.
