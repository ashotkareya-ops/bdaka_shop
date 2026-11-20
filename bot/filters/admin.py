from aiogram.filters import Filter
from config.settings import settings

class AdminFilter(Filter):
    async def __call__(self, event):
        user = getattr(event, "from_user", None)
        return bool(user and user.id in settings.admins)
