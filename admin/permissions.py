from config.settings import settings

def is_admin_id(telegram_id: int) -> bool:
    return telegram_id in settings.admins
